"""Static contract tests for related permission check UI hooks."""

from pathlib import Path

STATIC_DIR = Path('src/oci_policy_analysis/presentation/web/static')


def test_reference_data_page_renders_related_permission_checks() -> None:
    html = (STATIC_DIR / 'reference-data.html').read_text(encoding='utf-8')

    assert 'formatRelatedChecksText' in html
    assert 'related_checks' in html
    assert 'Related permission checks' in html


def test_simulation_history_renders_related_permission_checks() -> None:
    html = (STATIC_DIR / 'simulation.html').read_text(encoding='utf-8')

    assert 'formatRelatedPermissionChecksHtml' in html
    assert 'related_permission_checks' in html
