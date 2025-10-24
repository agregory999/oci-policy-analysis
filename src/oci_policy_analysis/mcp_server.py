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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

import argparse
import json
import sys
import threading

import uvicorn
import uvicorn.config
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.responses import JSONResponse

from oci_policy_analysis.logger import get_logger
from oci_policy_analysis.logic.caching import CacheManager
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.models import (
    DefineStatement,
    DynamicGroup,
    DynamicGroupSearch,
    Group,
    PolicySearch,
    PolicyStatement,
    User,
)

# Clone and modify Uvicorn's default LOGGING_CONFIG safely
_LOGGING_CONFIG = uvicorn.config.LOGGING_CONFIG.copy()
_LOGGING_CONFIG['formatters']['default'] = {
    'format': '%(levelprefix)s %(message)s',
    'use_colors': False,
}

# Patch back the modified config
uvicorn.config.LOGGING_CONFIG = _LOGGING_CONFIG

# Global logger for this module
logger = get_logger(component='mcp_server')
logger.info('MCP server module logger initialized.')


mcp = FastMCP(name='OCI Policy MCP')
pca: PolicyAnalysisRepository | None = None


# --- Resources and Tools (unchanged) ---
@mcp.custom_route('/health', methods=['GET'])
async def health_check(request):
    # Perform any necessary checks here (e.g., database connection, external service availability)
    return JSONResponse({'status': 'healthy'})


@mcp.resource('policies://regular-policy-statements', description='Return All regular policy statements in the tenancy')
def list_policy_statements() -> list[PolicyStatement]:
    """
    All policy statements in the tenancy.

    Use this resource when the user asks for:
    - A complete list of all policy statements.
    - Raw policy data for analysis or summarization.
    - Parsed policy data you can filter on yourself
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(
        f'Resource returning {len(pca.regular_statements)} regular and {len(pca.cross_tenancy_statements)} CT policy statements'
    )
    return pca.regular_statements


# Filter invalid policy statements
@mcp.resource(
    'policies://filter_invalid_policy_statements',
    description=(
        "Return all policy statements where the 'Valid' field is False. "
        'These represent invalid or unparsable policy statements. '
        'NO Filtering is supported using this tool; it simply returns all invalid statements. '
    ),
)
def filter_invalid_policy_statements() -> list[PolicyStatement]:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    results = [s for s in pca.regular_statements if not s.get('Valid', True)]
    logger.info(f'Resource returning {len(results)} invalid policy statements')
    return results


@mcp.resource(
    'policies://cross-tenancy-statements', description='Return All cross-tenancy policy statements in the tenancy'
)
def cross_tenancy_policy_statements() -> list[PolicyStatement]:
    """
    All cross-trenancy policy statements in the tenancy.

    Use this resource when the user asks for:
    - Cross tenancy policy statements.
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    return pca.cross_tenancy_statements


@mcp.resource(
    'policies://root-compartment-policy-statements',
    description='Return All regular policy statements in the root compartment of the tenancy',
)
def root_policy_statements() -> list[PolicyStatement]:
    """
    All regular policy statements in the root compartment of the tenancy.

    Use this resource when the user asks for:
    - Root only tenancy policy statements.
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info('Tool Policy Filter for ROOT only')
    results = pca.filter_policy_statements({'policy_compartment': ['ROOTONLY']})
    logger.info(f'Filter for root returning {len(results)} policy statements to client')
    return results


@mcp.resource('groups://all', description='Return All groups in the tenancy')
def list_groups() -> str:
    """
    All groups in the tenancy.

    Use this resource when the user asks for:
    - All named groups in the tenancy.
    - Domain and group information
    - Raw group information for cross-referencing with policies
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Groups returning {len(pca.groups)} groups')
        return json.dumps(pca.groups)
    except Exception as e:
        raise ToolError(f'Failed to fetch groups: {e}') from e


@mcp.resource('dynamic-groups://all', description='Return All dynamic groups in the tenancy')
def list_dynamic_groups() -> list[DynamicGroup]:
    """
    All dynamic groups in the tenancy.

    Use this resource when the user asks for:
    - All named dynamic groups in the tenancy.
    - Domain and dynamic group information
    - Raw dynamic group information for cross-referencing with policies
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Dynamic Groups returning {len(pca.dynamic_groups)} groups')
        return pca.dynamic_groups
    except Exception as e:
        raise ToolError(f'Failed to fetch dynamic groups: {e}') from e


@mcp.resource('users://all', description='Return All users in the tenancy')
def list_users() -> list[User]:
    """
    All users in the tenancy.

    Use this resource when the user asks for:
    - All named users in the tenancy.
    - Domain and user information
    - Raw user information for cross-referencing with groups
    """
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Users returning {len(pca.users)} users')
        return pca.users
    except Exception as e:
        raise ToolError(f'Failed to fetch users: {e}') from e


# --- Tools ---


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
def filter_policy_statements(filters: PolicySearch) -> list[PolicyStatement]:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(f'Tool Policy Filter with JSON filters: {filters}')
    raw_results = pca.filter_policy_statements(filters)
    for st in raw_results:
        logger.debug(f'Raw Result: {st} \n\n')
    logger.info(f'Filter returning {len(raw_results)} policy statements to client')
    return raw_results


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


@mcp.tool(
    name='search_dynamic_groups',
    description=(
        'Return all dynamic groups that match the specified criteria. '
        "Input may include the dynamic group's domain (string or null for Default) and name (string). "
        "Returns a list of dynamic group dictionaries with keys 'dynamic_group_name', 'domain_name', and 'matching_rule'. "
        'Pass in no filter criteria to return all dynamic groups. Any provided criteria will be combined with AND logic. '
        'For policy filtering, use the main filter_policy_statements tool instead.'
    ),
)
def search_dynamic_groups(filters: DynamicGroupSearch) -> list[DynamicGroup]:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Searching dynamic groups with filters {filters}')
        results = pca.filter_dynamic_groups(filters)
        logger.debug(f'Dynamic Groups: {json.dumps(results, indent=4)}')

        logger.info(f'Returning {len(results)} dynamic groups matching filters')
        return results
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
def filter_cross_tenancy_policies_by_alias(alias: str) -> list[PolicyStatement]:
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


# ============================================================
# EMBEDDED SERVER CONTROL (for Tkinter integration)
# ============================================================

server_thread: threading.Thread | None = None
server_instance: uvicorn.Server | None = None
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


def build_arg_parser():
    parser = argparse.ArgumentParser()
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument('--profile')
    auth.add_argument('--instance-principal', action='store_true')
    auth.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    auth.add_argument('--session-token', help='OCI session token for instance principal auth', default=None)
    parser.add_argument(
        '--recursive', action='store_true', default=True, help='Recursively load all compartments (default: True)'
    )
    parser.add_argument('--transport', default='stdio', choices=['stdio', 'streamable-http'])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    return parser


def main():
    args = build_arg_parser().parse_args()
    recursive = args.recursive

    logger.info(
        f'Loading MCP Server using Profile={args.profile or "DEFAULT"}, '
        f'InstancePrincipal={args.instance_principal}, '
        f'Recursive={recursive}, Transport={args.transport}'
    )

    # --- Embedded Initialization ---
    global pca
    pca = PolicyAnalysisRepository()

    ok_pca = pca.initialize_client(
        use_instance_principal=args.instance_principal,
        session_token=args.session_token or None,
        recursive=recursive,
        profile=(args.profile or 'DEFAULT'),
    )

    if not ok_pca:
        logger.error('Failed initializing clients')
        sys.exit(2)

    # Create Cache Manager
    cache_manager = CacheManager(policy_analysis=pca)
    try:
        if args.use_cache:
            if not cache_manager.load_combined_cache(named_cache=args.use_cache):
                logger.warning(f'Failed to load cache: {args.use_cache}')
                sys.exit(2)
        else:
            # Load live data from OCI
            logger.info('Loading live data from OCI')
            pca.load_policies_and_compartments()
            pca.load_complete_identity_domains()
    except Exception as e:
        logger.warning(f'Policy and Identity domains load failed: {e}')
        exit(2)

    logger.info(
        f'Tenancy loaded. Policies: {len(pca.regular_statements)} regular, '
        f'{len(pca.cross_tenancy_statements)} cross-tenancy; '
        f'Groups: {len(pca.groups)}; Users: {len(pca.users)}; '
        f'Dynamic Groups: {len(pca.dynamic_groups)}'
    )

    # --- Start MCP Server ---
    if args.transport == 'stdio':
        mcp.run(transport='stdio')
    else:
        mcp.run(transport='streamable-http', port=args.port, host=args.host)


# # --- Inspector/Claude env bootstrap ---
# if 'OCI_PROFILE' in os.environ or 'OCI_INSTANCE_PRINCIPAL' in os.environ:
#     profile = os.getenv('OCI_PROFILE')
#     use_ip = bool(os.getenv('OCI_INSTANCE_PRINCIPAL', ''))
#     session = os.getenv('OCI_SESSION', '')
#     recursive = not bool(os.getenv('OCI_NO_RECURSIVE', ''))
#     logger.info(f'Loading MCP Dev from OCI Profile {profile} with IP: {use_ip} and Recursion: {recursive}')

#     initialize_and_load(use_ip, profile, session, recursive)

if __name__ == '__main__':
    main()
