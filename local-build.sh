#!/usr/bin/env bash
set -e

PYTHON_BIN=${PYTHON_BIN:-python3.12}
MODE=${MODE:-all}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        *)
            echo "❌ Unknown argument: $1"
            echo "Usage: ./local-build.sh [--mode desktop|web|cli|mcp|all]"
            exit 1
            ;;
    esac
done

if [ ! -d ".venv" ]; then
    echo "🐍 Creating fresh venv with ${PYTHON_BIN}..."
    "${PYTHON_BIN}" -m venv .venv
else
    echo "♻️ Reusing existing .venv"
fi

source .venv/bin/activate

echo "🔄 Ensuring pip + tools are installed..."
python -m pip install "pip==25.3"
python -m pip install setuptools wheel build pip-tools pyinstaller ruff

echo "🔒 Locking dependencies..."
python -m piptools compile --generate-hashes --output-file frozen.txt pyproject.toml

echo "📦 Exporting dependency list (no dev dependencies)..."
grep -v '^-e .' frozen.txt > deps.txt
grep -v -- "--hash=" deps.txt > frozen2.txt
mv frozen2.txt frozen.txt
rm deps.txt

echo "📥 Installing published dependency wheels..."
# Pillow and similar native packages publish CPython 3.12 wheels. Do not force
# source builds: that triggers an isolated build environment and requires local
# system libraries such as zlib.
pip install --only-binary=:all: -r frozen.txt

echo "📦 Building your own package..."
python -m build --no-isolation

case "$MODE" in
    desktop)
        EXTRAS=""
        ;;
    web)
        EXTRAS="[web]"
        ;;
    cli)
        EXTRAS=""
        ;;
    mcp)
        EXTRAS="[mcp]"
        ;;
    all)
        EXTRAS="[all]"
        ;;
    *)
        echo "❌ Invalid mode: $MODE"
        echo "   Valid modes: desktop, web, cli, mcp, all"
        exit 1
        ;;
esac

echo "🚀 Installing your package (editable mode) for mode: $MODE"
pip install -e ".${EXTRAS}"

echo "🎉 Local build complete!"
echo "   App    → dist/"
