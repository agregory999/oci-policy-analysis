# Compatibility adapter for the consolidated native PowerShell command.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run/clean.ps1") @args
exit $LASTEXITCODE
