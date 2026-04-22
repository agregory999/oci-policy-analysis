"""Service facade for reference data lookups."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo


@dataclass
class ReferenceDataService:
    """Expose reference data lookup helpers for UI/web consumers."""

    reference_data: ReferenceDataRepo

    def __post_init__(self) -> None:
        """Initialize logger after dataclass construction.

        Returns:
            None
        """
        self.logger = get_logger(component='reference_data_service')

    def list_resources(self) -> list[str]:
        """List known resource identifiers.

        Returns:
            list[str]: Sorted resource names.
        """
        return sorted(self.reference_data.data.get('resources', {}).keys())

    def list_families(self) -> list[str]:
        """List known resource family identifiers.

        Returns:
            list[str]: Sorted family names.
        """
        return sorted(self.reference_data.data.get('families', {}).keys())

    def get_permissions(self, entity: str, verb: str, action: str = 'allow') -> list[str]:
        """Resolve permissions for a target entity and verb.

        Args:
            entity: Entity or resource key.
            verb: IAM verb to evaluate.
            action: Policy action, typically allow or deny.

        Returns:
            list[str]: Matching permissions.
        """
        return self.reference_data.get_permissions(entity, verb, action)

    def get_permission_risk(self, permission: str, resource: str | None = None) -> int:
        """Get risk score for a permission/resource pairing.

        Args:
            permission: Permission identifier.
            resource: Optional resource scope.

        Returns:
            int: Risk score.
        """
        return int(self.reference_data.get_permission_risk(permission, resource))

    def get_source(self, entity: str) -> str:
        """Get source metadata for an entity.

        Args:
            entity: Entity or resource key.

        Returns:
            str: Source descriptor.
        """
        return self.reference_data.get_source(entity)

    def get_family(self, resource_name: str) -> str | None:
        """Get containing family for a resource name.

        Args:
            resource_name: Resource name.

        Returns:
            str | None: Family name when available.
        """
        return self.reference_data.get_containing_family(resource_name)
