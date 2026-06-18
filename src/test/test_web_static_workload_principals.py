from pathlib import Path

STATIC_DIR = Path('src/oci_policy_analysis/presentation/web/static')


def test_workload_principals_static_page_is_linked_by_current_name():
    assert (STATIC_DIR / 'workload-principals-analysis.html').exists()
    assert not (STATIC_DIR / 'resource-principals-analysis.html').exists()

    index_html = (STATIC_DIR / 'index.html').read_text()
    limited_home_html = (STATIC_DIR / 'limited-home.html').read_text()

    assert '/workload-principals-analysis.html' in index_html
    assert '/workload-principals-analysis.html' in limited_home_html
    assert '/resource-principals-analysis.html' not in index_html
    assert '/resource-principals-analysis.html' not in limited_home_html


def test_workload_principals_page_has_auto_apply_filter_layout():
    page_html = (STATIC_DIR / 'workload-principals-analysis.html').read_text()

    assert 'id="runBtn"' not in page_html
    assert "getElementById('runBtn')" not in page_html
    assert 'workload-principals-filter-grid' in page_html
    assert 'workload-filter-type' in page_html
    assert 'workload-filter-text' in page_html
    assert 'workload-filter-clear' in page_html
    assert "textFilterEl.addEventListener('input', ()=>{ if (!isDynamicGroupMode()) loadPolicies(); });" in page_html
    assert "const resp = await fetch('/entities/dynamic-groups');" in page_html


def test_workload_principals_results_can_send_conditions_to_tester():
    page_html = (STATIC_DIR / 'workload-principals-analysis.html').read_text()

    assert 'id="policyContextMenu"' in page_html
    assert 'id="sendConditionToTesterBtn"' in page_html
    assert "tr.addEventListener('contextmenu'" in page_html
    assert 'function conditionTextForRow(row)' in page_html
    assert 'sessionStorage.setItem(CONDITION_TESTER_STORAGE_KEY, conditionText);' in page_html
    assert "window.location.href = '/condition-tester.html?from=workload-principals-analysis';" in page_html
