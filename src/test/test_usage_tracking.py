"""Usage lifecycle and old JSON contracts, without live bucket writes."""

import json

import pytest

from oci_policy_analysis.analytics.model import UsageDoc
from oci_policy_analysis.application.core.support import usage_tracking as tracking
from oci_policy_analysis.application.services.usage_service import UsageSession


@pytest.fixture
def uploads(monkeypatch):
    bodies = []
    monkeypatch.setattr(tracking, '_tracker', None)
    monkeypatch.setattr(tracking, '_get_par_base_url', lambda: 'https://example.invalid/write/')

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def send(request, **kwargs):
        assert request.get_method() == 'PUT'
        bodies.append((request.full_url, json.loads(request.data)))
        return Response()

    monkeypatch.setattr(tracking.request, 'urlopen', send)
    yield bodies
    monkeypatch.setattr(tracking, '_tracker', None)


def test_qt_default_publication_is_backward_readable_and_contains_only_counts(uploads):
    session = UsageSession({}, '7.0.test')
    session.set_tenancy('ocid1.tenancy.secret.fullidentifierABC123')
    session.view('browser')
    session.operation('data_load', source='tenancy', counts={'policies': 3, 'users': 4, 'secret_policy': 'private'})
    session.operation('arbitrary private text', source='private path')
    session.close()
    session.close()
    assert len(uploads) == 1
    url, raw = uploads[0]
    assert '/ABC123/' in url
    assert raw['schema_version'] == 1 and raw['interface'] == 'qt'
    assert raw['tenancy_suffix'] == 'ABC123'
    assert raw['operations'][0]['payload'] == {
        'success': True,
        'source': 'tenancy',
        'counts': {'policies': 3, 'users': 4},
    }
    assert len(raw['operations']) == 1
    assert 'fullidentifier' not in json.dumps(raw)
    assert 'private' not in json.dumps(raw)
    doc = UsageDoc.from_dict(raw, tenancy_suffix=None)
    assert doc and doc.interface == 'qt' and doc.tenancy_suffix == 'ABC123'


def test_explicit_opt_out_and_runtime_disable_discard_pending_data(uploads):
    session = UsageSession({'usage_tracking_enabled': False}, '7')
    session.view('browser')
    session.set_tenancy('ocid1.tenancy.secret.ABC123')
    session.set_enabled(True)
    tracker = session.tracker
    session.operation('simulation_run')
    session.set_enabled(False)
    tracker.flush()  # A retained MCP reference must not bypass opt-out.
    session.close()
    assert not uploads


def test_session_tenancy_rotation_separates_operations(uploads):
    session = UsageSession({}, '7')
    session.set_tenancy('ocid1.tenancy.ABC123')
    session.operation('data_load', counts={'policies': 5})
    session.set_tenancy('ocid1.tenancy.XYZ789')
    session.operation('report_generate')
    session.close()
    assert len(uploads) == 2
    assert uploads[0][1]['tenancy_suffix'] == 'ABC123'
    assert [op['op_type'] for op in uploads[0][1]['operations']] == ['data_load']
    assert uploads[1][1]['tenancy_suffix'] == 'XYZ789'
    assert [op['op_type'] for op in uploads[1][1]['operations']] == ['report_generate']


def test_legacy_tracker_rotation_handles_operations_without_events(uploads):
    tracker = tracking.UsageTracker(True, 'old')
    tracker.set_tenancy_suffix('ABC123')
    tracker.track_operation('simulation_run')
    tracker.set_tenancy_suffix('XYZ789')
    tracker.track_operation('data_load')
    tracker.flush()
    assert len(uploads) == 2
    assert [op['op_type'] for op in uploads[1][1]['operations']] == ['data_load']


def test_repeated_initialization_does_not_drop_current_run(uploads):
    tracker = tracking.init_usage_tracker({'usage_tracking_enabled': True}, '7')
    tracker.track('tab_change', tab_name='A')
    assert tracking.init_usage_tracker({'usage_tracking_enabled': True}, '7') is tracker
    tracker.flush()
    assert uploads[0][1]['events'][0]['payload']['tab_name'] == 'A'


def test_upload_failure_does_not_raise_or_log_bearer_credentials(uploads, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError('https://private.invalid/p/SUPER_SECRET/')

    monkeypatch.setattr(tracking.request, 'urlopen', fail)
    tracker = tracking.UsageTracker(True, '7')
    tracker.track('app_start')
    tracker.flush()
    assert 'SUPER_SECRET' not in caplog.text


def test_historical_documents_accept_missing_operations_new_fields_and_malformed_items():
    raw = {
        'run_id': 'old',
        'app_version': '4.4',
        'started_at': '2025-01-01T00:00:00Z',
        'events': [{'event_type': 'tab_change', 'ts': '2025-01-01T00:00:01Z', 'payload': {'tab_name': 'OldTab'}}, None],
        'operations': 42,
        'future_field': 'ignored',
    }
    doc = UsageDoc.from_dict(raw, tenancy_suffix='abc123')
    assert doc and len(doc.events) == 1 and not doc.operations
    assert doc.interface == 'unknown' and doc.schema_version == 0


def test_initialization_after_flush_starts_new_document_for_web_operations(uploads):
    first = tracking.init_usage_tracker({'usage_tracking_enabled': True}, '7')
    first.track_operation('web_operation')
    first.flush()
    second = tracking.init_usage_tracker({'usage_tracking_enabled': True}, '7')
    assert second is not first
    second.track_operation('web_operation')
    second.flush()
    assert len(uploads) == 2


def test_usage_boundary_rejects_free_text_and_nonidentifier_suffixes(uploads):
    session = UsageSession({}, '7')
    session.set_tenancy('sensitive/../../')
    session.view('private-policy-name')
    session.view('browser', 'private-filter-text')
    session.close()
    raw = json.dumps(uploads[0][1])
    assert 'private' not in raw and 'sensitive' not in raw
    assert uploads[0][1]['tenancy_suffix'] is None


def test_unknown_bucket_prefix_is_not_counted_as_a_known_tenancy():
    from oci_policy_analysis.analytics.aggregator import compute_overview_metrics

    raw = {'run_id': 'old', 'app_version': '4', 'started_at': '2025-01-01T00:00:00Z'}
    unknown = UsageDoc.from_dict(raw, tenancy_suffix='unknown')
    known = UsageDoc.from_dict({**raw, 'run_id': 'known'}, tenancy_suffix='ABC123')
    assert compute_overview_metrics([unknown])['distinct_tenancies'] == 0
    assert compute_overview_metrics([unknown, known])['distinct_tenancies'] == 1


def test_web_startup_and_operation_rotation_keep_explicit_interface(uploads, monkeypatch):
    from types import SimpleNamespace

    from oci_policy_analysis.presentation.web import dependencies
    from oci_policy_analysis.presentation.web.api import routes_core

    settings = {'usage_tracking_enabled': True}
    monkeypatch.setattr(dependencies, 'get_settings', lambda: settings)
    monkeypatch.setattr(dependencies, 'AppContext', SimpleNamespace(from_settings=lambda _: object()))
    monkeypatch.setattr(routes_core, 'get_settings', lambda: settings)
    dependencies.get_context.cache_clear()
    try:
        dependencies.get_context()
        assert tracking.get_usage_tracker().interface == 'web'
        context = SimpleNamespace(policy_repo=SimpleNamespace(tenancy_ocid='ocid1.tenancy.ABC123'))
        for _ in range(2):
            routes_core._track_web_operation('/policies', ctx=context, status='success')
            assert tracking.get_usage_tracker().interface == 'web'
        assert len(uploads) == 2
        assert all(document['interface'] == 'web' for _, document in uploads)
    finally:
        dependencies.get_context.cache_clear()
