"""Recommendation summaries must use the loaded tenancy limit."""

from types import SimpleNamespace

from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab


def _tab(chain_limit, cumulative_count):
    repo = SimpleNamespace(
        tenancy_policy_limits={'policy_statements_per_compartment_chain_count': chain_limit},
        compartments=[{'statement_count_cumulative': cumulative_count}],
    )
    tab = object.__new__(PolicyRecommendationsTab)
    tab.policy_repo = repo
    tab.app = SimpleNamespace(
        policy_intelligence=SimpleNamespace(overlay={'recommendations': []}),
        policy_compartment_analysis=repo,
    )
    return tab


def test_summary_uses_custom_tenancy_limit_instead_of_500_default():
    recommendations = _tab(900, 600)._get_recommendation_summary()

    assert not any(item.get('Category') == 'Limits' for item in recommendations)


def test_summary_reports_custom_limit_when_compartment_exceeds_it():
    recommendations = _tab(900, 901)._get_recommendation_summary()

    limit_recommendation = next(item for item in recommendations if item.get('Category') == 'Limits')
    assert 'tenancy limit of 900' in limit_recommendation['Notes']


def test_summary_does_not_assume_a_limit_when_none_is_supplied():
    recommendations = _tab(None, 600)._get_recommendation_summary()

    assert not any(item.get('Category') == 'Limits' for item in recommendations)
