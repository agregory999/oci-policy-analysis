##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# cleanup_statements_too_open.py – Overly broad statements cleanup check.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository

LOCKED_POLICY_NAME = 'Tenant Admin Policy'


@dataclass(frozen=True)
class StatementsTooOpenCheck:
    """Intelligence strategy: collect overly broad manage all-resources statements."""

    strategy_id: str = 'statements_too_open'
    display_name: str = 'Overly broad statements'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        too_open = [
            st
            for st in repo.regular_statements
            if (
                st.get('verb', '').lower() == 'manage'
                and st.get('resource', '').lower() == 'all-resources'
                and st.get('policy_name', '') != LOCKED_POLICY_NAME
            )
        ]
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = too_open
