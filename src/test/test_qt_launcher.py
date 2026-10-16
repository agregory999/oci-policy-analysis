"""Check the optional Qt command without requiring a GUI or Qt installation."""

import builtins
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_console_entrypoint_preserves_existing_commands():
    scripts = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['scripts']
    assert scripts['oci-policy-analysis-qt'] == 'oci_policy_analysis.presentation.qt.launcher:main'
    assert scripts['oci-policy-analysis-ui'] == 'oci_policy_analysis.main:main'
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
