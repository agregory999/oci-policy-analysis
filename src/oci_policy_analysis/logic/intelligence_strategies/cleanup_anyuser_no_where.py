##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# cleanup_anyuser_no_where.py – Any-user without where clause cleanup check.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class AnyuserNoWhereCheck:
    """Intelligence strategy: collect any-user statements with no where clause."""

    strategy_id: str = 'anyuser_no_where'
    display_name: str = 'Any-user without where'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        items = [
            st for st in repo.regular_statements if st.get('subject_type') == 'any-user' and not st.get('conditions')
        ]
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = items
