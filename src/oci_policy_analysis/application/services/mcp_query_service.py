"""Focused query service for MCP policy and identity tools."""

from __future__ import annotations

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.services.analysis_service import AnalysisService
from oci_policy_analysis.common.models_iam import DynamicGroupSearch, Group, GroupSearch, User, UserSearch
from oci_policy_analysis.common.models_policy import BasePolicyStatement, DefineStatement, PolicySearch


class MCPQueryService:
    """Service facade for MCP search and filtering operations.

    MCP tools should remain thin protocol adapters. This service centralizes
    the query operations they expose so MCP follows the same service-oriented
    application model as web and desktop consumers.
    """

    def __init__(self, context: AppContext) -> None:
        """Initialize the MCP query service.

        Args:
            context: Shared application context.
        """
        self.context = context
        self.analysis = AnalysisService(context)

    def filter_policy_statements(self, filters: PolicySearch) -> list[dict]:
        """Filter loaded policy statements.

        Args:
            filters: Policy search criteria.

        Returns:
            list[dict]: Matching policy statement dictionaries.
        """
        return list(self.analysis.filter_policy_statements(filters=filters).statements)

    def get_groups_for_user(self, user: User) -> list[Group]:
        """Return groups for an exact user.

        Args:
            user: Exact user descriptor.

        Returns:
            list[Group]: Groups containing the user.
        """
        return self.context.policy_repo.get_groups_for_user(user)

    def get_users_for_group(self, group: Group) -> list[User]:
        """Return users for an exact group.

        Args:
            group: Exact group descriptor.

        Returns:
            list[User]: Users in the group.
        """
        return self.context.policy_repo.get_users_for_group(group)

    def search_users(self, filters: UserSearch) -> list[User]:
        """Search loaded users.

        Args:
            filters: User search criteria.

        Returns:
            list[User]: Matching users.
        """
        return self.context.policy_repo.filter_users(filters)

    def search_groups(self, filters: GroupSearch) -> list[Group]:
        """Search loaded groups.

        Args:
            filters: Group search criteria.

        Returns:
            list[Group]: Matching groups.
        """
        return self.context.policy_repo.filter_groups(filters)

    def search_dynamic_groups(self, filters: DynamicGroupSearch) -> list[dict]:
        """Search loaded dynamic groups.

        Args:
            filters: Dynamic group search criteria.

        Returns:
            list[dict]: Matching dynamic groups.
        """
        return self.context.policy_repo.filter_dynamic_groups(filters)

    def list_cross_tenancy_aliases(self) -> list[DefineStatement]:
        """Return loaded cross-tenancy aliases.

        Returns:
            list[DefineStatement]: Defined aliases known to the active policy data.
        """
        return list(getattr(self.context.policy_repo, 'defined_aliases', []) or [])

    def filter_cross_tenancy_policies_by_alias(self, alias: str) -> list[BasePolicyStatement]:
        """Return cross-tenancy statements referencing an alias.

        Args:
            alias: Alias to match.

        Returns:
            list[BasePolicyStatement]: Matching cross-tenancy policy statements.
        """
        return self.context.policy_repo.filter_cross_tenancy_policy_statements([alias])
