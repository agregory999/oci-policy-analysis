"""Service facade for reference data lookups."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.models.models_reference_data import (
    FamilyResourcesRow,
    OperationPermissionsRow,
    ResourceFamilyRow,
)
from oci_policy_analysis.application.core.repo import ReferenceDataRepo
from oci_policy_analysis.application.core.support.logger import get_logger


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

    def check_overlap(
        self,
        entity1: str,
        verb1: str,
        action1: str,
        entity2: str,
        verb2: str,
        action2: str,
    ) -> list[str]:
        """Check overlapping permissions between two statement-style selectors.

        Args:
            entity1: First resource/family entity.
            verb1: First verb.
            action1: First action (allow/deny).
            entity2: Second resource/family entity.
            verb2: Second verb.
            action2: Second action (allow/deny).

        Returns:
            list[str]: Overlapping permissions.
        """
        return self.reference_data.check_overlap_params(entity1, verb1, action1, entity2, verb2, action2)

    def get_family(self, resource_name: str) -> str | None:
        """Get containing family for a resource name.

        Args:
            resource_name: Resource name.

        Returns:
            str | None: Family name when available.
        """
        return self.reference_data.get_containing_family(resource_name)

    @staticmethod
    def _dedupe_keep_order(tokens: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for token in tokens:
            key = token.strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(token.strip())
        return out

    def list_resources_with_family(self) -> list[ResourceFamilyRow]:
        """List known non-family resources with resolved family names when available."""

        resources = self.list_resources()
        rows: list[ResourceFamilyRow] = []
        for resource in resources:
            family = self.get_family(resource) or ''
            rows.append({'resource': resource, 'family': family})
        return rows

    def list_families_with_resources(self) -> list[FamilyResourcesRow]:
        """List known families and their member resources."""

        families = self.reference_data.data.get('families', {})
        rows: list[FamilyResourcesRow] = []
        for family in sorted(families.keys()):
            family_data = families.get(family, {})
            resources = sorted(str(r).strip() for r in family_data.get('resources', []) if str(r).strip())
            rows.append({'family': family, 'resources': resources})
        return rows

    def list_operations_with_permissions(self) -> list[OperationPermissionsRow]:
        """List API operations grouped metadata for permission lookup helpers."""

        operations_by_api = self.reference_data.data.get('operations_by_api', {})
        rows: list[OperationPermissionsRow] = []
        for api_name in sorted(operations_by_api.keys()):
            ops = operations_by_api.get(api_name, {})
            if not isinstance(ops, dict):
                continue
            for operation_name in sorted(ops.keys()):
                meta = ops.get(operation_name, {})
                permissions = [
                    str(p).strip().upper()
                    for p in (meta.get('permissions', []) if isinstance(meta, dict) else [])
                    if str(p).strip()
                ]
                rows.append(
                    {
                        'api_name': str(api_name),
                        'operation_name': str(operation_name),
                        'label': f'{api_name}:{operation_name}',
                        'permissions': permissions,
                    }
                )
        return rows

    def build_resource_filter_from_resource(
        self, resource: str, *, include_all_resources: bool = False
    ) -> tuple[str, list[str]]:
        """Build `resource|family|all-resources` string for a resource selection."""

        resource_clean = str(resource or '').strip()
        if not resource_clean:
            return '', ['resource is required']

        family = self.get_family(resource_clean)
        warnings: list[str] = []
        if not family:
            warnings.append(f'No containing family found for resource "{resource_clean}".')

        ordered = [resource_clean]
        if family:
            ordered.append(family)
        if include_all_resources:
            ordered.append('all-resources')
        return '|'.join(self._dedupe_keep_order(ordered)), warnings

    def build_resource_filter_from_family(
        self, family: str, *, include_all_resources: bool = False
    ) -> tuple[str, list[str]]:
        """Build `family|resource1|...|all-resources` string for a family selection."""

        family_clean = str(family or '').strip()
        if not family_clean:
            return '', ['family is required']

        family_map = self.reference_data.family_name_map or {}
        canonical_family = family_map.get(family_clean.casefold(), family_clean)
        families = self.reference_data.data.get('families', {})
        family_data = families.get(canonical_family)
        warnings: list[str] = []
        member_resources: list[str] = []

        if isinstance(family_data, dict):
            member_resources = [str(r).strip() for r in family_data.get('resources', []) if str(r).strip()]
        else:
            warnings.append(f'Family "{family_clean}" was not found in reference data.')

        ordered = [canonical_family, *member_resources]
        if include_all_resources:
            ordered.append('all-resources')
        return '|'.join(self._dedupe_keep_order(ordered)), warnings
