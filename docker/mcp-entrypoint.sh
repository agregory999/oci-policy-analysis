#!/usr/bin/env bash
set -euo pipefail

AUTH_MODE="${MCP_AUTH_MODE:-instance_principal}"
TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
HOST="${MCP_HOST:-0.0.0.0}"
PORT="${MCP_PORT:-8765}"
LOG_LEVEL="${MCP_LOG_LEVEL:-WARNING}"
RECURSIVE="${MCP_RECURSIVE:-true}"
SAVE_CACHE_AFTER_LOAD="${MCP_SAVE_CACHE_AFTER_LOAD:-false}"
COMPARTMENT_DOMAIN_SEARCH_DEPTH="${MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH:-1}"

OCI_PROFILE_NAME="${OCI_PROFILE:-}"
MCP_CACHE_NAME="${MCP_USE_CACHE:-}"
OCI_SESSION_TOKEN_VALUE="${OCI_SESSION_TOKEN:-}"
OAUTH_ENABLED="${MCP_OAUTH_ENABLED:-false}"

to_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

print_oauth_help() {
  cat >&2 <<'EOF'

OAuth for MCP is enabled, but required configuration is missing or invalid.

Required environment variables:
  export MCP_OAUTH_ENABLED="true"
  export MCP_OAUTH_ISSUER="https://idcs-<id>.identity.oraclecloud.com/"
  export MCP_OAUTH_JWKS_URI="https://idcs-<id>.identity.oraclecloud.com/admin/v1/SigningCert/jwk"
  export MCP_OAUTH_AUDIENCE="<resource-server-primary-audience>"
  export MCP_OAUTH_REQUIRED_SCOPES="read"
  export MCP_OAUTH_RESOURCE_SERVER_URL="https://<mcp-public-host>/mcp"
  export MCP_OAUTH_AUTHORIZATION_SERVER_URL="https://idcs-<id>.identity.oraclecloud.com/"

Optional environment variables:
  export MCP_OAUTH_UPDATE_SCOPE="update"
  export MCP_OAUTH_ALGORITHM="RS256"

Copy the required block, replace placeholder values from the OCI Identity Domain application, then rerun the MCP server.
EOF
}

SERVER_ARGS=(
  "--transport" "${TRANSPORT}"
  "--host" "${HOST}"
  "--port" "${PORT}"
  "--compartment-domain-search-depth" "${COMPARTMENT_DOMAIN_SEARCH_DEPTH}"
  "--log-level" "${LOG_LEVEL}"
)

if [[ ! "${COMPARTMENT_DOMAIN_SEARCH_DEPTH}" =~ ^[0-9]+$ ]] || (( COMPARTMENT_DOMAIN_SEARCH_DEPTH < 1 || COMPARTMENT_DOMAIN_SEARCH_DEPTH > 6 )); then
  echo "MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH must be an integer between 1 and 6." >&2
  exit 2
fi

if [[ "$(to_lower "${OAUTH_ENABLED}")" == "true" ]]; then
  OAUTH_REQUIRED_VARS=(
    "MCP_OAUTH_ISSUER"
    "MCP_OAUTH_JWKS_URI"
    "MCP_OAUTH_AUDIENCE"
    "MCP_OAUTH_REQUIRED_SCOPES"
    "MCP_OAUTH_RESOURCE_SERVER_URL"
    "MCP_OAUTH_AUTHORIZATION_SERVER_URL"
  )
  OAUTH_MISSING_VARS=()
  for var_name in "${OAUTH_REQUIRED_VARS[@]}"; do
    if [[ -z "${!var_name:-}" ]]; then
      OAUTH_MISSING_VARS+=("${var_name}")
    fi
  done
  if (( ${#OAUTH_MISSING_VARS[@]} > 0 )); then
    echo "ERROR: Missing required OAuth environment variables: ${OAUTH_MISSING_VARS[*]}" >&2
    print_oauth_help
    exit 2
  fi
fi

if [[ "$(to_lower "${RECURSIVE}")" == "true" ]]; then
  SERVER_ARGS+=("--recursive")
fi

if [[ "$(to_lower "${SAVE_CACHE_AFTER_LOAD}")" != "true" ]]; then
  SERVER_ARGS+=("--dont-save-cache-after-load")
fi

case "${AUTH_MODE}" in
  resource_principal)
    SERVER_ARGS+=("--resource-principal")
    ;;
  instance_principal)
    SERVER_ARGS+=("--instance-principal")
    ;;
  profile)
    if [[ -z "${OCI_PROFILE_NAME}" ]]; then
      echo "MCP_AUTH_MODE=profile requires OCI_PROFILE to be set." >&2
      exit 2
    fi
    SERVER_ARGS+=("--profile" "${OCI_PROFILE_NAME}")
    ;;
  cache)
    if [[ -z "${MCP_CACHE_NAME}" ]]; then
      echo "MCP_AUTH_MODE=cache requires MCP_USE_CACHE to be set." >&2
      exit 2
    fi
    SERVER_ARGS+=("--use-cache" "${MCP_CACHE_NAME}")
    ;;
  session_token)
    if [[ -z "${OCI_SESSION_TOKEN_VALUE}" ]]; then
      echo "MCP_AUTH_MODE=session_token requires OCI_SESSION_TOKEN to be set." >&2
      exit 2
    fi
    SERVER_ARGS+=("--session-token" "${OCI_SESSION_TOKEN_VALUE}")
    ;;
  *)
    echo "Unsupported MCP_AUTH_MODE: ${AUTH_MODE}" >&2
    echo "Supported values: resource_principal, instance_principal, profile, cache, session_token" >&2
    exit 2
    ;;
esac

echo "Starting OCI Policy Analysis MCP server with auth=${AUTH_MODE}, transport=${TRANSPORT}, host=${HOST}, port=${PORT}, log_level=${LOG_LEVEL}, oauth=${OAUTH_ENABLED}" >&2
exec python -m oci_policy_analysis.mcp_server "${SERVER_ARGS[@]}"
