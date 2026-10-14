"""Validation for standalone MCP operational environment settings."""

import os


def mcp_domain_search_depth():
    """MCP has one depth variable; desktop/web preferences remain in saved settings."""
    raw = os.environ.get('MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH', '1')
    if not raw.isdigit() or not 1 <= int(raw) <= 6:
        raise ValueError('MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH must be 1 through 6')
    return int(raw)
