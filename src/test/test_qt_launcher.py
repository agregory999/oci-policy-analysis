"""Check the optional Qt command without requiring a GUI or Qt installation."""

import builtins
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_console_entrypoint_preserves_existing_commands():
    scripts = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['scripts']
    assert scripts['oci-policy-analysis-legacy-ui'] == 'oci_policy_analysis.presentation.tk.main:main'
    assert scripts['oci-policy-analysis-ui'] == 'oci_policy_analysis.presentation.qt.launcher:main'
    assert scripts['oci-policy-analysis-cli'] == 'oci_policy_analysis.cli:main'
    assert scripts['oci-policy-analysis-web'] == 'oci_policy_analysis.presentation.web.main:main'
    assert scripts['oci-policy-analysis-mcp'] == 'oci_policy_analysis.mcp_server:main'


def test_launcher_explains_missing_qt_without_masking_other_import_errors():
    # Use a fresh interpreter so Qt modules cached by other tests cannot hide
    # accidental eager imports. A basic logger prevents operator log-file access.
    code = """
import builtins, logging, sys
logging.basicConfig()
original = builtins.__import__
def without_qt(name, *args, **kwargs):
    if name == 'PySide6' or name.startswith('PySide6.'):
        raise ModuleNotFoundError("No module named 'PySide6'", name='PySide6')
    return original(name, *args, **kwargs)
builtins.__import__ = without_qt
from oci_policy_analysis.presentation.qt.launcher import main
assert not any(name.startswith('PySide6') for name in sys.modules)
sys.exit(main([]))
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 2, result.stderr
    assert 'pip install "oci-policy-analysis[qt]"' in result.stderr
    assert 'Traceback' not in result.stderr


def test_launcher_does_not_hide_an_unrelated_missing_dependency(monkeypatch):
    from oci_policy_analysis.presentation.qt.launcher import main

    original = builtins.__import__

    def missing_dependency(name, *args, **kwargs):
        if name == 'main' and kwargs.get('level', args[3] if len(args) > 3 else 0) == 1:
            raise ModuleNotFoundError('Missing backend dependency', name='some_backend_dependency')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing_dependency)
    import pytest

    with pytest.raises(ModuleNotFoundError, match='Missing backend dependency'):
        main([])


def test_launcher_destroys_widgets_before_return_and_handles_sigint(tmp_path):
    """Exercise real event loops and interpreter exit outside pytest's shared app."""
    code = r"""
import logging, os, signal, sys
from pathlib import Path
logging.basicConfig()
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import QTimer
from shiboken6 import isValid
from oci_policy_analysis.application.core.support import caching, config
from oci_policy_analysis.presentation.qt import main as ui
root = Path(sys.argv[1])
caching.CACHE_DIR = root / 'cache'
config.SETTINGS_PATH = str(root / 'settings.json')
original = ui.WorkbenchWindow
windows = []
class Window(original):
    def __init__(self, **kwargs):
        super().__init__(**{**kwargs, 'record_usage': False})
        windows.append(self)
        if sys.argv[2].startswith('loaded-'):
            sys.path.insert(0, sys.argv[3])
            from qt_compact_sample import sample_snapshot
            from oci_policy_analysis.presentation.qt import loading
            loading.sample_snapshot = sample_snapshot
            self.settings_page.load_sample()
        QTimer.singleShot(100, self.finish)

    def finish(self):
        if self.controller.worker is not None:
            QTimer.singleShot(100, self.finish)
        elif sys.argv[2].endswith('button'):
            self.close()
        else:
            os.kill(os.getpid(), signal.SIGINT)
ui.WorkbenchWindow = Window
previous = signal.getsignal(signal.SIGINT)
assert ui.main([]) == 0
assert signal.getsignal(signal.SIGINT) == previous
assert len(windows) == 1 and not isValid(windows[0])
print('CLEAN_EXIT')
"""
    for mode in ('button', 'sigint', 'loaded-button', 'loaded-sigint'):
        result = subprocess.run(
            [sys.executable, '-c', code, str(tmp_path), mode, str(ROOT / 'src' / 'test')],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert 'CLEAN_EXIT' in result.stdout
