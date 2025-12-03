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
        logger.info(f'Loading reference data from directory: {self.json_dir}')
        self.data = self._load_data()

    def _load_data(self):
        data = {'resources': {}, 'families': {}}
        files_loaded = 0
        for file_path in glob.glob(os.path.join(self.json_dir, '*.json')):
            logger.debug(f'Loading reference data file: {file_path}')
            try:
                with open(file_path) as f:
                    file_data = json.load(f)
                    debug_resources = file_data.get('resources', {})
                    debug_families = file_data.get('families', {})
                    logger.debug(
                        f'File {file_path}: contains {len(debug_resources)} resources, {len(debug_families)} families'
                    )
                    data['resources'].update(debug_resources)
                    data['families'].update(debug_families)
                    logger.debug(
                        f'File {file_path} loaded/merged. Cumulative resources: {len(data["resources"])}, families: {len(data["families"])}'
                    )
                    files_loaded += 1
            except Exception as e:
                logger.error(f'Error loading {file_path}: {e}')
        logger.info(
            f'Loaded {files_loaded} reference data files. Total resources: {len(data["resources"])}, families: {len(data["families"])}'
        )
        return data

    def get_permissions(self, entity, verb, action='allow'):
        """
        Get cumulative permissions for a resource or family at a given verb level and action.
        For "allow": behavior is as before.
        For "deny": logic is inverted -- broader verbs (like 'inspect') deny more permissions.

        Args:
            entity (str): Resource name or family name.
            verb (str): Verb level ('inspect', 'read', 'use', 'manage').
            action (str): "allow" or "deny" (default: "allow")

        Returns:
            list: List of cumulative permissions.
        """
        if entity in self.data['families']:
            all_perms = set()
            for res in self.data['families'][entity]['resources']:
                perms = self._get_cumulative_permissions(res, verb, action)
                if perms:
                    all_perms.update(perms)
            return [p.upper() for p in all_perms]
        else:
            perms = self._get_cumulative_permissions(entity, verb, action)
            if perms:
                return [p.upper() for p in perms]
            return perms

    def _get_cumulative_permissions(self, resource, verb, action='allow'):
        if resource not in self.data['resources']:
            return None
        verbs_order = ['inspect', 'read', 'use', 'manage']
        try:
            index = verbs_order.index(verb)
        except ValueError:
            return None
        perms = []
        if action == 'deny':
            # For deny, we deny verb and everything MORE powerful (up the privilege ladder)
            for v in verbs_order[index:]:
                perms.extend(self.data['resources'][resource]['verbs'].get(v, []))
        else:
            # For allow, we allow verb and everything LESS powerful
            for v in verbs_order[: index + 1]:
                perms.extend(self.data['resources'][resource]['verbs'].get(v, []))
        return list({p.upper() for p in perms})  # Dedup and uppercase

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
        sources = set()
        if entity in self.data['families']:
            source_url = self.data['families'][entity].get('source_url', '')
            if source_url:
                sources.add(source_url)
        else:
            for _fam, fam_data in self.data['families'].items():
                if entity in fam_data['resources']:
                    source_url = fam_data.get('source_url', '')
                    if source_url:
                        sources.add(source_url)
        return ', '.join(sources) if sources else ''
