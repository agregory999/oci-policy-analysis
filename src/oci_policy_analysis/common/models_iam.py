"""IAM entity and search models (groups, users, dynamic groups, compartments)."""

from typing import Annotated, NotRequired, TypedDict


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
    """Model representing an OCI IAM group (identity and metadata)."""

    domain_name: NotRequired[Annotated[str, 'The domain of the group. If not provided, the default domain.']]
    group_name: Annotated[str, 'The name of the group.']
    group_id: NotRequired[Annotated[str, 'The ID of the group. Not required for filters.']]
    group_ocid: NotRequired[Annotated[str, 'The OCID of the group. Not required for filters.']]
    description: NotRequired[Annotated[str, 'The description of the group. Not required for filters.']]


class User(TypedDict):
    """Model representing an OCI IAM user."""

    domain_name: NotRequired[Annotated[str, 'The domain of the user. If not provided, the default domain.']]
    user_name: Annotated[str, 'The user name. Required']
    user_ocid: NotRequired[Annotated[str, 'The user OCID. Not required for filters.']]
    display_name: NotRequired[Annotated[str, 'The display name. Not required for filters.']]
    email: NotRequired[Annotated[str, 'The primary email address. Not required for filters.']]
    user_id: NotRequired[Annotated[str, 'The user ID. Not required for filters.']]
    groups: NotRequired[Annotated[list[str], 'List of group OCIDs the user belongs to. Not required for filters.']]


class DynamicGroup(TypedDict):
    """Model representing an OCI IAM dynamic group."""

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


class GroupSearch(TypedDict, total=False):
    """Search model for OCI IAM groups."""

    domain_name: Annotated[
        list[str],
        'Domain name(s) to filter groups by. If provided, use the specified domain(s) to search. If not provided, the default domain is used.',
    ]

    group_name: Annotated[list[str], 'Group display name(s) to match. Accepts full or partial names.']

    group_ocid: Annotated[list[str], 'A list of OCIDs or partial OCIDs of the group.']


class UserSearch(TypedDict, total=False):
    """Search model for OCI IAM users."""

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
    """Search model for OCI IAM dynamic groups."""

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
