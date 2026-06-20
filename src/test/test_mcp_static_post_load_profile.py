"""Static contract tests for MCP post-load behavior."""

from pathlib import Path


def test_mcp_load_paths_use_minimal_post_load_profile() -> None:
    source = Path('src/oci_policy_analysis/mcp_server.py').read_text(encoding='utf-8')

    assert "load_from_cache(args.use_cache, post_load_profile='minimal')" in source
    assert source.count("post_load_profile='minimal'") >= 3
    assert 'run_post_load_pipeline(' not in source


def test_mcp_does_not_expose_permissions_report() -> None:
    source = Path('src/oci_policy_analysis/mcp_server.py').read_text(encoding='utf-8')
    tools_catalog = Path('src/oci_policy_analysis/application/core/resources/mcp_tools_list/mcp_tools.json').read_text(
        encoding='utf-8'
    )

    assert 'permissions_report' not in source
    assert 'permissions_report' not in tools_catalog
    assert 'permissions report' not in tools_catalog.lower()
