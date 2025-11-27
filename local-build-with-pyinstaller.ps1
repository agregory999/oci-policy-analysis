#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

Write-Host "==============================================="
Write-Host "     LOCAL BUILD + PYINSTALLER (SOURCE ONLY)   "
Write-Host "==============================================="

if (-not (Test-Path ".venv")) {
    Write-Host "🐍 Creating fresh uv venv..."
    uv venv --python=3.12
} else {
    Write-Host "♻️ Reusing existing .venv"
}

& .venv\Scripts\Activate.ps1

Write-Host "🔄 Ensuring pip + tools are installed..."
uv pip install pip setuptools wheel build pyinstaller ruff

Write-Host "🔒 Locking dependencies with uv..."
uv lock

Write-Host "📦 Exporting dependencies (no dev)..."
uv export --no-dev | Out-File -Encoding utf8 frozen.txt

Write-Host "🧹 Removing local project (-e .) and hash entries..."
(Get-Content frozen.txt) | Where-Object { $_ -notmatch '^-e \.' -and $_ -notmatch '--hash=' } | Set-Content frozen.txt

Write-Host "🔨 Building wheels from source..."
New-Item -ItemType Directory -Force -Path wheels | Out-Null
pip wheel --no-binary=:all: -r frozen.txt -w wheels/

Write-Host "📥 Installing only local source-built wheels..."
pip install --no-index --find-links=./wheels -r frozen.txt

Write-Host "📦 Installing your project (editable mode)..."
pip install -e .

Write-Host "📝 Determining version via importlib.metadata..."
$VERSION = python -c "import importlib.metadata; print(importlib.metadata.version('oci_policy_analysis'))"
Write-Host "   → version = $VERSION"

$VERSION | Out-File -Encoding utf8 -NoNewline src\oci_policy_analysis\version.txt

Write-Host "==============================================="
Write-Host "             RUNNING PYINSTALLER"
Write-Host "==============================================="

Write-Host "🪟 Windows detected — building onefile .exe"

$PY_DLL = python -c "import sysconfig, glob, os; b=sysconfig.get_config_var('BINDIR'); matches=glob.glob(os.path.join(b, 'python3*.dll')); print(matches[0] if matches else '')"
Write-Host "   Python DLL: $PY_DLL"

pyinstaller `
  --name "OCI Policy Analysis" `
  --onefile `
  --clean --noconfirm --noconsole `
  --icon "icons\oci-policy-dg-viewer.ico" `
  --collect-all sys `
  --copy-metadata fastmcp `
  --add-data "src\oci_policy_analysis\version.txt;oci_policy_analysis" `
  --add-data "src\reference_data;reference_data" `
  --add-binary "$PY_DLL;." `
  src\oci_policy_analysis\main.py

Write-Host "🪟 Packaging → dist\oci-policy-analysis-windows-$VERSION.zip"
Push-Location dist
Compress-Archive -Path "OCI Policy Analysis.exe" -DestinationPath "oci-policy-analysis-windows-$VERSION.zip" -Force
Pop-Location

Write-Host "🎉 Build Complete!"
Write-Host "   → dist\ contains fully platform-specific packaged binaries"
