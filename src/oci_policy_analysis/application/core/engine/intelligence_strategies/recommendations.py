##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# recommendations.py – Overall recommendations intelligence strategy.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class OverallRecommendationStrategy:
    """Intelligence strategy: build overall recommendations from cleanup, consolidation, etc."""

    strategy_id: str = 'recommendations'
    display_name: str = 'Overall recommendations'
    category: str = 'recommendation'

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
        engine.build_overall_recommendations(params=params)
