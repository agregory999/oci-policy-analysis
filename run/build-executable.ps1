#!/usr/bin/env pwsh
param(
    [ValidateSet("desktop", "qt")][string]$Interface = "desktop",
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$BuildArgs
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if ($Interface -eq "qt") {
    uv sync --inexact --extra qt --extra qt-build --extra web --extra mcp
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    uv pip check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & .venv\Scripts\python.exe run-build/build_qt_executable.py @BuildArgs
    exit $LASTEXITCODE
}

Write-Host "==============================================="
Write-Host "     LOCAL BUILD + PYINSTALLER (SOURCE ONLY)   "
Write-Host "==============================================="

uv sync --inexact --extra web --extra mcp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .venv\Scripts\Activate.ps1
uv pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed." }
python scripts/check_desktop_imports.py
if ($LASTEXITCODE -ne 0) { throw "Desktop startup dependency imports failed." }
Write-Host "Determining version via importlib.metadata..."
$VERSION = python -c "import importlib.metadata; print(importlib.metadata.version('oci_policy_analysis'))"
Write-Host "  -> version = $VERSION"

$VERSION | Out-File -Encoding utf8 -NoNewline src\oci_policy_analysis\version.txt

Write-Host "==============================================="
Write-Host "             RUNNING PYINSTALLER"
Write-Host "==============================================="

Write-Host "Windows detected - building onefile .exe"

$PY_DLL = python -c "import sys, os; major=sys.version_info[0]; minor=sys.version_info[1]; name=f'python{major}{minor}.dll'; paths=[os.path.join(os.path.dirname(sys.executable), name), os.path.join(getattr(sys, 'base_prefix', sys.prefix), name)]; print(next((p for p in paths if os.path.exists(p)), ''))"

Write-Host "   Python DLL: $PY_DLL"

pyinstaller `
  --distpath dist/tk --workpath build/tk --specpath run-build `
  --name "oci-policy-analysis-tk" `
  --onefile `
  --clean --noconfirm --noconsole `
  --icon "icons\oci-policy-dg-viewer.ico" `
  --collect-all sys `
  --copy-metadata fastmcp `
  --add-data "src\oci_policy_analysis\version.txt;oci_policy_analysis" `
  --add-data "src\oci_policy_analysis\application\core\resources\permissions;oci_policy_analysis\application\core\resources\permissions" `
  --add-data "src\oci_policy_analysis\application\core\resources\mcp_tools_list;oci_policy_analysis\application\core\resources\mcp_tools_list" `
  --add-data "src\oci_policy_analysis\application\core\resources\parsers;oci_policy_analysis\application\core\resources\parsers" `
  --add-binary "$PY_DLL;." `
  src\oci_policy_analysis\main.py

Write-Host "Packaging dist oci-policy-analysis-tk-windows-$VERSION.zip"
Push-Location dist/tk
Compress-Archive -Path "oci-policy-analysis-tk.exe" -DestinationPath "oci-policy-analysis-tk-windows-$VERSION.zip" -Force
Pop-Location

Write-Host "Build Complete"
Write-Host "dist contains fully platform-specific packaged binaries"
