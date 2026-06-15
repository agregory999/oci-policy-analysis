##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# mcp_server.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

# Defensive: ensure sys.stderr exists (PyInstaller edge case)
import io  # noqa: E402
import sys

# ---- PATCH STDOUT/STDERR FOR UVICORN + PYINSTALLER ----
# This must run before any logging config is loaded by uvicorn.


class DummyStream(io.StringIO):
    def isatty(self):
        return False


# PyInstaller windowed application gives None for stdout/stderr
if sys.stdout is None:
    sys.stdout = DummyStream()

if sys.stderr is None:
    sys.stderr = DummyStream()
# -------------------------------------------------------

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
from typing import Any, Literal, TypedDict  # noqa: E402

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from uvicorn import Server  # noqa: E402

from oci_policy_analysis.application.context import AppContext  # noqa: E402
from oci_policy_analysis.application.core.models.models_iam import (  # noqa: E402
    DynamicGroupSearch,
    Group,
    GroupSearch,
    User,
    UserSearch,
)
from oci_policy_analysis.application.core.models.models_policy import (  # noqa: E402
    PolicySearch,
    PolicyStatementFull,
    PolicySummary,
    Principal,
)
from oci_policy_analysis.application.core.models.models_responses import (  # noqa: E402
    DynamicGroupSearchFull,
    DynamicGroupSummary,
    GroupSearchFull,
    GroupSummary,
    UserSearchFull,
    UserSummary,
)
from oci_policy_analysis.application.core.support import config  # noqa: E402
from oci_policy_analysis.application.core.support.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.application.services.load_service import LoadService  # noqa: E402
from oci_policy_analysis.application.services.mcp_query_service import MCPQueryService  # noqa: E402

try:  # usage tracking is optional when running embedded; ignore if unavailable
    from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker  # type: ignore[import]
except Exception:  # pragma: no cover - defensive fallback

    def get_usage_tracker():  # type: ignore[no-redef]
        return None


# Global logger for this module
logger = get_logger(component='mcp_server')

mcp = FastMCP(name='OCI Policy MCP')
app_context: AppContext | None = None

# Decision logic: return summary if result set is too large
POLICY_RESULT_THRESHOLD = 50  # Adjust based on your needs

# Decision logic: return summary if result set is too large
IAM_SEARCH_THRESHOLD = 50  # Use the same threshold as policies


class MCPPolicySearch(TypedDict, total=False):
    """Compact MCP policy filters."""

    action: list[str]
    principal: Principal
    principals: list[Principal]
    principal_keys: list[str]
    verb: list[Literal['inspect', 'read', 'use', 'manage']]
    statement_text: list[str]
    policy_name: list[str]
    compartment_path: list[str]
    resource: list[str]
    location: list[str]
    effective_path: list[str]
    subject_type: list[Literal['group', 'dynamic-group', 'any-user', 'any-group', 'service']]
    subject: list[str]
    principal_key: list[str]
    permission: list[str]
    comments: list[str]
    conditions: list[str]
    valid: bool


def _build_service_context(log_level: str) -> AppContext:
    """Create the service-backed application context used by standalone MCP."""

    settings = config.load_settings()
    settings['global_log_level'] = log_level
    return AppContext.from_settings(settings)


def _require_service_context() -> AppContext:
    """Return the active service context or raise a MCP tool error."""

    if app_context is None:
        raise ToolError('MCP service context is not initialized.')
    return app_context


def _query_service() -> MCPQueryService:
    """Return a query service bound to the active MCP application context."""

    return MCPQueryService(_require_service_context())


# ===========================================================
# TOOL REGISTRY FOR UI (Embedded MCP Tab)
# ===========================================================

_REGISTERED_TOOLS: list[dict[str, Any]] = []


def _track_mcp_tool(tool_name: str, status: str = 'success', **extra: object) -> None:
    """Best-effort anonymous tracking for MCP tool calls.

    This is only active when the embedded MCP server is running inside the
    main desktop UI with usage tracking enabled. Standalone MCP runs either
    do not import ``get_usage_tracker`` or return ``None`` from it.

    ``status`` is a coarse outcome flag (e.g. ``success`` or ``error``).
    ``extra`` can include non-personal aggregates such as ``count`` for
    batch sizes. No policy text, OCIDs, or identity data should ever be
    passed here.
    """

    try:
        tracker = get_usage_tracker()
        if tracker is None:
            return
        payload: dict[str, object] = {'tool_name': tool_name, 'status': status}
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        tracker.track_operation('mcp_tool', **payload)
    except Exception:
        logger.debug('Usage tracking for mcp_tool.%s (%s) failed', tool_name, status, exc_info=True)


def _normalize_policy_statement_for_mcp(stmt: dict) -> dict:
    """Return a MCP-safe copy of a policy statement.

    For any-user/any-group subjects, clear the subject list so that the
    JSON output always uses an array type for ``subject`` even when the
    underlying repository uses a simple string like "any-user".

    Semantics for these special subjects are conveyed via ``subject_type``;
    MCP consumers should rely on that field rather than the ``subject``
    contents. This helper is intentionally scoped to MCP output only and
    does not mutate the underlying repository statements.
    """

    # Shallow copy to avoid mutating repository-backed dicts.
    st = dict(stmt)
    string_fields = (
        'policy_name',
        'policy_ocid',
        'compartment_ocid',
        'compartment_path',
        'statement_text',
        'creation_time',
        'internal_id',
        'action',
        'subject_type',
        'verb',
        'resource',
        'location_type',
        'location',
        'conditions',
        'comments',
        'confidence',
        'match_confidence',
        'match_confidence_reason',
        'effective_compartment_ocid',
        'effective_path',
    )
    list_string_fields = ('permission', 'invalid_reasons', 'parsing_notes', 'principal_keys')

    # Ensure core string fields never carry null values in MCP output.
    for field in string_fields:
        if field in st:
            value = st.get(field)
            st[field] = '' if value is None else str(value)

    # Ensure list[str] fields are consistently string-safe.
    for field in list_string_fields:
        if field in st:
            value = st.get(field)
            if isinstance(value, list):
                st[field] = ['' if item is None else str(item) for item in value]
            elif value is None:
                st[field] = []
            else:
                st[field] = [str(value)]

    # Normalize canonical principals list for strict MCP output validation.
    principals_value = st.get('principals')
    if isinstance(principals_value, list):
        normalized_principals = []
        for principal in principals_value:
            if not isinstance(principal, dict):
                continue
            normalized_principal = dict(principal)
            for key in ('principal_type', 'principal_key', 'domain_name', 'name', 'ocid', 'display_name'):
                if key in normalized_principal:
                    value = normalized_principal.get(key)
                    normalized_principal[key] = '' if value is None else str(value)
            normalized_principals.append(normalized_principal)
        st['principals'] = normalized_principals

    stype = st.get('subject_type')
    if stype in ('any-user', 'any-group'):
        # Ensure JSON schema expecting an array type for "subject" is satisfied
        # regardless of how the repo stored this field internally.
        st['subject'] = []
        logger.debug('_normalize_subject_for_mcp: normalized subject for subject_type=%s', stype)
    elif isinstance(st.get('subject'), list):
        # MCP validates JSON output strictly. Legacy subject tuples may include
        # a None domain marker; principals/principal_keys carry canonical identity
        # semantics, so keep this display-oriented field string-safe.
        normalized_subjects = []
        for entry in st.get('subject', []):
            if isinstance(entry, (list | tuple)):
                normalized_subjects.append(['' if value is None else str(value) for value in entry])
            else:
                normalized_subjects.append('' if entry is None else str(entry))
        st['subject'] = normalized_subjects
    return st


def _summarize_schema(schema: dict[str, Any] | None) -> str:
    """Return a short description of a JSON schema for display in the MCP tab tools table.

    Preference is to list top-level property names; fall back to schema "type" if present.
    """

    if not schema or not isinstance(schema, dict):
        return ''
    props = schema.get('properties')
    if isinstance(props, dict) and props:
        return ', '.join(str(k) for k in props.keys())
    schema_type = schema.get('type')
    return str(schema_type) if schema_type else ''


def _refresh_registered_tools_from_mcp() -> None:
    """Rebuild the in-process registry from FastMCP's tool definitions.

    This inspects the FastMCP instance to derive tool metadata so the UI
    does not need to duplicate tool definitions.
    """

    global _REGISTERED_TOOLS
    tools: list[dict[str, Any]] = []

    # FastMCP exposes its tools via its tool manager; use the public get_tools() API.
    logger.info(
        '[_refresh_registered_tools_from_mcp] FastMCP instance type=%s, candidate tool-related attributes=%s',
        type(mcp),
        [name for name in dir(mcp) if 'tool' in name.lower()],
    )

    try:
        # FastMCP exposes a get_tools() helper that returns a mapping of tool name -> tool object
        get_tools_fn = getattr(mcp, 'get_tools', None)
        tools_map = get_tools_fn() if callable(get_tools_fn) else None
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('[_refresh_registered_tools_from_mcp] mcp.get_tools() failed: %s', exc, exc_info=True)
        tools_map = None

    if isinstance(tools_map, dict):
        tool_iter = list(tools_map.values())
    elif tools_map is None:
        tool_iter = []
    else:
        tool_iter = list(tools_map) if hasattr(tools_map, '__iter__') else []

    if not tool_iter:
        logger.warning(
            '[_refresh_registered_tools_from_mcp] No tools discovered via mcp.get_tools(); UI registry will be empty. '
            'tools_map=%r',
            tools_map,
        )
        _REGISTERED_TOOLS = []
        return

    logger.info(
        '[_refresh_registered_tools_from_mcp] tool_iter length=%d, sample=%r',
        len(tool_iter),
        tool_iter[:2],
    )

    for tool in tool_iter:
        try:
            name = getattr(tool, 'name', '')
            desc = getattr(tool, 'description', '')
            logger.info(
                '[_refresh_registered_tools_from_mcp] inspecting tool name=%r, type=%s, dir_contains_input_schema=%s, dir_contains_output_schema=%s',
                name,
                type(tool),
                'input_schema' in dir(tool),
                'output_schema' in dir(tool),
            )
            # FastMCP exposes JSON-schema-like input/output definitions on the tool;
            # use them if present, otherwise leave blank and let UI show empty strings.
            input_schema = getattr(tool, 'input_schema', None)
            output_schema = getattr(tool, 'output_schema', None)
            tools.append(
                {
                    'name': str(name),
                    'description': str(desc),
                    'inputs': _summarize_schema(input_schema) if input_schema is not None else '',
                    'outputs': _summarize_schema(output_schema) if output_schema is not None else '',
                }
            )
        except Exception as exc:  # defensive; do not break registry build for a single tool
            logger.error('Failed to register MCP tool metadata for UI: %s', exc, exc_info=True)

    _REGISTERED_TOOLS = tools
    logger.info('MCP tool registry built with %d tools for UI display', len(_REGISTERED_TOOLS))


def get_registered_tools() -> list[dict[str, Any]]:
    """Return the list of MCP tools as seen by the FastMCP instance.

    The result is used exclusively by the Embedded MCP tab to display
    name/description/inputs/outputs in a table. It does not require the
    server to be running; it reflects the tools registered on the FastMCP
    instance at import time (or after any explicit refresh).
    """

    # Lazy initialization: always try to refresh once when called from the UI.
    # This ensures that even if FastMCP attaches tools later in import order,
    # the registry is rebuilt the first time the Embedded MCP tab is shown.
    try:
        _refresh_registered_tools_from_mcp()
    except Exception as exc:  # defensive: never break callers due to registry issues
        logger.error('get_registered_tools: failed to refresh registry: %s', exc, exc_info=True)
    return list(_REGISTERED_TOOLS)


# --- Resources and Tools (unchanged) ---
@mcp.custom_route('/health', methods=['GET'])
async def health_check(request):
    # Perform any necessary checks here (e.g., database connection, external service availability)
    return JSONResponse({'status': 'healthy'})


# ---------------------
# --- Tools ---
# ---------------------


# Main Policy filter tool
@mcp.tool(
    name='filter_policy_statements',
    description=(
        'Primary policy search. Filter loaded OCI IAM statements; OR within a field, AND across fields. '
        'Large matches return a summary; smaller matches return full statements.'
    ),
)
def filter_policy_statements(filters: MCPPolicySearch) -> dict[str, Any]:
    """Filter policy statements through the MCP query service.

    Args:
        filters: Policy statement search criteria.

    Returns:
        PolicyFilterResponse: Full statement results or a summarized response.
    """
    tool_name = 'filter_policy_statements'
    try:
        logger.info('Tool Policy Filter with JSON filters: %s', filters)
        raw_results = _query_service().filter_policy_statements(PolicySearch(**filters))

        if len(raw_results) > POLICY_RESULT_THRESHOLD:
            # Generate summary response
            logger.info('Large result set (%d statements), returning summary', len(raw_results))

            # Calculate breakdowns
            policy_breakdown = {}
            action_breakdown = {}
            compartment_breakdown = {}
            subject_type_breakdown = {}
            verb_breakdown = {}

            for statement in raw_results:
                # Policy breakdown
                policy_name = statement.get('policy_name', 'Unknown')
                policy_breakdown[policy_name] = policy_breakdown.get(policy_name, 0) + 1

                # Action breakdown (allow/deny)
                action = statement.get('action', 'allow').lower()
                action_breakdown[action] = action_breakdown.get(action, 0) + 1

                # Compartment breakdown
                compartment = statement.get('policy_compartment', 'Unknown')
                compartment_breakdown[compartment] = compartment_breakdown.get(compartment, 0) + 1

                # Subject type breakdown
                subject_type = statement.get('subject_type', 'Unknown')
                subject_type_breakdown[subject_type] = subject_type_breakdown.get(subject_type, 0) + 1

                # Verb breakdown
                verb = statement.get('verb', 'Unknown')
                verb_breakdown[verb] = verb_breakdown.get(verb, 0) + 1

            # Get sample statements (first 15)
            sample_statements = [statement.get('statement_text', '') for statement in raw_results[:15]]

            summary_response: PolicySummary = {
                'response_type': 'summary',
                'total_statements': len(raw_results),
                'truncated': True,
                'truncation_point': POLICY_RESULT_THRESHOLD,
                'policy_breakdown': policy_breakdown,
                'action_breakdown': action_breakdown,
                'compartment_breakdown': compartment_breakdown,
                'subject_type_breakdown': subject_type_breakdown,
                'verb_breakdown': verb_breakdown,
                'sample_statements': sample_statements,
                'message': (
                    'Result set too large '
                    f'({len(raw_results)} statements). Returning summary with breakdowns. '
                    'Use more specific filters to get full details.'
                ),
            }

            logger.info('Returning summary for %d policy statements', len(raw_results))
            _track_mcp_tool(tool_name, status='success', total_statements=len(raw_results))
            return summary_response

        # Return full results for smaller sets
        logger.info('Manageable result set (%d statements), returning full data', len(raw_results))

        # Log raw results for debugging
        for st in raw_results:
            logger.debug('Raw Result: %s\n\n', st)

        # Normalize subjects for MCP output (e.g., any-user / any-group)
        normalized_results = [_normalize_policy_statement_for_mcp(st) for st in raw_results]

        full_response: PolicyStatementFull = {
            'response_type': 'full',
            'statements': normalized_results,
            'total_count': len(normalized_results),
        }

        logger.info('Filter returning %d full policy statements to client', len(normalized_results))
        _track_mcp_tool(tool_name, status='success', total_statements=len(normalized_results))
        return full_response
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in filter_policy_statements: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in filter_policy_statements: {exc}') from exc


# User and Group tools
@mcp.tool(
    name='get_groups_for_user',
    description=('Return groups for an exact OCI IAM user. Use search_users first when the user name is uncertain.'),
)
def get_groups_for_user(user: User) -> list[dict[str, Any]]:
    """Return groups for an exact user through the MCP query service.

    Args:
        user: Exact user descriptor.

    Returns:
        list[Group]: Groups containing the user.
    """
    try:
        logger.info(f'MCP Tool: Getting groups for user {user}')
        results = _query_service().get_groups_for_user(user)
        logger.debug(f'Groups: {results}')

        logger.info(f'Returning {len(results)} groups for user {user}')
        return results
    except Exception as e:
        raise ToolError(f'Failed to retrieve groups for user {user}: {e}') from e


@mcp.tool(
    name='get_users_for_group',
    description=('Return users for an exact OCI IAM group. Use search_groups first when the group name is uncertain.'),
)
def get_users_for_group(group: Group) -> list[dict[str, Any]]:
    """Get all users for a specific group.

    Args:
        group: Exact group descriptor.

    Returns:
        list[User]: List of user entries who are members of that group.
    """
    try:
        logger.info(f'MCP Tool: Getting users for group {group}')
        results = _query_service().get_users_for_group(group)
        logger.debug(f'Users: {results}')

        logger.info(f'Returning {len(results)} users for group {group}')
        return results
    except Exception as e:
        raise ToolError(f'Failed to retrieve users for group {group}: {e}') from e


# MCP Tool to search for users with Union type response
@mcp.tool(
    name='search_users',
    description=('Search loaded IAM users by domain, name/display name, or OCID. Empty filters list all users.'),
)
def search_users(filters: UserSearch) -> dict[str, Any]:
    """Search users through the MCP query service.

    Args:
        filters: User search criteria.

    Returns:
        UserSearchResponse: Full user results or a summarized response.
    """
    try:
        logger.info(f'MCP Tool: Searching users with filters {filters}')
        raw_results = _query_service().search_users(filters)
        logger.debug(f'Users: {json.dumps(raw_results, indent=4)}')

        if len(raw_results) > IAM_SEARCH_THRESHOLD:
            # Generate summary response
            from collections import Counter

            # Generate breakdowns
            domain_breakdown = Counter()
            sample_users = []

            for user in raw_results:
                domain_name = user.get('domain_name', 'Default')
                domain_breakdown[domain_name] += 1

                # Collect sample user names (first N)
                if len(sample_users) < 15:
                    user_name = user.get('user_name', user.get('email', 'Unknown'))
                    sample_users.append(user_name)

            logger.info(f'Returning summary for {len(raw_results)} users (threshold: {IAM_SEARCH_THRESHOLD})')
            return UserSummary(
                response_type='summary',
                total_users=len(raw_results),
                truncated=True,
                truncation_point=IAM_SEARCH_THRESHOLD,
                domain_breakdown=dict(domain_breakdown),
                sample_users=sample_users,
                message=f'Result set too large ({len(raw_results)} users). Returning summary with breakdowns. Use more specific filters to get full details.',
            )
        else:
            # Return full results
            logger.info(f'Returning {len(raw_results)} users (under threshold)')
            return UserSearchFull(response_type='full', users=raw_results, total_count=len(raw_results))

    except Exception as e:
        raise ToolError(f'Failed to retrieve users with filters {filters}: {e}') from e


# MCP tool to search for groups with Union type response
@mcp.tool(
    name='search_groups',
    description=('Search loaded IAM groups by domain, name, or OCID. Empty filters list all groups.'),
)
def search_groups(filters: GroupSearch) -> dict[str, Any]:
    """Search groups through the MCP query service.

    Args:
        filters: Group search criteria.

    Returns:
        GroupSearchResponse: Full group results or a summarized response.
    """
    try:
        logger.info(f'MCP Tool: Searching groups with filters {filters}')
        raw_results = _query_service().search_groups(filters)
        logger.debug(f'Groups: {json.dumps(raw_results, indent=4)}')

        # Decision logic: return summary if result set is too large
        IAM_SEARCH_THRESHOLD = 50  # Use the same threshold as policies

        if len(raw_results) > IAM_SEARCH_THRESHOLD:
            # Generate summary response
            from collections import Counter

            # Generate breakdowns
            domain_breakdown = Counter()
            sample_groups = []

            for group in raw_results:
                domain_name = group.get('domain_name', 'Default')
                domain_breakdown[domain_name] += 1

                # Collect sample group names (first N)
                if len(sample_groups) < 15:
                    group_name = group.get('group_name', 'Unknown')
                    sample_groups.append(group_name)

            logger.info(f'Returning summary for {len(raw_results)} groups (threshold: {IAM_SEARCH_THRESHOLD})')
            return GroupSummary(
                response_type='summary',
                total_groups=len(raw_results),
                truncated=True,
                truncation_point=IAM_SEARCH_THRESHOLD,
                domain_breakdown=dict(domain_breakdown),
                sample_groups=sample_groups,
                message=f'Result set too large ({len(raw_results)} groups). Returning summary with breakdowns. Use more specific filters to get full details.',
            )
        else:
            # Return full results
            logger.info(f'Returning {len(raw_results)} groups (under threshold)')
            return GroupSearchFull(response_type='full', groups=raw_results, total_count=len(raw_results))

    except Exception as e:
        raise ToolError(f'Failed to retrieve groups with filters {filters}: {e}') from e


# MCP tool to search for dynamic groups with Union type response
@mcp.tool(
    name='search_dynamic_groups',
    description=('Search loaded dynamic groups by domain, name, OCID, rule text, or in-use status.'),
)
def search_dynamic_groups(filters: DynamicGroupSearch) -> dict[str, Any]:
    """Search dynamic groups through the MCP query service.

    Args:
        filters: Dynamic group search criteria.

    Returns:
        DynamicGroupSearchResponse: Full dynamic group results or a summarized response.
    """
    try:
        logger.info(f'MCP Tool: Searching dynamic groups with filters {filters}')
        raw_results = _query_service().search_dynamic_groups(filters)
        logger.debug(f'Dynamic Groups: {json.dumps(raw_results, indent=4)}')

        # Decision logic: return summary if result set is too large
        IAM_SEARCH_THRESHOLD = 50  # Use the same threshold as policies

        if len(raw_results) > IAM_SEARCH_THRESHOLD:
            # Generate summary response
            from collections import Counter

            # Generate breakdowns
            domain_breakdown = Counter()
            in_use_breakdown = Counter()
            sample_dynamic_groups = []

            for dg in raw_results:
                domain_name = dg.get('domain_name', 'Default')
                domain_breakdown[domain_name] += 1

                # Track usage status
                in_use = dg.get('in_use', False)
                in_use_breakdown['in_use' if in_use else 'not_in_use'] += 1

                # Collect sample dynamic group names (first N)
                if len(sample_dynamic_groups) < 15:
                    dg_name = dg.get('dynamic_group_name', 'Unknown')
                    sample_dynamic_groups.append(dg_name)

            logger.info(f'Returning summary for {len(raw_results)} dynamic groups (threshold: {IAM_SEARCH_THRESHOLD})')
            return DynamicGroupSummary(
                response_type='summary',
                total_dynamic_groups=len(raw_results),
                truncated=True,
                truncation_point=IAM_SEARCH_THRESHOLD,
                domain_breakdown=dict(domain_breakdown),
                in_use_breakdown=dict(in_use_breakdown),
                sample_dynamic_groups=sample_dynamic_groups,
                message=f'Result set too large ({len(raw_results)} dynamic groups). Returning summary with breakdowns. Use more specific filters to get full details.',
            )
        else:
            # Return full results
            logger.info(f'Returning {len(raw_results)} dynamic groups (under threshold)')
            return DynamicGroupSearchFull(
                response_type='full', dynamic_groups=raw_results, total_count=len(raw_results)
            )

    except Exception as e:
        raise ToolError(f'Failed to retrieve dynamic groups with filters {filters}: {e}') from e


# --- CROSS TENANCY TOOLS START HERE ---


@mcp.tool('cross-tenancy-alias-list', description='List all loaded cross-tenancy alias definitions.')
def list_cross_tenancy_aliases() -> list[dict[str, Any]]:
    """Retrieve all defined aliases from the MCP query service.

    Returns:
        list[DefineStatement]: All aliases known to the active policy data.
    """
    try:
        raw_aliases = _query_service().list_cross_tenancy_aliases()
        logger.info(f'Returning {len(raw_aliases)} aliases')
        logger.debug(f'Aliases: {raw_aliases}')
        return [_normalize_policy_statement_for_mcp(stmt) for stmt in raw_aliases]
    except Exception as e:
        logger.error(f'Failed to list aliases: {e}')
        raise ToolError(f'Failed to list aliases: {e}') from e


@mcp.tool('cross-tenancy-policies-by-alias', description='Filter cross-tenancy policy statements for a given alias.')
def filter_cross_tenancy_policies_by_alias(alias: str) -> list[dict[str, Any]]:
    """Retrieve all cross-tenancy policy statements that reference an alias.

    Args:
        alias: The named cross-tenancy alias to filter policy statements by.

    Returns:
        list[BasePolicyStatement]: List of matching policy statements.
    """
    try:
        logger.info(f"Filtering cross-tenancy statements for alias '{alias}'")
        raw_results = _query_service().filter_cross_tenancy_policies_by_alias(alias)
        logger.info(f"Found {len(raw_results)} policy statements matching alias '{alias}'")
        logger.debug(f'Policies: {raw_results}')
        return [_normalize_policy_statement_for_mcp(stmt) for stmt in raw_results]
    except Exception as e:
        logger.error(f'Failed to filter policies by alias: {e}')
        raise ToolError(f'Failed to filter policies by alias: {e}') from e


# ===========================================================
# RELOAD MCP DATA TOOL
# ===========================================================
@mcp.tool(
    name='reload_mcp_data',
    description=(
        'Reload live OCI policy and identity data for this MCP server. Requires live auth, not cache-only mode.'
    ),
)
def reload_mcp_data() -> dict:
    """
    Reload all policy and identity data from OCI through the MCP load service.

    Args:
        recursive (bool): Whether to recursively load all compartments. Default is True.

    Returns:
        dict: Summary of the reload operation.
    """

    ctx = _require_service_context()
    repo = ctx.policy_repo

    try:
        if not getattr(repo, 'policies_loaded_from_tenancy', False):
            raise ToolError(
                'Data reload is only supported when running with a profile, instance principal, or session token'
            )

        auth_args = globals().get('args')
        if auth_args is None:
            raise ToolError('Reload is only supported for standalone MCP runs.')

        result = LoadService(ctx).load_from_tenancy(
            use_instance_principal=bool(getattr(auth_args, 'instance_principal', False)),
            profile=getattr(auth_args, 'profile', None) or None,
            session_token=getattr(auth_args, 'session_token', None) or None,
            recursive=bool(getattr(auth_args, 'recursive', True)),
            save_cache_after_load=True,
        )
        if not result.success:
            raise ToolError(result.message)

        logger.info('Data reloaded successfully')
        return {
            'status': 'success',
            'message': 'Data reloaded successfully',
            'total_policies': len(repo.regular_statements),
            'data_as_of': repo.data_as_of,
        }
    except Exception as e:
        logger.error(f'Failed to reload data: {e}')
        raise ToolError(f'Failed to reload data: {e}') from e


# ============================================================
# EMBEDDED SERVER CONTROL (for Tkinter integration)
# ============================================================

server_thread: threading.Thread | None = None
server_instance: Server | None = None
server_running: bool = False


def start_mcp_server_in_thread(settings: dict):
    """
    Start MCP server in a background thread (for Tkinter integration).

    Args:
        config (dict): MCP server config {host, port, key_path, cert_path, ...}
        log_fn (callable): optional logger callback, e.g. PopupConsole.write_line()
    """
    global server_thread, server_instance, server_running

    # prevent multiple starts
    if server_thread and server_thread.is_alive():
        logger.info('MCP server is already running.')
        return

    # Set the boolean for running status before starting the thread to prevent race conditions in status checks
    server_running = False  # reset

    def _run():
        global server_running
        try:
            logger.info(
                f"Starting FastMCP server on {settings.get('mcp_host', '127.0.0.1')}:{settings.get('mcp_port', 8765)}"
            )
            server_running = True
            mcp.run(
                transport='streamable-http',
                port=settings.get('mcp_port', 8765),
                host=settings.get('mcp_host', '127.0.0.1'),
                show_banner=False,
            )
        except Exception as e:
            logger.exception(f'MCP server crashed: {e}')
        finally:
            logger.info('MCP server thread exited.')
            server_running = False

    # run uvicorn in a daemon thread so Tkinter stays responsive
    server_thread = threading.Thread(target=_run, daemon=True)
    server_thread.start()


def mcp_server_status() -> bool:
    """
    Check if the MCP server is currently running.

    Returns:
        bool: True if the server is running, False otherwise.
    """
    global server_thread
    return bool(server_thread and server_thread.is_alive())


# ============================================================
# Main Entry Point for standalone MCP server run
# ============================================================


def _build_arg_parser():
    parser = argparse.ArgumentParser()
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument('--profile')
    auth.add_argument('--instance-principal', action='store_true')
    auth.add_argument('--resource-principal', action='store_true')
    auth.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    auth.add_argument('--session-token', help='OCI session token for instance principal auth', default=None)
    parser.add_argument(
        '--recursive', action='store_true', default=True, help='Recursively load all compartments (default: True)'
    )
    parser.add_argument(
        '--dont-save-cache-after-load', help='Save the combined cache after loading from OCI', action='store_true'
    )
    parser.add_argument('--transport', default='stdio', choices=['stdio', 'streamable-http'])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument(
        '--compartment-domain-search-depth',
        type=int,
        default=1,
        choices=range(1, 7),
        metavar='[1-6]',
        help='Depth for identity-domain compartment traversal (1=root only, 2=include direct children, max=6).',
    )
    parser.add_argument(
        '--log-level',
        default='WARNING',
        choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'critical', 'error', 'warning', 'info', 'debug'],
        help='Application and MCP framework log level for standalone MCP mode (default: WARNING).',
    )
    return parser


def main():
    """
    Entry point for the OCI Policy Analysis Standalone MCP Server.

    Parses command-line arguments to load, filter, display, or export OCI identity and policy information
    from Oracle Cloud Infrastructure (OCI) using cached or live data.
    """
    logger.info('MCP server module logger initialized.')

    global args
    args = _build_arg_parser().parse_args()
    args.log_level = str(args.log_level).upper()
    set_log_level(args.log_level, announce=False)
    logging.getLogger('mcp').setLevel(args.log_level)
    logging.getLogger('mcp.server').setLevel(args.log_level)
    recursive = args.recursive

    logger.info(
        f'Loading MCP Server using Profile={args.profile or "DEFAULT"}, '
        f'InstancePrincipal={args.instance_principal}, '
        f'ResourcePrincipal={args.resource_principal}, '
        f'Recursive={recursive}, '
        f'CompartmentDomainSearchDepth={args.compartment_domain_search_depth}, '
        f'Transport={args.transport}'
    )

    global app_context
    app_context = _build_service_context(args.log_level)
    load_service = LoadService(app_context)

    try:
        if args.use_cache:
            result = load_service.load_from_cache(args.use_cache)
        else:
            result = load_service.load_from_tenancy(
                use_instance_principal=args.instance_principal,
                use_resource_principal=bool(args.resource_principal),
                profile=args.profile or None,
                session_token=args.session_token or None,
                recursive=recursive,
                compartment_domain_search_depth=args.compartment_domain_search_depth,
                save_cache_after_load=not args.dont_save_cache_after_load,
            )
        if not result.success:
            logger.error('MCP data load failed: %s', result.message)
            sys.exit(2)
    except Exception as e:
        logger.warning(f'Policy and Identity domains load failed: {e}')
        sys.exit(2)

    repo = app_context.policy_repo
    logger.info(
        f'Tenancy loaded ({"from cache" if args.use_cache else "live"}). Policies: {len(repo.regular_statements)} regular, '
        f'{len(repo.cross_tenancy_statements)} cross-tenancy; '
        f'Groups: {len(repo.groups)}; Users: {len(repo.users)}; '
        f'Dynamic Groups: {len(repo.dynamic_groups)}'
    )

    # --- Start MCP Server ---
    if args.transport == 'stdio':
        logger.info(
            'Starting MCP server in stdio mode - if you get errors, please ensure you set environment variable MCP_STDIO_MODE=1'
        )
        mcp.run(transport='stdio', show_banner=False, log_level=args.log_level.lower())
        # mcp.run(transport='stdio', show_banner=False)
    else:
        mcp.run(
            transport='streamable-http',
            port=args.port,
            host=args.host,
            log_level=args.log_level.lower(),
            show_banner=False,
        )


if __name__ == '__main__':
    main()
