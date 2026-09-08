##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# base.py – Intelligence strategy protocol and pluggable contract.
#
# Strategies are kept logically separate from the engine; the engine depends
# on this protocol only. New strategies implement this protocol and are
# registered with PolicyIntelligenceEngine (e.g. via register_strategy or constructor).
#
# Overlay keys by category:
#   risk -> overlay['risk_scores']
#   overlap -> overlay['overlaps']
#   cleanup -> overlay['cleanup_items'][check_id] (engine merges into cleanup_items)
#   consolidation_suggestion -> overlay['consolidations']
#   recommendation -> overlay['recommendations']
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from typing import Protocol

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository

# Categories for grouping in Settings and run order.
IntelligenceCategory = str  # 'risk' | 'overlap' | 'cleanup' | 'consolidation_suggestion' | 'recommendation'


class IntelligenceStrategy(Protocol):
    """
    Protocol for pluggable intelligence strategies.

    Implement this protocol in a separate module and register with
    PolicyIntelligenceEngine.register_strategy() or pass strategies= into the constructor.
    """

    strategy_id: str
    """Unique machine-readable id (e.g. for persistence and settings)."""

    display_name: str
    """Human-readable name shown in the UI (e.g. Settings checkboxes)."""

    category: str
    """One of: risk, overlap, cleanup, consolidation_suggestion, recommendation."""

    required_capabilities: frozenset[str]
    """Capabilities required when evaluating a partial CIS Compliance dataset."""

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        """Run this strategy and write results into overlay.

        Args:
            repo: Policy repository with policies, compartments, regular_statements, etc.
            overlay: Mutable dict to write results into (risk_scores, overlaps, cleanup_items, etc.).
            params: Optional params (e.g. where_clause_reduction_pct, engine reference for indexes).
        """
        ...
