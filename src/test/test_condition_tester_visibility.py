import inspect

from oci_policy_analysis.main import App
from oci_policy_analysis.presentation.desktop.console_tab import ConsoleTab
from oci_policy_analysis.presentation.desktop.settings_tab import SettingsTab
from oci_policy_analysis.presentation.desktop.workload_principals_tab import WorkloadPrincipalsTab


def test_condition_tester_is_not_in_advanced_toggle():
    source = inspect.getsource(SettingsTab._toggle_advanced_tabs)

    assert 'condition_tester_tab' not in source
    assert 'Condition Tester\\n(Advanced)' not in source


def test_condition_tester_main_tab_label_is_not_advanced():
    source = inspect.getsource(App.__init__)

    assert "self.notebook.add(self.condition_tester_tab, text='Condition\\nTester')" in source
    assert 'self.notebook.forget(self.condition_tester_tab)' not in source
    assert 'Condition Tester\\n(Advanced)' not in source


def test_workload_principals_any_style_rows_can_open_condition_tester():
    source = inspect.getsource(WorkloadPrincipalsTab._build_ui)

    assert 'View in Condition Tester Tab' in source
    assert "self.principals_style_var.get() in ('any-user', 'any-group', 'any-user / any-group')" in source


def test_workload_principals_filters_place_text_search_above_oke_controls():
    source = inspect.getsource(WorkloadPrincipalsTab._build_ui)

    assert "Text Filter:'" in source
    assert 'grid(row=0, column=2' in source
    assert 'grid(row=0, column=5' in source
    assert "OKE Service Account:'" in source
    assert 'grid(row=2, column=2' in source
    assert "OKE Cluster OCID:'" in source
    assert 'grid(row=2, column=4' in source


def test_console_tab_uses_current_logger_names_only():
    source = inspect.getsource(ConsoleTab._build_ui)

    assert 'internal.console_tab' not in source
    assert 'ui.main' not in source
    assert 'mcp.server' not in source
    assert 'resource_principals_tab' not in source
    assert "permissions_report'" not in source
    assert 'workload_principals_tab' in source
    assert 'permissions_report_tab' in source
    assert 'limits_tab' in source
    assert 'presentation.desktop.console_tab' in source
    assert 'web_routes' in source
    assert 'web_auth' in source
