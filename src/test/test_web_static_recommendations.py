"""Static contract tests for the recommendations page."""

from pathlib import Path


def _page_html() -> str:
    return Path('src/oci_policy_analysis/presentation/web/static/recommendations.html').read_text(encoding='utf-8')


def test_recommendations_page_has_summary_filters_action_details_and_taller_table() -> None:
    page_html = _page_html()

    assert 'summarySeverityFilter' in page_html
    assert 'summaryCategoryFilter' in page_html
    assert 'summary_counts' in page_html
    assert '<th>Action Detail</th>' in page_html
    assert "['Recommendation', 'Priority', 'Category', 'Notes', 'Action', 'ActionDetail']" in page_html
    assert 'max-height: 520px' in page_html


def test_recommendations_page_has_context_menu_destinations() -> None:
    page_html = _page_html()

    assert "tr.addEventListener('contextmenu'" in page_html
    assert 'recommendationContextMenu' in page_html
    assert 'contextActionsForRow' in page_html
    assert 'policyFilterUrl' in page_html
    assert '/policy-analysis.html?' in page_html
    assert '/dynamic-group-analysis.html?' in page_html
    assert '/workload-principals-analysis.html?' in page_html
    assert '/users-groups-analysis.html?' in page_html
    assert 'cardOverlap' not in page_html
    assert 'overlapTable' not in page_html
    assert 'window.location.href = action.url' in page_html


def test_recommendations_page_renders_supersession_with_structured_fly_in() -> None:
    page_html = _page_html()

    assert 'cardSupersession' in page_html
    assert 'supersessionTable' in page_html
    assert 'formatSupersessionDetail' in page_html
    assert "tableId === 'supersessionTable'" in page_html
    assert 'payload.supersession || []' in page_html


def test_target_pages_accept_navigation_filters() -> None:
    policy_html = Path('src/oci_policy_analysis/presentation/web/static/policy-analysis.html').read_text(
        encoding='utf-8'
    )
    dg_html = Path('src/oci_policy_analysis/presentation/web/static/dynamic-group-analysis.html').read_text(
        encoding='utf-8'
    )
    workload_html = Path('src/oci_policy_analysis/presentation/web/static/workload-principals-analysis.html').read_text(
        encoding='utf-8'
    )
    users_groups_html = Path('src/oci_policy_analysis/presentation/web/static/users-groups-analysis.html').read_text(
        encoding='utf-8'
    )

    assert 'applyInboundFilterFromUrl' in policy_html
    assert "params.get('filter')" in policy_html
    assert 'applyInboundFiltersFromUrl' in dg_html
    assert "params.get('dynamic_group_ocid')" in dg_html
    assert 'applyInboundFiltersFromUrl' in workload_html
    assert "params.get('workload_namespace')" in workload_html
    assert 'applyInboundFiltersFromUrl' in users_groups_html
    assert "params.get('search')" in users_groups_html
