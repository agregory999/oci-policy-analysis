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
import hashlib
import json
import logging
import queue
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

# Third-party imports
from deepdiff import DeepDiff, parse_path
from oci import config, pagination
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner, SecurityTokenSigner
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.generative_ai import GenerativeAiClient
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
    BaseChatRequest,
    ChatDetails,
    GenericChatRequest,
    Message,
    OnDemandServingMode,
    TextContent,
)
from oci.identity import IdentityClient
from oci.identity.models import Compartment, Policy
from oci.identity_domains import IdentityDomainsClient
from oci.identity_domains.models import DynamicResourceGroup
from oci.loggingsearch import LogSearchClient
from oci.loggingsearch.models import SearchLogsDetails, SearchResult
from oci.signer import load_private_key_from_file

from oci_policy_analysis.logger import get_logger
from oci_policy_analysis.logic.models import (
    DefineStatement,
    DynamicGroup,
    DynamicGroupSearch,
    Group,
    GroupSearch,
    PolicyOverlap,
    PolicySearch,
    PolicyStatement,
    User,
    UserSearch,
)
from reference_data.reference_data_repo import ReferenceDataRepo

# Global logger for this module
logger = get_logger(component='data_repo')

# Reference Data
permission_reference_repo = ReferenceDataRepo()

# Constants
THREADS = 9
POLICY_REGEX = r"""^\s*allow\s+ # Start with allow (and whitespace at front)
    (?P<subjecttype>service|any-user|any-group|dynamic-group|group|resource)\s* # Subject type
    (?P<subject>([\w\/\'\.\\, +-]|,)+?)?\s+(to\s+)? # Subject (optional, can be empty in case of any-user)
    ((?P<verb>read|inspect|use|manage)\s+(?P<resource>[\w-]+)|(?P<perm>{[\s*\w\s*|\s*\w\s*,\s*]+}))\s+ # verb and resource or permission set
    in\s+(?P<locationtype>any-tenancy|tenancy|compartment\s+id|compartment)\s* # Location type
    (?P<location>[\w\':.-]+)?(?:\s+where\s+ # Location
    (?P<condition>.+))? # Condition (optional)
    (?:(?P<optional>\s*\/\/.+))?$ # Comment (optional)
"""
# Case insensitive, allow \n in capture
policy_regex = re.compile(POLICY_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE | re.DOTALL)

# OCID_REGEX = r'ocid1\.\w+\.\w+\.\w*\.\w+'

CROSS_TENANCY_DEFINE_REGEX = r"""
    (?P<statement_type>define)\s+  # Capture statement type
    (?P<define_type>compartment|group|dynamic-group|tenancy)\s+  # Define type
    (?P<principal>\S+)\s+  # Principal (simple name)
    (?:as\s+)(?P<alias>\S+)  # Alias, capturing only the value without 'as '
"""

define_regex = re.compile(CROSS_TENANCY_DEFINE_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)

# CROSS_TENANCY_ADMIT_REGEX = r"""
#     (?P<statement_type>admit)\s+  # Capture statement type
#     (?P<principal>any-user|group\s+(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+)(?:\s*,\s*(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+))*)?\s+  # Principal (any-user or comma-separated groups: domain/group, 'domain'/'group', simple)
#     (?:of\s+)(?P<of_tenancy>tenancy\s+\S+)\s+  # 'of tenancy' clause, excluding 'of '
#     to\s+(?:(?P<permission>{[^}]+})|(?P<action>{[^}]+}|\S+)\s+(?P<resource>\S+))?\s+  # Permission or action + resource, both optional
#     in\s+(?P<location>compartment\s+[\w:]+|tenancy\s+\S+)  # Location (compartment or tenancy)
#     (?P<where_clause>\s+where\s+(?:all\s+)?{[^}]+})?  # Optional where clause
#     (?P<comment>\s*//\s*[^\n]*)?  # Optional comment
# """

# admit_regex = re.compile(CROSS_TENANCY_ADMIT_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)


# CROSS_TENANCY_ENDORSE_REGEX = r"""
#     (?P<statement_type>endorse)\s+  # Capture statement type
#     (?P<principal>any-user|group\s+(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+)(?:\s*,\s*(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+))*\s+|dynamic-group\s+\S+\s+)  # Principal (any-user, groups: domain/group, 'domain'/'group', simple, or dynamic-group)
#     to\s+(?:(?P<permission>{[^}]+})|(?P<action>{[^}]+}|\S+|associate\s+\S+\s+with\s+\S+\s+in\s+(?:compartment\s+[\w:]+|tenancy\s+\S+))\s+(?P<resource>\S+))?\s+  # Permission or action + resource, both optional
#     in\s+(?P<location>compartment\s+[\w:]+|tenancy\s+\S+)  # Location (compartment or tenancy)
#     (?P<of_tenancy_clause>(?:\s+of\s+tenancy\s+\S+)?)  # Optional 'of tenancy' clause
#     (?P<where_clause>\s+where\s+(?:all\s+)?{[^}]+})?  # Optional where clause
#     (?P<comment>\s*//\s*[^\n]*)?  # Optional comment
# """
# endorse_regex = re.compile(CROSS_TENANCY_ENDORSE_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'

# For MCP-specific JSON
VALID_VERBS = {'inspect', 'read', 'use', 'manage'}


class IdentityDataNotLoaded(Exception):
    """Exception raised when identity data is accessed without being loaded."""

    pass


class PolicyAnalysisRepository:
    """This is the main data repository for Policy, Identity, and Compartment data

    During initialization, the entire compartment hierarchy and policy tree is loaded into a central JSON dictionary.
    This central dictionary is then referenced by functions that filter and return a subset of information for display.
    Parsing, additional analysis, and import/export are made available by additional functions exposed.

    Attributes:
        compartments: A list of JSON dicts containing the compartment hierarchy
        regular_statements: A list of JSON dicts containing the individual regular policy statements within an OCI tenancy
        cross_tenancy_statements: A list of JSON dicts containing the individual cross-tenancy policy statements within an OCI tenancy
        defined_aliases: A list of JSON dicts containing the "define" statements within an OCI tenancy, used for cross-tenancy evaluation
        dynamic_groups: A list of JSON dicts containing the Dyanmic Groups present in the OCI tenancy
        identity_domains: A list of JSON dicts containing the Identity Domains in the OCI tenancy
        groups: A list of JSON dicts containing the Groups in the OCI tenancy
        users: A list of JSON dicts containing the Users in the OCI tenancy
        domain_clients: A dict containing the OCI IdentityDomainClients required to collect all of the information
         data_as_of: The timestamp that this data load was completed.
        tenancy_ocid: The OCID of the tenancy being analyzed here.
        identity_client: The OCI client that is initialized and used for all data loading purposes.
    """

    def __init__(self):
        self.compartments = []  # List of dicts: {id, name, parent_id, hierarchy_path, hierarchy_ocids}
        self.regular_statements: list[PolicyStatement] = []
        self.cross_tenancy_statements = []
        self.defined_aliases: list[DefineStatement] = []  # Store define statements as list of dict
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users: list[User] = []
        self.domain_clients = {}
        self.data_as_of = ''
        self.tenancy_ocid = None
        self.identity_client = None
        self.identity_domains_loaded = False
        logger.info('Initialized PolicyAnalysisRepo')

    def initialize_client(
        self,
        use_instance_principal: bool,
        session_token: str | None = None,
        recursive: bool = True,
        profile: str = 'DEFAULT',
    ) -> bool:
        """Initializes the OCI client to be used for all data operations

        Client can be loaded using PROFILE or Instance Principal authentication methods

        Args:
            use_instance_principal: Whether to attempt Instance Principal signer-based authentication
            recursive: Whether to load tenancy data across all compartments, or simply the root (tenancy) compartment
            session: The named OCI Session Token Profile to use - must be present on the file system in the standard OCI location of .oci/config
            profile: The named OCI Profile to use - must be present on the file system in the standard OCI location of .oci/config

        Returns:
            A boolean indicating whether the client was created successfully.  False indicates that an unrecoverable issue occurred
            setting up the client.

        """
        self.session_token = session_token
        self.use_instance_principal = use_instance_principal
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.logging_search_client = LogSearchClient(config={}, signer=self.signer)
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            elif session_token:
                logger.info('Attempt session auth')
                self.config = config.from_file(profile_name=session_token)
                token_file = self.config['security_token_file']
                token = None
                with open(token_file) as f:
                    token = f.read()
                private_key = load_private_key_from_file(self.config['key_file'])
                self.signer = SecurityTokenSigner(token, private_key)
                self.identity_client = IdentityClient({'region': self.config['region']}, signer=self.signer)
                self.tenancy_ocid = self.config['tenancy']
                logger.info('Success session auth')
            else:
                logger.debug(f'Using Profile Authentication: {profile}')
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.logging_search_client = LogSearchClient(self.config)
                self.tenancy_ocid = self.config['tenancy']
            logger.info(f'Set up Identity Client for tenancy: {self.tenancy_ocid}')

            # Set Recursion
            self.recursive = recursive
            logger.debug(f'Set recursive to: {self.recursive}')

            # Get tenancy name
            self.tenancy_name = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid).data.name

            # Return True because we got the clients
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    # --- Internal Helpers ---
    def get_policy_overlaps_by_internal_id(self, internal_id: str) -> list[PolicyOverlap]:
        """Given an internal ID, return the list of PolicyOverlap entries for that statement"""
        overlaps: list[PolicyOverlap] = []
        for st in self.regular_statements:
            if st.get('internal_id') == internal_id:
                overlaps = st.get('policy_overlap', [])
                break
        return overlaps

    def _find_invalid_statements(self):  # noqa: C901
        """
        Find invalid statements.  Mark them as invalid with reason.
        Currently checks for:
        - Dynamic Groups that do not exist
        - Groups that do not exist
        - Locations (OCID based compartments) that do not exist
        - Valid verbs / resources
        """
        # Policy Statements can be invalid for several reasons, maybe even more than 1.
        # TODO: Expand this function to check more invalid cases

        # Create an empty list to hold invalid reasons - only add to dict if more than 0 found
        for st in self.regular_statements:
            invalid_reasons = []
            # Dynamic Group check
            if st['subject_type'] == 'dynamic-group':
                for subject in st['subject']:
                    dg_domain = subject[0] or 'default'
                    dg_name = subject[1]
                    # See if this DG exists in our loaded DGs
                    logger.debug(f'Checking DG existence for {dg_domain}/{dg_name}')
                    dg_found = any(
                        dg.get('dynamic_group_name').lower() == dg_name.lower()
                        and dg.get('domain_name', 'default').lower() == dg_domain.lower()
                        for dg in self.dynamic_groups
                    )
                    if not dg_found:
                        st['valid'] = False
                        invalid_reasons.append(f'Dynamic Group {dg_name} not found in tenancy')
                        logger.warning(f"Dynamic Group {dg_name} not found for statement: {st['statement_text']}")
            # Group check
            elif st['subject_type'] == 'group':
                for subject in st['subject']:
                    group_domain = subject[0] or 'default'
                    group_name = subject[1]
                    # See if this Group exists in our loaded Groups
                    logger.debug(f'Checking Group existence for {group_domain}/{group_name}')
                    group_found = any(
                        g.get('group_name').lower() == group_name.lower()
                        and g.get('domain_name', 'default').lower() == group_domain.lower()
                        for g in self.groups
                    )
                    if not group_found:
                        st['valid'] = False
                        invalid_reasons.append(f'Group {group_name} not found in tenancy')
                        logger.warning(f"Group {group_name} not found for statement: {st['statement_text']}")
            # Location check
            if st['location_type'] == 'compartment id':
                location_ocid = st['location']
                if not self._check_invalid_location(location_ocid):
                    st['valid'] = False
                    invalid_reasons.append(f'Compartment OCID {location_ocid} not found in tenancy')
                    logger.warning(f"Compartment OCID {location_ocid} not found for statement: {st['statement_text']}")
            # Verb check
            if st['verb'] and st['verb'].casefold() not in VALID_VERBS:
                logger.warning(f"Invalid Verb found: {st['verb']}")
                st['valid'] = False
                invalid_reasons.append(f'Invalid Verb ({st['verb']}) found')

            # if there are reasons, add to the statement
            if len(invalid_reasons) > 0:
                st['invalid_reasons'] = invalid_reasons

    def _calculate_effective_compartments_for_statements(self):
        """
        Resolve effective compartment for all statements.  Loop through all statements and calculate
        """
        for st in self.regular_statements:
            logger.debug(f"-Statement: {st.get('statement_text')}")
            # Case 1 - in tenancy
            if st.get('location_type') == 'tenancy':
                st['effective_compartment_ocid'] = self.tenancy_ocid
                st['effective_path'] = self._name_path_from_ocid(self.tenancy_ocid)
                logger.debug(f"Effective (ten) path for {st.get('statement_text')}: {st.get('effective_path')}")
            # Case 2 - Compartment ID
            elif st.get('location_type') == 'compartment id':
                st['effective_compartment_ocid'] = st.get('location')
                st['effective_path'] = self._name_path_from_ocid(st.get('location'))
                st['parsing_notes'].append('Compartment ID used for location')
                logger.debug(f"Effective (id) path for {st.get('statement_text')}: {st.get('effective_path')}")
            # Case 3 - Compartment Name (with or without full path)
            # Note - if location refers to current compartment, we need to remove that from the path
            else:
                logger.debug(f"Need to calc eff path for {st.get('statement_text')}")
                location = st.get('location')
                parts = [p.strip() for p in location.split(':') if p.strip()]
                policy_path = self._name_path_from_ocid(st.get('compartment_ocid'))
                logger.debug(f'Policy Path: {policy_path} / Location parts: {parts}')

                # If the first element of the path is the same as the policy compartment name, remove it from cosideration
                eff_path = policy_path
                comp_name = self._comp_name_path_ocid(st.get('compartment_ocid'))
                logger.debug(f'Compartment name for compare: {comp_name}')
                # We need just the name of the compartment of the policy, get from
                if parts[0].casefold() == comp_name.casefold():
                    st['parsing_notes'].append('Deleted compartment from effective location')
                    del parts[0]
                for p in parts:
                    eff_path += f'/{p}'
                logger.debug(f"Effective (loc) path for {st.get('statement_text')}: {eff_path}")
                st['effective_path'] = eff_path
                st['effective_compartment_ocid'] = self.compartments_by_path.get(eff_path, {}).get('id')

    def _name_path_from_ocid(self, ocid: str) -> str | None:
        """Lookup full root:...:name path from a compartment OCID."""
        comp = self.compartments_by_id.get(ocid)
        return comp.get('path') if comp else None

    def _comp_name_path_ocid(self, ocid: str) -> str | None:
        """Get compartment name from compartment OCID."""
        comp = self.compartments_by_id.get(ocid)
        return comp.get('name') if comp else None

    def _build_compartment_index(self) -> None:
        """
        Build quick-lookup structures for resolving compartment names and parent/child
        relationships used by _calculate_effective_compartments_for_statements().
        """

        # Build these idexes for use later
        self.compartments_by_id: dict[str, dict[str, str]] = {}
        self.compartments_by_path: dict[str, dict[str, str]] = {}
        self.children_by_parent: dict[str, dict[str, str]] = {}

        for comp in self.compartments:  # however you store them
            cid = comp.get('id')
            name = comp.get('name')
            parent_id = comp.get('parent_id') or self.tenancy_ocid
            # There is no path at this point, maybe we can generate it now
            path = comp.get('hierarchy_path')
            logger.debug(f'***Path is {path}')
            # path, ocids = self._get_compartment_path(comp, 0, '')
            # path = comp.get("path")

            # Index by id
            self.compartments_by_id[cid] = {
                'name': name,
                'path': comp.get('hierarchy_path'),
                'parent_id': parent_id,
            }

            # Index by path
            if path:
                self.compartments_by_path[path] = {'id': cid, 'name': name}

            # Build children_by_parent
            self.children_by_parent.setdefault(parent_id, {})[name] = cid

        logger.info(
            f'Built compartment index: {len(self.compartments_by_id)} compartments, '
            f'{len(self.children_by_parent)} parents with children.'
        )

    def _get_compartment_path(self, compartment: Compartment, level: int, comp_string: str) -> tuple[str, list[str]]:
        """Recursive function to generate a compartment's path to the root"""
        hierarchy_ocids = [compartment.id]
        logger.debug(f'Processing compartment {compartment.name} (OCID: {compartment.id}) at level {level}')
        if not compartment.compartment_id:
            logger.debug(f'Reached root compartment: {compartment.name} (OCID: {compartment.id})')
            return f'ROOT{comp_string}', hierarchy_ocids  # type: ignore
        try:
            parent_response = self.identity_client.get_compartment(compartment_id=compartment.compartment_id)
            if parent_response.data is None:
                logger.warning(f'Failed to get parent compartment for {compartment.id}')
                return comp_string, hierarchy_ocids  # type: ignore
            parent_path, parent_ocids = self._get_compartment_path(
                parent_response.data, level + 1, f'/{compartment.name}{comp_string}'
            )
            hierarchy_ocids.extend(parent_ocids)
            logger.debug(f'Compartment {compartment.name} path: {parent_path}, OCIDs: {hierarchy_ocids}')
            return parent_path, hierarchy_ocids
        except Exception as e:
            logger.error(f'Error getting parent compartment for {compartment.id}: {e}')
            return comp_string, hierarchy_ocids

    def _check_invalid_location(self, compartment_ocid) -> bool:
        """Given a compartment OCID-based location, return False if there is no compartment (any more)"""

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

    def _parse_subjects(self, subject_string) -> list[tuple[str, str]]:
        """Parse a comma-separated string of subjects and return list of (domain, name) tuples"""
        # Split by comma and strip whitespace
        subject_parts = [part.strip() for part in subject_string.split(',')]
        results: list[tuple[str, str]] = []

        for part in subject_parts:
            if not part:  # Skip empty parts
                continue

            logger.debug(f"  DEBUG: Processing part: '{part}'")

            # Check if it contains a separator (/ or \)
            if '/' in part or '\\' in part:
                # Split on the separator
                if '/' in part:
                    separator_parts = part.split('/', 1)  # Split only on first occurrence
                else:
                    separator_parts = part.split('\\', 1)  # Split only on first occurrence

                if len(separator_parts) == 2:
                    domain_part = separator_parts[0].strip()
                    name_part = separator_parts[1].strip()

                    # Remove quotes from domain and name
                    domain = domain_part.strip('\'"')
                    name = name_part.strip('\'"')

                    logger.debug(f"  DEBUG: Found separator - domain: '{domain}', name: '{name}'")
                    results.append((domain, name))
                else:
                    # Shouldn't happen, but fallback
                    clean_name = part.strip('\'"')
                    logger.debug(
                        f"  DEBUG: Separator found but couldn't split properly - using as simple name: '{clean_name}'"
                    )
                    results.append(('Default', clean_name))
            else:
                # No separator, it's just a name
                clean_name = part.strip('\'"')
                logger.debug(f"  DEBUG: No separator - simple name: '{clean_name}'")
                results.append(('Default', clean_name))

        return results

    def _parse_statement(self, statement: str, comp_id: str, policy: Policy) -> bool:  # noqa: C901
        """Parses a policy statement into component parts
        Subject / Verb / Resource(or permission) / Location / Conditions (opt) / Comments (opt)

        This is the main parsing logic that uses Regular Expressions and post-parsing logic.
        An example of post-parsing would be to separate the subject list into an actual list of tuples
        representing the domain and group or dynamic group.
        """
        comp = self.get_compartment_by_id(comp_id)
        logger.debug(f'Parsing statement {statement} (Comp: {comp})')
        comp_string = comp['hierarchy_path'] if comp else 'ROOT'

        # internal ID for statement, used for reference later
        internal_id = hashlib.md5((statement + policy.id).encode()).hexdigest()
        logger.debug(f'Internal ID for statement: {internal_id}')
        # Basic statement dict - will be augmented after parsing
        statement_dict: PolicyStatement = PolicyStatement(
            policy_name=policy.name,  # type: ignore
            policy_ocid=policy.id,  # type: ignore
            compartment_ocid=comp_id,
            policy_compartment=comp_string,
            statement_text=statement,
            creation_time=str(policy.time_created),
            valid=True,  # Mark as False later if needed
            parsed=False,  # Mark as True later if parsed successfully
            internal_id=internal_id,  # Adding this for display
        )

        # Only for ROOT compartment, check to see if there is a cross-tenancy policy
        logger.debug(f'Checking to see if Cross-tenancy: {statement}')

        # Define case
        if comp_id == self.tenancy_ocid and statement.startswith('define'):
            # Parse Define
            try:
                # result = re.search(CROSS_TENANCY_DEFINE_REGEX, statement, re.IGNORECASE | re.MULTILINE)
                result = define_regex.match(statement).groupdict()
                logger.debug(f'Result Define: {result}')
                if result.get('alias') and result.get('principal'):
                    logger.debug(
                        f"Adding to Defined Aliases - Name: {result.get('principal')}, Type: {result.get('define_type')}, OCID: {result.get('alias')}"
                    )
                    define_dict: DefineStatement = DefineStatement(
                        policy_name=policy.name,
                        policy_ocid=policy.id,
                        policy_description=policy.description,
                        statement_text=statement,
                        valid=True,
                        creation_time=str(policy.time_created),
                        defined_type=result.get('define_type'),
                        defined_name=result.get('principal'),
                        ocid_alias=result.get('alias'),
                    )
                    self.defined_aliases.append(define_dict)

                    return True
            except Exception as e:
                logger.warning(f'Failed to parse define: {e}')
                return False

        # Admit/endorse case (not parsing at the moment)
        elif comp_id == self.tenancy_ocid and (statement.startswith('admit') or statement.startswith('endorse')):
            # TODO: parse these properly - for now, just store them

            self.cross_tenancy_statements.append(statement_dict)
            return True
            # TODO: try cross-tenancy parsing again

        # Regular Statements are everything else
        else:
            # Regular Statements
            logger.debug(f'Hierarchy string: {comp_string}')

            # Process Results of regex
            match_result = policy_regex.match(statement)
            if match_result and match_result.groupdict():
                result = match_result.groupdict()
                logger.debug(f"Subject parsed 1: {result.get('subject')} ||| Statement: {statement}")
                try:
                    # Populate parsed fields
                    statement_dict['valid'] = True  # Currently for Validity
                    statement_dict['subject_type'] = result.get('subjecttype') or 'other'
                    statement_dict['subject'] = result.get('subject') or ''
                    statement_dict['verb'] = result.get('verb') or ''
                    statement_dict['resource'] = result.get('resource') or ''
                    statement_dict['permission'] = []
                    statement_dict['location_type'] = result.get('locationtype') or ''
                    statement_dict['location'] = result.get('location') or ''
                    statement_dict['conditions'] = result.get('condition') or ''
                    statement_dict['comments'] = result.get('optional') or ''
                    statement_dict['parsing_notes'] = []
                    statement_dict['parsed'] = True  # Currently for parsed
                    # Additional Subject Parsing
                    if statement_dict['subject_type'] in ['any-user', 'any-group']:
                        statement_dict['subject'] = [(None, statement_dict['subject_type'])]
                    else:
                        # subject_result = re.findall(SUBJECT_REGEX, statement_list[7], re.IGNORECASE)
                        # Try new subject parser
                        subject_result = self._parse_subjects(statement_dict['subject'])
                        logger.debug(f'Subject parsed: {subject_result}')
                        # statement_list[7] = [(a[2] or "Default", a[4]) for a in subject_result]
                        if len(subject_result) > 1:
                            statement_dict['parsing_notes'].append('Multiple subjects found')
                        statement_dict['subject'] = subject_result

                    # If permissions are present, parse them into a list.
                    if result.get('perm'):
                        # permissions looks like {permission1,permission2, permission3}
                        # Strip the braces and split , and strip whitespace
                        perms = result.get('perm').strip('{}').split(',')
                        perms = [p.strip() for p in perms if p.strip()]
                        logger.info(f'Parsed permissions from {result.get("perm")} to {perms}')
                        statement_dict['permission'] = perms
                        statement_dict['parsing_notes'].append(f'Parsed {len(perms)} permissions from permission set.')
                    # If the location was wrapped in quotes, remove them
                    if statement_dict['location']:
                        statement_dict['location'] = statement_dict['location'].strip('\'"')
                except Exception as e:
                    logger.warning(f'Failed to parse statement: {e}')

            else:
                logger.warning(f'No regex match for statement: |{statement}|')

            logging.debug(f'Parsed Statement as JSON: {statement_dict}')
            self.regular_statements.append(statement_dict)

            # Success or fail based on parsed field
            return True if statement_dict.get('parsed') else False

        # Catch All - should never get here
        logger.warning(f'Should not get here.  Statement not added to anything: {statement}')

        return False

    def _parse_dynamic_group(self, domain_name: str, dg: DynamicResourceGroup) -> DynamicGroup:
        """Extract the contents of the DG into a dict"""
        logger.debug(f'Created by: {dg.idcs_created_by}')
        return DynamicGroup(
            domain_name=domain_name,
            dynamic_group_name=dg.display_name,
            dynamic_group_id=dg.id,
            description=dg.description or '',
            matching_rule=dg.matching_rule,
            in_use=True,  # Placeholder until analysis is run
            dynamic_group_ocid=dg.ocid,
            creation_time=str(dg.meta.created),
            created_by_ocid=dg.idcs_created_by.ocid if dg.idcs_created_by else None,
            created_by_name=dg.idcs_created_by.display if dg.idcs_created_by else None,
        )

    # --- Main Data Loading Functions ---
    def load_compartment_and_policies_worker(self, compartment: Compartment):
        """Worker function to load compartment and policy data as JSON object in a thread"""
        try:
            start_time = time.perf_counter()
            # Load compartment data
            logger.info(f'Processing compartment: {compartment.name} (OCID: {compartment.id})')
            # Do this instead of build_compartment index
            path, ocids = self._get_compartment_path(compartment, 0, '')
            self.compartments.append(
                {
                    'id': compartment.id,
                    'name': compartment.name if compartment.id != self.tenancy_ocid else 'ROOT',
                    'parent_id': compartment.compartment_id,
                    'hierarchy_path': path,
                    'hierarchy_ocids': ocids,
                }
            )
            logger.debug(f'Loaded compartment: {compartment.name}, Path: {path}, OCID: {compartment.id}')

            # Load policies for the compartment
            policies_response = self.identity_client.list_policies(compartment_id=compartment.id, limit=1000)
            if policies_response and policies_response.data:
                logger.debug(f'Looping policies for comp: {compartment.name} ({len(policies_response.data)})')
                load_pol_time = time.perf_counter()
                this_comp_count: int = 0
                for policy in policies_response.data:
                    for statement in policy.statements:
                        # Maybe just let the parser add to either list - returns False if not parsed
                        if not self._parse_statement(str.casefold(statement), compartment.id, policy):  # type: ignore
                            logger.warning(f'Statement was unable to parse: {statement}')
                        this_comp_count += 1

                parse_time = time.perf_counter()
                logger.debug(f'{compartment.name}: Policy Load {this_comp_count} regular, {len(self.cross_tenancy_statements)} CT policies and \
{len(self.defined_aliases)} aliases in {load_pol_time-start_time:.2f} and parse all in {parse_time-load_pol_time:.2f}s')

            else:
                logger.debug(f'No policies found for compartment: {compartment.id}')
                return
            parse_time = time.perf_counter()
            logger.debug(f'{compartment.name}: Policy Load {this_comp_count} regular, {len(self.cross_tenancy_statements)} CT policies and \
{len(self.defined_aliases)} aliases in {load_pol_time-start_time:.2f} and parse all in {parse_time-load_pol_time:.2f}s')

        except Exception as se:
            logger.error(f'Failed to load compartment or policies for {compartment.id}: {se}')

    def load_policies_and_compartments(self) -> bool:
        """Load all compartments and policies from a tenancy using OCI Clients.

        If recursive was selected, use a thread pool and the worker function.

        Returns:
            a boolean indicating success or failure
        """
        self.compartments = []
        self.regular_statements: list[PolicyStatement] = []
        self.cross_tenancy_statements: list[PolicyStatement] = []
        self.defined_aliases: list[DefineStatement] = []
        start_time = time.perf_counter()
        try:
            root_comp_response = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid)
            if root_comp_response.data is None:
                logger.error(f'Failed to get root compartment: {self.tenancy_ocid}')
                return False
            root_comp = root_comp_response.data
            comp_list = [root_comp]
            logger.info(f'Loaded root compartment: {root_comp.name} (OCID: {root_comp.id})')
            # If recursive, get all compartments
            if self.recursive:
                logger.debug('Loading compartments recursively')
                comp_response = pagination.list_call_get_all_results(
                    self.identity_client.list_compartments,
                    self.tenancy_ocid,
                    access_level='ACCESSIBLE',
                    sort_order='ASC',
                    # compartment_id_in_subtree=False,
                    compartment_id_in_subtree=True,
                    lifecycle_state='ACTIVE',
                    limit=1000,
                )
                if comp_response.data is None:
                    logger.error('Failed to list compartments')
                    return False
                comp_list.extend(comp_response.data)
            logger.info(f'All compartments loaded: {len(comp_list)}')
            # Catch the load time for compartments
            comp_load_time = time.perf_counter()

            # Load all of the policy data in threaded worker if recursive
            if self.recursive:
                # Use a thread pool
                with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='thread') as executor:
                    executor.map(self.load_compartment_and_policies_worker, comp_list)
            else:
                # Call the worker on its own with just the root compartment
                self.load_compartment_and_policies_worker(compartment=root_comp)

            # Now self.compartments exists. If we build the index from it, won't be as slow
            self._build_compartment_index()

            # Print indexes
            logger.debug(f'Compartments by id: {self.compartments_by_id}')
            logger.debug(f'Compartments by path: {self.compartments_by_path}')
            logger.debug(f'Children by parent: {self.children_by_parent}')

            # Now call effective compartment code - for all
            self._calculate_effective_compartments_for_statements()

            # Find invalid statements - e.g., invalid dynamic groups
            self._find_invalid_statements()

            # Mark Dynamic groups as invalid if not used in any statement
            self.run_dg_in_use_analysis()

            # Keep track of the time of this completed data load
            self.data_as_of = str(datetime.now(UTC))
            policy_finish_time = time.perf_counter()
            logger.info(
                f'Loaded {len(self.compartments)} compartments in {comp_load_time-start_time:.2f} and {len(self.regular_statements)} policies in {policy_finish_time-comp_load_time:.2f}s'
            )
            return True
        except Exception as e:
            logger.error(f'Failed to load policies and compartments: {e}')
            return False

    def get_compartment_by_id(self, compartment_id: str) -> dict:
        return next((c for c in self.compartments if c['id'] == compartment_id), None)

    def load_complete_identity_domains(self) -> bool:  # noqa: C901
        """Loads everything into the cetntral JSON

        Identity Domains are loaded via the Identity Client.
        For each Identity Domain, load the Dynamic Groups, Groups, and Users

        Args:
            none

        Returns:
            A boolean indicating success of the data load.  False indicates there was some failure in loading data,
            so it may be incomplete.
        """
        # Clean up any existing data
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users = []
        try:
            domain_response = self.identity_client.list_domains(compartment_id=self.tenancy_ocid)  # type: ignore
            if domain_response.data is None:  # type: ignore
                logger.error('Failed to list identity domains')
                return False
            # Should we really keep the full thing?
            self.identity_domains = domain_response.data
            logger.info(f'Loaded {len(self.identity_domains)} identity domains')

            self.domain_clients = {}

            for domain in self.identity_domains:
                try:
                    # Get IdentityDomainsClient and hold on to it
                    if self.use_instance_principal:
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

                    # Load Dynamic Groups
                    dg_response = domain_client.list_dynamic_resource_groups(attribute_sets=['all'])
                    if dg_response and dg_response.data:
                        logger.debug(
                            f'Got the List of DG for {domain.display_name}.  Count: {len(dg_response.data.resources)}'
                        )
                        for dg in dg_response.data.resources:
                            logger.debug(f'DG: {dg.display_name}')
                            # Append the Dynamic Group dict to the list
                            self.dynamic_groups.append(
                                self._parse_dynamic_group(domain_name=domain.display_name, dg=dg)
                            )
                    else:
                        logger.error('Failed to list dynamic groups')
                        return False

                    # Load Groups
                    start_index = 1
                    limit = 1000
                    while True:
                        group_response = domain_client.list_groups(
                            start_index=start_index, count=limit, sort_by='displayName', sort_order='ASCENDING'
                        )
                        if group_response.data is None or not group_response.data.resources:
                            break
                        for g in group_response.data.resources:
                            logger.debug(f'Group: {g}')

                            # Set the group into the bigger picture JSON
                            self.groups.append(
                                Group(
                                    domain_name=domain.display_name,
                                    group_name=g.display_name,
                                    group_ocid=g.ocid,
                                    group_id=g.id,
                                    description=g.urn_ietf_params_scim_schemas_oracle_idcs_extension_group_group.description
                                    if g.urn_ietf_params_scim_schemas_oracle_idcs_extension_group_group
                                    else '',
                                )
                            )
                        # Logic to re-start new request
                        if (
                            len(group_response.data.resources) < limit
                            or start_index + limit > group_response.data.total_results
                        ):
                            break
                        start_index += limit
                    logging.debug(f'All Groups: {self.groups}')

                    # Load Users
                    start_index = 1
                    while True:
                        user_response = domain_client.list_users(
                            start_index=start_index,
                            count=limit,
                            sort_by='displayName',
                            sort_order='ASCENDING',
                            attribute_sets=['all'],
                        )
                        if user_response.data is None or not user_response.data.resources:
                            break
                        for u in user_response.data.resources:
                            logging.debug(f'User: {u}')
                            if not u.groups:
                                logging.debug(f'No groups for user {u.display_name}')
                                continue
                            group_list = []
                            for gg in u.groups:
                                group_list.append(gg.ocid)
                            # Default the email to None
                            email = 'None'
                            if hasattr(u, 'emails') and u.emails:
                                for em in u.emails:
                                    if em.primary:
                                        email = em.value
                                        break
                            else:
                                logger.debug(f'No emails for user {u.display_name}')
                            # Set the user into the bigger picture JSON
                            self.users.append(
                                User(
                                    domain_name=domain.display_name,
                                    user_name=u.user_name,
                                    user_ocid=u.ocid,
                                    display_name=u.display_name,
                                    email=email,
                                    user_id=u.id,
                                    groups=group_list,
                                )
                            )

                        # Loop Logic
                        if (
                            len(user_response.data.resources) < limit
                            or start_index + limit > user_response.data.total_results
                        ):
                            break
                        start_index += limit
                    logging.debug(f'All Users: {self.users}')

                    self.data_as_of = str(datetime.now(UTC))

                    # Indicate we loaded successfully
                    self.identity_domains_loaded = True
                except Exception as e:
                    logger.error(f'Failed to load groups/users for domain {domain.id}: {e}')
                    raise
            logger.info(
                f'Loaded {len(self.groups)} groups, {len(self.users)} users, {len(self.dynamic_groups)} dynamic groups across all domains'
            )

            return True
        except Exception as e:
            logger.error(f'Failed to load identity domains: {e}')
            # return False
            raise e

    # --- Main Filtering Functions ---
    # Filtering logic - return a list of policy statements matching given filter
    # Single policy filter function that resolves fuzzy search if provided, exact search if provided, and then other criteria if provided
    # If multiple criteria are provided, they are ANDed together
    # If multiple values are provided for a single criteria, they are ORed together
    # If no criteria are provided, return all policy statements
    # If no policy statements exist, return empty list
    # Fuzzy and Exact search are mutually exclusive - if both are provided, fuzzy search is used
    # If Identity Domains are not loaded and either fuzzy or exact search is requested, raise an error
    def filter_policy_statements(self, filters: PolicySearch) -> list[PolicyStatement]:  # noqa: C901
        """Filter policy statements based on provided criteria.
        Args:
            filters (PolicySearch): An object containing filter criteria:
                - exact_groups (list[Group]| None): Exact groups to search for policy statements.  List of Group, which includes domain_name and group_name
                - exact_users (list[User]| None): Exact users to search for policy statements.  List of User, which contains domain_name and user_name
                - exact_dynamic_groups (list[DynamicGroup]| None): Exact dynamic groups to search for policy statements.  List of DynamicGroup, which contains domain_name and name
                - search_groups (GroupSearch | None): Fuzzy search string for policy statements.
                - search_users (UserSearch | None): Fuzzy search string for policy statements.
                - search_dynamic_groups (DynamicGroupSearch | None): Fuzzy search string for policy statements.
                - subject_type (list[str] | None): List of subject types to filter by.
                - verb (list[str] | None): List of verbs to filter by.
                - resource (list[str] | None): List of resources to filter by.
                - permission (list[str] | None): List of permissions to filter by.
                - location_type (list[str] | None): List of location types to filter by.
                - location (list[str] | None): List of locations to filter by.
                - policy_compartment (list[str] | None): List of compartment names or "ROOTONLY" to filter by.
                - effective_path (list[str] | None): List of effective compartment paths or "ROOTONLY" to filter by.
                - effective_compartment_ocid (list[str] | None): List of effective compartment OCIDs to filter by.
                - conditions (list[str] | None): List of conditions to filter by.
                - valid (bool | None): Filter by validity of policy statements.
                - creation_time_range (tuple[datetime | None, datetime | None] | None): Creation time range to filter by.
        Returns:
            list[PolicyStatement]: A list of policy statements matching the filter criteria.
        Raises:
            ValueError: If fuzzy or exact search is requested but identity domains are not loaded.
        """
        logger.info(f'Filtering policy statements with criteria: {filters}')

        # If fuzzy or exact search is requested, identity domains must be loaded. If not, raise an error
        if (filters.get('search_groups') or filters.get('exact_groups')) and not self.identity_domains_loaded:
            raise IdentityDataNotLoaded('Identity domains must be loaded to filter policy statements.')
        if (filters.get('search_users') or filters.get('exact_users')) and not self.identity_domains_loaded:
            raise IdentityDataNotLoaded('Identity domains must be loaded to filter policy statements.')
        if (
            filters.get('search_dynamic_groups') or filters.get('exact_dynamic_groups')
        ) and not self.identity_domains_loaded:
            raise IdentityDataNotLoaded('Identity domains must be loaded to filter policy statements.')

        # If fuzzy search is provided, use it and ignore exact search.
        self._resolve_fuzzy_search(filters=filters)
        # If exact users were provided for filtering, resolve them to domain/name tuples
        self._resolve_exact_users(filters=filters)

        # At this point we have exact groups or exact dynamic groups to deal with
        logger.info(f'Post-fuzzy/exact search filters: {filters}')
        # Apply regular search - AND all provided fields except fuzzy search
        results = []

        for stmt in self.regular_statements:
            match = True

            for key, values in filters.items():
                if key == 'exact_groups':
                    # Get the groups from the exact filter
                    logger.debug(f'Filtering on exact_groups with values: {values}')
                    groups_filter = filters.get('exact_groups', None)
                    # Only applies to statements where "subject_type" == "group"
                    if stmt.get('subject_type') != 'group':
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to subject_type not 'group'")
                        match = False
                        break
                    subjects = stmt.get('subject', [])
                    if not isinstance(subjects, list):
                        logger.warning(f"Unexpected Subject format in statement {stmt.get('policy_name')}: {subjects}")
                        match = False
                        break
                    if len(groups_filter) == 0:
                        logger.debug('No groups in exact_groups filter, thus no match possible')
                        match = False
                        break
                    # A match occurs if any provided domain and group name combo matches any subject in the statement (case-insensitive)
                    subj_matched = False
                    for subj_domain, subj_name in subjects:
                        # Now we need to iterate the provided groups and see if any match
                        for group in groups_filter:
                            group_domain = group.get('domain_name') or 'default'
                            group_name = group.get('group_name')
                            if (
                                subj_domain.casefold() == group_domain.casefold()
                                and subj_name.casefold() == group_name.casefold()
                            ):
                                logger.debug(
                                    f"Matched group {subj_domain}/{subj_name} in statement {stmt.get('policy_name')} to filter group {group_domain}/{group_name}"
                                )
                                subj_matched = True
                    if not subj_matched:
                        logger.debug(
                            f"No match found for exact_group filter in statement {stmt.get('policy_name')} Text: {stmt.get('statement_text')} Statement: {stmt.get('subject')}"
                        )
                        match = False  # If we get here, no match found
                        break

                # For exact dynamic group, similar logic
                elif key == 'exact_dynamic_groups' and values:
                    logger.debug(f'Filtering on exact_dynamic_groups with values: {values}')
                    dyn_groups_filter = filters.get('exact_dynamic_groups', [])
                    if stmt.get('subject_type') != 'dynamic-group':
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to Subject Type not 'dynamic-group'")
                        match = False
                        break
                    subjects = stmt.get('subject', [])
                    if not isinstance(subjects, list):
                        logger.warning(f"Unexpected Subject format in statement {stmt.get('policy_name')}: {subjects}")
                        match = False
                        break
                    subj_matched = False
                    for subj_domain, subj_name in subjects:
                        for dg in dyn_groups_filter:
                            dg_domain = dg.get('domain_name') or 'default'
                            dg_name = dg.get('dynamic_group_name')
                            if (
                                subj_domain.casefold() == dg_domain.casefold()
                                and subj_name.casefold() == dg_name.casefold()
                            ):
                                logger.debug(
                                    f"Matched dynamic group {subj_domain}/{subj_name} in statement {stmt.get('policy_name')} to filter group {dg_domain}/{dg_name}"
                                )
                                subj_matched = True
                    if not subj_matched:
                        logger.debug(
                            f"No match found for exact_dynamic_groups filter in statement {stmt.get('policy_name')} Text: {stmt.get('statement_text')} Statement: {stmt.get('subject')}"
                        )
                        match = False  # If we get here, no match found
                        break
                # Compartment special: ROOTONLY
                elif key == 'policy_compartment' and 'ROOTONLY' in values:
                    if stmt.get('compartment_ocid') != self.tenancy_ocid:
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to ROOTONLY restriction")
                        match = False
                        break
                elif key == 'location' and 'tenancy' in values:
                    if stmt.get('location_type', '').casefold() != 'tenancy':
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to location not tenancy")
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
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to verb mismatch: {field_value}")
                        match = False
                        break
                # Validity check
                elif key == 'valid':
                    valid_value = values
                    statement_valid_value = stmt.get('valid', False)
                    logger.debug(f'Filtering on validity: {valid_value} vs {statement_valid_value}')
                    if valid_value != statement_valid_value:
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to validity mismatch")
                        match = False
                        break
                # Effective path search
                elif key == 'effective_path':
                    filter_eff_value = values[0].lower()
                    statement_eff_value = str(stmt.get('effective_path', '')).lower()
                    logger.debug(f'Filtering on filt/st {filter_eff_value} vs {statement_eff_value}')
                    # Logic here - if the effective path given contains the effective path of the statement,
                    # then it is a match.  This allows searching for all policies effective in a given compartment and its children.
                    if not (filter_eff_value.startswith(statement_eff_value)):
                        logger.debug(
                            f"Rejecting {stmt.get('policy_name')} due to effective_path mismatch: "
                            f"{statement_eff_value} not in {filter_eff_value}"
                        )
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
                    if not any(val.lower() in field_value for val in values):
                        logger.debug(f"Rejecting {stmt.get('policy_name')} due to {key} mismatch")
                        match = False
                        break

            if match:
                results.append(stmt)

        logger.info(f'Filter applied. {len(results)} matched out of {len(self.regular_statements)}')
        return results

    def filter_cross_tenancy_policy_statements(self, alias_filter: list[str]) -> list[PolicyStatement]:
        # Iterate cross-tenant policies
        filtered = []
        for statement in self.cross_tenancy_statements:
            for alias_to_check in alias_filter:
                # Check each alias to see if in statement test
                statement_text = statement.get('statement_text', '')
                if alias_to_check in statement_text:
                    logger.info(f'Adding statement (alias={alias_to_check}): {statement_text}')
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
        logger.info(f'Looking for users in group: {group_domain}/{group_name}')
        logger.info(f'Number of groups: {len(self.groups)}  Number of users: {len(self.users)}')
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
                logger.debug(f"User found. Groups: {u.get('groups')}")

                for user_group_ocid in u.get('groups', []):
                    # Find the Group OCID in the groups and append
                    for g in self.groups:
                        if g.get('group_ocid') == user_group_ocid:
                            # Now append as tuple
                            groups_for_user.append(g)
                            logger.debug(f"Adding Group {g.get('domain_name')} / {g.get('group_name')} ")
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
                term.lower() in str(u.get('username')).lower() for term in user_filter.get('search')
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
                term in str(g.get('group_name')).lower() for term in group_filter.get('group_name')
            )
            matches_domain = not group_filter.get('domain_name') or any(
                term in str(g.get('domain_name')).lower() for term in group_filter.get('domain_name', ['default'])
            )
            matches_ocid = not group_filter.get('group_ocid') or any(
                term in str(g.get('group_ocid')).lower() for term in group_filter.get('group_ocid')
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

    def _resolve_fuzzy_search(self, filters: PolicySearch):  # noqa: C901
        """Look for fuzzy search and turn it into an exact search"""
        logger.debug(f"Resolve fuzzy Groups: {filters.get('search_groups')}")
        logger.debug(f"Resolve fuzzy Users: {filters.get('search_users')}")
        logger.debug(f"Resolve fuzzy DG: {filters.get('search_dynamic_groups')}")

        # First do fuzzy user search
        if filters.get('search_users'):
            user_filter: UserSearch = filters.get('search_users')
            logger.info(f'User filter to check: {user_filter}')
            filtered_users = self._user_search_internal(user_filter)
            logger.info(f'User search returned {len(filtered_users)} users')
            # Now, for each user, get their groups and add to exact groups
            exact_groups: list[Group] = []
            for u in filtered_users:
                user_groups: list[Group] = self.get_groups_for_user(u)
                exact_groups.extend(user_groups)

            # De-dup exact groups
            seen = set()
            deduplicated_list = []
            for group in exact_groups:
                identifier = (group.get('domain_name') or 'Default', group.get('group_name'))
                if identifier not in seen:
                    seen.add(identifier)
                    deduplicated_list.append(group)
            exact_groups = deduplicated_list
            # Set exact groups into filter that was passed in
            filters['exact_groups'] = exact_groups
            del filters['search_users']
            logger.info(f'Added {len(exact_groups)} exact groups to filter (removed fuzzy user search)')
        # Next, fuzzy group search
        elif filters.get('search_group'):
            group_filter: GroupSearch = filters.get('search_groups')
            exact_groups: list[Group] = self._group_search_internal(group_filter)

            # De-dup exact groups
            seen = set()
            deduplicated_list = []
            for group in exact_groups:
                identifier = (group.get('domain_name') or 'Default', group.get('group_name'))
                if identifier not in seen:
                    seen.add(identifier)
                    deduplicated_list.append(group)
            exact_groups = deduplicated_list
            # Set exact groups into filter that was passed in
            filters['exact_groups'] = exact_groups
            # remove the fuzzy search
            del filters['search_groups']
            logger.info(f'Added {len(exact_groups)} exact groups to filter')
        # Finally, fuzzy dynamic group search
        elif filters.get('search_dynamic_groups'):
            dg_filter: DynamicGroupSearch = filters.get('search_dynamic_groups')
            exact_dgs: list[DynamicGroup] = self._dynamic_group_search_internal(dg_filter)

            # Set exact DGs into filter that was passed in
            filters['exact_dynamic_groups'] = exact_dgs
            # Remove fuzzy search
            del filters['search_dynamic_groups']
            logger.info(f'Added {len(exact_dgs)} exact dynamic groups to filter (removed fuzzy dynamic group search)')
        else:
            logger.debug('No fuzzy logic executed, search not changed.')

    def _resolve_exact_users(self, filters: PolicySearch):
        """Look for exact users and turn them into groups"""
        if not filters.get('exact_users'):
            return
        user_filter: list[User] = filters.get('exact_users')
        # Start with no groups and iterate users
        exact_groups: list[Group] = []
        for u in self.users:
            # We need an exact match on domain and username
            user_domain = u.get('domain_name') or 'default'
            user_name = u.get('user_name')
            for filter_user in user_filter:
                filter_domain = filter_user.get('domain_name') or 'default'
                filter_name = filter_user.get('user_name')

                logger.debug(
                    f'Checking actual user {user_domain}/{user_name} against filter user {filter_domain}/{filter_name}'
                )
                if (
                    filter_domain.casefold() == user_domain.casefold()
                    and filter_name.casefold() == user_name.casefold()
                ):
                    # get groups for user
                    logger.debug(f'Exact user match found: {user_domain}/{user_name}')
                    uu: User = {'domain_name': user_domain, 'user_name': user_name}  # type: ignore
                    user_groups: list[Group] = self.get_groups_for_user(uu)
                    logger.debug(f'User groups: {user_groups}')
                    # add groups into exact match in filter
                    exact_groups.extend(user_groups)
        # De-dup exact groups
        seen = set()
        deduplicated_list = []
        for group in exact_groups:
            identifier = (group.get('domain_name') or 'Default', group.get('group_name'))
            if identifier not in seen:
                seen.add(identifier)
                deduplicated_list.append(group)
        exact_groups = deduplicated_list
        # Set exact groups into filter that was passed in
        filters['exact_groups'] = exact_groups
        del filters['exact_users']
        logger.info(f'Exact User Search {len(exact_groups)} exact groups to filter (removed exact user search)')

    def filter_groups(self, group_filter: GroupSearch) -> list[Group]:
        """Filter groups based on the provided filter.  Public function used by MCP or UI"""
        filtered = []
        logger.info(f'Filtering Groups based on: {group_filter}')

        filtered: list[Group] = self._group_search_internal(group_filter)

        logger.info(f'Filtered to {len(filtered)} groups')
        return filtered

    def filter_users(self, user_filter: UserSearch) -> list[User]:
        """
        Filter users based on the provided filter.  Public function used by MCP or UI
        Args:
            user_filter (UserSearch): A dictionary with optional keys:
                - 'domain_name' (list[str]): List of domain names to filter by (case-insensitive).
                - 'search' (list[str]): List of search terms to match against usernames and display names (case-insensitive).
                - 'user_ocid' (list[str]): List of user OCIDs to filter by (case-insensitive).
        Returns:
            list[User]: A list of users that match the filter criteria. Each user is represented as a dictionary with keys:
                - 'domain_name' (str | None): The domain name of the user.
                - 'user_name' (str): The username.
                - 'user_ocid' (str): The OCID of the user.
                - 'display_name' (str): The display name of the user.
                - 'email' (str): The email of the user.
                - 'user_id' (str): The ID of the user.
                - 'groups' (list[str]): List of group OCIDs the user belongs to.
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
                - OR: multiple values within a field act as logical OR.
                - AND: multiple fields are combined as logical AND.
                - Supported keys:
                    * domain_name      → matches "Domain"
                    * dynamic_group_name        → matches "DG Name"
                    * matching_rule        → matches "Matching Rule"
                    * dynamic_group_ocid      → matches "DG OCID"
                    * in_use      → matches "In Use" (True/False)

        Returns:
            list[DynamicGroup]: A list of dynamic groups that satisfy the filters. Each dynamic group is represented as a dictionary with keys:
                - 'domain_name' (str | None): The domain name of the dynamic group.
                - 'dynamic_group_name' (str): The name of the dynamic group.
                - 'dynamic_group_id' (str): The ID of the dynamic group.
                - 'dynamic_group_ocid' (str): The OCID of the dynamic group.
                - 'matching_rule' (str): The matching rule of the dynamic group.
                - 'description' (str): The description of the dynamic group.
                - 'in_use' (bool): Whether the dynamic group is in use.
                - 'creation_time' (str): The creation timestamp of the dynamic group.
                - 'created_by_name' (str): The name of the user who created the dynamic group.
                - 'created_by_ocid' (str): The OCID of the user who created the dynamic group.
        Raises:
            ValueError: If an unknown filter key is provided.
        """
        results = []
        logger.info(f'Filtering Dynamic Groups based on: {filters}')

        for dg in self.dynamic_groups:
            match = True

            for key, values in filters.items():
                # Check in-use first because it is special
                if key == 'in_use':
                    if not values and not dg.get('in_use', False):
                        logger.debug(
                            f"DG included {dg.get('dynamic_group_name')} due to in_use match: {dg.get('in_use')} = {values}"
                        )
                        continue
                    else:
                        logger.debug(
                            f"DG rejected {dg.get('dynamic_group_name')} in_use: {dg.get('in_use')} != {values}"
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
                        logger.debug(f"Rejecting DG {dg.get('DG Name')} due to {key} mismatch")
                        match = False
                        break

            if match:
                results.append(dg)

        logger.info(f'Filter applied. {len(results)} matched out of {len(self.dynamic_groups)}')
        return results

    # --- Other Public Functions ---
    def compare_against_cache(self, cached_tenancy: str, cached_date: str) -> str:
        """Loads a cache set and compares with the currently loaded policy set and return changes"""
        # What I need to do is be given the names of a cache file, load it, and then compare the policies to what is in memory
        # Loading the cache is similar to the main loading, but do not want these in memory
        changes = []

        # Load the referenced cache
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        combined_cache_file = CACHE_DIR / f'combined_cache_{cached_tenancy}_{cached_date}.json'
        # Load policies
        if combined_cache_file.exists():
            with open(combined_cache_file, encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
            cached_policies = cache_data.get('policies', [])
            self.cached_dynamic_groups = cache_data.get('dynamic_groups', [])
            self.cached_cross_tenency_policies = cache_data.get('cross_tenancy_policies', [])
            logger.info(f'Loaded {len(cached_policies)} statements from cache: {combined_cache_file}')
            logger.info(f'Currently {len(self.regular_statements)} statements in memory from {self.data_as_of}')

            # Do the comparison with deepdiff (do we need to sort the policies first?)
            # Include paths for the maximum length
            # max_len = max(len(self.regular_statements), len(cached_policies))
            # include_paths = [f"root[{i}]['statement_text']" for i in range(max_len)]
            diff = DeepDiff(
                self.regular_statements,
                cached_policies,
                ignore_order=True,
                verbose_level=2,
                # include_paths=include_paths,
                # exclude_paths=["root['data']"]
                # include_paths="root[*]['statement_text']"  # Only compare the statement text
                # group_by=
            )

            logger.info(
                f'Found {len(diff.get("iterable_item_added", []))} added, '
                f'{len(diff.get("iterable_item_removed", []))} removed, '
                f'{len(diff.get("values_changed", []))} changed policies'
            )
            for change_type, changes_list in diff.items():
                logger.info(f'Change Type: {change_type}')
                if change_type == 'values_changed':
                    for i, change in enumerate(changes_list):
                        change_index_parsed = parse_path(change)
                        logger.info(f'Changed{i}: Index:{change} Parsed: {change_index_parsed}')
                        if len(change_index_parsed) == 2 and change_index_parsed[1] == 'statement_text':
                            # Change to statement
                            this_change = changes_list[change]
                            # logger.info(f'- New: {this_change["new_value"]}\n')
                            # logger.info(f'- Old: {this_change["old_value"]}\n')
                            changes.append(
                                f'Changed Statement #{change_index_parsed[0]} from {this_change["old_value"]} to {this_change["new_value"]}'
                            )
                            logger.info(
                                f'Changed Statement #{change_index_parsed[0]} from {this_change["old_value"]} to {this_change["new_value"]}'
                            )
                        else:
                            logger.info(f'Change: {changes_list[change]}\n')

                elif change_type == 'iterable_item_removed':
                    for i, change in enumerate(changes_list):
                        this_change = changes_list[change]
                        change_index_parsed = parse_path(change)
                        changes.append(
                            f'Removed Statement{i} #{change_index_parsed[0]} - {this_change["statement_text"]}'
                        )
                        logger.info(f'Removed Statement #{change_index_parsed[0]} - {this_change["statement_text"]}')

                        # logger.info(f'Removed({i}): Index:{change_index_parsed}: {changes_list[change]}\n\n')
                elif change_type == 'iterable_item_added':
                    for i, change in enumerate(changes_list):
                        this_change = changes_list[change]
                        change_index_parsed = parse_path(change)
                        changes.append(
                            f'Added Statement{i} #{change_index_parsed[0]} - {this_change["statement_text"]}'
                        )
                        logger.info(f'Added Statement #{change_index_parsed[0]} - {this_change["statement_text"]}')

                        # logger.info(f'Added({i}): Index:{change_index_parsed}: {changes_list[change]}\n\n')

        else:
            logger.warning(f'Policies cache file not found: {combined_cache_file}')
            return ''
        return '\n'.join(changes)

    def run_dg_in_use_analysis(self) -> None:
        """Analyzes Dynamic Group data for unused Dynamic Groups

        Given a list of policy statements, iterates to see if each dynamic group is used.  If not, it
        is marked with "In Use" = False, for later display

        Args:
            policy_statements: A list of JSON dicts containing a policy statement each
        """

        # Build a list of all subjects as list(tuple(domain,name))
        all_subjects: list[tuple] = []
        for st in self.regular_statements:
            subject_list = st.get('subject') or []
            subject_type = st.get('subject_type')
            logger.debug(f'SubType: {subject_type} Subject: {subject_list}')
            if subject_type == 'dynamic-group':
                logger.debug(f'Add: {subject_type} Subject: {subject_list}')
                all_subjects.extend(subject_list)

        logger.info(f'all subjects: {len(all_subjects)}')
        # all_subjects = list(set(all_subjects))
        # logger.info(f"all subjects: {len(all_subjects)}")

        # Iterate all DGs, look at their Domain and Name, then look through each statement
        unused_dynamic_groups = 0
        for dg in self.dynamic_groups:
            dg_domain = dg.get('domain_name') or 'default'
            dg_name = dg.get('dynamic_group_name')
            in_use = False  # Will be true at end if it exists
            # Iterate our subject list
            for subj_domain, subj_name in all_subjects:
                logger.debug(f'Compare {dg_domain} = {subj_domain} and {dg_name} = {subj_name}')
                if dg_domain.casefold() == subj_domain.casefold() and dg_name.casefold() == subj_name.casefold():
                    in_use = True
                    break
            # Now if in_use still False, change the DG itself
            if not in_use:
                logger.info(f'Dynamic Group {dg_domain}/{dg_name} not in use')
                dg['in_use'] = False
                unused_dynamic_groups += 1

        logger.info(f'Found {unused_dynamic_groups} unused dynamic groups')

    def analyze_policy_overlap(self) -> None:  # noqa: C901
        """Analyze policy overlaps by comparing statements across policies."""
        logger.info('Analyzing policy overlaps - setting up structure for comparison')
        for st in self.regular_statements:
            # Get effective compartment
            effective_compartment = st.get('effective_path', '') or 'n/a'
            statement_text = st.get('statement_text', '') or 'n/a'
            policy_overlap = []
            logger.info(
                f'Analyzing statement "{statement_text}" in policy {st["policy_name"]} for overlaps - effective path: {effective_compartment}'
            )
            # Loop against all other statements
            for other_st in self.regular_statements:
                # Qualify OUT quickly - self-comparison
                if other_st.get('internal_id', 'N/A') == st.get('internal_id', 'N/A'):
                    continue
                # Non-matching subject types
                if other_st.get('subject_type') != st.get('subject_type'):
                    continue
                # Effective Path missing
                # if not other_st.get('effective_path') or not other_st.get('resource') or not other_st.get('verb'):
                #     continue
                if not other_st.get('effective_path'):
                    continue
                # Effective path must be broader or same in other_st
                # for example, if other is ROOT/A/B and this statement is ROOT/A/B/C, then continue processing
                # if other is ROOT/A/B/C or ROOT/C and this is ROOT/A/B, then skip
                if not effective_compartment.lower().startswith(other_st.get('effective_path', '').lower()):
                    continue

                # if there are explicit permissions, use those. otherwise get them from the repo
                other_permissions = other_st.get('permission') or permission_reference_repo.get_permissions(
                    entity=other_st.get('resource', ''), verb=other_st.get('verb', '')
                )
                st_permissions = st.get('permission') or permission_reference_repo.get_permissions(
                    entity=st.get('resource', ''), verb=st.get('verb', '')
                )

                logger.debug(
                    f'Checking potential overlap(1) between "{st_permissions}" and "{other_permissions}" for statements "{st["policy_name"]}:{statement_text}" and "{other_st["policy_name"]}:{other_st["statement_text"]}"'
                )
                # If either list is empty, assume we haven't mapped these resources yet, so compare resource itself
                if not other_permissions or not st_permissions:
                    if other_st.get('resource', '').lower() != st.get('resource', '').lower():
                        continue
                    logger.debug(
                        f'Potential Overlap (resource) based on resource name match: {st["policy_name"]}:{statement_text} / {other_st["policy_name"]}:{other_st["statement_text"]}'
                    )
                    reason = (
                        f'Exact match on resource name ({st["resource"]}), subject_type, and at least one subject, '
                        f'with broader effective compartment in other policy ({other_st["effective_path"]})'
                    )
                # The repo can find the overlaps - will be a list of permissions that overlap
                perm_overlap = permission_reference_repo.check_overlap(st_permissions, other_permissions)
                if len(perm_overlap) == 0:
                    continue
                # Permission overlap found
                reason = (
                    f'Permission Overlap on permissions {perm_overlap} between resource {st["resource"]} '
                    f'and {other_st["resource"]}, subject_type, and at least one subject, '
                    f'with broader effective compartment in other policy ({other_st["effective_path"]})'
                )
                logger.debug(
                    f'Permission Overlap (permission) Check between "{st_permissions}" and "{other_permissions}": {perm_overlap}'
                )

                # Now check subjects for overlap - each statement has a list of multiple subjects that are tuples (domain,subject)
                st_subjects = st.get('subject', [])
                other_subjects = other_st.get('subject', [])
                subject_overlap = False
                for st_subj in st_subjects:
                    for other_subj in other_subjects:
                        if (st_subj[0] or '').lower() == (other_subj[0] or '').lower() and st_subj[
                            1
                        ].lower() == other_subj[1].lower():
                            subject_overlap = True
                            break
                    if subject_overlap:
                        break
                if not subject_overlap:
                    continue
                logger.info(
                    f'Potential Overlap: {st["policy_name"]}:{statement_text} / {other_st["policy_name"]}:{other_st["statement_text"]}'
                )
                # Now we have a potential overlap
                # Confidence level is lower if there is a where clause in either statement
                confidence = 'high'
                if st.get('conditions') or other_st.get('conditions'):
                    logger.info(
                        f'***Policy Overlap detected with WHERE clause: Statement "{statement_text}" in policy {st["policy_name"]} '
                        f'is potentially superseded by statement {other_st["statement_text"]} in policy {other_st["policy_name"]}'
                    )
                    confidence = 'medium'

                policy_overlap.append(
                    PolicyOverlap(
                        superseded_by=other_st['policy_name'],
                        confidence=confidence,
                        reason=reason,
                        statement_text=other_st['statement_text'],
                        internal_id=other_st['internal_id'],
                    )
                )
            if len(policy_overlap) > 0:
                st['policy_overlap'] = policy_overlap
                logger.info(
                    f'Policy Overlap(s) found for statement "{statement_text}" in policy {st["policy_name"]}: {len(policy_overlap)}'
                )
        logger.info(f'Initialized policy_overlap lists for {len(self.regular_statements)} statements')

    # Not in use
    def _check_history(self, policy_ocid: str, start_time: str) -> None:
        """Look at audit logs to track changes to a policy"""
        the_log = f'{self.tenancy_ocid}/_Audit'
        logs_returned = self.logging_search_client.search_logs(
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

                    # if 'type' in res.data:
                    #     logger.info(f'Type: {res.data["type"]}')
                    # else:
                    #     logger.info('No type found in log data')
                # logger.info(f'Log: {log.get["data"].get("datetime", "No message found")}')
        else:
            logger.info('No policy update logs found in the last 24 hours')
        pass

    def _get_domains(self) -> list:
        return [{'id': d.id, 'display_name': d.display_name, 'url': d.url} for d in self.identity_domains]


class AI:
    """AI Module for OCI Policy Analysis

    Contains all of the available GenAI calls that can be made to obtain additional context.

    Attributes:
        genai_client: The OCI GenAI Client.
        genai_inference_client: The OCI GenAI Inference Client
    """

    def __init__(self):
        """Initialize OCI GenAI client and constants."""
        logger.info('Initialized AI Module')

        # Mark not initialized
        self.initialized = False

    def initialize_client(self, use_instance_principal: bool, profile: str = 'DEFAULT') -> bool:
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication for AI')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.genai_client = GenerativeAiClient(config={}, signer=self.signer)
                self.genai_inference_client = GenerativeAiInferenceClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
                self.region = self.signer.region
            else:
                logger.debug(f'Using Profile Authentication for AI: {profile}')
                self.config = config.from_file(profile_name=profile)
                self.genai_client = GenerativeAiClient(self.config)
                self.genai_inference_client = GenerativeAiInferenceClient(self.config)
                self.tenancy_ocid = self.config['tenancy']
                self.region = self.config['region']
            logger.info(f'Set up GenAI and Inference Client for tenancy: {self.tenancy_ocid}')

            # Set up base endpoint
            self.base_endpoint = f'https://inference.generativeai.{self.region}.oci.oraclecloud.com'
            self.initialized = True
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def update_config(self, model_ocid, endpoint, compartment_ocid):
        """Update Model ID and Endpoint, reinitializing client if endpoint changes."""
        logger.info(
            f'Updating AI config: Model OCID:{model_ocid}, Endpoint:{endpoint}, Compartment: {compartment_ocid}'
        )
        self.model_ocid = model_ocid
        self.endpoint = endpoint
        self.compartment_ocid = compartment_ocid

    def create_chat_request(self, prompt):
        # Create Chat Details
        chat_detail = ChatDetails()
        chat_detail.serving_mode = OnDemandServingMode(model_id=self.model_ocid)

        content = TextContent()
        content.text = prompt

        chat_request = GenericChatRequest()
        chat_request.api_format = BaseChatRequest.API_FORMAT_GENERIC
        chat_request.messages = [Message(role='USER', content=[content])]
        chat_request.max_tokens = 1500
        chat_request.temperature = 0
        chat_request.top_p = 0.25
        chat_request.top_k = 0

        chat_detail.chat_request = chat_request
        chat_detail.compartment_id = self.compartment_ocid
        logger.info(f'Created Chat Request with prompt: {prompt}')
        logger.debug(f'Created Chat: {chat_detail}')
        return chat_detail

    def list_models(self) -> list[dict]:
        """List available models using GenerativeAiClient.list_models."""
        logger.info('Listing available models')
        try:
            # Try to list models from tenancy
            response = self.genai_client.list_models(compartment_id=self.tenancy_ocid)
            models = [
                {
                    'Model Name': model.display_name or 'Unknown',
                    'Model OCID': model.id,
                    'Lifecycle State': model.lifecycle_state or 'N/A',
                    'Creation Date': model.time_created.isoformat() if model.time_created else 'N/A',
                }
                for model in response.data.items
            ]
            # for model in models:
            #     self.model_name_cache[model['id']] = model['display_name']
            logger.info('Retrieved %d models from list_models', len(models))
            return models
        except ServiceError as e:
            logger.error('Service error listing models: %s', e)
            raise
        except Exception as e:
            logger.error('Error listing models: %s', e)
            raise

    async def analyze_policy_statement(  # noqa: C901
        self, policy_text: str, queue: queue.Queue = None, additional_instruction: str = ''
    ):  # noqa: C901
        """Call OCI GenAI to analyze an OCI IAM policy statement, using cache if available.

        Given an OCI Policy Statement, analyze using AI. Put the results on a Queue that if provided.
        Otherwise, return the data directly as Markdown.

        Args:
            policy_text: The OCI Policy statement string to analyze
            queue: An initialized Queue object, on which to put the response.  None if you expect a reply directly
            additional_instruction: An optional line of additional instruction for the AI Prompt.

        Returns:
            The result in markdown, if a queue was not provided.
        """
        logger.info('Analyzing policy statement: %s', policy_text)

        start_time = time.perf_counter()
        logger.info(f'Calling OCI GenAI for policy analysis: {policy_text}')
        prompt = (
            f"Describe OCI Policy permission '{policy_text}' in detail, including what it allows, typical use cases, and any important considerations. "
            'Format the response in GFM markdown with clear sections using the 3rd level ### header For each section. '
            'Avoid empty lines in lists and ensure all content is concise and relevant. '
            'Use unordered lists (- item) for permissions and use cases, ensuring each list item has meaningful content and no empty items. '
            'Give the original policy statement back in a fenced code block '
            "Include a direct documentation link if available under a 'Documentation' section. "
            f'{additional_instruction} '
        )
        chat_detail = self.create_chat_request(prompt=prompt)
        # Make the request
        try:
            response = self.genai_inference_client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logger.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            # Process result
            if isinstance(raw_content, list):
                logger.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logger.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logger.debug(f"Extracted 'text' attribute from first item: {policy_text} = {result[:100]}")
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logger.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logger.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logger.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logger.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logger.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logger.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logger.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logger.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logger.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logger.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logger.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logger.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logger.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logger.error('Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000])
                result = f'Error: Extracted content is not a string: {type(result)}'

            logger.debug('Final result type: %s, content: %s', type(result), result[:100])

        except ServiceError as e:
            if e.status == 404:
                logger.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = f'<p>Error: Policy analysis failed (404) - likely this is a permission issue.  Make sure that the Profile API or Instance Principal user has \
<code>allow group PolicyUsers to use generative-ai in tenancy</code><br/>If you enable DEBUG and run again, you will see the entire message below. <br/>{e if self.verbose else ""}<p>'

            else:
                logger.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
        except Exception as e:
            logger.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
        finally:
            logger.info('Completed policy analysis in %s seconds', (time.perf_counter() - start_time))

        # Put on queue if it is there or return the result
        if queue:
            queue.put(result)
        else:
            return result

    async def test_ai_call(self, query: str, queue: queue.Queue, additional_instruction: str = ''):  # noqa: C901
        """Call OCI GenAI to test AI functionality. Put the results on a Queue that is provided"""
        logger.info(f'Given Prompt: {query}, Additional Instruction: {additional_instruction}')

        start_time = time.perf_counter()
        prompt = (
            f'{query} '
            f'{additional_instruction} '
            'return strict markdown format with no empty lines.'
            'markdown should include sections with headers (##) and unordered lists (* item).'
            'return a web link if relevant.'
        )
        chat_detail = self.create_chat_request(prompt=prompt)
        # Make the request
        try:
            response = self.genai_inference_client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logger.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            # Process result
            if isinstance(raw_content, list):
                logger.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logger.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logger.debug(f"Extracted 'text' attribute from first item: {result[:100]}")
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logger.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logger.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logger.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logger.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logger.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logger.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logger.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logger.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logger.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logger.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logger.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logger.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logger.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logger.error('Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000])
                result = f'Error: Extracted content is not a string: {type(result)}'

            logger.debug('Final result type: %s, content: %s', type(result), result[:100])

            logger.info(f'Completed test call in {time.perf_counter() - start_time:.2f} seconds')

        except ServiceError as e:
            if e.status == 404:
                logger.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = f'<p>Error: Policy analysis failed (404) - likely this is a permission issue.  Make sure that the Profile API or Instance Principal user has access to use generative-ai in tenancy.<br/>If you enable DEBUG and run again, you will see the entire message below. <br/>{e if logger.level == logger.debug else ""}<p>'
            else:
                logger.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
        except Exception as e:
            logger.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
        finally:
            logger.info('Completed policy analysis (error) in %s seconds', (time.perf_counter() - start_time))

        # Put on queue if it is there or return the result
        if queue:
            queue.put(result)
        else:
            return result
