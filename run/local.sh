#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mode="${1:-${LOCAL_MODE:-ui}}"
if [[ $# -gt 0 ]]; then shift; fi
[[ -x "$root_dir/.venv/bin/python" ]] || { echo "Run run/build.sh first." >&2; exit 2; }
# Operator deployment profile must never select the local SDK identity.
export OCI_PROFILE="${LOCAL_OCI_PROFILE:-DEFAULT}"
case "${mode}" in
  ui|desktop) exec .venv/bin/oci-policy-analysis-ui "$@" ;;
  legacy-ui|legacy-desktop) exec .venv/bin/oci-policy-analysis-legacy-ui "$@" ;;
  cli) exec .venv/bin/oci-policy-analysis-cli "$@" ;;
  web) exec .venv/bin/oci-policy-analysis-web --host "${LOCAL_HOST:-127.0.0.1}" --port "${LOCAL_WEB_PORT:-8000}" "$@" ;;
  mcp) exec .venv/bin/oci-policy-analysis-mcp --transport "${LOCAL_MCP_TRANSPORT:-stdio}" --host "${LOCAL_HOST:-127.0.0.1}" --port "${LOCAL_MCP_PORT:-8765}" "$@" ;;
  *) echo "Usage: run/local.sh [ui|legacy-ui|cli|web|mcp] [arguments...]" >&2; exit 2 ;;
esac
