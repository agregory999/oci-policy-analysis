"""Regression coverage for identity diagnostics in desktop troubleshooting views."""

from __future__ import annotations

from types import SimpleNamespace

from oci_policy_analysis.application.core.common.policy_helpers import render_diagnostic_text
from oci_policy_analysis.presentation.desktop.debugger_tab import DebuggerTab
from oci_policy_analysis.presentation.desktop.users_tab import GROUPS_ALL_COLUMNS, render_diagnostic_name


def test_group_diagnostic_name_shows_a_zero_width_space() -> None:
    assert 'Diagnostic Name' in GROUPS_ALL_COLUMNS
    assert render_diagnostic_name('NetworkAdmins\u200b') == 'NetworkAdmins[U+200B ZERO WIDTH SPACE]'
    assert render_diagnostic_text('NetworkAdmins\u200b') == 'NetworkAdmins[U+200B ZERO WIDTH SPACE]'


def test_debugger_exposes_policy_repo_groups_and_dynamic_groups() -> None:
    repository = SimpleNamespace(
        groups=[{'group_name': 'NetworkAdmins\u200b'}],
        dynamic_groups=[{'dynamic_group_name': 'BuildAgents'}],
    )
    debugger = DebuggerTab.__new__(DebuggerTab)
    debugger.app = SimpleNamespace(policy_compartment_analysis=repository)

    debugger.source_var = SimpleNamespace(get=lambda: 'Policy Repo Groups')
    assert debugger._get_source_data() == repository.groups

    debugger.source_var = SimpleNamespace(get=lambda: 'Policy Repo Dynamic Groups')
    assert debugger._get_source_data() == repository.dynamic_groups
