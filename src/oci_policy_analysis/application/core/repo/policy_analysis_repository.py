##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# data_repo.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import collections
import csv
import hashlib
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

# Third-party imports
from oci import config, pagination
from oci.auth.signers import (
    InstancePrincipalsSecurityTokenSigner,
    SecurityTokenSigner,
    get_resource_principals_signer,
)
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.identity import IdentityClient
from oci.identity_domains import IdentityDomainsClient
from oci.identity_domains.models import DynamicResourceGroup
from oci.loggingsearch import LogSearchClient
from oci.loggingsearch.models import SearchLogsDetails, SearchResult
from oci.resource_search import ResourceSearchClient
from oci.resource_search.models import StructuredSearchDetails
from oci.signer import load_private_key_from_file

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.models.models import (
    AdmitStatement,
    BasePolicy,
    BasePolicyStatement,
    Compartment,
    DefineStatement,
    DynamicGroup,
    DynamicGroupSearch,
    EndorseStatement,
    Group,
    GroupSearch,
    PolicySearch,
    Principal,
    RegularPolicyStatement,
    User,
    UserSearch,
)
from oci_policy_analysis.application.core.parser.condition_structure import (
    format_condition_structure_summary,
    parse_condition_structure,
)
from oci_policy_analysis.application.core.parser.policy_statement_normalizer import PolicyStatementNormalizer
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.tag_based_policy_service import (
    POLICY_TAG_FILTER_FIELDS,
    TAG_FILTER_FIELDS,
    TagBasedPolicyService,
)

# Global logger for this module
logger = get_logger(component='core.repo.policy_analysis_repository')

# Constants
THREADS = 6

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'

# For MCP-specific JSON
VALID_VERBS = {'inspect', 'read', 'use', 'manage'}


def _resolve_compliance_output_csv(dir_path: str, filename: str, *, required: bool = True) -> str | None:
    """Return a legacy or directory-prefixed CIS Compliance output CSV path."""

    output_dir = Path(dir_path)
    candidates = (
        output_dir / filename,
        output_dir / f'{output_dir.name}_{filename}',
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    if required:
        expected = ', '.join(str(candidate) for candidate in candidates)
        raise FileNotFoundError(f'Compliance output file not found. Expected one of: {expected}')
    return None


def _open_optional_compliance_csv(path: str | None):
    """Open a compliance CSV, or provide an empty CSV stream when it is optional."""
    return open(path, encoding='utf-8') if path else StringIO('')


class PolicyAnalysisRepository:
    """
    This is the main data repository for Policy, Identity, and Compartment data

    During initialization, the entire compartment hierarchy and policy tree is loaded into a central JSON dictionary.
    This central dictionary is then referenced by functions that filter and return a subset of information for display.
    Parsing, additional analysis, and import/export are made available by additional functions exposed.

    Loading of data starts from `load_policies_and_compartments`, which loads all compartments and policies recursively

    Filtering functions return lists of dataclass objects defined in models.py for easy consumption by UI or CLI layers.

    See `filter_policy_statements` for an example of filtering and returning PolicyStatement objects.
    """

    def _api_call_with_logging(self, label, fn, *args, **kwargs):
        """Wrap OCI API call for logging+timing at INFO or CRITICAL based on settings."""

        # TODO: https://docs.oracle.com/en-us/iaas/tools/python/latest/exceptions.html

        log_critical = False
        try:
            if self.settings and isinstance(self.settings, dict):
                log_critical = self.settings.get('always_log_api_calls', False)
        except Exception:
            pass
        level_func = logger.critical if log_critical else logger.info

        t0 = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            elapsed = time.perf_counter() - t0
            # Print more details about the API call on success
            level_func(
                f'[API] {label} ({getattr(fn, "__name__", repr(fn))}) succeeded in {elapsed:.2f}s — args={args} kwargs={kwargs}'
            )
            return result
        except ServiceError as se:
            if getattr(self, '_cleanup_reload_api_errors', None) is not None:
                self._cleanup_reload_api_errors.append(label)
            elapsed = time.perf_counter() - t0
            # Print detailed ServiceError info
            logger.error(
                f'[API] {label} ({getattr(fn, "__name__", repr(fn))}) ServiceError after {elapsed:.2f}s: code={se.code} status={se.status} message={se.message} args={args}, kwargs={kwargs}'
            )
            raise
        except Exception as e:
            if getattr(self, '_cleanup_reload_api_errors', None) is not None:
                self._cleanup_reload_api_errors.append(label)
            elapsed = time.perf_counter() - t0
            # Print more details on generic exception
            logger.error(
                f'[API] {label} ({getattr(fn, "__name__", repr(fn))}) failed after {elapsed:.2f}s: {e} args={args}, kwargs={kwargs}'
            )
            raise

    def _iter_legacy_subject_strings(self, stmt: RegularPolicyStatement) -> list[str]:
        """Flatten legacy ``subject`` representations into searchable strings."""
        subjects = stmt.get('subject', [])
        flattened: list[str] = []
        if isinstance(subjects, str):
            return [subjects]
        if not isinstance(subjects, list):
            return flattened

        for subj in subjects:
            if isinstance(subj, tuple | list):
                parts = [str(p) for p in subj if p is not None and str(p).strip()]
                if parts:
                    flattened.append('/'.join(parts))
                    flattened.extend(parts)
            elif subj is not None:
                flattened.append(str(subj))
        return flattened

    def _subject_token_matches_statement(self, stmt: RegularPolicyStatement, token: str) -> bool:
        """Principal-first subject matching with legacy fallback.

        A token matches if it appears (case-insensitive substring) in any of:
        principal domain/name/ocid/principal_key/display_name.
        If principals are unavailable, fallback to flattened legacy ``subject``.
        """
        needle = (token or '').strip().casefold()
        if not needle:
            return True

        principals = stmt.get('principals', [])
        if isinstance(principals, list) and principals:
            for principal in principals:
                if not isinstance(principal, dict):
                    continue
                for field in ('domain_name', 'name', 'ocid', 'principal_key', 'display_name'):
                    value = principal.get(field)
                    if isinstance(value, str) and needle in value.casefold():
                        return True

        # Legacy fallback for older statements missing principals
        for legacy_text in self._iter_legacy_subject_strings(stmt):
            if needle in str(legacy_text).casefold():
                return True
        return False

    @staticmethod
    def _normalize_principal_field(value: object) -> str:
        """Return a normalized principal field value for matching.

        Args:
            value: Raw principal value from a statement or filter.

        Returns:
            str: Trimmed case-folded value, or an empty string for missing values.
        """
        if value is None:
            return ''
        return str(value).strip().casefold()

    def _statement_principal_keys(self, stmt: RegularPolicyStatement) -> set[str]:
        """Return normalized principal keys available on a policy statement.

        Args:
            stmt: Policy statement to inspect.

        Returns:
            set[str]: Normalized canonical principal keys.
        """
        keys: set[str] = set()

        singular_key = self._normalize_principal_field(stmt.get('principal_key'))
        if singular_key:
            keys.add(singular_key)

        raw_keys = stmt.get('principal_keys', [])
        if isinstance(raw_keys, list):
            for key in raw_keys:
                normalized = self._normalize_principal_field(key)
                if normalized:
                    keys.add(normalized)
        elif raw_keys:
            normalized = self._normalize_principal_field(raw_keys)
            if normalized:
                keys.add(normalized)

        principals = stmt.get('principals', [])
        for principal in principals if isinstance(principals, list) else []:
            if not isinstance(principal, dict):
                continue
            principal_key = self._normalize_principal_field(principal.get('principal_key'))
            if principal_key:
                keys.add(principal_key)

        return keys

    @staticmethod
    def _identity_matches(
        *,
        actual_domain: object | None,
        actual_name: object | None,
        filter_domain: object | None,
        filter_name: object | None,
    ) -> bool:
        """Return whether identity domain/name values match case-insensitively.

        Args:
            actual_domain: Domain value from loaded identity data.
            actual_name: Name value from loaded identity data.
            filter_domain: Domain value from the caller.
            filter_name: Name value from the caller.

        Returns:
            bool: True when both domain and name match.
        """
        actual_domain_str = str(actual_domain or 'Default').casefold()
        actual_name_str = str(actual_name or '').casefold()
        filter_domain_str = str(filter_domain or 'Default').casefold()
        filter_name_str = str(filter_name or '').casefold()
        return bool(actual_name_str and filter_name_str) and (
            actual_domain_str == filter_domain_str and actual_name_str == filter_name_str
        )

    def _group_principal_keys(
        self,
        *,
        domain_name: object | None = None,
        group_name: object | None = None,
        group_ocid: object | None = None,
    ) -> set[str]:
        """Return equivalent named and ID-based principal keys for a group.

        Args:
            domain_name: Optional group identity domain.
            group_name: Optional group name.
            group_ocid: Optional group OCID.

        Returns:
            set[str]: Canonical group and group-id keys that refer to the same group.
        """
        keys: set[str] = set()
        domain = str(domain_name or 'Default').strip()
        name = str(group_name or '').strip()
        ocid = str(group_ocid or '').strip()

        if name:
            keys.add(calculate_principal_key('group', domain, name))
        if ocid:
            keys.add(f'group-id:{ocid}')

        for group in self.groups:
            if not isinstance(group, dict):
                continue
            group_matches_ocid = bool(ocid and str(group.get('group_ocid') or '').casefold() == ocid.casefold())
            group_matches_name = self._identity_matches(
                actual_domain=group.get('domain_name'),
                actual_name=group.get('group_name'),
                filter_domain=domain,
                filter_name=name,
            )
            if not (group_matches_ocid or group_matches_name):
                continue
            resolved_name = str(group.get('group_name') or '').strip()
            if resolved_name:
                keys.add(calculate_principal_key('group', group.get('domain_name') or 'Default', resolved_name))
            resolved_ocid = str(group.get('group_ocid') or '').strip()
            if resolved_ocid:
                keys.add(f'group-id:{resolved_ocid}')

        return keys

    def _dynamic_group_principal_keys(
        self,
        *,
        domain_name: object | None = None,
        dynamic_group_name: object | None = None,
        dynamic_group_ocid: object | None = None,
    ) -> set[str]:
        """Return equivalent named and ID-based principal keys for a dynamic group.

        Args:
            domain_name: Optional dynamic group identity domain.
            dynamic_group_name: Optional dynamic group name.
            dynamic_group_ocid: Optional dynamic group OCID.

        Returns:
            set[str]: Canonical dynamic-group and dynamic-group-id keys for the same dynamic group.
        """
        keys: set[str] = set()
        domain = str(domain_name or 'Default').strip()
        name = str(dynamic_group_name or '').strip()
        ocid = str(dynamic_group_ocid or '').strip()

        if name:
            keys.add(calculate_principal_key('dynamic-group', domain, name))
        if ocid:
            keys.add(f'dynamic-group-id:{ocid}')

        for dynamic_group in self.dynamic_groups:
            if not isinstance(dynamic_group, dict):
                continue
            dg_matches_ocid = bool(
                ocid and str(dynamic_group.get('dynamic_group_ocid') or '').casefold() == ocid.casefold()
            )
            dg_matches_name = self._identity_matches(
                actual_domain=dynamic_group.get('domain_name'),
                actual_name=dynamic_group.get('dynamic_group_name'),
                filter_domain=domain,
                filter_name=name,
            )
            if not (dg_matches_ocid or dg_matches_name):
                continue
            resolved_name = str(dynamic_group.get('dynamic_group_name') or '').strip()
            if resolved_name:
                keys.add(
                    calculate_principal_key(
                        'dynamic-group', dynamic_group.get('domain_name') or 'Default', resolved_name
                    )
                )
            resolved_ocid = str(dynamic_group.get('dynamic_group_ocid') or '').strip()
            if resolved_ocid:
                keys.add(f'dynamic-group-id:{resolved_ocid}')

        return keys

    def _user_principal_keys(
        self,
        *,
        domain_name: object | None = None,
        user_name: object | None = None,
        user_ocid: object | None = None,
    ) -> set[str]:
        """Return user principal keys and group principals reachable from a user.

        Args:
            domain_name: Optional user identity domain.
            user_name: Optional user name.
            user_ocid: Optional user OCID.

        Returns:
            set[str]: User keys plus group/group-id keys for loaded memberships.
        """
        keys: set[str] = set()
        domain = str(domain_name or 'Default').strip()
        name = str(user_name or '').strip()
        ocid = str(user_ocid or '').strip()

        if name:
            keys.add(calculate_principal_key('user', domain, name))
        if ocid:
            keys.add(f'user-id:{ocid}')

        for user in self.users:
            if not isinstance(user, dict):
                continue
            user_matches_ocid = bool(ocid and str(user.get('user_ocid') or '').casefold() == ocid.casefold())
            user_matches_name = self._identity_matches(
                actual_domain=user.get('domain_name'),
                actual_name=user.get('user_name'),
                filter_domain=domain,
                filter_name=name,
            )
            if not (user_matches_ocid or user_matches_name):
                continue
            resolved_name = str(user.get('user_name') or '').strip()
            if resolved_name:
                keys.add(calculate_principal_key('user', user.get('domain_name') or 'Default', resolved_name))
            resolved_ocid = str(user.get('user_ocid') or '').strip()
            if resolved_ocid:
                keys.add(f'user-id:{resolved_ocid}')
            for group_ocid in user.get('groups', []) or []:
                keys.update(self._group_principal_keys(group_ocid=group_ocid))

        return keys

    def _equivalent_principal_keys_for_key(self, principal_key: str) -> set[str]:
        """Return all known equivalent principal keys for a canonical key.

        Args:
            principal_key: Canonical principal key supplied by a caller or parsed
                from a statement.

        Returns:
            set[str]: Equivalent keys, including the original key.
        """
        raw_key = str(principal_key or '').strip()
        if not raw_key:
            return set()

        keys: set[str] = {raw_key}
        if ':' not in raw_key:
            return keys

        principal_type, payload = raw_key.split(':', 1)
        principal_type = principal_type.strip()
        payload = payload.strip()

        if principal_type == 'group-id':
            keys.update(self._group_principal_keys(group_ocid=payload))
        elif principal_type == 'group' and '/' in payload:
            domain, name = payload.split('/', 1)
            keys.update(self._group_principal_keys(domain_name=domain, group_name=name))
        elif principal_type == 'dynamic-group-id':
            keys.update(self._dynamic_group_principal_keys(dynamic_group_ocid=payload))
        elif principal_type == 'dynamic-group' and '/' in payload:
            domain, name = payload.split('/', 1)
            keys.update(self._dynamic_group_principal_keys(domain_name=domain, dynamic_group_name=name))
        elif principal_type == 'user-id':
            keys.update(self._user_principal_keys(user_ocid=payload))
        elif principal_type == 'user' and '/' in payload:
            domain, name = payload.split('/', 1)
            keys.update(self._user_principal_keys(domain_name=domain, user_name=name))

        return keys

    def _equivalent_principal_keys_for_selector(self, selector: Principal) -> set[str]:
        """Return equivalent principal keys for a structured principal selector.

        Args:
            selector: Principal selector from ``PolicySearch``.

        Returns:
            set[str]: Equivalent keys derived from selector fields and identity data.
        """
        if not isinstance(selector, dict):
            return set()

        keys: set[str] = set()
        principal_key = str(selector.get('principal_key') or '').strip()
        if principal_key:
            keys.update(self._equivalent_principal_keys_for_key(principal_key))

        principal_type = str(selector.get('principal_type') or '').strip()
        domain_name = selector.get('domain_name')
        name = selector.get('name')
        ocid = selector.get('ocid')

        if principal_type == 'group':
            keys.update(self._group_principal_keys(domain_name=domain_name, group_name=name, group_ocid=ocid))
        elif principal_type == 'group-id':
            keys.update(self._group_principal_keys(group_ocid=ocid or name))
        elif principal_type == 'dynamic-group':
            keys.update(
                self._dynamic_group_principal_keys(
                    domain_name=domain_name,
                    dynamic_group_name=name,
                    dynamic_group_ocid=ocid,
                )
            )
        elif principal_type == 'dynamic-group-id':
            keys.update(self._dynamic_group_principal_keys(dynamic_group_ocid=ocid or name))
        elif principal_type == 'user':
            keys.update(self._user_principal_keys(domain_name=domain_name, user_name=name, user_ocid=ocid))
        elif principal_type == 'user-id':
            keys.update(self._user_principal_keys(user_ocid=ocid or name))

        return keys

    def _normalized_equivalent_principal_keys_for_key(self, principal_key: str) -> set[str]:
        """Return normalized equivalent principal keys for matching.

        Args:
            principal_key: Principal key to expand and normalize.

        Returns:
            set[str]: Case-folded equivalent keys.
        """
        return {
            normalized
            for key in self._equivalent_principal_keys_for_key(principal_key)
            if (normalized := self._normalize_principal_field(key))
        }

    def _normalized_equivalent_statement_principal_keys(self, stmt: RegularPolicyStatement) -> set[str]:
        """Return normalized statement principal keys with identity equivalents.

        Args:
            stmt: Policy statement to inspect.

        Returns:
            set[str]: Case-folded statement principal keys and equivalents.
        """
        keys: set[str] = set()
        for principal_key in self._statement_principal_keys(stmt):
            keys.update(self._normalized_equivalent_principal_keys_for_key(principal_key))
        return keys

    def _principal_key_matches_statement(self, stmt: RegularPolicyStatement, principal_key: str) -> bool:
        """Return whether a statement matches a canonical principal key.

        Args:
            stmt: Policy statement to inspect.
            principal_key: Canonical principal key filter value.

        Returns:
            bool: True when the statement contains the requested principal key.
        """
        normalized_keys = self._normalized_equivalent_principal_keys_for_key(principal_key)
        if not normalized_keys:
            return True
        return bool(normalized_keys & self._normalized_equivalent_statement_principal_keys(stmt))

    @staticmethod
    def _normalize_condition_value(value: object) -> str:
        """Normalize a condition value for case-insensitive evidence matching."""
        return str(value or '').strip().strip('\'"').casefold()

    def _condition_atoms_for_statement(self, stmt: RegularPolicyStatement) -> list[dict[str, object]]:
        """Return parsed condition atoms, parsing raw conditions as a fallback."""
        structure = stmt.get('where_clause_structure') or stmt.get('where_clause') or {}
        if isinstance(structure, dict):
            atoms = structure.get('atoms')
            if isinstance(atoms, list):
                return [atom for atom in atoms if isinstance(atom, dict)]

        parsed = parse_condition_structure(str(stmt.get('conditions') or ''))
        atoms = parsed.get('atoms') if isinstance(parsed, dict) else []
        return [atom for atom in atoms if isinstance(atom, dict)] if isinstance(atoms, list) else []

    def _condition_atom_with_value(
        self, atoms: list[dict[str, object]], left: str, expected: str
    ) -> dict[str, object] | None:
        """Return matching parsed condition atom for ``left`` with ``expected``."""
        expected_value = self._normalize_condition_value(expected)
        if not expected_value:
            return None
        expected_left = left.casefold()
        for atom in atoms:
            atom_left = self._normalize_principal_field(atom.get('normalized_left') or atom.get('left'))
            if atom_left != expected_left:
                continue
            raw_right = str(atom.get('right') or '')
            right_values = [self._normalize_condition_value(value) for value in raw_right.split(',')]
            if expected_value in right_values:
                return atom
        return None

    def _condition_has_value(self, atoms: list[dict[str, object]], left: str, expected: str) -> bool:
        """Return whether parsed condition atoms contain ``left`` with ``expected``."""
        return self._condition_atom_with_value(atoms, left, expected) is not None

    def _raw_condition_has_value(self, stmt: RegularPolicyStatement, left: str, expected: str) -> bool:
        """Best-effort fallback for older cache rows without parsed condition atoms."""
        expected_value = self._normalize_condition_value(expected)
        if not expected_value:
            return True
        conditions = str(stmt.get('conditions') or '').casefold()
        return left.casefold() in conditions and expected_value in conditions

    def _condition_principal_match_details(
        self,
        stmt: RegularPolicyStatement,
        selector: Principal,
        *,
        required_checks: list[tuple[str, str]],
        confidence_identity_lefts: set[str],
        match_confidence_reason: str,
        allow_type_only: bool = False,
    ) -> dict[str, object] | None:
        """Match condition-backed principal selectors and return evidence details."""
        subject_type = self._normalize_principal_field(stmt.get('subject_type'))
        if subject_type not in {'any-user', 'any-group'}:
            return None

        checks = [(left, self._normalize_principal_field(expected)) for left, expected in required_checks]
        checks = [(left, expected) for left, expected in checks if expected]
        if not checks and not allow_type_only:
            return None

        atoms = self._condition_atoms_for_statement(stmt)
        used_parsed_atoms = bool(atoms)
        identity_evidence: list[dict[str, object]] = []

        for left, expected in checks:
            if used_parsed_atoms:
                atom = self._condition_atom_with_value(atoms, left, expected)
                if atom is None:
                    return None
                identity_evidence.append(atom)
            elif not self._raw_condition_has_value(stmt, left, expected):
                return None

        if not used_parsed_atoms:
            return {
                'match_confidence': 'identity_match_unparsed_conditions',
                'match_confidence_reason': match_confidence_reason,
                'principal_evidence': [],
                'residual_conditions': [],
            }

        residual_atoms = [
            atom
            for atom in atoms
            if self._normalize_principal_field(atom.get('normalized_left') or atom.get('left'))
            not in confidence_identity_lefts
        ]
        if residual_atoms:
            confidence = 'identity_match_with_residual'
            reason = match_confidence_reason
        else:
            confidence = 'exact'
            reason = match_confidence_reason
        return {
            'match_confidence': confidence,
            'match_confidence_reason': reason,
            'principal_evidence': identity_evidence,
            'residual_conditions': residual_atoms,
        }

    def _resource_principal_match_details(
        self, stmt: RegularPolicyStatement, selector: Principal
    ) -> dict[str, object] | None:
        """Match resource-principal selectors and return confidence/evidence details."""
        resource_type = self._normalize_principal_field(selector.get('resource_type') or selector.get('type'))
        principal_ocid = self._normalize_principal_field(selector.get('ocid') or selector.get('resource_ocid'))
        compartment_ocid = self._normalize_principal_field(
            selector.get('compartment_ocid') or selector.get('resource_compartment_ocid')
        )
        if not any([resource_type, principal_ocid, compartment_ocid]):
            return None
        return self._condition_principal_match_details(
            stmt,
            selector,
            required_checks=[
                ('request.principal.type', resource_type),
                ('request.principal.id', principal_ocid),
                ('request.principal.compartment.id', compartment_ocid),
            ],
            confidence_identity_lefts={
                'request.principal.type',
                'request.principal.id',
                'request.principal.compartment.id',
            },
            match_confidence_reason=(
                'Matched requested request.principal.* identity evidence, but residual where-clause conditions remain '
                'and were not evaluated as part of principal identity.'
            ),
        )

    def _oke_workload_identity_match_details(
        self, stmt: RegularPolicyStatement, selector: Principal
    ) -> dict[str, object] | None:
        """Match OKE workload identity selectors and return confidence/evidence details."""
        namespace = self._normalize_principal_field(selector.get('workload_namespace'))
        service_account = self._normalize_principal_field(selector.get('workload_service_account'))
        cluster_id = self._normalize_principal_field(selector.get('workload_cluster_id'))
        allow_type_only = bool(self._normalize_principal_field(selector.get('principal_type')))
        if not any([namespace, service_account, cluster_id]) and not allow_type_only:
            return None
        return self._condition_principal_match_details(
            stmt,
            selector,
            required_checks=[
                ('request.principal.type', 'workload'),
                ('request.principal.namespace', namespace),
                ('request.principal.service_account', service_account),
                ('request.principal.cluster_id', cluster_id),
            ],
            confidence_identity_lefts={
                'request.principal.type',
                'request.principal.namespace',
                'request.principal.service_account',
                'request.principal.cluster_id',
            },
            match_confidence_reason=(
                'Matched requested OKE workload identity evidence in the where-clause; residual conditions, if any, '
                'were not evaluated as part of workload identity identity matching.'
            ),
            allow_type_only=True,
        )

    def _resource_principal_match_confidence(self, stmt: RegularPolicyStatement, selector: Principal) -> str | None:
        """Match resource-principal selectors against any-user/any-group condition evidence."""
        details = self._resource_principal_match_details(stmt, selector)
        if not details:
            return None
        return str(details.get('match_confidence') or '')

    def _principal_match_details(self, stmt: RegularPolicyStatement, selector: Principal) -> dict[str, object] | None:
        """Return match details for a structured principal selector, or None when unmatched."""
        principal_type = self._normalize_principal_field(selector.get('principal_type'))
        if principal_type in {'resource-principal', 'resource_principal', 'workload-principal', 'workload_principal'}:
            return self._resource_principal_match_details(stmt, selector)
        if principal_type in {'oke-workload-identity', 'oke_workload_identity'}:
            return self._oke_workload_identity_match_details(stmt, selector)
        if self._identity_principal_matches_statement(stmt, selector):
            return {'match_confidence': 'matched'}
        return None

    def _principal_match_confidence(self, stmt: RegularPolicyStatement, selector: Principal) -> str | None:
        """Return match confidence for a structured principal selector, or None when unmatched."""
        details = self._principal_match_details(stmt, selector)
        if not details:
            return None
        return str(details.get('match_confidence') or '')

    def _principal_matches_statement(self, stmt: RegularPolicyStatement, selector: Principal) -> bool:
        """Return whether a statement matches a structured principal selector."""
        return self._principal_match_confidence(stmt, selector) is not None

    def _identity_principal_matches_statement(self, stmt: RegularPolicyStatement, selector: Principal) -> bool:
        """Return whether a statement matches a structured principal selector.

        Args:
            stmt: Policy statement to inspect.
            selector: Principal filter value. Populated selector fields are ANDed
                for a single statement principal; multiple selectors are ORed by
                the caller.

        Returns:
            bool: True when any statement principal satisfies the selector.
        """
        if not isinstance(selector, dict):
            return False

        selector_values = {
            field: self._normalize_principal_field(selector.get(field))
            for field in ('principal_type', 'principal_key', 'domain_name', 'name', 'ocid', 'display_name')
        }
        selector_values = {field: value for field, value in selector_values.items() if value}
        if not selector_values:
            return False

        selector_keys = {
            normalized
            for key in self._equivalent_principal_keys_for_selector(selector)
            if (normalized := self._normalize_principal_field(key))
        }
        if selector_keys and selector_keys & self._normalized_equivalent_statement_principal_keys(stmt):
            return True

        principals = stmt.get('principals', [])
        for principal in principals if isinstance(principals, list) else []:
            if not isinstance(principal, dict):
                continue
            if all(
                self._normalize_principal_field(principal.get(field)) == expected
                for field, expected in selector_values.items()
            ):
                return True

        # Legacy fallback for older statements that do not have principal models.
        principal_key = selector_values.get('principal_key')
        if principal_key and not self._principal_key_matches_statement(stmt, principal_key):
            return False
        principal_type = selector_values.get('principal_type')
        if principal_type and self._normalize_principal_field(stmt.get('subject_type')) != principal_type:
            return False
        fallback_tokens = [
            value
            for field, value in selector_values.items()
            if field in {'domain_name', 'name', 'ocid', 'display_name'} and value
        ]
        return bool(fallback_tokens) and all(
            self._subject_token_matches_statement(stmt, token) for token in fallback_tokens
        )

    def __init__(self):
        self.compartments = []  # List of dicts: {id, name, parent_id, hierarchy_path, hierarchy_ocids}
        self.policies: list[BasePolicy] = []  # List of BasePolicy dicts
        self.regular_statements: list[RegularPolicyStatement] = []
        self.cross_tenancy_statements = []
        self.defined_aliases: list[DefineStatement] = []  # Store define statements as list of dict
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users: list[User] = []
        # Catalog of defined tags discovered from OCI Resource Search +
        # Identity tag APIs.
        # Shape:
        # {
        #   namespace_name: {
        #       "keys": {
        #           "key1": ["AllowedValueA", "AllowedValueB"],
        #           "key2": None,  # user supplied / no static enum list published
        #       },
        #       "compartment_ocid": "ocid1.compartment...",
        #       "compartment_path": "ROOT/Shared"
        #   }
        # }
        self.defined_tag_namespace_keys: dict[str, dict[str, Any]] = {}
        self.domain_clients = {}
        self.data_as_of = ''
        self.tenancy_ocid = None
        # OCI service clients (may be None when working offline/cache-only)
        self.identity_client = None
        self.logging_search_client = None
        self.resource_search_client = None
        self.limits_client = None
        self.identity_loaded_from_tenancy = False
        self.policies_loaded_from_tenancy = False
        self.version = 2
        self.load_all_users = True
        self.compliance_capabilities: dict[str, bool] = {}
        self.compliance_artifact_counts: dict[str, int] = {}
        # Settings controlling logging/behavior (injected by App)
        self.settings = None
        # Keep the refence data repo as a member
        # self.permission_reference_repo = ReferenceDataRepo()
        self.permission_reference_repo = None
        # self.on_policy_statements_updated = None  # Optional callback, set by UI for reload hooks
        logger.info('Initialized PolicyAnalysisRepo')
        # Create a Normalizer instance
        self.normalizer = PolicyStatementNormalizer()
        # Cached tenancy-wide policy statement limit (fetch once per run)
        self.tenancy_policy_statement_limit = None
        # Snapshot-specific limit metadata. Missing from older caches is valid.
        self.tenancy_policy_limits: dict[str, Any] = {}
        self.current_cache_name = ''

    def enrich_display_structures(self) -> None:
        """Attach parsed display structures to loaded statements and dynamic groups."""
        for statement in self.regular_statements or []:
            if not isinstance(statement, dict):
                continue
            conditions = str(statement.get('conditions') or '').strip()
            if 'where_clause_structure' not in statement:
                structure = parse_condition_structure(conditions)
                statement['where_clause_structure'] = structure
                statement['where_clause'] = structure
            elif 'where_clause' not in statement and isinstance(statement.get('where_clause_structure'), dict):
                statement['where_clause'] = statement['where_clause_structure']
            structure = statement.get('where_clause_structure') or statement.get('where_clause') or {}
            if isinstance(structure, dict):
                statement['conditions_where_clause'] = conditions
                statement['conditions_parsed_structure'] = format_condition_structure_summary(structure)
                statement['condition_atoms'] = structure.get('atoms', [])
            TagBasedPolicyService.enrich_statement(statement)

        for dynamic_group in self.dynamic_groups or []:
            if not isinstance(dynamic_group, dict):
                continue
            if 'matching_rule_structure' not in dynamic_group:
                dynamic_group['matching_rule_structure'] = parse_condition_structure(dynamic_group.get('matching_rule'))
            structure = dynamic_group.get('matching_rule_structure') or {}
            if isinstance(structure, dict):
                dynamic_group['matching_rule_parsed_structure'] = format_condition_structure_summary(structure)

    def reset_state(self):
        """
        Resets all main state variables (lists, dictionaries, flags, clients, IDs, etc.).
        Call this before any data (re)load operation for a clean repository state.
        """
        self.compartments = []
        self.policies = []
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = []
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users = []
        self.defined_tag_namespace_keys = {}
        self.domain_clients = {}
        self.data_as_of = ''
        self.tenancy_ocid = None
        # Reset all OCI service clients so that any previous tenancy context
        # does not leak across cache/JSON/CIS loads.  Callers that need a
        # client must either re-run initialize_client or gracefully handle
        # the None case.
        self.identity_client = None
        self.logging_search_client = None
        self.resource_search_client = None
        self.limits_client = None
        self.identity_loaded_from_tenancy = False
        self.policies_loaded_from_tenancy = False
        self.version = 1
        self.load_all_users = True
        self.snapshot_kind = None
        self.inventory_complete = True
        self.compartment_domain_search_depth = None
        self.compliance_capabilities = {}
        self.compliance_artifact_counts = {}
        # Do not replace permission_reference_repo: it is injected by the app (main) and
        # must remain the loaded ReferenceDataRepo so risk scoring and permission lookups work.
        # If there are additional ephemeral analysis/cache attributes, reset them here
        # (e.g., self._policy_progress_queue, self.normalizer, cached_*, etc.)
        logger.info('PolicyAnalysisRepository state has been reset.')

    def initialize_client(
        self,
        use_instance_principal: bool,
        use_resource_principal: bool = False,
        session_token: str | None = None,
        recursive: bool = True,
        profile: str = 'DEFAULT',
    ) -> bool:
        """Initializes the OCI client to be used for all data operations

        Client can be loaded using PROFILE or Instance Principal authentication methods

        Args:
            use_instance_principal: Whether to attempt Instance Principal signer-based authentication
            use_resource_principal: Whether to attempt Resource Principal signer-based authentication
            recursive: Whether to load tenancy data across all compartments, or simply the root (tenancy) compartment
            session: The named OCI Session Token Profile to use - must be present on the file system in the standard OCI location of .oci/config
            profile: The named OCI Profile to use - must be present on the file system in the standard OCI location of .oci/config

        Returns:
            A boolean indicating whether the client was created successfully.  False indicates that an unrecoverable issue occurred
            setting up the client.

        """
        self.session_token = session_token
        self.use_instance_principal = use_instance_principal
        self.use_resource_principal = use_resource_principal
        try:
            from oci.limits import LimitsClient

            if os.environ.get('OPA_OCI_SDK_DEBUG', '0') == '1':
                logging.getLogger('oci').setLevel(logging.DEBUG)
                logger.info('OPA_OCI_SDK_DEBUG enabled: OCI SDK logger set to DEBUG')

            if use_resource_principal:
                logger.info('Using Resource Principal authentication to initialize OCI clients')
                logger.info('Creating resource principal signer...')
                self.signer = get_resource_principals_signer()
                logger.info('Resource principal signer created successfully')
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.logging_search_client = LogSearchClient(config={}, signer=self.signer)
                self.resource_search_client = ResourceSearchClient(config={}, signer=self.signer)
                self.limits_client = LimitsClient(config={}, signer=self.signer)
                # most resource principal signer variants expose tenancy_id, but keep safe fallback
                self.tenancy_ocid = getattr(self.signer, 'tenancy_id', None)
                if not self.tenancy_ocid:
                    logger.warning('Resource principal signer did not expose tenancy_id directly.')
                logger.info('Resource principal tenancy OCID resolved: %s', self.tenancy_ocid)
            elif use_instance_principal:
                logger.info('Using Instance Principal authentication to initialize OCI clients')
                logger.info('Creating InstancePrincipalsSecurityTokenSigner...')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                logger.info('Instance principal signer created successfully')
                # Identity for all policy Data
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.logging_search_client = LogSearchClient(config={}, signer=self.signer)
                self.resource_search_client = ResourceSearchClient(config={}, signer=self.signer)
                self.limits_client = LimitsClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
                logger.info('Instance principal tenancy OCID resolved: %s', self.tenancy_ocid)
            elif session_token:
                logger.info('Using session-token authentication to initialize OCI clients')
                self.config = config.from_file(profile_name=session_token)
                token_file = self.config['security_token_file']
                token = None
                with open(token_file) as f:
                    token = f.read()
                private_key = load_private_key_from_file(self.config['key_file'])
                self.signer = SecurityTokenSigner(token, private_key)
                self.identity_client = IdentityClient({'region': self.config['region']}, signer=self.signer)
                self.resource_search_client = ResourceSearchClient(
                    {'region': self.config['region']}, signer=self.signer
                )
                self.limits_client = LimitsClient({'region': self.config['region']}, signer=self.signer)
                self.tenancy_ocid = self.config['tenancy']
                logger.info('Success session auth')
            else:
                logger.debug(f'Using Profile Authentication: {profile}')
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.logging_search_client = LogSearchClient(self.config)
                self.tenancy_ocid = self.config['tenancy']
                self.resource_search_client = ResourceSearchClient(self.config)
                self.limits_client = LimitsClient(self.config)
            logger.info(f'Set up Identity Client for tenancy: {self.tenancy_ocid}')
            if not self.tenancy_ocid:
                logger.error('Tenancy OCID is not available after client initialization.')
                return False

            # Set Recursion
            self.recursive = recursive
            logger.debug(f'Set recursive to: {self.recursive}')

            # Get tenancy name
            logger.info('Resolving tenancy name via IdentityClient.get_compartment...')
            tenancy_compartment = self._api_call_with_logging(
                'IdentityClient.get_compartment', self.identity_client.get_compartment, compartment_id=self.tenancy_ocid
            )
            if not tenancy_compartment or not tenancy_compartment.data:
                logger.error('Unable to resolve tenancy compartment details for OCID: %s', self.tenancy_ocid)
                return False
            self.tenancy_name = tenancy_compartment.data.name
            logger.info(f'Initialized client for tenancy: {self.tenancy_name} ({self.tenancy_ocid})')
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def check_statement_location_validity(self, st):
        """
        Checks if the compartment location for a statement is valid (exists and is ACTIVE).

        Args:
            st: The policy statement (dict).

        Returns:
            None if valid; string message if invalid.
        """
        if st.get('location_type') == 'compartment id':
            logger.info(f'Checking location validity for statement: {st.get("statement_text")}')
            location_ocid = st.get('location')
            if not self._check_invalid_location(location_ocid):
                return f'Compartment OCID {location_ocid} not found in tenancy'
        return None

    def _check_invalid_location(self, compartment_ocid) -> bool:
        """
        Given a compartment OCID-based location, return False if there is no compartment (any more)
        or if the compartment is not ACTIVE.  True if it exists and is ACTIVE.

        Called from Policy IntelligenceEngine.find_invalid_statements() - only doing this now because of the OCI Client needed
        """
        try:
            comp: Compartment = self.identity_client.get_compartment(compartment_id=compartment_ocid).data
            if comp.lifecycle_state == Compartment.LIFECYCLE_STATE_ACTIVE:
                return True
            else:
                logger.warning(f'Found Compartment but not ACTIVE: {compartment_ocid} was: {comp.lifecycle_state}')
                return False

        except Exception as e:
            # Any error means it is invalid
            logger.debug(f'Compartment OCID {compartment_ocid} not valid: {e}')
            return False

    def _parse_define_statement(self, policy: BasePolicy, statement: DefineStatement) -> bool:
        """
        This is now a thin wrapper calling the centralized PolicyStatementNormalizer.
        """

        try:
            # Use definition's base model fields for required meta
            base = {
                k: statement[k]
                for k in [
                    'policy_name',
                    # 'policy_description',
                    'policy_ocid',
                    'compartment_ocid',
                    'compartment_path',
                    'creation_time',
                    'internal_id',
                ]
                if k in statement
            }
            normalized = self.normalizer.normalize(
                statement_text=statement['statement_text'], statement_type='define', base_fields=base
            )
            if isinstance(normalized, dict) and not normalized.get('parsed', True):
                # convert statement to dict to ensure we can add fields
                statement_dict = dict(statement)
                statement_dict['parsed'] = False
                statement_dict['valid'] = False
                statement_dict['invalid_reasons'] = normalized.get('invalid_reasons', [])
                logger.debug(
                    f'Define statement was unable to normalize: {statement_dict.get("statement_text")} | Reason: {statement_dict.get("invalid_reasons")}'
                )
                self.defined_aliases.append(statement_dict)
                return False
            self.defined_aliases.append(normalized)
            logger.debug(f'Define Statement Added: {normalized}')
            return True
        except Exception as e:
            statement['parsed'] = False
            statement['valid'] = False
            statement['invalid_reasons'] = [f'Normalize define statement failed: {e}']
            logger.debug(f'Normalize define statement failed: {e}')
            self.defined_aliases.append(statement)
            return False

    def _parse_admit_statement(self, policy: BasePolicy, statement: AdmitStatement) -> bool:
        """
        This is now a thin wrapper calling the centralized PolicyStatementNormalizer.
        """

        try:
            base = {
                k: statement[k]
                for k in [
                    'policy_name',
                    # 'policy_description',
                    'policy_ocid',
                    'compartment_ocid',
                    'compartment_path',
                    'creation_time',
                    'internal_id',
                ]
                if k in statement
            }
            normalized = self.normalizer.normalize(
                statement_text=statement['statement_text'], statement_type='admit', base_fields=base
            )
            if isinstance(normalized, dict) and not normalized.get('parsed', True):
                statement_dict = dict(statement)
                statement_dict['parsed'] = False
                statement_dict['valid'] = False
                statement_dict['invalid_reasons'] = normalized.get('invalid_reasons', [])
                logger.debug(
                    f"Admit statement was unable to normalize: {statement_dict.get('statement_text')} | Reason: {statement_dict.get('invalid_reasons')}"
                )
                self.cross_tenancy_statements.append(statement_dict)
                return False
            self.cross_tenancy_statements.append(normalized)
            logger.debug(f'Admit Statement Added: {normalized}')
            return True
        except Exception as ex:
            statement['valid'] = False
            statement['parsed'] = False
            statement['invalid_reasons'] = [f'Normalize admit parser failed: {ex}']
            logger.debug(f'Normalize admit parser failed: {ex}')
            self.cross_tenancy_statements.append(statement)
            return False

    def _parse_endorse_statement(self, policy: BasePolicy, statement: EndorseStatement) -> bool:
        """
        This is now a thin wrapper calling the centralized PolicyStatementNormalizer.
        """

        try:
            base = {
                k: statement[k]
                for k in [
                    'policy_name',
                    # 'policy_description',
                    'policy_ocid',
                    'compartment_ocid',
                    'compartment_path',
                    'creation_time',
                    'internal_id',
                ]
                if k in statement
            }
            normalized = self.normalizer.normalize(
                statement_text=statement['statement_text'], statement_type='endorse', base_fields=base
            )
            if isinstance(normalized, dict) and not normalized.get('parsed', True):
                statement_dict = dict(statement)
                statement_dict['parsed'] = False
                statement_dict['valid'] = False
                statement_dict['invalid_reasons'] = normalized.get('invalid_reasons', [])
                logger.debug(
                    f"Endorse statement was unable to normalize: {statement_dict.get('statement_text')} | Reason: {statement_dict.get('invalid_reasons')}"
                )
                self.cross_tenancy_statements.append(statement_dict)
                return False
            self.cross_tenancy_statements.append(normalized)
            logger.debug(f'Endorse Statement Added: {normalized}')
            return True
        except Exception as ex:
            statement['valid'] = False
            statement['parsed'] = False
            statement['invalid_reasons'] = [f'Normalize endorse parser failed: {ex}']
            logger.debug(f'Normalize endorse parser failed: {ex}')
            self.cross_tenancy_statements.append(statement)
            return False

    def _resolve_ocid_subjects_in_statement(self, stmt: RegularPolicyStatement):
        """
        If the statement has subject_type group or dynamic-group and all subjects are OCIDs,
        replace each OCID with (domain, name) if resolvable, otherwise ('Unknown', ocid).
        Mark as invalid if any unresolved OCIDs. Add parsing_notes for both resolution and unresolved cases.
        This is done in-place on the statement dict.
        """
        subject_type = stmt.get('subject_type')
        subjects = stmt.get('subject', [])
        principals = stmt.get('principals', [])
        if not isinstance(subjects, list):
            return

        # Handle group/dynamic-group subjects with raw OCID lists
        is_named_group = subject_type in ('group', 'dynamic-group')
        # Handle explicit group-id/dynamic-group-id subjects using principals
        is_id_group = subject_type in ('group-id', 'dynamic-group-id')

        if is_named_group:
            # Detect if all subjects are in OCID format (no tuple/list inside)
            all_ocids = all(isinstance(s, str) and s.lower().startswith('ocid1.') for s in subjects)
            if not all_ocids:
                return

        resolved_subjects = []
        unresolved_ocids = []
        resolution_notes = []
        for ocid in subjects if is_named_group else []:
            if subject_type == 'group':
                grp = next((g for g in self.groups if g.get('group_ocid', '').lower() == ocid.lower()), None)
                if grp:
                    dom = grp.get('domain_name') or 'Default'
                    name = grp.get('group_name') or ocid
                    resolved_subjects.append((dom, name))
                    resolution_notes.append(f'Resolved group OCID {ocid} -> {dom}/{name}')
                else:
                    resolved_subjects.append(('Unknown', ocid))
                    unresolved_ocids.append(ocid)
            elif subject_type == 'dynamic-group':
                dg = next(
                    (d for d in self.dynamic_groups if d.get('dynamic_group_ocid', '').lower() == ocid.lower()), None
                )
                if dg:
                    dom = dg.get('domain_name') or 'Default'
                    name = dg.get('dynamic_group_name') or ocid
                    resolved_subjects.append((dom, name))
                    resolution_notes.append(f'Resolved dynamic group OCID {ocid} -> {dom}/{name}')
                else:
                    resolved_subjects.append(('Unknown', ocid))
                    unresolved_ocids.append(ocid)
        # Handle group-id/dynamic-group-id using principals
        if is_id_group and isinstance(principals, list):
            for principal in principals:
                if not isinstance(principal, dict):
                    continue
                ocid = principal.get('ocid')
                if not ocid and isinstance(principal.get('principal_key'), str):
                    _prefix, candidate = principal['principal_key'].split(':', 1)
                    ocid = candidate
                if not ocid:
                    continue
                if subject_type == 'group-id':
                    grp = next((g for g in self.groups if g.get('group_ocid', '').lower() == str(ocid).lower()), None)
                    if grp:
                        dom = grp.get('domain_name') or 'Default'
                        name = grp.get('group_name') or ocid
                        resolution_notes.append(f'Resolved group OCID {ocid} -> {dom}/{name}')
                    else:
                        unresolved_ocids.append(str(ocid))
                else:
                    dg = next(
                        (
                            d
                            for d in self.dynamic_groups
                            if d.get('dynamic_group_ocid', '').lower() == str(ocid).lower()
                        ),
                        None,
                    )
                    if dg:
                        dom = dg.get('domain_name') or 'Default'
                        name = dg.get('dynamic_group_name') or ocid
                        resolution_notes.append(f'Resolved dynamic group OCID {ocid} -> {dom}/{name}')
                    else:
                        unresolved_ocids.append(str(ocid))

        if resolved_subjects:
            stmt['subject'] = resolved_subjects

        notes = stmt.setdefault('parsing_notes', [])
        if resolution_notes:
            notes.extend(resolution_notes)
        if unresolved_ocids:
            notes.append(
                f"Failed to resolve OCID(s): {', '.join(sorted(set(unresolved_ocids)))}; inserted as ('Unknown', ocid)"
            )
            stmt['valid'] = False
        elif resolution_notes:
            notes.append('All OCID subject(s) resolved to domain/name tuple(s).')

    def _build_principals_from_statement(self, stmt: RegularPolicyStatement) -> list[Principal]:
        """Derive canonical principal models from subject_type + subject.

        This is additive/non-breaking: it populates ``principals`` while
        leaving legacy ``subject`` untouched.
        """
        subject_type = (stmt.get('subject_type') or '').strip()
        subjects = stmt.get('subject')
        principals: list[Principal] = []

        def _policy_subject_domain(value: object | None) -> str:
            """Return the policy-derived domain, normalizing the default name.

            The subject parser supplies a named domain from the segment before
            ``/``. A bare group or dynamic-group name is represented as
            ``default`` there; expose it consistently as ``Default`` without
            claiming that an Identity Domains inventory was loaded.
            """
            domain = str(value or 'Default').strip()
            return 'Default' if not domain or domain.casefold() == 'default' else domain

        if not subject_type:
            stmt['principals'] = principals
            return principals

        def _append_principal(
            *,
            principal_type: str,
            principal_key: str,
            domain_name: str | None = None,
            name: str | None = None,
            ocid: str | None = None,
            display_name: str | None = None,
        ) -> None:
            principals.append(
                {
                    'principal_type': principal_type,
                    'principal_key': principal_key,
                    'domain_name': domain_name,
                    'name': name,
                    'ocid': ocid,
                    'display_name': display_name or principal_key,
                }
            )

        if subject_type in ('any-user', 'any-group', 'service'):
            subj_list = subjects if isinstance(subjects, list) else [subjects]
            for subj in subj_list:
                name = str(subj or subject_type).strip()
                key = calculate_principal_key(subject_type, None, name)
                _append_principal(
                    principal_type=subject_type,
                    principal_key=key,
                    name=name,
                    display_name=name,
                )
            stmt['principals'] = principals
            return principals

        if subject_type in ('group-id', 'dynamic-group-id'):
            subj_list = subjects if isinstance(subjects, list) else [subjects]
            for subj in subj_list:
                ocid = None
                if isinstance(subj, tuple | list) and len(subj) >= 2:
                    ocid = str(subj[1] or '').strip()
                elif isinstance(subj, str):
                    ocid = subj.strip()
                if not ocid:
                    continue
                key = f'{subject_type}:{ocid}'
                _append_principal(
                    principal_type=subject_type,
                    principal_key=key,
                    ocid=ocid,
                    display_name=ocid,
                )
            stmt['principals'] = principals
            return principals

        subj_list = subjects if isinstance(subjects, list) else [subjects]
        for subj in subj_list:
            domain = None
            name = None
            if isinstance(subj, tuple | list) and len(subj) >= 2:
                domain = _policy_subject_domain(subj[0])
                name = str(subj[1] or '').strip()
            elif isinstance(subj, str):
                name = subj.strip()
            if not name:
                continue
            key = calculate_principal_key(subject_type, domain, name)
            display = f'{domain}/{name}' if domain else name
            _append_principal(
                principal_type=subject_type,
                principal_key=key,
                domain_name=domain,
                name=name,
                display_name=display,
            )

        stmt['principals'] = principals
        return principals

    def _parse_statement(self, policy: BasePolicy, statement: RegularPolicyStatement) -> bool:
        """
        This is now a thin wrapper calling the centralized PolicyStatementNormalizer.
        """

        try:
            base = {
                k: statement[k]
                for k in [
                    'policy_name',
                    # 'policy_description',
                    'policy_ocid',
                    'compartment_ocid',
                    'compartment_path',
                    'creation_time',
                    'internal_id',
                ]
                if k in statement
            }
            normalized = self.normalizer.normalize(
                statement_text=statement['statement_text'], statement_type='regular', base_fields=base
            )
            policy_tags = {
                'policy_tags': policy.get('tags', {}),
                'policy_freeform_tags': policy.get('freeform_tags', {}),
                'policy_defined_tags': policy.get('defined_tags', {}),
            }
            if isinstance(normalized, dict) and not normalized.get('parsed', True):
                statement_dict = dict(statement)
                statement_dict.update(policy_tags)
                statement_dict['action'] = 'unknown'
                statement_dict['parsed'] = False
                statement_dict['valid'] = False
                statement_dict['invalid_reasons'] = normalized.get('invalid_reasons', [])
                logger.debug(
                    f"Regular statement was unable to normalize: {statement_dict.get('statement_text')} | Reason: {statement_dict.get('invalid_reasons')}"
                )
                logger.debug(f'Full invalid statement data: {statement_dict}')
                self.regular_statements.append(statement_dict)
                return False
            normalized.update(policy_tags)
            TagBasedPolicyService.enrich_statement(normalized)
            # Build principals first (raw subject), resolve OCIDs, then rebuild principals
            # so they reflect resolved domain/name tuples.
            self._build_principals_from_statement(normalized)
            self._resolve_ocid_subjects_in_statement(normalized)
            self._build_principals_from_statement(normalized)
            self.regular_statements.append(normalized)
            logger.debug(f'Regular Policy Statement Parsed: {normalized}')
            logger.debug(f'Regular Policy Statement Parsed: {normalized}')
            return True
        except Exception as ex:
            statement['parsed'] = False
            statement['valid'] = False
            statement['invalid_reasons'] = [f'Normalize regular policy parser failed: {ex}']
            logger.debug(f'Normalize regular policy parser failed: {ex}')
            self.regular_statements.append(statement)
            return False

    def _parse_dynamic_group(self, domain, dg: DynamicResourceGroup) -> DynamicGroup:
        """Extract the contents of the DG into a dict"""
        logger.debug(f'Created by: {dg.idcs_created_by}')
        matching_rule_structure = parse_condition_structure(dg.matching_rule)
        return DynamicGroup(
            domain_name=domain.display_name,
            domain_ocid=domain.id,
            dynamic_group_name=dg.display_name,
            dynamic_group_id=dg.id,
            description=dg.description or '',
            matching_rule=dg.matching_rule,
            matching_rule_structure=matching_rule_structure,
            matching_rule_parsed_structure=format_condition_structure_summary(matching_rule_structure),
            in_use=True,  # Placeholder until analysis is run
            dynamic_group_ocid=dg.ocid,
            creation_time=str(dg.meta.created),
            created_by_ocid=dg.idcs_created_by.ocid if dg.idcs_created_by else None,
            created_by_name=dg.idcs_created_by.display if dg.idcs_created_by else None,
        )

    # --- Main Data Loading Functions for Tenancy ---
    def load_compartments_only(self) -> bool:
        """
        Loads only compartments (hierarchy, flat) using OCI Clients.
        """
        self.compartments = []
        start_time = time.perf_counter()
        try:
            logger.info('Bulk fetching all compartments...')
            root_comp_response = self._api_call_with_logging(
                'IdentityClient.get_compartment', self.identity_client.get_compartment, compartment_id=self.tenancy_ocid
            )
            if not root_comp_response or not root_comp_response.data:
                logger.error(f'Failed to get root compartment: {self.tenancy_ocid}')
                return False
            root_comp = root_comp_response.data
            comp_response = self._api_call_with_logging(
                'IdentityClient.list_compartments',
                pagination.list_call_get_all_results,
                self.identity_client.list_compartments,
                self.tenancy_ocid,
                access_level='ACCESSIBLE',
                sort_order='ASC',
                compartment_id_in_subtree=True,
                lifecycle_state='ACTIVE',
                limit=1000,
            )
            all_comps = [root_comp] + (list(comp_response.data) if comp_response and comp_response.data else [])
            logger.info(f'Total compartments loaded: {len(all_comps)}')

            # Build our internal list with hierarchy paths - also extract tags if present
            self.compartments.clear()
            for comp in all_comps:
                tags = {}
                if hasattr(comp, 'freeform_tags') and comp.freeform_tags:
                    tags.update(comp.freeform_tags)
                if hasattr(comp, 'defined_tags') and comp.defined_tags:
                    for ns, val in comp.defined_tags.items():
                        if isinstance(val, dict):
                            for k, v in val.items():
                                tags[f'{ns}:{k}'] = v
                        else:
                            tags[ns] = val
                compartment = Compartment(
                    id=comp.id,
                    name=(comp.name if comp.id != self.tenancy_ocid else 'ROOT'),
                    parent_id=comp.compartment_id,
                    hierarchy_path='',
                    description=getattr(comp, 'description', '') or '',
                    lifecycle_state=getattr(comp, 'lifecycle_state', '') or '',
                    **({'tags': tags} if tags else {}),
                )
                self.compartments.append(compartment)
            logger.info('Building compartment hierarchy paths and lookup tables...')
            for compartment in self.compartments:
                compartment['hierarchy_path'] = self._get_hierarchy_path_for_compartment(compartment, '')
            total_time = time.perf_counter() - start_time
            logger.info(f'Loaded {len(self.compartments)} compartments in {total_time:.2f}s')
            return True
        except Exception as e:
            logger.error(f'Failed to load compartments: {e}')
            return False

    def load_policies_only(self) -> bool:
        """
        Loads policies/statements only, assuming compartments are already loaded.
        """
        self.policies = []
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = []
        self.defined_tag_namespace_keys = {}
        # Ensure compliance flag is reset on live tenancy load
        self.loaded_from_compliance_output = False
        start_time = time.perf_counter()
        try:
            logger.info('Bulk fetching all policies for all compartments...')
            if self.recursive:
                policy_query = 'query policy resources'
            else:
                policy_query = f"query policy resources where compartmentId = '{self.tenancy_ocid}'"
            # Run policy search and then for each result, fetch the full policy details and statements - do this in threads for speed
            policy_search_results = self._api_call_with_logging(
                'ResourceSearchClient.search_resources',
                self.resource_search_client.search_resources,
                search_details=StructuredSearchDetails(type='Structured', query=policy_query),
                limit=1000,
            )
            if policy_search_results and policy_search_results.data and policy_search_results.data.items:
                logger.info(
                    f'Found {len(policy_search_results.data.items)} policies via Resource Search (recursive={self.recursive}).'
                )
                total_policies = len(policy_search_results.data.items)

                def _process_policy_resource(item, position, total_policies):
                    policy_ocid = item.identifier
                    compartment_ocid = item.compartment_id
                    try:
                        policy_response = self._api_call_with_logging(
                            'IdentityClient.get_policy', self.identity_client.get_policy, policy_id=policy_ocid
                        )
                        if policy_response and policy_response.data:
                            # Extract tags (keep original structure for round-trip)
                            freeform_tags = {}
                            defined_tags = {}
                            if hasattr(policy_response.data, 'freeform_tags') and policy_response.data.freeform_tags:
                                freeform_tags = dict(policy_response.data.freeform_tags)
                            if hasattr(policy_response.data, 'defined_tags') and policy_response.data.defined_tags:
                                try:
                                    defined_tags = dict(policy_response.data.defined_tags)
                                except Exception:
                                    defined_tags = {}
                            # Flatten tags for UI display (namespace:key for defined tags)
                            tags = {}
                            if freeform_tags:
                                tags.update(freeform_tags)
                            if defined_tags:
                                for ns, val in defined_tags.items():
                                    if isinstance(val, dict):
                                        for k, v in val.items():
                                            tags[f'{ns}:{k}'] = v
                                    else:
                                        tags[str(ns)] = str(val)
                            comp_path = next(
                                (
                                    comp['hierarchy_path']
                                    for comp in self.compartments
                                    if comp['id'] == policy_response.data.compartment_id
                                ),
                                'ROOT',
                            )
                            policy_obj = BasePolicy(
                                policy_ocid=policy_response.data.id,
                                policy_name=policy_response.data.name,
                                description=policy_response.data.description or '',
                                compartment_ocid=policy_response.data.compartment_id,
                                compartment_path=comp_path,
                                creation_time=policy_response.data.time_created,
                                tags=tags if tags else None,
                                freeform_tags=freeform_tags if freeform_tags else None,
                                defined_tags=defined_tags if defined_tags else None,
                            )
                            self.policies.append(policy_obj)
                            for statement in policy_response.data.statements:
                                hierarchy_path = next(
                                    (
                                        comp['hierarchy_path']
                                        for comp in self.compartments
                                        if comp['id'] == compartment_ocid
                                    ),
                                    'UNKNOWN_PATH',
                                )
                                base_policy_statement: BasePolicyStatement = BasePolicyStatement(
                                    policy_name=policy_response.data.name,
                                    policy_ocid=policy_response.data.id,
                                    compartment_ocid=policy_response.data.compartment_id,
                                    compartment_path=hierarchy_path,
                                    statement_text=statement,
                                    creation_time=str(policy_response.data.time_created),
                                    internal_id=hashlib.md5((statement + policy_response.data.id).encode()).hexdigest(),
                                    parsed=False,
                                )
                                st_text_lower = statement.strip().lower()
                                if st_text_lower.startswith('define'):
                                    define_statement: DefineStatement = DefineStatement(**base_policy_statement)
                                    self._parse_define_statement(policy_obj, define_statement)
                                elif (
                                    st_text_lower.startswith('admit')
                                    or st_text_lower.startswith('endorse')
                                    or st_text_lower.startswith('deny admit')
                                    or st_text_lower.startswith('deny endorse')
                                ):
                                    if st_text_lower.startswith('admit') or st_text_lower.startswith('deny admit'):
                                        admit_statement: AdmitStatement = AdmitStatement(**base_policy_statement)
                                        self._parse_admit_statement(policy_obj, admit_statement)
                                    elif st_text_lower.startswith('endorse') or st_text_lower.startswith(
                                        'deny endorse'
                                    ):
                                        endorse_statement: EndorseStatement = EndorseStatement(**base_policy_statement)
                                        self._parse_endorse_statement(policy_obj, endorse_statement)
                                else:
                                    policy_statement: RegularPolicyStatement = RegularPolicyStatement(
                                        **base_policy_statement
                                    )
                                    self._parse_statement(policy_obj, policy_statement)
                    except Exception as e:
                        logger.warning(
                            f'Failed to get policy {policy_ocid}: {e}. '
                            'This may be expected if the policy was deleted as part of a consolidation plan execution.'
                        )

                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    for idx, item in enumerate(policy_search_results.data.items):
                        executor.submit(_process_policy_resource, item, idx, total_policies)

            # Build the defined tag namespace/key catalog from a dedicated
            # resource query so UI consumers can display current namespaces
            # independent of whether tags appear on policy objects.
            self._refresh_defined_tag_catalog_from_resource_query()
            self.data_as_of = str(datetime.now(UTC))
            total_time = time.perf_counter() - start_time
            logger.info(f'Bulk loaded {len(self.regular_statements)} policy statements in {total_time:.2f}s')
            self._enrich_compartments_with_statement_counts()
            self.policies_loaded_from_tenancy = True
            return True
        except Exception as e:
            logger.error(f'Failed to load policies: {e}')
            return False

    def get_compartment_path_for_ocid(self, compartment_ocid: str | None) -> str:
        """Resolve a compartment OCID to a hierarchy path string."""
        if not compartment_ocid:
            return 'ROOT'
        if compartment_ocid == self.tenancy_ocid:
            return 'ROOT'

        comp = next((c for c in (self.compartments or []) if c.get('id') == compartment_ocid), None)
        if comp:
            return comp.get('hierarchy_path') or self._get_hierarchy_path_for_compartment(comp, '')
        return 'UNKNOWN_PATH'

    def _extract_tag_static_values(self, validator_obj) -> list[str] | None:
        """Extract static enum values from an OCI tag validator object."""
        if not validator_obj:
            return None

        # Most OCI validator model objects expose "values" for enum-like lists.
        values = getattr(validator_obj, 'values', None)
        if isinstance(values, list | tuple | set):
            normalized = sorted({str(v) for v in values if v is not None}, key=lambda x: x.lower())
            return normalized or None

        # Fallback for alternate object field names.
        for attr_name in ('allowed_values', 'enum_values', 'list_values'):
            vals = getattr(validator_obj, attr_name, None)
            if isinstance(vals, list | tuple | set):
                normalized = sorted({str(v) for v in vals if v is not None}, key=lambda x: x.lower())
                return normalized or None

        # Dict-style fallback if an SDK object is converted/intercepted as dict.
        if isinstance(validator_obj, dict):
            for key_name in ('values', 'allowedValues', 'allowed_values', 'enumValues', 'enum_values'):
                vals = validator_obj.get(key_name)
                if isinstance(vals, list | tuple | set):
                    normalized = sorted({str(v) for v in vals if v is not None}, key=lambda x: x.lower())
                    return normalized or None

        return None

    def _merge_tag_static_values(
        self, existing_values: list[str] | None, new_values: list[str] | None
    ) -> list[str] | None:
        """Merge existing/new static values and return normalized output."""
        if isinstance(existing_values, list) and isinstance(new_values, list):
            return sorted(set(existing_values + new_values), key=lambda x: x.lower())
        if isinstance(existing_values, list):
            return existing_values
        if isinstance(new_values, list):
            return new_values
        return None

    def _get_static_values_for_tag(self, namespace_ocid: str, tag_name: str, tag_obj) -> list[str] | None:
        """Resolve static values for a tag using get_tag first, then list_tags payload fallback."""
        static_values = None

        # Primary path: fetch full tag definition and inspect validator.
        try:
            tag_full_resp = self._api_call_with_logging(
                'IdentityClient.get_tag',
                self.identity_client.get_tag,
                tag_namespace_id=namespace_ocid,
                tag_name=tag_name,
            )
            tag_full = getattr(tag_full_resp, 'data', None)
            static_values = self._extract_tag_static_values(getattr(tag_full, 'validator', None))
            if static_values is None:
                static_values = self._extract_tag_static_values(getattr(tag_full, 'tag_definition_validator', None))
        except Exception:
            logger.debug(
                f'Unable to get full tag definition for namespace={namespace_ocid} tag={tag_name}; '
                'falling back to list_tags payload.',
                exc_info=True,
            )

        # Fallback path: some payloads may already include validator.
        if static_values is None:
            static_values = self._extract_tag_static_values(getattr(tag_obj, 'validator', None))
        if static_values is None:
            static_values = self._extract_tag_static_values(getattr(tag_obj, 'tag_definition_validator', None))

        return static_values

    def _load_tag_keys_for_namespace(self, namespace_ocid: str, keys: dict[str, list[str] | None]) -> None:
        """Load/merge keys for a namespace into the provided mapping."""
        tags_resp = self._api_call_with_logging(
            'IdentityClient.list_tags',
            pagination.list_call_get_all_results,
            self.identity_client.list_tags,
            tag_namespace_id=namespace_ocid,
            limit=1000,
        )

        for tag_obj in getattr(tags_resp, 'data', []) or []:
            tag_name = getattr(tag_obj, 'name', None)
            if not tag_name:
                continue
            tag_name_str = str(tag_name)
            static_values = self._get_static_values_for_tag(
                namespace_ocid=namespace_ocid, tag_name=tag_name_str, tag_obj=tag_obj
            )
            keys[tag_name_str] = self._merge_tag_static_values(keys.get(tag_name_str), static_values)

    def _ensure_tag_namespace_entry(self, item) -> tuple[str, str, dict[str, Any]] | None:
        """Create/update catalog entry for a namespace and return (name, ocid, entry)."""
        namespace_ocid = getattr(item, 'identifier', None)
        namespace_name = getattr(item, 'display_name', None) or getattr(item, 'name', None) or str(namespace_ocid or '')
        if not namespace_name:
            return None

        namespace_entry = self.defined_tag_namespace_keys.setdefault(
            str(namespace_name),
            {
                'keys': {},
                'compartment_ocid': getattr(item, 'compartment_id', None),
                'compartment_path': self.get_compartment_path_for_ocid(getattr(item, 'compartment_id', None)),
            },
        )
        keys = namespace_entry.setdefault('keys', {})
        if not isinstance(keys, dict):
            keys = {}
            namespace_entry['keys'] = keys

        namespace_entry['compartment_ocid'] = getattr(item, 'compartment_id', None)
        namespace_entry['compartment_path'] = self.get_compartment_path_for_ocid(getattr(item, 'compartment_id', None))
        return str(namespace_name), str(namespace_ocid or ''), namespace_entry

    def _refresh_defined_tag_catalog_from_resource_query(self) -> None:
        """Refresh defined tag namespace/key catalog using OCI Resource Search.

        This method intentionally uses ``query tagnamespace resources`` to
        discover namespaces, then calls Identity ``list_tags`` per namespace to
        resolve keys.
        """

        self.defined_tag_namespace_keys = {}
        logger.debug(
            f'Starting defined tag namespace/key refresh from Resource Search (recursive={getattr(self, "recursive", None)}). '
            'Results are stored in-memory only (cache persistence deferred).'
        )
        if not self.resource_search_client or not self.identity_client:
            logger.debug('Skipping tag namespace catalog refresh: clients not initialized.')
            return

        try:
            if self.recursive:
                tag_ns_query = 'query tagnamespace resources'
            else:
                tag_ns_query = f"query tagnamespace resources where compartmentId = '{self.tenancy_ocid}'"

            search_resp = self._api_call_with_logging(
                'ResourceSearchClient.search_resources (tagnamespace)',
                self.resource_search_client.search_resources,
                search_details=StructuredSearchDetails(type='Structured', query=tag_ns_query),
                limit=1000,
            )
            items = list(search_resp.data.items) if search_resp and search_resp.data and search_resp.data.items else []
            logger.info(f'Discovered {len(items)} tag namespace resources via Resource Search.')

            for item in items:
                namespace_meta = self._ensure_tag_namespace_entry(item)
                if not namespace_meta:
                    continue
                namespace_name, namespace_ocid, namespace_entry = namespace_meta

                keys = namespace_entry.setdefault('keys', {})
                if not isinstance(keys, dict):
                    keys = {}
                    namespace_entry['keys'] = keys
                if not namespace_ocid:
                    continue

                try:
                    self._load_tag_keys_for_namespace(namespace_ocid=namespace_ocid, keys=keys)
                    logger.info(
                        'Loaded defined tag namespace "%s" (ocid=%s) with %d key(s).',
                        namespace_name,
                        namespace_ocid,
                        len(keys),
                    )
                except Exception:
                    logger.info(
                        'Unable to list keys for tag namespace %s (%s).',
                        namespace_name,
                        namespace_ocid,
                        exc_info=True,
                    )

            # Drop empty placeholder namespaces if they have no keys and no
            # meaningful name.
            self.defined_tag_namespace_keys = {
                ns: entry for ns, entry in self.defined_tag_namespace_keys.items() if ns and isinstance(entry, dict)
            }
            logger.info(
                'Tag namespace catalog refreshed: %d namespaces, %d keys total (in-memory only).',
                len(self.defined_tag_namespace_keys),
                sum(
                    len((v or {}).get('keys') or {})
                    for v in self.defined_tag_namespace_keys.values()
                    if isinstance((v or {}).get('keys'), dict)
                ),
            )
        except Exception:
            logger.info('Tag namespace catalog refresh failed.', exc_info=True)

    def load_policies_and_compartments(self) -> bool:
        """
        Loads both compartments and all policies using OCI Clients. (Convenience function)
        """
        # Always reset reload timestamp unless restored/preserved by special path (e.g., cache); complies with cache/offline/compliance logic elsewhere too.
        self.policy_data_reloaded = None
        # Ensure compliance flag is reset on live tenancy load
        self.loaded_from_compliance_output = False
        self.current_cache_name = ''
        self.tenancy_policy_limits = {}
        ok1 = self.load_compartments_only()
        if not ok1:
            return False
        ok2 = self.load_policies_only()
        return ok2

    def reload_compartment_policy_data(self) -> bool:
        """
        Reload just the policy/compartment/statement data (not IAM), and update the in-memory timestamp.
        (No cache operations here—see main.py/App for cache update and UI triggers.)

        Returns:
            bool: True if the reload succeeded, False otherwise.
        """
        logger.info('Reloading only compartment+policy+statement data (not IAM)... (No cache ops in repo)')
        success = self.load_policies_and_compartments()
        if not success:
            logger.error('Policy/compartment reload failed!')
            return False
        self.policy_data_reloaded = datetime.now(UTC).isoformat()
        return True

    def fetch_tenancy_policy_statement_limits(self):
        """
        Fetch two key limits from OCI Limits service ("Identity"):
        - policies-count (max policies in tenancy)
        - policy-statements-per-compartment-chain-count (max statements in a compartment hierarchy)
        Uses _api_call_with_logging to time/log the call.
        Returns a tuple: (policies_count_limit, chain_limit) or (None, None) if unavailable or error.
        """
        logger = get_logger(component='limits_fetch')
        policies_count = None
        chain_count = None

        try:
            if not self.tenancy_ocid:
                logger.error('No tenancy_ocid set; cannot fetch OCI policy limits')
                return (None, None)
            limits_client = getattr(self, 'limits_client', None)
            if not limits_client:
                logger.error('No limits_client found. Did you run initialize_client first?')
                return (None, None)

            result = self._api_call_with_logging(
                'LimitsClient.list_limit_values (identity)',
                limits_client.list_limit_values,
                service_name='identity',
                compartment_id=self.tenancy_ocid,
            )
            limits = result.data if hasattr(result, 'data') else []
            if not limits:
                logger.error('No limits returned from OCI API for identity service.')
                self.tenancy_policy_statement_limit = (None, None)
                return (None, None)

            for limit in limits:
                if getattr(limit, 'name', None) == 'policies-count':
                    policies_count = getattr(limit, 'value', None)
                    logger.info(f'Limit: {limit}')
                elif getattr(limit, 'name', None) == 'policy-statements-per-compartment-chain-count':
                    chain_count = getattr(limit, 'value', None)
                    logger.info(f'Limit: {limit}')

            self.tenancy_policy_statement_limit = (policies_count, chain_count)
            self.tenancy_policy_limits = self._build_tenancy_policy_limits(
                policies_count, chain_count, source='live OCI'
            )
            if policies_count is None or chain_count is None:
                logger.warning(
                    'Failed to find some limit values: policies-count=%s, policy-statements-per-compartment-chain-count=%s',
                    str(policies_count),
                    str(chain_count),
                )
            return (policies_count, chain_count)
        except Exception as e:
            logger.error(f'[API] list_limit_values failed: {e}')
            self.tenancy_policy_statement_limit = (None, None)
            self.tenancy_policy_limits = {}
            return (None, None)

    def _build_tenancy_policy_limits(self, policies_count, chain_count, *, source: str) -> dict[str, Any]:
        """Normalize tenancy-specific limit metadata for display and caching."""

        def _positive(value):
            try:
                value = int(value)
                return value if value > 0 else None
            except (TypeError, ValueError):
                return None

        return {
            'policies_count': _positive(policies_count),
            'policy_statements_per_compartment_chain_count': _positive(chain_count),
            'source': source,
            'captured_at': datetime.now(UTC).isoformat(),
        }

    def set_user_supplied_tenancy_policy_limits(self, policies_count, chain_count) -> dict[str, Any]:
        """Set validated limits for only the active tenancy snapshot/cache."""
        limits = self._build_tenancy_policy_limits(policies_count, chain_count, source='user-supplied')
        if not limits['policies_count'] or not limits['policy_statements_per_compartment_chain_count']:
            raise ValueError('Both policy limits must be positive whole numbers.')
        self.tenancy_policy_limits = limits
        self.tenancy_policy_statement_limit = (
            limits['policies_count'],
            limits['policy_statements_per_compartment_chain_count'],
        )
        return limits

    # --- Internal fetchers for Identity Domain entities ---
    def _fetch_dynamic_groups_for_domain(self, domain, domain_client):
        """
        Fetch all dynamic groups for a domain, returning a list of DynamicGroup model objects.
        Uses ThreadPoolExecutor to fetch details in parallel and appends incrementally for UI.
        """
        import threading

        logger.info(f'Fetching dynamic groups for domain: {domain.display_name}')
        dg_list = []
        dg_lock = threading.Lock()
        try:

            def fetch_full_dg(_dg):
                try:
                    thread_id = threading.get_ident()
                    thread_name = threading.current_thread().name
                    logger.debug(
                        f"Thread {thread_name} (id={thread_id}) starting fetch_full_dg for dg_id={getattr(_dg, 'id', None)} display_name={getattr(_dg, 'display_name', None)}"
                    )
                    full_dg = self._api_call_with_logging(
                        'IdentityDomainsClient.get_dynamic_resource_group',
                        domain_client.get_dynamic_resource_group,
                        dynamic_resource_group_id=_dg.id,
                        attribute_sets=['all'],
                    ).data
                    logger.debug(
                        f"Thread {thread_name} (id={thread_id}) finished fetch_full_dg for dg_id={getattr(_dg, 'id', None)} display_name={getattr(_dg, 'display_name', None)}"
                    )
                    parsed = self._parse_dynamic_group(domain=domain, dg=full_dg)
                    with dg_lock:
                        self.dynamic_groups.append(parsed)
                    return parsed
                except Exception as e:
                    logger.error(f'Failed to fetch dynamic group details for: {_dg.id}: {e}')
                    return None

            from concurrent.futures import ThreadPoolExecutor, as_completed

            start_index = 1
            limit = 1000
            while True:
                dg_response = self._api_call_with_logging(
                    'IdentityDomainsClient.list_dynamic_resource_groups',
                    domain_client.list_dynamic_resource_groups,
                    start_index=start_index,
                    count=limit,
                    sort_by='displayName',
                    sort_order='ASCENDING',
                    attribute_sets=['never'],
                )
                if dg_response is None or dg_response.data is None:
                    logger.error('Failed to list dynamic groups')
                    return []
                if not dg_response.data.resources:
                    break
                logger.debug(
                    'Got dynamic group page for %s: start_index=%s count=%s total_results=%s',
                    domain.display_name,
                    start_index,
                    len(dg_response.data.resources),
                    getattr(dg_response.data, 'total_results', None),
                )

                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(fetch_full_dg, _dg) for _dg in dg_response.data.resources]
                    for f in as_completed(futures):
                        result = f.result()
                        if result:
                            dg_list.append(result)

                total_results = getattr(dg_response.data, 'total_results', 0) or 0
                if len(dg_response.data.resources) < limit or start_index + limit > total_results:
                    break
                start_index += limit
        except Exception as e:
            logger.error(f'Exception during dynamic group fetch: {e}')
            return []
        logger.info(f'Fetched {len(dg_list)} dynamic groups for domain: {domain.display_name}')
        return dg_list

    def _fetch_groups_for_domain(self, domain, domain_client):
        """
        Fetch all groups for a domain, returning a list of Group model objects using ThreadPoolExecutor.
        """
        import threading

        logger.info(f'Fetching groups for domain: {domain.display_name}')
        group_list = []
        group_lock = threading.Lock()
        try:
            start_index = 1
            limit = 1000

            def fetch_full_group(g):
                try:
                    thread_id = threading.get_ident()
                    thread_name = threading.current_thread().name
                    logger.debug(
                        f"Thread {thread_name} (id={thread_id}) starting fetch_full_group for group_id={getattr(g, 'id', None)} display_name={getattr(g, 'display_name', None)}"
                    )
                    group_obj = Group(
                        domain_name=domain.display_name,
                        group_name=g.display_name,
                        group_ocid=g.ocid,
                        group_id=g.id,
                        description=getattr(
                            g, 'urn_ietf_params_scim_schemas_oracle_idcs_extension_group_group', None
                        ).description
                        if getattr(g, 'urn_ietf_params_scim_schemas_oracle_idcs_extension_group_group', None)
                        else '',
                    )
                    with group_lock:
                        self.groups.append(group_obj)
                    logger.debug(
                        f"Thread {thread_name} (id={thread_id}) finished fetch_full_group for group_id={getattr(g, 'id', None)} display_name={getattr(g, 'display_name', None)}"
                    )
                    return group_obj
                except Exception as e:
                    logger.error(f"Failed to process group details for: {getattr(g, 'id', None)}: {e}")
                    return None

            from concurrent.futures import ThreadPoolExecutor, as_completed

            while True:
                group_response = self._api_call_with_logging(
                    'IdentityDomainsClient.list_groups',
                    domain_client.list_groups,
                    start_index=start_index,
                    count=limit,
                    sort_by='displayName',
                    sort_order='ASCENDING',
                )
                if group_response.data is None or not group_response.data.resources:
                    break
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(fetch_full_group, g) for g in group_response.data.resources]
                    for f in as_completed(futures):
                        res = f.result()
                        if res:
                            group_list.append(res)
                if (
                    len(group_response.data.resources) < limit
                    or start_index + limit > group_response.data.total_results
                ):
                    break
                start_index += limit
            logger.info(f'Fetched {len(group_list)} groups for domain: {domain.display_name}')
            return group_list
        except Exception as e:
            logger.error(f'Exception during group fetch: {e}')
            return []

    def _fetch_users_for_domain(self, domain, domain_client):
        """
        Fetch users for a domain using OCI generator + ThreadPoolExecutor for user detail calls.
        Uses pagination.list_call_get_all_results_generator to list users.
        """

        logger.info(f'Fetching users for domain: {domain.display_name} with paginator and thread pool')

        def user_summary_generator():
            start_index = 1
            limit = 1000
            while True:
                user_response = self._api_call_with_logging(
                    'IdentityDomainsClient.list_users',
                    domain_client.list_users,
                    start_index=start_index,
                    count=limit,
                    sort_by='displayName',
                    sort_order='ASCENDING',
                    attribute_sets=['never'],
                )
                if user_response.data is None or not user_response.data.resources:
                    break
                yield from user_response.data.resources
                if len(user_response.data.resources) < limit or start_index + limit > user_response.data.total_results:
                    break
                start_index += limit

        import threading

        def fetch_full_user(u):
            try:
                thread_id = threading.get_ident()
                thread_name = threading.current_thread().name
                logger.debug(
                    f"Thread {thread_name} (id={thread_id}) starting fetch_full_user for user_id={getattr(u, 'id', None)} display_name={getattr(u, 'display_name', None)}"
                )
                user_attributes = self._api_call_with_logging(
                    'IdentityDomainsClient.get_user',
                    domain_client.get_user,
                    user_id=u.id,
                    attribute_sets=['all'],
                ).data
                logger.debug(
                    f"Thread {thread_name} (id={thread_id}) finished fetch_full_user for user_id={getattr(u, 'id', None)} display_name={getattr(u, 'display_name', None)}"
                )
                groups_list = (
                    [gg.ocid for gg in getattr(user_attributes, 'groups', []) if hasattr(gg, 'ocid')]
                    if hasattr(user_attributes, 'groups') and user_attributes.groups
                    else []
                )
                email = 'None'
                if hasattr(user_attributes, 'emails') and user_attributes.emails:
                    for em in user_attributes.emails:
                        if getattr(em, 'primary', False):
                            email = em.value
                            break
                return User(
                    domain_name=domain.display_name,
                    user_name=u.user_name,
                    user_ocid=u.ocid,
                    display_name=u.display_name,
                    email=email,
                    user_id=u.id,
                    groups=groups_list,
                )
            except Exception as exc:
                logger.error(f'Failed to fetch user detail for {u.display_name}: {exc}')
                return None

        # Thread pool for get_user calls, incrementally append to self.users
        try:
            from threading import Lock

            user_list = []
            user_lock = Lock()
            with ThreadPoolExecutor(max_workers=THREADS) as executor:
                futures = []
                for user_summary in user_summary_generator():
                    futures.append(executor.submit(fetch_full_user, user_summary))
                for f in as_completed(futures):
                    result = f.result()
                    if result:
                        # Append incrementally, with lock for thread safety with GUI callbacks
                        with user_lock:
                            self.users.append(result)
                        user_list.append(result)
            logger.info(f'Fetched {len(user_list)} users for domain: {domain.display_name}')
        except Exception as e:
            logger.error(f'Exception during user fetch: {e}')

        return user_list

    def load_complete_identity_domains(
        self, load_all_users: bool = True, compartment_domain_search_depth: int = 1
    ) -> bool:
        """
        Loads users, groups, dynamic groups, and domains for all compartments up to the given depth
        below the root compartment.
        """

        try:
            seen_domain_ids = set()
            all_domains = []

            def add_domains_from_compartment(compartment_id: str) -> bool:
                resp = self._api_call_with_logging(
                    'IdentityClient.list_domains', self.identity_client.list_domains, compartment_id=compartment_id
                )
                logger.info(
                    f'Listed domains for compartment {compartment_id}: {len(resp.data) if resp and resp.data else 0}'
                )
                if resp.data is None:
                    logger.error('Failed to list identity domains for compartment %s', compartment_id)
                    return False
                for d in resp.data:
                    if d.id not in seen_domain_ids:
                        seen_domain_ids.add(d.id)
                        all_domains.append(d)
                return True

            # Ensure compartments are loaded (critical for depth BFS)
            if not hasattr(self, 'compartments') or not self.compartments:
                logger.info('Compartments not loaded yet; calling load_policies_and_compartments() to load.')
                self.load_policies_and_compartments()
            if not self.compartments:
                logger.error('Compartment load failed or returned empty. Falling back to root-only search.')
                compartments_to_enumerate = [self.tenancy_ocid]
            else:
                parent_map = collections.defaultdict(list)
                for comp in self.compartments:
                    parent_id = comp.get('parent_id') or self.tenancy_ocid
                    parent_map[parent_id].append(comp)
                cur_level = [self.tenancy_ocid]
                all_ocids = set(cur_level)
                for _lvl in range(1, max(1, compartment_domain_search_depth)):
                    next_level = []
                    for cid in cur_level:
                        for child in parent_map.get(cid, []):
                            child_id = child.get('id')
                            if child_id and child_id not in all_ocids:
                                next_level.append(child_id)
                                all_ocids.add(child_id)
                    cur_level = next_level
                    if not cur_level:
                        break
                compartments_to_enumerate = list(all_ocids)

            logger.info(
                f'Enumerating domains from compartments at depth {compartment_domain_search_depth}: {compartments_to_enumerate}'
            )

            for comp_ocid in compartments_to_enumerate:
                logger.info(f'Calling add_domains_from_compartment with: {comp_ocid}')
                if not add_domains_from_compartment(comp_ocid):
                    return False

            self.identity_domains = all_domains
            logger.info(
                'Loaded %s identity domains from %s compartments',
                len(self.identity_domains),
                len(compartments_to_enumerate),
            )

            self.domain_clients = {}

            for domain in self.identity_domains:
                try:
                    # Get IdentityDomainsClient and hold on to it
                    if self.use_instance_principal or self.use_resource_principal:
                        domain_client = IdentityDomainsClient(
                            config={}, signer=self.signer, service_endpoint=domain.url
                        )
                    elif self.session_token:
                        logger.info('Session auth for IdentityDomainsClient')
                        self.config = config.from_file(profile_name=self.session_token)
                        token_file = self.config['security_token_file']
                        token = None
                        with open(token_file) as f:
                            token = f.read()
                        private_key = load_private_key_from_file(self.config['key_file'])
                        self.signer = SecurityTokenSigner(token, private_key)
                        domain_client = IdentityDomainsClient(
                            {'region': self.config['region']}, signer=self.signer, service_endpoint=domain.url
                        )
                        self.tenancy_ocid = self.config['tenancy']
                        logger.info('Success session auth')
                    else:
                        domain_client = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
                    self.domain_clients[domain.id] = domain_client

                    # --- Orchestrate loading of Dynamic Groups, Groups, and Users with comments, timing, and logging ---

                    # Use log level per settings for timing (critical if "Log All Timings" enabled, info otherwise)
                    log_critical = False
                    try:
                        if self.settings and isinstance(self.settings, dict):
                            log_critical = self.settings.get('always_log_api_calls', False)
                    except Exception:
                        pass
                    timing_logger = logger.critical if log_critical else logger.info

                    # Fetch and aggregate Dynamic Groups
                    t0 = time.perf_counter()
                    dg_list = self._fetch_dynamic_groups_for_domain(domain, domain_client)
                    elapsed = time.perf_counter() - t0
                    timing_logger(
                        f'[API] _fetch_dynamic_groups_for_domain got {len(dg_list)} dynamic groups for {domain.display_name} completed in {elapsed:.2f}s'
                    )
                    # Dynamic groups have already been incrementally appended in _fetch_dynamic_groups_for_domain

                    # Fetch and aggregate Groups
                    t0 = time.perf_counter()
                    group_list = self._fetch_groups_for_domain(domain, domain_client)
                    elapsed = time.perf_counter() - t0
                    timing_logger(
                        f'[API] _fetch_groups_for_domain got {len(group_list)} groups for {domain.display_name} completed in {elapsed:.2f}s'
                    )
                    # Groups are already appended incrementally

                    # Fetch and aggregate Users (only if enabled)
                    if load_all_users:
                        t0 = time.perf_counter()
                        user_list = self._fetch_users_for_domain(domain, domain_client)
                        elapsed = time.perf_counter() - t0
                        timing_logger(
                            f'[API] _fetch_users_for_domain got {len(user_list)} users for {domain.display_name} completed in {elapsed:.2f}s'
                        )
                        # Users are already appended incrementally
                    else:
                        self.users = []

                    self.data_as_of = str(datetime.now(UTC))

                except Exception as e:
                    logger.error(f'Failed to load groups/users for domain {domain.id}: {e}')
                    raise
            logger.info(
                f'Loaded {len(self.groups)} groups, {len(self.users)} users, {len(self.dynamic_groups)} dynamic groups across all domains'
            )
            # Set this so that callback can stop any waiting
            self.identity_loaded_from_tenancy = True

            return True
        except Exception as e:
            logger.error(f'Failed to load identity domains: {e}')
            # return False
            raise e

    def _enrich_compartments_with_statement_counts(self):
        """
        For each compartment, assign:
        - statement_count_direct: # of policy statements defined directly in this compartment.
        - statement_count_cumulative: cumulative total including ancestors.
        """
        # Build direct count for each compartment by OCID using up-to-date self.regular_statements
        statements = getattr(self, 'regular_statements', []) or []
        direct_statement_count = {}
        for st in statements:
            coid = st.get('compartment_ocid')
            if not coid:
                continue
            direct_statement_count[coid] = direct_statement_count.get(coid, 0) + 1
        # Assign direct count
        for comp in self.compartments or []:
            comp_id = comp.get('id')
            comp['statement_count_direct'] = direct_statement_count.get(comp_id, 0)
        # Now cumulative (for each compartment, sum direct count for self and all ancestors)
        comp_by_id = {c.get('id'): c for c in self.compartments or []}
        for comp in self.compartments or []:
            cumulative = 0
            c = comp
            visited = set()
            while c:
                cid = c.get('id')
                if cid in visited or not cid:
                    break
                cumulative += direct_statement_count.get(cid, 0)
                visited.add(cid)
                pid = c.get('parent_id')
                if not pid or pid == cid or pid not in comp_by_id:
                    break
                c = comp_by_id[pid]
            comp['statement_count_cumulative'] = cumulative

    # --- Main Filtering Functions ---
    # Filtering logic - return a list of policy statements matching given filter
    # Single policy filter function that resolves fuzzy search if provided, exact search if provided, and then other criteria if provided
    # If multiple criteria are provided, they are ANDed together
    # If multiple values are provided for a single criteria, they are ORed together
    # If no criteria are provided, return all policy statements
    # If no policy statements exist, return empty list
    # Fuzzy and Exact search are mutually exclusive - if both are provided, fuzzy search is used
    # If Identity Domains are not loaded and either fuzzy or exact search is requested, raise an error
    def filter_policy_statements(  # noqa: C901
        self,
        filters: PolicySearch,
        *,
        statements: list[RegularPolicyStatement] | None = None,
    ) -> list[RegularPolicyStatement]:
        """
        Filter policy statements by one or more criteria.

        Args:
            filters (PolicySearch): Dictionary of filter keys and their values (e.g. verb, resource, permission, group, etc).
            statements: Optional alternate list of policy-like statements to filter.
                When provided, this list is filtered instead of the repository's
                ``regular_statements``. This is useful for applying the same
                JSON filter semantics to **prospective** or simulated statement
                sets that are not part of the loaded tenancy data.

        Returns:
            list[PolicyStatement]: List of statements matching the filter.
        """
        logger.info('Filtering policy statements with criteria: %s', filters)

        # If fuzzy or exact search is requested, identity domains must be loaded. If not, raise an error
        # Previously, filtering by group/user/dynamic-group required identity_domains_loaded.
        # This check and logic has been removed per requirements; filtering will proceed regardless.

        # If fuzzy search is provided, use it and ignore exact search.
        self._resolve_fuzzy_search(filters=filters)
        # If exact users were provided for filtering, resolve them to domain/name tuples
        self._resolve_exact_users(filters=filters)

        # At this point we have exact groups or exact dynamic groups to deal with
        logger.debug(f'Post-fuzzy/exact search filters: {filters}')

        # Choose the candidate list to filter. If an explicit list of
        # statements is passed (e.g., prospective/what-if statements
        # normalized to the same shape), filter that instead of the
        # repository's canonical regular_statements.
        candidate_statements = statements if statements is not None else self.regular_statements

        # Apply regular search - AND all provided fields except fuzzy search
        results = []
        tag_filter_keys = TAG_FILTER_FIELDS & set(filters)

        for stmt in candidate_statements:
            match = True

            for key, values in filters.items():
                if key in TAG_FILTER_FIELDS:
                    if key != sorted(tag_filter_keys)[0]:
                        continue
                    if not TagBasedPolicyService.matches_tag_filters(stmt, filters):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to tag condition filter mismatch')
                        match = False
                        break
                elif key == 'condition_atom_terms':
                    if not TagBasedPolicyService.matches_condition_atom_terms(stmt, values):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to condition atom term mismatch')
                        match = False
                        break
                elif key in POLICY_TAG_FILTER_FIELDS:
                    if not TagBasedPolicyService.matches_policy_metadata_tags(stmt, key, values):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to policy metadata tag mismatch')
                        match = False
                        break
                elif key == 'principal_key':
                    raw_values = values if isinstance(values, list) else [values]
                    expected_keys = {str(v).strip() for v in raw_values if str(v).strip()}
                    if not expected_keys:
                        continue

                    statement_keys: set[str] = set()
                    direct_keys = stmt.get('principal_keys')
                    if isinstance(direct_keys, list):
                        statement_keys.update(str(k).strip() for k in direct_keys if str(k).strip())
                    direct_key = stmt.get('principal_key')
                    if isinstance(direct_key, str) and direct_key.strip():
                        statement_keys.add(direct_key.strip())
                    principals = stmt.get('principals')
                    if isinstance(principals, list):
                        for principal in principals:
                            if isinstance(principal, dict):
                                pkey = principal.get('principal_key')
                                if isinstance(pkey, str) and pkey.strip():
                                    statement_keys.add(pkey.strip())

                    if not statement_keys:
                        # Legacy fallback for statements that predate principal key enrichment.
                        self._build_principals_from_statement(stmt)
                        principals = stmt.get('principals')
                        if isinstance(principals, list):
                            for principal in principals:
                                if isinstance(principal, dict):
                                    pkey = principal.get('principal_key')
                                    if isinstance(pkey, str) and pkey.strip():
                                        statement_keys.add(pkey.strip())

                    if not (statement_keys & expected_keys):
                        logger.debug(
                            'Rejecting %s due to principal_key mismatch: expected=%s statement_keys=%s',
                            stmt.get('policy_name'),
                            sorted(expected_keys),
                            sorted(statement_keys),
                        )
                        match = False
                        break

                elif key == 'exact_groups':
                    # Get the groups from the exact filter
                    logger.debug(f'Filtering on exact_groups with values: {values}')
                    groups_filter = filters.get('exact_groups', []) or []
                    subject_type = (stmt.get('subject_type') or '').lower()
                    if subject_type not in ('group', 'group-id'):
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to subject_type not group/group-id")
                        match = False
                        break
                    subjects = stmt.get('subject', [])
                    if not isinstance(subjects, list):
                        logger.warning(f'Unexpected Subject format in statement {stmt.get("policy_name")}: {subjects}')
                        match = False
                        break
                    if len(groups_filter) == 0:
                        logger.debug('No groups in exact_groups filter, thus no match possible')
                        match = False
                        break
                    group_name_refs = set()
                    group_ocid_refs = set()
                    for group in groups_filter:
                        group_domain = (group.get('domain_name') or 'default').strip()
                        group_name = (group.get('group_name') or '').strip()
                        if group_name:
                            group_name_refs.add((group_domain.casefold(), group_name.casefold()))
                        group_ocid = (group.get('group_ocid') or '').strip()
                        if group_ocid:
                            group_ocid_refs.add(group_ocid.casefold())
                        elif group_name:
                            resolved = next(
                                (
                                    g
                                    for g in self.groups
                                    if (g.get('group_name') or '').casefold() == group_name.casefold()
                                    and (g.get('domain_name') or 'default').casefold() == group_domain.casefold()
                                ),
                                None,
                            )
                            if resolved and resolved.get('group_ocid'):
                                group_ocid_refs.add(str(resolved.get('group_ocid')).casefold())

                    subj_matched = False
                    if subject_type == 'group':
                        for subj_domain, subj_name in subjects:
                            subj_domain_str = str(subj_domain or 'default').casefold()
                            subj_name_str = str(subj_name or '').casefold()
                            if (subj_domain_str, subj_name_str) in group_name_refs:
                                logger.debug(
                                    f'Matched group {subj_domain}/{subj_name} in statement {stmt.get("policy_name")} to exact_groups filter'
                                )
                                subj_matched = True
                                break
                    else:
                        for subj in subjects:
                            ocid = None
                            if isinstance(subj, tuple | list) and len(subj) >= 2:
                                ocid = subj[1]
                            elif isinstance(subj, str):
                                ocid = subj
                            if ocid and str(ocid).casefold() in group_ocid_refs:
                                logger.debug(
                                    f'Matched group-id {ocid} in statement {stmt.get("policy_name")} to exact_groups filter'
                                )
                                subj_matched = True
                                break
                    if not subj_matched:
                        logger.debug(
                            f'No match found for exact_group filter in statement {stmt.get("policy_name")} Text: {stmt.get("statement_text")} Statement: {stmt.get("subject")}'
                        )
                        match = False  # If we get here, no match found
                        break

                # For exact dynamic group, similar logic
                elif key == 'exact_dynamic_groups' and values:
                    logger.debug(f'Filtering on exact_dynamic_groups with values: {values}')
                    dyn_groups_filter = filters.get('exact_dynamic_groups', []) or []
                    subject_type = (stmt.get('subject_type') or '').lower()
                    if subject_type not in ('dynamic-group', 'dynamic-group-id'):
                        logger.debug(
                            f"Rejecting {stmt.get('policy_name')} due to Subject Type not dynamic-group/dynamic-group-id"
                        )
                        match = False
                        break
                    subjects = stmt.get('subject', [])
                    if not isinstance(subjects, list):
                        logger.warning(f'Unexpected Subject format in statement {stmt.get("policy_name")}: {subjects}')
                        match = False
                        break
                    dg_name_refs = set()
                    dg_ocid_refs = set()
                    for dg in dyn_groups_filter:
                        dg_domain = (dg.get('domain_name') or 'default').strip()
                        dg_name = (dg.get('dynamic_group_name') or '').strip()
                        if dg_name:
                            dg_name_refs.add((dg_domain.casefold(), dg_name.casefold()))
                        dg_ocid = (dg.get('dynamic_group_ocid') or '').strip()
                        if dg_ocid:
                            dg_ocid_refs.add(dg_ocid.casefold())
                        elif dg_name:
                            resolved = next(
                                (
                                    d
                                    for d in self.dynamic_groups
                                    if (d.get('dynamic_group_name') or '').casefold() == dg_name.casefold()
                                    and (d.get('domain_name') or 'default').casefold() == dg_domain.casefold()
                                ),
                                None,
                            )
                            if resolved and resolved.get('dynamic_group_ocid'):
                                dg_ocid_refs.add(str(resolved.get('dynamic_group_ocid')).casefold())

                    subj_matched = False
                    if subject_type == 'dynamic-group':
                        for subj_domain, subj_name in subjects:
                            subj_domain_str = str(subj_domain or 'default').casefold()
                            subj_name_str = str(subj_name or '').casefold()
                            if (subj_domain_str, subj_name_str) in dg_name_refs:
                                logger.debug(
                                    f'Matched dynamic group {subj_domain}/{subj_name} in statement {stmt.get("policy_name")} to exact_dynamic_groups filter'
                                )
                                subj_matched = True
                                break
                    else:
                        for subj in subjects:
                            ocid = None
                            if isinstance(subj, tuple | list) and len(subj) >= 2:
                                ocid = subj[1]
                            elif isinstance(subj, str):
                                ocid = subj
                            if ocid and str(ocid).casefold() in dg_ocid_refs:
                                logger.debug(
                                    f'Matched dynamic-group-id {ocid} in statement {stmt.get("policy_name")} to exact_dynamic_groups filter'
                                )
                                subj_matched = True
                                break
                    if not subj_matched and dg_ocid_refs:
                        principals = stmt.get('principals', [])
                        for principal in principals if isinstance(principals, list) else []:
                            ocid = None
                            if isinstance(principal, dict):
                                ocid = principal.get('ocid')
                                if not ocid:
                                    principal_key = principal.get('principal_key')
                                    if isinstance(principal_key, str) and ':' in principal_key:
                                        _prefix, candidate = principal_key.split(':', 1)
                                        ocid = candidate
                            if ocid and str(ocid).casefold() in dg_ocid_refs:
                                logger.debug(
                                    f'Matched dynamic group OCID {ocid} via principals in statement {stmt.get("policy_name")}'
                                )
                                subj_matched = True
                                break
                    if not subj_matched:
                        logger.debug(
                            f'No match found for exact_dynamic_groups filter in statement {stmt.get("policy_name")} Text: {stmt.get("statement_text")} Statement: {stmt.get("subject")}'
                        )
                        match = False  # If we get here, no match found
                        break
                # Compartment special: ROOTONLY
                elif key == 'compartment_path' and 'ROOTONLY' in values:
                    if stmt.get('compartment_ocid') != self.tenancy_ocid:
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to ROOTONLY restriction')
                        match = False
                        break
                elif key == 'location' and 'tenancy' in values:
                    if stmt.get('location_type', '').casefold() != 'tenancy':
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to location not tenancy')
                        match = False
                        break
                # Once domain cases are done, iterate remaining values
                # Verb enum
                elif key == 'verb':
                    invalid = set(values) - VALID_VERBS
                    if invalid:
                        logger.debug(f'Invalid verbs in filter: {invalid}')
                    field_value = str(stmt.get('verb', '')).lower()
                    if field_value not in values:
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to verb mismatch: {field_value}')
                        match = False
                        break
                # Validity check
                elif key == 'valid':
                    valid_value = values
                    statement_valid_value = stmt.get('valid', False)
                    logger.debug(f'Filtering on validity: {valid_value} vs {statement_valid_value}')
                    if valid_value != statement_valid_value:
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to validity mismatch')
                        match = False
                        break
                # Effective path search
                elif key == 'effective_path':
                    raw_values = values if isinstance(values, list) else [values]
                    filter_eff_values = [str(v).strip().lower() for v in raw_values if str(v).strip()]
                    if not filter_eff_values:
                        continue
                    statement_eff_value = str(stmt.get('effective_path', '')).lower()
                    logger.debug(f'Filtering on filt/st {filter_eff_values} vs {statement_eff_value}')
                    # Logic here - if the effective path given contains the effective path of the statement,
                    # then it is a match.  This allows searching for all policies effective in a given compartment and its children.
                    if not any(
                        filter_eff_value.startswith(statement_eff_value) for filter_eff_value in filter_eff_values
                    ):
                        logger.debug(
                            f'Rejecting {stmt.get("policy_name")} due to effective_path mismatch: '
                            f'{statement_eff_value} not in any of {filter_eff_values}'
                        )
                        match = False
                        break
                # Permission list search (OR logic across provided values)
                elif key == 'permission':
                    stmt_permissions = stmt.get('permission', [])
                    if isinstance(stmt_permissions, str):
                        stmt_permissions_list = [stmt_permissions]
                    elif isinstance(stmt_permissions, list):
                        stmt_permissions_list = [str(p) for p in stmt_permissions]
                    else:
                        stmt_permissions_list = [str(stmt_permissions)]

                    stmt_perm_ci = [p.lower() for p in stmt_permissions_list if p]
                    raw_values = values if isinstance(values, list) else [values]
                    value_ci = [str(v).lower() for v in raw_values if str(v).strip()]

                    if not value_ci:
                        continue

                    if not any(any(v in perm for perm in stmt_perm_ci) for v in value_ci):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to permission mismatch')
                        match = False
                        break
                elif key == 'principal_keys':
                    raw_values = values if isinstance(values, list) else [values]
                    principal_keys = [str(v).strip() for v in raw_values if str(v).strip()]
                    if not principal_keys:
                        continue
                    if not any(
                        self._principal_key_matches_statement(stmt, principal_key) for principal_key in principal_keys
                    ):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to principal_key mismatch')
                        match = False
                        break
                elif key in {'principal', 'principals'}:
                    raw_values = values if isinstance(values, list) else [values]
                    principal_selectors = [v for v in raw_values if isinstance(v, dict)]
                    if not principal_selectors:
                        continue
                    match_details = next(
                        (
                            details
                            for selector in principal_selectors
                            if (details := self._principal_match_details(stmt, selector)) is not None
                        ),
                        None,
                    )
                    if match_details is None:
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to principal selector mismatch')
                        match = False
                        break
                    match_confidence = str(match_details.get('match_confidence') or '')
                    if match_confidence != 'matched':
                        stmt = RegularPolicyStatement(
                            {
                                **stmt,
                                'match_confidence': match_confidence,
                                'confidence': stmt.get('confidence') or match_confidence,
                                'match_confidence_reason': match_details.get('match_confidence_reason') or '',
                                'principal_evidence': match_details.get('principal_evidence') or [],
                                'residual_conditions': match_details.get('residual_conditions') or [],
                            }
                        )
                elif key == 'subject':
                    raw_values = values if isinstance(values, list) else [values]
                    value_ci = [str(v).strip() for v in raw_values if str(v).strip()]
                    if not value_ci:
                        continue
                    if not any(self._subject_token_matches_statement(stmt, token) for token in value_ci):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to principal/subject mismatch')
                        match = False
                        break
                # Default lookup using column map
                else:
                    column = key
                    logger.debug(f'Filtering on {key} mapped to column {column} with values {values}')
                    if not column or not values:
                        logger.debug(f'Unknown filter key: {key} or values empty, skipping')
                        continue
                    field_value = str(stmt.get(column, '')).lower()
                    raw_values = values if isinstance(values, list) else [values]
                    if not any(str(val).lower() in field_value for val in raw_values):
                        logger.debug(f'Rejecting {stmt.get("policy_name")} due to {key} mismatch')
                        match = False
                        break

            if match:
                results.append(stmt)

        logger.info(
            'Filter applied. %d matched out of %d Regular statements.',
            len(results),
            len(candidate_statements),
        )
        return results

    def filter_cross_tenancy_policy_statements(self, alias_filter: list[str]) -> list[RegularPolicyStatement]:
        """
        Filter cross-tenancy policy statements containing any provided alias.

        Args:
            alias_filter (list[str]): List of aliases to look for in statement text.

        Returns:
            list[PolicyStatement]: Filtered cross-tenancy policy statements.
        """
        filtered = []
        for statement in self.cross_tenancy_statements:
            for alias_to_check in alias_filter:
                # Check each alias to see if in statement text
                statement_text = statement.get('statement_text', '')
                if alias_to_check in statement_text:
                    logger.debug(f'Adding statement (alias={alias_to_check}): {statement_text}')
                    filtered.append(statement)
        logger.info(f'Returning {len(filtered)} Cross-Tenancy Results')
        return filtered

    # -- Identity Domain Related Filtering Functions ---
    def get_users_for_group(self, group: Group) -> list[User]:
        """
        Return all users that belong to the specified exact group.  Membership is determined by matching the group name and domain name.

        Args:
            group (Group): A dictionary with keys:
                - 'domain': str | None
                - 'name': str

        Returns:
            list[User]: A list of Users that belong to the specified group. If the group does not exist or has no members, returns an empty list.
        """
        group_domain = group.get('domain_name') or 'default'
        group_name = group['group_name']
        logger.debug(f'Number of groups: {len(self.groups)}  Number of users: {len(self.users)}')
        # Get GID (as it is used by users)
        group_ocid = None
        for g in self.groups:
            if (
                g.get('group_name', '').casefold() == group_name.casefold()
                and g.get('domain_name', '').casefold() == group_domain.casefold()
            ):
                group_ocid = g.get('group_ocid')
                break
        if not group_ocid:
            logger.warning(f'Group not found: {group_domain}/{group_name}')
            return []
        logger.debug(f'Group OCID: {group_ocid}')
        # now iterate users and see if any have that OCID in their groups field
        matched_users = [u for u in self.users if group_ocid in u.get('groups', [])]

        logger.info(f'Found {len(matched_users)} users for group {group_domain}/{group_name}')
        return matched_users

    def get_groups_for_user(self, user: User) -> list[Group]:
        """Return the list of all Groups that a user is a member of

        Args:
            user (User): The user to find groups for.

        Returns:
            list[Group]: A list of Groups that the user is a member of.
        """
        groups_for_user: list[Group] = []
        logger.info(f'User to filter: {user}')
        logger.debug(f'Users: {self.users}')

        # Iterate through users to find our user
        for u in self.users:
            # Match the tuple
            if (
                u.get('user_name', '').casefold() == user.get('user_name').casefold()
                and u.get('domain_name', 'default').casefold() == user.get('domain_name', 'default').casefold()
            ):
                logger.debug(f'User found. Groups: {u.get("groups")}')

                # hold that thought...
                for user_group_ocid in u.get('groups', []):
                    # Find the Group OCID in the groups and append
                    for g in self.groups:
                        if g.get('group_ocid') == user_group_ocid:
                            # Now append as tuple
                            groups_for_user.append(g)
                            logger.debug(f'Adding Group {g.get("domain_name")} / {g.get("group_name")} ')
        logger.info(f'Found {len(groups_for_user)} groups for user {user.get("domain_name")} / {user.get("user_name")}')
        return groups_for_user

    def _user_search_internal(self, user_filter: UserSearch) -> list[User]:
        """
        Search for users based on the provided filter.
        Using the internal names in the User object
        """
        logger.info(f'User filter to check: {user_filter}')
        users_return: list[User] = []
        for u in self.users:
            # for uu in user_filter:
            matches_domain = not user_filter.get('domain_name') or any(
                term.lower() in str(u.get('domain_name')).lower() for term in user_filter.get('domain_name')
            )
            matches_username = not user_filter.get('search') or any(
                term.lower() in str(u.get('user_name')).lower() for term in user_filter.get('search')
            )
            matches_display = not user_filter.get('search') or any(
                term.lower() in str(u.get('display_name')).lower() for term in user_filter.get('search')
            )
            matches_ocid = not user_filter.get('user_ocid') or any(
                term.lower() in str(u.get('user_ocid')).lower() for term in user_filter.get('user_ocid')
            )
            # If any match (OR), then get groups and add to exact match
            if matches_domain and (matches_username or matches_display) and matches_ocid:
                # get groups for user
                logger.debug(f'Found a user match: {u} / {user_filter}')
                users_return.append(u)

        logger.info(f'User Search got {len(users_return)} users')
        return users_return

    def _group_search_internal(self, group_filter: GroupSearch) -> list[Group]:
        """
        Search for groups based on the provided filter.
        Using the internal names in the User object
        """
        logger.info(f'Group filter to check: {group_filter}')
        groups_return: list[Group] = []
        for g in self.groups:
            matches_name = not group_filter.get('group_name') or any(
                term.lower() in str(g.get('group_name')).lower() for term in group_filter.get('group_name')
            )
            matches_domain = not group_filter.get('domain_name') or any(
                term.lower() in str(g.get('domain_name')).lower()
                for term in group_filter.get('domain_name', ['default'])
            )
            matches_ocid = not group_filter.get('group_ocid') or any(
                term.lower() in str(g.get('group_ocid')).lower() for term in group_filter.get('group_ocid')
            )
            if matches_name and matches_domain and matches_ocid:
                groups_return.append(g)
        logger.info(f'Group Search returning {len(groups_return)} groups')
        return groups_return

    def _dynamic_group_search_internal(self, dg_filter: DynamicGroupSearch) -> list[DynamicGroup]:
        """Search for dynamic groups based on the provided filter."""
        logger.info(f'Dynamic Group filter to check: {dg_filter}')
        dgs_return: list[DynamicGroup] = []
        for dg in self.dynamic_groups:
            matches_name = not dg_filter.get('dynamic_group_name') or any(
                term in str(dg.get('dynamic_group_name')).lower() for term in dg_filter.get('dynamic_group_name')
            )
            matches_domain = not dg_filter.get('domain_name') or any(
                term in str(dg.get('domain_name')).lower() for term in dg_filter.get('domain_name', ['default'])
            )
            matches_ocid = not dg_filter.get('dynamic_group_ocid') or any(
                term in str(dg.get('dynamic_group_ocid')).lower() for term in dg_filter.get('dynamic_group_ocid')
            )
            matches_rule = not dg_filter.get('matching_rule') or any(
                term in str(dg.get('matching_rule')).lower() for term in dg_filter.get('matching_rule')
            )
            matches_description = not dg_filter.get('description') or any(
                term in str(dg.get('description')).lower() for term in dg_filter.get('description')
            )
            if matches_name and matches_domain and matches_ocid and matches_rule and matches_description:
                dgs_return.append(
                    {
                        'domain_name': dg.get('domain_name'),
                        'dynamic_group_name': dg.get('dynamic_group_name'),
                        'dynamic_group_ocid': dg.get('dynamic_group_ocid'),
                    }
                )
        logger.info(f'Dynamic Group Search returning {len(dgs_return)} dynamic groups')
        return dgs_return

    def _resolve_fuzzy_search(self, filters: PolicySearch):
        """Look for fuzzy search and turn it into an exact search"""
        logger.debug(f'Resolve fuzzy Groups: {filters.get("search_groups")}')
        logger.debug(f'Resolve fuzzy Users: {filters.get("search_users")}')
        logger.debug(f'Resolve fuzzy DG: {filters.get("search_dynamic_groups")}')

        def _add_principals(principals: list[Principal]) -> None:
            existing = filters.get('principals', []) or []
            if not isinstance(existing, list):
                existing = []
            existing.extend(principals)
            filters['principals'] = existing

        def _group_principal(group: Group) -> Principal:
            principal: Principal = {
                'principal_type': 'group',
                'domain_name': group.get('domain_name') or 'Default',
                'name': group.get('group_name') or '',
            }
            if group.get('group_ocid'):
                principal['ocid'] = str(group.get('group_ocid'))
            return principal

        def _dynamic_group_principal(dynamic_group: DynamicGroup) -> Principal:
            principal: Principal = {
                'principal_type': 'dynamic-group',
                'domain_name': dynamic_group.get('domain_name') or 'Default',
                'name': dynamic_group.get('dynamic_group_name') or '',
            }
            if dynamic_group.get('dynamic_group_ocid'):
                principal['ocid'] = str(dynamic_group.get('dynamic_group_ocid'))
            return principal

        def _user_principal(user: User) -> Principal:
            principal: Principal = {
                'principal_type': 'user',
                'domain_name': user.get('domain_name') or 'Default',
                'name': user.get('user_name') or '',
            }
            if user.get('user_ocid'):
                principal['ocid'] = str(user.get('user_ocid'))
            return principal

        # First do fuzzy user search
        if filters.get('search_users'):
            user_filter: UserSearch = filters.get('search_users')
            logger.info(f'User filter to check: {user_filter}')
            filtered_users = self._user_search_internal(user_filter)
            logger.info(f'User search returned {len(filtered_users)} users')
            _add_principals([_user_principal(user) for user in filtered_users])
            del filters['search_users']
            logger.info(f'Added {len(filtered_users)} user principals to filter (removed fuzzy user search)')
        # Next, fuzzy group search
        elif filters.get('search_groups'):
            group_filter: GroupSearch = filters.get('search_groups')
            matching_groups: list[Group] = self._group_search_internal(group_filter)
            _add_principals([_group_principal(group) for group in matching_groups])
            # remove the fuzzy search
            del filters['search_groups']
            logger.info(f'Added {len(matching_groups)} group principals to filter')
        # Finally, fuzzy dynamic group search
        elif filters.get('search_dynamic_groups'):
            dg_filter: DynamicGroupSearch = filters.get('search_dynamic_groups')
            matching_dgs: list[DynamicGroup] = self._dynamic_group_search_internal(dg_filter)
            _add_principals([_dynamic_group_principal(dg) for dg in matching_dgs])
            # Remove fuzzy search
            del filters['search_dynamic_groups']
            logger.info(f'Added {len(matching_dgs)} dynamic group principals to filter')
        else:
            logger.debug('No fuzzy logic executed, search not changed.')

    def _resolve_exact_users(self, filters: PolicySearch):
        """Look for exact users and turn them into user principal selectors."""
        if not filters.get('exact_users'):
            return
        user_filter: list[User] = filters.get('exact_users')
        logger.info(f'Exact User filter to check: {user_filter}')
        principals: list[Principal] = []
        for user in user_filter:
            principal: Principal = {
                'principal_type': 'user',
                'domain_name': user.get('domain_name') or 'Default',
                'name': user.get('user_name') or '',
            }
            if user.get('user_ocid'):
                principal['ocid'] = str(user.get('user_ocid'))
            principals.append(principal)
        existing = filters.get('principals', []) or []
        if not isinstance(existing, list):
            existing = []
        existing.extend(principals)
        filters['principals'] = existing
        del filters['exact_users']
        logger.info(f'Exact User Search added {len(principals)} user principals to filter')

    def filter_groups(self, group_filter: GroupSearch) -> list[Group]:
        """Filter groups based on the provided filter.  Public function used by MCP or UI"""
        filtered = []
        logger.info(f'Filtering Groups based on: {group_filter}')

        filtered: list[Group] = self._group_search_internal(group_filter)

        logger.info(f'Filtered to {len(filtered)} groups')
        return filtered

    def filter_users(self, user_filter: UserSearch) -> list[User]:
        """
        Filter users based on the provided filter.

        This function is used by the MCP interface and the UI.

        Args:
            user_filter (UserSearch):
                A dictionary with optional keys.

                * ``domain_name`` (list[str]): Domain names to filter by (case-insensitive).
                * ``search`` (list[str]): Search terms to match against usernames and display names (case-insensitive).
                * ``user_ocid`` (list[str]): User OCIDs to filter by (case-insensitive).

        Returns:
            list[User]:
                Users that match the filter criteria.

                Each :class:`User` is represented as a dictionary with keys:

                * ``domain_name`` (str | None): Domain name of the user.
                * ``user_name`` (str): Username.
                * ``user_ocid`` (str): OCID of the user.
                * ``display_name`` (str): Display name of the user.
                * ``email`` (str): Email of the user.
                * ``user_id`` (str): Internal ID of the user.
                * ``groups`` (list[str]): Group OCIDs the user belongs to.
        """

        logger.info(f'Filtering Users (public) based on: {user_filter}')
        filtered_users: list[User] = self._user_search_internal(user_filter)

        logger.info(f'Filtered to {len(filtered_users)} users')
        for u in filtered_users:
            logger.debug(f'User: {u.get("domain_name")}/{u.get("user_name")} Name:"{u.get("display_name")}"')
        return filtered_users

    def filter_dynamic_groups(self, filters: DynamicGroupSearch) -> list[DynamicGroup]:
        """
        Filter dynamic groups using JSON-based filters.

        Args:
            filters (DynamicGroupSearch): A mapping of filter keys to one or more values.

                - **OR**: multiple values within a field act as logical OR.
                - **AND**: multiple fields are combined as logical AND.

                **Supported keys:**
                * ``domain_name`` → matches "Domain"
                * ``dynamic_group_name`` → matches "DG Name"
                * ``matching_rule`` → matches "Matching Rule"
                * ``dynamic_group_ocid`` → matches "DG OCID"
                * ``in_use`` → matches "In Use" (True/False)

        Returns:
            list[DynamicGroup]: A list of dynamic groups that satisfy the filters.

                Each dynamic group is represented as a dictionary with keys:
                * ``domain_name`` (str | None): The domain name of the dynamic group.
                * ``dynamic_group_name`` (str): The name of the dynamic group.
                * ``dynamic_group_id`` (str): The ID of the dynamic group.
                * ``dynamic_group_ocid`` (str): The OCID of the dynamic group.
                * ``matching_rule`` (str): The matching rule of the dynamic group.
                * ``description`` (str): The description of the dynamic group.
                * ``in_use`` (bool): Whether the dynamic group is in use.
                * ``creation_time`` (str): The creation timestamp of the dynamic group.
                * ``created_by_name`` (str): The name of the user who created the dynamic group.
                * ``created_by_ocid`` (str): The OCID of the user who created the dynamic group.

        Raises:
            ValueError: If an unknown filter key is provided.
        """

        results = []
        # Only INFO if non-empty or filters indicate stateful/intentional request, else DEBUG
        if self.dynamic_groups or filters:
            logger.info(f'Filtering Dynamic Groups based on: {filters}')
        else:
            logger.debug(f'Filtering Dynamic Groups based on: {filters} (no data loaded yet)')

        for dg in self.dynamic_groups:
            match = True

            for key, values in filters.items():
                # Check in-use first because it is special
                if key == 'in_use':
                    if values is None:
                        logger.debug('Skipping empty in_use filter')
                        continue
                    if bool(dg.get('in_use', False)) is bool(values):
                        logger.debug(
                            f'DG included {dg.get("dynamic_group_name")} due to in_use match: {dg.get("in_use")} = {values}'
                        )
                        continue
                    else:
                        logger.debug(
                            f'DG rejected {dg.get("dynamic_group_name")} in_use: {dg.get("in_use")} != {values}'
                        )
                        match = False
                        break
                elif not values:
                    logger.debug(f'Skipping empty filter for key: {key}')
                    continue
                else:
                    values = [v.lower() for v in values]
                    logger.debug(f'Filtering on {key} mapped to column {key} with values {values}')

                    field_value = str(dg.get(key, '')).lower()
                    logger.debug(f'Field value for {key}: {field_value}')
                    if not any(val.lower() in field_value for val in values):
                        logger.debug(f'Rejecting DG {dg.get("DG Name")} due to {key} mismatch')
                        match = False
                        break

            if match:
                results.append(dg)

        if self.dynamic_groups or filters:
            logger.info(f'Filter applied. {len(results)} matched out of {len(self.dynamic_groups)} Dynamic Groups.')
        else:
            logger.debug(f'Filter applied. {len(results)} matched out of 0 Dynamic Groups (pre-load state)')
        return results

    # --- Other Public Functions ---

    # Not in use
    def _check_history(self, policy_ocid: str, start_time: str) -> None:
        """Look at audit logs to track changes to a policy"""
        the_log = f'{self.tenancy_ocid}/_Audit'
        logs_returned = self._api_call_with_logging(
            'LogSearchClient.search_logs',
            self.logging_search_client.search_logs,
            search_logs_details=SearchLogsDetails(
                search_query=f"search \"{the_log}\" | (type in ('com.oraclecloud.identityControlPlane.UpdatePolicy','com.oraclecloud.identityControlPlane.CreatePolicy','com.oraclecloud.identityControlPlane.DeletePolicy')) | sort by datetime desc",
                # search_query=f'search \"{the_log}\" where type=\'com.oraclecloud.identityControlPlane.UpdatePolicy\'',
                time_start='2025-07-10T11:59:00Z',
                time_end='2025-07-23T23:59:00Z',
            ),
            limit=1000,
        )
        if logs_returned and logs_returned.data and logs_returned.data.results:
            logger.info(f'Found {len(logs_returned.data.results)} logs for policy updates in the last 24 hours')
            for log in logs_returned.data.results:
                res: SearchResult = log
                if res and res.data:
                    type_of_log = res.data.get('logContent').get('type')
                    change_curr = (
                        res.data.get('logContent').get('data').get('stateChange').get('current').get('statements')
                    )
                    change_prev = None
                    if (
                        res.data.get('logContent').get('data')
                        and res.data.get('logContent').get('data').get('stateChange')
                        and res.data.get('logContent').get('data').get('stateChange').get('previous')
                    ):
                        # Previous state change exists
                        change_prev = (
                            res.data.get('logContent').get('data').get('stateChange').get('previous').get('statements')
                        )
                    logger.info(f'Log Type: {type_of_log}')
                    logger.info(f'***Log Details: Type: {type_of_log}Previous:{change_prev} Current:{change_curr}')

        else:
            logger.info('No policy update logs found in the last 24 hours')
        pass

    def _get_domains(self) -> list:
        return [{'id': d.id, 'display_name': d.display_name, 'url': d.url} for d in self.identity_domains]

    # --- Compliance Output Loading ---
    # Because we are not using OCI clients here, we need to load from CSV files
    # We need to load in this order:
    # 1. Domains
    # 2. Dynamic Groups
    # 3. Users
    # 3a. Augment users with group membership
    # 4. Groups + Membership
    # 5. Compartments
    # 5a. Augment compartment data with path strings (cannot use client here)
    # 6. Policies

    def _get_domain_name_from_ocid(self, domain_ocid: str) -> str:
        """Given a domain OCID, return the domain name from loaded domains"""
        if not domain_ocid or domain_ocid == '':
            return 'Default'
        for domain in self.identity_domains:
            # Domains may be represented either as dicts (CSV/offline path)
            # or SDK model objects such as DomainSummary (tenancy path).
            if isinstance(domain, dict):
                candidate_id = domain.get('id')
                candidate_name = domain.get('display_name', 'Default')
            else:
                candidate_id = getattr(domain, 'id', None)
                candidate_name = getattr(domain, 'display_name', 'Default')

            if candidate_id == domain_ocid:
                return candidate_name or 'Default'
        return 'Default'

    def _get_hierarchy_path_for_compartment(self, compartment, comp_string: str) -> str:
        """Given a compartment JSON dict, return the full hierarchy path as a string"""
        # If OCID is the tenancy OCID, return ROOT
        if compartment.get('id') == self.tenancy_ocid:
            return 'ROOT'
        path_parts = []
        current_comp = compartment
        while current_comp:
            path_parts.append(current_comp.get('name', 'Unknown'))
            parent_id = current_comp.get('parent_id')
            if not parent_id or parent_id == current_comp.get('id'):
                break
            # Find parent compartment in loaded compartments
            parent_comp = next((comp for comp in self.compartments if comp.get('id') == parent_id), None)
            current_comp = parent_comp
        # Reverse the path parts to get from root to leaf
        path_parts.reverse()
        full_path = '/'.join(path_parts)
        logger.debug(f'Compartment {comp_string} full path: {full_path}')
        return full_path

    def _load_defined_tag_catalog_from_compliance_output_placeholder(self, dir_path: str) -> None:
        """Placeholder for future compliance-output tag namespace/key ingestion.

        TODO (future): Parse compliance output artifacts for defined tag
        namespaces/keys (+ optional value validators) and populate
        ``self.defined_tag_namespace_keys`` with the same shape used by
        live tenancy loading:

            {
                namespace_name: {
                    "keys": {key_name: [values...] | None},
                    "compartment_ocid": str | None,
                    "compartment_path": str,
                }
            }

        This is intentionally a no-op for now per product request.
        """
        logger.debug(
            'Compliance placeholder: defined tag namespace catalog ingestion not yet implemented (dir=%s).',
            dir_path,
        )

    def load_from_compliance_output_dir(self, dir_path: str, load_all_users: bool = True) -> bool:  # noqa: C901
        """
        Load a CIS Compliance export from CSV files.

        Compartments and policies are required. Identity-oriented artifacts
        (domains, dynamic groups, groups/membership, and users) are optional,
        so a policy-and-compartments-only export remains useful for hierarchy,
        policy movement, consolidation, and policy-derived principal searches.

        Always resets the reload time (`policy_data_reloaded`) so that reload is not shown for compliance/CSV data.

        Starts with domains, then dynamic groups, then users/groups/membership, then compartments, then policies.
        This function is for offline/compliance output analysis: no attempt to initialize any OCI client.

        Args:
            dir_path (str): Path to a directory containing the expected compliance output files.
            load_all_users (bool): If False, skip loading users. Default is True.

        Returns:
            bool: True if all files parsed and data loaded successfully, False otherwise.
        """

        # Explicit: always clear reload time before compliance/CSV load.
        self.policy_data_reloaded = None
        # A CIS import is a new offline snapshot, not an extension of a cache.
        self.current_cache_name = ''
        self.tenancy_policy_limits = {}
        csv.field_size_limit(sys.maxsize)

        logger.info(f'Loading compliance data from output dir: {dir_path}')

        # Optional pre-step: special case for compliance domains CSV.
        # In the raw_data_identity_domains.csv export, the tenancy OCID is represented
        # as the compartment_id of the row whose display_name is "Default Domain".
        # When present, we use that compartment_id to seed self.tenancy_ocid so that
        # downstream usage/limits logic (including usage tracking) has a correct
        # tenancy OCID even if the compartments CSV is incomplete.
        domains_csv_path = _resolve_compliance_output_csv(dir_path, 'raw_data_identity_domains.csv', required=False)
        if domains_csv_path:
            try:
                with open(domains_csv_path, encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        display_name = (row.get('display_name') or '').strip()
                        if display_name.lower() == 'default domain':
                            default_domain_compartment_id = (row.get('compartment_id') or '').strip()
                            if default_domain_compartment_id:
                                # SPECIAL CASE: in compliance output, the tenancy OCID is the
                                # compartment_id of the Default Domain row.
                                self.tenancy_ocid = default_domain_compartment_id
                                logger.info(
                                    'Set tenancy_ocid from raw_data_identity_domains.csv Default Domain compartment_id: %s',
                                    self.tenancy_ocid,
                                )
                            break
            except Exception as e:
                logger.error(f'Failed to read tenancy_ocid from raw_data_identity_domains.csv: {e}')

        # We need to only use the CSV files and stop using the JSON file altogether
        try:
            # Step 1: Set the tenancy OCID and Name from the data
            compartments_csv_path = _resolve_compliance_output_csv(dir_path, 'raw_data_identity_compartments.csv')
            with open(compartments_csv_path, encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('id', '').startswith('ocid1.tenancy.'):
                        # If tenancy_ocid was already set from domains CSV, keep it;
                        # otherwise, use the value from compartments.
                        if not self.tenancy_ocid:
                            self.tenancy_ocid = row.get('id', '')
                        self.tenancy_name = row.get('name', '')
                        logger.info(
                            'Set tenancy OCID to %s and name to %s (compartments CSV)',
                            self.tenancy_ocid,
                            self.tenancy_name,
                        )
                        break
            if not self.tenancy_ocid or not self.tenancy_name:
                logger.error('Could not find tenancy OCID and name in compartments CSV')
                return False

            # --- Step 2: Load Dynamic Groups ---
            dgs_file = _resolve_compliance_output_csv(dir_path, 'raw_data_identity_dynamic_groups.csv', required=False)
            with _open_optional_compliance_csv(dgs_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    created_by = row.get('idcs_created_by', '{}')
                    try:
                        created_by_json = json.loads(created_by)
                        created_by_ocid = created_by_json.get('odid', 'n/a')
                    except json.JSONDecodeError:
                        created_by_ocid = 'n/a'
                    domain_ocid = row.get('domain_ocid', '')
                    domain_name = self._get_domain_name_from_ocid(domain_ocid)
                    matching_rule_structure = parse_condition_structure(row.get('matching_rule', ''))
                    dg: DynamicGroup = {
                        'domain_name': domain_name or 'Default',
                        'dynamic_group_name': row.get('display_name') or '',
                        'dynamic_group_id': 'n/a',
                        'dynamic_group_ocid': row.get('ocid', ''),
                        'matching_rule': row.get('matching_rule', ''),
                        'matching_rule_structure': matching_rule_structure,
                        'matching_rule_parsed_structure': format_condition_structure_summary(matching_rule_structure),
                        'description': row.get('description') or '',
                        'in_use': True,  # Default to True; will be updated later
                        'creation_time': 'n/a',
                        'created_by_name': 'n/a',
                        'created_by_ocid': created_by_ocid,
                    }
                    self.dynamic_groups.append(dg)
            logger.info(f'Loaded {len(self.dynamic_groups)} dynamic groups from CSV')

            # --- Step 3: Load Groups ---
            groups_file = _resolve_compliance_output_csv(
                dir_path, 'raw_data_identity_groups_and_membership.csv', required=False
            )
            user_membership: dict[str, list[str]] = {}
            user_domains: dict[str, str] = {}
            seen_groups = set()
            with _open_optional_compliance_csv(groups_file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    group: Group = {
                        'domain_name': row.get('domain_deeplink', '').split('","')[-1].rstrip('")')
                        if 'domain_deeplink' in row
                        else 'Default',
                        'group_name': row.get('name') or '',
                        'group_ocid': row.get('id') or '',
                        'description': row.get('description') or '',
                        'group_id': row.get('id') or '',
                    }
                    logger.debug(f'Processing group: {group}')
                    member_user_ocid = row.get('user_id', '')
                    if member_user_ocid and member_user_ocid != '':
                        if member_user_ocid not in user_membership:
                            user_membership[member_user_ocid] = []
                        user_membership[member_user_ocid].append(row.get('id'))
                    group_key = (group['domain_name'], group['group_name'])
                    if member_user_ocid and member_user_ocid != '':
                        user_domains[member_user_ocid] = group['domain_name']
                    if group_key in seen_groups:
                        continue
                    seen_groups.add(group_key)
                    self.groups.append(group)
            logger.debug(f'Loaded {len(self.groups)} groups')

            # --- Step 4: Load Users, unless disabled ---
            self.users = []
            users_file: str | None = None
            if load_all_users:
                users_file = _resolve_compliance_output_csv(dir_path, 'raw_data_identity_users.csv', required=False)
                with _open_optional_compliance_csv(users_file) as f:
                    reader = csv.DictReader(f)
                    for user_item in reader:
                        logger.debug(f'Processing user item: {user_item}')
                        user: User = {
                            'domain_name': user_item.get('domain_deeplink', '').split('","')[-1].rstrip('")')
                            if 'domain_deeplink' in user_item
                            else 'Default',
                            'user_name': user_item.get('name') or '',  # No way to get username or email
                            'user_ocid': user_item.get('id') or '',
                            'display_name': user_item.get('name') or '',
                            'email': user_item.get('email') or '',
                            'user_id': user_item.get('external_identifier') or '',
                            'groups': [],
                        }
                        group_names_str = user_item.get('groups', '') or ''
                        group_names = eval(group_names_str) if group_names_str else []
                        group_ocids = []
                        for group_name in group_names:
                            group_obj = next(
                                (
                                    g
                                    for g in self.groups
                                    if g.get('group_name') == group_name
                                    and g.get('domain_name') == user.get('domain_name')
                                ),
                                None,
                            )
                            if group_obj:
                                group_ocids.append(group_obj.get('group_ocid', ''))
                        user['groups'] = group_ocids

                        logger.info(f'Loaded user: {user}')
                        self.users.append(user)
                logger.info(f'Loaded {len(self.users)} users')
            else:
                logger.info('Skipping load of users due to load_all_users=False')

            # -- Step 5: Load Compartments ---
            compartments_file = compartments_csv_path
            with open(compartments_file, encoding='utf-8') as f:
                reader = csv.DictReader(f)
                # Iterate compartments and add to list
                for comp_item in reader:
                    compartment = {
                        'id': comp_item.get('id') or '',
                        'name': comp_item.get('name') or '',
                        'hierarchy_path': None,  # will be built later
                        'lifecycle_state': comp_item.get('lifecycle_state') or '',
                        'parent_id': comp_item.get('compartment_id') or '',
                        'description': comp_item.get('description') or '',
                    }
                    logger.debug(f'Processing compartment: {compartment}')
                    # Only add ACTIVE compartments
                    if compartment['lifecycle_state'] == 'ACTIVE':
                        self.compartments.append(compartment)
                    else:
                        logger.debug(
                            f"Skipping compartment {compartment['name']} with lifecycle state {compartment['lifecycle_state']}"
                        )
                # For some reason the root compartment is not included - add it manually
                root_compartment = Compartment(
                    id=self.tenancy_ocid,
                    name='ROOT',
                    parent_id='',
                    hierarchy_path='',
                    description='',
                    lifecycle_state='ACTIVE',
                )
                self.compartments.append(root_compartment)

            logger.debug(f'Loaded {len(self.compartments)} compartments')

            # Now build hierarchy paths for each compartment
            for comp in self.compartments:
                logger.info(f"Building path for compartment {comp.get('name','n/a')}")
                comp['hierarchy_path'] = self._get_hierarchy_path_for_compartment(comp, '')
            logger.info('Built hierarchy paths for compartments')

            # Debug just the compartment name and path for all compartments
            for comp in self.compartments:
                logger.info(f"Compartment: {comp.get('name','n/a')} Path: {comp.get('hierarchy_path','n/a')}")

            # --- Step 6: Load Policies ---
            compartments_file = _resolve_compliance_output_csv(dir_path, 'raw_data_identity_policies.csv')
            with open(compartments_file, encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for policy_item in reader:
                    # Create a Policy object for the Policy itself
                    # Try to extract tags from CSV: expects column "tags" as a JSON or stringified dict (optional)
                    tags = None
                    if 'tags' in policy_item:
                        tags_str = policy_item.get('tags') or ''
                        if tags_str:
                            try:
                                tags_candidate = eval(tags_str) if tags_str.startswith('{') else tags_str
                                if isinstance(tags_candidate, dict):
                                    tags = tags_candidate
                            except Exception:
                                pass

                    comp_path = next(
                        (
                            comp['hierarchy_path']
                            for comp in self.compartments
                            if comp['id'] == policy_item.get('compartment_id')
                        ),
                        'ROOT',
                    )
                    # ``id`` is the policy OCID in the CIS export.  Keep it
                    # as the canonical identifier for both the policy object
                    # and every parsed statement.  ``identifier`` is an
                    # export identifier and can differ, which otherwise
                    # prevents reports and policy-level risk from associating
                    # statements with their policy.
                    policy_ocid = policy_item.get('id') or policy_item.get('identifier') or ''
                    policy_obj = BasePolicy(
                        policy_name=policy_item.get('name') or '',
                        policy_ocid=policy_ocid,
                        compartment_ocid=policy_item.get('compartment_id') or '',
                        compartment_path=comp_path,
                        description=policy_item.get('description') or '',
                        creation_time='',
                        tags=tags if isinstance(tags, dict) else {},
                        freeform_tags=tags if isinstance(tags, dict) else {},
                    )
                    logger.debug(f'Processing policy: {policy_obj}')
                    self.policies.append(policy_obj)

                    # Get the basic details here and then iterate statements - those are to be added to the list
                    comp_id = policy_item.get('compartment_id') or ''
                    policy_name = policy_item.get('name') or ''
                    creation_time = policy_item.get('time_created') or ''
                    # Statements needs to be a list of strings, but appears like a single string in CSV. example:
                    # ['allow group iam_tag_group to inspect all-resources in tenancy', 'allow group iam_tag_group read instances in tenancy', 'allow group iam_tag_group to read load-balancers in tenancy', 'allow group iam_tag_group to read buckets in tenancy', 'allow group iam_tag_group to read nat-gateways in tenancy', 'allow group iam_tag_group to read public-ips in tenancy', 'allow group iam_tag_group to read file-family in tenancy', 'allow group iam_tag_group to read instance-configurations in tenancy', 'allow group iam_tag_group to read network-security-groups in tenancy', 'allow group iam_tag_group to read capture-filters in tenancy', 'allow group iam_tag_group to read resource-availability in tenancy', 'allow group iam_tag_group to read audit-events in tenancy', 'allow group iam_tag_group to read users in tenancy', 'allow group iam_tag_group to use cloud-shell in tenancy', 'allow group iam_tag_group to read vss-family in tenancy', 'allow group iam_tag_group to read usage-budgets in tenancy', 'allow group iam_tag_group to read usage-reports in tenancy', 'allow group iam_tag_group to read data-safe-family in tenancy', 'allow group iam_tag_group to read vaults in tenancy', 'allow group iam_tag_group to read keys in tenancy', 'allow group iam_tag_group to read tag-namespaces in tenancy', 'allow group Aiam_tag_group to use ons-family in tenancy where any {request.operation!=/Create*/, request.operation!=/Update*/, request.operation!=/Delete*/, request.operation!=/Change*/}']
                    statements = eval(policy_item.get('statements') or '[]')
                    logger.debug(f'Policy {policy_name} has {len(statements)} statements')
                    # Iterate each statement, determine type, and proceed to parse
                    for statement_text in statements:
                        # DO NOT lowercase statement text - preserve original case
                        stripped_statement = statement_text.strip()
                        base_policy_statement: BasePolicyStatement = BasePolicyStatement(
                            policy_name=policy_name,
                            policy_ocid=policy_ocid,
                            # policy_description=policy_item.get('description') or '',
                            compartment_ocid=comp_id,
                            compartment_path=comp_path,
                            statement_text=stripped_statement,
                            creation_time=creation_time,
                            internal_id=hashlib.md5((stripped_statement + '' + policy_ocid).encode()).hexdigest(),
                            parsed=False,
                        )
                        logger.debug(f'Processing statement: {statement_text}')
                        st_text_lower = stripped_statement.lower()
                        # Parse the statement now - cannot use the existing parser as is because it relies on OCI clients
                        if st_text_lower.startswith('define'):
                            # Parse as DefineStatement
                            define_statement: DefineStatement = DefineStatement(**base_policy_statement)
                            if not self._parse_define_statement(policy_obj, define_statement):
                                logger.debug(f'Define statement was unable to parse: {statement_text}')
                            logger.debug(f'Parsed define statement: {define_statement}')
                        # Admit and Deny Admit
                        elif st_text_lower.startswith('admit') or st_text_lower.startswith('deny admit'):
                            admit_statement: AdmitStatement = AdmitStatement(**base_policy_statement)
                            if not self._parse_admit_statement(policy_obj, admit_statement):
                                logger.debug(f'Admit statement was unable to parse: {statement_text}')
                            logger.debug(f'Parsed admit statement: {admit_statement}')
                        # Endorse Statement
                        elif st_text_lower.startswith('endorse'):
                            endorse_statement: EndorseStatement = EndorseStatement(**base_policy_statement)
                            if not self._parse_endorse_statement(policy_obj, endorse_statement):
                                logger.debug(f'Endorse statement was unable to parse: {statement_text}')
                            logger.debug(f'Parsed endorse statement: {endorse_statement}')
                        else:
                            # Regular Policy Statement
                            regular_statement: RegularPolicyStatement = RegularPolicyStatement(**base_policy_statement)
                            parsed_statement_valid = self._parse_statement(policy_obj, regular_statement)
                            if not parsed_statement_valid:
                                logger.warning(f'Invalid policy statement detected: {statement_text}')
                            logger.debug(f'Parsed regular policy statement: {regular_statement}')

            # --- Step 7 (placeholder): Load defined tag catalog from compliance output ---
            self._load_defined_tag_catalog_from_compliance_output_placeholder(dir_path)

            logger.info(f'Loaded {len(self.regular_statements)} policy statements')

            self.data_as_of = datetime.now(UTC).isoformat()
            # For compliance/JSON loads, explicitly clear the reload date unless recovered from cache elsewhere
            self.policy_data_reloaded = None
            self.loaded_from_compliance_output = True
            self.compliance_capabilities = {
                'policy_statements': bool(self.regular_statements),
                'policy_objects': True,
                'compartments': True,
                'compartment_hierarchy': True,
                'group_subject_names': bool(self.regular_statements),
                'dynamic_group_subject_names': bool(self.regular_statements),
                'groups_inventory': bool(groups_file),
                'dynamic_groups_inventory': bool(dgs_file),
                'users_inventory': bool(load_all_users and users_file),
                'group_memberships': bool(groups_file and load_all_users and users_file),
                'domains_inventory': bool(domains_csv_path),
                'defined_tag_catalog': bool(self.defined_tag_namespace_keys),
                'principal_resolution': bool(groups_file and load_all_users and users_file),
            }
            self.compliance_artifact_counts = {
                # The loader synthesizes ROOT for hierarchy calculations; do
                # not count it as an imported compartment in the UI.
                'compartments': len(
                    {compartment.get('id') for compartment in self.compartments if compartment.get('id')}
                ),
                'policies': len(self.policies),
                'statements': len(self.regular_statements),
                'groups': len(self.groups),
                'dynamic_groups': len(self.dynamic_groups),
                'users': len(self.users),
            }

            # After all policy statements loaded, enrich compartment counts
            self._enrich_compartments_with_statement_counts()

            # logger.warning(f"on_policy_statements_updated callback failed: {e}")

            logger.warning(
                'CIS Compliance load completed: artifacts=%s capabilities=%s',
                json.dumps(self.compliance_artifact_counts, sort_keys=True),
                json.dumps(self.compliance_capabilities, sort_keys=True),
            )
            logger.info('Compliance output data loaded successfully.')
            return True
        except Exception as e:
            # Show stack trace for debugging
            import traceback

            traceback.print_exc()
            logger.error(f'Compliance output data load failed: {e}')
            return False
