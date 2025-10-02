#!/usr/bin/env python3
import argparse
import json
import os
import sys

# from mcp.server.fastmcp import FastMCP
from fastmcp import FastMCP
from starlette.responses import JSONResponse

from logic.data_repo import IdentityDomainsAnalysis, PolicyCompartmentAnalysis
from logic.logger import get_logger

logger = get_logger()

mcp = FastMCP(name='OCI Policy MCP')
pca: PolicyCompartmentAnalysis | None = None
ida: IdentityDomainsAnalysis | None = None


# --- Resources and Tools (unchanged) ---
@mcp.custom_route('/health', methods=['GET'])
async def health_check(request):
    # Perform any necessary checks here (e.g., database connection, external service availability)
    return JSONResponse({'status': 'healthy'})


@mcp.resource('policies://all')
def list_policies() -> str:
    if not pca:
        return json.dumps({'error': 'repo not initialized'})
    return json.dumps(
        {
            'regular_statements': getattr(pca, 'regular_statements', []),
            'cross_tenancy_statements': getattr(pca, 'cross_tenancy_statements', []),
        }
    )


@mcp.tool
def find_policies_by_group(group_name: str) -> str:
    if not pca:
        return json.dumps({'error': 'repo not initialized'})
    return json.dumps(pca.filter_policy_statements_by_groups([group_name]))


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
    pca.load_policies_and_compartments()
    ida.load_domains_groups_users()
    try:
        ida.load_all_dynamic_groups()
    except Exception as e:
        logger.warning(f'Dynamic groups load failed: {e}')
    logger.info('Tenancy loaded.')


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
    if args.transport == 'stdio':
        mcp.run(transport='stdio')
    else:
        mcp.run(transport='streamable-http', host=args.host, port=args.port)


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
