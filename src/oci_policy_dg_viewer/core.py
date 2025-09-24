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
import argparse
import datetime
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Third-party imports
# import oci
# import oci
from deepdiff import DeepDiff, parse_path
from oci import config, pagination
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.identity import IdentityClient
from oci.identity.models import Compartment, Domain, Policy
from oci.identity_domains import IdentityDomainsClient
from oci.identity_domains.models import DynamicResourceGroup
from oci.loggingsearch import LogSearchClient
from oci.loggingsearch.models import SearchLogsDetails, SearchResult

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

OCID_REGEX = r'ocid1\.\w+\.\w+\.\w*\.\w+'

CROSS_TENANCY_DEFINE_REGEX = r"""
    (?P<statement_type>define)\s+  # Capture statement type
    (?P<define_type>compartment|group|dynamic-group|tenancy)\s+  # Define type
    (?P<principal>\S+)\s+  # Principal (simple name)
    (?:as\s+)(?P<alias>\S+)  # Alias, capturing only the value without 'as '
"""

define_regex = re.compile(CROSS_TENANCY_DEFINE_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)

CROSS_TENANCY_ADMIT_REGEX = r"""
    (?P<statement_type>admit)\s+  # Capture statement type
    (?P<principal>any-user|group\s+(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+)(?:\s*,\s*(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+))*)?\s+  # Principal (any-user or comma-separated groups: domain/group, 'domain'/'group', simple)
    (?:of\s+)(?P<of_tenancy>tenancy\s+\S+)\s+  # 'of tenancy' clause, excluding 'of '
    to\s+(?:(?P<permission>{[^}]+})|(?P<action>{[^}]+}|\S+)\s+(?P<resource>\S+))?\s+  # Permission or action + resource, both optional
    in\s+(?P<location>compartment\s+[\w:]+|tenancy\s+\S+)  # Location (compartment or tenancy)
    (?P<where_clause>\s+where\s+(?:all\s+)?{[^}]+})?  # Optional where clause
    (?P<comment>\s*//\s*[^\n]*)?  # Optional comment
"""

admit_regex = re.compile(CROSS_TENANCY_ADMIT_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)


CROSS_TENANCY_ENDORSE_REGEX = r"""
    (?P<statement_type>endorse)\s+  # Capture statement type
    (?P<principal>any-user|group\s+(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+)(?:\s*,\s*(?:(?:'[^']+'|[\w\-:]+)(?:\s*/\s*(?:'[^']+'|[\w\-:]+))|[\w\-:]+))*\s+|dynamic-group\s+\S+\s+)  # Principal (any-user, groups: domain/group, 'domain'/'group', simple, or dynamic-group)
    to\s+(?:(?P<permission>{[^}]+})|(?P<action>{[^}]+}|\S+|associate\s+\S+\s+with\s+\S+\s+in\s+(?:compartment\s+[\w:]+|tenancy\s+\S+))\s+(?P<resource>\S+))?\s+  # Permission or action + resource, both optional
    in\s+(?P<location>compartment\s+[\w:]+|tenancy\s+\S+)  # Location (compartment or tenancy)
    (?P<of_tenancy_clause>(?:\s+of\s+tenancy\s+\S+)?)  # Optional 'of tenancy' clause
    (?P<where_clause>\s+where\s+(?:all\s+)?{[^}]+})?  # Optional where clause
    (?P<comment>\s*//\s*[^\n]*)?  # Optional comment
"""
endorse_regex = re.compile(CROSS_TENANCY_ENDORSE_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE)

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'
CACHE_DATE = datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d-%H-%M-%S-%Z')

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
logger = logging.getLogger('data-core')


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

    def __init__(self, verbose: bool):
        # self.logger = logging.getLogger('oci-policy-compartment-analysis')
        if verbose:
            logger.setLevel(logging.DEBUG)
        self.compartments = []  # List of dicts: {id, name, parent_id, hierarchy_path, hierarchy_ocids}
        self.regular_statements = []
        self.cross_tenancy_statements = []
        self.defined_aliases = []  # Store define statements as list of dict

        self.data_as_of = ''
        self.tenancy_ocid = None
        self.identity_client = None
        logger.info('Initialized PolicyCompartmentAnalysis')

    def initialize_client(self, use_instance_principal: bool, recursive: bool = True, profile: str = 'DEFAULT') -> bool:
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
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def get_compartment_path(self, compartment: Compartment, level: int, comp_string: str) -> tuple[str, list[str]]:
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
            parent_path, parent_ocids = self.get_compartment_path(
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
            logger.warning(f'Compartment OCID {compartment_ocid} not valid: {e}')
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
        comp_string = comp['hierarchy_path'] if comp else 'ROOT'

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

                    # [result.get('Defined Name')] = (result.get('Defined Type'), result.get('OCID Alias'))
                    return True
            except Exception as e:
                logger.warning(f'Failed to parse define: {e}')
                return False

        # Admit/endorse case (not parsing at the moment)
        elif comp_id == self.tenancy_ocid and (statement.startswith('admit') or statement.startswith('endorse')):
            # TODO: parse these properly - for now, just store them
            statement_dict = {
                'Policy Name': policy.name,
                'Policy OCID': policy.id,
                'Statement Text': statement,
                'Creation Time': str(policy.time_created),
            }
            self.cross_tenancy_statements.append(statement_dict)
            return True
            # TODO: try corss-tenancy parsing again

        # Regular Statements are everything else
        else:
            # Regular Statements
            logger.debug(f'Hierarchy string: {comp_string}')

            # Basic Details - not parsed yet
            statement_list = [
                policy.name,
                policy.id,
                comp_id,
                comp_string,
                statement,
                True,  # Currently for Validity
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                str(policy.time_created),
                False,  # Currently for parsed
            ]

            # Process Results of regex
            match_result = policy_regex.match(statement)
            if match_result and match_result.groupdict():
                result = match_result.groupdict()
                logger.debug(f"Subject parsed 1: {result.get('subject')} ||| Statement: {statement}")
                try:
                    # Re-define Statement List
                    statement_list = [
                        policy.name,
                        policy.id,
                        comp_id,
                        comp_string,
                        statement,
                        True,  # Currently for Validity
                        result.get('subjecttype'),
                        result.get('subject') or '',
                        result.get('verb') or '',
                        result.get('resource') or '',
                        result.get('perm') or '',
                        result.get('locationtype') or '',
                        result.get('location') or '',
                        result.get('condition') or '',
                        result.get('optional') or '',
                        str(policy.time_created),
                        True,  # Currently for parsed
                    ]

                    # Additional Subject Parsing
                    if statement_list[6] in ['any-user', 'any-group']:
                        statement_list[7] = [(None, statement_list[6])]
                    else:
                        # subject_result = re.findall(SUBJECT_REGEX, statement_list[7], re.IGNORECASE)
                        # Try new subject parser
                        subject_result = self._parse_subjects(statement_list[7])
                        logger.debug(f'Subject parsed: {subject_result}')
                        # statement_list[7] = [(a[2] or "Default", a[4]) for a in subject_result]
                        statement_list[7] = subject_result

                    # Additional check for Location Validity
                    if statement_list[11].casefold() == 'compartment id':
                        # Check and change validity accordingly
                        statement_list[5] = self._check_invalid_location(statement_list[12])
                        logger.debug(f'Checked OCID {statement_list[12]} - Valid: {statement_list[5]}')

                except Exception as e:
                    logger.warning(f'Failed to parse statement: {e}')

            else:
                logger.warning(f'No regex match for statement: |{statement}|')

            # Create the dict - even if not parsed it will still appear
            statement_dict = {
                'Policy Name': statement_list[0],
                'Policy OCID': statement_list[1],
                'Compartment OCID': statement_list[2],
                'Policy Compartment': statement_list[3],
                'Statement Text': statement_list[4],
                'Valid': statement_list[5],
                'Subject Type': statement_list[6],
                'Subject': statement_list[7],  # This will be a list of tuples
                'Verb': statement_list[8],
                'Resource': statement_list[9],
                'Permission': statement_list[10],
                'Location Type': statement_list[11],
                'Location': statement_list[12],
                'Conditions': statement_list[13],
                'Comments': statement_list[14],
                'Creation Time': statement_list[15],
                'Parsed': statement_list[16],
            }

            # For Location, use compartment hierarchy and relative
            # Store regular statements
            # self.regular_statements.append(statement_list)
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
            # Load compartment data
            start_time = time.perf_counter()
            logger.debug(f'Processing compartment: {compartment.name} (OCID: {compartment.id})')
            path, ocids = self.get_compartment_path(compartment, 0, '')
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
        start_time = time.perf_counter()
        try:
            root_comp_response = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid)
            if root_comp_response.data is None:
                logger.error(f'Failed to get root compartment: {self.tenancy_ocid}')
                return False
            root_comp = root_comp_response.data
            comp_list = [root_comp]
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

            # Catch the load time for compartments
            comp_load_time = time.perf_counter()

            if self.recursive:
                # Use a thread pool
                with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='thread') as executor:
                    executor.map(self.load_compartment_and_policies_worker, comp_list)
            else:
                # Call the worker on its own with just the root compartment
                self.load_compartment_and_policies_worker(compartment=root_comp)

            # Keep track of the time of this completed data load
            self.data_as_of = str(datetime.datetime.now())
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

    # def get_hierarchy_ocids(self, compartment_id: str) -> list[str]:
    #     comp = self.get_compartment_by_id(compartment_id)
    #     return comp['hierarchy_ocids'] if comp else []

    # Filtering logic - return a list of policy statements matching given filter
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

    def filter_policy_statements_by_groups(self, groups_filter: list[tuple]) -> list:
        """Filter cached groups by list of (domain, name) tuples.  Returns"""
        logger.debug(f'Looking for all policies related to groups: {groups_filter}')
        groups_filter = list(set(groups_filter))
        logger.debug(f'De-duped groups: {groups_filter}')
        filtered = []
        for statement in self.regular_statements:
            if statement.get('Subject Type') == 'group':
                # Iterate provided dynamic groups
                for group_domain, group_name in groups_filter:
                    # Compare domain and name
                    if group_domain is None:
                        group_domain = 'Default'
                    # Iterate Policy statement subjects
                    for subj_domain, subj_name in statement.get('Subject'):
                        logging.debug(
                            f'Comparing Group {type(group_domain)}:{repr(group_domain)} / {type(group_name)}:{repr(group_name)} to Policy Subject {type(subj_domain)}:{repr(subj_domain)} / {type(subj_name)}:{repr(subj_name)}'
                        )
                        # Exact match on both domain and name required
                        if (subj_domain.casefold() == group_domain.casefold()) and (
                            group_name.casefold() == subj_name.casefold()
                        ):
                            filtered.append(statement)
                            logger.debug(f'Adding statement for group: {group_domain}/{group_name}: {statement}')
                        else:
                            logging.debug(
                                f'Not a match for group {group_domain}/{group_name}: Subject {subj_domain}/{subj_name}'
                            )
                            logger.debug(f'Not a match for group {group_domain}/{group_name}: {statement}')
        logger.info(f'Returning {len(filtered)} statements for groups: {groups_filter}')
        return filtered

    def filter_policy_statements_by_dynamic_group_name(self, dynamic_groups: list[tuple]) -> list:
        """Filter cached dynamic groups by list of (domain, name) tuples.  Returns"""
        filtered = []
        for statement in self.regular_statements:
            if statement.get('Subject Type') == 'dynamic-group':
                # Iterate provided dynamic groups
                for dg_domain, dg_name in dynamic_groups:
                    # Compare domain and name
                    if dg_domain is None:
                        dg_domain = 'Default'
                    # Iterate Policy statement subjects
                    for subj_domain, subj_name in statement.get('Subject'):
                        logger.debug(
                            f'Comparing DG {type(dg_domain)}:{repr(dg_domain)} / {type(dg_name)}:{repr(dg_name)} to Policy Subject {type(subj_domain)}:{repr(subj_domain)} / {type(subj_name)}:{repr(subj_name)}'
                        )
                        # Exact match on both domain and name required
                        if (subj_domain.casefold() == dg_domain.casefold()) and (
                            dg_name.casefold() == subj_name.casefold()
                        ):
                            filtered.append(statement)
                            logger.info(f'Adding statement for dynamic group: {dg_domain}/{dg_name}: {statement}')
                        else:
                            logger.debug(f'Not a match for dynamic group {dg_domain}/{dg_name}: {statement}')
        logger.info(f'Returning {len(filtered)} statements for dynamic groups: {dynamic_groups}')
        return filtered

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

    def __init__(self, verbose: bool):
        self.logger = logging.getLogger('oci-identity-domins-analysis')
        if verbose:
            logger.setLevel(logging.DEBUG)
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
            logger.info(f'Set up Identity Client for tenancy: {self.tenancy_ocid}')
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

    def load_all_dynamic_groups(self) -> bool:
        """Load all of the dynamic groups across all Identity Domains"""

        self.dynamic_groups = []
        self.identity_domains = []
        self.groups = []
        self.users = []
        # We need to go through all domains
        try:
            domains_response = self.identity_client.list_domains(compartment_id=self.tenancy_ocid)
            if domains_response and domains_response.data:
                for domain in domains_response.data:
                    logger.debug(f'Domain {domain.display_name}, OCID {domain.id}')
                    if self.use_instance_principal:
                        domain_client = IdentityDomainsClient(
                            config={}, signer=self.signer, service_endpoint=domain.url
                        )
                    else:
                        domain_client = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
                    self.domain_clients[domain.id] = domain_client

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
                    logger.info(f'Loaded {len(self.dynamic_groups)} dynamic groups')
            self.data_as_of = str(datetime.datetime.now())
            return True
        except ServiceError as se:
            logger.error(f'Failed to load dynamic groups: {se}')
            return False

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
                logger.info(f'Compare {dg_domain} = {subj_domain} and {dg_name} = {subj_name}')
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

    def filter_groups(self, name_filter=None) -> list:
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
            matches_name = not name_terms or any(term in str(u.get('User Name')).lower() for term in name_terms)
            if matches_name:
                logger.debug(f'Adding Group: {u.get("User Name")} due to filter match')
                filtered.append(u)

        logger.info(f'Filtered to {len(filtered)} users')
        return filtered

    def load_domains_groups_users(self) -> bool:  # noqa: C901
        """Loads everything into the cetntral JSON

        Identity Domains are loaded via the Identity Client.
        For each Identity Domain, load the Dynamic Groups, Groups, and Users

        Args:
            none

        Returns:
            A boolean indicating success of the data load.  False indicates there was some failure in loading data,
            so it may be incomplete.
        """
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
                            # Set the user into the bigger picture JSON
                            self.users.append(
                                {
                                    'Domain Name': domain.display_name,
                                    'User ID': u.id,
                                    'User OCID': u.ocid,
                                    'User Name': u.display_name,
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

                except Exception as e:
                    logger.error(f'Failed to load groups/users for domain {domain.id}: {e}')
                    raise
            logger.info(f'Loaded {len(self.groups)} groups and {len(self.users)} users across all domains')
            return True
        except Exception as e:
            logger.error(f'Failed to load identity domains: {e}')
            # return False
            raise

    def get_groups_for_user(self, user: str) -> list:
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
            if u.get('User Name') == user[1] and u.get('Domain Name') == user[0]:
                logger.info(f"User found. Groups: {u.get('User Groups')}")

                for user_group_ocid in u.get('User Groups'):
                    # Find the Group OCID in the groups and append
                    for g in self.groups:
                        if g.get('Group OCID') == user_group_ocid:
                            # Now append as tuple
                            groups_for_user.append((g.get('Domain Name'), g.get('Group Name')))
                            logger.info(f"Adding Group {g.get('Domain Name')}/{g.get('Group Name')} ")
        return groups_for_user

    # def get_domain_client(self, domain_id: str) -> IdentityDomainsClient:
    #     return self.domain_clients.get(domain_id)  # type: ignore

    def _get_domains(self) -> list:
        return [{'id': d.id, 'display_name': d.display_name, 'url': d.url} for d in self.identity_domains]

    # def get_domain_name_by_id(self, domain_id: str) -> str:
    #     for dom in self.identity_domains:
    #         if dom.id == domain_id:
    #             return dom.display_name
    #     return 'Unk'

    # def get_users_by_domain(self, domain_id: str) -> list:
    #     return [u for u in self.users if u['domain_id'] == domain_id]


# Utility functions for loading and saving cache, using combined caching strategy
def save_combined_cache(
    policy_analysis: PolicyCompartmentAnalysis, domains_analysis: IdentityDomainsAnalysis, export_file=None
) -> str:
    """Save combined cache for policies and dynamic groups. Returns file name if you care"""

    # Create the file as JSON first, collecting all details
    combined_data = {
        'tenancy_name': policy_analysis.tenancy_name,
        'tenancy_ocid': policy_analysis.tenancy_ocid,
        'policies': policy_analysis.regular_statements,
        'dynamic_groups': domains_analysis.dynamic_groups,
        'defined_aliases': policy_analysis.defined_aliases,
        'cross_tenancy_policies': policy_analysis.cross_tenancy_statements,
        'compartments': policy_analysis.compartments,
        'identity_domains': domains_analysis._get_domains(),
        'groups': domains_analysis.groups,
        'users': domains_analysis.users,
        'data_as_of': policy_analysis.data_as_of,
    }

    if export_file:
        with open(export_file.name, 'w', newline='', encoding='utf-8') as filehandle:
            json.dump(combined_data, filehandle, ensure_ascii=False)
        logger.info(f'Exported combined cache to: {export_file.name}')
        return str(export_file.name)

    else:
        # Just write to cache as normal
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        combined_cache_file = CACHE_DIR / f'combined_cache_{policy_analysis.tenancy_name}_{CACHE_DATE}.json'

        with open(combined_cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(combined_data, filehandle, ensure_ascii=False)
        logger.info(f'Saved combined cache to: {combined_cache_file}')

    # Update cache entries
    entry = {'tenancy_name': policy_analysis.tenancy_name, 'cache_date': CACHE_DATE}
    with open(CACHE_DIR / 'cache_entries.json', 'a', encoding='utf-8') as date_file:
        json.dump(entry, date_file, ensure_ascii=False)
        date_file.write('\n')  # Write a newline after each entry
    logger.info(f'Updated cache entries with: {entry}')

    # Return the name of the file
    return str(combined_cache_file)


def load_cache_from_json(
    loaded_json: dict,
    policy_analysis: PolicyCompartmentAnalysis,
    domains_analysis: IdentityDomainsAnalysis,
) -> bool:
    # Load everything
    logger.info(f'Loaded JSON({type(loaded_json)})')
    try:
        # Grab all of the elements of the cache
        policies = loaded_json.get('policies', [])
        dynamic_groups = loaded_json.get('dynamic_groups', [])
        cross_tenancy_data = loaded_json.get('cross_tenancy_policies', [])
        defined_aliases = loaded_json.get('defined_aliases', [])

        # Set the data in the policy analysis object
        policy_analysis.tenancy_name = loaded_json.get('tenancy_name', '')
        policy_analysis.tenancy_ocid = loaded_json.get('tenancy_ocid', '')
        policy_analysis.compartments = loaded_json.get('compartments', [])
        policy_analysis.regular_statements = policies
        policy_analysis.defined_aliases = defined_aliases
        policy_analysis.cross_tenancy_statements = cross_tenancy_data
        # Set the data in the domains analysis object
        domains_analysis.dynamic_groups = dynamic_groups
        domains_analysis.identity_domains = [
            Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
            for d in loaded_json.get('identity_domains', [])
        ]
        domains_analysis.groups = loaded_json.get('groups', {})
        domains_analysis.users = loaded_json.get('users', {})
        # Set the data as of time
        policy_analysis.data_as_of = loaded_json.get('data_as_of')
        domains_analysis.data_as_of = loaded_json.get('data_as_of')
        logger.info('Loaded combined cache from JSON')
        # Show counts of each loaded element
        logger.info(
            f'Loaded {len(policies)} policies, {len(dynamic_groups)} dynamic groups, '
            f'{len(cross_tenancy_data)} cross-tenancy policies, '
            f'{len(domains_analysis.identity_domains)} identity domains, '
            f'{len(domains_analysis.groups)} groups, and {len(domains_analysis.users)} users from cache.'
        )
        return True
    except json.JSONDecodeError as e:
        logger.error(f'Error decoding JSON from combined cache file: {e}')
        return False
    except Exception as e:
        logger.error(f'Error loading combined cache file: {e}')
        return False


def load_combined_cache(
    cached_tenancy: str,
    cached_date: str,
    policy_analysis: PolicyCompartmentAnalysis,
    domains_analysis: IdentityDomainsAnalysis,
) -> str:
    """Load combined cache for policies and dynamic groups.

    Given the name and data of a cache, loads the data into both of the centralized structures
    for Compartment/Policy and Identity Domain storage.

    Args:
        cached_tenancy: The name of the tenancy to load
        cached_date: The date string of the cache
        policy_analysis: The initialized PolicyCompartmentAnalysis class instance to use
        domains_analysis: The initialized IdentityDomainsAnalysis class instance to use
    Returns:
        A string indicating the name of the file used
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined_cache_file = CACHE_DIR / f'combined_cache_{cached_tenancy}_{cached_date}.json'
    if combined_cache_file.exists():
        try:
            with open(combined_cache_file, encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                # Grab all of the elements of the cache
                policies = cache_data.get('policies', [])
                dynamic_groups = cache_data.get('dynamic_groups', [])
                cross_tenancy_data = cache_data.get('cross_tenancy_policies', [])
                defined_aliases = cache_data.get('defined_aliases', [])
                # Set the data in the policy analysis object
                policy_analysis.tenancy_name = cache_data.get('tenancy_name', '')
                policy_analysis.tenancy_ocid = cache_data.get('tenancy_ocid', '')
                policy_analysis.compartments = cache_data.get('compartments', [])
                policy_analysis.regular_statements = policies
                policy_analysis.defined_aliases = defined_aliases
                policy_analysis.cross_tenancy_statements = cross_tenancy_data
                # Set the data in the domains analysis object
                domains_analysis.dynamic_groups = dynamic_groups
                domains_analysis.identity_domains = [
                    Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
                    for d in cache_data.get('identity_domains', [])
                ]
                domains_analysis.groups = cache_data.get('groups', {})
                domains_analysis.users = cache_data.get('users', {})
                # Set the data as of time
                policy_analysis.data_as_of = cache_data.get('data_as_of')
                domains_analysis.data_as_of = cache_data.get('data_as_of')
                logger.info(f'Loaded combined cache from: {combined_cache_file}')
                # Show counts of each loaded element
                logger.info(
                    f'Loaded {len(policies)} policies, {len(dynamic_groups)} dynamic groups, '
                    f'{len(cross_tenancy_data)} cross-tenancy policies, '
                    f'{len(domains_analysis.identity_domains)} identity domains, '
                    f'{len(domains_analysis.groups)} groups, and {len(domains_analysis.users)} users from cache.'
                )
                # Return True to indicate successful load
                return True
        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from combined cache file: {e}')
            return 'no cache'
        except Exception as e:
            logger.error(f'Error loading combined cache file: {e}')
            return 'no cache'
    logger.warning(f'Unable to load data from cache: {combined_cache_file}')
    return str(combined_cache_file)


def get_available_cache(tenancy_name: str | None) -> list[str]:
    """Get available cache files for a given profile

    If given no argument, simply return the list of all avialable cache files that
    exist in the cache directory.  Entries will contain the tenancy name and date loaded.

    Args:
        tenancy_name: The name of an OCI tenancy, which will filter the cache list down to only
        caches for that tenancy.

    Returns:
        a list of the available named caches
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return_entries = []
    try:
        with open(CACHE_DIR / 'cache_entries.json', encoding='utf-8') as date_file:
            entries = date_file.readlines()
        logger.debug(f'Entries found in cache_entries.json: {entries}')
        entries.reverse()  # Show most recent first
        logger.debug(f'Entries found in cache_entries.json (Reversed): {entries}')

        for entry in entries:
            cache = json.loads(entry)
            if tenancy_name and cache['tenancy_name'] != tenancy_name:
                continue
            return_entries.append(cache['tenancy_name'] + '\n' + cache['cache_date'])
    except json.JSONDecodeError:
        logger.warning('No cache entries found or cache_entries.json is empty.')
    except FileNotFoundError:
        logger.warning('cache_entries.json file not found. No cache entries available.')

    logger.info(f'Entries found in cache_entries.json: {len(return_entries)}')
    return return_entries


def load_cache_into_local_json(
    cached_tenancy: str,
    cached_date: str,
) -> dict:
    # Load everything into a JSON dict and return it
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined_cache_file = CACHE_DIR / f'combined_cache_{cached_tenancy}_{cached_date}.json'
    if combined_cache_file.exists():
        try:
            with open(combined_cache_file, encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                logger.info(f'Loaded combined cache from: {combined_cache_file}')
                # Show counts of each loaded element
                # Return data as object
                return cache_data
        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from combined cache file: {e}')
            return {}
        except Exception as e:
            logger.error(f'Error loading combined cache file: {e}')
            return {}
    logger.warning(f'Unable to load data from cache: {combined_cache_file}')
    return {}


# TODO: split this out into a CLI that is separated
def main():  # noqa: C901
    """Main function to parse arguments and print policies and dynamic groups."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument('--instance-principal', action='store_true', help='Use instance principal authentication')
    parser.add_argument('--get-caches', help='provide the names of caches', action='store_true')
    parser.add_argument('--print-all', help='Print all of the policies and DGs to screen', action='store_true')
    parser.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    parser.add_argument('--profile', default='DEFAULT', help='OCI CLI profile to use (default: DEFAULT)')
    parser.add_argument(
        '--export-json',
        help='Export everything that is collected (Policies, Dynamic Groups, Users, Groups, Cross-tenancy Policies) to JSON file',
        action='store_true',
    )
    args = parser.parse_args()

    # Configure logging based on verbose flag
    if args.verbose:
        logging.getLogger('oci-policy-dg-viewer').setLevel(logging.DEBUG)
        logging.getLogger('oci-policy-compartment-analysis').setLevel(logging.DEBUG)
        logging.getLogger('oci-identity-domains-analysis').setLevel(logging.DEBUG)

    # Initialize PolicyCompartmentAnalysis
    policy_analysis = PolicyCompartmentAnalysis(verbose=args.verbose)
    if not policy_analysis.initialize_client(use_instance_principal=args.instance_principal, profile=args.profile):
        logger.error('Failed to initialize PolicyCompartmentAnalysis client')
        return

    # Initialize IdentityDomainsAnalysis
    domains_analysis = IdentityDomainsAnalysis(verbose=args.verbose)
    if not domains_analysis.initialize_client(use_instance_principal=args.instance_principal, profile=args.profile):
        logger.error('Failed to initialize IdentityDomainsAnalysis client')
        return

    if args.get_caches:  # If get_caches is provided, list available caches
        available_caches = get_available_cache(tenancy_name=policy_analysis.tenancy_name)
        if available_caches:
            logger.info('Available caches:')
            for cache in available_caches:
                logger.info(cache)
        else:
            logger.info('No caches available.')
        return

    # Load policies and compartments
    if args.use_cache:
        if not load_combined_cache(
            cached_tenancy=policy_analysis.tenancy_name,
            cached_date=args.use_cache,
            policy_analysis=policy_analysis,
            domains_analysis=domains_analysis,
        ):
            logger.error('Failed to load combined cache')
            return
    else:
        if not policy_analysis.load_policies_and_compartments():
            logger.error('Failed to load policies and compartments from OCI')
            return
        if not domains_analysis.load_all_dynamic_groups():
            logger.error('Failed to load dynamic groups from OCI')
            return
        if not domains_analysis.load_domains_groups_users():
            logger.error('Failed to load identity domains, groups, and users from OCI')
            return
        cache_file_name = save_combined_cache(policy_analysis, domains_analysis)
        logger.info('Policies and dynamic groups saved successfully from OCI')

    # Print some basic details
    logger.info(f'Tenancy Name: {policy_analysis.tenancy_name}')
    logger.info(f'Tenancy OCID: {policy_analysis.tenancy_ocid}')
    logger.info(f'Data As Of: {policy_analysis.data_as_of}')
    logger.info('-' * 80)

    # Export JSON if needed
    if args.export_json:
        logger.info(f'The file is called {cache_file_name}')

    elif args.print_all:
        # Print regular policies
        logger.info('\nRegular Policies:')
        for stmt in policy_analysis.regular_statements:
            logger.info(f'Policy Name: {stmt.get("policy_name")}')
            logger.info(f'Statement: {stmt.get("statement_text")}')
            logger.info(f'Compartment Hierarchy: {stmt.get("compartment_string")}')
            if stmt.get('parsed'):
                logger.info(f'Subject Type: {stmt.get("subject_type")}')
                logger.info(f'Subject: {stmt.get("subject")}')
                logger.info(f'Verb: {stmt.get("verb")}')
                logger.info(f'Resource: {stmt.get("resource")}')
                logger.info(f'Permission: {stmt.get("permission")}')
                logger.info(f'Location Type: {stmt.get("location_type")}')
                logger.info(f'Location: {stmt.get("location")}')
                logger.info(f'Condition: {stmt.get("condition")}')
                logger.info(f'Comment: {stmt.get("comment")}')
                logger.info(f'Created: {stmt.get("created")}')
            else:
                logger.info('Statement could not be parsed into components')
            logger.info('-' * 80)

        # Print cross-tenancy policies
        logger.info('\nCross-Tenancy Policies:')
        logger.info('-' * 80)
        for stmt in policy_analysis.cross_tenancy_statements:
            logger.info(f'Policy Name: {stmt[0]}')
            logger.info(f'Statement: {stmt[1]}')
            logger.info(f'Created: {stmt[3]}')
            logger.info(f'Parsed: {stmt[4]}')
            if not stmt[4]:
                logger.info('-' * 80)
                continue
            logger.info(f'Statement Type: {stmt[5]}')
            logger.info(f'Principal: {stmt[6]}')
            logger.info(f'Of Tenancy: {stmt[7]}')
            logger.info(f'Action/Resource or Permission: {stmt[8]}')
            logger.info(f'Location: {stmt[9]}')
            logger.info(f'Where Clause: {stmt[10]}')
            logger.info(f'Comment: {stmt[11]}')
            logger.info('-' * 80)

        # Print dynamic groups
        logger.info('\nDynamic Groups:')
        logger.info('-' * 80)
        for dg in domains_analysis.dynamic_groups:
            logger.info(f'Domain: {dg[0]}')
            logger.info(f'Name: {dg[1]}')
            logger.info(f'Matching Rule: {dg[2]}')
            logger.info(f'In Use: {dg[3]}')
            logger.info(f'OCID: {dg[4]}')
            logger.info(f'Created: {dg[5]}')
            logger.info('-' * 80)
        # Print summary counts

    # Summary
    logger.info('-' * 80)
    logger.info(f'Total Regular Policies: {len(policy_analysis.regular_statements)}')
    logger.info(f'Total Cross-Tenancy Policies: {len(policy_analysis.cross_tenancy_statements)}')
    logger.info(f'Total Dynamic Groups: {len(domains_analysis.dynamic_groups)}')
    logger.info(f'Total Identity Domains: {len(domains_analysis.identity_domains)}')
    logger.info(f'Total Groups: {len(domains_analysis.groups)}')
    logger.info(f'Total Users: {len(domains_analysis.users)}')


if __name__ == '__main__':
    main()
