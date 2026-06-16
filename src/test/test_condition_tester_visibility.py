import inspect

from oci_policy_analysis.main import App
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
