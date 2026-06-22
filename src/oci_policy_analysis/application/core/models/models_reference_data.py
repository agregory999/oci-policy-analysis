"""Typed models for reference-data service responses."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class ResourceFamilyRow(TypedDict):
    """Resource and its containing family when known."""

    resource: str
    family: str


class FamilyResourcesRow(TypedDict):
    """Family and its member resources."""

    family: str
    resources: list[str]


class RelatedPermissionCheck(TypedDict):
    """Advisory related permission/resource check for an API operation."""

    resource: str
    operation: NotRequired[str]
    permissions: list[str]
    applies_when: NotRequired[str]
    principal: NotRequired[str]
    reason: NotRequired[str]
    failure_hint: NotRequired[str]
    missing_permissions: NotRequired[list[str]]
    satisfied: NotRequired[bool]


class OperationPermissionsRow(TypedDict):
    """Operation metadata with required permissions."""

    api_name: str
    operation_name: str
    label: str
    permissions: list[str]
    notes: NotRequired[str]
    related_checks: NotRequired[list[RelatedPermissionCheck]]
