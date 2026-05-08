"""Shared principal-focused analysis workflows for UI/Web consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.services.analysis_service import AnalysisService
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import DynamicGroup, Group, PolicySearch, RegularPolicyStatement, User


@dataclass
class PrincipalPolicyResult:
    """Simple result wrapper for principal-oriented policy retrieval."""

    statements: list[RegularPolicyStatement]


class PrincipalAnalysisService:
    AllowedSubjectType = Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']
    _RESOURCE_TYPE_PATTERN = re.compile(
        r"request\.principal\.type\s*=\s*(['\"])(?P<rtype>[^'\"\s{}]+)\1",
        re.IGNORECASE,
    )

    """Principal-key/subject-type-first policy retrieval helper.

    Notes:
        - Keeps legacy `subject` data on statements untouched.
        - Avoids building new UI flows around `subject` filter; relies on
          exact principal selectors and/or `subject_type` filters.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the principal analysis service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='principal_analysis_service')
        self.analysis = AnalysisService(context)

    def by_exact_dynamic_groups(self, dynamic_groups: list[DynamicGroup]) -> PrincipalPolicyResult:
        """Find statements matching exact dynamic groups.

        Args:
            dynamic_groups: Dynamic groups to match exactly.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info('Filtering policies by exact dynamic groups: count=%s', len(dynamic_groups))
        filters: PolicySearch = PolicySearch(exact_dynamic_groups=dynamic_groups)
        return PrincipalPolicyResult(statements=self.analysis.filter_policy_statements(filters=filters).statements)

    def by_exact_groups_users(
        self,
        *,
        groups: list[Group] | None = None,
        users: list[User] | None = None,
    ) -> PrincipalPolicyResult:
        """Find statements matching exact groups and users.

        Args:
            groups: Group objects to match exactly.
            users: User objects to match exactly.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info(
            'Filtering policies by exact principals: groups=%s users=%s', len(groups or []), len(users or [])
        )
        filters: PolicySearch = PolicySearch(exact_groups=groups or [], exact_users=users or [])
        return PrincipalPolicyResult(statements=self.analysis.filter_policy_statements(filters=filters).statements)

    def by_subject_types(
        self,
        *,
        subject_types: list[AllowedSubjectType],
        resource_type: str = 'Any',
    ) -> PrincipalPolicyResult:
        """Find statements by subject type and optional resource type scope.

        Args:
            subject_types: Subject type filters.
            resource_type: Optional resource type scope; "Any" disables resource filter.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info(
            'Filtering policies by subject types: count=%s resource_type=%s', len(subject_types), resource_type
        )
        filters: PolicySearch
        filters = PolicySearch(subject_type=subject_types)
        statements = list(self.analysis.filter_policy_statements(filters=filters).statements)
        if resource_type != 'Any':
            target = resource_type.casefold()
            statements = [
                st
                for st in statements
                if target in self._extract_resource_types_from_conditions(str(st.get('conditions') or ''))
            ]
        return PrincipalPolicyResult(statements=statements)

    @staticmethod
    def merge_unique(*statement_lists: list[RegularPolicyStatement]) -> list[RegularPolicyStatement]:
        """Merge statement lists while removing duplicates by internal identifier.

        Args:
            *statement_lists: One or more statement lists to merge.

        Returns:
            list[RegularPolicyStatement]: Ordered unique statements.
        """
        merged: list[RegularPolicyStatement] = []
        seen: set[str] = set()
        for statements in statement_lists:
            for st in statements:
                key = str(st.get('internal_id') or st.get('statement_text') or '')
                if key and key not in seen:
                    seen.add(key)
                    merged.append(st)
        return merged

    def get_resource_types(self) -> list[str]:
        """Return dynamic Resource Type values derived from policy where clauses.

        Resource Type values are extracted from condition clauses using
        ``request.principal.type = '<value>'`` expressions.
        """
        statements = list(getattr(self.context.policy_repo, 'regular_statements', []) or [])
        discovered: dict[str, str] = {}

        for st in statements:
            cond = str(st.get('conditions') or '')
            for resource_type in self._extract_resource_types_from_conditions(cond):
                if resource_type not in discovered:
                    discovered[resource_type] = resource_type

        return ['Any', *sorted(discovered.values(), key=str.casefold)]

    @classmethod
    def _extract_resource_types_from_conditions(cls, conditions: str) -> set[str]:
        """Extract normalized request.principal.type values from a condition string."""
        cond = str(conditions or '').strip()
        if not cond or 'request.principal.type' not in cond.casefold():
            return set()
        values: set[str] = set()
        for match in cls._RESOURCE_TYPE_PATTERN.finditer(cond):
            raw_value = str(match.group('rtype') or '').strip()
            if raw_value:
                values.add(raw_value.casefold())
        return values
