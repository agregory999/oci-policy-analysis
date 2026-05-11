##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# overlap.py – Policy overlap intelligence strategy.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class OverlapStrategy:
    """Intelligence strategy: analyze policy statement overlaps."""

    strategy_id: str = 'overlap'
    display_name: str = 'Policy overlap'
    category: str = 'overlap'

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
        engine.analyze_policy_overlap()
