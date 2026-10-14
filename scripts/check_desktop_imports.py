"""Verify desktop and embedded MCP imports before freezing release executables."""

from importlib.metadata import version


def main() -> None:
    """Import the desktop/MCP startup chain and exercise typed tool metadata."""
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata

    import oci_policy_analysis.main

    def smoke_tool(value: str) -> str:
        return value

    metadata = func_metadata(smoke_tool)
    assert metadata.arg_model.model_validate({'value': 'smoke'}).value == 'smoke'
    assert oci_policy_analysis.main.App is not None
    print(
        'Desktop startup imports passed: '
        + ', '.join(f'{name}={version(name)}' for name in ('pydantic', 'mcp', 'fastmcp'))
    )


if __name__ == '__main__':
    main()
