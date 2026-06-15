from __future__ import annotations

import asyncio
import json
import logging
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


class _FakeLogger:
    def __init__(self, level):
        self.level = level
        self.messages = []

    def isEnabledFor(self, level):
        return level >= self.level

    def info(self, message, *args):
        self.messages.append(message % args if args else message)

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


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


def _repo_with_compartments():
    root_ocid = 'ocid1.tenancy.oc1..root'
    app_ocid = 'ocid1.compartment.oc1..app'
    network_app_ocid = 'ocid1.compartment.oc1..networkapp'
    return SimpleNamespace(
        tenancy_ocid=root_ocid,
        compartments=[
            {
                'id': root_ocid,
                'name': 'ROOT',
                'parent_id': '',
                'hierarchy_path': 'ROOT',
                'lifecycle_state': 'ACTIVE',
                'statement_count_direct': 1,
                'statement_count_cumulative': 1,
            },
            {
                'id': 'ocid1.compartment.oc1..prod',
                'name': 'Prod',
                'parent_id': root_ocid,
                'hierarchy_path': 'ROOT/Prod',
                'lifecycle_state': 'ACTIVE',
                'statement_count_direct': 2,
                'statement_count_cumulative': 3,
            },
            {
                'id': app_ocid,
                'name': 'app',
                'parent_id': 'ocid1.compartment.oc1..prod',
                'hierarchy_path': 'ROOT/Prod/app',
                'lifecycle_state': 'ACTIVE',
                'description': 'Application compartment',
                'statement_count_direct': 3,
                'statement_count_cumulative': 6,
            },
            {
                'id': network_app_ocid,
                'name': 'app',
                'parent_id': root_ocid,
                'hierarchy_path': 'ROOT/Network/app',
                'lifecycle_state': 'ACTIVE',
                'statement_count_direct': 1,
                'statement_count_cumulative': 2,
            },
        ],
    )


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


def test_mcp_call_logging_is_info_only_with_full_input_and_truncated_output(monkeypatch):
    long_text = 'x' * (mcp_server.MCP_OUTPUT_LOG_LIMIT + 200)
    service = _FakeQueryService(statements=[_statement(statement_text=long_text)])
    info_logger = _FakeLogger(logging.INFO)
    monkeypatch.setattr(mcp_server, '_query_service', lambda: service)
    monkeypatch.setattr(mcp_server, 'logger', info_logger)

    mcp_server.policy_search.fn(filters={'statement_text': [long_text]})

    input_logs = [message for message in info_logger.messages if 'input(full)' in message]
    output_logs = [message for message in info_logger.messages if 'output(truncated)' in message]
    assert input_logs
    assert long_text in input_logs[0]
    assert output_logs
    assert '<truncated ' in output_logs[0]

    warning_logger = _FakeLogger(logging.WARNING)
    monkeypatch.setattr(mcp_server, 'logger', warning_logger)

    mcp_server.policy_search.fn(filters={'statement_text': [long_text]})

    assert warning_logger.messages == []


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


def test_identity_search_resolves_compartments_by_ocid_name_and_path(monkeypatch):
    repo = _repo_with_compartments()
    monkeypatch.setattr(mcp_server, 'app_context', SimpleNamespace(policy_repo=repo))

    by_ocid = mcp_server.identity_search.fn(
        entity_types=['compartment'],
        ocid=['ocid1.compartment.oc1..app'],
    )

    assert by_ocid['total_compartments'] == 1
    assert by_ocid['compartments'][0]['path'] == 'ROOT/Prod/app'
    assert by_ocid['compartments'][0]['effective_path'] == 'root/prod/app'
    assert by_ocid['compartments'][0]['parent_path'] == 'ROOT/Prod'

    by_name = mcp_server.identity_search.fn(entity_types=['compartment'], name=['app'])
    assert by_name['total_compartments'] == 2

    by_path = mcp_server.identity_search.fn(entity_types=['compartment'], compartment_path=['Prod/app'])
    assert by_path['total_compartments'] == 1
    assert by_path['compartments'][0]['ocid'] == 'ocid1.compartment.oc1..app'


def test_policy_search_advanced_resolves_compartment_ocids_from_principal_evidence(monkeypatch):
    repo = _repo_with_compartments()
    statement = _statement(
        subject_type='any-user',
        match_confidence='exact',
        principal_evidence=[
            {
                'normalized_left': 'request.principal.compartment.id',
                'right': "'ocid1.compartment.oc1..app'",
            }
        ],
        dynamic_group_rule_evidence=[
            {
                'matching_rule': "ALL {instance.compartment.id = 'ocid1.compartment.oc1..networkapp'}",
            }
        ],
    )
    service = _FakeQueryService(statements=[statement])
    monkeypatch.setattr(mcp_server, '_query_service', lambda: service)
    monkeypatch.setattr(mcp_server, 'app_context', SimpleNamespace(policy_repo=repo))

    response = mcp_server.policy_search.fn(mode='advanced', filters={'resource': ['repos']})

    resolved = response['statements'][0]['resolved_compartments']
    assert {row['path'] for row in resolved} == {'ROOT/Prod/app', 'ROOT/Network/app'}
    assert any('principal_evidence.request.principal.compartment.id' in row['sources'] for row in resolved)
    assert any('dynamic_group_rule_evidence.matching_rule' in row['sources'] for row in resolved)


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
