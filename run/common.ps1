$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = if ($env:RUN_ENV_FILE) { $env:RUN_ENV_FILE } else { Join-Path $ProjectRoot "run-build/.env" }
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*(#|$)') { continue }
        if ($line -notmatch '^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$') { throw "Invalid assignment in $EnvFile" }
        $name = $Matches[1]; $value = $Matches[2].Trim()
        # Keep exported one-run overrides. Values are literals, not executable PowerShell.
        if (Test-Path "Env:$name") { continue }
        if ($value -match "^'(.*)'$") { $value = $Matches[1] }
        elseif ($value -match '^"(.*)"$') { $value = $Matches[1] }
        elseif ($value -match '[\s;$`()]') { throw "Quote the literal value for $name in $EnvFile" }
        Set-Item "Env:$name" $value
    }
} elseif ($env:RUN_ENV_FILE) { throw "Missing config: $EnvFile" }
Set-Location $ProjectRoot
