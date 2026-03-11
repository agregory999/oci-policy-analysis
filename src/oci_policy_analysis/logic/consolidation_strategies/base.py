##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# base.py – Consolidation strategy protocol and pluggable contract.
#
# Strategies are kept logically separate from the engine; the engine depends
# on this protocol only. New strategies implement this protocol and are
# registered with ConsolidationEngine (e.g. via register_strategy or constructor).
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from typing import Protocol

from oci_policy_analysis.common.models_consolidation import ConsolidationPlan
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository


class Strategy(Protocol):
    """
    Protocol for pluggable consolidation strategies.

    Implement this protocol in a separate module and register with
    ConsolidationEngine.register_strategy() or pass strategies= into the constructor.
    """

    strategy_id: str
    """Unique machine-readable id (e.g. for persistence and lookup)."""

    display_name: str
    """Human-readable name shown in the UI (e.g. strategy dropdown)."""

    def build_plan(
        self,
        *,
        repo: PolicyAnalysisRepository,
        tenancy_ocid: str,
        dataset_version: str | None,
        candidate_internal_ids: set[str],
        protected_internal_ids: set[str],
        plan_id: str,
        params: dict[str, object] | None = None,
    ) -> ConsolidationPlan:
        """Build a consolidation plan for the given candidates and context.

        Args:
            repo: Policy repository with policies, compartments, regular_statements.
            tenancy_ocid: Tenancy OCID for the plan.
            dataset_version: Optional dataset version label.
            candidate_internal_ids: Set of statement internal_ids to consolidate.
            protected_internal_ids: Set of statement internal_ids to exclude.
            plan_id: Unique plan identifier.
            params: Optional strategy params (e.g. marker_tag_key for execution marking).

        Returns:
            A ConsolidationPlan with plan_id, plan_steps, plan_tags, etc.
        """
        ...
