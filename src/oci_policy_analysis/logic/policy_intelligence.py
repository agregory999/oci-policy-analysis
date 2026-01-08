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

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import PolicyOverlap

logger = get_logger(component='policy_intelligence')


class PolicyIntelligenceEngine:
    """
    Provides post-load intelligence, overlap analysis, and advanced policy insights.
    Holds a reference to a fully-loaded PolicyAnalysisRepository.
    """

    def __init__(self, policy_repo):
        """
        Args:
            policy_repo (PolicyAnalysisRepository): Repository with loaded compartment, policy, and identity data.
        """
        self.policy_repo = policy_repo
        logger.info('Initialized PolicyIntelligenceEngine with repo.')

    def run_dg_in_use_analysis(self):
        """
        Analyzes Dynamic Group data for unused Dynamic Groups.
        Should be called after repo is loaded and statements parsed.
        """
        # Build a list of all subjects as list(tuple(domain,name))
        all_subjects: list[tuple] = []
        for st in self.policy_repo.regular_statements:
            subject_list = st.get('subject') or []
            subject_type = st.get('subject_type')
            logger.debug(f'SubType: {subject_type} Subject: {subject_list}')
            if subject_type == 'dynamic-group':
                logger.debug(f'Add: {subject_type} Subject: {subject_list}')
                all_subjects.extend(subject_list)

        logger.debug(f'Subject Count for DG in-use analysis: {len(all_subjects)}')

        # Iterate all DGs, look at their Domain and Name, then look through each statement
        unused_dynamic_groups = 0
        for dg in self.policy_repo.dynamic_groups:
            dg_domain = dg.get('domain_name') or 'default'
            dg_name = dg.get('dynamic_group_name')
            in_use = False  # Will be true at end if it exists
            for subj_domain, subj_name in all_subjects:
                logger.debug(f'Compare {dg_domain} = {subj_domain} and {dg_name} = {subj_name}')
                if dg_domain.casefold() == subj_domain.casefold() and dg_name.casefold() == subj_name.casefold():
                    in_use = True
                    break
            if not in_use:
                logger.info(f'Dynamic Group {dg_domain}/{dg_name} not in use')
                dg['in_use'] = False
                unused_dynamic_groups += 1

        logger.info(f'Found {unused_dynamic_groups} unused dynamic groups')

    def analyze_policy_overlap(self):  # noqa: C901
        """
        Analyze policy statements for potential overlaps, calling after all statements loaded/parsed.
        """
        logger.info('Analyzing policy overlaps - setting up structure for comparison')
        start_time = time.perf_counter()
        repo = self.policy_repo

        # TODO: Make this never fail even on weird data
        # TODO: Optimize for large numbers of policies/statements
        for st in repo.regular_statements:
            effective_compartment = st.get('effective_path', '') or 'n/a'
            statement_text = st.get('statement_text', '') or 'n/a'
            policy_overlap = []
            additional_notes = ''
            perm_overlap = []
            reason = ''
            logger.debug(
                f'Analyzing statement "{statement_text}" in policy {st["policy_name"]} for overlaps - effective path: {effective_compartment}'
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
                    f'Checking potential overlap(1) between "{st_permissions}" and "{other_permissions}" for statements "{st["policy_name"]}:{statement_text}" and "{other_st["policy_name"]}:{other_st["statement_text"]}"'
                )
                # No idea why yet, but some statements have empty permission lists - treat these as resource-only checks
                if not other_permissions and not st_permissions:
                    logger.debug(
                        f'Both statements have no permissions, treating as resource-only overlap check: {st["policy_name"]}:{statement_text} / {other_st["policy_name"]}:{other_st["statement_text"]}'
                    )
                    continue

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
                    perm_overlap = ['Resource:' + st.get('resource', '')]
                else:
                    perm_overlap = repo.permission_reference_repo.check_overlap(st_permissions, other_permissions)
                    if len(perm_overlap) == 0:
                        continue
                    reason = (
                        f'Permission Overlap between resource {st["resource"]} '
                        f'and {other_st["resource"]}, subject_type, and at least one subject, '
                        f'with broader effective compartment in other policy ({other_st["effective_path"]})'
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
                        # Flatten if a list, or join with '/'
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
                    f'Potential Overlap: {st["policy_name"]}:{statement_text} / {other_st["policy_name"]}:{other_st["statement_text"]}'
                )
                confidence = 'high'
                if st.get('conditions') or other_st.get('conditions'):
                    logger.debug(
                        f'Policy Overlap detected with WHERE clause: Statement "{statement_text}" in policy {st["policy_name"]} '
                        f'is potentially superseded by statement {other_st["statement_text"]} in policy {other_st["policy_name"]}'
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
                st['policy_overlap'] = policy_overlap
                logger.debug(
                    f'Policy Overlap(s) found for statement "{statement_text}" in policy {st["policy_name"]}: {len(policy_overlap)}'
                )
        end_time = time.perf_counter()
        logger.info(
            f'Initialized policy_overlap lists for {len(repo.regular_statements)} statements in {end_time - start_time:.2f} seconds'
        )

    def get_policy_overlaps_by_internal_id(self, internal_id: str):
        """
        Returns all PolicyOverlap entries for a given policy statement internal ID.
        """
        repo = self.policy_repo
        overlaps: list = []
        for st in repo.regular_statements:
            if st.get('internal_id') == internal_id:
                overlaps = st.get('policy_overlap', [])
                break
        return overlaps

    def find_invalid_statements(self):  # noqa: C901
        """
        Mark regular policy statements as invalid if they fail various validity checks, such as:
        - Nonexistent Dynamic Groups or Groups
        - Invalid compartment OCIDs
        - Invalid verbs/resources

        This method modifies the statements in-place, adding an `invalid_reasons` list if applicable.
        """
        repo = self.policy_repo
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
                        invalid_reasons.append(f'Dynamic Group {dg_name} not found in tenancy')
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
                        invalid_reasons.append(f'Group {group_name} not found in tenancy')
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
                invalid_reasons.append(f'Invalid Verb ({st.get("verb")}) found')

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

        logger.debug(f"-Statement: {st.get('statement_text')}")
        # Case 1 - in tenancy
        if st.get('location_type') == 'tenancy':
            st['effective_compartment_ocid'] = repo.tenancy_ocid
            st['effective_path'] = self._name_path_from_ocid(repo.tenancy_ocid)
            if st['effective_path']:
                st['effective_path'] = st['effective_path'].lower()
            logger.debug(f"Effective (ten) path for {st.get('statement_text')}: {st.get('effective_path')}")
        # Case 2 - Compartment ID
        elif st.get('location_type') == 'compartment id':
            st['effective_compartment_ocid'] = st.get('location')
            st['effective_path'] = self._name_path_from_ocid(st.get('location'))
            if st['effective_path']:
                st['effective_path'] = st['effective_path'].lower()
            st.setdefault('parsing_notes', []).append('Compartment ID used for location')
            logger.debug(f"Effective (id) path for {st.get('statement_text')}: {st.get('effective_path')}")
        # Case 3 - Compartment Name (with or without full path)
        else:
            logger.debug(f"Need to calc eff path for {st.get('statement_text')}")
            location = st.get('location')
            parts = [p.strip() for p in location.split(':') if p.strip()] if location else []
            policy_path = self._name_path_from_ocid(st.get('compartment_ocid'))
            logger.debug(f'Policy Path: {policy_path} / Location parts: {parts}')
            eff_path = policy_path
            logger.debug(f'Initial effective path: {eff_path}')
            logger.debug(f"Compartment OCID for policy: {st.get('compartment_ocid')}")
            comp_name = self._comp_name_path_ocid(st.get('compartment_ocid'))
            logger.debug(f'Compartment name for compare: {comp_name}')
            if parts and parts[0].casefold() == (comp_name.casefold() if comp_name else ''):
                st.setdefault('parsing_notes', []).append('Deleted compartment from effective location')
                del parts[0]
            for p in parts:
                if eff_path is None:
                    eff_path = ''
                eff_path += f'/{p}'
            if eff_path:
                eff_path = eff_path.lower()
            logger.debug(f"Effective (loc) path for {st.get('statement_text')}: {eff_path}")
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
        logger.debug(f"Lookup details: {getattr(self, 'compartments_by_id', {})}")
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

    # Add further advanced intelligence/analysis methods as needed here.
