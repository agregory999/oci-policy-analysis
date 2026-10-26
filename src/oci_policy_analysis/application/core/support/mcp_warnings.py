"""Narrow warning compatibility for the tested FastMCP dependency stack."""

import warnings


def configure_mcp_dependency_warnings() -> None:
    """Hide two known Authlib deprecations before importing FastMCP.

    Importing Authlib's warning category first installs its own default filter.
    Exact message filters then leave other deprecations and runtime warnings
    visible. Call only when MCP dependencies are required; this imports Authlib.
    """
    from authlib.deprecate import AuthlibDeprecationWarning

    for message in (
        r'\Aauthlib\.jose module is deprecated, please use joserfc instead\.'
        r'\nIt will be compatible before version 2\.0\.0\.\Z',
        r'\AThe httpx module is deprecated; please use httpx2 instead\.\Z',
    ):
        warnings.filterwarnings('ignore', message=message, category=AuthlibDeprecationWarning)
