"""Search response models for IAM entities and reference data."""

from typing import Annotated, Literal, TypedDict

from .models_iam import DynamicGroup, Group, User


class UserSummary(TypedDict):
    """Lightweight summary of user search results when full details are not shown."""

    response_type: Literal['summary']
    total_users: Annotated[int, 'Total number of users that matched the search criteria']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of users included before truncation occurred']
    domain_breakdown: Annotated[dict[str, int], 'Count of users by domain (e.g., {"Default": 45, "federated": 29})']
    sample_users: Annotated[list[str], 'Sample of user names to give context (limited to first 10-20 users)']
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class UserSearchFull(TypedDict):
    """Model representing a full user search result set (all users)."""

    response_type: Literal['full']
    users: Annotated[list[User], 'Complete list of users']
    total_count: Annotated[int, 'Total number of users returned']


class GroupSummary(TypedDict):
    """Lightweight summary of group search results."""

    response_type: Literal['summary']
    total_groups: Annotated[int, 'Total number of groups that matched the search criteria']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of groups included before truncation occurred']
    domain_breakdown: Annotated[dict[str, int], 'Count of groups by domain (e.g., {"Default": 45, "federated": 29})']
    sample_groups: Annotated[list[str], 'Sample of group names to give context (limited to first 10-20 groups)']
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class GroupSearchFull(TypedDict):
    """Model representing a full group search result set (all groups)."""

    response_type: Literal['full']
    groups: Annotated[list[Group], 'Complete list of groups']
    total_count: Annotated[int, 'Total number of groups returned']


class DynamicGroupSummary(TypedDict):
    """Lightweight summary of dynamic group search results."""

    response_type: Literal['summary']
    total_dynamic_groups: Annotated[int, 'Total number of dynamic groups that matched the search criteria']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of dynamic groups included before truncation occurred']
    domain_breakdown: Annotated[
        dict[str, int], 'Count of dynamic groups by domain (e.g., {"Default": 45, "federated": 29})'
    ]
    in_use_breakdown: Annotated[
        dict[str, int], 'Count of dynamic groups by usage status (e.g., {"in_use": 25, "not_in_use": 10})'
    ]
    sample_dynamic_groups: Annotated[
        list[str], 'Sample of dynamic group names to give context (limited to first 10-20 dynamic groups)'
    ]
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class DynamicGroupSearchFull(TypedDict):
    """Model representing a full dynamic group search result set."""

    response_type: Literal['full']
    dynamic_groups: Annotated[list[DynamicGroup], 'Complete list of dynamic groups']
    total_count: Annotated[int, 'Total number of dynamic groups returned']


UserSearchResponse = Annotated[
    UserSummary | UserSearchFull,
    'Response from user search operations - either summary or full data based on size constraints',
]

GroupSearchResponse = Annotated[
    GroupSummary | GroupSearchFull,
    'Response from group search operations - either summary or full data based on size constraints',
]

DynamicGroupSearchResponse = Annotated[
    DynamicGroupSummary | DynamicGroupSearchFull,
    'Response from dynamic group search operations - either summary or full data based on size constraints',
]


class ReferenceDataDiffResult(TypedDict):
    """Result model describing the outcome of comparing two cached reference data sets."""

    response_type: Literal['reference_data_diff']
    cache_a: Annotated[str, 'Name of older cache (file or key)']
    cache_b: Annotated[str, 'Name of newer cache (file or key)']
    diff_summary: Annotated[str, 'One-line or short summary of differences (added, changed, removed)']
    diff_details: Annotated[dict, 'DeepDiff result details or filtered view suitable for UI display']
    message: Annotated[str, 'Human-readable message about the diff result or info']
