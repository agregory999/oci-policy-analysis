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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

from typing import Annotated, Literal, NotRequired, TypedDict


# Data Models for Policies, Dynamic Groups, Users, and Groups
class Group(TypedDict):
    """
    Represents an Exact OCI IAM group entry.
    Groups need a domain and name to be unique.
    Domain can be None for default domain.
    """

    domain_name: Annotated[str | None, 'The domain of the group. None for default domain.']
    group_name: Annotated[str, 'The name of the group.']
    group_id: Annotated[str | None, 'The ID of the group. Not required for filters.']
    group_ocid: Annotated[str | None, 'The OCID of the group. Not required for filters.']
    description: Annotated[str | None, 'The description of the group. Not required for filters.']


class User(TypedDict):
    """
    Represents an Exact OCI IAM user entry.
    Users need a domain and name to be unique.
    Domain can be None for default domain.
    """

    domain_name: Annotated[str | None, 'The domain name. None for default domain.']
    user_name: Annotated[str, 'The user name. Required']
    user_ocid: Annotated[str | None, 'The user OCID. Not required for filters.']
    display_name: Annotated[str, 'The display name. Not required for filters.']
    email: Annotated[str | None, 'The primary email address. Not required for filters.']
    user_id: Annotated[str | None, 'The user ID. Not required for filters.']
    groups: Annotated[list[str] | None, 'List of group OCIDs the user belongs to. Not required for filters.']


class DynamicGroup(TypedDict):
    """
    Represents an Exact OCI IAM dynamic group entry.
    Dynamic groups need a domain and name to be unique.
    Domain can be None for default domain.
    """

    domain_name: Annotated[str | None, 'The domain of the dynamic group. None for default domain.']
    dynamic_group_name: Annotated[str, 'The name of the dynamic group.']
    dynamic_group_ocid: NotRequired[Annotated[str | None, 'The OCID of the dynamic group. Not required for filters.']]
    dynamic_group_id: NotRequired[Annotated[str | None, 'The ID of the dynamic group. Not required for filters.']]
    matching_rule: NotRequired[
        Annotated[str | None, 'The matching rule expression for the dynamic group. Not required for filters.']
    ]
    description: NotRequired[Annotated[str | None, 'The description of the dynamic group. Not required for filters.']]
    in_use: NotRequired[
        Annotated[bool | None, 'True if the dynamic group is referenced by any policies. Not required for filters.']
    ]
    creation_time: NotRequired[
        Annotated[str | None, 'The creation time of the dynamic group. Not required for filters.']
    ]
    created_by_ocid: NotRequired[
        Annotated[str | None, 'The OCID of the user who created the dynamic group. Not required for filters.']
    ]
    created_by_name: NotRequired[
        Annotated[str | None, 'The name of the user who created the dynamic group. Not required for filters.']
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
        list[str | None] | None,
        'Domain name(s) to filter groups by. Use None or an empty string to include groups without a domain (Default domain).',
    ]

    group_name: Annotated[list[str] | None, 'Group display name(s) to match. Accepts full or partial names.']

    group_ocid: Annotated[str | None, 'The OCID of the group. ']


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
        list[str | None] | None,
        'Domain name(s) to filter users by. Use None or an empty string to include users without a domain (Default domain).',
    ]

    search: Annotated[
        list[str] | None,
        'User name(s) or Display Name(s) to match. Accepts full or partial names and matches display name or username.',
    ]

    user_ocid: Annotated[str | None, 'The OCID of the user.']


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
            list[str | None] | None,
            'Optional domain name(s) associated with the dynamic group. If provided, use None or an empty string for groups in the Default domain.',
        ]
    ]

    dynamic_group_name: NotRequired[
        Annotated[list[str] | None, 'Dynamic group name(s) to filter by. Accepts full or partial names.']
    ]

    matching_rule: NotRequired[
        Annotated[
            list[str] | None,
            "Matching rule expression(s) to search for (e.g., 'ALL {resource.type = instance, ...}'). Supports substring matches.",
        ]
    ]

    dynamic_group_ocid: Annotated[str | None, 'The OCID of the dynamic group.']
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

    exact_groups: Annotated[list[Group] | None, 'Exact Group(s) to filter policies by. Requires full group name.']

    exact_users: Annotated[list[User] | None, 'Exact User(s) to filter policies by. Requires full user name.']

    exact_dynamic_groups: Annotated[
        list[DynamicGroup] | None, 'Exact Dynamic Group(s) to filter policies by. Requires full or partial names.'
    ]

    search_groups: Annotated[
        GroupSearch | None, 'Fuzzy Search Group(s) to filter policies by. Accepts full or partial names.'
    ]

    search_users: Annotated[
        UserSearch | None, 'Fuzzy Search User(s) to filter policies by. Accepts full or partial names.'
    ]

    search_dynamic_groups: Annotated[
        DynamicGroupSearch | None, 'Fuzzy Search Dynamic Group(s) to filter policies by. Accepts full or partial names.'
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
    ]

    subject_type: Annotated[
        list[Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']],
        "Type of subject targeted by the policy. Must be one of 'group', 'dynamic-group', 'any-user', 'any-group', or 'service'.",
    ]

    subject: Annotated[list[str], 'Subject identifier(s), usually user, group, or domain/name pairs.']

    permission: Annotated[
        list[str], "List of specific permissions or actions (e.g., 'START_INSTANCE', 'READ_OBJECTS')."
    ]

    comments: Annotated[list[str], 'Comment text that appears at the end of policy statements (if any).']

    conditions: Annotated[list[str], "Conditional clauses ('any', 'all', etc.) used within the policy statement."]


# Return Types
class DefineStatement(TypedDict, total=False):
    """Parsed OCI IAM 'define' policy statement with optional metadata."""

    Policy_Name: Annotated[str, 'Human-readable policy name']
    Policy_OCID: Annotated[str, 'Unique OCID of the policy']
    Policy_Description: Annotated[str, 'Description of the policy']
    Statement_Text: Annotated[str, 'Full text of the define statement']
    Valid: Annotated[bool, 'True if the statement passed parsing and validation']
    Defined_Type: Annotated[str, 'Type of object defined (user, group, dynamic-group, etc.)']
    Defined_Name: Annotated[str, 'Name of the defined object']
    OCID_Alias: Annotated[str, 'Alias assigned for this definition, if any']
    Creation_Time: Annotated[str, 'ISO timestamp when the policy was created']


class PolicyStatement(TypedDict, total=False):
    """
    Represents a parsed OCI IAM policy statement.

    Each field corresponds to a normalized component extracted from a raw OCI policy text line.
    These structures are produced during policy parsing and returned by filter tools.
    """

    Policy_Name: Annotated[str, 'Display name of the policy containing this statement.']

    Policy_OCID: Annotated[str, 'Unique OCID identifier of the policy.']

    Compartment_OCID: Annotated[str, 'OCID of the compartment where this policy is defined.']

    Policy_Compartment: Annotated[str, 'Name of the compartment that owns this policy.']

    Statement_Text: Annotated[str, 'The full, raw text of the policy statement as defined in OCI.']

    Valid: Annotated[bool, 'True if the statement successfully parsed and passed internal validation.']

    Subject_Type: Annotated[
        str | None,
        "Type of subject targeted by the policy, such as 'group', 'dynamic-group', 'any-user', 'any-group', or 'service'.",
    ]

    Subject: Annotated[
        list[tuple[str | None, str]] | str | None,
        'The subject(s) this policy applies to. May be a list of (domain, name) tuples or a simple string if unstructured.',
    ]

    Verb: Annotated[
        str | None, "The IAM verb granting the level of access: one of 'inspect', 'read', 'use', or 'manage'."
    ]

    Resource: Annotated[
        str | None, "OCI resource type targeted by this statement (e.g., 'instance-family', 'bucket', 'compartment')."
    ]

    Permission: Annotated[
        str | None, "Specific permission or action derived from the statement (e.g., 'START_INSTANCE', 'READ_OBJECTS')."
    ]

    Location_Type: Annotated[str | None, "Indicates how the location was resolved: 'explicit', 'root', 'derived', etc."]

    Location: Annotated[str | None, 'Human-readable compartment path or OCID representing where this policy applies.']

    Effective_Compartment_OCID: Annotated[
        str | None, 'OCID of the effective compartment determined from policy scope analysis.'
    ]

    Effective_Path: Annotated[
        str | None,
        'Resolved compartment path string showing where the statement takes effect, including inherited scopes.',
    ]

    Conditions: Annotated[
        str | None, "Conditional logic (e.g., 'where any {request.user.id = ...}') if present in the statement."
    ]

    Comments: Annotated[str | None, 'Comments or annotations appended to the policy statement text, if any.']

    Creation_Time: Annotated[str, 'Timestamp (ISO-8601) of the policy’s creation in OCI.']

    Parsed: Annotated[bool, 'True if the parser successfully interpreted this statement and extracted its components.']

    Parsing_Notes: Annotated[
        list[str], 'List of notes or warnings generated during parsing, such as unsupported constructs.'
    ]
