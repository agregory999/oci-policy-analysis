"""Launch a separately configured desktop assistant without a chat protocol."""

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices

_DESKTOP_NAMES = {
    'claude-desktop': 'Claude',
    'chatgpt-desktop': 'ChatGPT',
    'codex-desktop': 'Codex',
}


def _launch_desktop_assistant(provider: str, application: str) -> bool:
    """Open an application or Windows shortcut, without arguments or config edits.

    An empty value discovers common installations. A successful return means
    the OS accepted the launch, not that the assistant connected to MCP. The external
    application is detached and remains open when the workbench closes.
    """
    if provider not in _DESKTOP_NAMES:
        return False
    application = application.strip().strip('"')
    if not application or application.casefold() == provider:
        if sys.platform == 'darwin':
            return QProcess.startDetached('/usr/bin/open', ['-a', _DESKTOP_NAMES[provider]])[0]
        # Claude Code also installs claude.exe; never infer Desktop from that
        # ambiguous PATH entry. Desktop's known install paths are separate.
        candidates = []
        if sys.platform == 'win32' and provider == 'claude-desktop':
            local = os.environ.get('LOCALAPPDATA')
            if local:
                candidates.extend(
                    str(Path(local) / relative)
                    for relative in ('AnthropicClaude/claude.exe', 'Programs/Claude/Claude.exe')
                )
        candidates.append(shutil.which(provider))
        application = next((value for value in candidates if value and Path(value).is_file()), '')
    if not application:
        return False
    path = Path(application).expanduser()
    if sys.platform == 'win32' and path.suffix.casefold() == '.lnk':
        return path.is_file() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
    if sys.platform == 'darwin' and path.suffix.casefold() == '.app':
        return path.is_dir() and QProcess.startDetached('/usr/bin/open', [str(path.resolve())])[0]
    program = str(path.resolve()) if path.is_file() else shutil.which(application)
    return bool(program) and QProcess.startDetached(program, [])[0]
