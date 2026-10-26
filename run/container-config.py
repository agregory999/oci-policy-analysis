"""Validate and render only application runtime settings, never operator credentials."""

import json
import os
import sys

OAUTH = {
    'MCP_OAUTH_ENABLED',
    'MCP_OAUTH_ISSUER',
    'MCP_OAUTH_JWKS_URI',
    'MCP_OAUTH_AUDIENCE',
    'MCP_OAUTH_REQUIRED_SCOPES',
    'MCP_OAUTH_RESOURCE_SERVER_URL',
    'MCP_OAUTH_AUTHORIZATION_SERVER_URL',
    'MCP_OAUTH_UPDATE_SCOPE',
    'MCP_OAUTH_AUTHORIZATION_SCOPES',
    'MCP_OAUTH_ALGORITHM',
    'MCP_OAUTH_AUTHORIZATION_SERVER_METADATA_ISSUER',
    'MCP_OAUTH_AUTHORIZATION_ENDPOINT',
    'MCP_OAUTH_TOKEN_ENDPOINT',
}


def boolean(name, default):
    raw = os.environ.get(name, default).lower()
    if raw not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}:
        raise ValueError(f'{name} must be a boolean')
    return 'true' if raw in {'true', '1', 'yes', 'on'} else 'false'


def containers(kind):
    depth = os.environ.get('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH', '1')
    if not depth.isdigit() or not 1 <= int(depth) <= 6:
        raise ValueError('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH must be 1 through 6')
    oauth = {}
    if kind != 'web' and boolean('MCP_OAUTH_ENABLED', 'false') == 'true':
        oauth = {key: os.environ[key] for key in OAUTH if os.environ.get(key)}
    if oauth.get('MCP_OAUTH_ENABLED', 'false').lower() in {'true', '1', 'yes', 'on'}:
        for key in (
            'MCP_OAUTH_ISSUER',
            'MCP_OAUTH_JWKS_URI',
            'MCP_OAUTH_AUDIENCE',
            'MCP_OAUTH_REQUIRED_SCOPES',
            'MCP_OAUTH_RESOURCE_SERVER_URL',
            'MCP_OAUTH_AUTHORIZATION_SERVER_URL',
        ):
            if not oauth.get(key):
                raise ValueError(f'Missing {key} with OAuth enabled')
    level = os.environ.get('MCP_LOG_LEVEL', 'INFO').upper()
    if kind != 'web' and level not in {'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'}:
        raise ValueError('Invalid MCP_LOG_LEVEL')
    result = []
    for mode in ('web', 'mcp') if kind == 'combined' else (kind,):
        port = int(os.environ.get(f'{mode.upper()}_PORT', '8000' if mode == 'web' else '8765'))
        if not 1 <= port <= 65535:
            raise ValueError(f'{mode.upper()}_PORT must be 1 through 65535')
        env = {'OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH': depth}
        if mode == 'web':
            env.update(
                WEB_RESOURCE_PRINCIPAL_ONLY=os.environ.get('WEB_RESOURCE_PRINCIPAL_ONLY', 'true'),
                WEB_HOST='0.0.0.0',
                WEB_PORT=str(port),
            )
        else:
            env.update(
                MCP_AUTH_MODE='resource_principal',
                MCP_TRANSPORT='streamable-http',
                MCP_HOST='0.0.0.0',
                MCP_PORT=str(port),
                MCP_LOG_LEVEL=level,
            )
            # Only explicitly selected optional MCP settings enter its container.
            for name in ('MCP_RECURSIVE', 'MCP_SAVE_CACHE_AFTER_LOAD'):
                if os.environ.get(name):
                    env[name] = boolean(name, 'false')
            env.update(oauth)
        result.append(
            {
                'displayName': f'oci-policy-analysis-{mode}',
                'imageUrl': '/'.join(
                    os.environ[key] for key in ('OCI_REGISTRY_HOST', 'OCI_NAMESPACE', 'OCI_REPOSITORY')
                )
                + ':'
                + os.environ[f'IMAGE_TAG_{mode.upper()}'],
                'isResourcePrincipalDisabled': False,
                'environmentVariables': env,
                'healthChecks': [
                    {
                        'healthCheckType': 'HTTP',
                        'name': f'{mode}-health',
                        'path': '/health',
                        'port': port,
                        'initialDelayInSeconds': 120,
                        'intervalInSeconds': 30,
                        'timeoutInSeconds': 5,
                        'failureThreshold': 6,
                        'successThreshold': 1,
                        'failureAction': 'KILL',
                    }
                ],
            }
        )
    if len(result) == 2 and result[0]['healthChecks'][0]['port'] == result[1]['healthChecks'][0]['port']:
        raise ValueError('WEB_PORT and MCP_PORT must differ')
    return result


if __name__ == '__main__':
    try:
        json.dump(containers(sys.argv[1]), sys.stdout)
    except (ValueError, KeyError) as exc:
        print(f'Invalid deployment config: {exc}', file=sys.stderr)
        sys.exit(2)
