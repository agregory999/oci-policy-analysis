from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import oci_policy_analysis.mcp_server as mcp_server
import pytest
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair


def test_oauth_scope_parser_accepts_spaces_and_commas() -> None:
    assert mcp_server._split_scopes('scope.one, scope.two scope.three') == [
        'scope.one',
        'scope.two',
        'scope.three',
    ]


def test_oauth_disabled_returns_no_provider(monkeypatch) -> None:
    monkeypatch.delenv('MCP_OAUTH_ENABLED', raising=False)

    assert mcp_server._build_oauth_auth_provider_from_env() is None


def test_oauth_enabled_missing_env_fails_with_guidance(monkeypatch) -> None:
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    for var_name in mcp_server.MCP_OAUTH_REQUIRED_VARS:
        monkeypatch.delenv(var_name, raising=False)
    monkeypatch.delenv('MCP_OAUTH_REQUIRED_SCOPES', raising=False)

    with pytest.raises(ValueError) as exc_info:
        mcp_server._build_oauth_auth_provider_from_env()

    message = str(exc_info.value)
    assert 'Missing required OAuth environment variables' in message
    assert 'Required environment variables:' in message
    assert 'Optional environment variables:' in message
    assert 'MCP_OAUTH_REQUIRED_SCOPES' in message


def test_oauth_enabled_builds_remote_auth_provider(monkeypatch) -> None:
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    monkeypatch.setenv('MCP_OAUTH_ISSUER', 'https://idcs-example.identity.oraclecloud.com/')
    monkeypatch.setenv('MCP_OAUTH_JWKS_URI', 'https://idcs-example.identity.oraclecloud.com/admin/v1/SigningCert/jwk')
    monkeypatch.setenv('MCP_OAUTH_AUDIENCE', 'oci-policy-analysis-mcp')
    monkeypatch.setenv('MCP_OAUTH_REQUIRED_SCOPES', 'oci-policy-analysis-mcp.invoke,oci-policy-analysis-mcp.reload')
    monkeypatch.setenv('MCP_OAUTH_RESOURCE_SERVER_URL', 'https://mcp.example.com/mcp')
    monkeypatch.setenv('MCP_OAUTH_AUTHORIZATION_SERVER_URL', 'https://idcs-example.identity.oraclecloud.com/')

    provider = mcp_server._build_oauth_auth_provider_from_env()

    assert provider is not None
    assert provider.required_scopes == ['oci-policy-analysis-mcp.invoke', 'oci-policy-analysis-mcp.reload']
    assert provider.resource_name == 'OCI Policy Analysis MCP'


def test_oauth_metadata_shim_advertises_local_issuer_and_oci_endpoints(monkeypatch) -> None:
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    monkeypatch.setenv('MCP_OAUTH_ISSUER', 'https://identity.oraclecloud.com/')
    monkeypatch.setenv('MCP_OAUTH_JWKS_URI', 'https://idcs-example.identity.oraclecloud.com/admin/v1/SigningCert/jwk')
    monkeypatch.setenv('MCP_OAUTH_AUDIENCE', 'oci-policy-analysis-mcp')
    monkeypatch.setenv('MCP_OAUTH_REQUIRED_SCOPES', 'read')
    monkeypatch.setenv('MCP_OAUTH_AUTHORIZATION_SCOPES', 'oci-policy-analysis-mcpread')
    monkeypatch.setenv('MCP_OAUTH_RESOURCE_SERVER_URL', 'https://mcp.example.com')
    monkeypatch.setenv('MCP_OAUTH_AUTHORIZATION_SERVER_URL', 'https://idcs-example.identity.oraclecloud.com/')
    monkeypatch.setenv('MCP_OAUTH_AUTHORIZATION_SERVER_METADATA_ISSUER', 'https://mcp.example.com/oauth/oci-idcs')
    monkeypatch.setenv(
        'MCP_OAUTH_AUTHORIZATION_ENDPOINT', 'https://idcs-example.identity.oraclecloud.com/oauth2/v1/authorize'
    )
    monkeypatch.setenv('MCP_OAUTH_TOKEN_ENDPOINT', 'https://idcs-example.identity.oraclecloud.com/oauth2/v1/token')

    provider = mcp_server._build_oauth_auth_provider_from_env()

    assert provider is not None
    assert provider.authorization_servers == ['https://mcp.example.com/oauth/oci-idcs']
    assert provider.authorization_server_metadata == (
        'https://mcp.example.com/oauth/oci-idcs',
        {
            'issuer': 'https://mcp.example.com/oauth/oci-idcs',
            'authorization_endpoint': 'https://idcs-example.identity.oraclecloud.com/oauth2/v1/authorize',
            'token_endpoint': 'https://idcs-example.identity.oraclecloud.com/oauth2/v1/token',
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code'],
            'token_endpoint_auth_methods_supported': ['none'],
            'code_challenge_methods_supported': ['S256'],
            'scopes_supported': ['oci-policy-analysis-mcpread'],
        },
    )
    assert mcp_server._oauth_authorization_server_metadata_paths('https://mcp.example.com/oauth/oci-idcs') == (
        '/.well-known/oauth-authorization-server/oauth/oci-idcs',
        '/oauth/oci-idcs/.well-known/oauth-authorization-server',
    )


def test_oauth_enabled_requires_required_scopes(monkeypatch) -> None:
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    monkeypatch.setenv('MCP_OAUTH_ISSUER', 'https://idcs-example.identity.oraclecloud.com/')
    monkeypatch.setenv('MCP_OAUTH_JWKS_URI', 'https://idcs-example.identity.oraclecloud.com/admin/v1/SigningCert/jwk')
    monkeypatch.setenv('MCP_OAUTH_AUDIENCE', 'oci-policy-analysis-mcp')
    monkeypatch.delenv('MCP_OAUTH_REQUIRED_SCOPES', raising=False)
    monkeypatch.setenv('MCP_OAUTH_RESOURCE_SERVER_URL', 'https://mcp.example.com/mcp')
    monkeypatch.setenv('MCP_OAUTH_AUTHORIZATION_SERVER_URL', 'https://idcs-example.identity.oraclecloud.com/')

    with pytest.raises(ValueError, match='MCP_OAUTH_REQUIRED_SCOPES'):
        mcp_server._build_oauth_auth_provider_from_env()


def test_reload_scope_is_checked_only_when_oauth_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv('MCP_OAUTH_UPDATE_SCOPE', 'oci-policy-analysis-mcp.update')
    monkeypatch.delenv('MCP_OAUTH_ENABLED', raising=False)
    mcp_server._require_oauth_scope('oci-policy-analysis-mcp.update')

    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    monkeypatch.setattr(
        mcp_server,
        'get_access_token',
        lambda: SimpleNamespace(scopes=['oci-policy-analysis-mcp.read']),
    )
    with pytest.raises(mcp_server.ToolError, match='MCP OAuth scope required'):
        mcp_server._require_oauth_scope('oci-policy-analysis-mcp.update')

    monkeypatch.setattr(
        mcp_server,
        'get_access_token',
        lambda: SimpleNamespace(scopes=['oci-policy-analysis-mcp.read', 'oci-policy-analysis-mcp.update']),
    )
    mcp_server._require_oauth_scope('oci-policy-analysis-mcp.update')


def test_invoke_logging_records_oauth_identity_without_bearer_token(monkeypatch, caplog) -> None:
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'true')
    monkeypatch.setattr(
        mcp_server,
        'get_access_token',
        lambda: SimpleNamespace(
            client_id='client-123',
            scopes=['oci-policy-analysis-mcp.read'],
            claims={'user_displayname': 'Alice Example', 'ca_name': 'alice'},
        ),
    )

    with caplog.at_level(logging.WARNING, logger=mcp_server.logger.name):
        mcp_server._log_mcp_call_input('policy_search', {'filters': {'resource': 'object'}})

    assert (
        'MCP OAuth invoke policy_search client_id=client-123 user_displayname=Alice Example '
        'ca_name=alice '
        'scopes=oci-policy-analysis-mcp.read' in caplog.text
    )
    assert 'Bearer' not in caplog.text


def test_jwt_verifier_accepts_valid_token_and_rejects_claim_mismatches() -> None:
    key_pair = RSAKeyPair.generate()
    issuer = 'https://idcs-example.identity.oraclecloud.com/'
    audience = 'oci-policy-analysis-mcp'
    scope = 'oci-policy-analysis-mcp.invoke'

    valid_token = key_pair.create_token(
        subject='alice',
        issuer=issuer,
        audience=audience,
        scopes=[scope],
    )
    verifier = JWTVerifier(
        public_key=key_pair.public_key,
        issuer=issuer,
        audience=audience,
        required_scopes=[scope],
        base_url='https://mcp.example.com/mcp',
    )

    access_token = asyncio.run(verifier.verify_token(valid_token))
    assert access_token is not None
    assert access_token.client_id == 'alice'
    assert scope in access_token.scopes

    wrong_audience = key_pair.create_token(
        subject='alice',
        issuer=issuer,
        audience='other-audience',
        scopes=[scope],
    )
    missing_scope = key_pair.create_token(
        subject='alice',
        issuer=issuer,
        audience=audience,
        scopes=['other.scope'],
    )
    missing_one_of_multiple_required_scopes = key_pair.create_token(
        subject='alice',
        issuer=issuer,
        audience=audience,
        scopes=[scope],
    )
    expired = key_pair.create_token(
        subject='alice',
        issuer=issuer,
        audience=audience,
        scopes=[scope],
        expires_in_seconds=-1,
    )

    assert asyncio.run(verifier.verify_token(wrong_audience)) is None
    assert asyncio.run(verifier.verify_token(missing_scope)) is None
    assert asyncio.run(verifier.verify_token(expired)) is None

    verifier_with_two_required_scopes = JWTVerifier(
        public_key=key_pair.public_key,
        issuer=issuer,
        audience=audience,
        required_scopes=[scope, 'oci-policy-analysis-mcp.reload'],
        base_url='https://mcp.example.com/mcp',
    )
    assert asyncio.run(verifier_with_two_required_scopes.verify_token(missing_one_of_multiple_required_scopes)) is None
