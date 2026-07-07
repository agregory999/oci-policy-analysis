# MCP Deployment on OCI Container Instance

This guide packages the standalone MCP server as a container image, pushes it to OCIR, and deploys it to an OCI Container Instance running in a private subnet.

The default runtime behavior in this guide is:

- live tenancy load at startup (no cache load)
- `--resource-principal` authentication
- streamable HTTP transport
- listen on `0.0.0.0:8765`
- log level `INFO`
- do not save cache after live load
- identity domain compartment search depth `1` by default (set `2` when domains exist in child compartments)

## 1. Prerequisites

- OCI CLI installed and authenticated.
- Docker installed locally.
- A private OCIR repository path (you said you are creating this).
- A VCN/subnet where the Container Instance can reach OCI public APIs (typically via NAT Gateway in private subnet).
- IAM policy for the Container Instance granting the read permissions needed by policy analysis. See [Setup: Permissions Required and Authentication](setup.md#permissions-required-and-authentication).
- Optional OAuth setup for real-user or machine-to-machine MCP access. See [MCP OAuth Setup](mcp_oauth.md).

## 2. Build and Push to OCIR

Use the helper script (repo root, Unix shell):

```bash
chmod +x local-build-push-mcp-ocir.sh
```

```bash
export OCI_REGION=iad
export OCI_NAMESPACE=<object-storage-namespace>
export OCIR_REPO=oci-policy-analysis/mcp
export OCI_COMPARTMENT_OCID=<compartment-ocid-containing-ocir-repo>
export OCIR_USERNAME='<your-oci-username>'
export OCIR_AUTH_TOKEN='<oci-auth-token>'
export IMAGE_TAG=mcp-container-001

./local-build-push-mcp-ocir.sh
```

Windows PowerShell variant:

```powershell
.\local-build-push-mcp-ocir.ps1
```

These scripts validate required environment variables and fail gracefully with clear setup guidance when values are missing.

Output includes a pushed image URI, for example:

`iad.ocir.io/<namespace>/oci-policy-analysis/mcp:mcp-container-001`

## 3. Container Runtime Contract

Container entrypoint:

- file: `docker/mcp-entrypoint.sh`
- image: `Dockerfile.mcp`

Supported environment variables:

- `MCP_AUTH_MODE` (`instance_principal` default; options: `resource_principal`, `instance_principal`, `profile`, `cache`, `session_token`)
- `MCP_TRANSPORT` (`streamable-http` default)
- `MCP_HOST` (`0.0.0.0` default)
- `MCP_PORT` (`8765` default)
- `MCP_LOG_LEVEL` (`WARNING` default; use `INFO` temporarily for OAuth setup diagnostics and MCP call logging)
- `MCP_RECURSIVE` (`true` default)
- `MCP_SAVE_CACHE_AFTER_LOAD` (`false` default)
- `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH` (`1` default; valid range `1-6`; set `2` to include direct child compartments)
- `OCI_PROFILE` (required only if `MCP_AUTH_MODE=profile`)
- `MCP_USE_CACHE` (required only if `MCP_AUTH_MODE=cache`)
- `OCI_SESSION_TOKEN` (required only if `MCP_AUTH_MODE=session_token`)

For OAuth configuration, use the single canonical guide: [MCP OAuth Setup](mcp_oauth.md).

## 4. Create OCI Container Instance

Use the local deployment script (recommended):

Unix shell:

```bash
export OCI_PROFILE=ADMIN-ANDGRE-5678
export OCI_COMPARTMENT_OCID=<target-compartment-ocid>
export OCI_SUBNET_OCID=<target-private-subnet-ocid>
export OCI_IMAGE_URL=ocir.us-ashburn-1.oci.oraclecloud.com/<namespace>/<repo>:latest
export OCI_AD=<target-availability-domain>
# Optional static private IP in selected subnet:
# export OCI_PRIVATE_IP=10.254.0.250

# Optional MCP runtime overrides:
# export MCP_LOG_LEVEL=WARNING
# export MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH=2

# For OAuth protection, follow [MCP OAuth Setup](mcp_oauth.md).

./local-deploy-mcp-container-instance.sh
```

Windows PowerShell:

```powershell
$env:OCI_PROFILE="ADMIN-ANDGRE-5678"
$env:OCI_COMPARTMENT_OCID="<target-compartment-ocid>"
$env:OCI_SUBNET_OCID="<target-private-subnet-ocid>"
$env:OCI_IMAGE_URL="ocir.us-ashburn-1.oci.oraclecloud.com/<namespace>/<repo>:latest"
$env:OCI_AD="<target-availability-domain>"
# Optional static private IP in selected subnet:
# $env:OCI_PRIVATE_IP="10.254.0.250"

# Optional MCP runtime overrides:
# $env:MCP_LOG_LEVEL="WARNING"
# $env:MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH="2"

# For OAuth protection, follow [MCP OAuth Setup](mcp_oauth.md).

.\local-deploy-mcp-container-instance.ps1
```

These scripts:

- use your configured `OCI_PROFILE` when provided
- apply the MCP defaults in this guide unless overridden
- redeploy safely by deleting an existing same-name instance before create
- support optional fixed private IP via `OCI_PRIVATE_IP`
- fail gracefully when required variables are missing

OCI Console manual flow (alternative):

1. Go to `Developer Services -> Containers & Artifacts -> Container Instances`.
2. Create Container Instance in your target compartment.
3. Networking:
   - select your VCN and private subnet
   - ensure egress to OCI APIs (NAT or service gateway path as appropriate)
4. Image source:
   - choose OCIR image URI pushed in step 2
5. Container settings:
   - container port: `8765`
   - command: leave empty (uses image entrypoint)
   - environment variables:
     - `MCP_AUTH_MODE=resource_principal`
     - `MCP_TRANSPORT=streamable-http`
     - `MCP_HOST=0.0.0.0`
     - `MCP_PORT=8765`
     - `MCP_LOG_LEVEL=WARNING`
     - `MCP_SAVE_CACHE_AFTER_LOAD=false`
     - `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH=2` (recommended for tenancies where identity domains are in child compartments)
     - optional OAuth variables from [MCP OAuth Setup](mcp_oauth.md)
6. Attach IAM policy for the container instance resource principal auth path. See [Setup: Permissions Required and Authentication](setup.md#permissions-required-and-authentication).
7. Create and wait until state is `Active`.

## 5. Validate in OCI

Check logs first:

- confirm startup includes resource principal mode
- confirm tenancy load succeeded
- confirm MCP transport started on `0.0.0.0:8765`

From a host that can reach the private endpoint:

```bash
curl -sS http://<container-instance-private-ip>:8765/health
```

Expected response:

```json
{"status":"healthy"}
```

Tool-level validation through MCP client/proxy:

- call `tools/list`
- call `filter_policy_statements` with a known `principal_keys` value

Example payload:

```json
{
  "filters": {
    "principal_keys": ["group:Default/Administrators"]
  }
}
```

## 6. Optional: Front with Load Balancer

For external consumers, front this private Container Instance with an OCI Load Balancer or API Gateway:

- listener: HTTPS 443
- backend set target: container private IP port `8765`
- health check path: `/health`
- route MCP clients to `https://<lb-host>/mcp`

For OAuth-protected deployments, see [MCP OAuth Setup](mcp_oauth.md).

## 7. Local Smoke Test Before Push

Build and run locally:

```bash
docker build -f Dockerfile.mcp -t opa-mcp:local .
docker run --rm -p 8765:8765 opa-mcp:local
```

Then:

```bash
curl -sS http://127.0.0.1:8765/health
```

If local Docker is not running in OCI with instance principal access, use cache mode and mount your local cache directory:

```bash
docker run --rm -p 8765:8765 \
  -e MCP_AUTH_MODE=cache \
  -e MCP_USE_CACHE=<cache-name> \
  -v $HOME/.oci-policy-analysis/cache:/root/.oci-policy-analysis/cache:ro \
  opa-mcp:local
```

## 8. Redeployment for Runtime Parameter Changes

OCI Container Instances do not support in-place updates of container environment variables.
If you change any MCP runtime parameter (for example `MCP_LOG_LEVEL`, `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH`, transport, host/port, or auth mode), redeploy the container instance.

Typical flow:

1. Update your intended environment variable values.
2. Build and push a new image tag (or reuse `latest`).
3. Run `./local-deploy-mcp-container-instance.sh` (or `.\local-deploy-mcp-container-instance.ps1`) to redeploy.
4. The script deletes/recreates the Container Instance with updated environment variables.
5. Validate startup logs and `/health`.
