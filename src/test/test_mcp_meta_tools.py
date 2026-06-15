from __future__ import annotations

import asyncio
import json
from importlib import resources
from types import SimpleNamespace

import oci_policy_analysis.mcp_server as mcp_server
import tiktoken


class _FakeQueryService:
    def __init__(self, statements=None, dynamic_groups=None):
        self.statements = statements or []
        self.dynamic_groups = dynamic_groups or []

    def filter_policy_statements(self, filters):
        self.last_policy_filters = filters
        return list(self.statements)

    def search_dynamic_groups(self, filters):
        self.last_dynamic_group_filters = filters
        return list(self.dynamic_groups)

    def search_users(self, filters):
        return []

    def search_groups(self, filters):
        return []

    def get_groups_for_user(self, user):
        return [{'domain_name': user.get('domain_name', 'Default'), 'group_name': 'Operators'}]

    def get_users_for_group(self, group):
        return [{'domain_name': group.get('domain_name', 'Default'), 'user_name': 'alice'}]


def _statement(**overrides):
    row = {
        'policy_name': 'PolicyA',
        'statement_text': 'allow any-user to read repos in tenancy',
        'subject_type': 'any-user',
        'principal_keys': ['any-user:None/any-user'],
        'principals': [{'principal_type': 'any-user', 'principal_key': 'any-user:None/any-user'}],
        'verb': 'read',
        'resource': 'repos',
        'effective_path': 'root',
        'conditions': '',
        'stable_key': 's1',
    }
    row.update(overrides)
    return row


def test_mcp_tool_surface_is_compact_meta_tools_only():
    tools = asyncio.run(mcp_server.mcp.get_tools())

    assert sorted(tools.keys()) == [
        'cross_tenancy_search',
        'data_operations',
        'identity_search',
        'policy_history_search',
        'policy_search',
        'policy_search_set',
    ]


def test_packaged_mcp_tools_artifact_matches_compact_surface():
    with resources.files('oci_policy_analysis.application.core.resources.mcp_tools_list').joinpath(
        'mcp_tools.json'
    ).open('r', encoding='utf-8') as handle:
        data = json.load(handle)

    tools = data['result']['tools']
    assert [tool['name'] for tool in tools] == [
        'policy_search',
        'policy_search_set',
        'policy_history_search',
        'identity_search',
        'data_operations',
        'cross_tenancy_search',
    ]

    token_count = len(tiktoken.get_encoding('o200k_base').encode(json.dumps(data)))
    assert token_count < 4000


def test_policy_search_returns_bounded_simple_rows(monkeypatch):
    service = _FakeQueryService(statements=[_statement(match_confidence='exact')])
    monkeypatch.setattr(mcp_server, '_query_service', lambda: service)

    response = mcp_server.policy_search.fn(filters={'resource': ['repos']})

    assert response['total_count'] == 1
    assert response['statements'][0]['policy_name'] == 'PolicyA'
    assert response['statements'][0]['match_confidence'] == 'exact'
    assert service.last_policy_filters['resource'] == ['repos']


def test_policy_search_set_summarizes_required_searches(monkeypatch):
    service = _FakeQueryService(statements=[_statement(match_confidence='exact')])
    monkeypatch.setattr(mcp_server, '_query_service', lambda: service)

    response = mcp_server.policy_search_set.fn(
        intent='install_validation',
        product_or_service='repo pull',
        searches=[
            {
                'search_id': 'workload',
                'label': 'workload can read repos',
                'required': True,
                'query': {'mode': 'advanced', 'filters': {'resource': ['repos']}},
            }
        ],
        evaluation={'require_workload_principal_coverage': True, 'min_confidence': 'rule_evidence'},
    )

    assert response['set_summary']['matched_required_searches'] == 1
    assert response['set_summary']['likely_ready'] is True
    assert response['search_results'][0]['search_id'] == 'workload'


def test_identity_search_dynamic_group_operation(monkeypatch):
    dynamic_group = {
        'domain_name': 'Default',
        'dynamic_group_name': 'Instances',
        'matching_rule': "ALL {resource.type = 'instance'}",
    }
    service = _FakeQueryService(dynamic_groups=[dynamic_group])
    monkeypatch.setattr(mcp_server, '_query_service', lambda: service)

    response = mcp_server.identity_search.fn(entity_types=['dynamic-group'], matching_rule=['instance'])

    assert response['total_dynamic_groups'] == 1
    assert response['dynamic_groups'][0]['dynamic_group_name'] == 'Instances'


def test_data_operations_get_status(monkeypatch):
    repo = SimpleNamespace(
        tenancy_name='tenancy',
        tenancy_ocid='ocid1.tenancy.oc1..example',
        data_as_of='2026-06-15T00:00:00Z',
        regular_statements=[{}],
        cross_tenancy_statements=[],
        defined_aliases=[],
        users=[{}],
        groups=[{}],
        dynamic_groups=[{}],
        policies_loaded_from_tenancy=False,
    )
    monkeypatch.setattr(mcp_server, 'app_context', SimpleNamespace(policy_repo=repo))

    response = mcp_server.data_operations.fn(operation='get_status')

    assert response['operation'] == 'get_status'
    assert response['regular_statements'] == 1
    assert response['dynamic_groups'] == 1
