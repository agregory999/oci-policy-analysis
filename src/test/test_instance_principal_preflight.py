"""Bound metadata discovery before entering the SDK's retrying signer setup."""

import http.client
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from oci_policy_analysis.application.services import load_service


@pytest.mark.parametrize('outcome', [200, 403, TimeoutError(), OSError(), http.client.BadStatusLine('invalid')])
def test_metadata_probe_is_direct_bounded_and_closes(monkeypatch, outcome):
    connection = Mock()
    if isinstance(outcome, Exception):
        connection.getresponse.side_effect = outcome
    else:
        connection.getresponse.return_value.status = outcome
    factory = Mock(return_value=connection)
    monkeypatch.setattr(load_service.http.client, 'HTTPConnection', factory)
    assert load_service._instance_metadata_available() is (outcome == 200)
    factory.assert_called_once_with('169.254.169.254', None, timeout=0.5)
    connection.request.assert_called_once_with(
        'GET', '/opc/v2/instance/region', headers={'Authorization': 'Bearer Oracle'}
    )
    connection.close.assert_called_once()


def test_failed_metadata_probe_preserves_context_and_skips_sdk(monkeypatch):
    repo = Mock()
    context = SimpleNamespace(policy_repo=repo, settings={})
    service = load_service.LoadService(context)
    reset = Mock()
    monkeypatch.setattr(service, '_reset_repo_state_before_load', reset)
    monkeypatch.setattr(load_service, '_instance_metadata_available', lambda: False)
    stages = []
    result = service.load_from_tenancy(use_instance_principal=True, on_stage=lambda *args: stages.append(args))
    assert not result.success
    assert 'OCI Compute instance with a valid instance principal' in result.message
    repo.initialize_client.assert_not_called()
    reset.assert_not_called()
    assert stages[-1][0] == 'Failed'


def test_successful_metadata_probe_continues_sdk_initialization(monkeypatch):
    repo = Mock()
    repo.initialize_client.return_value = False
    service = load_service.LoadService(SimpleNamespace(policy_repo=repo, settings={}))
    monkeypatch.setattr(service, '_reset_repo_state_before_load', lambda: None)
    monkeypatch.setattr(load_service, '_instance_metadata_available', lambda: True)
    result = service.load_from_tenancy(use_instance_principal=True)
    assert not result.success  # Probe success must not claim successful authentication.
    repo.initialize_client.assert_called_once()
