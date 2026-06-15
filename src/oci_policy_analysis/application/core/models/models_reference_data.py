"""Typed models for reference-data service responses."""

from __future__ import annotations

from typing import TypedDict


class ResourceFamilyRow(TypedDict):
    """Resource and its containing family when known."""

    resource: str
    family: str


class FamilyResourcesRow(TypedDict):
    """Family and its member resources."""

    family: str
    resources: list[str]


class OperationPermissionsRow(TypedDict):
    """Operation metadata with required permissions."""

    api_name: str
    operation_name: str
    label: str
    permissions: list[str]
