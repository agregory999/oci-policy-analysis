#!/usr/bin/env bash
set -euo pipefail

AUTH_MODE="${MCP_AUTH_MODE:-instance_principal}"
TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
HOST="${MCP_HOST:-0.0.0.0}"
PORT="${MCP_PORT:-8765}"
LOG_LEVEL="${MCP_LOG_LEVEL:-INFO}"
RECURSIVE="${MCP_RECURSIVE:-true}"
SAVE_CACHE_AFTER_LOAD="${MCP_SAVE_CACHE_AFTER_LOAD:-false}"
COMPARTMENT_DOMAIN_SEARCH_DEPTH="${MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH:-1}"

OCI_PROFILE_NAME="${OCI_PROFILE:-}"
MCP_CACHE_NAME="${MCP_USE_CACHE:-}"
OCI_SESSION_TOKEN_VALUE="${OCI_SESSION_TOKEN:-}"

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

if [[ "${RECURSIVE,,}" == "true" ]]; then
  SERVER_ARGS+=("--recursive")
fi

if [[ "${SAVE_CACHE_AFTER_LOAD,,}" != "true" ]]; then
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

echo "Starting OCI Policy Analysis MCP server with auth=${AUTH_MODE}, transport=${TRANSPORT}, host=${HOST}, port=${PORT}, log_level=${LOG_LEVEL}" >&2
exec python -m oci_policy_analysis.mcp_server "${SERVER_ARGS[@]}"
