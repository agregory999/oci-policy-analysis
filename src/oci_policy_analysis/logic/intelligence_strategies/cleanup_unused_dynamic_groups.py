##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# cleanup_unused_dynamic_groups.py – Unused dynamic groups cleanup check.
#
# Assumes engine has already run run_dg_in_use_analysis() before strategies.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class UnusedDynamicGroupsCheck:
    """Intelligence strategy: collect unused dynamic groups for cleanup."""

    strategy_id: str = 'unused_dynamic_groups'
    display_name: str = 'Unused dynamic groups'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        unused = repo.filter_dynamic_groups({'in_use': [False]})
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = unused
