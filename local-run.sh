#!/usr/bin/env bash
set -e

echo "==============================================="
echo "              LOCAL RUN APPLICATION            "
echo "==============================================="

# Check for venv
if [ ! -d ".venv" ]; then
    echo "❌ No virtual environment found (.venv)."
    echo "   Please run local_build.sh or local_build_with_pyinstaller.sh first."
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

echo "🚀 Running OCI Policy Analysis..."
echo "-----------------------------------------------"

# Run via module form (recommended for portability)
python -m oci_policy_analysis.main "$@"

echo "-----------------------------------------------"
echo "🏁 Application finished."
