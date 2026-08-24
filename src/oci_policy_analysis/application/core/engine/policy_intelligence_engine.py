##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# policy_intelligence.py
#
# Encapsulates after-load analysis, intelligence, and reporting logic for policies.
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import time
from typing import TYPE_CHECKING

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.engine.recommendation_actions import catalog_guidance
from oci_policy_analysis.application.core.models.models import PolicyIntelligence, PolicyOverlap
from oci_policy_analysis.application.core.parser import collect_tag_conditions, parse_condition_structure
from oci_policy_analysis.application.core.repo.reference_data_repo import VERB_RISK_WEIGHTS, ReferenceDataRepo
from oci_policy_analysis.application.core.support.logger import get_logger

if TYPE_CHECKING:
    from oci_policy_analysis.application.core.engine.intelligence_strategies.base import IntelligenceStrategy

logger = get_logger(component='core.engine.policy_intelligence_engine')


def _append_unique(items: list, value) -> None:
    """Append value only if not already present (preserve order)."""
    if value not in items:
        items.append(value)


def _condition_text(statement: dict) -> str:
    """Return condition text as a normalized lower-case string."""

    return str(statement.get('conditions') or statement.get('condition') or '').lower()


def _is_any_principal_statement(statement: dict) -> bool:
    """Return True for any-user/any-group policy subjects."""

    return str(statement.get('subject_type') or '').lower() in {'any-user', 'any-group'}


def _normalize_subjects(subjects, subject_type: str) -> list[tuple[str | None, str]]:
    """Return policy subjects as ``(domain, name)`` tuples."""

    if subjects is None:
        return [('Default', 'UNKNOWN')]
    if isinstance(subjects, str):
        return [(None, subjects)]
    normalized = []
    for subject in subjects:
        if isinstance(subject, tuple | list) and len(subject) >= 2:
            normalized.append((subject[0], subject[1]))
        else:
            normalized.append((None, str(subject or subject_type or 'UNKNOWN')))
    return normalized or [('Default', 'UNKNOWN')]


def _condition_atoms(statement: dict) -> list[dict]:
    """Return parsed condition atoms from a statement, parsing raw text if needed."""

    atoms = statement.get('condition_atoms')
    if isinstance(atoms, list):
        return [atom for atom in atoms if isinstance(atom, dict)]
    structure = statement.get('where_clause_structure') or statement.get('where_clause') or {}
    if isinstance(structure, dict) and isinstance(structure.get('atoms'), list):
        return [atom for atom in structure.get('atoms', []) if isinstance(atom, dict)]
    parsed = parse_condition_structure(statement.get('conditions') or statement.get('condition') or '')
    parsed_atoms = parsed.get('atoms') if isinstance(parsed, dict) else []
    return [atom for atom in parsed_atoms if isinstance(atom, dict)] if isinstance(parsed_atoms, list) else []


def _condition_atom_values(statement: dict) -> dict[str, str]:
    """Return first right-side value for each condition atom left side."""

    values = {}
    for atom in _condition_atoms(statement):
        left = str(atom.get('normalized_left') or atom.get('left') or '').casefold()
        right = str(atom.get('right') or '').strip().strip('\'"')
        if left and right and left not in values:
            values[left] = right
    return values


def _derived_principal_identity(statement: dict, original_subject_key: str, subject_type: str) -> tuple[str, str]:
    """Return display principal key/kind, deriving resource/workload identities from conditions."""

    if not _is_any_principal_statement(statement):
        return original_subject_key, subject_type
    values = _condition_atom_values(statement)
    principal_type = str(values.get('request.principal.type') or '').strip()
    if not principal_type:
        return original_subject_key, subject_type
    if principal_type.casefold() == 'workload':
        cluster_id = values.get('request.principal.cluster_id') or 'unknown'
        namespace = values.get('request.principal.namespace') or 'unknown'
        service_account = values.get('request.principal.service_account') or 'unknown'
        return f'oke-workload-identity:{cluster_id}/{namespace}/{service_account}', 'oke-workload-identity'
    compartment_id = values.get('request.principal.compartment.id') or 'unknown'
    return f'resource-principal:{principal_type}/{compartment_id}', 'resource-principal'


def _path_is_self_or_descendant(candidate_path: str, effective_path: str) -> bool:
    """Return True when candidate path is the effective path or a descendant path."""

    candidate = str(candidate_path or '').strip('/').lower()
    effective = str(effective_path or '').strip('/').lower()
    return bool(candidate and effective and (candidate == effective or candidate.startswith(f'{effective}/')))


def _path_sort_key(path: str) -> tuple[int, str]:
    """Sort root before child paths, then alphabetically."""

    clean = str(path or '').strip('/')
    return (0 if clean.casefold() == 'root' else clean.count('/') + 1, clean.casefold())


# OCI Identity Domains system group that cannot be deleted and may have zero members; exclude from cleanup.
ALL_DOMAIN_USERS_GROUP_NAME = 'All Domain Users'

# Compartment policy statement limits (hard OCI rules)
POLICY_STATEMENT_HARD_LIMIT = 500
POLICY_STATEMENT_WARNING_THRESHOLD = int(POLICY_STATEMENT_HARD_LIMIT * 0.9)  # 450

# Cleanup check IDs; when enabled_check_ids is passed to build_cleanup_items, only these run.
CLEANUP_CHECK_IDS = (
    'invalid_statements',
    'unused_groups',
    'unused_dynamic_groups',
    'statements_too_open',
    'anyuser_no_where',
)

# Default run order for intelligence strategies (strategy_id). Ensures e.g. cleanup before recommendations.
DEFAULT_STRATEGY_RUN_ORDER = [
    'risk_scores',
    'supersession',
    'consolidation_suggestion',
    'invalid_statements',
    'unused_groups',
    'unused_dynamic_groups',
    'statements_too_open',
    'anyuser_no_where',
    'recommendations',
]


class PolicyIntelligenceEngine:
    """
    Provides post-load intelligence, overlap analysis, and advanced policy insights on OCI policies.

    This engine operates on a loaded PolicyAnalysisRepository and delivers advanced analytics such as risk scores,
    overlaps, recommendations, and policy hygiene findings.

    Args:
        policy_repo (PolicyAnalysisRepository): The repository containing loaded compartment, policy, and identity data.

    Attributes:
        policy_repo (PolicyAnalysisRepository): Source of OCI policy, identity, and compartment data.
        overlay (PolicyIntelligence): Stores the full results of all analytics (risk, overlaps, recommendations, etc).
        permissions_report (dict): Holds the effective permissions report used by various UI components.
    """

    def __init__(self, policy_repo, strategies: list['IntelligenceStrategy'] | None = None):
        """
        Initialize the PolicyIntelligenceEngine and prepare analytics overlay structures.

        Args:
            policy_repo (PolicyAnalysisRepository): Repository with loaded compartment, policy, and identity data.
            strategies: Optional list of IntelligenceStrategy implementations. If None, uses built-in default(s)
                when run_all() is called with strategies registered elsewhere, or legacy method calls.
        """
        self.policy_repo = policy_repo
        # Explicitly type and instantiate the overlay using the model
        self.overlay: PolicyIntelligence = PolicyIntelligence(
            overlaps=[], recommendations=[], risk_scores=[], consolidations=[], supersessions=[]
        )
        self.permissions_report = {}
        self._strategies: dict[str, IntelligenceStrategy] = {}
        self._run_order: list[str] = list(DEFAULT_STRATEGY_RUN_ORDER)
        to_register = strategies if strategies is not None else self._get_default_strategies()
        for s in to_register:
            self.register_strategy(s)
        logger.info(
            'Initialized PolicyIntelligenceEngine with repo; strategies=%s',
            list(self._strategies.keys()) if self._strategies else 'none (legacy mode)',
        )

    # ------------------------------------------------------------------
    # Principal key helpers (shared across simulation/intelligence/UI)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_principal_key(subject_type: str, domain: str | None, name: str) -> str:
        """Return the canonical *principal key* string for a subject triple.

        Delegates to shared helper in policy_helpers for consistent
        normalization across repo/intelligence/simulation layers.
        """
        return calculate_principal_key(subject_type, domain, name)

    def _get_default_strategies(self) -> list['IntelligenceStrategy']:
        """Lazy import to avoid circular import at module load."""
        from oci_policy_analysis.application.core.engine.intelligence_strategies import (
            get_default_intelligence_strategies,
        )

        return get_default_intelligence_strategies()

    def register_strategy(self, strategy: 'IntelligenceStrategy') -> None:
        """Register a single intelligence strategy (pluggable)."""
        self._strategies[strategy.strategy_id] = strategy
        logger.debug('Registered intelligence strategy: %s (%s)', strategy.strategy_id, strategy.display_name)

    def get_strategy_ids(self) -> list[str]:
        """Return strategy_ids in run order (for Settings and run_all filtering)."""
        return list(self._run_order)

    def get_strategies_for_settings(self) -> list[tuple[str, str, str]]:
        """Return (strategy_id, display_name, category) for all registered strategies, in run order."""
        seen = set()
        out = []
        for sid in self._run_order:
            s = self._strategies.get(sid)
            if s and sid not in seen:
                seen.add(sid)
                out.append((s.strategy_id, s.display_name, s.category))
        return out

    def run_all(
        self,
        enabled_strategy_ids: list[str] | None = None,
        params: dict | None = None,
    ) -> None:
        """
        Run all enabled intelligence strategies in order and merge results into overlay.

        Ensures prerequisites (compartment index, invalid statements, DG in-use) are run first.
        If no strategies are registered, falls back to legacy method calls for backward compatibility.

        Args:
            enabled_strategy_ids: If None, run all registered strategies (or legacy path). Otherwise run only these.
            params: Optional dict (e.g. where_clause_reduction_pct, service_principal_reduction_pct,
                enabled_cleanup_check_ids, consolidation_strategy_names). Passed to each strategy; engine ref added.
        """
        params = dict(params or {})
        params['engine'] = self
        repo = self.policy_repo
        overlay = self.overlay

        # Prerequisites used by one or more strategies
        if not getattr(self, 'compartments_by_path', None) and repo.compartments:
            self.build_compartment_index()
        self.resolve_cross_tenancy_aliases()
        self.find_invalid_statements()
        self.run_dg_in_use_analysis()

        if not self._strategies:
            # Legacy path: call existing methods in order
            where_pct = params.get('where_clause_reduction_pct', 50)
            svc_pct = params.get('service_principal_reduction_pct', 50)
            self.calculate_potential_risk_scores(
                where_clause_reduction_pct=where_pct,
                service_principal_reduction_pct=svc_pct,
            )
            self.build_policy_consolidation()
            enabled_checks = params.get('enabled_cleanup_check_ids')
            self.build_cleanup_items(enabled_check_ids=enabled_checks)
            self.build_overall_recommendations()
            return

        run_ids = set(enabled_strategy_ids) if enabled_strategy_ids else set(self._strategies)
        logger.info(
            'Policy intelligence run_all starting: enabled_strategy_ids=%s',
            sorted(run_ids),
        )
        for strategy_id in self._run_order:
            if strategy_id not in self._strategies:
                logger.info('Policy intelligence strategy skipped (not registered): %s', strategy_id)
                continue
            if strategy_id not in run_ids:
                logger.info('Policy intelligence strategy skipped (disabled): %s', strategy_id)
                continue
            strategy = self._strategies[strategy_id]
            logger.info(
                'Policy intelligence strategy running: %s (%s)',
                strategy.strategy_id,
                strategy.display_name,
            )
            try:
                strategy.run(repo, overlay, params)  # pyright: ignore[reportArgumentType]
                logger.info(
                    'Policy intelligence strategy completed: %s (%s)',
                    strategy.strategy_id,
                    strategy.display_name,
                )
            except Exception as e:
                logger.warning('Intelligence strategy %s failed: %s', strategy_id, e)

    def resolve_cross_tenancy_aliases(self) -> None:
        """Resolve referenced cross-tenancy aliases to define OCIDs.

        Parse-time sets alias placeholders as unresolved. This step resolves them
        after all define/admit/endorse parsing is complete.
        """
        repo = self.policy_repo
        defined_aliases = list(getattr(repo, 'defined_aliases', []) or [])
        ct_statements = list(getattr(repo, 'cross_tenancy_statements', []) or [])

        alias_map: dict[str, str] = {}
        for define in defined_aliases:
            alias_name = str(define.get('defined_name') or '').strip()
            alias_ocid = str(define.get('ocid_alias') or '').strip()
            if alias_name:
                alias_map[alias_name.casefold()] = alias_ocid

        for st in ct_statements:
            aliases = st.get('tenancy_aliases')
            if not isinstance(aliases, list):
                aliases = []
            aliases = [str(a).strip() for a in aliases if str(a).strip()]
            st['tenancy_aliases'] = aliases

            resolved_aliases: dict[str, dict[str, str | bool]] = {}
            unresolved: list[str] = []
            for alias in aliases:
                ocid = alias_map.get(alias.casefold(), '')
                resolved = bool(ocid)
                resolved_aliases[alias] = {'alias': alias, 'ocid': ocid, 'resolved': resolved}
                if not resolved:
                    unresolved.append(alias)

            st['resolved_aliases'] = resolved_aliases
            st['aliases_resolved'] = len(unresolved) == 0

            if unresolved:
                st['valid'] = False
                reasons = list(st.get('invalid_reasons') or [])
                for alias in unresolved:
                    reason = f'Unresolved tenancy alias: {alias}'
                    if reason not in reasons:
                        reasons.append(reason)
                st['invalid_reasons'] = reasons

    def build_permissions_report(self):  # noqa: C901
        """
        Build a detailed nested report of effective permissions for all policy statements.

        Scans all statements, resolves permissions and subjects, and groups by effective path and subject.
        Stores both the structured report and supporting lookup maps in self.permissions_report.

        Returns:
            dict: A structure with keys "report", "resource_map", "perm_conditionals", and "perm_statements" containing
            all effective allow/deny permissions and metadata, or empty dicts if no data is present.
        """
        logger.info('Building permissions report data (centralized)')
        permission_reference_repo = ReferenceDataRepo()
        report = {}
        resource_map = {}
        perm_conditionals = {}  # (path,subject,perm) -> True/False
        perm_statements = {}  # (path,subject,perm) -> statement_text
        direct_grant_rows = []
        skipped_count = 0
        allow_count = 0
        deny_count = 0
        statements = self.policy_repo.regular_statements
        logger.info('Permissions report input statements: %d', len(statements or []))
        for idx, stmt in enumerate(statements or []):
            try:
                effective_path = stmt.get('effective_path')
                if not effective_path or effective_path is None:
                    effective_path = 'UNKNOWN'
                action = stmt.get('action', 'allow').lower()
                subjects = _normalize_subjects(stmt.get('subject', []), str(stmt.get('subject_type') or 'unknown'))
                subject_type = stmt.get('subject_type', 'unknown')
                permissions = stmt.get('permission', [])
                if isinstance(permissions, str):
                    permissions = [permissions]
                resource_str = stmt.get('resource')
                statement_text = stmt.get('statement_text', '')
                is_conditional = bool(stmt.get('conditions'))
                if not permissions:
                    resource = stmt.get('resource', '')
                    verb = stmt.get('verb', '')
                    if resource and verb:
                        permissions = permission_reference_repo.get_permissions(
                            entity=resource, verb=verb, action=action
                        )
                        if not permissions:
                            permissions = [f'{verb.upper()}_{resource.upper()}']
                    else:
                        permissions = ['UNKNOWN_PERMISSION']
                for subject_domain, subject_name in subjects:
                    # Use shared helper to ensure principal_key / subject_key
                    # format is consistent with simulation and UI surfaces.
                    original_subject_key = self.calculate_principal_key(subject_type, subject_domain, subject_name)
                    subject_key, principal_kind = _derived_principal_identity(
                        stmt, original_subject_key, str(subject_type or 'unknown')
                    )
                    if effective_path not in report:
                        report[effective_path] = {}
                    if subject_key not in report[effective_path]:
                        report[effective_path][subject_key] = {
                            'allow': set(),
                            'deny': set(),
                            'subject_type': principal_kind,
                            'original_subject_keys': set(),
                        }
                    report[effective_path][subject_key]['original_subject_keys'].add(original_subject_key)
                    if action == 'deny':
                        report[effective_path][subject_key]['deny'].update(permissions)
                        deny_count += len(permissions)
                    else:
                        report[effective_path][subject_key]['allow'].update(permissions)
                        allow_count += len(permissions)
                    for perm in permissions:
                        perm_conditionals[(effective_path, subject_key, perm)] = is_conditional
                        perm_statements[(effective_path, subject_key, perm)] = statement_text
                        direct_grant_rows.append(
                            {
                                'effective_path': effective_path,
                                'grant_path': effective_path,
                                'principal_key': subject_key,
                                'original_subject_key': original_subject_key,
                                'principal_kind': principal_kind,
                                'action': 'deny' if action == 'deny' else 'allow',
                                'resource': resource_str or '',
                                'permission': perm,
                                'conditional': is_conditional,
                                'inherited': False,
                                'inherited_from': '',
                                'statement_text': statement_text,
                                'policy_name': stmt.get('policy_name') or '',
                                'statement_id': stmt.get('internal_id') or stmt.get('id') or '',
                            }
                        )
                    rsrc = resource_str if resource_str else ('Permissions (select row)' if permissions else '')
                    resource_map[(effective_path, subject_key)] = rsrc
            except Exception as exc:
                skipped_count += 1
                logger.debug(
                    'Skipping statement while building permissions report: index=%s policy=%s error=%s statement=%r',
                    idx,
                    stmt.get('policy_name') if isinstance(stmt, dict) else '',
                    exc,
                    stmt,
                    exc_info=True,
                )
        for path in report:
            for subject in report[path]:
                report[path][subject]['allow'] = sorted(
                    [perm for perm in list(report[path][subject]['allow']) if perm is not None]
                )
                report[path][subject]['deny'] = sorted(
                    [perm for perm in list(report[path][subject]['deny']) if perm is not None]
                )
                report[path][subject]['original_subject_keys'] = sorted(report[path][subject]['original_subject_keys'])
        if skipped_count:
            logger.warning(
                'Permissions report skipped %d malformed statement(s); enable DEBUG for details', skipped_count
            )
        grant_rows = self._expand_effective_permission_rows(direct_grant_rows)
        principal_count = sum(len(subjects) for subjects in report.values())
        logger.info(
            'Permissions report built: paths=%d principals=%d direct_allow_grants=%d direct_deny_grants=%d effective_rows=%d skipped=%d',
            len(report),
            principal_count,
            allow_count,
            deny_count,
            len(grant_rows),
            skipped_count,
        )
        # Store both the report and auxiliary maps for selection/detail lookups:
        self.permissions_report = {
            'report': report,
            'resource_map': resource_map,
            'perm_conditionals': perm_conditionals,
            'perm_statements': perm_statements,
            'grant_rows': grant_rows,
            'summary': {
                'statement_count': len(statements or []),
                'path_count': len(report),
                'principal_count': principal_count,
                'allow_grant_count': allow_count,
                'deny_grant_count': deny_count,
                'direct_grant_row_count': len(direct_grant_rows),
                'effective_grant_row_count': len(grant_rows),
                'skipped_statement_count': skipped_count,
            },
        }
        return self.permissions_report

    def _expand_effective_permission_rows(self, direct_rows: list[dict]) -> list[dict]:
        """Expand direct grants to each descendant compartment where they are effective."""

        if not direct_rows:
            return []
        known_paths = set()
        for row in direct_rows:
            grant_path = str(row.get('grant_path') or row.get('effective_path') or '').strip()
            if grant_path:
                known_paths.add(grant_path)
        for path in getattr(self, 'compartments_by_path', {}) or {}:
            if path:
                known_paths.add(str(path))
        for comp in getattr(self.policy_repo, 'compartments', []) or []:
            path = comp.get('hierarchy_path') if isinstance(comp, dict) else None
            if path:
                known_paths.add(str(path).lower())

        expanded_rows = []
        for row in direct_rows:
            grant_path = str(row.get('grant_path') or row.get('effective_path') or '').strip()
            if not grant_path or grant_path == 'UNKNOWN':
                expanded_rows.append(dict(row))
                continue
            descendant_paths = [path for path in known_paths if _path_is_self_or_descendant(path, grant_path)] or [
                grant_path
            ]
            for path in sorted(descendant_paths, key=_path_sort_key):
                expanded = dict(row)
                expanded['effective_path'] = path
                expanded['grant_path'] = grant_path
                inherited = path.strip('/').casefold() != grant_path.strip('/').casefold()
                expanded['inherited'] = inherited
                expanded['inherited_from'] = grant_path if inherited else ''
                expanded_rows.append(expanded)
        return expanded_rows

    def run_dg_in_use_analysis(self):  # noqa: C901
        """
        Analyzes Dynamic Group data for unused Dynamic Groups.
        Should be called after repo is loaded and statements parsed.
        """
        # Build normalized subject reference sets for both supported DG principal forms:
        #   1) dynamic-group: domain/name references
        #   2) dynamic-group-id: OCID references
        named_subject_refs: set[tuple[str, str]] = set()
        id_subject_refs: set[str] = set()

        for st in self.policy_repo.regular_statements:
            subject_list = st.get('subject') or []
            subject_type = st.get('subject_type')
            logger.debug(f'SubType: {subject_type} Subject: {subject_list}')

            if subject_type == 'dynamic-group':
                logger.debug(f'Add: {subject_type} Subject: {subject_list}')
                for subject in subject_list:
                    if isinstance(subject, tuple | list) and len(subject) >= 2:
                        subj_domain = str(subject[0] or 'default').strip().casefold()
                        subj_name = str(subject[1] or '').strip().casefold()
                        if subj_name:
                            named_subject_refs.add((subj_domain, subj_name))
            elif subject_type == 'dynamic-group-id':
                logger.debug(f'Add: {subject_type} Subject: {subject_list}')
                for subject in subject_list:
                    subj_ocid = ''
                    if isinstance(subject, tuple | list) and len(subject) >= 2:
                        # Canonical parser shape is (None, ocid), but be tolerant.
                        subj_ocid = str(subject[1] or '').strip()
                    elif isinstance(subject, str):
                        subj_ocid = subject.strip()
                    if subj_ocid:
                        id_subject_refs.add(subj_ocid.casefold())

        logger.debug(
            'Subject counts for DG in-use analysis: named=%s id=%s',
            len(named_subject_refs),
            len(id_subject_refs),
        )

        # Iterate all DGs, and consider in-use if matched by either domain/name or OCID.
        unused_dynamic_groups = 0
        for dg in self.policy_repo.dynamic_groups:
            dg_domain = str(dg.get('domain_name') or 'default').strip()
            dg_name = str(dg.get('dynamic_group_name') or '').strip()
            dg_ocid = str(dg.get('dynamic_group_ocid') or '').strip()

            in_use_by_name = bool(dg_name) and (dg_domain.casefold(), dg_name.casefold()) in named_subject_refs
            in_use_by_id = bool(dg_ocid) and dg_ocid.casefold() in id_subject_refs
            in_use = in_use_by_name or in_use_by_id

            dg['in_use'] = in_use
            if not in_use:
                logger.info(f'Dynamic Group {dg_domain}/{dg_name} not in use')
                unused_dynamic_groups += 1

        logger.info(f'Found {unused_dynamic_groups} unused dynamic groups')

    def analyze_policy_overlap(self):  # noqa: C901
        """
        Analyze policy statements for potential overlaps, calling after all statements loaded/parsed.
        Stores result in self.overlay["overlaps"] using the new PolicyIntelligence overlay structure.
        """
        logger.info('Analyzing policy overlaps and building overlay structure')
        start_time = time.perf_counter()
        repo = self.policy_repo
        self.overlay['overlaps'] = []  # Reset on each analysis run

        overlaps_by_internal_id = {}

        for st in repo.regular_statements:
            effective_compartment = st.get('effective_path', '') or 'n/a'
            statement_text = st.get('statement_text', '') or 'n/a'
            policy_overlap = []
            additional_notes = ''
            perm_overlap = []
            reason = ''
            logger.debug(
                f'Analyzing statement "{statement_text}" in policy {st.get("policy_name")}'
                f' for overlaps - effective path: {effective_compartment}'
            )
            for other_st in repo.regular_statements:
                if other_st.get('internal_id', 'N/A') == st.get('internal_id', 'N/A'):
                    continue
                if other_st.get('subject_type') != st.get('subject_type'):
                    continue
                if not other_st.get('effective_path'):
                    continue
                if not effective_compartment.lower().startswith(other_st.get('effective_path', '').lower()):
                    continue

                other_permissions = other_st.get('permission') or repo.permission_reference_repo.get_permissions(
                    entity=other_st.get('resource', ''),
                    verb=other_st.get('verb', ''),
                    action=other_st.get('action', 'allow'),
                )
                st_permissions = st.get('permission') or repo.permission_reference_repo.get_permissions(
                    entity=st.get('resource', ''), verb=st.get('verb', ''), action=st.get('action', 'allow')
                )

                logger.debug(
                    f'Checking potential overlap(1) between "{st_permissions}" and "{other_permissions}" for statements "{st.get("policy_name")}:{statement_text}" and "{other_st.get("policy_name")}:{other_st.get("statement_text")}"'
                )
                if not other_permissions and not st_permissions:
                    logger.debug(
                        f'Both statements have no permissions, treating as resource-only overlap check: {st.get("policy_name")}:{statement_text} / {other_st.get("policy_name")}:{other_st.get("statement_text")}'
                    )
                    continue

                if not other_permissions or not st_permissions:
                    if other_st.get('resource', '').lower() != st.get('resource', '').lower():
                        continue
                    logger.debug(
                        f'Potential Overlap (resource) based on resource name match: {st.get("policy_name")}:{statement_text} / {other_st.get("policy_name")}:{other_st.get("statement_text")}'
                    )
                    reason = (
                        f'Exact match on resource name ({st.get("resource")}), subject_type, and at least one subject, '
                        f'with broader effective compartment in other policy ({other_st.get("effective_path")})'
                    )
                    perm_overlap = ['Resource:' + st.get('resource', '')]
                else:
                    perm_overlap = repo.permission_reference_repo.check_overlap(st_permissions, other_permissions)
                    if len(perm_overlap) == 0:
                        continue
                    reason = (
                        f'Permission Overlap between resource {st.get("resource")} '
                        f'and {other_st.get("resource")}, subject_type, and at least one subject, '
                        f'with broader effective compartment in other policy ({other_st.get("effective_path")})'
                    )
                    logger.debug(
                        f'Permission Overlap (permission) Check between "{st_permissions}" and "{other_permissions}": {perm_overlap}'
                    )
                st_subjects = st.get('subject', [])
                other_subjects = other_st.get('subject', [])
                subject_overlap = False
                for st_subj in st_subjects:
                    for other_subj in other_subjects:
                        st0 = st_subj[0]
                        st1 = st_subj[1]
                        oth0 = other_subj[0]
                        oth1 = other_subj[1]
                        if isinstance(st0, list):
                            st0 = '/'.join(map(str, st0))
                        if isinstance(st1, list):
                            st1 = '/'.join(map(str, st1))
                        if isinstance(oth0, list):
                            oth0 = '/'.join(map(str, oth0))
                        if isinstance(oth1, list):
                            oth1 = '/'.join(map(str, oth1))
                        if (str(st0) or '').lower() == (str(oth0) or '').lower() and str(st1).lower() == str(
                            oth1
                        ).lower():
                            subject_overlap = True
                            break
                    if subject_overlap:
                        break
                if not subject_overlap:
                    continue
                logger.debug(
                    f'Potential Overlap: {st.get("policy_name")}:{statement_text} / {other_st.get("policy_name")}:{other_st.get("statement_text")}'
                )
                confidence = 'high'
                if st.get('conditions') or other_st.get('conditions'):
                    logger.debug(
                        f'Policy Overlap detected with WHERE clause: Statement "{statement_text}" in policy {st.get("policy_name")}'
                        f' is potentially superseded by statement {other_st.get("statement_text")} in policy {other_st.get("policy_name")}'
                    )
                    confidence = 'medium'
                    additional_notes = (
                        'Runtime where clause(s) present in one or both statements may affect actual overlap.'
                    )

                policy_overlap.append(
                    PolicyOverlap(
                        superseded_by=other_st['policy_name'],
                        confidence=confidence,
                        reason=reason,
                        statement_text=other_st['statement_text'],
                        internal_id=other_st['internal_id'],
                        permission_overlap=perm_overlap,
                        additional_notes=additional_notes if 'additional_notes' in locals() else '',
                    )
                )
            if len(policy_overlap) > 0:
                overlaps_by_internal_id.setdefault(st.get('internal_id'), policy_overlap)
                logger.debug(
                    f'Policy Overlap(s) found for statement "{statement_text}" in policy {st.get("policy_name")}: {len(policy_overlap)}'
                )
        # Rebuild overlay "overlaps" as list of {'statement_internal_id': ..., 'overlaps': [...] }
        self.overlay['overlaps'] = [
            {'statement_internal_id': k, 'overlaps': v} for k, v in overlaps_by_internal_id.items()
        ]

        end_time = time.perf_counter()
        logger.info(
            f'Initialized policy_overlap overlay for {len(self.overlay["overlaps"])} statements in {end_time - start_time:.2f} seconds'
        )

    def get_policy_overlaps_by_internal_id(self, internal_id: str):
        """
        Returns all PolicyOverlap entries for a given policy statement internal ID by looking up the overlay model.
        """
        for entry in self.overlay.get('overlaps', []):
            if entry.get('statement_internal_id') == internal_id:
                return entry.get('overlaps', [])
        return []

    def get_policy_supersession_by_internal_id(self, internal_id: str) -> dict | None:
        """Return complete-supersession evidence for one statement.

        Args:
            internal_id: Internal ID of the lower-scope candidate statement.

        Returns:
            The directed supersession finding, or ``None`` when the statement
            is not completely covered by eligible ancestor evidence.
        """
        return next(
            (
                finding
                for finding in self.overlay.get('supersessions', []) or []
                if str(finding.get('statement_internal_id') or '') == str(internal_id or '')
            ),
            None,
        )

    def find_invalid_statements(self):  # noqa: C901
        """
        Mark regular policy statements as invalid if they fail various validity checks, such as:
        - Nonexistent Dynamic Groups or Groups
        - Tag-based where-clause references to missing defined tag namespace/key
        - Invalid compartment OCIDs
        - Invalid verbs/resources

        This method modifies the statements in-place, adding an `invalid_reasons` list if applicable.
        """
        repo = self.policy_repo

        # Build a case-insensitive lookup for defined tag namespaces/keys discovered
        # by the repository. Shape:
        #   {
        #     ns_casefold: {
        #        "name": "OriginalNamespace",
        #        "keys": { key_casefold: "OriginalKey" }
        #     }
        #   }
        raw_catalog = getattr(repo, 'defined_tag_namespace_keys', {})
        tag_catalog_index: dict[str, dict[str, dict[str, str] | str]] = {}
        if isinstance(raw_catalog, dict):
            for ns_name, ns_entry in raw_catalog.items():
                ns_name_str = str(ns_name or '').strip()
                if not ns_name_str or not isinstance(ns_entry, dict):
                    continue
                keys_map = ns_entry.get('keys')
                keys_lookup: dict[str, str] = {}
                if isinstance(keys_map, dict):
                    for key_name in keys_map.keys():
                        key_name_str = str(key_name or '').strip()
                        if key_name_str:
                            keys_lookup[key_name_str.casefold()] = key_name_str
                tag_catalog_index[ns_name_str.casefold()] = {
                    'name': ns_name_str,
                    'keys': keys_lookup,
                }

        tag_catalog_available = len(tag_catalog_index) > 0

        for st in repo.regular_statements:
            logger.debug(f'Checking validity for statement: {st.get("statement_text")}')
            # If parsing errors have already populated invalid_reasons, preserve them
            invalid_reasons = list(st.get('invalid_reasons', []))
            # Dynamic Group check
            if st.get('subject_type') == 'dynamic-group':
                for subject in st.get('subject', []):
                    dg_domain = subject[0] or 'default'
                    dg_name = subject[1]
                    # See if this DG exists in our loaded DGs
                    logger.debug(f'Checking DG existence for {dg_domain}/{dg_name}')
                    dg_found = any(
                        dg.get('dynamic_group_name', '').lower() == dg_name.lower()
                        and dg.get('domain_name', 'default').lower() == dg_domain.lower()
                        for dg in repo.dynamic_groups
                    )
                    if not dg_found:
                        st['valid'] = False
                        _append_unique(invalid_reasons, f'Dynamic Group {dg_name} not found in tenancy')
                        logger.debug(f'Dynamic Group {dg_name} not found for statement: {st.get("statement_text")}')
            # Group check
            elif st.get('subject_type') == 'group':
                for subject in st.get('subject', []):
                    group_domain = subject[0] or 'default'
                    group_name = subject[1]
                    logger.debug(f'Checking Group existence for {group_domain}/{group_name}')
                    group_found = any(
                        g.get('group_name', '').lower() == group_name.lower()
                        and g.get('domain_name', 'default').lower() == group_domain.lower()
                        for g in repo.groups
                    )
                    if not group_found:
                        st['valid'] = False
                        _append_unique(invalid_reasons, f'Group {group_name} not found in tenancy')
                        logger.debug(f'Group {group_name} not found for statement: {st.get("statement_text")}')
            # Location check
            # location_invalid_reason = repo.check_statement_location_validity(st)
            # if location_invalid_reason:
            #     st['valid'] = False
            #     invalid_reasons.append(location_invalid_reason)
            #     logger.debug(location_invalid_reason)
            # Verb check
            if st.get('verb') and st.get('verb', '').casefold() not in {'inspect', 'read', 'use', 'manage'}:
                logger.debug(f'Invalid Verb found: {st.get("verb")}')
                st['valid'] = False
                _append_unique(invalid_reasons, f'Invalid Verb ({st.get("verb")}) found')

            # Tag where-clause namespace/key check
            conditions_text = str(st.get('conditions') or '').strip()
            if conditions_text and '.tag.' in conditions_text.casefold():
                if not tag_catalog_available:
                    note = 'Tag namespace catalog unavailable; tag existence validation skipped.'
                    parsing_notes = st.setdefault('parsing_notes', [])
                    _append_unique(parsing_notes, note)
                else:
                    _structure, tag_conditions = collect_tag_conditions(conditions_text)
                    for cond in tag_conditions:
                        ns_name = (cond.tag_namespace or '').strip()
                        key_name = (cond.tag_key or '').strip()
                        if not ns_name:
                            continue

                        ns_entry = tag_catalog_index.get(ns_name.casefold())
                        if not ns_entry:
                            reason = f"Tag namespace '{ns_name}' not found in tenancy defined tags"
                            _append_unique(invalid_reasons, reason)
                            st['valid'] = False
                            continue

                        if key_name:
                            ns_keys = ns_entry.get('keys', {}) if isinstance(ns_entry, dict) else {}
                            if isinstance(ns_keys, dict) and key_name.casefold() not in ns_keys:
                                normalized_ns_name = str(ns_entry.get('name') or ns_name)
                                reason = f"Tag key '{key_name}' not found in tag namespace '{normalized_ns_name}'"
                                _append_unique(invalid_reasons, reason)
                                st['valid'] = False

            if len(invalid_reasons) > 0:
                st['invalid_reasons'] = invalid_reasons

    def calculate_effective_compartment_for_statement(self, st):  # noqa: C901
        """
        Calculate effective compartment OCID and path for a single statement, mutating st in place.
        Uses indexes built via build_compartment_index().
        """
        repo = self.policy_repo
        try:
            if (
                not hasattr(self, 'compartments_by_id') or not hasattr(self, 'compartments_by_path')
            ) and repo.compartments:
                logger.info('Compartment indexes not found, building now for effective compartment calculation.')
                self.build_compartment_index()
        except Exception as idx_exc:
            st['effective_path'] = f'(Error building compartment indexes: {idx_exc})'
            return

        if not hasattr(self, 'compartments_by_id') or not hasattr(self, 'compartments_by_path'):
            st['effective_path'] = '(Compartments not loaded or indexes unavailable)'
            return

        logger.debug(f'-Statement: {st.get("statement_text")}')
        # Case 1 - in tenancy
        if st.get('location_type') == 'tenancy':
            st['effective_compartment_ocid'] = repo.tenancy_ocid
            st['effective_path'] = self._name_path_from_ocid(repo.tenancy_ocid)
            if st['effective_path']:
                st['effective_path'] = st['effective_path'].lower()
            logger.debug(f'Effective (ten) path for {st.get("statement_text")}: {st.get("effective_path")}')
        # Case 2 - Compartment ID
        elif st.get('location_type') == 'compartment id':
            st['effective_compartment_ocid'] = st.get('location')
            st['effective_path'] = self._name_path_from_ocid(st.get('location'))
            if st['effective_path']:
                st['effective_path'] = st['effective_path'].lower()
            _append_unique(st.setdefault('parsing_notes', []), 'Compartment ID used for location')
            logger.debug(f'Effective (id) path for {st.get("statement_text")}: {st.get("effective_path")}')
        # Case 3 - Compartment Name (with or without full path)
        else:
            logger.debug(f'Need to calc eff path for {st.get("statement_text")}')
            location = st.get('location')
            location_str = str(location or '').strip()

            # When location arrives as an absolute hierarchy path (for example
            # ROOT/Finance/Sub), use it directly. This keeps prospective/editor
            # flows aligned with regular-statement effective path semantics and
            # avoids accidental duplication when a path-shaped location is
            # appended to policy_path.
            if location_str and '/' in location_str and ':' not in location_str:
                norm_loc = location_str.replace('\\', '/').strip('/')
                if norm_loc and norm_loc.split('/')[0].casefold() == 'root':
                    abs_eff_path = norm_loc.lower()
                    st['effective_path'] = abs_eff_path
                    st['effective_compartment_ocid'] = self.compartments_by_path.get(abs_eff_path, {}).get('id')
                    _append_unique(st.setdefault('parsing_notes', []), 'Absolute compartment path used for location')
                    logger.debug(
                        'Effective (abs-loc) path for %s: %s',
                        st.get('statement_text'),
                        abs_eff_path,
                    )
                    return

            parts = [p.strip() for p in location.split(':') if p.strip()] if location else []
            policy_path = self._name_path_from_ocid(st.get('compartment_ocid'))
            # Prospective statements may not always carry a concrete
            # compartment_ocid. Fall back to explicit compartment_path from
            # the editor/service payload so relative locations are resolved
            # under the selected policy compartment path.
            if not policy_path:
                cp = st.get('compartment_path')
                if isinstance(cp, str) and cp.strip():
                    policy_path = cp.strip()
            logger.debug(f'Policy Path: {policy_path} / Location parts: {parts}')
            eff_path = policy_path
            logger.debug(f'Initial effective path: {eff_path}')
            logger.debug(f'Compartment OCID for policy: {st.get("compartment_ocid")}')
            comp_name = self._comp_name_path_ocid(st.get('compartment_ocid'))
            # Prospective statements may not carry compartment_ocid. In that
            # case, infer the policy compartment basename from policy_path so
            # first-segment duplicate elimination still works (for example,
            # policy_path ROOT/Dev + location Dev should stay ROOT/Dev).
            if not comp_name and isinstance(policy_path, str) and policy_path.strip():
                pparts = [p for p in policy_path.replace('\\', '/').split('/') if p]
                comp_name = pparts[-1] if pparts else None
            logger.debug(f'Compartment name for compare: {comp_name}')
            if parts and parts[0].casefold() == (comp_name.casefold() if comp_name else ''):
                _append_unique(st.setdefault('parsing_notes', []), 'Deleted compartment from effective location')
                del parts[0]
            for p in parts:
                if eff_path is None:
                    eff_path = ''
                eff_path += f'/{p}'
            if eff_path:
                eff_path = eff_path.lower()
            logger.debug(f'Effective (loc) path for {st.get("statement_text")}: {eff_path}')
            st['effective_path'] = eff_path
            st['effective_compartment_ocid'] = self.compartments_by_path.get(eff_path, {}).get('id')

    def calculate_all_effective_compartments(self):
        """
        Resolve effective compartment for all statements. Loop through all statements and calculate.
        """
        for st in self.policy_repo.regular_statements:
            logger.debug(f'Calculating effective compartment for statement: {st.get("statement_text")}')
            self.calculate_effective_compartment_for_statement(st)

    def build_compartment_index(self):
        """
        Build quick-lookup structures for resolving compartment names and parent/child
        relationships used by calculate_effective_compartment_for_statement().
        """
        repo = self.policy_repo
        self.compartments_by_id = {}
        self.compartments_by_path = {}
        self.children_by_parent = {}

        logger.info(
            f'Building compartment indexes for effective compartment resolution. Compartments loaded: {len(repo.compartments)}'
        )
        for comp in repo.compartments:
            cid = comp.get('id')
            name = comp.get('name')
            parent_id = comp.get('parent_id') or repo.tenancy_ocid
            path = comp.get('hierarchy_path')
            logger.debug(f'***Path is {path}')

            self.compartments_by_id[cid] = {
                'name': name,
                'path': path,
                'parent_id': parent_id,
            }

            if path:
                self.compartments_by_path[path] = {'id': cid, 'name': name}

            self.children_by_parent.setdefault(parent_id, {})[name] = cid

        # TODO: Add these to debugger_tab as options
        logger.debug(f'Compartment by ID index: {self.compartments_by_id}')
        logger.debug(f'Compartment by Path index: {self.compartments_by_path}')
        logger.debug(f'Children by Parent index: {self.children_by_parent}')
        logger.info(
            f'Built compartment index: {len(self.compartments_by_id)} compartments, '
            f'{len(self.children_by_parent)} parents with children.'
        )

    def _name_path_from_ocid(self, ocid: str):
        logger.debug(f'Lookup details: {getattr(self, "compartments_by_id", {})}')
        comp = getattr(self, 'compartments_by_id', {}).get(ocid)
        return comp.get('path') if comp else None

    def _comp_name_path_ocid(self, ocid: str):
        comp = getattr(self, 'compartments_by_id', {}).get(ocid)
        return comp.get('name') if comp else None

    def _check_invalid_location(self, compartment_ocid) -> bool:
        """
        Returns False if the given compartment_ocid is not an active compartment (according to OCI).
        """
        repo = self.policy_repo
        try:
            comp = repo.identity_client.get_compartment(compartment_id=compartment_ocid).data
            if comp.lifecycle_state == 'ACTIVE':
                return True
            else:
                logger.warning(f'Found Compartment but not ACTIVE: {compartment_ocid} was: {comp.lifecycle_state}')
                return False

        except Exception as e:
            logger.debug(f'Compartment OCID {compartment_ocid} not valid: {e}')
            return False

    def calculate_potential_risk_scores(self, where_clause_reduction_pct=50, service_principal_reduction_pct=50):  # noqa: C901
        """
        Calculates potential risk scores for each policy statement.

        Formula: risk = exposure_points × compartments_in_scope (then optional reductions for WHERE clause
        or service principal). Exposure points = sum of each permission's risk by verb level from the
        reference data (inspect=1, read=5, use=50, manage=100). When the statement has a permission list,
        each permission is looked up and its verb-level risk is summed. When it has no permission list,
        the reference repo returns the sum of all permissions for that verb/resource (each weighted by
        its verb). Compartments in scope = number of compartments at or below the statement's effective
        path in the hierarchy (e.g. "in tenancy" with 12 compartments => multiplier 12; a statement
        effective in a sub-compartment has a smaller multiplier).

        Applies a raw score reduction for statements with a WHERE clause, and a further reduction for
        service-principal statements with use/manage verbs (adjustable via service_principal_reduction_pct).

        Results are stored in self.overlay["risk_scores"] as a list of dicts:
          { "statement_internal_id", "score", "notes", "recommendations" }
        """
        logger.info(
            'Calculating potential risk scores with where_clause_reduction_pct=%s, service_principal_reduction_pct=%s',
            where_clause_reduction_pct,
            service_principal_reduction_pct,
        )
        repo = self.policy_repo
        ref_repo = repo.permission_reference_repo
        # Ensure compartment index is built
        if not hasattr(self, 'compartments_by_path') or not self.compartments_by_path:
            self.build_compartment_index()

        # Cap for unknown family/resource: assume no unknown type scores more than 10% of manage all-resources
        all_resources_manage_risk = ref_repo.get_verb_resource_risk('manage', 'all-resources') if ref_repo else 0
        cap_unknown_risk = max(1, int(0.10 * (all_resources_manage_risk or 1)))

        risk_scores = []
        for st in repo.regular_statements:
            internal_id = st.get('internal_id')
            verb = st.get('verb', '').lower()
            resource = st.get('resource', '').lower()
            permissions = st.get('permission', [])
            effective_path = st.get('effective_path', '') or ''
            compartment_exposure = 1
            notes = []
            recommendations = []

            # Exposure points: sum of each permission's risk by verb level (inspect=1, read=5, use=50, manage=100 from reference data)
            if permissions:
                exposure_points = ref_repo.get_permissions_risk_sum(permissions, resource)
                notes.append(
                    f'Exposure points (sum of per-permission risk by verb level from reference data): {exposure_points} '
                    f'for {len(permissions)} permission(s).'
                )
            else:
                exposure_points = ref_repo.get_verb_resource_risk(verb, resource)
                if exposure_points == 0:
                    # Unknown resource or no permissions in reference data; use a small rubric and cap later
                    risk_factor = VERB_RISK_WEIGHTS.get(verb, 1)
                    is_family = '-family' in resource
                    base = 2 if is_family else 1
                    exposure_points = base * risk_factor
                    notes.append(
                        f'No permissions in reference for ({verb}, {resource}); assumed exposure points: {exposure_points} '
                        f'(base {base} × verb weight {risk_factor}).'
                    )
                else:
                    notes.append(
                        f'Exposure points (sum of permissions at verb "{verb}" for resource from reference data): {exposure_points}.'
                    )
            perm_risk_base = exposure_points

            # Cap unknown family/resource so they do not outrank manage all-resources (assume at most 10%)
            resource_ci = (resource or '').lower()
            is_known_family = resource_ci in getattr(ref_repo, 'family_name_map', {})
            res_key = getattr(ref_repo, 'resource_name_map', {}).get(resource_ci)
            is_known_resource = res_key in (ref_repo.data.get('resources', {}) if ref_repo else {})
            if not is_known_family and not is_known_resource and resource_ci and resource_ci != 'all-resources':
                if perm_risk_base > cap_unknown_risk:
                    notes.append(
                        f'Unknown resource: exposure points capped to {cap_unknown_risk} '
                        f'(10% of manage all-resources exposure).'
                    )
                    perm_risk_base = cap_unknown_risk

            # Compartment multiplier: number of compartments at or below this statement's effective path in the hierarchy
            path_lower = effective_path.lower()
            compartments_in_scope = 0
            if path_lower:
                for other_path in self.compartments_by_path or {}:
                    if _path_is_self_or_descendant(other_path, path_lower):
                        compartments_in_scope += 1
                if compartments_in_scope == 0:
                    compartments_in_scope = 1
                notes.append(
                    f'Compartments at or below effective path "{effective_path}": {compartments_in_scope} '
                    f'(statement applies to this compartment and all descendants).'
                )
            else:
                compartments_in_scope = 1
                notes.append('Compartments at or below effective path: 1 (path unknown).')
            compartment_exposure = compartments_in_scope

            total_risk = perm_risk_base * compartment_exposure
            notes.append(
                f'Risk = exposure points × compartments: {perm_risk_base} × {compartment_exposure} = {total_risk}'
            )

            # WHERE clause reduction and recommendation
            has_where_clause = bool(st.get('conditions'))
            if has_where_clause:
                reduction_pct = (
                    where_clause_reduction_pct if isinstance(where_clause_reduction_pct, int | float) else 50
                )
                reduced_risk = int(total_risk * (1.0 - (reduction_pct / 100.0)))
                notes.append(f'WHERE clause present: raw risk reduced by {reduction_pct}% to {reduced_risk}.')
                total_risk = reduced_risk
                recommendations.append(
                    'Test and tighten where clause definition to reduce policy statement blast radius'
                )

            # Service principal reduction: use/manage for service principals is inherently lower risk than group/dynamic-group
            subject_type = (st.get('subject_type') or '').lower()
            if subject_type == 'service' and verb in ('use', 'manage'):
                reduction_pct = (
                    service_principal_reduction_pct if isinstance(service_principal_reduction_pct, int | float) else 50
                )
                reduced_risk = int(total_risk * (1.0 - (reduction_pct / 100.0)))
                notes.append(
                    f'Service principal with {verb}: risk reduced by {reduction_pct}% to {reduced_risk} (lower than group/dynamic-group).'
                )
                total_risk = reduced_risk

            # Generate other recommendations (least privilege, scope reduction, etc.)
            path_is_root = effective_path.lower() == 'root'
            is_family = resource in (ref_repo.data.get('families', {}).keys())
            is_many_perms = (len(permissions) or 0) > 8 or perm_risk_base > 100

            if verb == 'manage' and path_is_root:
                recommendations.append(
                    'High risk: Statement grants MANAGE at tenancy root. Recommend scoping to sub-compartment or to a specific resource where possible.'
                )
            if is_family and verb in {'use', 'manage'} and compartment_exposure > 10:
                recommendations.append(
                    "Consider using 'read' for entire families/resources and reserving 'use' or 'manage' for narrow/specific resources or compartments."
                )
            if is_many_perms and compartment_exposure > 5:
                recommendations.append(
                    "Permissions grant wide access. Consider reducing permission set and limiting the statement's compartment scope."
                )
            if verb == 'manage':
                recommendations.append(
                    "For most scenarios, prefer 'use' for practical operations and 'manage' only when administrative actions are justified."
                )
            if not recommendations and total_risk > 100:
                recommendations.append('Review scope and permissions for potential risk reduction.')

            logger.debug(
                'Risk score for statement %s: base=%s, exposure=%s, total=%s. Notes: %s Recommendations: %s',
                internal_id,
                perm_risk_base,
                compartment_exposure,
                total_risk,
                '; '.join(notes),
                recommendations,
            )
            risk_scores.append(
                {
                    'statement_internal_id': internal_id,
                    'score': int(total_risk),
                    'notes': ' '.join(notes),
                    'recommendations': recommendations,
                }
            )

        self.overlay['risk_scores'] = risk_scores
        logger.info(f'Calculated risk scores for {len(risk_scores)} statements.')

    def build_cleanup_items(self, enabled_check_ids=None):
        """
        Analyze policy repository and collect actionable cleanup items for all key risk categories.
        This should be called BEFORE build_overall_recommendations.

        Args:
            enabled_check_ids: If None, all checks run. Otherwise only run checks whose ID is in this list
                (use CLEANUP_CHECK_IDS). Disabled keys are set to empty list in overlay.

        The lists are attached to self.overlay["cleanup_items"].
        """
        repo = self.policy_repo
        run_all = enabled_check_ids is None
        enabled = set(enabled_check_ids) if enabled_check_ids else set(CLEANUP_CHECK_IDS)

        def _run(check_id):
            return run_all or check_id in enabled

        # (1) Invalid Policy Statements
        invalid_statements = (
            [st for st in repo.regular_statements if st.get('invalid_reasons')] if _run('invalid_statements') else []
        )

        # (2) Unused Groups (only when users were loaded; otherwise we intentionally did not load users).
        # Exclude the special "All Domain Users" group (one per domain); it cannot be deleted and may have zero members.
        if _run('unused_groups') and getattr(repo, 'load_all_users', True):
            unused_groups = [
                group
                for group in repo.groups
                if (group.get('group_name') or '').strip().lower() != ALL_DOMAIN_USERS_GROUP_NAME.lower()
                and not repo.get_users_for_group(group)
            ]
        else:
            unused_groups = []

        # (3) Unused Dynamic Groups
        if _run('unused_dynamic_groups'):
            self.run_dg_in_use_analysis()  # ensure DG in_use fields are updated
            unused_dgs = repo.filter_dynamic_groups({'in_use': [False]})
        else:
            unused_dgs = []

        # (4) Overly broad manage all-resources
        statements_too_open = (
            [
                st
                for st in repo.regular_statements
                if (
                    st.get('verb', '').lower() == 'manage'
                    and st.get('resource', '').lower() == 'all-resources'
                    and st.get('policy_name', '') != 'Tenant Admin Policy'
                )
            ]
            if _run('statements_too_open')
            else []
        )

        # (5) Any-user without where
        anyuser_no_where = (
            [st for st in repo.regular_statements if st.get('subject_type') == 'any-user' and not st.get('conditions')]
            if _run('anyuser_no_where')
            else []
        )

        self.overlay['cleanup_items'] = {
            'invalid_statements': invalid_statements,
            'unused_groups': unused_groups,
            'unused_dynamic_groups': unused_dgs,
            'statements_too_open': statements_too_open,
            'anyuser_no_where': anyuser_no_where,
        }

    def build_overall_recommendations(self, params: dict | None = None):  # noqa: C901
        """
        Build the overall (user-facing) recommendations list for overlay["recommendations"].
        Each recommendation summarizes the count of existing actionable issues.
        Assumes build_cleanup_items has already been called and populated "cleanup_items".
        If no real recommendations are found, yields one informational finding as a placeholder.
        params may include consolidation_strategy_names (list of display names) for workbench cross-link.

        Example of recommendation dict::

            {
                'Recommendation': 'Investigate invalid policy statements',
                'Priority': 'High',
                'Category': 'Policy Hygiene',
                'Notes': '3 invalid policy statement(s) detected. Review the cleanup/fix tab for details.',
                'Action': 'Plan: Review and remediate invalid policy statements',
                'ActionDetail': 'Examine policies with invalid statements and resolve as appropriate.',
            }

        This could change in the future to include risk score-based recommendations.
        """
        params = params or {}
        consolidation_strategy_names = params.get('consolidation_strategy_names') or []
        cleanup = self.overlay.get('cleanup_items', {})
        consolidations = self.overlay.get('consolidations') or []
        supersessions = self.overlay.get('supersessions') or []
        recommendations = []

        # Consolidation: direct user to consolidation documentation/resources and suggest strategies
        if consolidations:
            strategy_hint = ''
            if consolidation_strategy_names:
                strategy_hint = f' Consider strategies: {", ".join(consolidation_strategy_names)}.'
            recommendations.append(
                {
                    'Recommendation': 'Consider consolidating policies',
                    'Priority': 'Medium',
                    'Category': 'Consolidation',
                    'Notes': (
                        f'{len(consolidations)} consolidation opportunity(ies) detected. '
                        'Refer to OCI documentation, Oracle Cloud security blogs, and your local security/identity experts to develop a consolidation plan.'
                    ),
                    **catalog_guidance(
                        'consolidate_policies',
                        ActionDetail=(
                            'Review the listed consolidation candidates, then consult OCI policy documentation, Oracle Security/Cloud blogs, '
                            'and your local cloud security/identity experts to design and implement a safe consolidation approach.'
                            f'{strategy_hint}'
                        ),
                    ),
                }
            )

        removable_supersessions = [
            finding for finding in supersessions if '(Review)' not in str(finding.get('classification') or '')
        ]
        if removable_supersessions:
            recommendations.append(
                {
                    'Recommendation': 'Review fully superseded policy statements',
                    'Priority': 'Medium',
                    'Category': 'Policy Hygiene',
                    'Notes': (
                        f'{len(removable_supersessions)} policy statement(s) are fully covered by an applicable '
                        'unconditional statement at the same or an ancestor scope. Review the Superseded view '
                        'before removing any statement.'
                    ),
                    'Action': 'Review supersession evidence and remove only statements confirmed unnecessary.',
                    'ActionDetail': (
                        'Use the Superseded view to compare candidate permissions and every applicable evidence '
                        'statement. Findings with conditional evidence are intentionally excluded from this summary.'
                    ),
                }
            )

        if cleanup.get('invalid_statements'):
            recommendations.append(
                {
                    'Recommendation': 'Investigate invalid policy statements',
                    'Priority': 'High',
                    'Category': 'Policy Hygiene',
                    'Notes': f'{len(cleanup["invalid_statements"])} invalid policy statement(s) detected. Review the cleanup/fix tab for details.',
                    **catalog_guidance('invalid_statements'),
                }
            )
        if cleanup.get('unused_groups'):
            recommendations.append(
                {
                    'Recommendation': 'Ensure all groups are needed; consider removing unused groups',
                    'Priority': 'Medium',
                    'Category': 'Identity Management',
                    'Notes': f'{len(cleanup["unused_groups"])} unused group(s) (0 members) detected. See cleanup/fix tab for actionable list.',
                    **catalog_guidance('unused_groups'),
                }
            )
        if cleanup.get('unused_dynamic_groups'):
            recommendations.append(
                {
                    'Recommendation': 'Clean up unused Dynamic Groups',
                    'Priority': 'Medium',
                    'Category': 'Identity Management',
                    'Notes': f'{len(cleanup["unused_dynamic_groups"])} unused dynamic group(s) detected. See cleanup/fix tab for actionable list.',
                    **catalog_guidance('unused_dynamic_groups'),
                }
            )
        if cleanup.get('statements_too_open'):
            recommendations.append(
                {
                    'Recommendation': 'Tighten policies that are too open (manage all-resources)',
                    'Priority': 'High',
                    'Category': 'Access Scope',
                    'Notes': f"{len(cleanup['statements_too_open'])} policy statement(s) granting 'manage all-resources' broadly detected. See cleanup/fix tab for details.",
                    **catalog_guidance('statements_too_open'),
                }
            )
        if cleanup.get('anyuser_no_where'):
            recommendations.append(
                {
                    'Recommendation': 'Always limit any-user statements with a concise where clause',
                    'Priority': 'High',
                    'Category': 'Access Scope',
                    'Notes': f"{len(cleanup['anyuser_no_where'])} policy statement(s) with 'any-user' subject and no where clause detected. See cleanup/fix tab for details.",
                    **catalog_guidance('anyuser_no_where'),
                }
            )

        workload_findings = self._workload_identity_hygiene_findings()
        if workload_findings:
            recommendations.append(
                {
                    'Recommendation': 'Tighten OKE workload identity policy conditions',
                    'Priority': 'High',
                    'Category': 'Workload Identity',
                    'Notes': (
                        f'{len(workload_findings)} any-user workload policy statement(s) have incomplete OKE workload identity constraints. '
                        'This check validates policy condition shape only; it does not claim Kubernetes namespace existence.'
                    ),
                    'EvidenceCount': len(workload_findings),
                    'Evidence': workload_findings[:10],
                    **catalog_guidance('oke_workload_identity_hygiene'),
                }
            )

        resource_principal_findings = self._resource_principal_hygiene_findings()
        if resource_principal_findings:
            recommendations.append(
                {
                    'Recommendation': 'Tighten resource principal policy conditions',
                    'Priority': 'Medium',
                    'Category': 'Resource Principal',
                    'Notes': (
                        f'{len(resource_principal_findings)} any-user/any-group resource principal policy statement(s) '
                        'lack recommended principal type or compartment constraints.'
                    ),
                    'EvidenceCount': len(resource_principal_findings),
                    'Evidence': resource_principal_findings[:10],
                    **catalog_guidance('resource_principal_hygiene'),
                }
            )

        tag_findings = self._tag_based_policy_hygiene_findings()
        if tag_findings:
            recommendations.append(
                {
                    'Recommendation': 'Review tag-based policy condition coverage',
                    'Priority': 'Medium',
                    'Category': 'Tag-Based Access',
                    'Notes': f'{len(tag_findings)} policy statement(s) use tag-based conditions that should be reviewed for access-control hygiene.',
                    'EvidenceCount': len(tag_findings),
                    'Evidence': tag_findings[:10],
                    **catalog_guidance('tag_based_policy_hygiene'),
                }
            )

        # Low-priority informational: statements referencing the special "All Domain Users" group
        repo = self.policy_repo
        all_domain_users_refs = 0
        for st in repo.regular_statements:
            if st.get('subject_type') != 'group':
                continue
            for subject in st.get('subject') or []:
                _domain, name = (subject[0] or ''), (subject[1] or '')
                if (name or '').strip().lower() == ALL_DOMAIN_USERS_GROUP_NAME.lower():
                    all_domain_users_refs += 1
                    break
        if all_domain_users_refs:
            recommendations.append(
                {
                    'Recommendation': 'Review usage of the All Domain Users group',
                    'Priority': 'Low',
                    'Category': 'Identity Management',
                    'Notes': f"{all_domain_users_refs} policy statement(s) reference the special 'All Domain Users' group. Consider reviewing whether this broad membership is appropriate.",
                    **catalog_guidance('all_domain_users'),
                }
            )

        # Existing logic for critical recommendations (unchanged)
        for st in repo.regular_statements:
            policy_name = st.get('policy_name', '')
            verb = st.get('verb', '').lower()
            resource = st.get('resource', '').lower()
            if st.get('effective_path', '') is None:
                logger.info(f'Skipping statement with undefined effective_path (fix this): {st.get("statement_text")}')
                # Lets recommend fixing this first
                recommendations.append(
                    {
                        'Recommendation': 'Statement has undefined effective path',
                        'Priority': 'High',
                        'Category': 'Compartment Resolution',
                        'Notes': f'Statement in policy {policy_name} has no effective path calculated. Ensure compartments are loaded and statement locations are valid.',
                        **catalog_guidance(
                            'undefined_effective_path',
                            ActionDetail=f"Check statement: '{st.get('statement_text', '')}' in policy '{policy_name}' for location issues.",
                        ),
                    }
                )
                continue
            eff_path = st.get('effective_path', '').lower()
            conditions = st.get('conditions')
            if (
                policy_name != 'Tenant Admin Policy'
                and verb == 'manage'
                and resource == 'all-resources'
                and eff_path == 'root'
                and not conditions
            ):
                recommendations.append(
                    {
                        'Recommendation': 'Review non-admin statement that grants manage all-resources at root',
                        'Priority': 'Critical',
                        'Category': 'Policy Scope',
                        'Notes': f'Policy {policy_name} grants manage all-resources at root with no conditions. Consider limiting scope or adding conditions.',
                        **catalog_guidance(
                            'manage_all_root',
                            ActionDetail=f"Work with compartment admins to restrict '{policy_name}' or replace 'manage all-resources' with least privilege.",
                        ),
                    }
                )

        # --- AGGREGATED POLICY STATEMENT PER-COMPARTMENT LIMIT RECOMMENDATION ---
        limit_hit = False
        for comp in repo.compartments:
            n_cumulative = comp.get('statement_count_cumulative', 0)
            if n_cumulative >= POLICY_STATEMENT_HARD_LIMIT or n_cumulative >= POLICY_STATEMENT_WARNING_THRESHOLD:
                limit_hit = True
                break
        if limit_hit:
            recommendations.append(
                {
                    'Recommendation': 'Compartment policy statement limits exceeded or near limit',
                    'Priority': 'Critical',
                    'Category': 'Limits',
                    'Notes': (
                        'One or more compartments are near or have exceeded policy statement count limits. '
                        f'See the Limits tab for details and affected compartments (limit: {POLICY_STATEMENT_HARD_LIMIT} per compartment).'
                    ),
                    **catalog_guidance(
                        'limits',
                        ActionDetail=(
                            'Review, consolidate, or delete policy statements in affected compartments.'
                            ' Only a single summary recommendation appears even if multiple limits are exceeded.'
                        ),
                    ),
                }
            )

        # Guarantee at least one recommendation so UI never appears empty:
        if not recommendations:
            recommendations.append(
                {
                    'Recommendation': 'No critical recommendations detected.',
                    'Priority': 'Info',
                    'Category': 'General',
                    'Notes': 'No critical risks found in current policy set.',
                    **catalog_guidance('no_critical'),
                }
            )
        self.overlay['recommendations'] = recommendations
        # Log summary
        critical_count = sum(1 for r in recommendations if r.get('Priority') == 'Critical')
        high_count = sum(1 for r in recommendations if r.get('Priority') == 'High')
        logger.info(
            f'Built overall recommendations: {len(recommendations)} total, {critical_count} critical, {high_count} high.'
        )

    def _workload_identity_hygiene_findings(self) -> list[dict]:
        """Find any-user OKE workload identity policies missing key workload atoms."""

        findings = []
        required_atoms = (
            'request.principal.type',
            'request.principal.cluster_id',
            'request.principal.namespace',
            'request.principal.service_account',
        )
        for st in getattr(self.policy_repo, 'regular_statements', []) or []:
            conditions = _condition_text(st)
            if not _is_any_principal_statement(st) or 'request.principal.type' not in conditions:
                continue
            if "'workload'" not in conditions and '"workload"' not in conditions:
                continue
            missing = [atom for atom in required_atoms if atom not in conditions]
            if missing:
                findings.append(
                    {
                        'Policy': st.get('policy_name') or '',
                        'Statement': st.get('statement_text') or '',
                        'Missing Conditions': ', '.join(missing),
                    }
                )
        return findings

    def _resource_principal_hygiene_findings(self) -> list[dict]:
        """Find broad resource-principal policies missing type or compartment constraints."""

        findings = []
        for st in getattr(self.policy_repo, 'regular_statements', []) or []:
            conditions = _condition_text(st)
            if not _is_any_principal_statement(st) or 'request.principal.' not in conditions:
                continue
            if "'workload'" in conditions or '"workload"' in conditions:
                continue
            missing = []
            if 'request.principal.type' not in conditions:
                missing.append('request.principal.type')
            if 'request.principal.compartment.id' not in conditions:
                missing.append('request.principal.compartment.id')
            if missing:
                findings.append(
                    {
                        'Policy': st.get('policy_name') or '',
                        'Statement': st.get('statement_text') or '',
                        'Missing Conditions': ', '.join(missing),
                    }
                )
        return findings

    def _tag_based_policy_hygiene_findings(self) -> list[dict]:
        """Find tag-condition policy statements that merit review."""

        findings = []
        for st in getattr(self.policy_repo, 'regular_statements', []) or []:
            conditions = str(st.get('conditions') or st.get('condition') or '')
            if '.tag.' not in conditions.lower():
                continue
            tag_conditions = []
            try:
                tag_conditions = collect_tag_conditions(conditions) or []
            except Exception:
                tag_conditions = []
            access_types = {
                str(getattr(cond, 'access_type', '') or getattr(cond, 'left', '')).lower() for cond in tag_conditions
            }
            if not tag_conditions:
                reason = 'Tag condition could not be parsed into structured tag atoms.'
            elif any('freeform' in access_type for access_type in access_types):
                reason = 'Freeform tag conditions are present; defined tags are preferred for access control.'
            else:
                reason = (
                    'Tag-based access condition present; review request/target tag semantics and catalog alignment.'
                )
            findings.append(
                {
                    'Policy': st.get('policy_name') or '',
                    'Statement': st.get('statement_text') or '',
                    'Reason': reason,
                }
            )
        return findings

    def build_policy_consolidation(self):
        """
        Analyze policies/statements for possible consolidation opportunities and
        populate overlay["consolidations"] with a list of dicts::

            {
                "Statement": ...,
                "Policy Name(s)": ...,
                "Compartment": ...,
                "Principal": ...,
                "Service/Resource": ...,
                "Consolidation Reason": ...,
                "Action": ...,         # always present now
                "ActionDetail": ...    # optional, for detail/planning dialog
            }

        Criteria:
            1. Policies with only a single statement (likely consolidation candidate).
            2. Statements with identical principal, compartment, and service/resource,
               but split across multiple differently-named policies (should suggest merge).

        """
        repo = self.policy_repo
        consolidation_findings = []

        # 1. Policies with only a single statement
        policy_statement_count = {}
        policy_statements = {}
        for st in repo.regular_statements:
            pol = st.get('policy_name', '')
            policy_statement_count.setdefault(pol, 0)
            policy_statement_count[pol] += 1
            policy_statements.setdefault(pol, []).append(st)
        for pol, count in policy_statement_count.items():
            if count == 1:
                st = policy_statements[pol][0]
                statement_text = st.get('statement_text', '')
                compartment = st.get('effective_path', '')
                principal = _principal_str(st)
                resource = st.get('resource', '')
                permissions = st.get('permission', [])
                consolidation_findings.append(
                    {
                        'Statement': statement_text,
                        'Policy Name(s)': pol,
                        'Compartment': compartment,
                        'Principal': principal,
                        'Service/Resource': resource or permissions,
                        'Consolidation Reason': f'Policy {pol} has only one statement; consider consolidation if other similar policies exist.',
                        'Action': f"Plan: Review and possibly merge '{pol}' into another policy with similar principal or scope.",
                        'ActionDetail': f"Review statement '{statement_text}' in policy '{pol}' for merge candidates.",
                    }
                )

        # 2. Same principal, compartment, and resource/service spread across policies
        combo_index = {}
        for st in repo.regular_statements:
            principal = _principal_str(st)
            compartment = st.get('effective_path', '')
            resource = st.get('resource', '')
            combo = (principal, compartment, resource)
            if not all(combo):
                continue
            combo_index.setdefault(combo, [])
            combo_index[combo].append(st)
        for combo, sts in combo_index.items():
            # If applies to more than one unique policy
            policy_names = {st.get('policy_name', '') for st in sts}
            if len(sts) > 1 and len(policy_names) > 1:
                statement_texts = '; '.join([st.get('statement_text', '') for st in sts])
                consolidation_findings.append(
                    {
                        'Statement': statement_texts,
                        'Policy Name(s)': ', '.join(sorted(policy_names)),
                        'Compartment': combo[1],
                        'Principal': combo[0],
                        'Service/Resource': combo[2],
                        'Consolidation Reason': 'Multiple policies found with same principal, resource/service, and compartment; recommend merge for clarity.',
                        'Action': f'Plan: Consolidate policies {", ".join(sorted(policy_names))} into one.',
                        'ActionDetail': f'Statements: {statement_texts}.\nEvaluate details and propose a single policy.',
                    }
                )

        self.overlay['consolidations'] = consolidation_findings


def _principal_str(st):
    typ = st.get('subject_type') or ''
    subs = st.get('subject') or []
    # Expect list of tuples; join for display
    if not subs:
        return typ
    sub_list = []
    for sub in subs:
        # tuple or list of two: (domain, name)
        if isinstance(sub, tuple | list):
            domain, name = sub if len(sub) == 2 else ('', '')
            if domain and domain != 'default':
                sub_list.append(f'{typ}:{domain}/{name}')
            else:
                sub_list.append(f'{typ}:{name}')
        elif isinstance(sub, str):
            sub_list.append(f'{typ}:{sub}')
        else:
            sub_list.append(f'{typ}:{str(sub)}')
    return ', '.join(sub_list)
