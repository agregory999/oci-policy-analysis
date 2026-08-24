"""Static and route contracts for the reports page."""

from types import SimpleNamespace

from oci_policy_analysis.presentation.web.api import routes_core


def test_reports_page_has_on_demand_json_download() -> None:
    """The reports page exposes the first JSON overlap report."""
    page = open('src/oci_policy_analysis/presentation/web/static/reports.html', encoding='utf-8').read()

    assert 'runOverlapReport' in page
    assert 'downloadOverlapReport' in page
    assert "'/reports/' + reportTypeNode.value" in page
    assert 'reportFormat' in page
    assert 'markdown' in page
    assert 'policy-inventory' in page
    assert 'permissions' in page
    assert 'supersession' in page
    assert 'completionMessage' in page
    assert page.index('value="full-overlaps"') > page.index('value="supersession"')


def test_full_overlap_route_delegates_to_reports_service(monkeypatch) -> None:
    """The web route delegates report generation through its application service."""

    class Service:
        def __init__(self, _context) -> None:
            pass

        def get_overlap_report(self) -> dict:
            return {'report_id': 'full-overlaps'}

        def with_rendered_formats(self, report: dict) -> dict:
            return report

    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace())
    monkeypatch.setattr(routes_core, 'ReportsService', Service)

    assert routes_core.get_full_overlap_report() == {'report_id': 'full-overlaps'}
