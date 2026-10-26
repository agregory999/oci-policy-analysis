$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
$Mode = if ($env:LOCAL_BUILD_MODE) { $env:LOCAL_BUILD_MODE } else { "all" }
if ($args.Count -eq 2 -and $args[0] -eq "--mode") { $Mode = $args[1] }
elseif ($args.Count -ne 0) { throw "Usage: run/build.ps1 [--mode ui|legacy-ui|web|cli|mcp|all]" }
$UvArgs = @("sync")
switch ($Mode) {
    "all" { $UvArgs += @("--extra", "qt", "--extra", "web", "--extra", "mcp") }
    { $_ -in "web", "mcp" } { $UvArgs += @("--extra", $Mode) }
    { $_ -in "ui", "desktop" } { $UvArgs += @("--extra", "qt", "--extra", "mcp") }
    { $_ -in "legacy-ui", "legacy-desktop" } { $UvArgs += @("--extra", "mcp") }
    "cli" { }
    default { throw "Invalid build mode: $Mode" }
}
if ($env:PYTHON_BIN) { $UvArgs += @("--python", $env:PYTHON_BIN) }
uv @UvArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv build
exit $LASTEXITCODE
