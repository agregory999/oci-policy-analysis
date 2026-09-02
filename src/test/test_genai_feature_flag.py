"""Regression coverage for the desktop OCI GenAI preview flag."""

from pathlib import Path
from types import SimpleNamespace

from oci_policy_analysis.main import App
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.policies_tab import PoliciesTab
from oci_policy_analysis.presentation.desktop.settings_tab import SettingsTab


def _source(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def test_base_tab_reads_the_app_genai_feature_flag() -> None:
    disabled_tab = SimpleNamespace(app=SimpleNamespace(genai_feature_enabled=False))
    enabled_tab = SimpleNamespace(app=SimpleNamespace(genai_feature_enabled=True))

    assert not BaseUITab.is_genai_feature_enabled(disabled_tab)
    assert BaseUITab.is_genai_feature_enabled(enabled_tab)


def test_genai_calls_and_pane_toggle_are_noops_when_feature_is_disabled() -> None:
    disabled_app = SimpleNamespace(genai_feature_enabled=False)

    App.toggle_bottom(disabled_app)
    App.ask_genai_async(disabled_app, 'Explain this policy')


def test_policies_ai_assist_handler_is_a_noop_when_feature_is_disabled() -> None:
    calls = []
    disabled_tab = SimpleNamespace(
        is_genai_feature_enabled=lambda: False,
        app=SimpleNamespace(toggle_bottom=lambda: calls.append('toggled')),
    )

    PoliciesTab._on_ai_assist_clicked(disabled_tab)

    assert calls == []


def test_settings_genai_methods_are_noops_when_feature_is_disabled() -> None:
    disabled_settings = SimpleNamespace(is_genai_feature_enabled=lambda: False)

    SettingsTab._refresh_model_table(disabled_settings)
    SettingsTab._on_ai_region_changed(disabled_settings)
    SettingsTab._load_subscribed_regions(disabled_settings)
    SettingsTab.apply_config(disabled_settings)
    SettingsTab._on_ai_enablement_finished(disabled_settings, True, 'unused')


def test_desktop_genai_controls_are_guarded_by_the_feature_flag() -> None:
    main_source = _source('src/oci_policy_analysis/main.py')
    settings_source = _source('src/oci_policy_analysis/presentation/desktop/settings_tab.py')

    assert "'--enable-genai'" in main_source
    assert 'self.genai_feature_enabled = enable_genai' in main_source
    assert 'if self.genai_feature_enabled:' in main_source
    assert 'if not self.is_genai_feature_enabled():' in settings_source

    for path in (
        'src/oci_policy_analysis/presentation/desktop/policies_tab.py',
        'src/oci_policy_analysis/presentation/desktop/policy_browser_tab.py',
        'src/oci_policy_analysis/presentation/desktop/dynamic_group_tab.py',
        'src/oci_policy_analysis/presentation/desktop/users_tab.py',
        'src/oci_policy_analysis/presentation/desktop/workload_principals_tab.py',
    ):
        source = _source(path)
        assert 'if self.is_genai_feature_enabled():' in source
        assert "text='AI Assist'" in source
