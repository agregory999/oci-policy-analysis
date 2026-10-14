"""Service facade for policy statement filtering."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.models.models import PolicySearch, RegularPolicyStatement
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict


@dataclass
class FilterResult:
    """Statement-search result over the loaded repository.

    Attributes:
        total: Number of source statements in the searched repository or subset.
        matched: Number of statements satisfying the filters.
        statements: Matching normalized source statement records, including invalid
            records when permitted by the filters.
    """

    total: int
    matched: int
    statements: list[RegularPolicyStatement]


class AnalysisService:
    """Filter source statements without requiring a presentation adapter.

    Args:
        context: Runtime containing the active policy repository.

    Attributes:
        context: Shared runtime queried on each operation.
        logger: Component logger for search diagnostics.

    Notes:
        Queries source statements rather than only admitted corpus facts. Empty
        results do not establish absence of OCI access in an incomplete snapshot.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the analysis service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='analysis_service')

    def filter_policy_statements(self, filters: PolicySearch) -> FilterResult:
        """Filter all loaded policy statements by provided filters.

        Args:
            filters: Search filters applied to policy statements.

        Returns:
            FilterResult: Total statement count and matched statements.
        """
        self.logger.info('Filtering policy statements via AnalysisService: %s', filters)
        repo = self.context.policy_repo
        statements = repo.filter_policy_statements(filters=filters)
        total = len(getattr(repo, 'regular_statements', []) or [])
        self.logger.info('Filter complete: matched=%s total=%s', len(statements), total)
        return FilterResult(total=total, matched=len(statements), statements=statements)

    def filter_policy_statements_from_payload(self, payload: dict[str, object]) -> FilterResult:
        """Build filters from raw payload and execute statement filtering.

        Args:
            payload: Dictionary payload containing raw filter values.

        Returns:
            FilterResult: Filtered statement result.
        """
        filters = build_policy_search_from_dict(payload)
        return self.filter_policy_statements(filters=filters)

    def filter_policy_statements_subset(
        self, *, filters: PolicySearch, statements: list[RegularPolicyStatement]
    ) -> FilterResult:
        """Filter a provided subset of statements with policy search criteria.

        Args:
            filters: Search filters applied to the subset.
            statements: Preselected statements to search within.

        Returns:
            FilterResult: Result scoped to the provided statement subset.
        """
        self.logger.info('Filtering subset via AnalysisService: %s', filters)
        repo = self.context.policy_repo
        results = repo.filter_policy_statements(filters=filters, statements=statements)
        self.logger.info('Subset filter complete: matched=%s total=%s', len(results), len(statements))
        return FilterResult(total=len(statements), matched=len(results), statements=results)
