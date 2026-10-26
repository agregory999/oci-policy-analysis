#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$Mode = if ($env:LOCAL_MODE) { $env:LOCAL_MODE } else { "ui" }
$HostBind = if ($env:LOCAL_HOST) { $env:LOCAL_HOST } else { "127.0.0.1" }
$PortBind = $null
$Reload = $false
$Transport = if ($env:LOCAL_MCP_TRANSPORT) { $env:LOCAL_MCP_TRANSPORT } else { "stdio" }
$Passthrough = @()

for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "--mode" {
            $i++
            $Mode = $args[$i]
        }
        "--host" {
            $i++
            $HostBind = $args[$i]
        }
        "--port" {
            $i++
            $PortBind = [int]$args[$i]
        }
        "--reload" {
            $Reload = $true
        }
        "--transport" {
            $i++
            $Transport = $args[$i]
        }
        "--" {
            if ($i + 1 -lt $args.Count) {
                $Passthrough = $args[($i + 1)..($args.Count - 1)]
            }
            break
        }
        default {
            Write-Host "❌ Unknown argument: $($args[$i])"
            Write-Host "Usage: ./local-run.ps1 --mode ui|legacy-ui|web|cli|mcp [--host HOST] [--port PORT] [--reload] [--transport stdio|streamable-http] [-- <extra args>]"
            exit 1
        }
    }
}

$env:OCI_PROFILE = if ($env:LOCAL_OCI_PROFILE) { $env:LOCAL_OCI_PROFILE } else { "DEFAULT" }
if ($null -eq $PortBind) {
    $PortBind = if ($Mode -eq "mcp") { if ($env:LOCAL_MCP_PORT) { [int]$env:LOCAL_MCP_PORT } else { 8765 } } else { if ($env:LOCAL_WEB_PORT) { [int]$env:LOCAL_WEB_PORT } else { 8000 } }
}
Write-Host "==============================================="
Write-Host "              LOCAL RUN APPLICATION            "
Write-Host "==============================================="

# Check for venv
if (-not (Test-Path ".venv")) {
    Write-Host "❌ No virtual environment found (.venv)."
    Write-Host "   Please run local-build.ps1 or local-build-with-pyinstaller.ps1 first."
    exit 1
}

Write-Host "🐍 Activating virtual environment..."

if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .venv\Scripts\Activate.ps1
} else {
    Write-Host "❌ Could not find activation script in .venv."
    exit 1
}

Write-Host "🚀 Running OCI Policy Analysis..."
Write-Host "-----------------------------------------------"

switch ($Mode) {
    { $_ -in "ui", "desktop" } {
        oci-policy-analysis-ui @Passthrough
    }
    { $_ -in "legacy-ui", "legacy-desktop" } {
        oci-policy-analysis-legacy-ui @Passthrough
    }
    "web" {
        $WebArgs = @("--host", $HostBind, "--port", "$PortBind")
        if ($Reload) {
            $WebArgs += "--reload"
        }
        oci-policy-analysis-web @WebArgs @Passthrough
    }
    "cli" {
        oci-policy-analysis-cli @Passthrough
    }
    "mcp" {
        if ($Transport -eq "streamable-http") {
            oci-policy-analysis-mcp --transport streamable-http --host $HostBind --port $PortBind @Passthrough
        } else {
            oci-policy-analysis-mcp --transport stdio @Passthrough
        }
    }
    default {
        Write-Host "❌ Invalid mode: $Mode"
        Write-Host "   Valid modes: ui, legacy-ui, web, cli, mcp"
        exit 1
    }
}

Write-Host "-----------------------------------------------"
Write-Host "🏁 Application finished."
