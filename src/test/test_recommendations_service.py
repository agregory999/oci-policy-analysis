"""Tests for recommendations dashboard payload shaping."""

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
