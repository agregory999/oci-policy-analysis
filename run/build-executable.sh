#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

PYTHON_BIN=${PYTHON_BIN:-python3}

if [[ "${1:-desktop}" == "qt" ]]; then
    shift
    uv sync --inexact --extra qt --extra qt-build --extra web --extra mcp --python "$PYTHON_BIN"
    uv pip check
    exec "$root_dir/.venv/bin/python" run-build/build_qt_executable.py "$@"
elif [[ "${1:-desktop}" != "desktop" ]]; then
    echo "Usage: run/build-executable.sh [desktop|qt] [Qt build options]" >&2
    exit 2
fi


echo "==============================================="
echo "     LOCAL BUILD + PYINSTALLER (SOURCE ONLY)   "
echo "==============================================="

command -v uv >/dev/null || { echo "Install uv first." >&2; exit 2; }
uv sync --inexact --extra web --extra mcp --python "$PYTHON_BIN"
uv pip install pyinstaller
source "$root_dir/.venv/bin/activate"
uv pip check
python scripts/check_desktop_imports.py
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
      --distpath dist/tk --workpath build/tk --specpath run-build \
      --name="oci-policy-analysis-tk" \
      --windowed \
      --clean --noconfirm --noconsole \
      --icon="$root_dir/icons/oci-policy-dg-viewer.icns" \
      --collect-all=sys \
      --copy-metadata fastmcp \
      --add-data "$root_dir/src/oci_policy_analysis/version.txt:oci_policy_analysis" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/permissions:oci_policy_analysis/application/core/resources/permissions" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/mcp_tools_list:oci_policy_analysis/application/core/resources/mcp_tools_list" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/parsers:oci_policy_analysis/application/core/resources/parsers" \
      --add-binary="$PY_LIB:Frameworks/Python" \
      "$root_dir/src/oci_policy_analysis/main.py"

    echo "🍎 Packaging .app → dist/tk/oci-policy-analysis-tk-macos-${VERSION}.app.tar.gz"
    cd dist/tk
    tar -czf "oci-policy-analysis-tk-macos-${VERSION}.app.tar.gz" "oci-policy-analysis-tk.app"
    cd ../..

elif [[ "$OS" == "Linux" ]]; then
    echo "🐧 Linux detected — building onefile binary"

    PY_SO=$(python3 -c "import sysconfig, glob, os; \
libdir=sysconfig.get_config_var('LIBDIR'); \
matches=glob.glob(os.path.join(libdir, 'libpython*.so*')); \
print(matches[0] if matches else '')")

    echo "   Python .so: $PY_SO"

    pyinstaller \
      --distpath dist/tk --workpath build/tk --specpath run-build \
      --name="oci-policy-analysis-tk" \
      --onefile \
      --clean --noconfirm --noconsole \
      --icon="$root_dir/icons/oci-policy-dg-viewer.png" \
      --collect-all=sys \
      --copy-metadata fastmcp \
      --add-data "$root_dir/src/oci_policy_analysis/version.txt:oci_policy_analysis" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/permissions:oci_policy_analysis/application/core/resources/permissions" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/mcp_tools_list:oci_policy_analysis/application/core/resources/mcp_tools_list" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/parsers:oci_policy_analysis/application/core/resources/parsers" \
      --add-binary="$PY_SO:." \
      "$root_dir/src/oci_policy_analysis/main.py"

    echo "🐧 Packaging → dist/tk/oci-policy-analysis-tk-linux-${VERSION}.tar.gz"
    cd dist/tk
    tar -czf "oci-policy-analysis-tk-linux-${VERSION}.tar.gz" "oci-policy-analysis-tk"
    cd ../..

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
      --distpath dist/tk --workpath build/tk --specpath run-build \
      --name "oci-policy-analysis-tk" \
      --onefile \
      --clean --noconfirm --noconsole \
      --icon "$root_dir/icons/oci-policy-dg-viewer.ico" \
      --collect-all sys \
      --copy-metadata fastmcp \
      --add-data "$root_dir/src/oci_policy_analysis/version.txt;oci_policy_analysis" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/permissions;oci_policy_analysis/application/core/resources/permissions" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/mcp_tools_list;oci_policy_analysis/application/core/resources/mcp_tools_list" \
      --add-data "$root_dir/src/oci_policy_analysis/application/core/resources/parsers;oci_policy_analysis/application/core/resources/parsers" \
      --add-binary "$PY_DLL;." \
      "$root_dir/src/oci_policy_analysis/main.py"

    echo "🪟 Packaging → dist/tk/oci-policy-analysis-tk-windows-${VERSION}.zip"
    cd dist/tk
    zip -r "oci-policy-analysis-tk-windows-${VERSION}.zip" "oci-policy-analysis-tk.exe"
    cd ../..

else
    echo "❌ Unsupported OS: $OS"
    exit 1
fi

echo "🎉 Build Complete!"
echo "   → dist/ contains fully platform-specific packaged binaries"
