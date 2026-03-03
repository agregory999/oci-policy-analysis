##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# risk.py – Risk score intelligence strategy.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class RiskScoreStrategy:
    """Intelligence strategy: calculate potential risk scores for policy statements."""

    strategy_id: str = 'risk_scores'
    display_name: str = 'Risk scores'
    category: str = 'risk'

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
        where_pct = params.get('where_clause_reduction_pct', 50)
        svc_pct = params.get('service_principal_reduction_pct', 50)
        engine.calculate_potential_risk_scores(
            where_clause_reduction_pct=where_pct,
            service_principal_reduction_pct=svc_pct,
        )
