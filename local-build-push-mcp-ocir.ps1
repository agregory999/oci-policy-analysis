# Compatibility adapter; container operations share the Bash implementation.
$ErrorActionPreference = "Stop"
& bash (Join-Path $PSScriptRoot "run/build-push-image.sh") mcp @args
exit $LASTEXITCODE
