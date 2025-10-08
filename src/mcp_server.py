#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Literal, TypedDict

# from mcp.server.transport.stdio import stdio_server
# from mcp.server.transport.http import http_server
# from mcp.server.fastmcp import FastMCP
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from logic.data_repo import (
    DynamicGroup,
    Group,
    IdentityDomainsAnalysis,
    PolicyCompartmentAnalysis,
    PolicyFilters,
    PolicyStatement,
    User,
)
from logic.logger import get_logger

logger = get_logger(use_console=True)

mcp = FastMCP(name='OCI Policy MCP')
pca: PolicyCompartmentAnalysis | None = None
ida: IdentityDomainsAnalysis | None = None


# Combined filter input for policies - example
class CombinedFilterInput(TypedDict):
    groups: list[Group]
    verbs: list[Literal['inspect', 'read', 'use', 'manage']]


# --- Resources and Tools (unchanged) ---
@mcp.custom_route('/health', methods=['GET'])
async def health_check(request):
    # Perform any necessary checks here (e.g., database connection, external service availability)
    return JSONResponse({'status': 'healthy'})


@mcp.resource('policies://regular', description='Return All regular policy statements in the tenancy')
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


@mcp.resource('policies://cross-tenancy', description='Return All cross-tenancy policy statements in the tenancy')
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
    'policies://compartment/root',
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
    results = pca.filter_policy_statements_json({'policy_compartment': ['ROOTONLY']})
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
    if not ida:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Groups returning {len(ida.groups)} groups')
        return json.dumps(ida.groups)
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
    if not ida:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Dynamic Groups returning {len(ida.dynamic_groups)} groups')
        return ida.dynamic_groups
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
    if not ida:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'Resource Users returning {len(ida.users)} users')
        return ida.users
    except Exception as e:
        raise ToolError(f'Failed to fetch users: {e}') from e


# --- Tools ---


# Policy filter tool
@mcp.tool(
    name='filter_policy_statements_json',
    description=(
        'Filter OCI IAM policy statements using a JSON filter object. '
        'Each field is optional; OR within each field, AND across fields. '
        'Special cases: '
        '- verb must be one of inspect/read/use/manage '
        '- policy_compartment supports ROOTONLY to bring back policy statements only in the root compartment '
        '- policy_text matches anywhere in the statement text.'
    ),
)
def filter_policy_statements_json(filters: PolicyFilters) -> list[PolicyStatement]:
    if not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(f'Tool Policy Filter with JSON filters: {filters}')
    results = pca.filter_policy_statements_json(filters)
    logger.info(f'Filter returning {len(results)} policy statements to client')
    return results


# Filter by dynamic groups
@mcp.tool(
    name='filter_policy_statements_by_dynamic_groups',
    description=(
        'Filter OCI IAM policy statements by dynamic group membership. '
        "Input is a list of objects, each with keys 'domain' (string or null) "
        "and 'name' (string). Only applies to statements where Subject Type is 'dynamic-group'. "
        'Matches occur if any provided (domain, name) matches any subject in the statement.'
    ),
)
def filter_policy_statements_by_dynamic_groups(dynamic_groups: list[DynamicGroup]) -> list[PolicyStatement]:
    if not ida or not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(f'Tool Dynamic Group Filter with groups: {dynamic_groups}')
    # print(f'Dynamic Groups: {dynamic_groups}', flush=True)
    results = pca.filter_policy_statements_by_dynamic_group_name(dynamic_groups)
    logger.info(f'Filter returning {len(results)} policy statements to client')
    return results


# Policy filter by groups tool
@mcp.tool(
    name='filter_policy_statements_by_groups',
    description=(
        'Filter OCI IAM policy statements by group membership. '
        "Input is a list of objects with keys 'domain' (string or null) and 'name' (string). "
        "Only applies to statements where Subject Type is 'group'. "
        'Returns matching policy statements with full policy fields.'
        'Domain can be null for Default'
        'Name must be an exact match for an existing group name in the tenancy.'
    ),
)
def filter_policy_statements_by_groups(groups: list[Group]) -> list[PolicyStatement]:
    if not ida or not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    logger.info(f'Tool Dynamic Group Filter with groups: {groups}')
    # print(f'Dynamic Groups: {dynamic_groups}', flush=True)
    results = pca.filter_policy_statements_by_groups(groups)
    logger.info(f'Filter returning {len(results)} policy statements to client')
    return results


# Filter by groups and verbs (combined)
@mcp.tool(
    name='filter_policy_statements_by_group_and_verb',
    description=(
        "Filter OCI IAM policy statements where Subject Type is 'group' and Verb matches. "
        'Input includes a list of groups (domain/name) and a list of verbs.'
    ),
)
def filter_policy_statements_by_group_and_verb(params: CombinedFilterInput) -> list[PolicyStatement]:
    if not ida or not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    by_groups = pca.filter_policy_statements_by_groups(params['groups'])
    return [s for s in by_groups if s.get('Verb', '').lower() in [v.lower() for v in params['verbs']]]


# Filter invalid policy statements
@mcp.tool(
    name='filter_invalid_policy_statements',
    description=(
        "Return all policy statements where the 'Valid' field is False. "
        'These represent invalid or unparsable policy statements.'
    ),
)
def filter_invalid_policy_statements() -> list[PolicyStatement]:
    if not ida or not pca:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    return [s for s in pca.regular_statements if not s.get('Valid', True)]


@mcp.tool(
    name='get_users_for_group',
    description=(
        'Return all users that belong to a specified OCI IAM group. '
        "Input must include the group's domain (string or null for Default) and name (string). "
        "Returns a list of user dictionaries with keys 'user_name', 'user_id', and 'domain_name'."
    ),
)
def get_users_for_group(group: Group) -> list[User]:
    """
    Get all users for a specific group.

    Args:
        group (Group): A dictionary containing:
            - 'domain' (str | None): The group's domain, or None for Default.
            - 'name' (str): The group name.

    Returns:
        list[User]: List of user entries who are members of that group.
    """
    if not ida:
        raise ToolError('Repository not initialized. Run with a profile or instance principal.')
    try:
        logger.info(f'MCP Tool: Getting users for group {group}')
        results = ida.get_users_for_group(group)
        logger.info(f'Returning {len(results)} users for group {group}')
        return results
    except Exception as e:
        raise ToolError(f'Failed to retrieve users for group {group}: {e}') from e


# --- Initialization ---
def initialize_and_load(use_instance_principal, profile, session, recursive):
    global pca, ida
    pca = PolicyCompartmentAnalysis()
    ida = IdentityDomainsAnalysis()
    ok_pca = pca.initialize_client(
        use_instance_principal=use_instance_principal,
        session=session or '',
        recursive=recursive,
        profile=(profile or 'DEFAULT'),
    )
    ok_ida = ida.initialize_client(
        use_instance_principal=use_instance_principal,
        profile=(profile or 'DEFAULT'),
    )
    if not ok_pca or not ok_ida:
        logger.error('Failed initializing clients')
        sys.exit(2)
    try:
        pca.load_policies_and_compartments()
        ida.load_complete_identity_domains()
    except Exception as e:
        logger.warning(f'Policy and Identity domains load failed: {e}')
    logger.info(
        f'Tenancy loaded. Policies: {len(pca.regular_statements)} regular, {len(pca.cross_tenancy_statements)} cross-tenancy; Groups: {len(ida.groups)}; Users: {len(ida.users)}; Dynamic Groups: {len(ida.dynamic_groups)}'
    )


def build_arg_parser():
    parser = argparse.ArgumentParser()
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument('--profile')
    auth.add_argument('--instance-principal', action='store_true')
    parser.add_argument('--session', default='')
    parser.add_argument('--no-recursive', action='store_true')
    parser.add_argument('--transport', default='stdio', choices=['stdio', 'streamable-http'])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    return parser


def main():
    args = build_arg_parser().parse_args()
    recursive = not args.no_recursive
    logger.info(
        f'Loading MCP as Server from OCI Profile {args.profile} with IP: {args.instance_principal} and Recursion: {recursive} and Transport: {args.transport}'
    )
    initialize_and_load(args.instance_principal, args.profile, args.session, recursive)

    # mcp.run()
    # asyncio.run(http_server(mcp, port=args.port))
    if args.transport == 'stdio':
        mcp.run(transport='stdio')
    else:
        mcp.run(transport='streamable-http', port=args.port)


# --- Inspector/Claude env bootstrap ---
if 'OCI_PROFILE' in os.environ or 'OCI_INSTANCE_PRINCIPAL' in os.environ:
    profile = os.getenv('OCI_PROFILE')
    use_ip = bool(os.getenv('OCI_INSTANCE_PRINCIPAL', ''))
    session = os.getenv('OCI_SESSION', '')
    recursive = not bool(os.getenv('OCI_NO_RECURSIVE', ''))
    logger.info(f'Loading MCP Dev from OCI Profile {profile} with IP: {use_ip} and Recursion: {recursive}')

    initialize_and_load(use_ip, profile, session, recursive)

if __name__ == '__main__':
    main()
