##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# cleanup_unused_groups.py – Unused groups cleanup check.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

# OCI Identity Domains system group that cannot be deleted; exclude from cleanup.
ALL_DOMAIN_USERS_GROUP_NAME = 'All Domain Users'


@dataclass(frozen=True)
class UnusedGroupsCheck:
    """Intelligence strategy: collect groups with no users for cleanup."""

    strategy_id: str = 'unused_groups'
    display_name: str = 'Unused groups'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        if not getattr(repo, 'load_all_users', True):
            overlay.setdefault('cleanup_items', {})[self.strategy_id] = []
            return
        unused = [
            g
            for g in repo.groups
            if (g.get('group_name') or '').strip().lower() != ALL_DOMAIN_USERS_GROUP_NAME.lower()
            and not repo.get_users_for_group(g)
        ]
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = unused
