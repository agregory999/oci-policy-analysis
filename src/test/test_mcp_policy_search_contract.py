"""MCP policy search should explain and resolve OCI resource scope."""

import asyncio

import pytest
from fastmcp.exceptions import ToolError

from oci_policy_analysis import mcp_server


def test_live_tool_schema_describes_resource_family() -> None:
    tools = asyncio.run(mcp_server.mcp.get_tools())
    schema = tools['policy_search'].parameters
    filters = schema['$defs']['MCPPolicyFilters']['properties']

    assert 'resource_family' in filters
    assert 'object storage' in filters['resource_family']['description']
    assert 'OCI policy resource type' in filters['resource']['description']
    assert 'not pagination' in schema['properties']['limit']['description']
    assert 'detailed-row threshold capped at 50' in tools['policy_search'].description
    assert 'summary_substituted' in tools['policy_search'].description


def test_object_storage_family_expands_to_all_grant_scopes() -> None:
    filters = mcp_server._policy_filters_from_request(
        {'resource_family': 'object storage', 'principal': {'principal_type': 'group'}, 'verb': ['manage']}
    )

    assert set(filters['resource']) == {
        'object-family',
        'objectstorage-namespaces',
        'buckets',
        'objects',
        'all-resources',
    }
    assert filters['principal'] == {'principal_type': 'group'}
    assert filters['verb'] == ['manage']


def test_product_phrase_in_resource_also_expands() -> None:
    filters = mcp_server._policy_filters_from_request({'resource': ['object storage']})

    assert 'object storage' not in filters['resource']
    assert 'objects' in filters['resource']
    assert 'all-resources' in filters['resource']


def test_unknown_resource_family_is_rejected_with_guidance() -> None:
    with pytest.raises(ToolError, match='Unknown resource_family'):
        mcp_server._policy_filters_from_request({'resource_family': 'not-a-family'})


def test_limit_clamp_is_reported(monkeypatch) -> None:
    class EmptyQueryService:
        def filter_policy_statements(self, _filters):
            return []

    monkeypatch.setattr(mcp_server, '_query_service', EmptyQueryService)
    response = mcp_server._run_policy_search_request({'filters': {}, 'limit': 500})

    assert response['returned_count'] == 0
    assert response['detail_row_limit'] == 50
    assert any('capped at 50' in warning for warning in response['warnings'])


def test_unfiltered_search_returns_summary_instead_of_rows(monkeypatch) -> None:
    class QueryService:
        def filter_policy_statements(self, _filters):
            return [{'policy_name': 'PolicyA', 'verb': 'manage', 'resource': 'buckets'}]

    monkeypatch.setattr(mcp_server, '_query_service', QueryService)
    response = mcp_server._run_policy_search_request({'filters': {}})

    assert response['response_type'] == 'summary'
    assert response['summary_substituted'] is True
    assert response['summary_reason'] == 'unfiltered_query'
    assert response['total_count'] == 1
    assert response['returned_count'] == 0
    assert response['statements'] == []
    assert 'narrow filters' in response['refinement_hint']
    assert any('Summary returned' in warning for warning in response['warnings'])


def test_large_filtered_search_returns_bounded_summary(monkeypatch) -> None:
    class QueryService:
        def filter_policy_statements(self, _filters):
            return [
                {
                    'policy_name': f'Policy{i}',
                    'verb': 'manage',
                    'resource': 'buckets',
                    'principals': [{'principal_type': 'group', 'name': 'Admins'}],
                }
                for i in range(80)
            ]

    monkeypatch.setattr(mcp_server, '_query_service', QueryService)
    response = mcp_server._run_policy_search_request({'filters': {'verb': ['manage']}, 'limit': 500})

    assert response['response_type'] == 'summary'
    assert response['summary_reason'] == 'too_many_matches'
    assert response['total_count'] == 80
    assert response['statements'] == []
    assert response['returned_count'] == 0
    assert response['breakdowns']['by_policy']['__other__'] == 60
    assert response['summary_evidence']['principal_types'] == ['group']

    set_result = mcp_server.policy_search_set.fn(
        searches=[{'search_id': 'groups', 'filters': {'verb': ['manage']}}],
        evaluation={'require_human_principal_coverage': True},
    )
    assert set_result['set_summary']['human_principal_coverage'] == 'present'


def test_filtered_search_under_threshold_returns_rows(monkeypatch) -> None:
    class QueryService:
        def filter_policy_statements(self, _filters):
            return [{'policy_name': 'PolicyA', 'verb': 'manage', 'resource': 'buckets'}]

    monkeypatch.setattr(mcp_server, '_query_service', QueryService)
    response = mcp_server._run_policy_search_request({'filters': {'verb': ['manage']}, 'limit': 5})

    assert response['response_type'] == 'simple'
    assert response['summary_substituted'] is False
    assert response['returned_count'] == 1
    assert response['statements'][0]['policy_name'] == 'PolicyA'


def test_requested_summary_has_no_rows() -> None:
    response = mcp_server._format_policy_search_response(
        [{'policy_name': 'PolicyA', 'verb': 'manage', 'resource': 'buckets'}],
        detail_level='summary',
    )

    assert response['response_type'] == 'summary'
    assert response['summary_substituted'] is False
    assert response['summary_reason'] == 'requested_summary'
    assert response['statements'] == []


def test_history_search_uses_all_matches_even_when_mcp_response_is_summary() -> None:
    class Repo:
        def filter_policy_statements(self, *, filters):
            assert filters['verb'] == ['manage']
            return [{'policy_name': f'Policy{i}', 'verb': 'manage', 'resource': 'buckets'} for i in range(80)]

    rows = mcp_server._run_query_for_history('single', {'filters': {'verb': ['manage']}}, Repo())

    assert len(rows) == 80


def test_search_set_schema_exposes_filters_examples_and_selection_guidance():
    tools = asyncio.run(mcp_server.mcp.get_tools())
    tool = tools['policy_search_set']
    schema = tool.parameters
    assert 'MCPPolicySetSearch' in schema['$defs']
    item = schema['$defs']['MCPPolicySetSearch']['properties']
    assert {'search_id', 'label', 'required', 'filters', 'query'} <= item.keys()
    assert 'resource_family' in schema['$defs']['MCPPolicyFilters']['properties']
    assert 'examples' in schema['properties']['searches']
    assert 'two or more' in tool.description
    assert 'not proof of effective access' in tool.description
    assert 'policy_search_set' in tools['policy_search'].description


def test_typed_set_direct_and_legacy_wrapped_requests_preserve_results(monkeypatch):
    from oci_policy_analysis.application.core.models.models_mcp import MCPPolicySetSearch

    class QueryService:
        def filter_policy_statements(self, filters):
            return (
                [{'policy_name': 'ManagePolicy', 'verb': 'manage', 'resource': 'buckets'}]
                if filters['verb'] == ['manage']
                else []
            )

    monkeypatch.setattr(mcp_server, '_query_service', QueryService)
    filters = {'verb': ['manage'], 'resource_family': 'object storage'}
    direct = MCPPolicySetSearch(search_id='manage', filters=filters, detail_level='summary')
    legacy = MCPPolicySetSearch(search_id='manage', query={'filters': filters, 'detail_level': 'summary'})
    direct_result = mcp_server.policy_search_set.fn(searches=[direct])
    legacy_result = mcp_server.policy_search_set.fn(searches=[legacy])
    assert direct_result == legacy_result
    assert direct_result['set_summary']['matched_required_searches'] == 1
    assert direct_result['search_results'][0]['total_count'] == 1


def test_packaged_set_schema_matches_live_contract():
    import json
    from importlib import resources

    tools = asyncio.run(mcp_server.mcp.get_tools())
    data = json.loads(
        resources.files('oci_policy_analysis.application.core.resources.mcp_tools_list')
        .joinpath('mcp_tools.json')
        .read_text()
    )
    record = next(item for item in data['result']['tools'] if item['name'] == 'policy_search_set')
    assert record['inputSchema'] == tools['policy_search_set'].parameters
    assert record['description'] == tools['policy_search_set'].description


def test_fastmcp_accepts_nested_search_set_inputs(monkeypatch):
    import json

    class QueryService:
        def filter_policy_statements(self, _filters):
            return []

    monkeypatch.setattr(mcp_server, '_query_service', QueryService)
    result = asyncio.run(
        mcp_server.policy_search_set.run(
            {
                'intent': 'access_review',
                'searches': [
                    {
                        'search_id': 'groups',
                        'filters': {'principal': {'principal_type': 'group'}, 'resource_family': 'object storage'},
                    },
                    {
                        'search_id': 'workloads',
                        'query': {'filters': {'principal': {'principal_type': 'dynamic-group'}}},
                    },
                ],
                'evaluation': {'require_human_principal_coverage': True},
            }
        )
    )
    payload = json.loads(result.content[0].text)
    assert payload['set_summary']['total_searches'] == 2
    assert payload['set_summary']['missing_required_searches'] == ['groups', 'workloads']
