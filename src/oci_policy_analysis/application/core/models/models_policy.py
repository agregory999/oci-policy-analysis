"""Policy and statement models."""

from typing import Annotated, Literal, NotRequired, TypedDict

from .models_iam import DynamicGroup, DynamicGroupSearch, Group, GroupSearch, User, UserSearch


class Principal(TypedDict, total=False):
    """Canonical policy principal."""

    principal_type: Annotated[
        str,
        'Principal type.',
    ]
    principal_key: Annotated[str, 'Canonical principal key.']
    domain_name: NotRequired[Annotated[str | None, 'Identity domain.']]
    name: NotRequired[Annotated[str, 'Principal name.']]
    ocid: NotRequired[Annotated[str, 'Principal OCID.']]
    display_name: NotRequired[Annotated[str, 'Display label.']]
    resource_type: NotRequired[Annotated[str, 'Resource principal type from request.principal.type.']]
    resource_ocid: NotRequired[Annotated[str, 'Resource principal OCID from request.principal.id.']]
    compartment_ocid: NotRequired[Annotated[str, 'Resource principal compartment OCID.']]
    resource_compartment_ocid: NotRequired[Annotated[str, 'Resource principal compartment OCID.']]
    match_mode: NotRequired[Annotated[str, 'Principal match mode hint.']]


class ConditionAtom(TypedDict, total=False):
    """Parsed condition atom for display/evidence."""

    id: Annotated[str, 'Atom id within the clause.']
    left: Annotated[str, 'Left side expression.']
    operator: Annotated[str, 'Operator.']
    right: Annotated[str, 'Right side expression.']
    normalized_left: Annotated[str, 'Case-normalized left side.']
    value_type: Annotated[str, 'Right side value kind.']
    evidence_kind: Annotated[str, 'Evidence category.']
    subexpression: Annotated[str, 'Raw atom text.']


class ConditionStructure(TypedDict, total=False):
    """Parsed where/rule structure for display."""

    raw_text: Annotated[str, 'Raw clause text.']
    parse_status: Annotated[Literal['parsed', 'partial', 'unsupported', 'absent'], 'Parse status.']
    structure: Annotated[str, 'Compact tree summary.']
    atoms: Annotated[list[ConditionAtom], 'Flat condition atoms.']
    residual_text: Annotated[str, 'Unparsed or residual text.']
    warnings: Annotated[list[str], 'Parse warnings.']


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
    """Policy statement filters."""

    action: Annotated[list[str], "Statement actions: 'allow' or 'deny'."]
    exact_groups: Annotated[list[Group], 'Exact groups.']
    exact_users: Annotated[list[User], 'Exact users.']
    exact_dynamic_groups: Annotated[list[DynamicGroup], 'Exact dynamic groups.']
    search_groups: Annotated[GroupSearch, 'Fuzzy group search.']
    search_users: Annotated[UserSearch, 'Fuzzy user search.']
    search_dynamic_groups: Annotated[DynamicGroupSearch, 'Fuzzy dynamic group search.']
    principals: Annotated[
        list[Principal],
        'Structured principal selectors.',
    ]
    principal: Annotated[
        Principal,
        'Single structured principal selector.',
    ]
    principal_keys: Annotated[
        list[str],
        'Canonical principal keys.',
    ]
    verb: Annotated[
        list[Literal['inspect', 'read', 'use', 'manage']],
        'Policy verbs to match.',
    ]
    statement_text: Annotated[list[str], 'Statement text substrings.']
    policy_name: Annotated[list[str], 'Policy names.']
    compartment_path: Annotated[list[str], "Policy compartment paths; 'ROOTONLY' means root policies."]
    resource: Annotated[list[str], 'Policy resource types.']
    location: Annotated[
        list[str],
        'Policy locations or OCIDs.',
    ]
    effective_path: Annotated[
        list[str],
        'Effective paths; exact or prefix match.',
    ]
    subject_type: Annotated[
        list[Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']],
        'Policy subject types.',
    ]
    subject: Annotated[list[str], 'Subject identifiers.']
    principal_key: Annotated[
        list[str],
        'Legacy principal key filter.',
    ]
    permission: Annotated[list[str], 'Permission names.']
    comments: Annotated[list[str], 'Statement comment substrings.']
    conditions: Annotated[list[str], 'Condition substrings.']
    valid: Annotated[
        bool,
        'True for valid statements; false for invalid.',
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

    policy_name: Annotated[str, 'Policy name.']
    policy_ocid: Annotated[str, 'Policy OCID.']
    compartment_ocid: Annotated[str, 'Policy compartment OCID.']
    compartment_path: Annotated[str, 'Policy compartment path.']
    statement_text: Annotated[str, 'Raw policy statement.']
    creation_time: Annotated[str, 'Policy creation time.']
    internal_id: Annotated[str, 'Internal statement ID.']
    parsed: Annotated[bool, 'True when parsed.']


class DefineStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'define' policy statement with optional metadata."""

    valid: Annotated[bool, 'True when valid.']
    defined_type: Annotated[str, 'Defined object type.']
    defined_name: Annotated[str, 'Defined object name.']
    ocid_alias: Annotated[str, 'Defined OCID alias.']
    comment: NotRequired[Annotated[str, 'Statement comment.']]


class EndorseStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'endorse' cross-tenancy policy statement with optional metadata."""

    valid: Annotated[bool, 'True when valid.']
    action_type: Annotated[
        Literal['endorse', 'deny endorse'], 'Type of endorse action: either "endorse" or "deny endorse"'
    ]
    endorsed_principal_type: Annotated[
        Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service'],
        'Type of principal: group, dynamic-group, any-user, service.',
    ]
    principal_keys: NotRequired[Annotated[list[str], 'Canonical principal keys.']]
    endorsed_principal: Annotated[str, 'Endorsed principal.']
    endorsed_principal_tenancy: Annotated[str, 'Endorsed principal tenancy.']
    endorse_action: Annotated[str, 'Endorse verb/permission.']
    endorse_resource: Annotated[str, 'Endorse resource.']
    endorse_permissions: NotRequired[Annotated[list[str], 'Endorse permissions.']]
    endorse_tenancy: Annotated[str, 'Endorsed tenancy alias.']
    endorse_associate_resource: NotRequired[Annotated[str, 'Associate resource A.']]
    endorse_associate_tenancy: NotRequired[Annotated[str, 'Associate tenancy A.']]
    endorse_associate_with_resource: NotRequired[Annotated[str, 'Associate resource B.']]
    endorse_associate_with_tenancy: NotRequired[Annotated[str, 'Associate tenancy B.']]
    associate_clause_raw: NotRequired[Annotated[str, 'Raw associate clause.']]
    tenancy_aliases: NotRequired[Annotated[list[str], 'Referenced tenancy aliases.']]
    resolved_aliases: NotRequired[
        Annotated[
            dict[str, dict[str, str | bool]],
            'Alias resolution map populated by intelligence step; keys are alias names and values include ocid/resolved.',
        ]
    ]
    aliases_resolved: NotRequired[Annotated[bool, 'True when aliases resolve.']]
    where_clause: NotRequired[Annotated[str, 'Where clause.']]
    comment: NotRequired[Annotated[str, 'Statement comment.']]


class AdmitStatement(BasePolicyStatement, total=False):
    """Parsed OCI IAM 'admit' cross-tenancy policy statement with parsed metadata."""

    valid: Annotated[bool, 'True when valid.']
    action_type: Annotated[Literal['admit', 'deny admit'], 'Type of admit action: either "admit" or "deny admit"']
    admitted_principal_type: Annotated[
        Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service'],
        'Type of principal: group, dynamic-group, any-user, etc.',
    ]
    principal_keys: NotRequired[Annotated[list[str], 'Canonical principal keys.']]
    admitted_principal: Annotated[str, 'Admitted principal.']
    admitted_tenancy: Annotated[str, 'Admitted tenancy.']
    admit_action: Annotated[str, 'Admit verb/permission.']
    admit_resource: Annotated[str, 'Admit resource.']
    admit_permissions: NotRequired[Annotated[list[str], 'Admit permissions.']]
    admit_location_type: Annotated[str, 'Admit location type.']
    admit_location: Annotated[str, 'Admit location.']
    admit_associate_resource: NotRequired[Annotated[str, 'Associate resource A.']]
    admit_associate_tenancy: NotRequired[Annotated[str, 'Associate tenancy A.']]
    admit_associate_with_resource: NotRequired[Annotated[str, 'Associate resource B.']]
    admit_associate_with_tenancy: NotRequired[Annotated[str, 'Associate tenancy B.']]
    associate_clause_raw: NotRequired[Annotated[str, 'Raw associate clause.']]
    tenancy_aliases: NotRequired[Annotated[list[str], 'Referenced tenancy aliases.']]
    resolved_aliases: NotRequired[
        Annotated[
            dict[str, dict[str, str | bool]],
            'Alias resolution map populated by intelligence step; keys are alias names and values include ocid/resolved.',
        ]
    ]
    aliases_resolved: NotRequired[Annotated[bool, 'True when aliases resolve.']]
    where_clause: NotRequired[Annotated[str, 'Where clause.']]
    comment: NotRequired[Annotated[str, 'Statement comment.']]


class RegularPolicyStatement(BasePolicyStatement, total=False):
    """Represents a parsed OCI IAM policy statement."""

    action: Annotated[Literal['allow', 'deny'], "Statement action: 'allow' or 'deny'."]
    valid: Annotated[bool, 'True when valid.']
    invalid_reasons: Annotated[list[str], 'Validation errors.']
    subject_type: Annotated[
        str,
        'Policy subject type.',
    ]
    subject: Annotated[
        list[tuple[str | None, str]] | str,
        'Policy subject value.',
    ]
    principals: Annotated[
        list[Principal],
        'Canonical principals.',
    ]
    principal_keys: NotRequired[Annotated[list[str], 'Canonical principal keys.']]
    verb: Annotated[str, 'IAM verb.']
    resource: Annotated[str, 'Policy resource type.']
    permission: Annotated[
        list[str],
        'Derived permission names.',
    ]
    location_type: Annotated[str, 'Location resolution type.']
    location: Annotated[str, 'Policy location.']
    effective_compartment_ocid: Annotated[str | None, 'Effective compartment OCID.']
    effective_path: Annotated[
        str | None,
        'Effective compartment path.',
    ]
    conditions: Annotated[str, 'Statement conditions.']
    conditions_where_clause: NotRequired[Annotated[str, 'Raw conditions/where-clause text.']]
    conditions_parsed_structure: NotRequired[Annotated[str, 'Parsed condition tree summary.']]
    conditions_elements: NotRequired[Annotated[str, 'Parsed condition atoms for display.']]
    condition_atoms: NotRequired[Annotated[list[ConditionAtom], 'Parsed condition atoms.']]
    principal_evidence: NotRequired[
        Annotated[list[ConditionAtom], 'Condition atoms used as principal identity evidence.']
    ]
    residual_conditions: NotRequired[
        Annotated[list[ConditionAtom], 'Condition atoms not used as principal identity evidence.']
    ]
    match_confidence: NotRequired[Annotated[str, 'Workload principal match confidence.']]
    match_confidence_reason: NotRequired[Annotated[str, 'Explanation for workload principal match confidence.']]
    confidence: NotRequired[Annotated[str, 'Display confidence alias.']]
    where_clause: NotRequired[Annotated[ConditionStructure, 'Parsed where-clause structure.']]
    where_clause_structure: NotRequired[Annotated[ConditionStructure, 'Parsed where-clause structure.']]
    comments: Annotated[str, 'Statement comments.']
    parsing_notes: Annotated[list[str], 'Parser notes.']


class PolicySummary(TypedDict):
    """Policy filter summary."""

    response_type: Literal['summary']
    total_statements: Annotated[int, 'Matched statement count.']
    truncated: Annotated[bool, 'True when summarized.']
    truncation_point: Annotated[int, 'Full-result threshold.']
    policy_breakdown: Annotated[dict[str, int], 'Count by policy.']
    action_breakdown: Annotated[dict[str, int], 'Count by action.']
    compartment_breakdown: Annotated[dict[str, int], 'Count by compartment.']
    subject_type_breakdown: Annotated[dict[str, int], 'Count by subject type.']
    verb_breakdown: Annotated[dict[str, int], 'Count by verb.']
    sample_statements: Annotated[list[str], 'Sample statements.']
    message: Annotated[str, 'Summary note.']


class PolicyStatementFull(TypedDict):
    """Policy filter full result."""

    response_type: Literal['full']
    statements: Annotated[list[RegularPolicyStatement], 'Matched statements.']
    total_count: Annotated[int, 'Returned statement count.']


PolicyFilterResponse = Annotated[
    PolicySummary | PolicyStatementFull,
    'Policy filter result.',
]


class PolicyIntelligence(TypedDict, total=False):
    """Model for high-level analytics and findings of policy analysis (IAM intelligence overlay)."""

    overlaps: list[dict]
    recommendations: list[dict]
    risk_scores: list[dict]
    consolidations: list[dict]
    cleanup_items: NotRequired[dict]
