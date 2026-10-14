"""MCP request models that describe policy search inputs to tool consumers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MCPPrincipalSelector(BaseModel):
    """One identity selector; populated fields are matched together."""

    model_config = ConfigDict(extra='allow')

    principal_type: str | None = Field(
        default=None,
        description='Identity kind, such as group, dynamic-group, resource-principal, or instance-principal.',
    )
    domain_name: str | None = Field(default=None, description='Identity domain, such as Default.')
    name: str | None = Field(default=None, description='Group, user, or dynamic-group name.')
    ocid: str | None = Field(default=None, description='Exact identity OCID.')
    principal_key: str | None = Field(default=None, description='Exact canonical principal key.')
    resource_type: str | None = Field(default=None, description='Resource-principal OCI resource type.')
    compartment_ocid: str | None = Field(default=None, description='Resource-principal compartment OCID.')


class MCPPolicyFilters(BaseModel):
    """Discoverable common policy filters, with additional legacy fields retained."""

    model_config = ConfigDict(extra='allow')

    action: list[Literal['allow', 'deny']] | None = Field(
        default=None, description='Statement actions. Use ["allow"] when asking which identities are granted access.'
    )
    principal: MCPPrincipalSelector | None = Field(
        default=None, description='One structured identity selector, such as {"principal_type":"group"}.'
    )
    principals: list[MCPPrincipalSelector] | None = Field(
        default=None, description='Alternative identity selectors; any one may match.'
    )
    principal_keys: list[str] | None = Field(default=None, description='Exact canonical principal keys.')
    verb: list[Literal['inspect', 'read', 'use', 'manage']] | None = Field(
        default=None, description='OCI IAM policy verbs. Values are exact matches; multiple values are alternatives.'
    )
    resource: list[str] | None = Field(
        default=None,
        description=(
            'OCI policy resource type identifiers, not service names. Values are alternatives. '
            'For Object Storage, use buckets, objects, objectstorage-namespaces, object-family, and '
            'all-resources; or use resource_family="object storage" to include that full scope.'
        ),
    )
    resource_family: str | None = Field(
        default=None,
        description=(
            'Reference-data family name or alias. For example, "object storage" expands to '
            'buckets, objects, objectstorage-namespaces, object-family, and all-resources.'
        ),
    )
    permission: list[str] | None = Field(default=None, description='OCI permission names or substrings.')
    policy_name: list[str] | None = Field(default=None, description='Policy name substrings.')
    effective_path: list[str] | None = Field(default=None, description='Effective compartment paths.')
    statement_text: list[str] | None = Field(default=None, description='Raw policy statement text substrings.')


class MCPPolicySearchQuery(BaseModel):
    """The same query fields used by policy_search, usable within a search set."""

    model_config = ConfigDict(extra='allow')

    mode: Literal['simple', 'advanced'] = 'simple'
    detail_level: Literal['summary', 'simple', 'full'] = Field(
        default='simple', description='Use summary for comparisons; simple/full for bounded statement evidence.'
    )
    filters: MCPPolicyFilters | None = Field(default=None, description='The same typed filters as policy_search.')
    limit: int = Field(default=50, description='Detailed-row threshold capped at 50, not pagination.')


class MCPPolicySetSearch(MCPPolicySearchQuery):
    """One named check; direct query fields are preferred, legacy query wrappers remain accepted."""

    search_id: str = Field(
        default='', description='Unique identifier used in search_results and missing_required_searches.'
    )
    label: str = Field(default='', description='Short description of this comparison or required permission check.')
    required: bool = Field(
        default=True, description='Include this check in required-match coverage; false makes it informational.'
    )
    query: MCPPolicySearchQuery | None = Field(
        default=None, description='Legacy wrapped query, if supplied it takes precedence over direct query fields.'
    )


class MCPPolicySetEvaluation(BaseModel):
    """Optional evidence-coverage checks; matching statements are not effective authorization proof."""

    model_config = ConfigDict(extra='allow')

    min_confidence: Literal[
        'exact', 'subject_match_with_conditions', 'identity_match_with_residual', 'rule_evidence', 'broad', 'ambiguous'
    ] = Field(default='broad', description='Minimum acceptable statement-match confidence for required searches.')
    require_human_principal_coverage: bool = Field(
        default=False, description='Check for group-principal evidence across results.'
    )
    require_workload_principal_coverage: bool = Field(
        default=False, description='Check for workload-principal evidence across results.'
    )
    require_service_principal_coverage: bool = Field(
        default=False, description='Check for service-principal evidence across results.'
    )
    require_tag_condition_coverage: bool = Field(
        default=False, description='Request tag coverage caveats; this is not evaluated authorization.'
    )
