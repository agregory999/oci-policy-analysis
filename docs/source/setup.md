# Setup

This is the central setup guide for OCI Policy Analysis. Choose a run mode, choose a data source, and configure OCI access only when you intend to load live tenancy data.

## Choose a run mode

| Mode | Best for | Install |
|---|---|---|
| Desktop | Local, single-user interactive analysis | `pip install oci-policy-analysis` |
| Web | Browser-based local or team use | `pip install "oci-policy-analysis[web]"` |
| CLI | Automation, exports, and offline workflows | `pip install oci-policy-analysis` |
| MCP | AI clients and MCP-based automation | `pip install "oci-policy-analysis[mcp]"` |

All pip installs require Python 3.12 or later. Create a virtual environment first:

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

## Choose a data source

Choose this before configuring credentials. The application is read-only: it analyzes the selected data but does not modify OCI resources.

### Live OCI tenancy data

Use this option to read current compartments, policies, identity domains, users, groups, and dynamic groups. It requires an OCI user/API-key profile, session token, instance principal, or resource principal, plus the IAM permissions in [Permissions required](#permissions-required). Configure authentication and permissions before starting a live load.

### Combined cache

A combined cache is data previously saved by OCI Policy Analysis. Reopen it for repeatable or offline analysis, or compare caches in Historical Analysis. No OCI connection is required when opening a cache.

### OCI CIS Compliance output

Import the directory containing OCI CIS Compliance output CSV files when the analysis environment must not connect directly to OCI. The desktop and web applications provide **Load Compliance Data**. From the CLI:

```bash
oci-policy-analysis-cli --load-from-compliance /path/to/compliance_csv_output
```

See the [CLI guide](cli.md) for import details. CIS output is a supplied dataset, so features that need current OCI data may be unavailable.

### Obtain CIS Compliance output

OCI Landing Zones publishes the [CIS Compliance script](https://github.com/oci-landing-zones/oci-cis-landingzone-quickstart#cis-compliance-script) used to generate this data. Follow that guide to obtain and run the script with its `--raw` option, then keep the generated output directory available to the application.

Example using `standard.sh` script:
```bash
user@host scripts % ./standard.sh --cis '--raw'
```
Import that directory with **Load Compliance Data** in the desktop or web application, or pass its path to the CLI command above. Do not use a zip file, but rather the unzipped contents. This workflow lets a separate, approved process collect the tenancy data; OCI Policy Analysis then analyzes the resulting files without using OCI credentials or connecting to the tenancy.  Thus no access to the tenancy is required from the OCI Policy Analysis tool.

## Authentication and principals

Use the principal appropriate to where the application runs:

| Principal | Use when | Configuration |
|---|---|---|
| Named user / OCI profile | Running locally with an OCI config profile | Select the profile in the desktop/web app or use the CLI/MCP profile option. |
| Session token | Using temporary local credentials | Create a session token in the OCI CLI config and select its profile. |
| Instance principal | Running on an OCI Compute instance | Grant policies to the instance's dynamic group; no local user key is needed. |
| Resource principal | Running in an OCI Container Instance | Grant policies to the Container Instance resource principal; see [Containerized MCP](#containerized-mcp-on-oci-container-instances). |

Use a named profile or session token for a workstation. Use an instance or resource principal for OCI-hosted workloads so credentials are not stored in the runtime environment.

## Permissions required

Permissions are required **only for live OCI loads**. Cache and CIS Compliance imports do not require OCI credentials or IAM policies for this tool.

These policies grant read/inspect access for analysis - OCI Policy Analysis does not create, update, or delete any resources in your tenancy, and will not have access to do so provided the permissions are set up as follows. The permission statements grant very limited permission to read only what is required for the tool to function.

An OCI administrator must grant the policy to the identity that runs the tool, in the tenancy being analyzed. Use the policy that matches your principal:

**NOTE:** `generative-ai-family` is needed only for AI features in the desktop tool. Omit it when those features are not used. 

### User principal: API-key profile or session token

For a workstation user authenticated through an OCI API-key profile or session token, grant the policy to that user's group:

```text
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow group <your_group> to use generative-ai-family in tenancy
```

### Instance principal

For an application running on an OCI Compute VM, grant the equivalent policy to the instance's dynamic group:

```text
allow dynamic-group <your_dynamic_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow dynamic-group <your_dynamic_group> to use generative-ai-family in tenancy
```
You must have or create a dynamic group, based on the OCI Instance OCID or Compartment OCID of the instance.  This dynamic group then receives the permission above.

Example Dynamic Group Definition:
```json
ALL {instance.id = 'ocid1.instance.yy.zz'}
```
or
```json
ALL {instance.compartment.id = 'ocid1.compartment.yy.zz'}
```

### Resource principal: OCI Container Instance

For an MCP server running in an OCI Container Instance, scope the policy to that specific instance using a resource principal style (any-user/where):

```text
allow any-user to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy where all { request.principal.type = 'computecontainerinstance', request.principal.id = '<container-instance-ocid>' }
```

## Desktop application

Desktop mode is the full local tabbed experience and requires a working Tkinter installation.

```bash
python -m pip install oci-policy-analysis
python -m tkinter  # optional check; opens a small test window
oci-policy-analysis-ui
```

The downloadable macOS and Windows applications are available from the [Releases page](https://github.com/agregory999/oci-policy-analysis/releases). After launch, use **Settings** to choose live OCI, a cache, or CIS Compliance output; then continue with the [usage guide](usage.md).

For a source checkout, optional helpers create or reuse the environment and run desktop mode: `./local-build.sh --mode desktop` and `./local-run.sh --mode desktop` on macOS/Linux, or `./local-build.ps1 --mode desktop` and `./local-run.ps1 --mode desktop` in PowerShell.

### Optional AI chat (desktop only)

AI is not required for OCI Policy Analysis. The desktop application works without it; AI chat is an optional way to get additional context while reviewing policies and identities.

Use **Apply and Test GenAI Settings** in the desktop **Settings** tab to test the selected model. Model availability and supported capabilities vary by OCI region, model deployment, endpoint, compartment authorization, and authentication mode. The goal is a working chat response for the region and model you select.

The **Tested** column reports the result for the current application session. It is not a guarantee that the same model works in every region or configuration.

| Model / OCID | Region | Endpoint type | Auth mode | Date tested | Working chat | Notes |
|---|---|---|---|---|---|---|
| _Add model_ | | | | | | |

## Web application

Web mode has no Tkinter requirement.

```bash
python -m pip install "oci-policy-analysis[web]"
oci-policy-analysis-web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The server prints a runtime access key at startup; enter that key in the browser login modal. For a team deployment, bind to an appropriate interface, place the service behind TLS termination, and expose `GET /health` to the load balancer.

For a source checkout, use `pip install -e ".[web]"`. Optional helpers are `./local-build.sh --mode web` and `./local-run.sh --mode web --host 0.0.0.0 --port 8080` on macOS/Linux, with matching `local-build.ps1` and `local-run.ps1` PowerShell scripts. For a production/team deployment, terminate TLS at a load balancer or reverse proxy, target the application on port `8080` (or your selected port), health-check `GET /health`, and restrict direct backend access to the proxy.

## CLI

```bash
python -m pip install oci-policy-analysis
oci-policy-analysis-cli --help
```

Use the CLI for scripted live loads, cache use, CIS Compliance imports, filtering, and exports. See the [CLI guide](cli.md) for its command reference and examples.

## MCP server

```bash
python -m pip install "oci-policy-analysis[mcp]"
oci-policy-analysis-mcp --help
```

The standalone server supports local stdio and HTTP deployments. See the [MCP guide](mcp.md) for transports, client configuration, tool catalog, and OAuth.

## Containerized MCP on OCI Container Instances

Use this path to run the standalone MCP server privately in OCI with a resource principal. You need the OCI CLI, Docker, an OCIR repository, a private subnet with OCI API egress, and the resource-principal policy above.

### Build and push

```bash
export OCI_REGION=iad
export OCI_NAMESPACE=<object-storage-namespace>
export OCIR_REPO=oci-policy-analysis/mcp
export OCI_COMPARTMENT_OCID=<ocir-repository-compartment-ocid>
export OCIR_USERNAME='<oci-username>'
export OCIR_AUTH_TOKEN='<oci-auth-token>'
export IMAGE_TAG=mcp-container-001

./local-build-push-mcp-ocir.sh
```

### Deploy

```bash
export OCI_PROFILE=<deployment-profile>
export OCI_COMPARTMENT_OCID=<target-compartment-ocid>
export OCI_SUBNET_OCID=<private-subnet-ocid>
export OCI_IMAGE_URL=ocir.us-ashburn-1.oci.oraclecloud.com/<namespace>/<repo>:<tag>
export OCI_AD=<availability-domain>

./local-deploy-mcp-container-instance.sh
```

The image listens on port `8765` using streamable HTTP. Its environment variables are `MCP_AUTH_MODE` (`resource_principal`, `instance_principal`, `profile`, `cache`, or `session_token`), `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_LOG_LEVEL`, `MCP_RECURSIVE`, `MCP_SAVE_CACHE_AFTER_LOAD`, and `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH`. The deployment defaults to live data, resource-principal authentication, no cache save, and identity-domain search depth `1`; set `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH=2` when identity domains exist in child compartments. Confirm startup in the logs, then validate from a reachable host:

```bash
curl -sS http://<container-instance-private-ip>:8765/health
```

For a public or team endpoint, place an OCI Load Balancer or API Gateway in front of the private instance, use HTTPS, and health-check `/health`. To test locally before push, run `docker build -f Dockerfile.mcp -t opa-mcp:local .`, then `docker run --rm -p 8765:8765 opa-mcp:local` and request `http://127.0.0.1:8765/health`. OCI Container Instances require redeployment for runtime environment-variable changes. For OAuth, see the [MCP OAuth guide](mcp_oauth.md).

## Troubleshooting

- Confirm the virtual environment is active and Python is 3.12+.
- For desktop startup failures, verify `python -m tkinter` works.
- For web startup, confirm `pip install "oci-policy-analysis[web]"` completed and use the current runtime access key.
- For live loads, verify the chosen profile/principal and IAM policies above.
- For containerized MCP, check startup logs before troubleshooting client connectivity.
