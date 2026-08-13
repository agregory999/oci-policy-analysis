"""Tests for on-demand report generation."""

from types import SimpleNamespace

from oci_policy_analysis.application.services.reports_service import ReportsService


def test_full_overlap_report_runs_analysis_only_when_requested() -> None:
    """The report service invokes the existing overlap analyzer on demand."""

    class Engine:
        def __init__(self) -> None:
            self.overlay = {'overlaps': []}
            self.calls = 0

        def analyze_policy_overlap(self) -> None:
            self.calls += 1
            self.overlay['overlaps'] = [{'statement_internal_id': 'one', 'overlaps': [{'confidence': 'high'}]}]

    engine = Engine()
    service = ReportsService(
        SimpleNamespace(
            intelligence=engine,
            policy_repo=SimpleNamespace(data_as_of='2026-08-13', regular_statements=[{'internal_id': 'one'}]),
        )
    )

    report = service.get_overlap_report()

    assert engine.calls == 1
    assert report['report_id'] == 'full-overlaps'
    assert report['findings'][0]['candidate'] == {'internal_id': 'one'}


def test_report_markdown_is_rendered_from_native_json() -> None:
    """Markdown and HTML renderings are generated from the report payload."""
    service = ReportsService.__new__(ReportsService)
    report = {
        'title': 'Full Policy Overlap Report',
        'generated_at': '2026-08-13',
        'finding_count': 1,
        'findings': [
            {
                'candidate': {
                    'policy_name': 'Candidate',
                    'effective_path': 'ROOT/A',
                    'statement_text': 'allow group Devs',
                },
                'overlaps': [
                    {'superseded_by': 'Evidence', 'confidence': 'High', 'permission_overlap': ['BUCKET_READ']}
                ],
            }
        ],
    }

    rendered = service.with_rendered_formats(report)

    assert '# Full Policy Overlap Report' in rendered['markdown']
    assert '<h1>Full Policy Overlap Report</h1>' in rendered['markdown_html']


def test_policy_inventory_report_uses_loaded_statements() -> None:
    """Policy inventory is grouped as compartments, policies, tags, and statements."""
    service = ReportsService(
        SimpleNamespace(
            policy_repo=SimpleNamespace(
                data_as_of='2026-08-13',
                compartments=[
                    {
                        'id': 'compartment-a',
                        'name': 'A',
                        'path': 'inaccurate-path',
                        'hierarchy_path': 'ROOT/A',
                        'tags': {'Owner': 'Platform'},
                    }
                ],
                policies=[
                    {
                        'policy_ocid': 'policy-a',
                        'policy_name': 'Inventory',
                        'compartment_ocid': 'compartment-a',
                        'tags': {'Purpose': 'Testing'},
                    }
                ],
                regular_statements=[
                    {
                        'policy_name': 'Inventory',
                        'policy_ocid': 'policy-a',
                        'compartment_ocid': 'compartment-a',
                        'statement_text': 'allow group Devs to inspect buckets in compartment A',
                    }
                ],
            )
        )
    )

    report = service.get_policy_inventory_report()

    assert report['report_id'] == 'policy-inventory'
    assert report['findings'] == [
        {
            'name': 'A',
            'path': 'ROOT/A',
            'ocid': 'compartment-a',
            'tags': {'Owner': 'Platform'},
            'policies': [
                {
                    'name': 'Inventory',
                    'ocid': 'policy-a',
                    'tags': {'Purpose': 'Testing'},
                    'statements': ['allow group Devs to inspect buckets in compartment A'],
                }
            ],
        }
    ]
    assert report['counts'] == {'compartments': 1, 'policies': 1, 'statements': 1}
    markdown = service.to_markdown(report)
    assert '## Compartment: ROOT/A' in markdown
    assert '### Policy: Inventory' in markdown
    assert 'OCID: compartment-a  ' in markdown
    assert 'OCID: policy-a  ' in markdown
    rendered_html = service.with_rendered_formats(report)['markdown_html']
    assert 'OCID: compartment-a<br' in rendered_html
    assert 'OCID: policy-a<br' in rendered_html
    assert 'Tags: Owner: Platform' in markdown
    assert '    allow group Devs to inspect buckets in compartment A' in markdown
    assert (
        '<pre style="font-family: courier"><code style="font-family: courier">'
        'allow group Devs to inspect buckets in compartment A' in service.with_rendered_formats(report)['markdown_html']
    )
    assert 'internal_id' not in str(report)


def test_permissions_report_uses_effective_grant_rows_as_its_item_count() -> None:
    """Effective permissions reports count grant rows rather than wrapper objects."""
    service = ReportsService(
        SimpleNamespace(
            policy_repo=SimpleNamespace(data_as_of='2026-08-13'),
            intelligence=SimpleNamespace(
                permissions_report={
                    'report': {},
                    'grant_rows': [{'permission': 'ONE'}, {'permission': 'TWO'}],
                    'summary': {},
                }
            ),
        )
    )

    report = service.get_permissions_report()

    assert report['item_label'] == 'Effective grant rows'
    assert report['item_count'] == 2
    assert report['counts']['effective_grant_rows'] == 2
    assert 'Unknown Policy' not in service.to_markdown(report)
