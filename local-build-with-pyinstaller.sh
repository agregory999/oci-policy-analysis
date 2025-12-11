#!/usr/bin/env bash
set -e

PYTHON_BIN=${PYTHON_BIN:-python3}

echo "==============================================="
echo "     LOCAL BUILD + PYINSTALLER (SOURCE ONLY)   "
echo "==============================================="

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

echo "🔒 Locking dependencies with pip-compile..."
python -m piptools compile --generate-hashes --output-file frozen.txt pyproject.toml

echo "📦 Exporting dependencies (no dev)..."
grep -v '^-e .' frozen.txt > deps.txt
grep -v -- "--hash=" deps.txt > frozen2.txt
mv frozen2.txt frozen.txt
rm deps.txt

echo "🔨 Building wheels from source..."
mkdir -p wheels
pip wheel --no-binary=:all: -r frozen.txt -w wheels/

echo "📥 Installing only local source-built wheels..."
pip install --no-index --find-links=./wheels -r frozen.txt

echo "📦 Installing your project (editable mode)..."
pip install -e .

echo "📝 Determining version via importlib.metadata..."
VERSION=$(python - <<EOF
import importlib.metadata
print(importlib.metadata.version("oci_policy_analysis"))
EOF
)
echo "   → version = $VERSION"

echo "$VERSION" > src/oci_policy_analysis/version.txt

echo "==============================================="
echo "             RUNNING PYINSTALLER"
echo "==============================================="

OS=$(uname -s)

if [[ "$OS" == "Darwin" ]]; then
    echo "🍎 macOS detected — building .app bundle"

    PY_LIB=$(python3 -c "import sysconfig, glob, os; \
libdir=sysconfig.get_config_var('LIBDIR'); \
matches=glob.glob(os.path.join(libdir, 'libpython*.dylib')); \
print(matches[0] if matches else '')")

    echo "   Python dylib: $PY_LIB"

    pyinstaller \
      --name="OCI Policy Analysis" \
      --windowed \
      --clean --noconfirm --noconsole \
      --icon=icons/oci-policy-dg-viewer.icns \
      --collect-all=sys \
      --copy-metadata fastmcp \
      --add-data "src/oci_policy_analysis/version.txt:oci_policy_analysis" \
      --add-data "src/oci_policy_analysis/logic/permissions:oci_policy_analysis/logic/permissions" \
      --add-binary="$PY_LIB:Frameworks/Python" \
      src/oci_policy_analysis/main.py

    echo "🍎 Packaging .app → dist/oci-policy-analysis-macos-${VERSION}.app.tar.gz"
    cd dist
    tar -czf "oci-policy-analysis-macos-${VERSION}.app.tar.gz" "OCI Policy Analysis.app"
    cd ..

elif [[ "$OS" == "Linux" ]]; then
    echo "🐧 Linux detected — building onefile binary"

    PY_SO=$(python3 -c "import sysconfig, glob, os; \
libdir=sysconfig.get_config_var('LIBDIR'); \
matches=glob.glob(os.path.join(libdir, 'libpython*.so*')); \
print(matches[0] if matches else '')")

    echo "   Python .so: $PY_SO"

    pyinstaller \
      --name="oci-policy-analysis" \
      --onefile \
      --clean --noconfirm --noconsole \
      --icon=icons/oci-policy-dg-viewer.png \
      --collect-all=sys \
      --copy-metadata fastmcp \
      --add-data "src/oci_policy_analysis/version.txt:oci_policy_analysis" \
      --add-data "src/reference_data:reference_data" \
      --add-binary="$PY_SO:." \
      src/oci_policy_analysis/main.py

    echo "🐧 Packaging → dist/oci-policy-analysis-linux-${VERSION}.tar.gz"
    cd dist
    tar -czf "oci-policy-analysis-linux-${VERSION}.tar.gz" "oci-policy-analysis"
    cd ..

elif [[ "$OS" == MINGW* || "$OS" == MSYS* || "$OS" == CYGWIN* ]]; then
    echo "🪟 Windows detected — building onefile .exe"

    PY_DLL=$(python - <<EOF
import sysconfig, glob, os
b = sysconfig.get_config_var('BINDIR')
matches = glob.glob(os.path.join(b, 'python3*.dll'))
print(matches[0] if matches else '')
EOF
)

    echo "   Python DLL: $PY_DLL"

    pyinstaller \
      --name "OCI Policy Analysis" \
      --onefile \
      --clean --noconfirm --noconsole \
      --icon "icons/oci-policy-dg-viewer.ico" \
      --collect-all sys \
      --copy-metadata fastmcp \
      --add-data "src/oci_policy_analysis/version.txt;oci_policy_analysis" \
      --add-data "src/reference_data;reference_data" \
      --add-binary "$PY_DLL;." \
      src/oci_policy_analysis/main.py

    echo "🪟 Packaging → dist/oci-policy-analysis-windows-${VERSION}.zip"
    cd dist
    zip -r "oci-policy-analysis-windows-${VERSION}.zip" "OCI Policy Analysis.exe"
    cd ..

else
    echo "❌ Unsupported OS: $OS"
    exit 1
fi

echo "🎉 Build Complete!"
echo "   → dist/ contains fully platform-specific packaged binaries"
