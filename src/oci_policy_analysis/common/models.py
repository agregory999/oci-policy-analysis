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
from typing import Annotated, Literal, NotRequired, TypedDict  # noqa: UP035

# ================================
# Simulation Models
# ================================

# SimulationPrincipalType describes all valid principal types in simulation requests and results.
SimulationPrincipalType = Literal['group', 'user', 'dynamic-group', 'any-user', 'any-group', 'service']


class SimulationPrepareRequest(TypedDict):
    """
    Model describing the canonical input for simulation preparation.
    Used to obtain principal and where-clause context, never for actual simulation execution.
    """

    compartment_path: Annotated[str, 'Effective compartment path, e.g. "ROOT/Finance"']
    principal_type: Annotated[SimulationPrincipalType, 'Principal type for simulation']
    principal: Annotated[
        str | list[str | None],
        'String for "any-user"/"any-group"/"service"; [domain, name] for user/group/dynamic-group',
    ]


class SimulationPrepareResponse(TypedDict):
    """
    Model describing the output of simulation preparation.
    Provides required where fields and a standardized principal key.
    """

    required_where_fields: Annotated[list[str], 'All unique where clause variable names required for input']
    principal_key: Annotated[str, 'Principal key as calculated by engine (e.g., "user:Default/anita")']


class SimulationScenario(TypedDict):
    """
    Canonical input for SINGLE simulation (batch-mode simulations use a list of these in SimulationBatchRequest).
    All inputs must exactly match those from the context + UI builder/MCP client.

    Fields:
    - compartment_path: Effective compartment path scoped for this simulation (str)
    - principal_key: str. Output from SimulationPrepareResponse
    - api_operation: str. Required API operation (e.g., "oci:ListBuckets")
    - where_context: Dict[str, str]. Mapping from variable names to values for this run.
    - checked_statements: Optional[List[str]]. Internal statement IDs to restrict simulation (UI only; omit for MCP).
    """

    compartment_path: Annotated[str, 'Effective compartment path']
    principal_key: Annotated[str, 'Principal key, must be from preparation stage']
    api_operation: Annotated[str, 'API operation to simulate, e.g., "oci:ListBuckets"']
    where_context: Annotated[dict[str, str], 'Variable input mapping for required where fields']
    checked_statements: NotRequired[Annotated[list[str], 'Statement IDs (UI only, omit for MCP/server)']]


class SimulationBatchRequest(TypedDict):
    """
    Batch simulation request (multiplex multiple scenarios).
    - simulations: List of SimulationScenario dicts, each fully specified
    - trace: Optional bool, if true include detailed trace in result for each scenario

    Example:
    {
      "simulations": [
        { ... see SimulationScenario ... }
      ],
      "trace": true
    }
    """

    simulations: Annotated[list[SimulationScenario], 'List of simulation scenarios to run']
    trace: NotRequired[Annotated[bool, 'If true, include trace output in SimulationResult']]


class SimulationResult(TypedDict):
    """
    Canonical result for a single simulation scenario.
    All fields strictly correspond to engine outputs and are fully JSON-serializable.

    Fields:
    - result: "YES" if permitted, "NO" if denied (Literal)
    - api_call_allowed: Boolean (redundant with result but retained for clarity)
    - final_permission_set: List of permissions granted by policy for this op/context (trace=True only)
    - required_permissions_for_api_operation: List of permissions required for op (trace=True only)
    - missing_permissions: List of missing permissions needed for full allow
    - failure_reason: Reason for failure or denial, empty if successful
    - trace_statements: Optional[List[dict]], statement-by-statement trace (only present if trace enabled)
    """

    result: Annotated[Literal['YES', 'NO'], "'YES' if API operation permitted, 'NO' if denied"]
    api_call_allowed: Annotated[bool, 'True if API op permitted']
    final_permission_set: Annotated[list[str], 'Permissions granted after simulation']
    required_permissions_for_api_operation: Annotated[list[str], 'Permissions required for op']
    missing_permissions: Annotated[list[str], 'Any permissions missing for full allow']
    failure_reason: Annotated[str, 'Reason for denial or error, empty if successful']
    trace_statements: NotRequired[Annotated[list[dict], 'Statement-by-statement trace, if trace=True']]


class SimulationBatchResponse(TypedDict):
    """
    Batch simulation output: result list, matches input scenario order.

    Fields:
    - results: List[SimulationResult]. One per SimulationScenario submitted.
    """

    results: Annotated[list[SimulationResult], 'Simulation result(s) for each scenario, in order']


# ================================
# Entity Models (Policies, Dynamic Groups, Users, Groups)
# ================================
class Group(TypedDict):
    """
    Model representing an OCI IAM group (identity and metadata).
    A group is uniquely identified by domain and group name.
    """

    domain_name: NotRequired[Annotated[str, 'The domain of the group. If not provided, the default domain.']]
    group_name: Annotated[str, 'The name of the group.']
    group_id: NotRequired[Annotated[str, 'The ID of the group. Not required for filters.']]
    group_ocid: NotRequired[Annotated[str, 'The OCID of the group. Not required for filters.']]
    description: NotRequired[Annotated[str, 'The description of the group. Not required for filters.']]


class User(TypedDict):
    """
    Model representing an OCI IAM user.
    Only username and domain are required to uniquely identify a user.
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
    Model representing an OCI IAM dynamic group.
    Dynamic groups are collections of principals defined by rules; unique by domain and name.
    """

    domain_name: NotRequired[Annotated[str, 'The domain of the group. If not provided, the default domain.']]
    domain_ocid: NotRequired[Annotated[str, 'The OCID of the domain. Not required for filters.']]
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


class BasePolicy(TypedDict):
    """
    Model representing an OCI IAM policy.
    Captures policy identity and metadata but omits policy statements themselves.
    Policies are unique by their name within a compartment.
    """

    policy_name: Annotated[str, 'The name of the policy.']
    policy_ocid: Annotated[str, 'The OCID of the policy. Not required for filters.']
    description: Annotated[str | None, 'The description of the policy. Not required for filters.']
    compartment_ocid: Annotated[str, 'The OCID of the compartment containing the policy. Not required for filters.']
    creation_time: Annotated[str, 'The creation time of the policy. Not required for filters.']


# Search Models
class GroupSearch(TypedDict, total=False):
    """
    Search model for OCI IAM groups.
    Used to filter and query cached group metadata by different attributes.
    Lists inside a field use OR; multiple fields use AND.
    """

    domain_name: Annotated[
        list[str],
        'Domain name(s) to filter groups by. If provided, use the specified domain(s) to search. If not provided, the default domain is used.',
    ]

    group_name: Annotated[list[str], 'Group display name(s) to match. Accepts full or partial names.']

    group_ocid: Annotated[list[str], 'A list of OCIDs or partial OCIDs of the group.']


class UserSearch(TypedDict, total=False):
    """
    Search model for OCI IAM users.
    Used to filter and query cached user metadata by domain, username, or partial/display names.
    Lists inside a field use OR; multiple fields use AND.
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
    Search model for OCI IAM dynamic groups.
    Used to query dynamic groups based on domain, name, or matching rule criteria via MCP tools.
    Lists inside a field use OR; multiple fields use AND.
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


class PolicySearch(TypedDict, total=False):
    """
    Search/filter model for querying OCI IAM policy statements.
    Accepts many fields; lists use OR logic, multiple fields use AND.
    Used as input to policy filter tools provided by MCP.
    """

    action: Annotated[list[str], "Restrict results to statements of a given action: ['allow'], ['deny'], or both."]

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


class PolicyOverlap(TypedDict):
    """
    Model for representing overlap/conflict analysis between policy statements.
    Useful for reporting risk and redundancy in IAM policy analysis tools.
    """

    superseded_by: Annotated[str, 'The policy name that supersedes this statement']
    confidence: Annotated[str, 'Confidence level of the overlap (e.g., "high", "medium", "low")']
    reason: Annotated[str, 'Explanation for the overlap detection']
    statement_text: Annotated[str, 'The statement text of the superseding statement']
    internal_id: Annotated[str, 'The internal ID of the superseding statement']
    permission_overlap: Annotated[list[str], 'List of specific permissions that overlap between the two statements']
    additional_notes: NotRequired[Annotated[str, 'Any additional notes about the overlap analysis.']]


class BasePolicyStatement(TypedDict):
    """
    Base model for all OCI policy statement types, containing shared fields.
    All statement models inherit from this and add statement-type-specific data.
    """

    policy_name: Annotated[str, 'Display name of the policy containing this statement.']
    policy_description: Annotated[str, 'Description of the policy containing this statement.']
    policy_ocid: Annotated[str, 'Unique OCID identifier of the policy.']
    compartment_ocid: Annotated[str, 'OCID of the compartment where this policy is defined.']
    compartment_path: Annotated[str, 'Path of the compartment that owns this policy.']
    statement_text: Annotated[str, 'The full, raw text of the policy statement as defined in OCI.']
    creation_time: Annotated[str, 'Timestamp (ISO-8601) of the policy creation in OCI.']
    internal_id: Annotated[str, 'Unique internal hash identifier for this statement.']
    parsed: Annotated[bool, 'True if the parser successfully interpreted this statement and extracted its components.']


class DefineStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'define' policy statement with optional metadata."""

    valid: Annotated[bool, 'True if the statement passed parsing and validation']
    defined_type: Annotated[str, 'Type of object defined (user, group, dynamic-group, etc.)']
    defined_name: Annotated[str, 'Name of the defined object']
    ocid_alias: Annotated[str, 'Alias assigned for this definition, if any']
    comment: NotRequired[Annotated[str, 'Trailing policy statement comment if present']]


class EndorseStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'endorse' cross-tenancy policy statement with optional metadata."""

    valid: Annotated[bool, 'True if the statement passed parsing and validation']
    action_type: Annotated[
        Literal['endorse', 'deny endorse'], 'Type of endorse action: either "endorse" or "deny endorse"'
    ]
    endorsed_principal_type: Annotated[
        Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service'],
        'Type of principal: group, dynamic-group, any-user, service.',
    ]
    endorsed_principal: Annotated[str, 'Name of the principal being endorsed (group, dynamic-group, etc.)']
    endorsed_principal_tenancy: Annotated[str, 'The tenancy of the endorsed group or dynamic-group']
    endorse_action: Annotated[str, 'Verb or permission for the endorse statement (e.g., associate, use, etc.)']
    endorse_resource: Annotated[
        str, 'Target OCI resource of the endorse statement (e.g., instance-family, bucket, etc.)'
    ]
    endorse_permissions: NotRequired[Annotated[list[str], 'List of explicit permissions being endorsed']]
    endorse_tenancy: Annotated[str, 'Defined name of the endorsed tenancy']
    # "Associate ... with ..." triple-tenancy fields (optional, used for advanced endorses)
    endorse_associate_resource: NotRequired[Annotated[str, 'Resource being associated (resource_a)']]
    endorse_associate_tenancy: NotRequired[Annotated[str, 'Location of resource being associated']]
    endorse_associate_with_resource: NotRequired[Annotated[str, 'Remote resource being associated (resource_b)']]
    endorse_associate_with_tenancy: NotRequired[Annotated[str, 'Location of second resource being associated']]

    # where, comment
    where_clause: NotRequired[Annotated[str, 'Optional where clause (all {...}) attached']]
    comment: NotRequired[Annotated[str, 'Trailing policy statement comment if present']]


class AdmitStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'admit' cross-tenancy policy statement with parsed metadata."""

    valid: Annotated[bool, 'True if the statement passed parsing and validation']

    # Basic principal info
    action_type: Annotated[Literal['admit', 'deny admit'], 'Type of admit action: either "admit" or "deny admit"']

    admitted_principal_type: Annotated[
        Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service'],
        'Type of principal: group, dynamic-group, any-user, etc.',
    ]
    admitted_principal: Annotated[str, 'Name of the principal being admitted (group, dynamic-group, etc.)']
    admitted_tenancy: Annotated[str, 'The tenancy of the admitted group or dynamic-group']

    # Main admit action/target (for simple admits)
    admit_action: Annotated[str, 'Verb or permission for the admit statement (e.g., read, manage, use, etc.)']
    admit_resource: Annotated[str, 'Target OCI resource of the admit statement (e.g., all-resources, orm-stack, etc.)']
    admit_permissions: NotRequired[Annotated[list[str], 'List of explicit permissions being admitted']]
    admit_location_type: Annotated[str, 'tenancy or compartment or compartment id']
    admit_location: Annotated[str, 'The actual location value (e.g., tenancy, compartment OCID, etc.)']
    # "Associate ... with ..." triple-tenancy fields (optional, used for advanced admits)
    admit_associate_resource: NotRequired[Annotated[str, 'Resource being associated (resource_a)']]
    admit_associate_tenancy: NotRequired[Annotated[str, 'Location of resource being associated']]
    admit_associate_with_resource: NotRequired[Annotated[str, 'Remote resource being associated (resource_b)']]
    admit_associate_with_tenancy: NotRequired[Annotated[str, 'Location of second resource being associated']]

    # Permissions, where, comment
    where_clause: NotRequired[Annotated[str, 'Optional where clause (all {...}) attached']]
    comment: NotRequired[Annotated[str, 'Trailing policy statement comment if present']]


class RegularPolicyStatement(BasePolicyStatement, total=False):
    """
    Represents a parsed OCI IAM policy statement.

    Each field corresponds to a normalized component extracted from a raw OCI policy text line.
    These structures are produced during policy parsing and returned by filter tools.
    """

    # Literal - allow or deny
    action: Annotated[
        Literal['allow', 'deny'], "The IAM action specified in the policy statement: either 'allow' or 'deny'."
    ]
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

    parsing_notes: Annotated[
        list[str], 'List of notes or warnings generated during parsing, such as unsupported constructs.'
    ]


class PolicySummary(TypedDict):
    """
    Model for lightweight summary reporting for policy statement queries.
    Used by APIs or UI when result set is too large to send full details.
    """

    response_type: Literal['summary']
    total_statements: Annotated[int, 'Total number of policy statements that matched the filter']
    truncated: Annotated[bool, 'True if results were truncated due to size limits']
    truncation_point: Annotated[int, 'Number of statements included before truncation occurred']
    policy_breakdown: Annotated[
        dict[str, int], 'Count of statements by policy name (e.g., {"CloudGuardPolicies": 29, "Arista-Policy": 7})'
    ]
    action_breakdown: Annotated[dict[str, int], 'Count of statements by action (e.g., {"allow": 82, "deny": 33})']
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
    Model for detailed/full reporting of policy statement queries.
    Only used when result set is small enough to return every statement.
    """

    response_type: Literal['full']
    statements: Annotated[list[RegularPolicyStatement], 'Complete list of policy statements']
    total_count: Annotated[int, 'Total number of statements returned']


# Summary types for IAM search operations
class UserSummary(TypedDict):
    """
    Lightweight summary of user search results when full details are not shown.
    Used to communicate match counts and domain breakdowns for user searches.
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
    Model representing a full user search result set (all users).
    Used if the user list is small enough to return fully.
    """

    response_type: Literal['full']
    users: Annotated[list[User], 'Complete list of users']
    total_count: Annotated[int, 'Total number of users returned']


class GroupSummary(TypedDict):
    """
    Lightweight summary of group search results.
    Used to summarize group matches, domain breakdowns, and sampling.
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
    Model representing a full group search result set (all groups).
    Used if the group list is small enough to return fully.
    """

    response_type: Literal['full']
    groups: Annotated[list[Group], 'Complete list of groups']
    total_count: Annotated[int, 'Total number of groups returned']


class DynamicGroupSummary(TypedDict):
    """
    Lightweight summary of dynamic group search results.
    Used to summarize matches, domain/in-use breakdowns, and sample listing.
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
    Model representing a full dynamic group search result set.
    Used if the dynamic group list is small enough to return fully.
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


class ReferenceDataDiffResult(TypedDict):
    """
    Result model describing the outcome of comparing two cached reference data sets.
    Used by tools diagnosing drift or state changes in cached OCI data.
    """

    response_type: Literal['reference_data_diff']
    cache_a: Annotated[str, 'Name of older cache (file or key)']
    cache_b: Annotated[str, 'Name of newer cache (file or key)']
    diff_summary: Annotated[str, 'One-line or short summary of differences (added, changed, removed)']
    diff_details: Annotated[dict, 'DeepDiff result details or filtered view suitable for UI display']
    message: Annotated[str, 'Human-readable message about the diff result or info']


class PolicyIntelligence(TypedDict, total=False):
    """
    Model for high-level analytics and findings of policy analysis (IAM intelligence overlay).
    Reports overlaps, risk scores, recommendations, consolidation, unused resources, and other advanced data.
    Intended for UI or API overlays rather than core engine results.
    """

    overlaps: list[dict]
    recommendations: list[dict]
    risk_scores: list[dict]
    consolidations: list[dict]
    cleanup_items: NotRequired[dict]
