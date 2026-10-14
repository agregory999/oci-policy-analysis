"""Policy graph pages aggregate direct facts and preserve source details."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from oci_policy_analysis.application.core.policy_corpus import (
    CorpusProvenance,
    PolicyCorpus,
    PolicyCorpusFact,
)
from oci_policy_analysis.application.services.policy_graph_service import PolicyGraphService
from oci_policy_analysis.presentation.web.api import routes_core
from oci_policy_analysis.presentation.web.main import app


def _fact(statement: str, principal: str, permission: str, *, effect: str = 'allow') -> PolicyCorpusFact:
    source = CorpusProvenance('Policy A', 'ocid1.policy.test', statement, f'{effect} {principal} to read buckets')
    return PolicyCorpusFact(principal, 'ROOT/Prod', 'ROOT/Prod', permission, effect, '', source, resource='buckets')


def test_policy_graph_groups_permissions_and_filters_grants() -> None:
    corpus = PolicyCorpus(
        schema_version=1,
        built_at='now',
        facts=(
            _fact('one', 'group:Default/Ops', 'BUCKET_READ'),
            _fact('one', 'group:Default/Ops', 'BUCKET_INSPECT'),
            _fact('two', 'group:Default/Audit', 'BUCKET_READ', effect='deny'),
        ),
    )
    service = PolicyGraphService(corpus)
    page = service.get_page()
    assert page['total'] == 2
    assert page['summary'] == {'direct_facts': 3, 'source_statements': 2, 'exclusions': 0}
    ops = next(row for row in page['grants'] if row['principal'] == 'group:default/ops')
    assert ops['permissions'] == ['BUCKET_INSPECT', 'BUCKET_READ']
    assert ops['statement_id'] == 'one'
    assert service.get_page(effect='deny')['grants'][0]['principal'] == 'group:default/audit'
    assert service.get_page(principal='Ops', path='Prod', resource='buckets', query='Policy A')['total'] == 1
    assert service.get_page(query='missing')['total'] == 0
    assert service.get_page(page=2, page_size=1)['grants'][0]['statement_id'] == 'one'


def test_policy_graph_bounds_pages_and_handles_unloaded_corpus() -> None:
    assert PolicyGraphService(None).get_page()['loaded'] is False
    facts = tuple(_fact(str(index), f'group:Default/{index:02}', 'BUCKET_READ') for index in range(20))
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=facts)
    page = PolicyGraphService(corpus).get_page(page_size=100)
    assert page['page_size'] == 12
    assert len(page['grants']) == 12
    assert PolicyGraphService(corpus).get_page(page=2)['total'] == 20


def test_resource_or_permission_filter_preserves_complete_grant_permissions() -> None:
    corpus = PolicyCorpus(
        schema_version=1,
        built_at='now',
        facts=(
            _fact('one', 'group:Default/Ops', 'OBJECT_CREATE'),
            _fact('one', 'group:Default/Ops', 'OBJECT_READ'),
            _fact('two', 'group:Default/Audit', 'BUCKET_READ'),
        ),
    )
    service = PolicyGraphService(corpus)
    for term in ('OBJECT_CREATE', 'object_create', 'object_'):
        result = service.get_page(resource=term)
        assert result['total'] == 1
        assert result['grants'][0]['permissions'] == ['OBJECT_CREATE', 'OBJECT_READ']
        assert result['paths'] == [{'path': 'ROOT/Prod', 'grant_count': 1}]
    assert service.get_page(resource='buckets')['total'] == 2
    assert service.get_page(resource='OBJECT_DELETE')['total'] == 0
    assert service.get_page(resource='OBJECT_CREATE', principal='Audit')['total'] == 0


def test_policy_graph_route_and_page_are_served(monkeypatch) -> None:
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=(_fact('one', 'group:Default/Ops', 'BUCKET_READ'),))
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(corpus=corpus))
    client = TestClient(app)
    response = client.get('/analysis/policy-graph', params={'principal': 'Ops'})
    assert response.status_code == 200
    assert response.json()['grants'][0]['principal'] == 'group:default/ops'
    page = client.get('/policy-graph.html')
    assert page.status_code == 200
    assert 'Policy Graph' in page.text


def test_effective_path_matches_are_complete_before_grant_pagination():
    from dataclasses import replace

    facts = tuple(
        replace(
            _fact(str(index), f'group:Default/{index:02}', 'BUCKET_READ'),
            grant_path=f'ROOT/network-other-{index}',
            effective_path=f'ROOT/network-other-{index}',
        )
        for index in range(20)
    )
    target = 'ROOT/lz2-top/lz092026-network-cmp'
    facts += (replace(_fact('target', 'group:Default/zzz', 'BUCKET_READ'), grant_path=target, effective_path=target),)
    service = PolicyGraphService(PolicyCorpus(schema_version=1, built_at='now', facts=facts))
    page = service.get_page(path='network')
    assert page['total'] == 21
    assert len(page['grants']) == 12
    assert target not in {row['path'] for row in page['grants']}
    assert {'path': target, 'grant_count': 1} in page['paths']
    assert len(page['paths']) == 21
    assert service.get_page(path=target)['grants'][0]['statement_id'] == 'target'


def test_graph_overview_has_no_arbitrary_grants_but_retains_complete_path_discovery():
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=(_fact('one', 'group:Default/Ops', 'BUCKET_READ'),))
    overview = PolicyGraphService(corpus).get_page(overview=True)
    assert overview['needs_filter'] is True
    assert overview['grants'] == []
    assert overview['paths'] == [{'path': 'ROOT/Prod', 'grant_count': 1}]
    assert PolicyGraphService(corpus).get_page(overview=True, path='prod')['needs_filter'] is False


def test_graph_info_logging_reports_search_summary_and_unloaded_state(caplog):
    import logging

    name = 'oci-policy-analysis.application.services.policy_graph'
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=(_fact('one', 'group:Default/Ops', 'OBJECT_CREATE'),))
    with caplog.at_level(logging.INFO, logger=name):
        PolicyGraphService(corpus).get_page(resource='OBJECT_CREATE')
        PolicyGraphService(None).get_page()
    messages = [record.getMessage() for record in caplog.records if record.name == name]
    assert len(messages) == 2
    assert "filters=['resource_or_permission']" in messages[0]
    assert 'matching_grants=1 matching_paths=1 visible_grants=1 elapsed_ms=' in messages[0]
    assert 'no corpus loaded' in messages[1]


def test_policy_graph_component_is_configurable_in_both_interfaces(monkeypatch):
    from pathlib import Path

    from oci_policy_analysis.application.services.logging_service import LoggingService

    calls = []
    monkeypatch.setattr(
        'oci_policy_analysis.application.services.logging_service.set_component_level',
        lambda component, level: calls.append((component, level)),
    )
    settings = LoggingService({}).update_log_settings({'log_levels': {'policy_graph_service': 'INFO'}})
    component = 'application.services.policy_graph'
    assert settings['log_levels'][component] == 'INFO'
    assert (component, 'INFO') in calls
    package = Path(__file__).parents[1] / 'oci_policy_analysis'
    for relative in ('presentation/desktop/console_tab.py', 'presentation/web/static/logging.html'):
        assert f"'{component}'" in (package / relative).read_text()


def test_principal_discovery_includes_partial_matches_beyond_first_page():
    facts = tuple(_fact(str(index), f'group:Default/ops{index:02}', 'BUCKET_READ') for index in range(20))
    facts += (_fact('target', 'group:LZ092026/zzz-OpsTeam', 'BUCKET_READ'),)
    service = PolicyGraphService(PolicyCorpus(schema_version=1, built_at='now', facts=facts))
    result = service.get_page(principal='OPS')
    target = 'group:lz092026/zzz-opsteam'
    assert result['total'] == 21
    assert len(result['grants']) == 12
    assert target not in {row['principal'] for row in result['grants']}
    assert {'principal': target, 'grant_count': 1} in result['principals']
    assert len(result['principals']) == 21
    assert service.get_page(principal=target)['grants'][0]['statement_id'] == 'target'
    assert len(service.get_page(overview=True)['principals']) == 21
    assert service.get_page(principal='ops', effect='deny')['principals'] == []


def test_graph_search_waits_for_two_characters_or_a_filter_choice():
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=(_fact('one', 'group:Default/Ops', 'OBJECT_CREATE'),))
    service = PolicyGraphService(corpus)
    short = service.get_page(principal=' o ', overview=True)
    assert short['needs_filter'] is True
    assert short['grants'] == []
    assert short['principals']  # Suggestions remain available for choosing a principal.
    assert service.get_page(principal='op', overview=True)['needs_filter'] is False
    assert service.get_page(effect='allow', overview=True)['grants']
    assert service.get_page(principal='o')['grants']  # Existing API callers retain their behavior.


def test_all_results_returns_every_filtered_grant_and_retains_conditions():
    from dataclasses import replace

    condition = "request.permission = 'OBJECT_CREATE'"
    facts = tuple(
        replace(_fact(str(i), f'group:Default/ops{i:02}', 'OBJECT_CREATE'), condition=condition) for i in range(21)
    )
    service = PolicyGraphService(PolicyCorpus(schema_version=1, built_at='now', facts=facts))
    assert len(service.get_page(resource='OBJECT_CREATE')['grants']) == 12
    result = service.get_page(resource='OBJECT_CREATE', all_results=True, overview=True)
    assert len(result['grants']) == result['total'] == 21
    assert all(row['condition'] == condition for row in result['grants'])
    assert result['page'] == 1
    assert service.get_page(resource='missing', all_results=True)['grants'] == []
    assert service.get_page(all_results=True, overview=True)['grants'] == []


def test_graph_extracts_tester_clause_from_original_statement_when_condition_is_missing():
    from dataclasses import replace

    clause = "all { request.permission = 'OBJECT_CREATE', target.bucket.name = 'somewhere' }"
    original = f"Allow group 'Where' to manage objects in tenancy where {clause}"
    fact = _fact('conditional', 'group:Default/Ops', 'OBJECT_CREATE')
    fact = replace(fact, provenance=replace(fact.provenance, statement_text=original))
    row = PolicyGraphService(PolicyCorpus(schema_version=1, built_at='now', facts=(fact,))).get_page()['grants'][0]
    assert row['condition_clause'] == clause
    assert row['statement_text'] == original


def test_condition_handoff_accepts_full_statement_or_prefixed_clause():
    from oci_policy_analysis.application.services.condition_tester_service import extract_condition_clause

    clause = "request.permission = 'OBJECT_CREATE'"
    assert extract_condition_clause(f'WHERE {clause}') == clause
    assert extract_condition_clause(f'Allow group Ops to manage objects in tenancy where {clause}') == clause
    assert extract_condition_clause(clause) == clause
    assert extract_condition_clause('', "Allow group 'Where' to read objects in tenancy") == ''
