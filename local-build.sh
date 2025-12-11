#!/usr/bin/env bash
set -e

PYTHON_BIN=${PYTHON_BIN:-python3}

if [ ! -d ".venv" ]; then
    echo "🐍 Creating fresh venv with ${PYTHON_BIN}..."
    "${PYTHON_BIN}" -m venv .venv
else
    echo "♻️ Reusing existing .venv"
fi

source .venv/bin/activate

echo "🔄 Ensuring pip + tools are installed..."
python -m pip install --upgrade pip
python -m pip install setuptools wheel build pip-tools pyinstaller ruff

echo "🔒 Locking dependencies..."
python -m piptools compile --generate-hashes --output-file frozen.txt pyproject.toml

echo "📦 Exporting dependency list (no dev dependencies)..."
grep -v '^-e .' frozen.txt > deps.txt
grep -v -- "--hash=" deps.txt > frozen2.txt
mv frozen2.txt frozen.txt
rm deps.txt

echo "🔨 Building wheels from source..."
mkdir -p wheels
pip wheel --no-binary=:all: -r frozen.txt -w wheels/

echo "📥 Installing dependencies from local wheels..."
pip install --no-index --find-links=./wheels -r frozen.txt

echo "📦 Building your own package..."
python -m build

echo "🚀 Installing your package (editable mode)..."
pip install -e .

echo "🎉 Local build complete!"
echo "   Wheels → wheels/"
echo "   App    → dist/"
