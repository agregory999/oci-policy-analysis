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
