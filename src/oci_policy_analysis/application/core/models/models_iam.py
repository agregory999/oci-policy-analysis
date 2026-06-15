"""IAM entity and search models (groups, users, dynamic groups, compartments)."""

from typing import Annotated, Literal, NotRequired, TypedDict


class Compartment(TypedDict, total=False):
    """
    Model representing an OCI compartment (identity and metadata).
    Captures id, name, parent, description, path, lifecycle, and tags where available.
    Adds optional analysis/derived fields for policy statement counts.

    Optional/derived fields (set after loading and analysis):
      - statement_count_direct: Number of policy statements directly in this compartment.
      - statement_count_cumulative: Cumulative policy statements (this + all ancestors in path).
    """

    id: Annotated[str, 'Compartment OCID']
    name: Annotated[str, 'Display name of the compartment']
    parent_id: Annotated[str, 'Parent compartment OCID']
    hierarchy_path: Annotated[str, 'Full compartment hierarchy path, e.g., "ROOT/HR/Payroll"']
    description: NotRequired[Annotated[str, 'Description of the compartment']]
    lifecycle_state: NotRequired[Annotated[str, 'Lifecycle state (e.g., ACTIVE, DELETED)']]
    tags: NotRequired[
        Annotated[dict[str, str], 'Optional. All freeform and defined tags associated with the compartment.']
    ]
    statement_count_direct: NotRequired[
        Annotated[int, 'Number of policy statements directly in this compartment (analysis-derived, optional)']
    ]
    statement_count_cumulative: NotRequired[
        Annotated[int, 'Cumulative number of policy statements including all ancestors (analysis-derived, optional)']
    ]


class Group(TypedDict):
    """OCI IAM group."""

    domain_name: NotRequired[Annotated[str, 'Identity domain; defaults to Default.']]
    group_name: Annotated[str, 'Group name.']
    group_id: NotRequired[Annotated[str, 'Group ID.']]
    group_ocid: NotRequired[Annotated[str, 'Group OCID.']]
    description: NotRequired[Annotated[str, 'Group description.']]


class User(TypedDict):
    """OCI IAM user."""

    domain_name: NotRequired[Annotated[str, 'Identity domain; defaults to Default.']]
    user_name: Annotated[str, 'User name.']
    user_ocid: NotRequired[Annotated[str, 'User OCID.']]
    display_name: NotRequired[Annotated[str, 'Display name.']]
    email: NotRequired[Annotated[str, 'Primary email.']]
    user_id: NotRequired[Annotated[str, 'User ID.']]
    groups: NotRequired[Annotated[list[str], 'Group OCIDs.']]


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
    """Parsed rule/where structure for display."""

    raw_text: Annotated[str, 'Raw clause text.']
    parse_status: Annotated[Literal['parsed', 'partial', 'unsupported', 'absent'], 'Parse status.']
    structure: Annotated[str, 'Compact tree summary.']
    atoms: Annotated[list[ConditionAtom], 'Flat condition atoms.']
    residual_text: Annotated[str, 'Unparsed or residual text.']
    warnings: Annotated[list[str], 'Parse warnings.']


class DynamicGroup(TypedDict):
    """OCI dynamic group."""

    domain_name: NotRequired[Annotated[str, 'Identity domain; defaults to Default.']]
    domain_ocid: NotRequired[Annotated[str, 'Domain OCID.']]
    dynamic_group_name: Annotated[str, 'Dynamic group name.']
    dynamic_group_ocid: NotRequired[Annotated[str, 'Dynamic group OCID.']]
    dynamic_group_id: NotRequired[Annotated[str, 'Dynamic group ID.']]
    matching_rule: NotRequired[Annotated[str, 'Dynamic group matching rule.']]
    matching_rule_parsed_structure: NotRequired[Annotated[str, 'Parsed matching-rule summary.']]
    matching_rule_elements: NotRequired[Annotated[str, 'Parsed matching-rule atoms for display.']]
    matching_rule_structure: NotRequired[Annotated[ConditionStructure, 'Parsed matching-rule structure.']]
    description: NotRequired[Annotated[str | None, 'Dynamic group description.']]
    in_use: NotRequired[Annotated[bool, 'True when referenced by policy.']]
    creation_time: NotRequired[Annotated[str, 'Creation time.']]
    created_by_ocid: NotRequired[Annotated[str, 'Creator OCID.']]
    created_by_name: NotRequired[Annotated[str, 'Creator name.']]


class GroupSearch(TypedDict, total=False):
    """Group search filters."""

    domain_name: Annotated[
        list[str],
        'Domain names to match.',
    ]

    group_name: Annotated[list[str], 'Group names or substrings.']

    group_ocid: Annotated[list[str], 'Group OCIDs or substrings.']


class UserSearch(TypedDict, total=False):
    """User search filters."""

    domain_name: Annotated[
        list[str],
        'Domain names to match.',
    ]

    search: Annotated[
        list[str],
        'User names/display names or substrings.',
    ]

    user_ocid: Annotated[str, 'User OCIDs or substrings.']


class DynamicGroupSearch(TypedDict, total=False):
    """Dynamic group search filters."""

    domain_name: NotRequired[
        Annotated[
            list[str],
            'Domain names to match.',
        ]
    ]

    dynamic_group_name: NotRequired[Annotated[list[str], 'Dynamic group names or substrings.']]

    matching_rule: NotRequired[
        Annotated[
            list[str],
            'Matching rule substrings.',
        ]
    ]

    dynamic_group_ocid: Annotated[str, 'Dynamic group OCIDs or substrings.']
    in_use: NotRequired[
        Annotated[
            bool,
            'Filter by policy reference status.',
        ]
    ]
