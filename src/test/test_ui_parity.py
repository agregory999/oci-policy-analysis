"""Correctness contracts shared by the three interactive adapters."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.policy_browser_service import PolicyBrowserService
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict
from oci_policy_analysis.presentation.web.api import routes_core


def admin_request():
    return Request(
        {
            'type': 'http',
            'session': {
                'authenticated': True,
                'auth_mode': 'admin',
                'auth_key_fp': routes_core.current_key_fingerprint(),
            },
        }
    )


@pytest.mark.parametrize(
    'limit,count,expected', [(900, 600, 'ok'), (900, 800, 'warning'), (900, 901, 'over'), (None, 100, 'unknown')]
)
def test_compartment_hierarchy_uses_snapshot_limit(limit, count, expected):
    repo = SimpleNamespace(
        policies=[],
        compartments=[{'name': 'Example', 'id': 'c', 'statement_count_cumulative': count}],
        tenancy_policy_limits={'policy_statements_per_compartment_chain_count': limit} if limit else {},
    )
    assert (
        PolicyBrowserService(SimpleNamespace(policy_repo=repo)).list_compartment_hierarchy()['rows'][0]['limit_state']
        == expected
    )


def test_exact_policy_ocid_filter_does_not_match_names_paths_or_case_variations():
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {'policy_ocid': identifier, 'policy_name': 'Team', 'compartment_path': path, 'action': 'allow'}
        for identifier, path in [
            ('ocid1.policy.Case', 'ROOT/App'),
            ('ocid1.policy.case', 'ROOT/App'),
            ('ocid1.policy.other', 'ROOT/App/Child'),
        ]
    ]
    filters = build_policy_search_from_dict({'policy_ocid': ['ocid1.policy.Case']})
    assert repo.filter_policy_statements(filters) == [repo.regular_statements[0]]


def test_web_manual_limit_write_failure_restores_snapshot(monkeypatch):
    repo = PolicyAnalysisRepository()
    repo.current_cache_name = 'Missing_2026'
    previous = repo.set_user_supplied_tenancy_policy_limits('1000', '900')
    context = SimpleNamespace(policy_repo=repo, cache=SimpleNamespace(update_tenancy_policy_limits=lambda *_: False))
    monkeypatch.setattr(routes_core, 'get_context', lambda: context)
    with pytest.raises(HTTPException) as caught:
        routes_core.set_tenancy_policy_limits(
            {'policies_count': '2000', 'policy_statements_per_compartment_chain_count': '1200'}
        )
    assert caught.value.status_code == 500
    assert repo.tenancy_policy_limits == previous
    assert repo.tenancy_policy_statement_limit == (1000, 900)


def test_web_history_matches_qt_defaults_and_returns_coverage_warnings(monkeypatch):
    from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService

    left = {
        'policies': [{'policy_ocid': 'policy'}],
        'policy_statements': [
            {
                'policy_ocid': 'policy',
                'internal_id': 'id1',
                'statement_text': 'Allow group A to read buckets in tenancy',
            }
        ],
        'inventory_complete': False,
    }
    right = deepcopy(left)
    right['policy_statements'] = []
    cache = SimpleNamespace(
        load_cache_into_local_json=lambda cached_tenancy: left if cached_tenancy == 'left' else right
    )
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(cache=cache))
    result = routes_core.historical_compare({'left_cache': 'left', 'right_cache': 'right'})
    assert result['metadata']['meaningful_only'] and result['metadata']['include_incomplete']
    assert any(section['removed'] == 1 for section in result['policy_sections'])
    assert result['section_warnings']['Regular Statements']
    direct = HistoricalAnalysisService(cache).compare_caches(
        left_cache='left', right_cache='right', meaningful_only=True, include_incomplete=True
    )
    assert result['skipped_sections'] == direct.skipped_sections


def test_web_tag_projection_preserves_invalid_source_and_rejects_limited_session(monkeypatch):
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_ocid': 'policy',
            'conditions': 'target.resource.tag.Broken',
            'valid': False,
            'statement_text': 'Unparsed source evidence',
        }
    ]
    before = deepcopy(repo.regular_statements)
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(policy_repo=repo))
    result = routes_core.get_tag_based_inventory(admin_request())
    assert result['statements'][0]['valid'] is False
    assert result['conditions'][0]['tag_parse_status'].startswith('Unparsed')
    assert repo.regular_statements == before
    request = Request(
        {'type': 'http', 'session': {'authenticated': True, 'auth_mode': 'limited', 'limited_key_hash': 'not-active'}}
    )
    monkeypatch.setattr(routes_core, '_is_limited_session', lambda _: True)
    monkeypatch.setattr(routes_core, '_require_authenticated', lambda _: None)
    with pytest.raises(HTTPException) as caught:
        routes_core.get_tag_based_inventory(request)
    assert caught.value.status_code == 403


def test_api_journal_requires_admin_and_does_not_clear_on_read(monkeypatch):
    from oci_policy_analysis.application.core.support.api_calls import ApiCallJournal

    journal = ApiCallJournal(10)
    journal.append({'operation': 'Identity.get_policy', 'outcome': 'Error', 'http_status': 404})
    monkeypatch.setattr(routes_core, 'API_CALLS', journal)
    result = routes_core.list_api_calls(admin_request())
    assert result['rows'][0]['http_status'] == 404
    assert len(journal.snapshot()[1]) == 1
    routes_core.clear_api_calls(admin_request())
    assert journal.snapshot()[1] == []
