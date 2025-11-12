"""Top-level package for OCI Policy Analysis.

This package provides the main analysis, caching, and UI components.
"""

from .cli import main as cli_main
from .main import App as ui_main
from .mcp_server import main as mcp_main

__all__ = [
    'cli_main',
    'mcp_main',
    'ui_main',
]
