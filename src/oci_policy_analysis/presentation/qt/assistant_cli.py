"""Locate assistant CLIs and build their child environments on macOS and Windows.

Desktop apps launched from Finder, the Start menu or a shortcut do not inherit the
interactive shell's PATH, so Homebrew, npm and ~/.local installs can be invisible.
This module adds the usual install directories and, on Windows, maps an npm
``.cmd`` shim to the native binary it wraps. Shims run through cmd.exe, which
cannot pass the JSON-heavy arguments these adapters use.
"""

import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QProcessEnvironment

_SECRET_VARIABLES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'CODEX_API_KEY')
_SHIM_SUFFIXES = frozenset({'.cmd', '.bat', '.ps1'})


def search_directories(platform: str = sys.platform, home: Path | None = None) -> list[str]:
    """Return existing install directories to append after the inherited PATH.

    Args:
        platform: ``sys.platform`` value; selects macOS, Windows or other POSIX paths.
        home: Home directory override for tests; defaults to the operator's home.

    Returns:
        list[str]: Existing directories, in preference order, without duplicates.
    """
    home = home or Path.home()
    candidates = [home / '.local' / 'bin', home / '.npm-global' / 'bin', home / '.volta' / 'bin']
    if platform == 'win32':
        appdata = os.environ.get('APPDATA')
        candidates.insert(0, Path(appdata) / 'npm' if appdata else home / 'AppData' / 'Roaming' / 'npm')
    else:
        candidates[:0] = [Path('/opt/homebrew/bin'), Path('/usr/local/bin')]
    return [str(path) for path in dict.fromkeys(candidates) if path.is_dir()]


def search_path(platform: str = sys.platform, home: Path | None = None) -> str:
    """Return the inherited PATH followed by existing install directories."""
    inherited = [entry for entry in os.environ.get('PATH', '').split(os.pathsep) if entry]
    extra = [entry for entry in search_directories(platform, home) if entry not in inherited]
    return os.pathsep.join(inherited + extra)


def _windows_native_binary(shim: Path, name: str) -> Path | None:
    """Find the native exe that an npm shim launches, when the package is present."""
    if name != 'codex':
        return None
    # npm installs the platform package under the shim's node_modules; both nested and hoisted layouts occur.
    modules = shim.parent / 'node_modules'
    for pattern in (
        '@openai/codex/node_modules/@openai/codex-win32-*/vendor/*-windows-msvc/bin/codex.exe',
        '@openai/codex-win32-*/vendor/*-windows-msvc/bin/codex.exe',
    ):
        found = next(iter(sorted(modules.glob(pattern))), None)
        if found is not None and found.is_file():
            return found
    return None


def resolve_executable(
    executable: str, *, platform: str = sys.platform, home: Path | None = None
) -> tuple[Path | None, str]:
    """Resolve a CLI name or path to a program that QProcess can start directly.

    Args:
        executable: Name on PATH or an absolute path, without arguments.
        platform: ``sys.platform`` value; tests pass ``win32`` to exercise shim mapping.
        home: Home directory override for tests.

    Returns:
        tuple[Path | None, str]: Program path, or None with a user-facing reason.
    """
    name = executable.strip().strip('"')
    if not name:
        return None, 'No executable was selected.'
    candidate = Path(name).expanduser()
    if candidate.is_file():
        program = candidate
    else:
        found = shutil.which(name, path=search_path(platform, home))
        if found is None:
            return None, f'{name} not found. Install the CLI or select its executable.'
        program = Path(found)
    if platform == 'win32' and program.suffix.lower() in _SHIM_SUFFIXES:
        native = _windows_native_binary(program, Path(name).stem)
        if native is None:
            return None, (
                f'{program.name} is a script shim, which cannot run with the required arguments. '
                'Select the CLI native executable (for Codex: the codex.exe inside its npm platform package).'
            )
        program = native
    return program, ''


def child_environment(program: Path, *, platform: str = sys.platform, home: Path | None = None) -> QProcessEnvironment:
    """Build the inherited environment with install directories and bundled helpers on PATH.

    Args:
        program: Resolved executable; its bundled ``codex-path`` helpers are added when present.
        platform: ``sys.platform`` value.
        home: Home directory override for tests.

    Returns:
        QProcessEnvironment: Environment for the child process.
    """
    environment = QProcessEnvironment.systemEnvironment()
    helpers = program.parents[1] / 'codex-path' if len(program.parents) > 1 else None
    entries = [str(helpers)] if helpers is not None and helpers.is_dir() else []
    path = search_path(platform, home)
    environment.insert('PATH', os.pathsep.join(entries + [path]) if entries else path)
    return environment


def redact_secrets(text: str) -> str:
    """Remove API key values and key-shaped tokens from text that may be logged or shown.

    Args:
        text: Diagnostic text from a child process or protocol error.

    Returns:
        str: Text with known secret values and ``sk-`` tokens replaced, truncated to 500 characters.
    """
    for name in _SECRET_VARIABLES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, '[redacted]')
    return re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)[:500]


def billing_variables(environment: QProcessEnvironment, names: tuple[str, ...]) -> str:
    """Name the API-key variables present in a child environment, or the CLI login if none are set."""
    present = [name for name in names if environment.contains(name)]
    return ', '.join(present) if present else 'CLI login'
