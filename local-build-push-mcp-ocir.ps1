#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

# Build and push MCP container image to OCIR.
#
# Required environment variables:
#   OCI_REGION
#   OCI_NAMESPACE
#   OCIR_REPO
#   OCI_COMPARTMENT_OCID
#   OCIR_USERNAME
#   OCIR_AUTH_TOKEN
#
# Optional:
#   IMAGE_TAG (default: current git short SHA)
#   DOCKERFILE_PATH (default: Dockerfile.mcp)
#   OCI_PROFILE (default: CLI default profile)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker is required but not installed."
}

if (-not (Get-Command oci -ErrorAction SilentlyContinue)) {
    Write-Error "OCI CLI is required but not installed."
}

$requiredVars = @(
    "OCI_REGION",
    "OCI_NAMESPACE",
    "OCIR_REPO",
    "OCI_COMPARTMENT_OCID",
    "OCIR_USERNAME",
    "OCIR_AUTH_TOKEN"
)

$missingVars = @()
foreach ($varName in $requiredVars) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($varName))) {
        $missingVars += $varName
    }
}

if ($missingVars.Count -gt 0) {
    Write-Host "ERROR: Missing required environment variables: $($missingVars -join ', ')"
    Write-Host "Set them before running, for example:"
    Write-Host "  `$env:OCI_REGION='iad'"
    Write-Host "  `$env:OCI_NAMESPACE='<object-storage-namespace>'"
    Write-Host "  `$env:OCIR_REPO='<repo-path>'"
    Write-Host "  `$env:OCI_COMPARTMENT_OCID='<compartment-ocid>'"
    Write-Host "  `$env:OCIR_USERNAME='<oci-username>'"
    Write-Host "  `$env:OCIR_AUTH_TOKEN='<oci-auth-token>'"
    exit 2
}

$imageTag = [Environment]::GetEnvironmentVariable("IMAGE_TAG")
if ([string]::IsNullOrWhiteSpace($imageTag)) {
    $imageTag = (git rev-parse --short HEAD).Trim()
}

$dockerfilePath = [Environment]::GetEnvironmentVariable("DOCKERFILE_PATH")
if ([string]::IsNullOrWhiteSpace($dockerfilePath)) {
    $dockerfilePath = "Dockerfile.mcp"
}

$ociProfile = [Environment]::GetEnvironmentVariable("OCI_PROFILE")
$ociArgs = @()
if (-not [string]::IsNullOrWhiteSpace($ociProfile)) {
    $ociArgs += @("--profile", $ociProfile)
}

$ociRegion = [Environment]::GetEnvironmentVariable("OCI_REGION")
$ociNamespace = [Environment]::GetEnvironmentVariable("OCI_NAMESPACE")
$ocirRepo = [Environment]::GetEnvironmentVariable("OCIR_REPO")
$compartmentOcid = [Environment]::GetEnvironmentVariable("OCI_COMPARTMENT_OCID")
$ocirUsername = [Environment]::GetEnvironmentVariable("OCIR_USERNAME")
$ocirAuthToken = [Environment]::GetEnvironmentVariable("OCIR_AUTH_TOKEN")

$imageUri = "$ociRegion.ocir.io/$ociNamespace/$ocirRepo`:$imageTag"
Write-Host "Using image URI: $imageUri"
Write-Host "Checking OCIR repository '$ocirRepo'..."

$repoCount = oci @ociArgs artifacts container repository list `
    --compartment-id $compartmentOcid `
    --all `
    --query "data.items[?`"display-name`"=='$ocirRepo'] | length(@)" `
    --raw-output

if ($repoCount.Trim() -ne "1") {
    Write-Host "Repository not found. Creating '$ocirRepo'..."
    oci @ociArgs artifacts container repository create `
        --compartment-id $compartmentOcid `
        --display-name $ocirRepo | Out-Null
}

Write-Host "Logging into OCIR registry $ociRegion.ocir.io..."
$ocirAuthToken | docker login "$ociRegion.ocir.io" `
    --username "$ociNamespace/$ocirUsername" `
    --password-stdin | Out-Null

Write-Host "Building image with $dockerfilePath..."
docker build -f $dockerfilePath -t $imageUri .

Write-Host "Pushing image..."
docker push $imageUri

Write-Host "Done."
Write-Host "Pushed image: $imageUri"
