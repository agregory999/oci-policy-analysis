#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

MODE="${LOCAL_MODE:-desktop}"
HOST="${LOCAL_HOST:-127.0.0.1}"
PORT=""
RELOAD="false"
TRANSPORT="${LOCAL_MCP_TRANSPORT:-stdio}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --reload)
            RELOAD="true"
            shift
            ;;
        --transport)
            TRANSPORT="$2"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "❌ Unknown argument: $1"
            echo "Usage: ./local-run.sh --mode desktop|web|cli|mcp [--host HOST] [--port PORT] [--reload] [--transport stdio|streamable-http] [-- <extra args>]"
            exit 1
            ;;
    esac
done

if [[ -z "$PORT" ]]; then
    if [[ "$MODE" == mcp ]]; then PORT="${LOCAL_MCP_PORT:-8765}"; else PORT="${LOCAL_WEB_PORT:-8000}"; fi
fi
export LOCAL_HOST="$HOST" LOCAL_WEB_PORT="$PORT" LOCAL_MCP_PORT="$PORT" LOCAL_MCP_TRANSPORT="$TRANSPORT"
if [[ "$RELOAD" == true && "$MODE" == web ]]; then set -- --reload "$@"; fi
exec "$root_dir/run/local.sh" "$MODE" "$@"
