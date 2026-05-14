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
import time  # noqa: E402
from typing import Any  # noqa: E402

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from uvicorn import Server  # noqa: E402

from oci_policy_analysis.application.core.engine import PolicyIntelligenceEngine, PolicySimulationEngine  # noqa: E402
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository, ReferenceDataRepo  # noqa: E402
from oci_policy_analysis.common.caching import CacheManager  # noqa: E402
from oci_policy_analysis.common.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.common.models_iam import (  # noqa: E402
    DynamicGroupSearch,
    Group,
    GroupSearch,
    User,
    UserSearch,
)
from oci_policy_analysis.common.models_policy import (  # noqa: E402
    BasePolicyStatement,
    DefineStatement,
    PolicyFilterResponse,
    PolicySearch,
    PolicyStatementFull,
    PolicySummary,
)
from oci_policy_analysis.common.models_responses import (  # noqa: E402
    DynamicGroupSearchFull,
    DynamicGroupSearchResponse,
    DynamicGroupSummary,
    GroupSearchFull,
    GroupSearchResponse,
    GroupSummary,
    UserSearchFull,
    UserSearchResponse,
    UserSummary,
)
from oci_policy_analysis.common.models_simulation import (  # noqa: E402
    ProspectiveStatementInput,
    ProspectiveStatementResult,
    ProspectiveStatementSummary,
    SimulationBatchRequest,
    SimulationBatchResponse,
    SimulationPrepareRequest,
    SimulationPrepareResponse,
    SimulationResult,
)

try:  # usage tracking is optional when running embedded; ignore if unavailable
    from oci_policy_analysis.common.usage_tracking import get_usage_tracker  # type: ignore[import]
except Exception:  # pragma: no cover - defensive fallback

    def get_usage_tracker():  # type: ignore[no-redef]
        return None


# Global logger for this module
logger = get_logger(component='mcp_server')

mcp = FastMCP(name='OCI Policy MCP')
pca: PolicyAnalysisRepository | None = None

# Initialize the simulation engine (shares policy repo with PCA)
sim_engine: PolicySimulationEngine | None = None

# Decision logic: return summary if result set is too large
POLICY_RESULT_THRESHOLD = 50  # Adjust based on your needs

# Decision logic: return summary if result set is too large
IAM_SEARCH_THRESHOLD = 50  # Use the same threshold as policies


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


def _normalize_subject_for_mcp(stmt: dict) -> dict:
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
    stype = st.get('subject_type')
    if stype in ('any-user', 'any-group'):
        # Ensure JSON schema expecting an array type for "subject" is satisfied
        # regardless of how the repo stored this field internally.
        st['subject'] = []
        logger.debug('_normalize_subject_for_mcp: normalized subject for subject_type=%s', stype)
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


# --- Simulation Preparation Tool ---
@mcp.tool(
    name='prepare_simulation',
    description=(
        'Prepare a simulation for a specific compartment and principal. '
        'This tool returns all where-clause fields required for simulation for the specified context. '
        'Pass in the compartment_path (effective path), principal_type (e.g. "user", "any-user"), and principal '
        '(string for any-user/service, or (domain, name) tuple for user/group/dyn-group). '
        'See SimulationPrepareRequest for details.'
    ),
)
def prepare_simulation(request: SimulationPrepareRequest) -> SimulationPrepareResponse:
    """Return all required where-clause variable names for the given simulation context."""

    tool_name = 'prepare_simulation'
    try:
        if not sim_engine:
            raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')
        compartment_path = request.get('compartment_path')
        principal_type = request.get('principal_type')
        principal = request.get('principal')
        logger.info(
            'Preparing simulation for compartment="%s", type=%s, principal=%s',
            compartment_path,
            principal_type,
            principal,
        )
        principal_key, where_fields = sim_engine.get_required_where_fields_for_context(
            compartment_path, principal_type, principal
        )
        logger.info('Preparation Result: required_fields=%s, principal_key=%s', where_fields, principal_key)
        _track_mcp_tool(tool_name, status='success')
        return {'required_where_fields': list(where_fields), 'principal_key': principal_key}
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:  # defensive: normalize to ToolError
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in prepare_simulation: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in prepare_simulation: {exc}') from exc


# --- Simulation Batch Tool (Canonical MCP Flow) ---
@mcp.tool(
    name='run_simulation_batch',
    description=(
        'Run a batch of permission simulations for OCI principals and API operations. '
        'Input is a SimulationBatchRequest containing a list of SimulationScenario items. '
        'Each scenario must specify: compartment_path, principal_key (from prepare_simulation), api_operation, and where_context. '
        'checked_statement_ids should NOT be included. Result: SimulationBatchResponse with one result per input scenario. '
        "MCP never requests the trace ('trace' in SimulationBatchRequest should be omitted or false)."
    ),
)
def run_simulation_batch(request: SimulationBatchRequest) -> SimulationBatchResponse:
    """Batch run policy simulations per canonical MCP contract."""

    tool_name = 'run_simulation_batch'
    simulations = request.get('simulations', [])
    trace_requested = bool(request.get('trace', False))
    results: list[SimulationResult] = []

    try:
        if not sim_engine:
            raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')

        for scenario in simulations:
            try:
                compartment_path = scenario.get('compartment_path')
                principal_key = scenario.get('principal_key')
                api_operation = scenario.get('api_operation')
                where_context = scenario.get('where_context', {})
                engine_result = sim_engine.simulate_and_record(
                    principal_key,
                    compartment_path,
                    api_operation,
                    where_context,
                    trace=trace_requested,
                )

                sim_trace = engine_result.get('simulation_trace') or {}
                final_permissions = sim_trace.get('final_permission_set') or []
                required_perms = engine_result.get('required_permissions_for_api_operation') or sim_trace.get(
                    'required_permissions_for_api_operation',
                    [],
                )
                missing = engine_result.get('missing_permissions') or []
                failure_reason = engine_result.get('failure_reason') or ''

                sim_result: SimulationResult = {
                    'result': 'YES' if engine_result.get('api_call_allowed') else 'NO',
                    'api_call_allowed': bool(engine_result.get('api_call_allowed')),
                    'final_permission_set': list(final_permissions),
                    'required_permissions_for_api_operation': list(required_perms),
                    'missing_permissions': list(missing),
                    'failure_reason': str(failure_reason),
                }

                if trace_requested:
                    trace_statements = sim_trace.get('trace_statements') or []
                    sim_result['trace_statements'] = list(trace_statements)

                results.append(sim_result)
            except Exception as ex:
                logger.warning('Failed to simulate batch scenario %s: %s', scenario, ex)
                error_result: SimulationResult = {
                    'result': 'NO',
                    'api_call_allowed': False,
                    'final_permission_set': [],
                    'required_permissions_for_api_operation': [],
                    'missing_permissions': [],
                    'failure_reason': f'Simulation error: {ex}',
                }
                results.append(error_result)

        _track_mcp_tool(tool_name, status='success', count=len(simulations))
        return {'results': results}
    except ToolError:
        _track_mcp_tool(tool_name, status='error', count=len(simulations))
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error', count=len(simulations))
        logger.error('Unhandled error in run_simulation_batch: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in run_simulation_batch: {exc}') from exc


# ===========================================================
# PROSPECTIVE (WHAT-IF) STATEMENT MANAGEMENT TOOLS
# ===========================================================


@mcp.tool(
    name='list_prospective_statements',
    description=(
        'List all current prospective (what-if) policy statements loaded into the simulation engine. '
        'Each entry includes internal_id, policy_name, compartment_path, parsed/valid flags and invalid_reasons.'
    ),
)
def list_prospective_statements() -> list[ProspectiveStatementSummary]:
    """Return a summarized view of all currently configured prospective statements."""

    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')

    try:
        raw_list = sim_engine.get_prospective_statements() or []
    except Exception as exc:  # defensive
        logger.error('Failed to retrieve prospective statements from engine: %s', exc)
        raise ToolError(f'Failed to retrieve prospective statements from engine: {exc}') from exc

    summaries: list[ProspectiveStatementSummary] = []
    for pst in raw_list:
        summaries.append(
            ProspectiveStatementSummary(
                internal_id=pst.get('internal_id'),
                policy_name=pst.get('policy_name'),
                compartment_path=pst.get('compartment_path'),
                parsed=pst.get('parsed'),
                valid=pst.get('valid'),
                invalid_reasons=pst.get('invalid_reasons') or [],
                statement_text=pst.get('statement_text'),
            )
        )
    logger.info('list_prospective_statements: returning %d entries', len(summaries))
    try:
        tracker = get_usage_tracker()
        if tracker is not None:
            tracker.track_operation('mcp_tool', tool_name='list_prospective_statements', count=len(summaries))
    except Exception:
        logger.debug('Usage tracking for mcp_tool.list_prospective_statements failed', exc_info=True)
    return summaries


@mcp.tool(
    name='set_prospective_statements',
    description=(
        'Replace the entire set of prospective (what-if) policy statements used by the simulation engine. '
        'Input is a list of ProspectiveStatementInput objects; any existing prospective statements are discarded.'
    ),
)
def set_prospective_statements_tool(statements: list[ProspectiveStatementInput]) -> list[ProspectiveStatementSummary]:
    """Replace the engine's prospective statement list with the provided inputs and return summaries."""

    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')

    # Convert TypedDict input directly; engine expects simple dicts with the same keys.
    cleaned: list[dict] = []
    for st in statements or []:
        if not st.get('statement_text'):
            continue
        cleaned.append(
            {
                'compartment_path': st.get('compartment_path') or 'ROOT',
                'description': st.get('description') or '',
                'statement_text': st.get('statement_text') or '',
            }
        )

    try:
        sim_engine.set_prospective_statements(cleaned)
    except Exception as exc:
        logger.error('set_prospective_statements_tool: engine error: %s', exc, exc_info=True)
        raise ToolError(f'Failed to set prospective statements: {exc}') from exc

    try:
        tracker = get_usage_tracker()
        if tracker is not None:
            tracker.track_operation('mcp_tool', tool_name='set_prospective_statements', count=len(cleaned))
    except Exception:
        logger.debug('Usage tracking for mcp_tool.set_prospective_statements failed', exc_info=True)

    # Reuse list_prospective_statements for the summarized response
    return list_prospective_statements()


@mcp.tool(
    name='add_prospective_statement',
    description=(
        'Validate and add a single prospective (what-if) policy statement to the simulation engine. '
        'Returns parse/valid flags, any invalid reasons, normalized payload, and the assigned internal_id if added.'
    ),
)
def add_prospective_statement(input_model: ProspectiveStatementInput) -> ProspectiveStatementResult:
    """Validate and append a single prospective statement to the engine's what-if set."""

    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')

    stmt_text = (input_model.get('statement_text') or '').strip()
    compartment_path = (input_model.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    description = (input_model.get('description') or '').strip()

    if not stmt_text:
        return ProspectiveStatementResult(
            parsed=False,
            valid=False,
            invalid_reasons=['statement_text is required'],
            internal_id=None,
            normalized={},
            message='Prospective statement not added: statement_text is required.',
        )

    try:
        validation = sim_engine.validate_prospective_statement(stmt_text)
    except Exception as exc:
        logger.error('add_prospective_statement: validation error: %s', exc, exc_info=True)
        return ProspectiveStatementResult(
            parsed=False,
            valid=False,
            invalid_reasons=[str(exc)],
            internal_id=None,
            normalized={},
            message=f'Prospective statement validation raised an exception: {exc}',
        )

    parsed = bool(validation.get('parsed'))
    valid = bool(validation.get('valid'))
    invalid_reasons = validation.get('invalid_reasons') or []
    normalized = validation.get('normalized') or {}

    if not parsed or not valid:
        msg = 'Prospective statement parsed but is invalid.' if parsed else 'Prospective statement failed to parse.'
        return ProspectiveStatementResult(
            parsed=parsed,
            valid=valid,
            invalid_reasons=invalid_reasons,
            internal_id=None,
            normalized=normalized if parsed and valid else {},
            message=msg,
        )

    # Append to existing list and let the engine assign an internal_id.
    try:
        current = sim_engine.get_prospective_statements() or []
        before_ids = {pst.get('internal_id') for pst in current}
        current.append(
            {
                'compartment_path': compartment_path,
                'description': description,
                'statement_text': stmt_text,
            }
        )
        sim_engine.set_prospective_statements(current)
        updated = sim_engine.get_prospective_statements() or []
    except Exception as exc:
        logger.error('add_prospective_statement: engine error while appending: %s', exc, exc_info=True)
        return ProspectiveStatementResult(
            parsed=parsed,
            valid=valid,
            invalid_reasons=invalid_reasons,
            internal_id=None,
            normalized=normalized,
            message=f'Prospective statement validated but could not be added: {exc}',
        )

    # Find the newly-added statement's internal_id by diffing ids.
    after_ids = {pst.get('internal_id') for pst in updated}
    new_ids = [i for i in after_ids if i not in before_ids]
    assigned_id = new_ids[0] if new_ids else None

    result = ProspectiveStatementResult(
        parsed=parsed,
        valid=valid,
        invalid_reasons=invalid_reasons,
        internal_id=str(assigned_id) if assigned_id is not None else None,
        normalized=normalized,
        message='Prospective statement parsed, validated, and added successfully.'
        if assigned_id is not None
        else 'Prospective statement parsed and validated, but internal_id could not be determined.',
    )
    try:
        tracker = get_usage_tracker()
        if tracker is not None:
            tracker.track_operation('mcp_tool', tool_name='add_prospective_statement')
    except Exception:
        logger.debug('Usage tracking for mcp_tool.add_prospective_statement failed', exc_info=True)
    return result


@mcp.tool(
    name='clear_prospective_statements',
    description=(
        'Remove all prospective (what-if) statements from the simulation engine, restoring it to tenancy-only data.'
    ),
)
def clear_prospective_statements() -> dict:
    """Clear all currently configured prospective statements from the engine."""

    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')

    try:
        sim_engine.set_prospective_statements([])
        logger.info('clear_prospective_statements: all prospective statements removed.')
        try:
            tracker = get_usage_tracker()
            if tracker is not None:
                tracker.track_operation('mcp_tool', tool_name='clear_prospective_statements')
        except Exception:
            logger.debug('Usage tracking for mcp_tool.clear_prospective_statements failed', exc_info=True)
        return {'status': 'success', 'message': 'All prospective statements have been cleared.'}
    except Exception as exc:
        logger.error('clear_prospective_statements: engine error: %s', exc, exc_info=True)
        raise ToolError(f'Failed to clear prospective statements: {exc}') from exc


# Main Policy filter tool
@mcp.tool(
    name='filter_policy_statements',
    description=(
        'Favor this tool for all policy statement filtering needs.'
        'Filter OCI IAM policy statements using a JSON filter object. '
        'Each field is optional; OR within each field, AND across fields. '
        'Filtering allows Exact User, Group, Dynamic-Group matches. '
        'Fuzzy matching is also supported for user, group, and dynamic group criteria. '
        'Special cases: '
        '- verb must be one of inspect/read/use/manage '
        '- policy_compartment supports ROOTONLY to bring back policy statements only in the root compartment '
        '- policy_text matches anywhere in the statement text.'
        'Response: Returns either full policy statements or a summary based on result size. '
        'Large result sets (>100 statements) return a PolicySummary with counts and breakdowns. '
        'Smaller result sets return the complete PolicyStatement list.'
        'Filter Examples: '
        '- filter by verb and effective path: {"subject_type": ["group"], "subject": [{"domain_name": "Default", "group_name": "Admins"}], "verb": ["manage"], "resource": ["instance-family"]} '
        '- filter by exact user and verbs: {"exact_groups":[{"group_name":"PolicyAuditorGroup", "domain_name":"Default"}], "verb": ["manage","use"]} '
        '- filter by exact group, resource and verb: {"exact_groups":[{"group_name":"PolicyAuditorGroup", "domain_name":"Default"}], "verb": ["manage"], "resource": ["instance-family"]} '
        '- filter by exact dynamic group and location: {"exact_dynamic_groups":[{"dynamic_group_name":"DG1"}], "location": ["compartment1"]} '
        '- filter by users (fuzzy) and resource: {"search_users":{"search":["andrew","bob"], "user_ocid":["4qa","p57q"]}, "policy_compartment": ["ROOTONLY"]} '
        '- filter by groups (fuzzy) and resource: {"search_groups":{"search":["admins","developers"], "group_ocid":["4qa","p57q"], "domain_name": ["Default","domain1"]}, "resource": ["instance-family","database"]} '
        '- filter by dynamic groups (fuzzy) and resource: {"search_dynamic_groups":{"dynamic_group_name":["app","web"], "matching_rule":["instance.compartment.id","instance.id"], "domain_name": ["Default","domain1"]} '
    ),
)
def filter_policy_statements(filters: PolicySearch) -> PolicyFilterResponse:
    tool_name = 'filter_policy_statements'
    try:
        if not pca:
            raise ToolError('Repository not initialized. Run with a profile or instance principal.')

        logger.info('Tool Policy Filter with JSON filters: %s', filters)
        raw_results = pca.filter_policy_statements(filters)

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
        normalized_results = [_normalize_subject_for_mcp(st) for st in raw_results]

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
    description=(
        'Return all groups that a specified OCI IAM user belongs to. '
        'Input must include user_name but could also include domain_name. '
        "Returns a list of group dictionaries with keys 'group_name' and 'domain_name'. "
        'Only use this tool for getting groups for an exact User (no fuzzy matching). '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def get_groups_for_user(user: User) -> list[Group]:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Getting groups for user {user}')
        results = pca.get_groups_for_user(user)
        logger.debug(f'Groups: {results}')

        logger.info(f'Returning {len(results)} groups for user {user}')
        return results
    except Exception as e:
        raise ToolError(f'Failed to retrieve groups for user {user}: {e}') from e


@mcp.tool(
    name='get_users_for_group',
    description=(
        'Return all users that belong to a specified OCI IAM group. '
        "Input must include the group's domain (string or null for Default) and name (string). "
        "Returns a list of user dictionaries with keys 'user_name', 'user_id', and 'domain_name'. "
        'Only use this tool for getting users for an exact Group (no fuzzy matching). '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def get_users_for_group(group: Group) -> list[User]:
    """
    Get all users for a specific group.

    Args:
        group (Group): A dictionary containing:
            - 'domain_name' (str | None): The group's domain, or None for Default.
            - 'group_name' (str): The group name.

    Returns:
        list[User]: List of user entries who are members of that group.
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Getting users for group {group}')
        results = pca.get_users_for_group(group)
        logger.debug(f'Users: {results}')

        logger.info(f'Returning {len(results)} users for group {group}')
        return results
    except Exception as e:
        raise ToolError(f'Failed to retrieve users for group {group}: {e}') from e


# MCP Tool to search for users with Union type response
@mcp.tool(
    name='search_users',
    description=(
        'Return all users that match the specified criteria. '
        "Input may include the user's email (string) and name (string). "
        'Returns either a summary or full user list based on result size. '
        'Pass in no filter criteria to return all users. Any provided criteria will be combined with AND logic. '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def search_users(filters: UserSearch) -> UserSearchResponse:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Searching users with filters {filters}')
        raw_results = pca.filter_users(filters)
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
    description=(
        'Return all groups that match the specified criteria. '
        "Input may include the group's domain (string or null for Default) and name (string). "
        'Returns either a summary or full group list based on result size. '
        'Pass in no filter criteria to return all groups. Any provided criteria will be combined with AND logic. '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def search_groups(filters: GroupSearch) -> GroupSearchResponse:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Searching groups with filters {filters}')
        raw_results = pca.filter_groups(filters)
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
    description=(
        'Return all dynamic groups that match the specified criteria. '
        "Input may include the dynamic group's domain (string or null for Default) and name (string). "
        'Returns either a summary or full dynamic group list based on result size. '
        'Pass in no filter criteria to return all dynamic groups. Any provided criteria will be combined with AND logic. '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def search_dynamic_groups(filters: DynamicGroupSearch) -> DynamicGroupSearchResponse:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Searching dynamic groups with filters {filters}')
        raw_results = pca.filter_dynamic_groups(filters)
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


@mcp.tool('cross-tenancy-alias-list', description='List all defined aliases stored in the DataRepository.')
def list_cross_tenancy_aliases() -> list[DefineStatement]:
    """
    Retrieve all defined aliases as stored in the DataRepository.

    Returns:
        list[DefineStatement]: All aliases known to the repository.
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        raw_aliases = pca.defined_aliases
        logger.info(f'Returning {len(raw_aliases)} aliases')
        logger.debug(f'Aliases: {raw_aliases}')
        return raw_aliases
    except Exception as e:
        logger.error(f'Failed to list aliases: {e}')
        raise ToolError(f'Failed to list aliases: {e}') from e


@mcp.tool('cross-tenancy-policies-by-alias', description='Filter cross-tenancy policy statements for a given alias.')
def filter_cross_tenancy_policies_by_alias(alias: str) -> list[BasePolicyStatement]:
    """
    Retrieve all cross-tenancy policy statements that reference the provided alias.

    Args:
        alias (str): The named cross-tenancy alias to filter policy statements by.

    Returns:
        list[dict]: List of matching policy statements.
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f"Filtering cross-tenancy statements for alias '{alias}'")
        raw_results = pca.filter_cross_tenancy_policy_statements([alias])
        logger.info(f"Found {len(raw_results)} policy statements matching alias '{alias}'")
        logger.debug(f'Policies: {raw_results}')
        return raw_results
    except Exception as e:
        logger.error(f'Failed to filter policies by alias: {e}')
        raise ToolError(f'Failed to filter policies by alias: {e}') from e


# ===========================================================
# RELOAD MCP DATA TOOL
# ===========================================================
@mcp.tool(
    name='reload_mcp_data',
    description=(
        'Reload all policy and identity data from OCI into the MCP server repository. '
        'This allows refreshing data without restarting the server. '
        'Use with caution as it may take time depending on tenancy size.'
    ),
)
def reload_mcp_data() -> dict:
    """
    Reload all policy and identity data from OCI into the MCP server repository.

    Args:
        recursive (bool): Whether to recursively load all compartments. Default is True.

    Returns:
        dict: Summary of the reload operation.
    """

    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')

    try:
        if not (pca.policies_loaded_from_tenancy):
            raise ToolError(
                'Data reload is only supported when running with a profile, instance principal, or session token'
            )

        # Assuming we have data, reload it and create a new cache
        pca.load_complete_identity_domains()
        pca.load_policies_and_compartments()
        caching = CacheManager()
        logger.info('Saving new combined cache after data reload')
        caching.save_combined_cache(policy_analysis=pca)

        logger.info('Data reloaded successfully')
        return {
            'status': 'success',
            'message': 'Data reloaded successfully',
            'total_policies': len(pca.regular_statements),
            'data_as_of': pca.data_as_of,
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
    global server_thread, server_instance, pca, server_running

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
        f'Recursive={recursive}, Transport={args.transport}'
    )

    # --- Embedded Initialization ---
    global pca, sim_engine, reference_data_repo
    pca = PolicyAnalysisRepository()
    reference_data_repo = ReferenceDataRepo()

    # Load reference data so the simulation engine has permission and operation maps
    try:
        reference_data_repo.load_data()
        logger.info(
            'Reference data loaded for MCP server: services=%d, operations=%d',
            len(getattr(reference_data_repo, 'data', {}).get('services', {})),
            len(getattr(reference_data_repo, 'data', {}).get('operations', {})),
        )
    except Exception as exc:  # defensive: simulation can still run with direct permissions only
        logger.warning('Failed to load reference data for MCP server: %s', exc, exc_info=True)

    sim_engine = PolicySimulationEngine(policy_repo=pca, ref_data_repo=reference_data_repo)
    logger.info('Initialized Policy Analysis Repository and Simulation Engine.')

    # Create Cache Manager
    cache_manager = CacheManager()
    try:
        if args.use_cache:
            # Load from named cache
            logger.info(f'Loading data from cache: {args.use_cache}')
            if not cache_manager.load_combined_cache(policy_analysis=pca, named_cache=args.use_cache):
                logger.warning(f'Failed to load cache: {args.use_cache}')
                sys.exit(2)
        else:
            # Load live data from OCI
            logger.info(
                f'Loading live data from OCI tenancy using {"Instance Principal" if args.instance_principal else "Profile " + args.profile}'
            )
            if not pca.initialize_client(
                use_instance_principal=args.instance_principal,
                session_token=args.session_token or None,
                recursive=recursive,
                profile=(args.profile or 'DEFAULT'),
            ):
                logger.error('Failed initializing clients')
                sys.exit(2)
            # Client initialized successfully, load data
            pca.load_complete_identity_domains()
            pca.load_policies_and_compartments()
    except Exception as e:
        logger.warning(f'Policy and Identity domains load failed: {e}')
        exit(2)

    # Save the cache after load unless disabled
    if not args.dont_save_cache_after_load:
        # Save combined cache after loading from OCI
        logger.info('Saving combined cache after loading from OCI')
        cache_manager.save_combined_cache(policy_analysis=pca)

    # ---- Policy Intelligence step (MCP) ----
    logger.info('[MCP] Running minimal post-load policy intelligence')
    t0 = time.perf_counter()
    try:
        policy_intel = PolicyIntelligenceEngine(pca)
        policy_intel.calculate_all_effective_compartments()
        policy_intel.find_invalid_statements()
        policy_intel.run_dg_in_use_analysis()
    except Exception as exc:
        logger.warning(f'[MCP] Post-load policy intelligence raised exception: {exc}')
    t1 = time.perf_counter()
    logger.info(f'[MCP] Post-load policy intelligence completed in {t1 - t0:.2f}s')
    # ----------------------------------------

    logger.info(
        f'Tenancy loaded ({"from cache" if args.use_cache else "live"}). Policies: {len(pca.regular_statements)} regular, '
        f'{len(pca.cross_tenancy_statements)} cross-tenancy; '
        f'Groups: {len(pca.groups)}; Users: {len(pca.users)}; '
        f'Dynamic Groups: {len(pca.dynamic_groups)}'
    )

    # Now start Simulation Engine
    sim_engine = PolicySimulationEngine(policy_repo=pca, ref_data_repo=reference_data_repo)
    logger.info('Initialized Policy Analysis Repository and Simulation Engine.')

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
