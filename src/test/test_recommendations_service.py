"""Tests for recommendations dashboard payload shaping."""

from types import SimpleNamespace

from oci_policy_analysis.application.core.engine.recommendation_actions import overly_broad_statement_guidance
from oci_policy_analysis.application.services.recommendations_service import RecommendationsService


def test_summary_counts_group_by_severity_and_category() -> None:
    service = RecommendationsService.__new__(RecommendationsService)

    counts = service._summary_counts(
        [
            {'Priority': 'High', 'Category': 'Workload Identity'},
            {'Priority': 'High', 'Category': 'Resource Principal'},
            {'Priority': 'Medium', 'Category': 'Resource Principal'},
        ]
    )

    assert counts['severity'] == {'High': 2, 'Medium': 1}
    assert counts['category'] == {'Workload Identity': 1, 'Resource Principal': 2}


def test_overly_broad_deny_guidance_reviews_conditions() -> None:
    guidance = overly_broad_statement_guidance({'action': 'deny', 'conditions': "where request.user.id = 'alice'"})

    assert guidance['Reason'].startswith("Revokes 'manage all-resources'")
    assert 'effective path and target resources' in guidance['Action']
    assert 'test the conditions' in guidance['Action']


def test_overly_broad_allow_guidance_omits_condition_testing_without_conditions() -> None:
    guidance = overly_broad_statement_guidance({'action': 'allow', 'conditions': ''})

    assert guidance['Reason'].startswith("Grants 'manage all-resources'")
    assert 'test the conditions' not in guidance['Action']


def test_supersession_rows_preserve_candidate_and_evidence_details() -> None:
    service = RecommendationsService.__new__(RecommendationsService)
    service.context = SimpleNamespace(
        policy_repo=SimpleNamespace(
            regular_statements=[
                {
                    'internal_id': 'candidate',
                    'policy_name': 'Candidate Policy',
                    'compartment_path': 'ROOT/A',
                    'effective_path': 'ROOT/A/B',
                    'statement_text': 'allow group Devs to read buckets in compartment B',
                }
            ]
        ),
        intelligence=SimpleNamespace(
            overlay={
                'supersessions': [
                    {
                        'statement_internal_id': 'candidate',
                        'classification': 'Single Statement',
                        'candidate_permissions': ['bucket_read'],
                        'notes': 'Fully covered.',
                        'evidence': [{'policy_name': 'Ancestor Policy', 'relationship': 'Ancestor'}],
                    }
                ]
            }
        ),
    )

    rows = service._supersession_rows()

    assert rows[0]['Classification'] == 'Single Statement'
    assert rows[0]['Evidence'][0]['policy_name'] == 'Ancestor Policy'


def test_supersession_detail_keeps_full_source_and_separates_conditional_coverage():
    from copy import deepcopy

    candidate = {
        'internal_id': 'c',
        'policy_name': '<Policy>',
        'statement_text': 'x' * 900,
        'conditions': "where request.user.id = 'alice'",
        'effective_path': 'ROOT/A',
    }
    evidence = [
        {
            'policy_name': 'Unconditional',
            'effective_path': 'ROOT',
            'covered_permissions': ['READ'],
            'conditional': False,
        },
        {
            'policy_name': 'Conditional',
            'effective_path': 'ROOT/A',
            'covered_permissions': ['READ', 'WRITE'],
            'conditional': True,
        },
    ]
    context = SimpleNamespace(
        policy_repo=SimpleNamespace(regular_statements=[candidate]),
        intelligence=SimpleNamespace(
            overlay={
                'supersessions': [
                    {'statement_internal_id': 'c', 'candidate_permissions': ['READ', 'WRITE'], 'evidence': evidence}
                ]
            }
        ),
    )
    before = deepcopy(context.intelligence.overlay)
    service = RecommendationsService(context)
    detail = service.supersession_details('c')
    assert detail['candidate']['statement_text'] == 'x' * 900
    assert detail['candidate']['conditions'] == candidate['conditions']
    assert 'Unconditional' in detail['coverage'][0]['Unconditional coverage']
    assert 'Conditional' not in detail['coverage'][0]['Unconditional coverage']
    assert detail['coverage'][1]['Unconditional coverage'] == 'Not resolved'
    assert 'Conditional' in detail['coverage'][1]['Conditional evidence (review only)']
    detail['finding']['Evidence'].clear()
    assert context.intelligence.overlay == before
    assert service.supersession_details('obsolete') is None


def test_dashboard_preview_does_not_fetch_missing_live_limits():
    from unittest.mock import Mock

    fetch = Mock(side_effect=AssertionError('Preview must not call OCI'))
    repo = SimpleNamespace(
        tenancy_policy_limits={},
        current_cache_name='',
        loaded_from_compliance_output=False,
        limits_client=object(),
        fetch_tenancy_policy_statement_limits=fetch,
        compartments=[],
        policies=[],
        regular_statements=[],
    )
    context = SimpleNamespace(policy_repo=repo, intelligence=SimpleNamespace(overlay={}))
    dashboard = RecommendationsService(context).get_dashboard_payload(fetch_limits=False)
    assert dashboard['tenancy_policy_limits']['max_chain_count'] == 0
    fetch.assert_not_called()


def test_refresh_restores_prospects_and_retargets_manager_after_partial_failure(monkeypatch):
    from copy import deepcopy
    from unittest.mock import Mock

    import pytest

    old_engine = SimpleNamespace(
        get_prospective_statements=lambda: [{'internal_id': 'p-1', 'statement_text': 'local draft'}]
    )
    new_engine = SimpleNamespace(set_prospective_statements=Mock())
    manager = SimpleNamespace(bind_simulation_engine=Mock())
    context = SimpleNamespace(simulation=old_engine, settings={}, _prospective_service=manager)

    def fail(context, **kwargs):
        context.simulation = new_engine
        raise RuntimeError('partial pipeline failure')

    monkeypatch.setattr('oci_policy_analysis.application.post_load.run_post_load_pipeline', fail)
    service = RecommendationsService(context)
    with pytest.raises(RuntimeError, match='partial pipeline failure'):
        service.refresh_analysis(settings={'enabled_intelligence_checks': ['risk'], 'unrelated': 'ignored'})
    new_engine.set_prospective_statements.assert_called_once_with(deepcopy(old_engine.get_prospective_statements()))
    manager.bind_simulation_engine.assert_called_once_with(new_engine)
    assert context.settings == {'enabled_intelligence_checks': ['risk']}
