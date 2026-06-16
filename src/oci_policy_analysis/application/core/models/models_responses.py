"""Search response models for IAM entities and reference data."""

from typing import Annotated, Literal, TypedDict

from .models_iam import DynamicGroup, Group, User


class UserSummary(TypedDict):
    """User search summary."""

    response_type: Literal['summary']
    total_users: Annotated[int, 'Matched user count.']
    truncated: Annotated[bool, 'True when summarized.']
    truncation_point: Annotated[int, 'Full-result threshold.']
    domain_breakdown: Annotated[dict[str, int], 'User count by domain.']
    sample_users: Annotated[list[str], 'Sample user names.']
    message: Annotated[str, 'Summary note.']


class UserSearchFull(TypedDict):
    """Full user search result."""

    response_type: Literal['full']
    users: Annotated[list[User], 'Matched users.']
    total_count: Annotated[int, 'Returned user count.']


class GroupSummary(TypedDict):
    """Group search summary."""

    response_type: Literal['summary']
    total_groups: Annotated[int, 'Matched group count.']
    truncated: Annotated[bool, 'True when summarized.']
    truncation_point: Annotated[int, 'Full-result threshold.']
    domain_breakdown: Annotated[dict[str, int], 'Group count by domain.']
    sample_groups: Annotated[list[str], 'Sample group names.']
    message: Annotated[str, 'Summary note.']


class GroupSearchFull(TypedDict):
    """Full group search result."""

    response_type: Literal['full']
    groups: Annotated[list[Group], 'Matched groups.']
    total_count: Annotated[int, 'Returned group count.']


class DynamicGroupSummary(TypedDict):
    """Dynamic group search summary."""

    response_type: Literal['summary']
    total_dynamic_groups: Annotated[int, 'Matched dynamic group count.']
    truncated: Annotated[bool, 'True when summarized.']
    truncation_point: Annotated[int, 'Full-result threshold.']
    domain_breakdown: Annotated[dict[str, int], 'Dynamic group count by domain.']
    in_use_breakdown: Annotated[dict[str, int], 'Count by in-use status.']
    sample_dynamic_groups: Annotated[list[str], 'Sample dynamic group names.']
    message: Annotated[str, 'Summary note.']


class DynamicGroupSearchFull(TypedDict):
    """Full dynamic group search result."""

    response_type: Literal['full']
    dynamic_groups: Annotated[list[DynamicGroup], 'Matched dynamic groups.']
    total_count: Annotated[int, 'Returned dynamic group count.']


UserSearchResponse = Annotated[
    UserSummary | UserSearchFull,
    'User search result.',
]

GroupSearchResponse = Annotated[
    GroupSummary | GroupSearchFull,
    'Group search result.',
]

DynamicGroupSearchResponse = Annotated[
    DynamicGroupSummary | DynamicGroupSearchFull,
    'Dynamic group search result.',
]


class ReferenceDataDiffResult(TypedDict):
    """Result model describing the outcome of comparing two cached reference data sets."""

    response_type: Literal['reference_data_diff']
    cache_a: Annotated[str, 'Name of older cache (file or key)']
    cache_b: Annotated[str, 'Name of newer cache (file or key)']
    diff_summary: Annotated[str, 'One-line or short summary of differences (added, changed, removed)']
    diff_details: Annotated[dict, 'DeepDiff result details or filtered view suitable for UI display']
    message: Annotated[str, 'Human-readable message about the diff result or info']
