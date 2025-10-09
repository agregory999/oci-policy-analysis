##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# core.py
# core.py
#
# @author: Andrew Gregory
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import json
import logging
import queue
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

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

from logic.logger import get_logger

# Global logger for this module
logger = get_logger(component='data_repo')

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

# Covers both policies and groups/dynamic groups
FILTER_KEY_MAP = {
    'policy_name': 'Policy Name',
    'policy_ocid': 'Policy OCID',
    'compartment_ocid': 'Compartment OCID',
    'policy_compartment': 'Policy Compartment',
    'statement_text': 'Statement Text',
    'valid': 'Valid',
    'invalid_reason': 'Invalid Reason',
    'subject_type': 'Subject Type',
    'subject': 'Subject',
    'verb': 'Verb',
    'resource': 'Resource',
    'permission': 'Permission',
    'location_type': 'Location Type',
    'location': 'Location',
    'conditions': 'Conditions',
    'comments': 'Comments',
    'creation_time': 'Creation Time',
    'parsed': 'Parsed',
    'effective_path': 'Effective Path',
    'dg_name': 'DG Name',
    'dg_matching_rule': 'Matching Rule',
    'group_name': 'Group Name',
    'group_domain': 'Domain Name',
}


# TypedDicts for MCP - these improve the code readability and help with type checking
class Group(TypedDict):
    domain: str | None
    name: str


class User(TypedDict):
    """Represents an OCI IAM user entry. Users need a domain and name to be unique.  Domain can be None for default domain."""

    user_name: str
    user_id: str
    display_name: str
    domain_name: str | None


class DynamicGroup(TypedDict):
    domain: str | None
    name: str


class PolicyFilters(TypedDict, total=False):
    # "total=False" = all keys optional
    verb: list[Literal['inspect', 'read', 'use', 'manage']]
    statement_text: list[str]  # Text snippet of the policy statement to filter on
    policy_name: list[str]  # Name of the policy
    policy_compartment: list[str]  # supports ROOTONLY
    resource: list[str]  # resource is a list of OCI resources that this policy statement applies to
    location: list[
        str
    ]  # location is a list of relative compartment paths or compartment id OCID.  Also can be "tenancy"
    effective_path: list[
        str
    ]  # Contains the compartment path that this policy statement applies to.  This is used to determine if a policy applies to a given compartment or any of its children.
    subject_type: list[str]  # e.g. group, dynamic-group, any-user, any-group, service
    subject: list[str]  # subject is a list of names or domain/name
    permission: list[str]  # permission is a list of actions such as START_INSTANCE
    comments: list[str]  # comments added to the end of the policy statement
    conditions: list[str]  # any or all clause of an OCI policy statement


class GroupFilters(TypedDict, total=False):
    domain: list[str | None]  # None represents no domain
    name: list[str]


class DynamicGroupFilters(TypedDict, total=False):
    domain: list[str | None]  # None represents no domain
    name: list[str]
    matching_rule: list[str]


# LOC_TENANCY_RE = re.compile(r'\btenancy\b', re.IGNORECASE)
# LOC_COMP_NAME_RE = re.compile(r'\b([a-zA-Z0-9:_\-\s]+)$', re.IGNORECASE)
# LOC_COMP_ID_RE = re.compile(r'\b(ocid1\.compartment\..+)$', re.IGNORECASE)


class PolicyStatement(TypedDict, total=False):
    Policy_Name: str
    Policy_OCID: str
    Compartment_OCID: str
    Policy_Compartment: str
    Statement_Text: str
    Valid: bool
    Subject_Type: str
    Subject: list[tuple[str | None, str]] | str
    Verb: str
    Resource: str
    Permission: str
    Location_Type: str
    Location: str
    Effective_Compartment: str
    Effective_Path: str
    Conditions: str
    Comments: str
    Creation_Time: str
    Parsed: bool


class PolicyCompartmentAnalysis:
    """This is the main data repository for Policy and Compartment data

    During initialization, the entire compartment hierarchy and policy tree is loaded into a central JSON dictionary.
    This central dictionary is then referenced by functions that filter and return a subset of information for display.
    Parsing, additional analysis, and import/export are made available by additional functions exposed.

    Attributes:
        compartments: A list of JSON dicts containing the compartment hierarchy
        regular_statements: A list of JSON dicts containing the individual regular policy statements within an OCI tenancy
        cross_tenancy_statements: A list of JSON dicts containing the individual cross-tenancy policy statements within an OCI tenancy
        defined_aliases: A list of JSON dicts containing the "define" statements within an OCI tenancy, used for cross-tenancy evaluation
        data_as_of: The timestamp that this data load was completed.
        tenancy_ocid: The OCID of the tenancy being analyzed here.
        identity_client: The OCI client that is initialized and used for all data loading purposes.
    """

    def __init__(self):
        self.compartments = []  # List of dicts: {id, name, parent_id, hierarchy_path, hierarchy_ocids}
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = []  # Store define statements as list of dict

        self.data_as_of = ''
        self.tenancy_ocid = None
        self.identity_client = None
        logger.info('Initialized PolicyCompartmentAnalysis')

    def initialize_client(
        self, use_instance_principal: bool, session: str, recursive: bool = True, profile: str = 'DEFAULT'
    ) -> bool:
        """Initializes the OCI client to be used for all data operations

        Client can be loaded using PROFILE or Instance Principal authentication methods

        Args:
            use_instance_principal: Whether to attempt Instance Principal signer-based authentication
            recursive: Whether to load tenancy data across all compartments, or simply the root (tenancy) compartment
            profile: The named OCI Profile to use - must be present on the file system in the standard OCI location of .oci/config

        Returns:
            A boolean indicating whether the client was created successfully.  False indicates that an unrecoverable issue occurred
            setting up the client.

        """
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.logging_search_client = LogSearchClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            elif session:
                logger.info('Attempt session auth')
                self.config = config.from_file(profile_name=session)
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
            logger.info(f'Set up Identity Client (Policy) for tenancy: {self.tenancy_ocid}')

            # Set Recursion
            self.recursive = recursive
            logger.debug(f'Set recursive to: {self.recursive}')

            # Get tenancy name
            self.tenancy_name = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid).data.name
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def _calculate_effective_compartments_for_statements(self):
        """
        Resolve effective compartment for all statements.  Loop through all statements and calculate
        """
        for st in self.regular_statements:
            logger.debug(f"-Statement: {st.get('Statement Text')}")
            # Case 1 - in tenancy
            if st.get('Location Type') == 'tenancy':
                st['Effective Compartment'] = self.tenancy_ocid
                st['Effective Path'] = self._name_path_from_ocid(self.tenancy_ocid)
                logger.debug(f"Effective (ten) path for {st.get('Statement Text')}: {st.get('Effective Path')}")
            # Case 2 - Compartment ID
            elif st.get('Location Type') == 'compartment id':
                st['Effective Compartment'] = st.get('Location')
                st['Effective Path'] = self._name_path_from_ocid(st.get('Location'))
                st['Parsing Notes'].append('Compartment ID used for location')
                logger.debug(f"Effective (id) path for {st.get('Statement Text')}: {st.get('Effective Path')}")
            # Case 3 - Compartment Name (with or without full path)
            # Note - if location refers to current compartment, we need to remove that from the path
            else:
                logger.debug(f"Need to calc eff path for {st.get('Statement Text')}")
                location = st.get('Location')
                parts = [p.strip() for p in location.split(':') if p.strip()]
                policy_path = self._name_path_from_ocid(st.get('Compartment OCID'))
                logger.debug(f'Policy Path: {policy_path} / Location parts: {parts}')

                # If the first element of the path is the same as the policy compartment name, remove it from cosideration
                eff_path = policy_path
                comp_name = self._comp_name_path_ocid(st.get('Compartment OCID'))
                logger.debug(f'Compartment name for compare: {comp_name}')
                # We need just the name of the compartment of the policy, get from
                if parts[0].casefold() == comp_name.casefold():
                    st['Parsing Notes'].append('Deleted compartment from effective location')
                    del parts[0]
                for p in parts:
                    eff_path += f'/{p}'
                logger.debug(f"Effective (loc) path for {st.get('Statement Text')}: {eff_path}")
                st['Effective Path'] = eff_path
                st['Effective Compartment'] = self.compartments_by_path.get(eff_path, {}).get('id')

    # --- helpers (as before) ---
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

        # Basic statement dict - will be augmented after parsing
        statement_dict = {
            'Policy Name': policy.name,
            'Policy OCID': policy.id,
            'Compartment OCID': comp_id,
            'Policy Compartment': comp_string,
            'Statement Text': statement,
            'Creation Time': str(policy.time_created),
        }

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
                    define_dict = {
                        'Policy Name': policy.name,
                        'Policy OCID': policy.id,
                        'Policy Description': policy.description,
                        'Creation Time': str(policy.time_created),
                        'Statement Text': statement,
                        'Defined Type': result.get('define_type'),
                        'Defined Name': result.get('principal'),
                        'OCID Alias': result.get('alias'),
                    }
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
                    statement_dict['Valid'] = True  # Currently for Validity
                    statement_dict['Subject Type'] = result.get('subjecttype')
                    statement_dict['Subject'] = result.get('subject') or ''
                    statement_dict['Verb'] = result.get('verb') or ''
                    statement_dict['Resource'] = result.get('resource') or ''
                    statement_dict['Permission'] = result.get('perm') or ''
                    statement_dict['Location Type'] = result.get('locationtype') or ''
                    statement_dict['Location'] = result.get('location') or ''
                    statement_dict['Conditions'] = result.get('condition') or ''
                    statement_dict['Comments'] = result.get('optional') or ''
                    statement_dict['Parsing Notes'] = []
                    statement_dict['Parsed'] = True  # Currently for parsed
                    # Additional Subject Parsing
                    if statement_dict['Subject Type'] in ['any-user', 'any-group']:
                        statement_dict['Subject'] = [(None, statement_dict['Subject Type'])]
                    else:
                        # subject_result = re.findall(SUBJECT_REGEX, statement_list[7], re.IGNORECASE)
                        # Try new subject parser
                        subject_result = self._parse_subjects(statement_dict['Subject'])
                        logger.debug(f'Subject parsed: {subject_result}')
                        # statement_list[7] = [(a[2] or "Default", a[4]) for a in subject_result]
                        if len(subject_result) > 1:
                            statement_dict['Parsing Notes'].append('Multiple subjects found')
                        statement_dict['Subject'] = subject_result

                    # Additional check for Location Validity
                    if statement_dict['Location Type'].casefold() == 'compartment id':
                        # Check and change validity accordingly
                        statement_dict['Valid'] = self._check_invalid_location(statement_dict['Location'])
                        logger.debug(f"Checked OCID {statement_dict['Location']} - Valid: {statement_dict['Valid']}")
                        if not statement_dict['Valid']:
                            statement_dict['Invalid Reason'] = 'Invalid Compartment OCID'

                    # Additional check for Verb validity
                    if statement_dict['Verb'] and statement_dict['Verb'].casefold() not in VALID_VERBS:
                        logger.warning(f"Invalid Verb found: {statement_dict['Verb']}")
                        statement_dict['Valid'] = False
                        statement_dict['Invalid Reason'] = 'Invalid Verb'

                    # Fake invalid (delete this)
                    if statement_dict['Resource'] == 'orm-jobs':
                        logger.warning(f"Fake Invalid Resource found: {statement_dict['Resource']}")
                        statement_dict['Valid'] = False
                        statement_dict['Invalid Reason'] = 'Fake Invalid Resource for testing'
                except Exception as e:
                    logger.warning(f'Failed to parse statement: {e}')

            else:
                logger.warning(f'No regex match for statement: |{statement}|')

            logging.debug(f'Parsed Statement as JSON: {statement_dict}')
            self.regular_statements.append(statement_dict)

            # Success or fail based on Parsed field
            return True if statement_dict.get('Parsed') else False

        # Catch All - should never get here
        logger.warning(f'Should not get here.  Statement not added to anything: {statement}')

        return False

    def load_compartment_and_policies_worker(self, compartment: Compartment):
        """Worker function to load compartment and policy data as JSON object in a thread"""
        try:
            start_time = time.perf_counter()
            # Load compartment data
            logger.debug(f'Processing compartment: {compartment.name} (OCID: {compartment.id})')
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
                logger.info(f'Looping policies for comp: {compartment.name} ({len(policies_response.data)})')
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
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = []
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

    # Filtering logic - return a list of policy statements matching given filter
    def filter_cross_tenancy_policy_statements(self, alias_filter: list[str]) -> list:
        # Iterate cross-tenant policies
        filtered = []
        for statement in self.cross_tenancy_statements:
            for alias_to_check in alias_filter:
                # Check each alias to see if in statement test
                statement_text = statement.get('Statement Text', '')
                if alias_to_check in statement_text:
                    logger.info(f'Adding statement (alias={alias_to_check}): {statement_text}')
                    filtered.append(statement)
        logger.info(f'Returning {len(filtered)} Cross-Tenancy Results')
        return filtered

    def filter_policy_statements_by_groups(self, groups_filter: list[Group]) -> list[PolicyStatement]:
        """
        Filter policy statements by group membership.

        Args:
            groups_filter (list[Group]): A list of group objects, each with:
                - domain (str | None): The group domain. If None, treated as "Default".
                - name (str): The group name.

        Behavior:
            - Only applies to statements where "Subject Type" == "group".
            - A statement's "Subject" field may contain one or more (domain, name) pairs.
            - A match occurs if any provided (domain, name) tuple matches
            any subject in the statement (case-insensitive).

        Returns:
            list[PolicyStatement]: Matching policy statements.
        """
        logger.info(f'Filter policies related to groups: {groups_filter}')
        filtered: list[PolicyStatement] = []

        for statement in self.regular_statements:
            if statement.get('Subject Type') != 'group':
                continue

            subjects = statement.get('Subject', [])
            if not isinstance(subjects, list):
                logger.warning(f"Unexpected Subject format in statement {statement.get('Policy Name')}: {subjects}")
                continue
            if not groups_filter:
                logger.debug('No groups provided for filtering, skipping statement.')
                continue
            for group in groups_filter:
                group_domain = group.get('domain') or 'Default'
                group_name = group.get('name')

                for subj_domain, subj_name in subjects:
                    logger.debug(
                        f'Comparing Group ({group_domain}/{group_name}) '
                        f'to Policy Subject ({subj_domain}/{subj_name})'
                    )
                    if (
                        subj_domain.casefold() == group_domain.casefold()
                        and subj_name.casefold() == group_name.casefold()
                    ):
                        filtered.append(statement)
                        logger.debug(
                            f"Adding statement for group {group_domain}/{group_name}: {statement.get('Policy Name')}"
                        )
                        break  # stop checking once matched

        logger.info(f'Returning {len(filtered)} statements for groups: {groups_filter}')
        return filtered

    def filter_policy_statements_by_dynamic_group_name(
        self, dynamic_groups: list[DynamicGroup]
    ) -> list[PolicyStatement]:
        """
        Filter policy statements by dynamic group membership.

        Args:
            dynamic_groups (list[dict]): A list of objects with keys:
                - domain (str | None): Domain name for the dynamic group.
                If None, treated as "Default".
                - name (str): Dynamic group name.
            Behavior:
                - Only applies to statements where "Subject Type" == "dynamic-group".
                - The "Subject" field may contain one or more (domain, name) pairs.
                - A match occurs if any provided (domain, name) matches any subject in
                the statement (case-insensitive).

        Returns:
            list[dict[str, str]]: Matching policy statements.
        """
        filtered: list[dict[str, str]] = []

        for statement in self.regular_statements:
            if statement.get('Subject Type') != 'dynamic-group':
                continue

            subjects = statement.get('Subject', [])
            if not isinstance(subjects, list):
                logger.warning(f"Unexpected Subject format in statement {statement.get('Policy Name')}: {subjects}")
                continue

            for dg in dynamic_groups:
                domain = dg.get('domain') or 'Default'
                name = dg.get('name')

                for subj_domain, subj_name in subjects:
                    logger.debug(f'Comparing DG ({domain}/{name}) to Policy Subject ({subj_domain}/{subj_name})')

                    if subj_domain.casefold() == domain.casefold() and subj_name.casefold() == name.casefold():
                        filtered.append(statement)
                        logger.debug(
                            f"Adding statement for dynamic group {domain}/{name}: {statement.get('Policy Name')}"
                        )
                        break  # stop checking once matched

        logger.info(f'Returning {len(filtered)} statements for dynamic groups: {dynamic_groups}')
        return filtered

    def filter_policy_statements_json(self, filters: PolicyFilters) -> list[PolicyStatement]:  # noqa: C901
        """
        Filter policy statements using JSON-based filters.

        Args:
            filters (dict[PolicyFilters]): A mapping of filter keys to one or more values.
                - OR: multiple values within a field act as logical OR.
                - AND: multiple fields are combined as logical AND.
                - Supported keys:
                    * policy_name          → matches "Policy Name"
                    * policy_ocid          → matches "Policy OCID"
                    * compartment_ocid     → matches "Compartment OCID"
                    * policy_compartment   → matches "Policy Compartment"
                    * statement_text       → matches "Statement Text"
                    * subject_type         → matches "Subject Type"
                    * subject              → matches "Subject"
                    * verb                 → must be one of: inspect, read, use, manage
                    * resource             → matches "Resource"
                    * permission           → matches "Permission"
                    * location_type        → matches "Location Type"
                    * location             → matches "Location"
                    * effective_path       → matches "Effective Path"
                    * effective_compartment→ matches "Effective Compartment"
                    * conditions           → matches "Conditions"
                    * comments             → matches "Comments"
                    * creation_time        → matches "Creation Time"
                    * parsed               → matches "Parsed"
                - Special cases:
                    * verb: values must be a subset of {inspect, read, use, manage}
                    * policy_compartment: supports "ROOTONLY" (restrict to tenancy root)

        Returns:
            list[PolicyStatement]: A list of policy statements that satisfy the filters.
        """
        results = []

        for stmt in self.regular_statements:
            match = True

            for key, values in filters.items():
                values = [v.lower() for v in values]

                # Compartment special: ROOTONLY
                if key == 'policy_compartment' and 'rootonly' in values:
                    if stmt.get('Compartment OCID') != self.tenancy_ocid:
                        logger.debug(f"Rejecting {stmt.get('Policy Name')} due to ROOTONLY restriction")
                        match = False
                        break

                # Verb enum
                elif key == 'verb':
                    invalid = set(values) - VALID_VERBS
                    if invalid:
                        logger.debug(f'Invalid verbs in filter: {invalid}')
                    field_value = str(stmt.get('Verb', '')).lower()
                    if field_value not in values:
                        logger.debug(f"Rejecting {stmt.get('Policy Name')} due to verb mismatch: {field_value}")
                        match = False
                        break

                # Effective path search
                elif key == 'effective_path':
                    filter_eff_value = values[0]  # only one supported
                    statement_eff_value = str(stmt.get('Effective Path', '')).lower()
                    logger.debug(f'Filtering on filt/st {filter_eff_value} vs {statement_eff_value}')
                    # Logic here - if the effective path given contains the effective path of the statement,
                    # then it is a match.  This allows searching for all policies effective in a given compartment and its children.
                    if not (filter_eff_value.startswith(statement_eff_value)):
                        logger.debug(
                            f"Rejecting {stmt.get('Policy Name')} due to effective_path mismatch: "
                            f"{statement_eff_value} not in {filter_eff_value}"
                        )
                        match = False
                        break
                # Default lookup using column map
                else:
                    column = FILTER_KEY_MAP.get(key)
                    logger.debug(f'Filtering on {key} mapped to column {column} with values {values}')
                    if not column:
                        logger.warning(f'Unknown filter key: {key}')
                        continue
                    field_value = str(stmt.get(column, '')).lower()
                    if not any(val in field_value for val in values):
                        logger.debug(f"Rejecting {stmt.get('Policy Name')} due to {key} mismatch")
                        match = False
                        break

            if match:
                results.append(stmt)

        logger.info(f'Filter applied. {len(results)} matched out of {len(self.regular_statements)}')
        return results

    # Original - non-MCP version of filter_policy_statements
    def filter_policy_statements(
        self,
        subj_filter=None,
        verb_filter=None,
        resource_filter=None,
        location_filter=None,
        hierarchy_filter=None,
        condition_filter=None,
        text_filter=None,
        policy_filter=None,
    ) -> list:
        """Given the filters from the UI, return the list of matching policy statements.  Process the | as logical OR.

        There are 8 filters that can be applied.  Each filter is treated as its own and then they are applied at the
        end using logical AND.  If more than 1 filter is used, both must be true for the policy statement to be
        returned.

        Args:
            subj_filter: A delimited list of subjects that could appear in the policy statement. Supports | for OR
            verb_filter: A delimited list of verbs that could appear in the policy statement. Supports | for OR
            resource_filter: A delimited list of resources that could appear in the policy statement. Supports | for OR
            location_filter: A delimited list of locations that could appear in the policy statement. Supports | for OR
            hierarchy_filter: A delimited list of heierachy locations that could appear in the policy statement. Supports | for OR
            condition_filter: A delimited list of conditions that could appear in the policy statement. Supports | for OR
            text_filter: A delimited list of text bits that could appear in the policy statement. Supports | for OR
            policy_filter: A delimited list of policy names that could appear in the policy statement. Supports | for OR

        Returns:
            a list of JSON dicts representing policy statemewnts matching the criteria
        """
        filtered = []
        subject_terms = [term.strip().lower() for term in subj_filter.split('|') if term.strip()] if subj_filter else []
        verb_terms = [term.strip().lower() for term in verb_filter.split('|') if term.strip()] if verb_filter else []
        resource_terms = (
            [term.strip().lower() for term in resource_filter.split('|') if term.strip()] if resource_filter else []
        )
        location_terms = (
            [term.strip().lower() for term in location_filter.split('|') if term.strip()] if location_filter else []
        )
        hierarchy_terms = (
            [term.strip().lower() for term in hierarchy_filter.split('|') if term.strip()] if hierarchy_filter else []
        )
        condition_terms = (
            [term.strip().lower() for term in condition_filter.split('|') if term.strip()] if condition_filter else []
        )
        text_terms = [term.strip().lower() for term in text_filter.split('|') if term.strip()] if text_filter else []
        policy_terms = (
            [term.strip().lower() for term in policy_filter.split('|') if term.strip()] if policy_filter else []
        )
        logger.debug(
            f'Search Terms: Subject: {subject_terms} Location: {location_terms} Hierarchy: {hierarchy_terms}, Condition {condition_terms}'
        )

        # Iterate all policy statements and return a new list
        for st in self.regular_statements:
            matches_subject = not subject_terms or any(term in str(st.get('Subject')).lower() for term in subject_terms)
            matches_verb = not verb_terms or any(term in str(st.get('Verb')).lower() for term in verb_terms)
            matches_resource = not resource_terms or any(
                term in str(st.get('Resource')).lower() for term in resource_terms
            )
            matches_location = (
                not location_terms
                or any(term in str(st.get('Location')).lower() for term in location_terms)
                or (st.get('Location Type') == 'tenancy' and location_terms[0] == 'tenancy')
            )
            matches_hierarchy = (
                not hierarchy_terms
                or any(term in str(st.get('Policy Compartment')).lower() for term in hierarchy_terms)
                or (
                    st.get('Compartment OCID') == self.tenancy_ocid and hierarchy_terms[0] == 'rootonly'
                )  # Uses Root Level boolean
            )
            matches_condition = not condition_terms or any(
                term in str(st.get('Conditions')).lower().replace(' ', '') for term in condition_terms
            )
            matches_text = not text_terms or any(term in str(st.get('Statement Text')).lower() for term in text_terms)
            matches_policy = not policy_terms or any(
                term in str(st.get('Policy Name')).lower() for term in policy_terms
            )

            # All matches must be satisfied - None for a particular filter does that as well.
            if (
                matches_subject
                and matches_verb
                and matches_resource
                and matches_location
                and matches_hierarchy
                and matches_condition
                and matches_text
                and matches_policy
            ):
                logger.debug(f'Adding Statement {st.get("Statement Text")} due to filter match')
                filtered.append(st)

        logger.info(f'Filtered to {len(filtered)} policy statements')
        return filtered

    # Perform a comparison (left vs right)
    # TODO fix this to compare any 2 full JSON
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


class IdentityDomainsAnalysis:
    """This is the main data repository for Identity Domains data

    During initialization, all Identity Domain data is loaded into a central JSON dictionary.
    This central dictionary is then referenced by functions that filter and return a subset of information for display.
    Parsing, additional analysis, and import/export are made available by additional functions exposed.

    Attributes:
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
        self.tenancy_ocid = None
        self.identity_client = None
        self.signer = None
        self.config = None
        self.use_instance_principal = False
        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users = []
        self.domain_clients = {}
        self.policies = []
        self.data_as_of = ''

        logger.info('Initialized IdentityDomainsAnalysis')

    def initialize_client(self, use_instance_principal: bool, profile: str = 'DEFAULT') -> bool:
        """Initializes the OCI client to be used for all data operations

        Client can be loaded using PROFILE or Instance Principal authentication methods

        Args:
            use_instance_principal: Whether to attempt Instance Principal signer-based authentication
            recursive: Whether to load tenancy data across all compartments, or simply the root (tenancy) compartment
            profile: The named OCI Profile to use - must be present on the file system in the standard OCI location of .oci/config

        Returns:
            A boolean indicating whether the client was created successfully.  False indicates that an unrecoverable issue occurred
            setting up the client.

        """
        try:
            self.use_instance_principal = use_instance_principal
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            else:
                logger.debug(f'Using Profile Authentication: {profile}')
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.tenancy_ocid = self.config['tenancy']
            # Get tenancy name
            self.tenancy_name = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid).data.name
            logger.info(f'Set up Identity Client (Domain) for tenancy: {self.tenancy_ocid}')
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def _parse_dynamic_group(self, domain_name: str, dg: DynamicResourceGroup) -> dict:
        """Extract the contents of the DG into a dict"""

        dg_dict = {
            'Domain': domain_name,
            'DG Name': dg.display_name,
            'DG Description': dg.description,
            'Matching Rule': dg.matching_rule,
            'In Use': True,  # Placeholder until analysis is run
            'DG OCID': dg.ocid,
            'Creation Time': str(dg.meta.created),
        }
        return dg_dict
        # TODO: Add back invalid OCID analysis

    def run_dg_in_use_analysis(self, policy_statements: list):
        """Analyzes Dynamic Group data for unused Dynamic Groups

        Given a list of policy statements, iterates to see if each dynamic group is used.  If not, it
        is marked with "In Use" = False, for later display

        Args:
            policy_statements: A list of JSON dicts containing a policy statement each
        """

        # Build a list of all subjects as list(tuple(domain,name))
        all_subjects: list[tuple] = []
        for st in policy_statements:
            subject_list = st.get('Subject') or []
            subject_type = st.get('Subject Type')
            logger.debug(f'SubType: {subject_type} Subject: {subject_list}')
            if subject_type == 'dynamic-group':
                logger.info(f'Add: {subject_type} Subject: {subject_list}')
                all_subjects.extend(subject_list)

        logger.info(f'all subjects: {len(all_subjects)}')
        # all_subjects = list(set(all_subjects))
        # logger.info(f"all subjects: {len(all_subjects)}")

        # Iterate all DGs, look at their Domain and Name, then look through each statement
        unused_dynamic_groups = 0
        for dg in self.dynamic_groups:
            dg_domain = dg.get('Domain') or 'default'
            dg_name = dg.get('DG Name')
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
                dg['In Use'] = False
                unused_dynamic_groups += 1

        logger.info(f'Found {unused_dynamic_groups} unused dynamic groups')

    def filter_dynamic_groups(self, domain_filter=None, name_filter=None, type_filter=None, ocid_filter=None) -> list:
        """Filters Dynamic Groups by Domain, Name, Type, or OCID

        Returns a list of filtered Dynamic Groups.

        Args:
            domain_filter: A string containing domains to filter.  Can be delimited by | to indicate logical OR
            name_filter: A string containing dynamic group to filter.  Can be delimited by | to indicate logical OR
            type_filter: A string containing types to filter.  Can be delimited by | to indicate logical OR
            ocid_filter: A string containing OCIDs to filter.  Can be delimited by | to indicate logical OR

        Returns:
            A list of filtered dynamic groups, which are the original JSON format per dynamic group returned
        """
        filtered = []

        domain_terms = [dom.strip().lower() for dom in domain_filter.split('|') if dom.strip()] if domain_filter else []
        name_terms = [term.strip().lower() for term in name_filter.split('|') if term.strip()] if name_filter else []
        type_terms = [ty.strip().lower() for ty in type_filter.split('|') if ty.strip()] if type_filter else []
        ocid_terms = [oc.strip().lower() for oc in ocid_filter.split('|') if oc.strip()] if ocid_filter else []
        logger.debug(f'Filtering DGs based on Domain: {domain_filter} and Name: {name_filter}')
        for dg in self.dynamic_groups:
            # str(st.get('subject')).lower()
            matches_domain = not domain_terms or any(term in str(dg.get('Domain')).lower() for term in domain_terms)
            matches_name = not name_terms or any(term in str(dg.get('DG Name')).lower() for term in name_terms)
            matches_type = not type_terms or any(term in str(dg.get('Matching Rule')).lower() for term in type_terms)
            matches_ocid = not ocid_terms or any(term in str(dg.get('DG OCID')).lower() for term in ocid_terms)
            if matches_name and matches_domain and matches_type and matches_ocid:
                logger.debug(f'Adding DG {dg.get("Domain")}/{dg.get("DG Name")} due to filter match')
                filtered.append(dg)

        logger.info(f'Filtered to {len(filtered)} dynamic groups')
        return filtered

    def get_users_for_group(self, group: Group) -> list[User]:
        """
        Return all users that belong to the specified group.

        Args:
            group (Group): A dictionary with keys:
                - 'domain': str | None
                - 'name': str

        Returns:
            list[User]: All matching user entries with 'user_name', 'user_id', and 'domain_name'.
        """
        group_domain = group.get('domain') or 'default'
        group_name = group['name']
        logger.info(f'Looking for users in group: {group_domain}/{group_name}')
        logger.debug(f'Number of groups: {len(self.groups)}  Number of users: {len(self.users)}')

        group_ocids = [
            g['Group OCID']
            for g in self.groups
            if g.get('Group Name', '').casefold() == group_name.casefold()
            and g.get('Domain Name', '').casefold() == group_domain.casefold()
        ]

        if not group_ocids:
            logger.warning(f'No group found for {group_domain}/{group_name}')
            return []

        group_ocid = group_ocids[0]

        # Step 2: Find users who are members of that group
        matched_users: list[User] = []
        for user in self.users:
            user_groups = user.get('User Groups', [])
            if group_ocid in user_groups:
                matched_users.append(
                    {
                        'user_name': user.get('Username'),
                        'user_id': user.get('User ID'),
                        'domain_name': user.get('Domain Name'),
                        'display_name': user.get('Display Name'),
                    }
                )

        logger.info(f'Found {len(matched_users)} users for group {group_domain}/{group_name}')
        return matched_users

    def filter_groups(self, name_filter=None) -> list[Group]:
        filtered = []

        name_terms = [term.strip().lower() for term in name_filter.split('|') if term.strip()] if name_filter else []
        logger.debug(f'Filtering Groups based on Name: {name_filter}')
        for g in self.groups:
            matches_name = not name_terms or any(term in str(g.get('Group Name')).lower() for term in name_terms)
            if matches_name:
                logger.debug(f'Adding Group: {g.get("Group Name")} due to filter match')
                filtered.append(g)

        logger.info(f'Filtered to {len(filtered)} groups')
        return filtered

    def filter_users(self, name_filter=None) -> list:
        filtered = []

        name_terms = [term.strip().lower() for term in name_filter.split('|') if term.strip()] if name_filter else []
        logger.debug(f'Filtering Users based on Name: {name_filter}')
        for u in self.users:
            matches_name = not name_terms or any(term in str(u.get('Username')).lower() for term in name_terms)
            if matches_name:
                logger.debug(f'Adding Group: {u.get("Username")} due to filter match')
                filtered.append(u)

        logger.info(f'Filtered to {len(filtered)} users')
        return filtered

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
                            logging.debug(f'Group: {g}')

                            # Set the group into the bigger picture JSON
                            self.groups.append(
                                {
                                    'Domain OCID': domain.id,
                                    'Domain Name': domain.display_name,
                                    'Group ID': g.id,
                                    'Group OCID': g.ocid,
                                    'Group Name': g.display_name,
                                }
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

                            email = ''
                            for em in u.emails:
                                if em.primary:
                                    email = em.value
                                    break
                            # Set the user into the bigger picture JSON
                            self.users.append(
                                {
                                    'Domain Name': domain.display_name,
                                    'User ID': u.id,
                                    'User OCID': u.ocid,
                                    'Username': u.user_name,
                                    'Display Name': u.display_name,
                                    'Primary Email': email,
                                    'User Groups': group_list,
                                }
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
            raise

    def get_groups_for_user(self, user: User) -> list:
        """Return the list of all Groups that a user is a member of

        Args:


        Returns:
            A list of Groups
        """
        groups_for_user: list = []
        logger.info(f'User to filter: {user}')
        logger.debug(f'Users: {self.users}')

        # Iterate through users to find our user
        for u in self.users:
            # Match the tuple
            if (
                u.get('Username', '').casefold() == user.get('user_name').casefold()
                and u.get('Domain Name', 'default').casefold() == user.get('domain_name', 'default').casefold()
            ):
                logger.info(f"User found. Groups: {u.get('User Groups')}")

                for user_group_ocid in u.get('User Groups'):
                    # Find the Group OCID in the groups and append
                    for g in self.groups:
                        if g.get('Group OCID') == user_group_ocid:
                            # Now append as tuple
                            groups_for_user.append({'domain': g.get('Domain Name'), 'name': g.get('Group Name')})
                            logger.info(f"Adding Group {g.get('Domain Name')}/{g.get('Group Name')} ")
        return groups_for_user

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

        start_time = datetime.now()
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

            logger.info('Completed test call in %s seconds', (datetime.now() - start_time).total_seconds())

        except ServiceError as e:
            if e.status == 404:
                logger.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = f'<p>Error: Policy analysis failed (404) - likely this is a permission issue.  Make sure that the Profile API or Instance Principal user has access to use generative-ai in tenancy.<br/>If you enable DEBUG and run again, you will see the entire message below. <br/>{e if logger.level == logger.debug else ""}<p>'

            else:
                logger.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
        except Exception as e:
            logger.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )

        # Put on queue if it is there or return the result
        if queue:
            queue.put(result)
        else:
            return result
