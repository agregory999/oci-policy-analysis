##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# cleanup_invalid.py – Invalid statements cleanup check.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class InvalidStatementsCheck:
    """Intelligence strategy: collect invalid policy statements for cleanup."""

    strategy_id: str = 'invalid_statements'
    display_name: str = 'Invalid statements'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        invalid = [st for st in repo.regular_statements if st.get('invalid_reasons')]
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = invalid
