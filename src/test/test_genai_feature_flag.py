"""Regression coverage for removing the desktop OCI GenAI integration."""

import inspect

import pytest

from oci_policy_analysis import main as desktop
from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.presentation.desktop.settings_tab import SettingsTab


def test_removed_genai_flag_is_rejected_before_gui_startup(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['oci-policy-analysis-ui', '--enable-genai'])
    monkeypatch.setattr(desktop, 'App', lambda **kwargs: pytest.fail('GUI must not start'))
    with pytest.raises(SystemExit) as error:
        desktop.main()
    assert error.value.code == 2
    assert 'unrecognized arguments: --enable-genai' in capsys.readouterr().err


def test_desktop_and_context_have_no_genai_configuration_contract():
    assert 'enable_genai' not in inspect.signature(desktop.App).parameters
    assert 'ai_repo' not in inspect.signature(SettingsTab).parameters
    assert 'ai' not in AppContext.__dataclass_fields__
