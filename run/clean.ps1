#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$Mode = "all"
if ($args.Count -eq 2 -and $args[0] -eq "--mode") { $Mode = $args[1] }
elseif ($args.Count -ne 0) { throw "Usage: run/clean.ps1 [--mode ui|legacy-ui]" }

if ($Mode -eq "ui") {
    foreach ($Path in @("dist\qt", "build\qt")) {
        if (Test-Path $Path) { Remove-Item -Recurse -Force $Path }
    }
    Write-Host "Removed modern UI executable build artifacts. The shared .venv remains."
    exit 0
}
if ($Mode -eq "legacy-ui") {
    foreach ($Path in @("dist\tk", "build\tk")) {
        if (Test-Path $Path) { Remove-Item -Recurse -Force $Path }
    }
    @("run-build\oci-policy-analysis-tk.spec", "frozen.txt", "deps.txt", "deps2.txt") | ForEach-Object {
        if (Test-Path $_) { Remove-Item -Force $_ }
    }
    Write-Host "Removed legacy UI executable build artifacts. The shared .venv remains."
    exit 0
}
if ($Mode -ne "all") { throw "Invalid clean mode: $Mode (expected ui, legacy-ui, or all)" }

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
