"""Policy and statement models."""

from typing import Annotated, Literal, NotRequired, TypedDict

from .models_iam import DynamicGroup, DynamicGroupSearch, Group, GroupSearch, User, UserSearch


class Principal(TypedDict, total=False):
    """Canonical principal representation for parsed policy statements."""

    principal_type: Annotated[
        str,
        "Principal type (e.g., 'group', 'group-id', 'dynamic-group', 'dynamic-group-id', 'user', 'any-user', 'service').",
    ]
    principal_key: Annotated[str, 'Canonical principal key used for stable matching/display.']
    domain_name: NotRequired[
        Annotated[str | None, 'Identity domain for name-based principals; usually None for id-based principals.']
    ]
    name: NotRequired[Annotated[str, 'Display/principal name for name-based principals.']]
    ocid: NotRequired[Annotated[str, 'OCID for id-based principals when present.']]
    display_name: NotRequired[Annotated[str, 'Human-readable display string for UI/debug output.']]


class BasePolicy(TypedDict, total=False):
    """Model representing an OCI IAM policy (identity/metadata)."""

    policy_name: Annotated[str, 'The name of the policy.']
    policy_ocid: Annotated[str, 'The OCID of the policy. Not required for filters.']
    description: Annotated[str | None, 'The description of the policy. Not required for filters.']
    compartment_ocid: Annotated[str, 'The OCID of the compartment containing the policy. Not required for filters.']
    compartment_path: Annotated[str, 'Full compartment path string for the policy (e.g., "ROOT/CompA/CompB").']
    creation_time: Annotated[str, 'The creation time of the policy. Not required for filters.']
    tags: NotRequired[
        Annotated[
            dict[str, str],
            'Optional. Flattened tag map for display only (freeform plus defined flattened as "namespace:key").',
        ]
    ]
    freeform_tags: NotRequired[Annotated[dict[str, str], 'Optional. Freeform tag map as stored in OCI.']]
    defined_tags: NotRequired[
        Annotated[
            dict[str, dict[str, str]],
            'Optional. Defined tag map as stored in OCI (namespace -> key -> value).',
        ]
    ]


class PolicySearch(TypedDict, total=False):
    """Search/filter model for querying OCI IAM policy statements."""

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
    compartment_path: Annotated[
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
    principal_key: Annotated[
        list[str],
        'Canonical principal key(s) for exact principal matching (e.g., user:Default/alice, service:None/database).',
    ]
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
    """Model for representing overlap/conflict analysis between policy statements."""

    superseded_by: Annotated[str, 'The policy name that supersedes this statement']
    confidence: Annotated[str, 'Confidence level of the overlap (e.g., "high", "medium", "low")']
    reason: Annotated[str, 'Explanation for the overlap detection']
    statement_text: Annotated[str, 'The statement text of the superseding statement']
    internal_id: Annotated[str, 'The internal ID of the superseding statement']
    permission_overlap: Annotated[list[str], 'List of specific permissions that overlap between the two statements']
    additional_notes: NotRequired[Annotated[str, 'Any additional notes about the overlap analysis.']]


class BasePolicyStatement(TypedDict):
    """Base model for all OCI policy statement types, containing shared fields."""

    policy_name: Annotated[str, 'Display name of the policy containing this statement.']
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
    principal_keys: NotRequired[
        Annotated[list[str], 'Canonical principal key list derived from parsed subject payload.']
    ]
    endorsed_principal: Annotated[str, 'Name of the principal being endorsed (group, dynamic-group, etc.)']
    endorsed_principal_tenancy: Annotated[str, 'The tenancy of the endorsed group or dynamic-group']
    endorse_action: Annotated[str, 'Verb or permission for the endorse statement (e.g., associate, use, etc.)']
    endorse_resource: Annotated[
        str, 'Target OCI resource of the endorse statement (e.g., instance-family, bucket, etc.)'
    ]
    endorse_permissions: NotRequired[Annotated[list[str], 'List of explicit permissions being endorsed']]
    endorse_tenancy: Annotated[str, 'Defined name of the endorsed tenancy']
    endorse_associate_resource: NotRequired[Annotated[str, 'Resource being associated (resource_a)']]
    endorse_associate_tenancy: NotRequired[Annotated[str, 'Location of resource being associated']]
    endorse_associate_with_resource: NotRequired[Annotated[str, 'Remote resource being associated (resource_b)']]
    endorse_associate_with_tenancy: NotRequired[Annotated[str, 'Location of second resource being associated']]
    associate_clause_raw: NotRequired[Annotated[str, 'Raw associate clause text when endorse uses associate semantics']]
    tenancy_aliases: NotRequired[
        Annotated[list[str], 'Referenced tenancy aliases discovered during parsing (unresolved)']
    ]
    resolved_aliases: NotRequired[
        Annotated[
            dict[str, dict[str, str | bool]],
            'Alias resolution map populated by intelligence step; keys are alias names and values include ocid/resolved.',
        ]
    ]
    aliases_resolved: NotRequired[Annotated[bool, 'True when all referenced aliases are resolved to define OCIDs']]
    where_clause: NotRequired[Annotated[str, 'Optional where clause (all {...}) attached']]
    comment: NotRequired[Annotated[str, 'Trailing policy statement comment if present']]


class AdmitStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'admit' cross-tenancy policy statement with parsed metadata."""

    valid: Annotated[bool, 'True if the statement passed parsing and validation']
    action_type: Annotated[Literal['admit', 'deny admit'], 'Type of admit action: either "admit" or "deny admit"']
    admitted_principal_type: Annotated[
        Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service'],
        'Type of principal: group, dynamic-group, any-user, etc.',
    ]
    principal_keys: NotRequired[
        Annotated[list[str], 'Canonical principal key list derived from parsed subject payload.']
    ]
    admitted_principal: Annotated[str, 'Name of the principal being admitted (group, dynamic-group, etc.)']
    admitted_tenancy: Annotated[str, 'The tenancy of the admitted group or dynamic-group']
    admit_action: Annotated[str, 'Verb or permission for the admit statement (e.g., read, manage, use, etc.)']
    admit_resource: Annotated[str, 'Target OCI resource of the admit statement (e.g., all-resources, orm-stack, etc.)']
    admit_permissions: NotRequired[Annotated[list[str], 'List of explicit permissions being admitted']]
    admit_location_type: Annotated[str, 'tenancy or compartment or compartment id']
    admit_location: Annotated[str, 'The actual location value (e.g., tenancy, compartment OCID, etc.)']
    admit_associate_resource: NotRequired[Annotated[str, 'Resource being associated (resource_a)']]
    admit_associate_tenancy: NotRequired[Annotated[str, 'Location of resource being associated']]
    admit_associate_with_resource: NotRequired[Annotated[str, 'Remote resource being associated (resource_b)']]
    admit_associate_with_tenancy: NotRequired[Annotated[str, 'Location of second resource being associated']]
    associate_clause_raw: NotRequired[Annotated[str, 'Raw associate clause text when admit uses associate semantics']]
    tenancy_aliases: NotRequired[
        Annotated[list[str], 'Referenced tenancy aliases discovered during parsing (unresolved)']
    ]
    resolved_aliases: NotRequired[
        Annotated[
            dict[str, dict[str, str | bool]],
            'Alias resolution map populated by intelligence step; keys are alias names and values include ocid/resolved.',
        ]
    ]
    aliases_resolved: NotRequired[Annotated[bool, 'True when all referenced aliases are resolved to define OCIDs']]
    where_clause: NotRequired[Annotated[str, 'Optional where clause (all {...}) attached']]
    comment: NotRequired[Annotated[str, 'Trailing policy statement comment if present']]


class RegularPolicyStatement(BasePolicyStatement, total=False):
    """Represents a parsed OCI IAM policy statement."""

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
    principals: Annotated[
        list[Principal],
        'Derived canonical principal model list. Additive/non-breaking; legacy subject field remains during transition.',
    ]
    principal_keys: NotRequired[
        Annotated[list[str], 'Canonical principal key list derived from parsed subject payload.']
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
    """Model for lightweight summary reporting for policy statement queries."""

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
    """Model for detailed/full reporting of policy statement queries."""

    response_type: Literal['full']
    statements: Annotated[list[RegularPolicyStatement], 'Complete list of policy statements']
    total_count: Annotated[int, 'Total number of statements returned']


PolicyFilterResponse = Annotated[
    PolicySummary | PolicyStatementFull,
    'Response from policy filter operations - either summary or full data based on size constraints',
]


class PolicyIntelligence(TypedDict, total=False):
    """Model for high-level analytics and findings of policy analysis (IAM intelligence overlay)."""

    overlaps: list[dict]
    recommendations: list[dict]
    risk_scores: list[dict]
    consolidations: list[dict]
    cleanup_items: NotRequired[dict]
