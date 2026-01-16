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
from oci_policy_analysis.common.models import PolicyIntelligence, PolicyOverlap
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo

logger = get_logger(component='policy_intelligence')


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

    def __init__(self, policy_repo):
        """
        Initialize the PolicyIntelligenceEngine and prepare analytics overlay structures.

        Args:
            policy_repo (PolicyAnalysisRepository): Repository with loaded compartment, policy, and identity data.
        """
        self.policy_repo = policy_repo
        # Explicitly type and instantiate the overlay using the model
        self.overlay: PolicyIntelligence = PolicyIntelligence(
            overlaps=[], recommendations=[], risk_scores=[], consolidations=[]
        )
        self.permissions_report = {}
        logger.info('Initialized PolicyIntelligenceEngine with repo.')

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
        statements = self.policy_repo.regular_statements
        for _idx, stmt in enumerate(statements):
            try:
                effective_path = stmt.get('effective_path')
                if not effective_path or effective_path is None:
                    effective_path = 'UNKNOWN'
                action = stmt.get('action', 'allow').lower()
                subjects = stmt.get('subject', [])
                subject_type = stmt.get('subject_type', 'unknown')
                permissions = stmt.get('permission', [])
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
                if subjects is None:
                    subjects = [('Default', 'UNKNOWN')]
                for subject_domain, subject_name in subjects:
                    domain_str = str(subject_domain) if subject_domain else 'Default'
                    subject_key = f'{subject_type}:{domain_str}/{subject_name}'
                    if effective_path not in report:
                        report[effective_path] = {}
                    if subject_key not in report[effective_path]:
                        report[effective_path][subject_key] = {'allow': set(), 'deny': set()}
                    if action == 'deny':
                        report[effective_path][subject_key]['deny'].update(permissions)
                    else:
                        report[effective_path][subject_key]['allow'].update(permissions)
                    for perm in permissions:
                        perm_conditionals[(effective_path, subject_key, perm)] = is_conditional
                        perm_statements[(effective_path, subject_key, perm)] = statement_text
                    rsrc = resource_str if resource_str else ('Permissions (select row)' if permissions else '')
                    resource_map[(effective_path, subject_key)] = rsrc
            except Exception:
                pass
        for path in report:
            for subject in report[path]:
                report[path][subject]['allow'] = sorted(
                    [perm for perm in list(report[path][subject]['allow']) if perm is not None]
                )
                report[path][subject]['deny'] = sorted(
                    [perm for perm in list(report[path][subject]['deny']) if perm is not None]
                )
        # Store both the report and auxiliary maps for selection/detail lookups:
        self.permissions_report = {
            'report': report,
            'resource_map': resource_map,
            'perm_conditionals': perm_conditionals,
            'perm_statements': perm_statements,
        }
        return self.permissions_report

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

    def calculate_potential_risk_scores(self, where_clause_reduction_pct=50):  # noqa: C901
        """
        Calculates potential risk scores for each policy statement based on permission risk values (from reference data)
        and multiplies by a compartment exposure factor based on scope in the compartment hierarchy.
        Applies a raw score reduction for statements with a WHERE clause ('conditions'), adjustable as a percentage.

        Results are stored in self.overlay["risk_scores"] as a list of dicts:
          { "statement_internal_id", "score", "notes", "recommendations" }
        """
        logger.info(
            'Calculating potential risk scores for all policy statements with where_clause_reduction_pct=%s',
            where_clause_reduction_pct,
        )
        repo = self.policy_repo
        ref_repo = repo.permission_reference_repo
        # Ensure compartment index is built
        if not hasattr(self, 'compartments_by_path') or not self.compartments_by_path:
            self.build_compartment_index()

        risk_scores = []
        for st in repo.regular_statements:
            internal_id = st.get('internal_id')
            verb = st.get('verb', '').lower()
            resource = st.get('resource', '').lower()
            permissions = st.get('permission', [])
            effective_path = st.get('effective_path', '') or ''
            compartment_exposure = 1

            # Compute permission risk sum
            if permissions:
                perm_risk_base = ref_repo.get_permissions_risk_sum(permissions, resource)
                risk_detail = f"Sum of permission risks ({', '.join(permissions)}): {perm_risk_base}"
            else:
                verb_risk_map = {'inspect': 1, 'read': 2, 'use': 10, 'manage': 50}
                perm_risk_base = ref_repo.get_verb_resource_risk(verb, resource)
                if perm_risk_base == 0:
                    is_family = '-family' in resource
                    if verb == 'inspect':
                        base = 1 * (2 if is_family else 1)
                        expl = f'inspect verb base ({base})'
                    elif verb == 'read':
                        base = 2 * (2 if is_family else 1)
                        expl = f'read verb base ({base})'
                    else:
                        base = 2 if is_family else 1
                        expl = f'default base ({base})'
                    risk_factor = verb_risk_map.get(verb, 1)
                    perm_risk_base = base * risk_factor
                    risk_detail = f'No permissions for verb/resource ({verb}, {resource}): rubric base {base}*verb_mult{risk_factor}={perm_risk_base} ({expl})'
                else:
                    risk_detail = f'Verb/resource risk for ({verb}, {resource}): {perm_risk_base}'
            notes = [risk_detail]
            recommendations = []

            # Compartment exposure: count all subcompartments-in-scope (including self)
            path_lower = effective_path.lower()
            exposure_count = 0
            scope_label = '(path unknown)'
            if path_lower:
                for other_path in self.compartments_by_path or {}:
                    if other_path and other_path.lower().startswith(path_lower):
                        exposure_count += 1
                if exposure_count == 0:
                    exposure_count = 1
                scope_label = f'Effective path: {effective_path}, Exposure compartments covered: {exposure_count}'
            else:
                exposure_count = 1
                scope_label = 'Scope unknown: exposure x1'
            compartment_exposure = exposure_count
            notes.append(scope_label)

            total_risk = perm_risk_base * compartment_exposure
            notes.append(f'Final potential risk: {perm_risk_base} x {compartment_exposure} = {total_risk}')

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

    def build_cleanup_items(self):
        """
        Analyze policy repository and collect actionable cleanup items for all key risk categories.
        This should be called BEFORE build_overall_recommendations.
        The lists are attached to self.overlay["cleanup_items"].
        """
        repo = self.policy_repo

        # (1) Invalid Policy Statements
        invalid_statements = [st for st in repo.regular_statements if st.get('invalid_reasons')]

        # (2) Unused Groups
        unused_groups = [group for group in repo.groups if not repo.get_users_for_group(group)]

        # (3) Unused Dynamic Groups
        self.run_dg_in_use_analysis()  # ensure DG in_use fields are updated
        unused_dgs = repo.filter_dynamic_groups({'in_use': [False]})

        # (4) Overly broad manage all-resources
        statements_too_open = [
            st
            for st in repo.regular_statements
            if (
                st.get('verb', '').lower() == 'manage'
                and st.get('resource', '').lower() == 'all-resources'
                and st.get('policy_name', '') != 'Tenant Admin Policy'
            )
        ]

        # (5) Any-user without where
        anyuser_no_where = [
            st for st in repo.regular_statements if st.get('subject_type') == 'any-user' and not st.get('conditions')
        ]

        self.overlay['cleanup_items'] = {
            'invalid_statements': invalid_statements,
            'unused_groups': unused_groups,
            'unused_dynamic_groups': unused_dgs,
            'statements_too_open': statements_too_open,
            'anyuser_no_where': anyuser_no_where,
        }

    def build_overall_recommendations(self):
        """
        Build the overall (user-facing) recommendations list for overlay["recommendations"].
        Each recommendation summarizes the count of existing actionable issues.
        Assumes build_cleanup_items has already been called and populated "cleanup_items".
        If no real recommendations are found, yields one informational finding as a placeholder.
        """
        cleanup = self.overlay.get('cleanup_items', {})
        recommendations = []

        if cleanup.get('invalid_statements'):
            recommendations.append(
                {
                    'Recommendation': 'Investigate invalid policy statements',
                    'Priority': 'High',
                    'Category': 'Policy Hygiene',
                    'Notes': f"{len(cleanup['invalid_statements'])} invalid policy statement(s) detected. Review the cleanup/fix tab for details.",
                    'Action': 'Plan: Review and remediate invalid policy statements',
                    'ActionDetail': 'Examine policies with invalid statements and resolve as appropriate.',
                }
            )
        if cleanup.get('unused_groups'):
            recommendations.append(
                {
                    'Recommendation': 'Ensure all groups are needed; consider removing unused groups',
                    'Priority': 'Medium',
                    'Category': 'Identity Management',
                    'Notes': f"{len(cleanup['unused_groups'])} unused group(s) (0 members) detected. See cleanup/fix tab for actionable list.",
                    'Action': 'Plan: Remove or repurpose unused groups',
                    'ActionDetail': 'Review business need for empty groups and remove unless justified.',
                }
            )
        if cleanup.get('unused_dynamic_groups'):
            recommendations.append(
                {
                    'Recommendation': 'Clean up unused Dynamic Groups',
                    'Priority': 'Medium',
                    'Category': 'Identity Management',
                    'Notes': f"{len(cleanup['unused_dynamic_groups'])} unused dynamic group(s) detected. See cleanup/fix tab for actionable list.",
                    'Action': 'Plan: Remove unused dynamic groups',
                    'ActionDetail': 'Delete or reassign dynamic groups not referenced in policy statements.',
                }
            )
        if cleanup.get('statements_too_open'):
            recommendations.append(
                {
                    'Recommendation': 'Tighten policies that are too open (manage all-resources)',
                    'Priority': 'High',
                    'Category': 'Access Scope',
                    'Notes': f"{len(cleanup['statements_too_open'])} policy statement(s) granting 'manage all-resources' broadly detected. See cleanup/fix tab for details.",
                    'Action': "Plan: Restrict broad 'manage all-resources' statements",
                    'ActionDetail': 'Replace with least privilege and restrict to smallest viable compartment and subject.',
                }
            )
        if cleanup.get('anyuser_no_where'):
            recommendations.append(
                {
                    'Recommendation': 'Always limit any-user statements with a concise where clause',
                    'Priority': 'High',
                    'Category': 'Access Scope',
                    'Notes': f"{len(cleanup['anyuser_no_where'])} policy statement(s) with 'any-user' subject and no where clause detected. See cleanup/fix tab for details.",
                    'Action': 'Plan: Add where clauses to any-user statements',
                    'ActionDetail': 'Enforce least privilege by specifying a concise where clause for all any-user policies.',
                }
            )

        # Existing logic for critical recommendations (unchanged)
        repo = self.policy_repo
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
                        'Action': 'Plan: Review statement locations',
                        'ActionDetail': f"Check statement: '{st.get('statement_text','')}' in policy '{policy_name}' for location issues.",
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
                        'Action': 'Plan: Restrict scope for manage all-resources',
                        'ActionDetail': f"Work with compartment admins to restrict '{policy_name}' or replace 'manage all-resources' with least privilege.",
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
                    'Action': 'No action needed',
                    'ActionDetail': 'No action is required at this time.',
                }
            )
        self.overlay['recommendations'] = recommendations
        # Log summary
        critical_count = sum(1 for r in recommendations if r.get('Priority') == 'Critical')
        high_count = sum(1 for r in recommendations if r.get('Priority') == 'High')
        logger.info(
            f'Built overall recommendations: {len(recommendations)} total, {critical_count} critical, {high_count} high.'
        )

    def build_policy_consolidation(self):
        """
        Analyze policies/statements for possible consolidation opportunities and
        populate overlay["consolidations"] with a list of dicts:
          {
            "Statement": ...,
            "Policy Name(s)": ...,
            "Compartment": ...,
            "Principal": ...,
            "Service/Resource": ...,
            "Consolidation Reason": ...,
            "Action": ...,  # <-- always present now
            "ActionDetail": ...  # <-- optional for detail/planning dialog
          }

        Criteria:
        1. Policies with only a single statement (likely consolidation candidate).
        2. Statements with identical principal, compartment and service/resource,
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
                consolidation_findings.append(
                    {
                        'Statement': statement_text,
                        'Policy Name(s)': pol,
                        'Compartment': compartment,
                        'Principal': principal,
                        'Service/Resource': resource,
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
                        'Action': f"Plan: Consolidate policies {', '.join(sorted(policy_names))} into one.",
                        'ActionDetail': f'Statements: {statement_texts}.\nEvaluate details and propose a single policy.',
                    }
                )

        # Always append a sample/demo row at the end for display testing.
        consolidation_findings.append(
            {
                'Statement': '[Sample] Consolidation not yet implemented: demo stub row',
                'Policy Name(s)': '[demo]',
                'Compartment': '[sample]',
                'Principal': '[sample]',
                'Service/Resource': '[sample]',
                'Consolidation Reason': 'Demo: Consolidation engine stubbed/not implemented yet.',
                'Action': 'Not yet implemented',
                'ActionDetail': 'Policy consolidation is not implemented in this version. This is a stub/demo entry for UI and engine plumbing.',
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
