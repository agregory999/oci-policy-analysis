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
BROAD_ALLOW_VERBS = frozenset({'manage', 'use'})
BROAD_DENY_VERBS = frozenset({'manage', 'read', 'inspect'})


def is_overly_broad_statement(statement: dict) -> bool:
    """Return whether an all-resources statement merits a scope review.

    Broad allows are limited to ``use`` and ``manage all-resources``. Broad
    denies of ``inspect``, ``read``, or ``manage all-resources`` can disable a
    principal across the effective path, so they are also surfaced for review.
    """
    if str(statement.get('resource') or '').strip().casefold() != 'all-resources':
        return False
    if str(statement.get('policy_name') or '').strip() == LOCKED_POLICY_NAME:
        return False

    action = str(statement.get('action') or 'allow').strip().casefold()
    verb = str(statement.get('verb') or '').strip().casefold()
    if action == 'deny':
        return verb in BROAD_DENY_VERBS
    return verb in BROAD_ALLOW_VERBS


@dataclass(frozen=True)
class StatementsTooOpenCheck:
    """Collect broad all-resources allows and denies for scope review."""

    strategy_id: str = 'statements_too_open'
    display_name: str = 'Overly broad statements'
    category: str = 'cleanup'

    def run(
        self,
        repo: PolicyAnalysisRepository,
        overlay: dict,
        params: dict | None = None,
    ) -> None:
        too_open = [st for st in repo.regular_statements if is_overly_broad_statement(st)]
        overlay.setdefault('cleanup_items', {})[self.strategy_id] = too_open
