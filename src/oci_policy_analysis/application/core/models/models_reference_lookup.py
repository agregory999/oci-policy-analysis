"""Strict, structured contracts for bundled reference catalog lookups."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IAMVerb = Literal['inspect', 'read', 'use', 'manage']
MatchMode = Literal['search', 'exact']


class ReferenceQuery(BaseModel):
    """Validate bounded discovery inputs without allowing unrecognized fields."""

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(
        min_length=1, max_length=200, description='Canonical identifier, declared alias or everyday search wording.'
    )
    match: MatchMode = Field(default='search', description='Exact identifiers/aliases only, or ranked text discovery.')
    limit: int = Field(default=10, ge=1, le=25, description='Maximum matches per page, from 1 to 25.')
    cursor: str | None = Field(
        default=None, max_length=512, description='Opaque next_cursor from the same lookup and catalog.'
    )


class ResourceReferenceQuery(ReferenceQuery):
    """Find resources or families and optionally expand one cumulative IAM verb."""

    kind: Literal['resource', 'family', 'either'] = 'either'
    verb: IAMVerb | None = None


class OperationReferenceQuery(ReferenceQuery):
    """Find qualified API operations, optionally within one catalog API group."""

    api_group: str | None = Field(default=None, min_length=1, max_length=100)


class PermissionReferenceQuery(ReferenceQuery):
    """Find permissions and reverse mappings, optionally for one exact resource."""

    resource: str | None = Field(default=None, min_length=1, max_length=200)


class ReferenceRecord(BaseModel):
    """Common match identity, discovery evidence and catalog provenance."""

    model_config = ConfigDict(extra='forbid')
    canonical_name: str
    match_type: Literal['identifier', 'alias', 'search_term', 'text']
    matched_text: str
    notes: str = ''
    source_urls: list[str] = Field(default_factory=list)
    catalog_status: str = 'unreviewed'
    mapping_status: str = 'mapped'


class PermissionExpansion(BaseModel):
    """A bounded cumulative permission list, with an explicit total and truncation."""

    permissions: list[str]
    total_count: int
    truncated: bool


class ResourceReferenceMatch(ReferenceRecord):
    """Resource/family identity, membership and cumulative allow-verb expansion."""

    kind: Literal['resource', 'family']
    source_resource_name: str
    aliases: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    families: list[str] = Field(default_factory=list)
    member_resources: list[str] = Field(default_factory=list)
    member_count: int = 0
    members_truncated: bool = False
    unmapped_member_resources: list[str] = Field(default_factory=list)
    unmapped_member_count: int = 0
    supported_verbs: list[str] = Field(default_factory=list)
    permissions_by_verb: dict[IAMVerb, PermissionExpansion]


class RelatedReferenceCheck(BaseModel):
    """Conditional or related API requirements retained from the catalog."""

    model_config = ConfigDict(extra='allow')
    resource: str = ''
    permissions: list[str] = Field(default_factory=list)
    operation: str = ''
    applies_when: str = ''
    reason: str = ''


class OperationReferenceMatch(ReferenceRecord):
    """Qualified API identity, known requirements and unresolved resource mappings."""

    api_group: str
    operation_name: str
    request_operation: str
    permissions: list[str]
    permission_count: int
    permissions_truncated: bool
    unmapped_permissions: list[str]
    related_checks: list[RelatedReferenceCheck] = Field(default_factory=list)


class PermissionResourceMatch(BaseModel):
    """Lowest catalog granting verb for one resource, not a complete policy plan."""

    resource: str
    source_resource_name: str
    families: list[str]
    lowest_granting_verb: IAMVerb
    granting_verbs: list[IAMVerb]
    additional_permissions: PermissionExpansion
    source_urls: list[str]


class PermissionReferenceMatch(ReferenceRecord):
    """Permission evidence from resource tables and operation requirements."""

    resource_mappings: list[PermissionResourceMatch]
    resource_mapping_count: int
    resource_mappings_truncated: bool
    operations: list[str]
    operation_count: int
    operations_truncated: bool


class ResourceReferenceResult(BaseModel):
    """Structured resource discovery and expansion result."""

    model_config = ConfigDict(extra='forbid')
    catalog_id: str
    catalog_version: str
    total_matches: int
    matches: list[ResourceReferenceMatch]
    next_cursor: str | None
    warnings: list[str]


class OperationReferenceResult(BaseModel):
    """Structured API operation discovery result."""

    model_config = ConfigDict(extra='forbid')
    catalog_id: str
    catalog_version: str
    total_matches: int
    matches: list[OperationReferenceMatch]
    next_cursor: str | None
    warnings: list[str]


class PermissionReferenceResult(BaseModel):
    """Structured permission discovery and reverse mapping result."""

    model_config = ConfigDict(extra='forbid')
    catalog_id: str
    catalog_version: str
    total_matches: int
    matches: list[PermissionReferenceMatch]
    next_cursor: str | None
    warnings: list[str]
