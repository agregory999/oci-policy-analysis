"""In-memory API metadata is complete, bounded, and independent of log levels."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from oci.exceptions import ServiceError

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support import api_calls


def test_sdk_attempts_capture_pages_and_retries_without_bodies_or_credentials(monkeypatch):
    journal = api_calls.ApiCallJournal()
    monkeypatch.setattr(api_calls, 'API_CALLS', journal)

    class Base:
        endpoint = 'https://identity.example.test'

        def call_api(self, path, method, **kwargs):
            if kwargs.get('fail'):
                raise ServiceError(429, 'TooManyRequests', {'opc-request-id': 'retry-id'}, 'Slow down')
            return SimpleNamespace(
                status=200,
                request_id='success-id',
                headers={'Authorization': 'SECRET-HEADER'},
                data={'private': 'SECRET-BODY'},
                request=SimpleNamespace(
                    url='https://user:SECRET-PASSWORD@identity.example.test/groups?token=SECRET-QUERY', method=method
                ),
            )

    class Client:
        def __init__(self):
            self.base_client = Base()

        def list_groups(self):
            # Simulate a retry followed by another page. Every actual SDK call
            # is recorded; the enclosing pagination helper adds no duplicate.
            try:
                self.base_client.call_api('/groups', 'GET', fail=True)
            except ServiceError:
                pass
            self.base_client.call_api('/groups', 'GET')
            return self.base_client.call_api('/groups', 'GET')

    repo = PolicyAnalysisRepository()
    repo.tenancy_ocid = 'tenancy-a'
    client = Client()

    def pages(fn):
        return fn()

    repo._api_call_with_logging('IdentityDomainsClient.list_groups', pages, client.list_groups)
    _, rows, dropped = journal.snapshot()
    assert [row['http_status'] for row in rows] == [429, 200, 200]
    assert all(row['operation'] == 'IdentityDomainsClient.list_groups' for row in rows)
    assert all(row['tenancy_ocid'] == 'tenancy-a' and row['duration_ms'] >= 0 for row in rows)
    assert rows[0]['request_id'] == 'retry-id'
    assert rows[1]['endpoint'] == 'https://identity.example.test/groups'
    assert 'SECRET' not in json.dumps(rows)
    assert dropped == 0


def test_policy_404_is_retained_without_claiming_deletion_or_requiring_verbose_logs(monkeypatch):
    journal = api_calls.ApiCallJournal()
    monkeypatch.setattr(api_calls, 'API_CALLS', journal)
    repo = PolicyAnalysisRepository()
    repo.settings = {'global_log_level': 'CRITICAL', 'always_log_api_calls': False}
    repo.api_calls_separate_view = True
    repo._cleanup_reload_api_errors = []

    def missing(**_kwargs):
        raise ServiceError(
            404,
            'NotAuthorizedOrNotFound',
            {'opc-request-id': 'request-404'},
            'Authorization failed or requested resource not found.',
            request_endpoint='GET https://identity.example.test/policies/policy-a',
        )

    with pytest.raises(ServiceError):
        repo._api_call_with_logging('IdentityClient.get_policy', missing, policy_id='policy-a')
    _, rows, _ = journal.snapshot()
    assert len(rows) == 1
    row = rows[0]
    assert row['http_status'] == 404 and row['code'] == 'NotAuthorizedOrNotFound'
    assert row['target'] == 'policy-a' and row['request_id'] == 'request-404'
    assert 'does not confirm deletion' in row['interpretation']
    assert 'insufficient permission' in row['interpretation']
    assert repo._cleanup_reload_api_errors == ['IdentityClient.get_policy']


def test_journal_is_thread_safe_bounded_and_clearable_without_resetting_cursors():
    journal = api_calls.ApiCallJournal(capacity=20)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda number: journal.append({'number': number}), range(100)))
    revision, rows, dropped = journal.snapshot()
    assert len(rows) == 20 and dropped == 80
    assert len({row['sequence'] for row in rows}) == 20
    rows[0]['number'] = 'detached'
    assert journal.snapshot()[1][0]['number'] != 'detached'
    journal.clear()
    new_revision, rows, dropped = journal.snapshot()
    assert new_revision > revision and rows == [] and dropped == 0
    assert journal.snapshot(new_revision)[1] is None


def test_local_failure_has_no_invented_http_status(monkeypatch):
    journal = api_calls.ApiCallJournal()
    monkeypatch.setattr(api_calls, 'API_CALLS', journal)
    repo = PolicyAnalysisRepository()

    def fail():
        raise TimeoutError('Local connection timeout')

    with pytest.raises(TimeoutError):
        repo._api_call_with_logging('IdentityClient.get_policy', fail)
    row = journal.snapshot()[1][0]
    assert row['http_status'] is None and row['code'] == 'TimeoutError'


def test_early_collection_errors_survive_later_successes_within_bounded_history():
    journal = api_calls.ApiCallJournal(capacity=3)
    journal.append({'outcome': 'Error', 'request_id': 'early-policy-404'})
    for index in range(20):
        journal.append({'outcome': 'Success', 'request_id': f'success-{index}'})
    _, rows, dropped = journal.snapshot()
    assert len(rows) == 3 and dropped == 18
    assert rows[0]['request_id'] == 'early-policy-404'
    assert rows[-1]['request_id'] == 'success-19'
