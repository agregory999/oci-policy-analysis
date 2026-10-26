"""Live policy strategies preserve identical source evidence without OCI access."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from oci.exceptions import ServiceError
from oci.identity.models import Policy
from oci.resource_search.models import ResourceSummary, ResourceSummaryCollection
from oci.response import Response

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support.api_calls import API_CALLS
from oci_policy_analysis.application.services.load_service import LoadService


class PolicyApi:
    def __init__(self, policies, search_ids=None, failed_compartments=()):
        self.policies = {policy.id: policy for policy in policies}
        self.search_ids = search_ids if search_ids is not None else list(self.policies)
        self.failed_compartments = failed_compartments
        self.search_calls, self.list_calls, self.get_calls = [], [], []

    @staticmethod
    def response(items, page, collection=False):
        offset = int(page or 0)
        result = items[offset : offset + 1]
        headers = {'opc-next-page': str(offset + 1)} if offset + 1 < len(items) else {}
        return Response(200, headers, ResourceSummaryCollection(items=result) if collection else result, None)

    def search_resources(self, **kwargs):
        self.search_calls.append(kwargs)
        items = [
            ResourceSummary(identifier=policy_id, compartment_id='old-search-path') for policy_id in self.search_ids
        ]
        return self.response(items, kwargs.get('page'), collection=True)

    def list_policies(self, compartment_id, **kwargs):
        self.list_calls.append((compartment_id, kwargs))
        if compartment_id in self.failed_compartments:
            raise ServiceError(403, 'NotAuthorized', {}, 'No access')
        items = [policy for policy in self.policies.values() if policy.compartment_id == compartment_id]
        return self.response(items, kwargs.get('page'))

    def get_policy(self, policy_id, **kwargs):
        self.get_calls.append(policy_id)
        if policy_id not in self.policies:
            raise ServiceError(404, 'NotAuthorizedOrNotFound', {}, 'Requested resource not found or not authorized')
        return Response(200, {}, self.policies[policy_id], None)


def _policies():
    return [
        Policy(
            id='root-policy',
            name='Root policy',
            compartment_id='tenancy',
            description='Description',
            time_created=datetime(2026, 10, 21, tzinfo=UTC),
            freeform_tags={'Owner': 'IAM'},
            defined_tags={'Governance': {'CostCenter': '42'}},
            statements=[
                'Allow group Team to read buckets in tenancy',
                'Define tenancy Partner as ocid1.tenancy.oc1..aaaa',
                'Define group Remote as ocid1.group.oc1..aaaa',
                'Admit group Remote of tenancy Partner to read buckets in tenancy',
                'Endorse group Team to read buckets in tenancy Partner',
                'this statement is invalid',
            ],
        ),
        Policy(
            id='child-policy',
            name='Child policy',
            compartment_id='child',
            description='',
            time_created=datetime(2026, 10, 21, tzinfo=UTC),
            statements=[
                'Allow group Team to inspect buckets in compartment Child',
            ],
        ),
        Policy(
            id='child-policy-2',
            name='Child second',
            compartment_id='child',
            description='',
            time_created=datetime(2026, 10, 21, tzinfo=UTC),
            statements=[],
        ),
    ]


@pytest.fixture
def repository(monkeypatch):
    monkeypatch.delenv('OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV', raising=False)
    monkeypatch.delenv('OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV', raising=False)
    repo = PolicyAnalysisRepository()
    repo.tenancy_ocid = 'tenancy'
    repo.recursive = True
    repo.settings = {}
    repo.identity_api_workers = 2
    repo.compartments = [
        {'id': 'tenancy', 'hierarchy_path': 'ROOT'},
        {'id': 'child', 'hierarchy_path': 'ROOT/Child'},
    ]
    repo._cleanup_reload_api_errors = []
    monkeypatch.setattr(repo, '_refresh_defined_tag_catalog_from_resource_query', lambda: None)
    return repo


def _attach(repo, api):
    repo.identity_client = api
    repo.resource_search_client = api


def test_discovery_methods_have_identical_normalized_data_and_get_authoritative_paths(repository):
    api = PolicyApi(_policies())
    _attach(repository, api)
    assert repository.load_policies_only()
    first = (
        repository.policies,
        repository.regular_statements,
        repository.cross_tenancy_statements,
        repository.defined_aliases,
    )
    assert len(api.search_calls) == 3  # every Resource Search page, not only the first 1,000
    assert repository.load_policies_only(policy_load_method='compartment')
    assert first == (
        repository.policies,
        repository.regular_statements,
        repository.cross_tenancy_statements,
        repository.defined_aliases,
    )
    assert {item[0] for item in api.list_calls} == {'tenancy', 'child'}
    assert len(api.list_calls) == 3  # child policy listing paginated
    assert all(item[1]['lifecycle_state'] == 'ACTIVE' for item in api.list_calls)
    root = next(policy for policy in repository.policies if policy['policy_ocid'] == 'root-policy')
    assert root['tags'] == {'Owner': 'IAM', 'Governance:CostCenter': '42'}
    assert root['freeform_tags'] == {'Owner': 'IAM'}
    assert root['defined_tags'] == {'Governance': {'CostCenter': '42'}}
    assert all(
        row['compartment_path'] == 'ROOT'
        for row in repository.regular_statements
        if row['policy_ocid'] == 'root-policy'
    )
    valid = next(
        row for row in repository.regular_statements if row['statement_text'].startswith('Allow group Team to read')
    )
    assert valid['internal_id'] == hashlib.md5((valid['statement_text'] + 'root-policy').encode()).hexdigest()
    assert valid['policy_tags'] == root['tags']
    assert any(row['valid'] is False for row in repository.regular_statements)
    assert len(repository.defined_aliases) == 2
    assert len(repository.cross_tenancy_statements) == 2


def test_compartment_discovery_bypasses_stale_search_and_uses_saved_method(repository):
    api = PolicyApi(_policies(), search_ids=['root-policy', 'deleted-policy'])
    _attach(repository, api)
    assert repository.load_policies_only()
    assert {policy['policy_ocid'] for policy in repository.policies} == {'root-policy'}
    assert repository._cleanup_reload_api_errors == ['IdentityClient.get_policy']
    repository.policy_load_method = None
    repository.settings = {'policy_load_method': 'compartment'}
    assert repository.load_policies_only()
    assert {policy['policy_ocid'] for policy in repository.policies} == {
        'root-policy',
        'child-policy',
        'child-policy-2',
    }
    assert len(api.search_calls) == 2  # no policy Search calls in compartment mode


def test_root_only_and_reloads_keep_selected_method(repository):
    api = PolicyApi(_policies())
    _attach(repository, api)
    repository.recursive = False
    assert repository.load_policies_only(policy_load_method='compartment')
    assert {policy['policy_ocid'] for policy in repository.policies} == {'root-policy'}
    assert {item[0] for item in api.list_calls} == {'tenancy'}
    assert repository.load_policies_only()  # follow-up consolidation/cleanup refresh
    assert not api.search_calls
    repository.reset_state()
    assert repository.policy_load_method is None


def test_search_root_scope_and_duplicate_ids(repository):
    api = PolicyApi(_policies(), search_ids=['root-policy', 'root-policy'])
    _attach(repository, api)
    repository.recursive = False
    assert repository.load_policies_only()
    assert "compartmentId = 'tenancy'" in api.search_calls[0]['search_details'].query
    assert api.get_calls == ['root-policy']


def test_compartment_failures_remain_in_api_calls_and_partial_inventory(repository):
    api = PolicyApi(_policies(), failed_compartments={'child'})
    _attach(repository, api)
    revision = API_CALLS.snapshot()[0]
    assert repository.load_policies_only(policy_load_method='compartment')
    assert {policy['policy_ocid'] for policy in repository.policies} == {'root-policy'}
    assert repository._cleanup_reload_api_errors == ['IdentityClient.list_policies']
    rows = API_CALLS.snapshot()[1]
    assert any(row['sequence'] > revision and row['http_status'] == 403 and row['outcome'] == 'Error' for row in rows)


@pytest.mark.parametrize('method', ['compartment', 'resource_search'])
def test_empty_inventory_is_valid_but_total_discovery_or_fetch_failure_is_not(repository, method):
    api = PolicyApi([])
    _attach(repository, api)
    assert repository.load_policies_only(policy_load_method=method)
    assert repository.policies_loaded_from_tenancy
    if method == 'compartment':
        api.failed_compartments = {'tenancy', 'child'}
    else:
        api.search_ids = ['deleted-policy']
    assert not repository.load_policies_only(policy_load_method=method)
    assert not repository.policies_loaded_from_tenancy
    assert repository._cleanup_reload_api_errors


@pytest.mark.parametrize(
    'saved,explicit,expected',
    [
        ({}, None, 'resource_search'),
        ({'policy_load_method': 'compartment'}, None, 'compartment'),
        ({'policy_load_method': 'compartment'}, 'resource_search', 'resource_search'),
    ],
)
def test_load_service_method_default_settings_and_explicit_override(repository, monkeypatch, saved, explicit, expected):
    repo = repository
    for name in ('initialize_client', 'load_compartments_only', 'load_complete_identity_domains', 'load_policies_only'):
        monkeypatch.setattr(repo, name, lambda **kwargs: True)
    context = SimpleNamespace(policy_repo=repo, settings=saved)
    result = LoadService(context).load_from_tenancy(
        use_instance_principal=False,
        policy_load_method=explicit,
        run_post_load_intelligence=False,
        save_cache_after_load=False,
    )
    assert result.success
    assert repo.policy_load_method == expected


def test_invalid_method_does_not_reset_current_snapshot(repository):
    repository.policies = [{'policy_ocid': 'keep-existing'}]
    context = SimpleNamespace(policy_repo=repository, settings={})
    with pytest.raises(ValueError, match='Unknown policy load method'):
        LoadService(context).load_from_tenancy(use_instance_principal=False, policy_load_method='typo')
    assert repository.policies == [{'policy_ocid': 'keep-existing'}]
