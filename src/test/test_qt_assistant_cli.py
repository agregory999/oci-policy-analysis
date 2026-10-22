"""Cross-platform resolution for embedded assistant CLIs."""

from pathlib import Path

import pytest

pytest.importorskip('PySide6')

from oci_policy_analysis.presentation.qt.assistant_cli import (  # noqa: E402
    billing_variables,
    child_environment,
    redact_secrets,
    resolve_executable,
    search_directories,
)

NATIVE = Path('node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin')


def _npm_install(root: Path) -> tuple[Path, Path]:
    shim = root / 'npm' / 'codex.cmd'
    shim.parent.mkdir(parents=True)
    shim.write_text('@echo off\r\n', encoding='utf-8')
    native = shim.parent / NATIVE / 'codex.exe'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'MZ')
    return shim, native


def test_windows_npm_shim_resolves_to_the_native_codex_binary(tmp_path):
    shim, native = _npm_install(tmp_path)

    program, reason = resolve_executable(str(shim), platform='win32')

    assert program == native and reason == ''


def test_windows_shim_without_native_package_explains_what_to_select(tmp_path):
    shim = tmp_path / 'codex.cmd'
    shim.write_text('@echo off\r\n', encoding='utf-8')

    program, reason = resolve_executable(str(shim), platform='win32')

    assert program is None
    assert 'script shim' in reason and 'codex.exe' in reason


def test_claude_shim_is_not_silently_replaced(tmp_path):
    shim = tmp_path / 'claude.cmd'
    shim.write_text('@echo off\r\n', encoding='utf-8')

    program, reason = resolve_executable(str(shim), platform='win32')

    assert program is None and 'Select the CLI native executable' in reason


def test_missing_executable_reports_not_found_on_every_platform(tmp_path):
    program, reason = resolve_executable(str(tmp_path / 'absent-codex'), platform='darwin', home=tmp_path)

    assert program is None and 'not found' in reason


def test_install_directories_are_added_only_when_they_exist(tmp_path):
    (tmp_path / '.local' / 'bin').mkdir(parents=True)
    (tmp_path / '.npm-global' / 'bin').mkdir(parents=True)

    found = search_directories('darwin', home=tmp_path)

    assert str(tmp_path / '.local' / 'bin') in found
    assert str(tmp_path / '.npm-global' / 'bin') in found
    assert str(tmp_path / '.volta' / 'bin') not in found


def test_child_environment_puts_bundled_codex_helpers_first(tmp_path):
    _, native = _npm_install(tmp_path)
    helpers = native.parents[1] / 'codex-path'
    helpers.mkdir()

    environment = child_environment(native, platform='win32', home=tmp_path)

    assert environment.value('PATH').split(';')[0] == str(helpers)


def test_billing_source_names_api_key_variables_or_the_cli_login(monkeypatch):
    from PySide6.QtCore import QProcessEnvironment

    environment = QProcessEnvironment()
    assert billing_variables(environment, ('OPENAI_API_KEY', 'CODEX_API_KEY')) == 'CLI login'
    environment.insert('OPENAI_API_KEY', 'sk-test')
    assert billing_variables(environment, ('OPENAI_API_KEY', 'CODEX_API_KEY')) == 'OPENAI_API_KEY'


def test_redaction_removes_known_secret_values_and_key_shaped_tokens(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'live-value-123')

    text = redact_secrets('auth failed for live-value-123 and sk-abcDEF_12 at login')

    assert 'live-value-123' not in text and 'sk-abcDEF' not in text
    assert text.count('[redacted]') == 2
