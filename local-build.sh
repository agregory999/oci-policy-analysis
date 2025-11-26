#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
    echo "🐍 Creating fresh uv venv..."
    uv venv --python=3.12
else
    echo "♻️ Reusing existing .venv"
fi

source .venv/bin/activate
# source mypythonvenv/bin/activate

echo "🔄 Ensuring pip + tools are installed..."
uv pip install pip setuptools wheel build pyinstaller ruff

echo "🔒 Locking dependencies..."
uv lock

echo "📦 Exporting dependency list (no dev dependencies)..."
uv export --no-dev > frozen.txt

echo "🧹 Removing local project entry..."
grep -v '^-e .' frozen.txt > deps.txt
grep -v -- "--hash=" deps.txt > deps2.txt
mv deps2.txt frozen.txt

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
