# Compatibility adapter: one sourceable configuration and deployment implementation.
$ErrorActionPreference = "Stop"
& bash (Join-Path $PSScriptRoot "run/deploy-container-instance.sh") mcp @args
exit $LASTEXITCODE
