"""Top-level package for OCI Policy Analysis.

This package provides the main analysis, caching, and UI components.
"""

from ._version import get_app_version
from .cli import main as cli_main

try:
    from .mcp_server import main as mcp_main
except Exception:  # pragma: no cover - optional dependency (fastmcp)
    mcp_main = None


def __getattr__(name: str):
    """Lazily expose tkinter App to avoid importing GUI deps for web/CLI usage."""
    if name == 'App':
        from .main import App as _App

        return _App
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'cli_main',
    'get_app_version',
    'mcp_main',
    'App',
]
