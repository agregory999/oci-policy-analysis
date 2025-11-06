##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# models.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

from typing import Annotated, Literal, NotRequired, TypedDict


# Data Models for Policies, Dynamic Groups, Users, and Groups
class Group(TypedDict):
    """
    Represents an Exact OCI IAM group entry.
    Groups need a domain and name to be unique.
    Domain should be provided for non-default domain.
    """

    domain_name: NotRequired[Annotated[str, 'The domain of the group. If not provided, the default domain.']]
    group_name: Annotated[str, 'The name of the group.']
    group_id: NotRequired[Annotated[str, 'The ID of the group. Not required for filters.']]
    group_ocid: NotRequired[Annotated[str, 'The OCID of the group. Not required for filters.']]
    description: NotRequired[Annotated[str, 'The description of the group. Not required for filters.']]


class User(TypedDict):
    """
    Represents an Exact OCI IAM user entry.
    Only requires a user_name to be unique within a domain.
    Domain should be provided for non-default domain.
    """

    domain_name: NotRequired[Annotated[str, 'The domain of the user. If not provided, the default domain.']]
    user_name: Annotated[str, 'The user name. Required']
    user_ocid: NotRequired[Annotated[str, 'The user OCID. Not required for filters.']]
    display_name: NotRequired[Annotated[str, 'The display name. Not required for filters.']]
    email: NotRequired[Annotated[str, 'The primary email address. Not required for filters.']]
    user_id: NotRequired[Annotated[str, 'The user ID. Not required for filters.']]
    groups: NotRequired[Annotated[list[str], 'List of group OCIDs the user belongs to. Not required for filters.']]


class DynamicGroup(TypedDict):
    """
    Represents an Exact OCI IAM dynamic group entry.
    Dynamic groups need a domain and name to be unique.
    Domain should be provided for non-default domain.
    """

    domain_name: NotRequired[Annotated[str, 'The domain of the group. If not provided, the default domain.']]
    dynamic_group_name: Annotated[str, 'The name of the dynamic group.']
    dynamic_group_ocid: NotRequired[Annotated[str, 'The OCID of the dynamic group. Not required for filters.']]
    dynamic_group_id: NotRequired[Annotated[str, 'The ID of the dynamic group. Not required for filters.']]
    matching_rule: NotRequired[
        Annotated[str, 'The matching rule expression for the dynamic group. Not required for filters.']
    ]
    description: NotRequired[Annotated[str | None, 'The description of the dynamic group. Not required for filters.']]
    in_use: NotRequired[
        Annotated[bool, 'True if the dynamic group is referenced by any policies. Not required for filters.']
    ]
    creation_time: NotRequired[Annotated[str, 'The creation time of the dynamic group. Not required for filters.']]
    created_by_ocid: NotRequired[
        Annotated[str, 'The OCID of the user who created the dynamic group. Not required for filters.']
    ]
    created_by_name: NotRequired[
        Annotated[str, 'The name of the user who created the dynamic group. Not required for filters.']
    ]


# Search Models
class GroupSearch(TypedDict, total=False):
    """
    Represents filters for OCI IAM groups.

    This structure is used by MCP tools that query or filter cached group data.
    Each field narrows results; lists within a field apply OR logic.
    Providing multiple fields applies AND logic.
    Providing no fields returns all groups.
    """

    domain_name: Annotated[
        list[str],
        'Domain name(s) to filter groups by. If provided, use the specified domain(s) to search. If not provided, the default domain is used.',
    ]

    group_name: Annotated[list[str], 'Group display name(s) to match. Accepts full or partial names.']

    group_ocid: Annotated[list[str], 'A list of OCIDs or partial OCIDs of the group.']


class UserSearch(TypedDict, total=False):
    """
    Represents filters for OCI IAM users.

    This structure is used by MCP tools that query or filter cached user data.
    Each field narrows results; lists within a field apply OR logic.
    'search' matches against either user name or display name.
    Providing multiple fields applies AND logic.
    Providing no fields returns all users.
    """

    domain_name: Annotated[
        list[str],
        'Domain name(s) to filter users by. If provided, use the specified domain(s) to search. If not provided, the default domain is used.',
    ]

    search: Annotated[
        list[str],
        'User name(s) or Display Name(s) to match. Accepts full or partial names and matches display name or username.',
    ]

    user_ocid: Annotated[
        str, 'A list of full or partial OCIDs of users to search on. The list will be treated as logical OR.'
    ]


class DynamicGroupSearch(TypedDict, total=False):
    """
    Represents filters for OCI IAM dynamic groups.

    Used by MCP tools to query dynamic groups based on domain, name, or matching rule criteria.
    Each field narrows results; lists within a field apply OR logic.
    Providing multiple fields applies AND logic.
    Providing no fields returns all dynamic groups.
    """

    domain_name: NotRequired[
        Annotated[
            list[str],
            'Domain name(s) associated with the dynamic group. If provided, use the specified domain(s) to search. If not provided, the default domain is used.',
        ]
    ]

    dynamic_group_name: NotRequired[
        Annotated[list[str], 'Dynamic group name(s) to filter by. Accepts full or partial names.']
    ]

    matching_rule: NotRequired[
        Annotated[
            list[str],
            "Matching rule expression(s) to search for (e.g., 'ALL {resource.type = instance, ...}'). Supports substring matches.",
        ]
    ]

    dynamic_group_ocid: Annotated[str, 'List of full or partial OCIDs of the dynamic group.']
    in_use: NotRequired[
        Annotated[
            bool,
            'If set to True, only return dynamic groups that are referenced by policies. If False, only those not in use. Not Required.',
        ]
    ]


# Filters for MCP or UI tools
class PolicySearch(TypedDict, total=False):
    """
    Represents filters for OCI IAM policy statements.

    This structure is used as input to policy filter tools exposed via MCP.
    Each key is optional; providing multiple fields narrows results (AND logic).
    Lists within a field apply OR logic among their entries.
    Providing no fields returns all policy statements.
    """

    exact_groups: Annotated[list[Group], 'Exact Group(s) to filter policies by. Requires full group_name.']

    exact_users: Annotated[list[User], 'Exact User(s) to filter policies by. Requires full user_name.']

    exact_dynamic_groups: Annotated[
        list[DynamicGroup], 'Exact Dynamic Group(s) to filter policies by. Requires full dynamic_group_name.'
    ]

    search_groups: Annotated[GroupSearch, 'Fuzzy Search Group(s) to filter policies by. Accepts full or partial names.']

    search_users: Annotated[UserSearch, 'Fuzzy Search User(s) to filter policies by. Accepts full or partial names.']

    search_dynamic_groups: Annotated[
        DynamicGroupSearch, 'Fuzzy Search Dynamic Group(s) to filter policies by. Accepts full or partial names.'
    ]

    verb: Annotated[
        list[Literal['inspect', 'read', 'use', 'manage']],
        'One or more policy verbs to match. Each value filters by IAM verb type.',
    ]

    statement_text: Annotated[list[str], 'Substring(s) of the policy statement text to match.']

    policy_name: Annotated[list[str], 'Filter by policy display name(s).']

    policy_compartment: Annotated[
        list[str], "Compartment(s) that define the policy. Supports 'ROOTONLY' to restrict to root-level policies."
    ]

    resource: Annotated[
        list[str], "One or more OCI resources (e.g., 'instance', 'bucket') that this policy applies to."
    ]

    location: Annotated[
        list[str],
        "Relative compartment path(s) or OCIDs representing where the policy applies. Accepts 'tenancy' for top-level.",
    ]

    effective_path: Annotated[
        list[str],
        'Computed effective compartment path(s) for scope evaluation, used to determine inheritance of permissions. '
        'Always starts with ROOT  '
        'An example is ROOT/compartment1/sub-comp'
        'This filter can handle multiple paths as a list of strings. '
        'Supports partial paths, e.g., ROOT/compartment1',
        'To match, this must be an exact match or a prefix(startswith) of the effective path of a policy statement.',
    ]

    subject_type: Annotated[
        list[Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']],
        "Type of subject targeted by the policy. Must be one or more of 'group', 'dynamic-group', 'any-user', 'any-group', or 'service'.",
    ]

    subject: Annotated[list[str], 'Subject identifier(s), usually user, group, or domain/name pairs.']

    permission: Annotated[
        list[str], "List of specific permissions or actions (e.g., 'START_INSTANCE', 'READ_OBJECTS')."
    ]

    comments: Annotated[list[str], 'Comment text that appears at the end of policy statements (if any).']

    conditions: Annotated[list[str], "Conditional clauses ('any', 'all', etc.) used within the policy statement."]

    valid: Annotated[
        bool,
        'If set to True, only return valid policy statements that parsed and passed validation. If False, only invalid statements.',
    ]


# Return Types
class PolicyOverlap(TypedDict):
    """Represents overlap analysis for a policy statement."""

    superseded_by: Annotated[str, 'The policy name that supersedes this statement']
    confidence: Annotated[str, 'Confidence level of the overlap (e.g., "high", "medium", "low")']
    reason: Annotated[str, 'Explanation for the overlap detection']
    statement_text: Annotated[str, 'The statement text of the superseding statement']
    internal_id: Annotated[str, 'The internal ID of the superseding statement']
    permission_overlap: Annotated[list[str], 'List of specific permissions that overlap between the two statements']
    additional_notes: NotRequired[Annotated[str, 'Any additional notes about the overlap analysis.']]


class DefineStatement(TypedDict, total=False):
    """Parsed OCI IAM 'define' policy statement with optional metadata."""

    policy_name: Annotated[str, 'Human-readable policy name']
    policy_ocid: Annotated[str, 'Unique OCID of the policy']
    policy_description: Annotated[str, 'Description of the policy']
    statement_text: Annotated[str, 'Full text of the define statement']
    valid: Annotated[bool, 'True if the statement passed parsing and validation']
    defined_type: Annotated[str, 'Type of object defined (user, group, dynamic-group, etc.)']
    defined_name: Annotated[str, 'Name of the defined object']
    ocid_alias: Annotated[str, 'Alias assigned for this definition, if any']
    creation_time: Annotated[str, 'ISO timestamp when the policy was created']


class PolicyStatement(TypedDict, total=False):
    """
    Represents a parsed OCI IAM policy statement.

    Each field corresponds to a normalized component extracted from a raw OCI policy text line.
    These structures are produced during policy parsing and returned by filter tools.
    """

    policy_name: Annotated[str, 'Display name of the policy containing this statement.']

    policy_ocid: Annotated[str, 'Unique OCID identifier of the policy.']

    compartment_ocid: Annotated[str, 'OCID of the compartment where this policy is defined.']

    policy_compartment: Annotated[str, 'Name of the compartment that owns this policy.']

    statement_text: Annotated[str, 'The full, raw text of the policy statement as defined in OCI.']

    valid: Annotated[bool, 'True if the statement successfully parsed and passed internal validation.']

    invalid_reasons: Annotated[list[str], 'If invalid, the reasons why parsing or validation failed.']

    subject_type: Annotated[
        str,
        "Type of subject targeted by the policy, such as 'group', 'dynamic-group', 'any-user', 'any-group', or 'service'.",
    ]

    subject: Annotated[
        list[tuple[str | None, str]] | str,
        'The subject(s) this policy applies to. May be a list of (domain, name) tuples or a simple string if unstructured.',
    ]

    verb: Annotated[str, "The IAM verb granting the level of access: one of 'inspect', 'read', 'use', or 'manage'."]

    resource: Annotated[
        str, "OCI resource type targeted by this statement (e.g., 'instance-family', 'bucket', 'compartment')."
    ]

    permission: Annotated[
        list[str],
        "Specific permissions or actions derived from the statement (e.g., 'START_INSTANCE', 'READ_OBJECTS').",
    ]

    location_type: Annotated[str, "Indicates how the location was resolved: 'explicit', 'root', 'derived', etc."]

    location: Annotated[str, 'Human-readable compartment path or OCID representing where this policy applies.']

    effective_compartment_ocid: Annotated[
        str | None, 'OCID of the effective compartment determined from policy scope analysis.'
    ]

    effective_path: Annotated[
        str | None,
        'Resolved compartment path string showing where the statement takes effect, including inherited scopes.',
    ]

    conditions: Annotated[
        str, "Conditional logic (e.g., 'where any {request.user.id = ...}') if present in the statement."
    ]

    comments: Annotated[str, 'Comments or annotations appended to the policy statement text, if any.']

    creation_time: Annotated[str, 'Timestamp (ISO-8601) of the policy’s creation in OCI.']

    parsed: Annotated[bool, 'True if the parser successfully interpreted this statement and extracted its components.']

    parsing_notes: Annotated[
        list[str], 'List of notes or warnings generated during parsing, such as unsupported constructs.'
    ]

    internal_id: Annotated[str, 'Unique internal hash identifier for this statement.']

    policy_overlap: NotRequired[Annotated[list[PolicyOverlap], 'Overlap analysis results for this policy statement.']]


class PolicySummary(TypedDict):
    """
    Summary information for policy statements when full details would be too large.

    Used as an alternative return type when the complete list of PolicyStatement objects
    would exceed response size limits or when the user only needs summary information.
    """

    response_type: Literal['summary']
    total_statements: Annotated[int, 'Total number of policy statements that matched the filter']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of statements included before truncation occurred']
    policy_breakdown: Annotated[
        dict[str, int], 'Count of statements by policy name (e.g., {"CloudGuardPolicies": 29, "Arista-Policy": 7})'
    ]
    compartment_breakdown: Annotated[
        dict[str, int], 'Count of statements by compartment (e.g., {"ROOT": 45, "ROOT/LZ-Top": 29})'
    ]
    subject_type_breakdown: Annotated[
        dict[str, int], 'Count of statements by subject type (e.g., {"group": 250, "service": 50, "dynamic-group": 40})'
    ]
    verb_breakdown: Annotated[
        dict[str, int], 'Count of statements by verb (e.g., {"manage": 120, "read": 100, "use": 80, "inspect": 40})'
    ]
    sample_statements: Annotated[
        list[str], 'Sample of statement texts to give context (limited to first 10-20 statements)'
    ]
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class PolicyStatementFull(TypedDict):
    """
    Complete policy statement data when size limits allow full response.
    """

    response_type: Literal['full']
    statements: Annotated[list[PolicyStatement], 'Complete list of policy statements']
    total_count: Annotated[int, 'Total number of statements returned']


# Summary types for IAM search operations
class UserSummary(TypedDict):
    """
    Summary information for user search when full details would be too large.
    """

    response_type: Literal['summary']
    total_users: Annotated[int, 'Total number of users that matched the search criteria']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of users included before truncation occurred']
    domain_breakdown: Annotated[dict[str, int], 'Count of users by domain (e.g., {"Default": 45, "federated": 29})']
    sample_users: Annotated[list[str], 'Sample of user names to give context (limited to first 10-20 users)']
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class UserSearchFull(TypedDict):
    """
    Complete user data when size limits allow full response.
    """

    response_type: Literal['full']
    users: Annotated[list[User], 'Complete list of users']
    total_count: Annotated[int, 'Total number of users returned']


class GroupSummary(TypedDict):
    """
    Summary information for group search when full details would be too large.
    """

    response_type: Literal['summary']
    total_groups: Annotated[int, 'Total number of groups that matched the search criteria']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of groups included before truncation occurred']
    domain_breakdown: Annotated[dict[str, int], 'Count of groups by domain (e.g., {"Default": 45, "federated": 29})']
    sample_groups: Annotated[list[str], 'Sample of group names to give context (limited to first 10-20 groups)']
    message: Annotated[str, 'Human-readable explanation of why summary was returned instead of full data']


class GroupSearchFull(TypedDict):
    """
    Complete group data when size limits allow full response.
    """

    response_type: Literal['full']
    groups: Annotated[list[Group], 'Complete list of groups']
    total_count: Annotated[int, 'Total number of groups returned']


class DynamicGroupSummary(TypedDict):
    """
    Summary information for dynamic group search when full details would be too large.
    """

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
    """
    Complete dynamic group data when size limits allow full response.
    """

    response_type: Literal['full']
    dynamic_groups: Annotated[list[DynamicGroup], 'Complete list of dynamic groups']
    total_count: Annotated[int, 'Total number of dynamic groups returned']


# Union types for IAM search responses with discriminators
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

# Union type for policy filter responses with discriminator
PolicyFilterResponse = Annotated[
    PolicySummary | PolicyStatementFull,
    'Response from policy filter operations - either summary or full data based on size constraints',
]
