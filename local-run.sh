#!/usr/bin/env bash
set -e

MODE="desktop"
HOST="127.0.0.1"
PORT="8000"
RELOAD="false"
TRANSPORT="stdio"

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

echo "==============================================="
echo "              LOCAL RUN APPLICATION            "
echo "==============================================="

# Check for venv
if [ ! -d ".venv" ]; then
    echo "❌ No virtual environment found (.venv)."
    echo "   Please run local-build.sh or local-build-with-pyinstaller.sh first."
    exit 1
fi

echo "🐍 Activating virtual environment..."

# macOS/Linux activation
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
# Windows Git Bash activation
elif [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
else
    echo "❌ Could not find activation script in .venv."
    exit 1
fi

echo "🚀 Running OCI Policy Analysis mode: ${MODE}"
echo "-----------------------------------------------"

case "$MODE" in
    desktop)
        python -m oci_policy_analysis.main "$@"
        ;;
    web)
        WEB_ARGS=(--host "$HOST" --port "$PORT")
        if [[ "$RELOAD" == "true" ]]; then
            WEB_ARGS+=(--reload)
        fi
        oci-policy-analysis-web "${WEB_ARGS[@]}" "$@"
        ;;
    cli)
        oci-policy-analysis-cli "$@"
        ;;
    mcp)
        if [[ "$TRANSPORT" == "streamable-http" ]]; then
            oci-policy-analysis-mcp --transport streamable-http --host "$HOST" --port "$PORT" "$@"
        else
            oci-policy-analysis-mcp --transport stdio "$@"
        fi
        ;;
    *)
        echo "❌ Invalid mode: $MODE"
        echo "   Valid modes: desktop, web, cli, mcp"
        exit 1
        ;;
esac

echo "-----------------------------------------------"
echo "🏁 Application finished."
