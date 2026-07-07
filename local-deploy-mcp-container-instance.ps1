#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

# Deploy (or redeploy) OCI Policy Analysis MCP as an OCI Container Instance.
#
# Required environment variables:
#   OCI_COMPARTMENT_OCID
#   OCI_SUBNET_OCID
#   OCI_IMAGE_URL
#
# Optional environment variables:
#   OCI_PROFILE
#   OCI_AD
#   OCI_CONTAINER_INSTANCE_NAME         (default: opa-mcp-policy-latest-a1)
#   OCI_CONTAINER_NAME                  (default: mcp)
#   OCI_CONTAINER_SHAPE                 (default: CI.Standard.A1.Flex)
#   OCI_CONTAINER_OCPUS                 (default: 1)
#   OCI_CONTAINER_MEMORY_GBS            (default: 8)
#   OCI_PRIVATE_IP                      (optional static private IP in selected subnet)
#   OCI_REDEPLOY                        (default: true)
#
#   MCP_AUTH_MODE                       (default: resource_principal)
#   MCP_TRANSPORT                       (default: streamable-http)
#   MCP_HOST                            (default: 0.0.0.0)
#   MCP_PORT                            (default: 8765)
#   MCP_LOG_LEVEL                       (default: WARNING)
#   MCP_SAVE_CACHE_AFTER_LOAD           (default: false)
#   MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH (default: 1)
#   MCP_OAUTH_ENABLED                   (default: false)
#   MCP_OAUTH_ISSUER                    (required if MCP_OAUTH_ENABLED=true)
#   MCP_OAUTH_JWKS_URI                  (required if MCP_OAUTH_ENABLED=true)
#   MCP_OAUTH_AUDIENCE                  (required if MCP_OAUTH_ENABLED=true)
#   MCP_OAUTH_REQUIRED_SCOPES           (required if MCP_OAUTH_ENABLED=true; token must include all listed scopes)
#   MCP_OAUTH_UPDATE_SCOPE              (optional; required for reload when set)
#   MCP_OAUTH_RESOURCE_SERVER_URL       (required if MCP_OAUTH_ENABLED=true)
#   MCP_OAUTH_AUTHORIZATION_SERVER_URL  (required if MCP_OAUTH_ENABLED=true)
#   MCP_OAUTH_ALGORITHM                 (default: RS256)

if (-not (Get-Command oci -ErrorAction SilentlyContinue)) {
    Write-Error "OCI CLI is required but not installed."
}

$requiredVars = @("OCI_COMPARTMENT_OCID", "OCI_SUBNET_OCID", "OCI_IMAGE_URL")
$missingVars = @()
foreach ($varName in $requiredVars) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($varName))) {
        $missingVars += $varName
    }
}
if ($missingVars.Count -gt 0) {
    Write-Host "ERROR: Missing required environment variables: $($missingVars -join ', ')"
    Write-Host "Set them before running:"
    Write-Host "  `$env:OCI_COMPARTMENT_OCID='<compartment-ocid>'"
    Write-Host "  `$env:OCI_SUBNET_OCID='<subnet-ocid>'"
    Write-Host "  `$env:OCI_IMAGE_URL='ocir.us-ashburn-1.oci.oraclecloud.com/<namespace>/<repo>:latest'"
    exit 2
}

$ociProfile = [Environment]::GetEnvironmentVariable("OCI_PROFILE")
$compartmentOcid = [Environment]::GetEnvironmentVariable("OCI_COMPARTMENT_OCID")
$subnetOcid = [Environment]::GetEnvironmentVariable("OCI_SUBNET_OCID")
$imageUrl = [Environment]::GetEnvironmentVariable("OCI_IMAGE_URL")

$instanceName = [Environment]::GetEnvironmentVariable("OCI_CONTAINER_INSTANCE_NAME")
if ([string]::IsNullOrWhiteSpace($instanceName)) { $instanceName = "opa-mcp-policy-latest-a1" }
$containerName = [Environment]::GetEnvironmentVariable("OCI_CONTAINER_NAME")
if ([string]::IsNullOrWhiteSpace($containerName)) { $containerName = "mcp" }
$shape = [Environment]::GetEnvironmentVariable("OCI_CONTAINER_SHAPE")
if ([string]::IsNullOrWhiteSpace($shape)) { $shape = "CI.Standard.A1.Flex" }
$ocpus = [Environment]::GetEnvironmentVariable("OCI_CONTAINER_OCPUS")
if ([string]::IsNullOrWhiteSpace($ocpus)) { $ocpus = "1" }
$memoryGbs = [Environment]::GetEnvironmentVariable("OCI_CONTAINER_MEMORY_GBS")
if ([string]::IsNullOrWhiteSpace($memoryGbs)) { $memoryGbs = "8" }
$privateIp = [Environment]::GetEnvironmentVariable("OCI_PRIVATE_IP")
$redeploy = [Environment]::GetEnvironmentVariable("OCI_REDEPLOY")
if ([string]::IsNullOrWhiteSpace($redeploy)) { $redeploy = "true" }
$ad = [Environment]::GetEnvironmentVariable("OCI_AD")

$mcpAuthMode = [Environment]::GetEnvironmentVariable("MCP_AUTH_MODE"); if ([string]::IsNullOrWhiteSpace($mcpAuthMode)) { $mcpAuthMode = "resource_principal" }
$mcpTransport = [Environment]::GetEnvironmentVariable("MCP_TRANSPORT"); if ([string]::IsNullOrWhiteSpace($mcpTransport)) { $mcpTransport = "streamable-http" }
$mcpHost = [Environment]::GetEnvironmentVariable("MCP_HOST"); if ([string]::IsNullOrWhiteSpace($mcpHost)) { $mcpHost = "0.0.0.0" }
$mcpPort = [Environment]::GetEnvironmentVariable("MCP_PORT"); if ([string]::IsNullOrWhiteSpace($mcpPort)) { $mcpPort = "8765" }
$mcpLogLevel = [Environment]::GetEnvironmentVariable("MCP_LOG_LEVEL"); if ([string]::IsNullOrWhiteSpace($mcpLogLevel)) { $mcpLogLevel = "WARNING" }
$mcpSaveCache = [Environment]::GetEnvironmentVariable("MCP_SAVE_CACHE_AFTER_LOAD"); if ([string]::IsNullOrWhiteSpace($mcpSaveCache)) { $mcpSaveCache = "false" }
$mcpDepth = [Environment]::GetEnvironmentVariable("MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH"); if ([string]::IsNullOrWhiteSpace($mcpDepth)) { $mcpDepth = "1" }
$mcpOauthEnabled = [Environment]::GetEnvironmentVariable("MCP_OAUTH_ENABLED"); if ([string]::IsNullOrWhiteSpace($mcpOauthEnabled)) { $mcpOauthEnabled = "false" }
$mcpOauthIssuer = [Environment]::GetEnvironmentVariable("MCP_OAUTH_ISSUER")
$mcpOauthJwksUri = [Environment]::GetEnvironmentVariable("MCP_OAUTH_JWKS_URI")
$mcpOauthAudience = [Environment]::GetEnvironmentVariable("MCP_OAUTH_AUDIENCE")
$mcpOauthRequiredScopes = [Environment]::GetEnvironmentVariable("MCP_OAUTH_REQUIRED_SCOPES")
$mcpOauthUpdateScope = [Environment]::GetEnvironmentVariable("MCP_OAUTH_UPDATE_SCOPE")
$mcpOauthResourceServerUrl = [Environment]::GetEnvironmentVariable("MCP_OAUTH_RESOURCE_SERVER_URL")
$mcpOauthAuthorizationServerUrl = [Environment]::GetEnvironmentVariable("MCP_OAUTH_AUTHORIZATION_SERVER_URL")
$mcpOauthAlgorithm = [Environment]::GetEnvironmentVariable("MCP_OAUTH_ALGORITHM"); if ([string]::IsNullOrWhiteSpace($mcpOauthAlgorithm)) { $mcpOauthAlgorithm = "RS256" }

if (-not ($mcpDepth -match '^\d+$') -or [int]$mcpDepth -lt 1 -or [int]$mcpDepth -gt 6) {
    Write-Host "ERROR: MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH must be an integer between 1 and 6."
    exit 2
}

$ociArgs = @()
if (-not [string]::IsNullOrWhiteSpace($ociProfile)) {
    $ociArgs += @("--profile", $ociProfile)
}

Write-Host "Resolving existing container instance named '$instanceName'..."
$listRaw = oci @ociArgs container-instances container-instance list --compartment-id $compartmentOcid --all --output json
$listData = $listRaw | ConvertFrom-Json
$existing = $listData.data.items | Where-Object { $_."display-name" -eq $instanceName -and $_."lifecycle-state" -ne "DELETED" } | Select-Object -First 1

if ($existing) {
    Write-Host "Found existing instance: $($existing.id)"
    if ([string]::IsNullOrWhiteSpace($ad)) {
        $ad = $existing."availability-domain"
        Write-Host "Using existing instance availability domain: $ad"
    }
    if ($redeploy.ToLower() -eq "true") {
        Write-Host "Deleting existing instance for redeploy..."
        oci @ociArgs container-instances container-instance delete --container-instance-id $existing.id --force --wait-for-state SUCCEEDED --max-wait-seconds 1800 | Out-Null
    } else {
        Write-Host "ERROR: Existing instance found and OCI_REDEPLOY is not true. Set OCI_REDEPLOY=true to replace it."
        exit 2
    }
}

if ([string]::IsNullOrWhiteSpace($ad)) {
    Write-Host "ERROR: OCI_AD is required when creating a new instance and no existing instance was found."
    exit 2
}

$containers = @(
    @{
        displayName = $containerName
        imageUrl = $imageUrl
        environmentVariables = @{
            MCP_AUTH_MODE = $mcpAuthMode
            MCP_TRANSPORT = $mcpTransport
            MCP_HOST = $mcpHost
            MCP_PORT = $mcpPort
            MCP_LOG_LEVEL = $mcpLogLevel
            MCP_SAVE_CACHE_AFTER_LOAD = $mcpSaveCache
            MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH = $mcpDepth
            MCP_OAUTH_ENABLED = $mcpOauthEnabled
            MCP_OAUTH_ISSUER = $mcpOauthIssuer
            MCP_OAUTH_JWKS_URI = $mcpOauthJwksUri
            MCP_OAUTH_AUDIENCE = $mcpOauthAudience
            MCP_OAUTH_REQUIRED_SCOPES = $mcpOauthRequiredScopes
            MCP_OAUTH_UPDATE_SCOPE = $mcpOauthUpdateScope
            MCP_OAUTH_RESOURCE_SERVER_URL = $mcpOauthResourceServerUrl
            MCP_OAUTH_AUTHORIZATION_SERVER_URL = $mcpOauthAuthorizationServerUrl
            MCP_OAUTH_ALGORITHM = $mcpOauthAlgorithm
        }
    }
)

$vnics = @(
    @{
        displayName = "mcp-vnic"
        subnetId = $subnetOcid
        isPublicIpAssigned = $false
    }
)
if (-not [string]::IsNullOrWhiteSpace($privateIp)) {
    $vnics[0].privateIp = $privateIp
}

$containersFile = New-TemporaryFile
$vnicsFile = New-TemporaryFile
try {
    ($containers | ConvertTo-Json -Depth 8) | Set-Content -Path $containersFile -Encoding utf8
    ($vnics | ConvertTo-Json -Depth 8) | Set-Content -Path $vnicsFile -Encoding utf8

    Write-Host "Creating container instance '$instanceName' in AD '$ad'..."
    oci @ociArgs container-instances container-instance create `
        --compartment-id $compartmentOcid `
        --availability-domain $ad `
        --display-name $instanceName `
        --shape $shape `
        --shape-config "{`"ocpus`":$ocpus,`"memoryInGBs`":$memoryGbs}" `
        --container-restart-policy ALWAYS `
        --containers "file://$containersFile" `
        --vnics "file://$vnicsFile" `
        --wait-for-state SUCCEEDED `
        --max-wait-seconds 1800 | Out-Null
}
finally {
    Remove-Item -Force $containersFile, $vnicsFile -ErrorAction SilentlyContinue
}

$postListRaw = oci @ociArgs container-instances container-instance list --compartment-id $compartmentOcid --all --output json
$postListData = $postListRaw | ConvertFrom-Json
$created = $postListData.data.items | Where-Object { $_."display-name" -eq $instanceName -and $_."lifecycle-state" -eq "ACTIVE" } | Select-Object -First 1

Write-Host "Deployment complete."
if ($created) {
    Write-Host "Container Instance OCID: $($created.id)"
    $instanceGetRaw = oci @ociArgs container-instances container-instance get --container-instance-id $created.id --output json
    $instanceGet = $instanceGetRaw | ConvertFrom-Json
    $containerId = $instanceGet.data.containers[0]."container-id"
    Write-Host "Container OCID: $containerId"
    $vnicId = $instanceGet.data.vnics[0]."vnic-id"
    if (-not [string]::IsNullOrWhiteSpace($vnicId)) {
        $vnicRaw = oci @ociArgs network vnic get --vnic-id $vnicId --output json
        $vnic = $vnicRaw | ConvertFrom-Json
        Write-Host "Private IP: $($vnic.data.'private-ip')"
    }
}
