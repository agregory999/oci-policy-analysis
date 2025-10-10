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

from typing import Annotated, Literal, TypedDict


class Group(TypedDict):
    """Represents an OCI IAM group entry. Groups need a domain and name to be unique.  Domain can be None for default domain."""

    domain: str | None
    name: str


class User(TypedDict):
    """Represents an OCI IAM user entry. Users need a domain and name to be unique.  Domain can be None for default domain."""

    user_name: str
    user_id: str
    display_name: str
    domain_name: str | None


class DynamicGroup(TypedDict):
    """Represents an OCI IAM dynamic group entry. Dynamic groups need a domain and name to be unique.  Domain can be None for default domain."""

    domain: str | None
    name: str


# Filters for MCP tools
class PolicyFilters(TypedDict, total=False):
    """
    Represents filters for OCI IAM policy statements.

    This structure is used as input to policy filter tools exposed via MCP.
    Each key is optional; providing multiple fields narrows results (AND logic).
    Lists within a field apply OR logic among their entries.
    Providing no fields returns all policy statements.
    """

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
        'Computed effective compartment path(s) for scope evaluation, used to determine inheritance of permissions.',
    ]

    subject_type: Annotated[
        list[str], "Type(s) of subject: 'group', 'dynamic-group', 'any-user', 'any-group', 'service', etc."
    ]

    subject: Annotated[list[str], 'Subject identifier(s), usually user, group, or domain/name pairs.']

    permission: Annotated[
        list[str], "List of specific permissions or actions (e.g., 'START_INSTANCE', 'READ_OBJECTS')."
    ]

    comments: Annotated[list[str], 'Comment text that appears at the end of policy statements (if any).']

    conditions: Annotated[list[str], "Conditional clauses ('any', 'all', etc.) used within the policy statement."]


class GroupFilters(TypedDict, total=False):
    """
    Represents filters for OCI IAM groups.

    This structure is used by MCP tools that query or filter cached group data.
    Each field narrows results; lists within a field apply OR logic.
    Providing multiple fields applies AND logic.
    Providing no fields returns all groups.
    """

    domain: Annotated[
        list[str | None] | None,
        'Domain name(s) to filter groups by. Use None or an empty string to include groups without a domain (Default domain).',
    ]

    name: Annotated[list[str] | None, 'Group display name(s) to match. Accepts full or partial names.']


class UserFilters(TypedDict, total=False):
    """
    Represents filters for OCI IAM users.

    This structure is used by MCP tools that query or filter cached user data.
    Each field narrows results; lists within a field apply OR logic.
    Providing multiple fields applies AND logic.
    Providing no fields returns all users.
    """

    domain: Annotated[
        list[str | None] | None,
        'Domain name(s) to filter users by. Use None or an empty string to include users without a domain (Default domain).',
    ]

    username: Annotated[list[str] | None, 'User name(s) to match. Accepts full or partial names.']

    display_name: Annotated[list[str] | None, 'User display name(s) to match. Accepts full or partial names.']


class DynamicGroupFilters(TypedDict, total=False):
    """
    Represents filters for OCI IAM dynamic groups.

    Used by MCP tools to query dynamic groups based on domain, name, or matching rule criteria.
    Each field narrows results; lists within a field apply OR logic.
    Providing multiple fields applies AND logic.
    Providing no fields returns all dynamic groups.
    """

    domain: Annotated[
        list[str | None] | None,
        'Domain name(s) associated with the dynamic group. Use None or an empty string for groups in the Default domain.',
    ]

    name: Annotated[list[str] | None, 'Dynamic group name(s) to filter by. Accepts full or partial names.']

    matching_rule: Annotated[
        list[str] | None,
        "Matching rule expression(s) to search for (e.g., 'ALL {resource.type = instance, ...}'). Supports substring matches.",
    ]


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

    Effective_Compartment: Annotated[
        str | None, 'Name of the effective compartment determined from policy scope analysis.'
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
