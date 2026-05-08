##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_suggestion.py – Consolidation opportunity suggestion strategy.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class ConsolidationSuggestionStrategy:
    """Intelligence strategy: suggest policy consolidation opportunities."""

    strategy_id: str = 'consolidation_suggestion'
    display_name: str = 'Consolidation suggestions'
    category: str = 'consolidation_suggestion'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        params = params or {}
        engine = params.get('engine')
        if not engine:
            return
        engine.build_policy_consolidation()
