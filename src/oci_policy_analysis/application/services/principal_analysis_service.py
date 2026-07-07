"""Shared principal-focused analysis workflows for UI/Web consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.models.models import (
    DynamicGroup,
    Group,
    PolicySearch,
    Principal,
    RegularPolicyStatement,
    User,
)
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.analysis_service import AnalysisService


@dataclass
class PrincipalPolicyResult:
    """Simple result wrapper for principal-oriented policy retrieval."""

    statements: list[RegularPolicyStatement]


class PrincipalAnalysisService:
    """Retrieve policy statements using structured principal selectors."""

    AllowedSubjectType = Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']
    _RESOURCE_TYPE_PATTERN = re.compile(
        r"request\.principal\.type\s*=\s*(['\"])(?P<rtype>[^'\"\s{}]+)\1",
        re.IGNORECASE,
    )

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

    @staticmethod
    def _principal_from_group(group: Group) -> Principal:
        principal: Principal = {
            'principal_type': 'group',
            'domain_name': group.get('domain_name') or 'Default',
            'name': group.get('group_name') or '',
        }
        if group.get('group_ocid'):
            principal['ocid'] = str(group.get('group_ocid'))
        return principal

    @staticmethod
    def _principal_from_dynamic_group(dynamic_group: DynamicGroup) -> Principal:
        principal: Principal = {
            'principal_type': 'dynamic-group',
            'domain_name': dynamic_group.get('domain_name') or 'Default',
            'name': dynamic_group.get('dynamic_group_name') or '',
        }
        if dynamic_group.get('dynamic_group_ocid'):
            principal['ocid'] = str(dynamic_group.get('dynamic_group_ocid'))
        return principal

    @staticmethod
    def _principal_from_user(user: User) -> Principal:
        principal: Principal = {
            'principal_type': 'user',
            'domain_name': user.get('domain_name') or 'Default',
            'name': user.get('user_name') or '',
        }
        if user.get('user_ocid'):
            principal['ocid'] = str(user.get('user_ocid'))
        return principal

    def by_exact_dynamic_groups(self, dynamic_groups: list[DynamicGroup]) -> PrincipalPolicyResult:
        """Find statements matching exact dynamic groups.

        Args:
            dynamic_groups: Dynamic groups to match exactly.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        return self.by_dynamic_groups(dynamic_groups)

    def by_dynamic_groups(self, dynamic_groups: list[DynamicGroup]) -> PrincipalPolicyResult:
        """Find statements matching dynamic group principals.

        Args:
            dynamic_groups: Dynamic groups to match as principal selectors.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info('Filtering policies by dynamic group principals: count=%s', len(dynamic_groups))
        principals = [self._principal_from_dynamic_group(dg) for dg in dynamic_groups]
        if not principals:
            return PrincipalPolicyResult(statements=[])
        filters: PolicySearch = PolicySearch(principals=principals)
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
        return self.by_groups_users(groups=groups, users=users)

    def by_groups_users(
        self,
        *,
        groups: list[Group] | None = None,
        users: list[User] | None = None,
    ) -> PrincipalPolicyResult:
        """Find statements matching group and user principals.

        User selectors are expanded by repository principal equivalence, so
        group-based policies for loaded user memberships are included.

        Args:
            groups: Group objects to match as principal selectors.
            users: User objects to match as principal selectors.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info(
            'Filtering policies by group/user principals: groups=%s users=%s', len(groups or []), len(users or [])
        )
        principals = [self._principal_from_group(group) for group in groups or []]
        principals.extend(self._principal_from_user(user) for user in users or [])
        if not principals:
            return PrincipalPolicyResult(statements=[])
        filters: PolicySearch = PolicySearch(principals=principals)
        return PrincipalPolicyResult(statements=self.analysis.filter_policy_statements(filters=filters).statements)

    def by_subject_types(
        self,
        *,
        subject_types: list[AllowedSubjectType],
        resource_type: str = 'Any',
        resource_compartment_ocid: str = '',
    ) -> PrincipalPolicyResult:
        """Find statements by subject type and optional resource type scope.

        Args:
            subject_types: Subject type filters.
            resource_type: Optional resource type scope; "Any" disables resource type evidence filtering.
            resource_compartment_ocid: Optional request.principal.compartment.id evidence filter.

        Returns:
            PrincipalPolicyResult: Matched policy statements.
        """
        self.logger.info(
            'Filtering policies by subject types: count=%s resource_type=%s resource_compartment_ocid=%s',
            len(subject_types),
            resource_type,
            bool(str(resource_compartment_ocid or '').strip()),
        )
        filters: PolicySearch
        resource_type_filter = str(resource_type or 'Any').strip()
        compartment_filter = str(resource_compartment_ocid or '').strip()
        if resource_type_filter != 'Any' or compartment_filter:
            principal: Principal = {'principal_type': 'resource-principal'}
            if resource_type_filter != 'Any':
                principal['resource_type'] = resource_type_filter
            if compartment_filter:
                principal['resource_compartment_ocid'] = compartment_filter
            filters = PolicySearch(subject_type=subject_types, principal=principal)
            return PrincipalPolicyResult(
                statements=list(self.analysis.filter_policy_statements(filters=filters).statements)
            )

        filters = PolicySearch(subject_type=subject_types)
        statements = list(self.analysis.filter_policy_statements(filters=filters).statements)
        return PrincipalPolicyResult(statements=statements)

    def by_oke_workload_identity(
        self,
        *,
        workload_namespace: str = '',
        workload_service_account: str = '',
        workload_cluster_id: str = '',
        subject_types: list[AllowedSubjectType] | None = None,
    ) -> PrincipalPolicyResult:
        """Find statements matching OKE workload identity evidence."""
        self.logger.info(
            'Filtering policies by OKE workload identity: namespace=%s service_account=%s cluster_id=%s',
            bool(str(workload_namespace or '').strip()),
            bool(str(workload_service_account or '').strip()),
            bool(str(workload_cluster_id or '').strip()),
        )
        principal: Principal = {'principal_type': 'oke-workload-identity'}
        if workload_namespace:
            principal['workload_namespace'] = workload_namespace
        if workload_service_account:
            principal['workload_service_account'] = workload_service_account
        if workload_cluster_id:
            principal['workload_cluster_id'] = workload_cluster_id
        filters: PolicySearch = {'principal': principal}
        if subject_types:
            filters['subject_type'] = subject_types
        return PrincipalPolicyResult(statements=self.analysis.filter_policy_statements(filters=filters).statements)

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

    def get_workload_identity_values(self) -> dict[str, list[str]]:
        """Return discovered OKE workload identity selector values from parsed conditions."""
        statements = list(getattr(self.context.policy_repo, 'regular_statements', []) or [])
        namespaces: dict[str, str] = {}
        service_accounts: dict[str, str] = {}
        cluster_ids: dict[str, str] = {}

        for st in statements:
            cond = str(st.get('conditions') or '')
            atoms = st.get('condition_atoms')
            if not isinstance(atoms, list):
                atoms = []
            if not atoms and cond:
                try:
                    atoms = list((st.get('where_clause_structure') or {}).get('atoms', []))
                except Exception:
                    atoms = []
            for atom in atoms:
                if not isinstance(atom, dict):
                    continue
                left = str(atom.get('normalized_left') or atom.get('left') or '').casefold()
                right = str(atom.get('right') or '').strip()
                if not right:
                    continue
                if left == 'request.principal.namespace':
                    namespaces.setdefault(right, right)
                elif left == 'request.principal.service_account':
                    service_accounts.setdefault(right, right)
                elif left == 'request.principal.cluster_id':
                    cluster_ids.setdefault(right, right)

        return {
            'namespaces': sorted(namespaces.values(), key=str.casefold),
            'service_accounts': sorted(service_accounts.values(), key=str.casefold),
            'cluster_ids': sorted(cluster_ids.values(), key=str.casefold),
        }

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
