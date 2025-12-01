#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "🐍 Creating fresh uv venv..."
    uv venv --python=3.12
} else {
    Write-Host "♻️ Reusing existing .venv"
}

& .venv\Scripts\Activate.ps1

Write-Host "🔄 Ensuring pip + tools are installed..."
uv pip install pip setuptools wheel build pyinstaller ruff

Write-Host "🔒 Locking dependencies..."
uv lock

Write-Host "📦 Exporting dependency list (no dev dependencies)..."
uv export --no-dev | Out-File -Encoding utf8 frozen.txt

Write-Host "🧹 Removing local project entry..."
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
