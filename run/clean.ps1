#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

Write-Host "==============================================="
Write-Host "            LOCAL CLEAN (FULL RESET)           "
Write-Host "==============================================="

Write-Host "Removing virtual environment..."
if (Test-Path ".venv") {
    Remove-Item -Recurse -Force ".venv"
}

Write-Host "Removing build artifacts..."
@("dist", "build", "wheels", "frozen.txt", "deps.txt", "deps2.txt") | ForEach-Object {
    if (Test-Path $_) {
        Remove-Item -Recurse -Force $_
    }
}

Write-Host "Cleaning Python caches..."
Get-ChildItem src -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force

Write-Host "Clean complete."
