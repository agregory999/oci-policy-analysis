##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# reference_data_repo.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import glob
import json
import os

from oci_policy_analysis.common.logger import get_logger

logger = get_logger(component='reference_data_repo')


class ReferenceDataRepo:
    """
    Repository for reference data on resources, families, and permissions.
    Loads from JSON files in a specified directory.

    JSON Structure Example:
    {
        "resources": {
            "resource_name": {
                "verbs": {
                    "inspect": ["permission1", "permission2"],
                    "read": ["permission3"],
                    "use": ["permission4"],
                    "manage": ["permission5"]
                }
            },
            ...
        },
        "families": {
            "family_name": {
                "resources": ["resource_name1", "resource_name2"],
                "source_url": "http://example.com/source"
            },
            ...
        }
    }

    Once all files are loaded, provides methods to query permissions and check overlaps.
    """

    def __init__(self, json_dir='permissions'):
        self.json_dir = os.path.join(os.path.dirname(__file__), json_dir)
        # Always define keys needed by consumers, even if load_data hasn't run yet
        self.data = {'resources': {}, 'families': {}}
        self.resource_name_map = {}
        self.family_name_map = {}
        self.verb_set = {'inspect', 'read', 'use', 'manage'}

    def load_data(self):
        logger.info(f'Loading reference data from directory: {self.json_dir}')
        self.data = {'resources': {}, 'families': {}}
        files_loaded = 0
        # Store operations for all loaded files in new field (flat)
        self.data['operations'] = {}
        # New: Also store a grouped operations structure for API/source display (`operations_by_api`)
        self.data['operations_by_api'] = {}
        # Per-verb risk weights: each permission is scored by the verb it belongs to (exposure points)
        verb_risk = {'inspect': 1, 'read': 5, 'use': 50, 'manage': 100}
        for file_path in glob.glob(os.path.join(self.json_dir, '*.json')):
            logger.debug(f'Loading reference data file: {file_path}')
            try:
                with open(file_path) as f:
                    file_data = json.load(f)
                    debug_resources = file_data.get('resources', {})
                    debug_families = file_data.get('families', {})
                    debug_operations = file_data.get('operations', {})
                    # Inject risk score into resources-per-verb-permission
                    for _res_name, resdata in debug_resources.items():
                        verbs = resdata.get('verbs', {})
                        for verb, perms in verbs.items():
                            risk = verb_risk.get(verb, 1)
                            if not isinstance(perms, list):
                                continue
                            # Store per-resource dictionary so we can find the risk for a permission
                            for perm in perms:
                                resdata.setdefault('permission_risks', {})[perm.upper()] = risk
                    logger.debug(
                        f'File {file_path}: contains {len(debug_resources)} resources, {len(debug_families)} families, {len(debug_operations)} operations'
                    )
                    self.data['resources'].update(debug_resources)
                    self.data['families'].update(debug_families)
                    # Determine api_name from filename (basename, no extension)
                    api_name = os.path.splitext(os.path.basename(file_path))[0]
                    if debug_operations:
                        self.data['operations'].update(debug_operations)
                        # group by api_name: {op_name: op_data + 'api_name': ...}
                        ops = {}
                        for op_name, meta in debug_operations.items():
                            meta_copy = dict(meta)  # don't mutate input
                            meta_copy['api_name'] = api_name
                            ops[op_name] = meta_copy
                        self.data['operations_by_api'][api_name] = ops
                    logger.debug(
                        f'File {file_path} loaded/merged. Cumulative resources: {len(self.data["resources"])}, families: {len(self.data["families"])}, operations: {len(self.data["operations"])}, operations_by_api: {len(self.data["operations_by_api"])}'
                    )
                    files_loaded += 1
            except Exception as e:
                logger.error(f'Error loading {file_path}: {e}')
        logger.info(
            f'Loaded {files_loaded} reference data files. Total resources: {len(self.data["resources"])}, families: {len(self.data["families"])}, operations: {len(self.data["operations"])}, operations_by_api: {len(self.data["operations_by_api"])}'
        )
        # Create case-insensitive maps for resources and families
        self.resource_name_map = {k.lower(): k for k in self.data['resources'].keys()}
        self.family_name_map = {k.lower(): k for k in self.data['families'].keys()}
        self.verb_set = {'inspect', 'read', 'use', 'manage'}

    def get_permission_risk(self, permission: str, resource: str | None = None):
        """
        Get the risk score for a single permission string (optionally for a given resource).
        If resource is not provided, search all resources.

        This method is case-insensitive for permission and resource.
        """
        perm = permission.upper()
        resource_key = None
        if resource:
            resource_key = self.resource_name_map.get(resource.lower())
        if resource_key and resource_key in self.data['resources']:
            risk = self.data['resources'][resource_key].get('permission_risks', {}).get(perm)
            if risk is not None:
                return risk
        # Search all resources if resource not given or not found
        for resdata in self.data['resources'].values():
            risk = resdata.get('permission_risks', {}).get(perm)
            if risk is not None:
                return risk
        return 1  # default fall-back risk score

    def get_permissions_risk_sum(self, permissions, resource: str | None = None):
        """
        Given a list of permissions (case-insensitive), compute the summed risk score.
        """
        total = 0
        for perm in permissions:
            total += self.get_permission_risk(perm, resource)
        return total

    def get_verb_resource_risk(self, verb: str, resource: str):
        """
        Get cumulative permission risk for all permissions associated with given verb/resource.
        """
        perms = self.get_permissions(resource, verb)
        return self.get_permissions_risk_sum(perms, resource)

    def get_permissions(self, entity, verb, action='allow'):
        """
        Get cumulative permissions for a resource or family at a given verb level and action.
        For "allow": behavior is as before.
        For "deny": logic is inverted -- broader verbs (like 'inspect') deny more permissions.

        Special case: if entity == 'all-resources', gather permissions from *all* resources/types,
        but for the specified verb only. For 'allow', union the specific-verb permissions from all.
        For 'deny', union the same but these are what is DENIED.

        Args:
            entity (str): Resource name or family name (case-insensitive).
            verb (str): Verb level ('inspect', 'read', 'use', 'manage'), case-insensitive.
            action (str): "allow" or "deny" (default: "allow")

        Returns:
            list: List of cumulative permissions, always UPPERCASE.
        """
        # Normalize inputs
        entity_ci = (entity or '').lower()
        verb_ci = (verb or '').lower()
        # Special entity: all-resources should follow the same cumulative
        # allow/deny semantics as individual resources and families.
        # We therefore aggregate the cumulative permissions from every
        # known resource instead of looking only at the single verb.
        if entity_ci == 'all-resources':
            all_perms = set()
            for res_name in self.data['resources'].keys():
                perms = self._get_cumulative_permissions(res_name, verb_ci, action)
                if perms:
                    all_perms.update(perms)
            return list(all_perms)
        # Handle families/resources with case-insensitive lookups
        if entity_ci in self.family_name_map:
            fam_key = self.family_name_map[entity_ci]
            all_perms = set()
            for res in self.data['families'][fam_key]['resources']:
                perms = self._get_cumulative_permissions(res, verb_ci, action)
                if perms:
                    all_perms.update(perms)
            return [p.upper() for p in all_perms]
        else:
            # Resource lookup
            res_key = self.resource_name_map.get(entity_ci, entity)
            perms = self._get_cumulative_permissions(res_key, verb_ci, action)
            if perms:
                return [p.upper() for p in perms]
            return []

    def _get_cumulative_permissions(self, resource, verb, action='allow'):
        # Case-insensitive resource and verb lookup
        resource_ci = (resource or '').lower()
        verb_ci = (verb or '').lower()
        resource_key = self.resource_name_map.get(resource_ci, resource)
        verbs_order = ['inspect', 'read', 'use', 'manage']
        try:
            index = [v.lower() for v in verbs_order].index(verb_ci)
        except ValueError:
            return None
        if resource_key not in self.data['resources']:
            return None
        perms = []
        if action == 'deny':
            # For deny, we deny verb and everything MORE powerful (up the privilege ladder)
            for v in [v.lower() for v in verbs_order][index:]:
                perms.extend(self.data['resources'][resource_key]['verbs'].get(v, []))
        else:
            # For allow, we allow verb and everything LESS powerful
            for v in [v.lower() for v in verbs_order][: index + 1]:
                perms.extend(self.data['resources'][resource_key]['verbs'].get(v, []))
        return list({p.upper() for p in perms})

    def check_overlap(self, perm_set1, perm_set2):
        """
        Check for overlapping permissions between two permission sets.  Uses 2 lists of permissions.
        Always compares and returns upper case permissions (display, logic, and reporting).
        """
        if not perm_set1 or not perm_set2:
            return []
        overlap = {p.upper() for p in perm_set1} & {p.upper() for p in perm_set2}
        return list(overlap)

    def check_overlap_params(self, entity1, verb1, action1, entity2, verb2, action2):
        """
        Check overlapped permissions by specifying both sides as entity/verb/action.

        Args:
            entity1 (str), verb1 (str), action1 (str)
            entity2 (str), verb2 (str), action2 (str)

        Returns:
            list: List of overlapping permissions.
        """
        perms1 = self.get_permissions(entity1, verb1, action1)
        perms2 = self.get_permissions(entity2, verb2, action2)
        return self.check_overlap(perms1, perms2)

    def get_source(self, entity):
        """
        Retrieve the source URL(s) for a given entity (resource or family) in a case-insensitive manner.
        """
        sources = set()
        entity_ci = (entity or '').lower()
        fam_key = self.family_name_map.get(entity_ci)
        if fam_key and fam_key in self.data['families']:
            source_url = self.data['families'][fam_key].get('source_url', '')
            if source_url:
                sources.add(source_url)
        else:
            res_key = self.resource_name_map.get(entity_ci)
            if res_key:
                for _fam, fam_data in self.data['families'].items():
                    if res_key in fam_data['resources']:
                        source_url = fam_data.get('source_url', '')
                        if source_url:
                            sources.add(source_url)
        return ', '.join(sources) if sources else ''

    def get_containing_family(self, resource_name: str) -> str | None:
        """Return the family that contains the given resource, if any.

        The lookup is case-insensitive for the resource name and returns the
        canonical family key as loaded from reference data JSON files.

        Args:
            resource_name: OCI resource token (for example: ``subnets``).

        Returns:
            The family name (for example: ``virtual-network-family``) if found,
            otherwise ``None``.
        """

        resource_ci = (resource_name or '').strip().lower()
        if not resource_ci:
            return None

        # Normalize to canonical resource key when possible.
        resource_key = self.resource_name_map.get(resource_ci, resource_name)

        for fam_name, fam_data in self.data.get('families', {}).items():
            resources = fam_data.get('resources', []) or []
            if any(str(res).strip().lower() == str(resource_key).strip().lower() for res in resources):
                return fam_name
        return None

    def has_api_operation_permissions(self, operation_name, granted_permissions):
        """
        Check if all required permissions for the given API operation are present in the granted_permissions list.
        Args:
            operation_name (str): Name of the API operation (as in 'operations' node).
            granted_permissions (list[str]): List of permission strings to check.
        Returns:
            bool: True if all required permissions for the operation are present, False otherwise.
        """
        # Find operation (case-sensitive key match)
        op_info = self.data.get('operations', {}).get(operation_name)
        if not op_info:
            logger.debug(f'API operation {operation_name!r} not found in reference data.')
            return False
        required = {p.upper() for p in op_info.get('permissions', [])}
        provided = {p.upper() for p in granted_permissions}
        missing = required - provided
        logger.debug(
            f'Checking permissions for op={operation_name!r}; required={required}, provided={provided}, missing={missing}'
        )
        return not missing
