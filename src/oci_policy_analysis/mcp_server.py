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
import threading  # noqa: E402

from deepdiff import DeepDiff  # noqa: E402
from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from uvicorn import Server  # noqa: E402

from oci_policy_analysis.common.caching import CacheManager  # noqa: E402
from oci_policy_analysis.common.logger import get_logger  # noqa: E402
from oci_policy_analysis.common.models import (  # noqa: E402
    BasePolicyStatement,
    DefineStatement,
    DynamicGroupSearch,
    DynamicGroupSearchFull,
    DynamicGroupSearchResponse,
    DynamicGroupSummary,
    Group,
    GroupSearch,
    GroupSearchFull,
    GroupSearchResponse,
    GroupSummary,
    PolicyFilterResponse,
    PolicySearch,
    PolicyStatementFull,
    PolicySummary,
    ReferenceDataDiffResult,
    SimulationBatchRequest,
    SimulationBatchResponse,
    SimulationPrepareRequest,
    SimulationPrepareResponse,
    User,
    UserSearch,
    UserSearchFull,
    UserSearchResponse,
    UserSummary,
)
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository  # noqa: E402
from oci_policy_analysis.logic.diff_utils import canonical_filter  # noqa: E402
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine  # noqa: E402

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
    """
    Return all required where-clause variable names for the given simulation context.

    Args:
        request: SimulationPrepareRequest

    Returns:
        SimulationPrepareResponse
    """
    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')
    compartment_path = request.get('compartment_path')
    principal_type = request.get('principal_type')
    principal = request.get('principal')
    logger.info(
        f'Preparing simulation for compartment="{compartment_path}", type={principal_type}, principal={principal}'
    )
    principal_key, where_fields = sim_engine.get_required_where_fields_for_context(
        compartment_path, principal_type, principal
    )
    logger.info(f'Preparation Result: required_fields={where_fields}, principal_key={principal_key}')
    return {'required_where_fields': list(where_fields), 'principal_key': principal_key}


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
    """
    Batch run policy simulations per canonical MCP contract.

    Args:
        request (SimulationBatchRequest): {
            "simulations": [SimulationScenario, ...],
            "trace": bool (optional, but ignored)
        }

    Returns:
        SimulationBatchResponse: {
            "results": [SimulationResult, ...]
        }
    """
    if not sim_engine:
        raise ToolError('Simulation engine not initialized. Ensure repository/init ran successfully.')
    simulations = request.get('simulations', [])
    results = []
    for scenario in simulations:
        try:
            compartment_path = scenario.get('compartment_path')
            principal_key = scenario.get('principal_key')
            api_operation = scenario.get('api_operation')
            where_context = scenario.get('where_context', {})
            # checked_statement_ids is absent (canonical MCP flow)
            # trace always False for MCP batch
            sim_result = sim_engine.simulate_and_record(
                principal_key, compartment_path, api_operation, where_context, trace=False
            )
            # Remove redundant or legacy fields if present (keep strictly to SimulationResult shape)
            if 'trace' in sim_result:
                sim_result.pop('trace')
            results.append(sim_result)
        except Exception as ex:
            logger.warning(f'Failed to simulate batch scenario: {scenario}, error: {ex}')
            results.append(
                {
                    'result': 'NO',
                    'api_call_allowed': False,
                    'final_permission_set': [],
                    'required_permissions_for_api_operation': [],
                    'missing_permissions': [],
                    'failure_reason': f'Simulation error: {ex}',
                }
            )
    return {'results': results}


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
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(f'Tool Policy Filter with JSON filters: {filters}')
    raw_results = pca.filter_policy_statements(filters)

    if len(raw_results) > POLICY_RESULT_THRESHOLD:
        # Generate summary response
        logger.info(f'Large result set ({len(raw_results)} statements), returning summary')

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
            'message': f'Result set too large ({len(raw_results)} statements). Returning summary with breakdowns. Use more specific filters to get full details.',
        }

        logger.info(f'Returning summary for {len(raw_results)} policy statements')
        return summary_response

    else:
        # Return full results for smaller sets
        logger.info(f'Manageable result set ({len(raw_results)} statements), returning full data')

        for st in raw_results:
            logger.debug(f'Raw Result: {st} \n\n')

        full_response: PolicyStatementFull = {
            'response_type': 'full',
            'statements': raw_results,
            'total_count': len(raw_results),
        }

        logger.info(f'Filter returning {len(raw_results)} full policy statements to client')
        return full_response


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
        logger.info(f"Filtering cross-tenancy policies for alias '{alias}'")
        raw_results = pca.filter_cross_tenancy_policy_statements([alias])
        logger.info(f"Found {len(raw_results)} policy statements matching alias '{alias}'")
        logger.debug(f'Policies: {raw_results}')
        return raw_results
    except Exception as e:
        logger.error(f'Failed to filter policies by alias: {e}')
        raise ToolError(f'Failed to filter policies by alias: {e}') from e


# ===========================================================
# REFERENCE DATA CACHE COMPARISON TOOL
# ===========================================================


@mcp.tool(
    name='compare_reference_data_caches',
    description='Compares the previous reference data cache for this tenancy to the current in-memory state using DeepDiff and returns a summarized result of the changes.',
)
def compare_reference_data_caches() -> ReferenceDataDiffResult:
    """
    Compares the in-memory current repository state ("right") to the previous-dated cache ("left") for this tenancy.

    Returns:
        ReferenceDataDiffResult: diff information and a summary
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')

    try:
        cache_mgr = CacheManager(policy_analysis=pca)
        cache_names = cache_mgr.get_available_cache(getattr(pca, 'tenancy_name', None))
        if not cache_names or len(cache_names) < 1:
            raise ToolError('No cached reference data sets available for comparison.')

        # Newest cache is current state, so previous is the "left" for comparison (if available)
        if len(cache_names) == 1:
            raise ToolError('At least one previous cached data set required for comparison.')

        # The most recent (cache_names[0]) may be the just-now-saved one (equivalent to in-memory);
        # we want to compare the previous cache file against in-memory as of now.
        previous_cache_name = cache_names[1]
        data_a = cache_mgr.load_cache_into_local_json(previous_cache_name)

        # Prepare the current repo state as would be saved to cache by current CacheManager logic
        combined_data = {
            'tenancy_name': pca.tenancy_name,
            'tenancy_ocid': pca.tenancy_ocid,
            'policies': pca.regular_statements,
            'dynamic_groups': pca.dynamic_groups,
            'defined_aliases': pca.defined_aliases,
            'cross_tenancy_policies': pca.cross_tenancy_statements,
            'compartments': pca.compartments,
            'identity_domains': pca._get_domains(),
            'groups': pca.groups,
            'users': pca.users,
            'data_as_of': pca.data_as_of,
        }
        data_b = combined_data

        # Show counts for each section for debug
        logger.info(
            f'Previous cache data counts: policies={len(data_a.get("policies", []))}, '
            f'dynamic_groups={len(data_a.get("dynamic_groups", []))}, '
            f'defined_aliases={len(data_a.get("defined_aliases", []))}, '
            f'cross_tenancy_policies={len(data_a.get("cross_tenancy_policies", []))}, '
            f'compartments={len(data_a.get("compartments", []))}, '
            f'identity_domains={len(data_a.get("identity_domains", []))}, '
            f'groups={len(data_a.get("groups", []))}, '
            f'users={len(data_a.get("users", []))}'
        )
        logger.info(
            f'Current in-memory data counts: policies={len(data_b.get("policies", []))}, '
            f'dynamic_groups={len(data_b.get("dynamic_groups", []))}, '
            f'defined_aliases={len(data_b.get("defined_aliases", []))}, '
            f'cross_tenancy_policies={len(data_b.get("cross_tenancy_policies", []))}, '
            f'compartments={len(data_b.get("compartments", []))}, '
            f'identity_domains={len(data_b.get("identity_domains", []))}, '
            f'groups={len(data_b.get("groups", []))}, '
            f'users={len(data_b.get("users", []))}'
        )

        if not data_a or not data_b:
            raise ToolError('Unable to access previous cache and/or current state for comparison.')

        left_filtered = canonical_filter(data_a)
        right_filtered = canonical_filter(data_b)

        ddiff = DeepDiff(left_filtered, right_filtered, ignore_order=True, verbose_level=2)
        diff_summary = ', '.join(f'{k}: {len(v)}' for k, v in ddiff.items() if isinstance(v, (dict, list)) or v)  # noqa: UP038
        if not diff_summary:
            diff_summary = 'No differences detected.'
        message = f"Compared previous cache '{previous_cache_name}' vs current memory. {diff_summary}"
        logger.info(message)

        result: ReferenceDataDiffResult = {
            'response_type': 'reference_data_diff',
            'cache_a': str(previous_cache_name),
            'cache_b': 'in-memory current state',
            'diff_summary': diff_summary,
            'diff_details': ddiff.to_dict() if hasattr(ddiff, 'to_dict') else dict(ddiff),
            'message': message,
        }
        return result

    except Exception as e:
        logger.error(f'Error comparing reference data caches: {e}')
        raise ToolError(f'Failed to compare reference data caches: {e}') from e


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

    logger.debug(f'Starting MCP server thread with config: {settings}')
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
    recursive = args.recursive

    logger.info(
        f'Loading MCP Server using Profile={args.profile or "DEFAULT"}, '
        f'InstancePrincipal={args.instance_principal}, '
        f'Recursive={recursive}, Transport={args.transport}'
    )

    # --- Embedded Initialization ---
    global pca, sim_engine
    pca = PolicyAnalysisRepository()
    sim_engine = PolicySimulationEngine(policy_repo=pca, ref_data_repo=getattr(pca, 'reference_data_repo', None))
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

    logger.info(
        f'Tenancy loaded ({"from cache" if args.use_cache else "live"}). Policies: {len(pca.regular_statements)} regular, '
        f'{len(pca.cross_tenancy_statements)} cross-tenancy; '
        f'Groups: {len(pca.groups)}; Users: {len(pca.users)}; '
        f'Dynamic Groups: {len(pca.dynamic_groups)}'
    )

    # Now start Simulation Engine
    sim_engine = PolicySimulationEngine(policy_repo=pca, ref_data_repo=getattr(pca, 'reference_data_repo', None))
    logger.info('Initialized Policy Analysis Repository and Simulation Engine.')

    # --- Start MCP Server ---
    if args.transport == 'stdio':
        logger.info(
            'Starting MCP server in stdio mode - if you get errors, please ensure you set environment variable MCP_STDIO_MODE=1'
        )
        mcp.run(transport='stdio', show_banner=False, log_level='error')
        # mcp.run(transport='stdio', show_banner=False)
    else:
        mcp.run(transport='streamable-http', port=args.port, host=args.host, log_level='info', show_banner=False)


if __name__ == '__main__':
    main()
