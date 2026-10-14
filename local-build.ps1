# Compatibility adapter for the consolidated native PowerShell command.
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run/build.ps1") @args
exit $LASTEXITCODE
