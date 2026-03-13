#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

Write-Host "==============================================="
Write-Host "     LOCAL BUILD + PYINSTALLER (SOURCE ONLY)   "
Write-Host "==============================================="

if (-not (Test-Path ".venv")) {
    Write-Host "Creating fresh venv..."
    python -m venv .venv
} else {
    Write-Host "Reusing existing .venv"
}

& .venv\Scripts\Activate.ps1

Write-Host "Ensuring pip + tools are installed..."
python -m pip install --upgrade pip
python -m pip install setuptools wheel build pip-tools pyinstaller ruff

Write-Host "Locking dependencies with pip-compile..."
python -m piptools compile --generate-hashes --output-file frozen.txt pyproject.toml

Write-Host "Cleaning dependency list (no dev dependencies)..."
(Get-Content frozen.txt) | Where-Object { $_ -notmatch '^-e \.' -and $_ -notmatch '--hash=' } | Set-Content frozen.txt

Write-Host "Building wheels from source..."
New-Item -ItemType Directory -Force -Path wheels | Out-Null
pip wheel --no-binary=:all: -r frozen.txt -w wheels/

Write-Host "Installing only local source-built wheels..."
pip install --no-index --find-links=./wheels -r frozen.txt

Write-Host "Installing your project (editable mode)..."
pip install -e .

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
  --name "OCI Policy Analysis" `
  --onefile `
  --clean --noconfirm --noconsole `
  --icon "icons\oci-policy-dg-viewer.ico" `
  --collect-all sys `
  --copy-metadata fastmcp `
  --add-data "src\oci_policy_analysis\version.txt;oci_policy_analysis" `
  --add-data "src\oci_policy_analysis\logic\permissions;oci_policy_analysis\logic\permissions" `
  --add-binary "$PY_DLL;." `
  src\oci_policy_analysis\main.py

Write-Host "Packaging dist oci-policy-analysis-windows-$VERSION.zip"
Push-Location dist
Compress-Archive -Path "OCI Policy Analysis.exe" -DestinationPath "oci-policy-analysis-windows-$VERSION.zip" -Force
Pop-Location

Write-Host "Build Complete"
Write-Host "dist contains fully platform-specific packaged binaries"
