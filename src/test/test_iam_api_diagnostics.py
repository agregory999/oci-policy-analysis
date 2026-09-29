import csv
import json
from types import SimpleNamespace

import pytest
from oci.exceptions import ServiceError
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository


def test_iam_api_diagnostics_captures_targeted_response_with_domain_context(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / 'iam-api-diagnostics.csv'
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV', str(output_path))
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_RESPONSES', '1')
    repo = PolicyAnalysisRepository()

    response = SimpleNamespace(data={'Resources': [{'id': 'group-1', 'displayName': 'ReadOnlyUsers'}]})
    result = repo._api_call_with_logging(
        'IdentityDomainsClient.list_groups',
        lambda: response,
        _iam_diagnostics_context={
            'entity_type': 'group',
            'domain_name': 'Default',
            'domain_ocid': 'domain-ocid',
        },
    )

    assert result is response
    with output_path.open(encoding='utf-8', newline='') as file_object:
        rows = list(csv.DictReader(file_object))
    assert len(rows) == 1
    assert rows[0]['call'] == 'IdentityDomainsClient.list_groups'
    assert rows[0]['domain_name'] == 'Default'
    assert rows[0]['status'] == 'success'
    assert json.loads(rows[0]['response_json']) == response.data


def test_iam_api_diagnostics_omits_responses_by_default(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / 'iam-api-diagnostics.csv'
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV', str(output_path))
    repo = PolicyAnalysisRepository()

    repo._api_call_with_logging(
        'IdentityDomainsClient.list_groups',
        lambda: SimpleNamespace(data={'Resources': [{'id': 'group-1'}]}),
        _iam_diagnostics_context={'entity_type': 'group'},
    )

    with output_path.open(encoding='utf-8', newline='') as file_object:
        assert list(csv.DictReader(file_object))[0]['response_json'] == ''


def test_iam_api_diagnostics_is_disabled_without_environment_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV', raising=False)
    repo = PolicyAnalysisRepository()

    repo._api_call_with_logging(
        'IdentityDomainsClient.list_groups',
        lambda: SimpleNamespace(data={'Resources': []}),
        _iam_diagnostics_context={'entity_type': 'group'},
    )

    assert not list(tmp_path.iterdir())


def test_iam_api_diagnostics_captures_service_error_details(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / 'iam-api-diagnostics.csv'
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV', str(output_path))
    repo = PolicyAnalysisRepository()

    def fail():
        raise ServiceError(
            status=403,
            code='NotAuthorizedOrNotFound',
            headers={'opc-request-id': 'request-123'},
            message='Access denied',
        )

    with pytest.raises(ServiceError):
        repo._api_call_with_logging(
            'IdentityDomainsClient.list_dynamic_resource_groups',
            fail,
            _iam_diagnostics_context={'entity_type': 'dynamic_group', 'domain_name': 'Default'},
        )

    with output_path.open(encoding='utf-8', newline='') as file_object:
        row = list(csv.DictReader(file_object))[0]
    assert row['status'] == 'service_error'
    assert row['http_status'] == '403'
    assert row['service_code'] == 'NotAuthorizedOrNotFound'
    assert row['request_id'] == 'request-123'
    assert row['error_message'] == 'Access denied'


def test_identity_api_workers_can_be_reduced_with_environment_flag(monkeypatch) -> None:
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IDENTITY_API_WORKERS', '1')

    assert PolicyAnalysisRepository().identity_api_workers == 1


@pytest.mark.parametrize('value', ['0', '7', 'invalid'])
def test_identity_api_workers_rejects_unsafe_or_invalid_values(monkeypatch, value) -> None:
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_IDENTITY_API_WORKERS', value)

    assert PolicyAnalysisRepository().identity_api_workers == 6
