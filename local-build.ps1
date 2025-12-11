#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "🐍 Creating fresh venv..."
    python -m venv .venv
} else {
    Write-Host "♻️ Reusing existing .venv"
}

& .venv\Scripts\Activate.ps1

Write-Host "🔄 Ensuring pip + tools are installed..."
python -m pip install --upgrade pip
python -m pip install setuptools wheel build pip-tools pyinstaller ruff

Write-Host "🔒 Locking dependencies with pip-compile..."
python -m piptools compile --generate-hashes --output-file frozen.txt pyproject.toml

Write-Host "📦 Cleaning dependency list (no dev dependencies)..."
(Get-Content frozen.txt) | Where-Object { $_ -notmatch '^-e \.' -and $_ -notmatch '--hash=' } | Set-Content frozen.txt

Write-Host "🔨 Building wheels from source..."
New-Item -ItemType Directory -Force -Path wheels | Out-Null
pip wheel --no-binary=:all: -r frozen.txt -w wheels/

Write-Host "📥 Installing dependencies from local wheels..."
pip install --no-index --find-links=./wheels -r frozen.txt

Write-Host "📦 Building your own package..."
python -m build

Write-Host "🚀 Installing your package (editable mode)..."
pip install -e .

Write-Host "🎉 Local build complete!"
Write-Host "   Wheels → wheels/"
Write-Host "   App    → dist/"
