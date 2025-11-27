#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

Write-Host "==============================================="
Write-Host "              LOCAL RUN APPLICATION            "
Write-Host "==============================================="

# Check for venv
if (-not (Test-Path ".venv")) {
    Write-Host "❌ No virtual environment found (.venv)."
    Write-Host "   Please run local-build.ps1 or local-build-with-pyinstaller.ps1 first."
    exit 1
}

Write-Host "🐍 Activating virtual environment..."

if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .venv\Scripts\Activate.ps1
} else {
    Write-Host "❌ Could not find activation script in .venv."
    exit 1
}

Write-Host "🚀 Running OCI Policy Analysis..."
Write-Host "-----------------------------------------------"

# Run via module form (recommended for portability)
python -m oci_policy_analysis.main $args

Write-Host "-----------------------------------------------"
Write-Host "🏁 Application finished."
