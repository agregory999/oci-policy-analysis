"""Check terminal dialog behavior without starting a Tk event loop."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from oci_policy_analysis.presentation.tk.main import App


@pytest.mark.parametrize('success', [True, False])
def test_loading_popup_success_autocloses_failure_requires_dismiss(success):
    scheduled = []
    dialog, bar, button = Mock(), Mock(), Mock()
    app = SimpleNamespace(
        after=lambda delay, callback: scheduled.append((delay, callback)),
        _policy_reload_dialog=dialog,
        _policy_reload_progressbar=bar,
        _policy_reload_dismiss_button=button,
        _set_policy_reload_progress_message=Mock(),
        _close_policy_reload_progress_dialog=Mock(),
    )
    App._finalize_operation_popup(app, True, success, 'A long final diagnostic')
    assert scheduled[0][0] == 0
    scheduled.pop(0)[1]()
    bar.stop.assert_called_once()
    app._set_policy_reload_progress_message.assert_called_once_with('A long final diagnostic')
    if success:
        assert scheduled == [(2200, app._close_policy_reload_progress_dialog)]
        button.pack.assert_not_called()
    else:
        assert scheduled == []
        button.pack.assert_called_once()
        button.focus_set.assert_called_once()
        dialog.protocol.assert_called_once_with('WM_DELETE_WINDOW', app._close_policy_reload_progress_dialog)
