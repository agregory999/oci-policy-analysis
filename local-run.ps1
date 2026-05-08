#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

$Mode = "desktop"
$HostBind = "127.0.0.1"
$PortBind = 8000
$Reload = $false
$Transport = "stdio"
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
            Write-Host "Usage: ./local-run.ps1 --mode desktop|web|cli|mcp [--host HOST] [--port PORT] [--reload] [--transport stdio|streamable-http] [-- <extra args>]"
            exit 1
        }
    }
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
    "desktop" {
        python -m oci_policy_analysis.main $Passthrough
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
        Write-Host "   Valid modes: desktop, web, cli, mcp"
        exit 1
    }
}

Write-Host "-----------------------------------------------"
Write-Host "🏁 Application finished."
