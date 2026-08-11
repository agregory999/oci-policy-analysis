# MCP Server

This repository provides a **Model Context Protocol (MCP)** server exposing OCI IAM data (users, groups, dynamic groups, and policy analysis) as structured tools and resources consumable by **Claude**, **VS Code MCP**, or any MCP-compliant proxy client.

MCP Integration can be done in several ways, depending on the client or situation.  The following diagrams show how MCP can be used to expose OCI policy data.   [Python FastMCP](https://gofastmcp.com/getting-started/welcome) is used for each of these methods.

Here are the methods that OCI Policy Analysis supports for MCP:

1) Standalone MCP Server -- In this method, the MCP server loads live or cached tenancy IAM and Policy data, then uses FastMCP to stand up an MCP Server.  This works in 2 possible ways:

    - If using FastMCP and STDIO, it is expected to be called from a calling process.
    - If using Streamable HTTP, the server can be invoked via any MCP Client supporting HTTP.  More details below

2) Embedded MCP Server -- In this method, the OCI Policy Analysis UI is used.  From the UI, the data is loaded from a tenancy or cache.  Then the UI tab "Embedded MCP Server" controls an HTTP-based server which is invoked from desktop MCP tools.

In the case of the standalone MCP Server, command line options are available, which control where to load the data from.  For example, to load data from a specific OCI Profile or from a local cache.  Also, there is a a switch to control STDIO or Streamable HTTP

## MCP Architectures

Many popular MCP tools allow a sub-process to run, using the STDIO mechanism.  Others expect you to have an MCP Server running and they will connect.  Both architectures are shown here:

### MCP via STDIO:

MCP Clients start the subprocess for MCP, and it loads its data, runs as an embedded python process, and the client sends and receives over Standard IO.

```mermaid
flowchart LR
    subgraph CLIENT["Client Machine"]
        C1[Claude Desktop or<br/>VS Code Copilot]
        MCP[MCP Server<br/>FastMCP STDIO]
        CACHE[Local Cache]
    end

    subgraph OCI["OCI Cloud"]
        OCI-API[OCI IAM API]
    end

    C1 -->|JSON-RPC STDIO| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Load via SDK Profile| OCI-API

    %% Styles
    style C1 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style OCI-API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

### MCP as HTTP (Remote Server):

Desktop tools such as VSCode and Claude can consume MCP endpoints running locally or remotely on a secure port.

```mermaid
flowchart LR
    subgraph CLIENT["Client Machine"]
        C1[Claude Desktop or<br/>VS Code Copilot]
        PROXY[mcp-proxy]
    end

    subgraph SERVER["Remote Server"]
        MCP[MCP Server<br/>FastMCP HTTP]
        CACHE[Cache or<br/>Instance Principal]
    end

    subgraph OCI["OCI Cloud"]
        OCI-API[OCI IAM API]
    end

    C1 -->|JSON-RPC| PROXY
    PROXY -->|HTTP/HTTPS| MCP
    MCP -->|Reads| CACHE
    MCP -.->|Load via SDK<br/>Profile or Instance Principal| OCI-API

    %% Styles
    style C1 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style PROXY fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style OCI-API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

## Running MCP from OCI Policy Analysis

## Core-Only Install for MCP (No Web/Desktop Extras)

For standalone MCP usage where you only need core + MCP runtime (and not the
desktop UI or web server), install from source using the base package:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Then run MCP directly:

```bash
python -m oci_policy_analysis.mcp_server --help
```

This keeps installation minimal while still enabling STDIO and streamable-HTTP
MCP modes documented below.

MCP Servers have 2 basic modes: STDIO and Streamable-HTTP.  STDIO mode is good for embedding in an AI Desktop client such as Claude, Oracle Code Assist, or VSCode.  More details on setups later on in the document.

Streamable HTTP is good for a server, where MCP is not local to the client, or in the OCI Policy Analysis Embedded MCP tab, the clients connect to the app over HTTP on the configured port.

In either case, the OCI Policy Analysis tool has a handful of options that can be applied.  See the usage for details:

```bash
usage: mcp_server.py [-h] (--profile PROFILE | --instance-principal | --resource-principal | --use-cache USE_CACHE | --session-token SESSION_TOKEN) [--recursive] [--dont-save-cache-after-load] [--transport {stdio,streamable-http}] [--port PORT] [--host HOST] [--compartment-domain-search-depth [1-6]] [--log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG,critical,error,warning,info,debug}]

options:
  -h, --help            show this help message and exit
  --profile PROFILE
  --instance-principal
  --resource-principal
  --use-cache USE_CACHE
                        provide the combined cache date to use
  --session-token SESSION_TOKEN
                        OCI session token for instance principal auth
  --recursive           Recursively load all compartments (default: True)
  --dont-save-cache-after-load
                        Dont save the combined cache after loading from OCI
  --transport {stdio,streamable-http}
  --port PORT
  --host HOST
  --compartment-domain-search-depth [1-6]
                        Depth for identity-domain compartment traversal (1=root only, 2=include direct children, max=6).
  --log-level {CRITICAL,ERROR,WARNING,INFO,DEBUG,critical,error,warning,info,debug}
                        Logging level. INFO logs MCP tool calls with full input and truncated output.
  ```

The options listed below cover the supported configurations.

When testing client-generated filters, start the MCP server with `--log-level INFO`. The server logs each tool call as `input(full)` and `output(truncated)`, with output capped for readability. Use `--log-level WARNING` for normal operation without tool payload logging.

(finding-the-available-caches)=
### Finding the Available Caches

If you want to use an existing cache from OCI Policy Analysis, for example, after having run the UI and loading data from any tenancy, you can use the command line first, to show the named caches available by tenancy and date of data load:

You can use the CLI to show caches for a given tenancy.  Ensure that the application is built locally first, and that the correct virtual environment is loaded:
```
agregory@agregory-mac ~ % python -m oci_policy_analysis.cli --get-caches andgre5678

2025-12-04 16:32:48,895 [INFO] [root] Root logger initialized (stdout + app.log).
2025-12-04 16:32:49,006 [INFO] [oci-policy-analysis.reference_data_repo] Loading reference data from directory: /Users/agregory/oci-policy-analysis/.venv/lib/python3.12/site-packages/oci_policy_analysis/logic/permissions
2025-12-04 16:32:49,008 [INFO] [oci-policy-analysis.reference_data_repo] Loaded 23 reference data files. Total resources: 303, families: 46
2025-12-04 16:32:49,339 [INFO] [oci-policy-analysis.reference_data_repo] Loading reference data from directory: /Users/agregory/oci-policy-analysis/.venv/lib/python3.12/site-packages/oci_policy_analysis/logic/permissions
2025-12-04 16:32:49,341 [INFO] [oci-policy-analysis.reference_data_repo] Loaded 23 reference data files. Total resources: 303, families: 46
<frozen runpy>:128: RuntimeWarning: 'oci_policy_analysis.cli' found in sys.modules after import of package 'oci_policy_analysis', but prior to execution of 'oci_policy_analysis.cli'; this may result in unpredictable behaviour
2025-12-04 16:32:49,341 [INFO] [oci-policy-analysis.cli] Logging to Console
2025-12-04 16:32:49,341 [INFO] [oci-policy-analysis.data_repo] Initialized PolicyAnalysisRepo
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.caching] Initialized Caching at /Users/agregory/.oci-policy-analysis/cache
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.caching] Entries found in cache_entries.json: 11
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] Available caches:
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-03-23-56-50-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-03-23-56-04-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-03-23-53-40-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-03-23-49-04-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-03-14-15-24-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-12-02-19-04-53-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-11-26-16-43-15-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-11-26-16-40-46-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-11-26-15-19-59-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-11-26-15-04-29-UTC
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] andgre5678_2025-11-26-saved
2025-12-04 16:32:49,342 [INFO] [oci-policy-analysis.cli] Exiting after listing caches as --get-caches was provided
``` 

With the cache name and date (for example, `andgre5678_2025-12-03-23-56-50-UTC`), you can set up MCP within the Claude or VSCode config file.

### MCP Option 1 - Locally with STDIO and Claude

In order to use Claude with MCP, you update a file called `claude_desktop_config.json` and simply restart Claude after changes.  To add the MCP server using STDIO mode, you likely want to start with a cached copy of the tenancy data, from a previous run from the UI or CLI, where the cache file exists.  See [above](#finding-the-available-caches) for more details on getting the cache name.

Claude Desktop and MCP over STDIO Architecture:

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        CD[Claude Desktop]
        MCP[MCP Server STDIO]
        CACHE[Local Cache]
    end

    subgraph OCI["OCI Cloud"]
        API[OCI IAM API]
    end

    CD -->|JSON-RPC STDIO| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Load via SDK<br/>Profile or Session Token| API

    style CD fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

Following are 2 examples.

#### Flavor 1 - Cached Data
```json
{
  "mcpServers": {
    "oci-policy-local": {
      "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
      "args": [
        "-m",
        "oci_policy_analysis.mcp_server",
        "--use-cache",
        "andgre5678_2025-12-03-23-56-50-UTC"
      ],
      "env": {
        "MCP_STDIO_MODE": "1"
      },
      "type": "stdio"
    }
  }
}
```
#### Flavor 2 - Load Data via SDK (Live)

**Hint** Your `YOUR-OCI-NAMED-PROFILE` may be `DEFAULT` if that is the only profile on your machine.
```json
{
  "mcpServers": {
    "oci-policy-local": {
      "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
      "args": [
        "-m",
        "oci_policy_analysis.mcp_server",
        "--profile",
        "YOUR-OCI-NAMED-PROFILE"
      ],
      "env": {
        "MCP_STDIO_MODE": "1"
      },
      "type": "stdio"
    }
  }
}
```

**NOTE** If you want to load live tenancy data but NOT create a new cache each time, add in the `--dont-save-cache-after-load` flag on a new line in the configuration above.

When Claude starts it will automatically run the code from your locally built application, assuming you set up a virtual environment similar to the path above.

### MCP Option 2 - Streamable HTTP and Claude

In this model, Claude requires an installed [MCP Proxy](https://github.com/sparfenyuk/mcp-proxy) on your machine.  The MCP Server can be started as a standalone Python process or from the OCI Policy Analysis UI with the Embedded MCP tab.  Either way, it will be listening on host:port and then the MCP Proxy connects to it.

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        CD[Claude Desktop]
        PROXY[mcp-proxy]
    end

    subgraph SERVER["Server (Local or Remote)"]
        MCP[MCP Server HTTP]
        CACHE[Local Cache]
    end

    subgraph OCI["OCI Cloud"]
        API[OCI IAM API]
    end

    CD -->|JSON-RPC| PROXY
    PROXY -->|HTTP/HTTPS| MCP
    MCP -->|Reads| CACHE
    MCP -.->|Load via SDK<br/>Profile or Instance Principal| API

    style CD fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style PROXY fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5

```

In this model, the MCP server is standalone.  It could be on your computer, using the MCP Server standalone server, or via the embedded MCP tab in the OCI Policy Analysis UI.  Either way, configure Claude like this:

```json
{
  "mcpServers": {
    "mcp-remote": {
      "command": "mcp-proxy",
      "args": [
        "http://url-or-ip:port/mcp"
      ]
    }
  }
}
```
When you start Claude, it will connect if your MCP is running at the given location.  Any time you restart the MCP server, simply close and reopen Claude to re-establish the connection.

### MCP Option 3 - VSCode Co-Pilot and STDIO (Local)

VSCode Configuration is similar to, but different from Claude.  The architecture for STDIO is very similar:

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        VSC[VS Code<br/>GitHub Copilot]
        MCP[MCP Server STDIO]
        CACHE[Local Cache]
    end

    subgraph OCI["OCI Cloud"]
        API[OCI IAM API]
    end

    VSC -->|JSON-RPC STDIO| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Load via SDK Calls| API

    style VSC fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

#### Flavor 1 - Cached Data

Use the command line to get the [name of the cache](#finding-the-available-caches) to use.  Then configure VSCode to add it to the startup command.

```json
    "mcp-local-stdio": {
        "type": "stdio",
        "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
        "env": {
            "MCP_STDIO_MODE": "1"
        },
        "args": [
            "-m",
            "oci_policy_analysis.mcp_server.",
            "--use-cache",
            "tenancy_2025-10-29-16-52-22-UTC"
        ]
    }
```

VSCode logs and output should show communication with MCP.

#### Flavor 2 - Load via OCI SDK (Live Data)

Without the cache, it will connect to the tenancy and load the data.

```json
		"mcp-local-stdio-live": {
			"type": "stdio",
			"command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
			"env": {
				"MCP_STDIO_MODE": "1"
			},
			"args": [
        "-m"
				"oci_policy_analysis.mcp_server",
				"--profile",
				"POLICY-ANDGRE-5678"
			]
		}
```
If it starts, you will something like this in the VSCode Output:
```
2025-10-29 20:06:33.711 [warning] [server stderr] 2025-10-29 20:06:33,710 [INFO] [root] Root logger initialized (stdout + app.log).
2025-10-29 20:06:33.912 [warning] [server stderr] 2025-10-29 20:06:33,911 [INFO] [oci.circuit_breaker] Default Auth client Circuit breaker strategy enabled
2025-10-29 20:06:34.835 [info] Discovered 6 tools
```

### MCP Option 4 - VSCode Remote HTTP

VSCode will also connect to any running MCP server, and does not need the MCP Proxy that Claude requires.  Simply connect to the running MCP Server, either running Standalone or Embedded within the UI.

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        VSC[VS Code<br/>GitHub Copilot]
    end

    subgraph SERVER["Server (Local or Remote)"]
        MCP[MCP Server HTTP]
        CACHE[Local Cache]
    end

    subgraph OCI["OCI Cloud"]
        API[OCI IAM API]
    end

    VSC -->|HTTPS| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Load via SDK<br/>Profile or Session Token| API

    style VSC fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5

```

In this case, your MCP server is already running like above, on your PC or on a remote server, or in the OCI Policy Analysis tool in the embedded MCP tab.  The host and port are available and open for connections. 

Set up VSCode for a remote MCP Server:
```
    "mcp-policy-remote": {
        "url": "https://mcp-host:port/mcp",
        "type": "http"
    }
```

### MCP Option 5 - Remote OCI Deployment with Load Balancer

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        CLIENT[Claude Desktop or<br/>VS Code Copilot]
        PROXY[mcp-proxy]
    end

    subgraph OCI_INFRA["OCI Infrastructure"]
        LB[Load Balancer<br/>HTTPS:443]
        
        subgraph COMPUTE["Compute Instance"]
            MCP[MCP Server HTTP:8765]
            CACHE[Local Cache]
        end
    end

    subgraph OCI_SERVICES["OCI Services"]
        API[OCI IAM API]
    end

    CLIENT -->|JSON-RPC| PROXY
    PROXY -->|HTTPS:443| LB
    LB -->|HTTP:8765| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|SDK Calls| API

    style CLIENT fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style PROXY fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style LB fill:#ffddaa,stroke:#ff9944,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px
```

In this production deployment, the MCP server runs on an OCI compute instance with instance principal authentication, behind an OCI Load Balancer with TLS termination. This provides secure, scalable access to OCI IAM data without storing credentials.

For OCI Container Instance deployment (OCIR image + private subnet + instance principal default runtime), follow:

- [Containerized MCP on OCI Container Instances](setup.md#containerized-mcp-on-oci-container-instances)

**Configuration for Claude:**
```json
{
  "mcpServers": {
    "mcp-remote": {
      "command": "mcp-proxy",
      "args": [
        "https://oci-policy-analysis-mcp.ocidemo.app/mcp"
      ]
    }
  }
}
```

**Configuration for VSCode:**
```json
{
  "servers": {
    "mcp-policy-remote": {
      "url": "https://oci-policy-analysis-mcp.ocidemo.app/mcp",
      "type": "http"
    }
  }
}
```

## Setup for MCP Locally or on a Server

Running locally allows you to build OCI Policy Analysis, connect to live or cached data, and avoid using the UI.  Similar to the CLI, you can run with a cached data set or load the tenancy.  For this way of running, STDIO doesn't make sense, as you are expecting a client to access via HTTP.  

Example 5 above talks about running on a server with a load balancer.  You can use the method described here to run OCI Policy Analysis on an OCI Virtual Machine with Instance Principal, and then expose using a Load Balancer.  Then desktop clients can connect MCP tools with stopping and starting the server.

### Load the tenancy via PROFILE
```bash
python  -m oci_policy_analysis.mcp_server --profile DEFAULT --transport streamable-http --host 0.0.0.0
```

### Load the tenancy via Instance Principal
```bash
python -m oci_policy_analysis.mcp_server --instance-principal --transport streamable-http --host 0.0.0.0
```

### Load the tenancy via Resource Principal
```bash
python -m oci_policy_analysis.mcp_server --resource-principal --transport streamable-http --host 0.0.0.0
```

### Using Cached Data
```bash
python -m oci_policy_analysis.mcp_server --use-cache andgre5678_2025-10-17-17-54-09-UTC --transport streamable-http --host 0.0.0.0
```

### Adding OCI Load Balancer
To run behind a Load Balancer on a server, see above first.  Following that, In your VCN's public subnet, run a standard Layer 7 Load Balancer, listening on port 443 (HTTPS) with health check and backend set with your private host and port (default 8765).  Once the LB is up, point Claude or VSCode (option 2 or 4 above) to the LB's public domain and port - below there is a cert running on the LB, so the https address and cert are valid.  But it points to the MCP server on the backend.

```bash
mcp-proxy add oci-policy-analysis --url https://oci-policy-analysis-mcp.ocidemo.app/mcp
```

## Secure Deployment on OCI (Outline Steps)

1. Deploy Compute Instance (OL9, Instance Principal)
2. Configure Dynamic Group and Policy:
   ```text
   Allow dynamic-group my-mcp-dg to read all-resources in tenancy
   ```
3. Launch service behind OCI Load Balancer (port 443 → 8000)
4. Add TLS (Let’s Encrypt or OCI Certificate)
5. Verify endpoint:
   ```bash
   curl -vk https://oci-policy-analysis-mcp.ocidemo.app/mcp
   ```

## OCI Container Instance Deployment

For a containerized standalone MCP deployment on OCI:

1. Build image using `Dockerfile.mcp`
2. Push image to OCIR
3. Deploy OCI Container Instance in private subnet
4. Run with defaults:
   - `MCP_AUTH_MODE=resource_principal`
   - `MCP_TRANSPORT=streamable-http`
   - `MCP_HOST=0.0.0.0`
   - `MCP_PORT=8765`
   - `MCP_LOG_LEVEL=INFO`
   - `MCP_SAVE_CACHE_AFTER_LOAD=false`
   - `MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH=1` (use `2` when identity domains are in child compartments)

Full procedure:

- [Containerized MCP on OCI Container Instances](setup.md#containerized-mcp-on-oci-container-instances)

## Available MCP Tools

For the OKE workload identity tool and advanced principal filter shape, see [OKE Workload Identity Querying](./oke_workload_identity.md). The top-level [Usage](./usage.md) guide explains where MCP sits relative to the UI tabs and advanced filters.

MCP clients choose tools from concise descriptions and JSON schemas. The server keeps tool schemas intentionally small; full examples and response notes live here instead of in the tool description payload.

### Tool Schema Token Metrics

The packaged MCP schema is intentionally compact. Measured against `src/oci_policy_analysis/application/core/resources/mcp_tools_list/mcp_tools.json`:

| Encoding | Total Tokens |
|----------|--------------|
| `o200k_base` | 1,310 |
| `cl100k_base` | 1,308 |

Per-tool schema footprint using `o200k_base`:

| Tool | Total | Description | Input Schema | Output Schema |
|------|------:|------------:|-------------:|--------------:|
| `policy_search` | 153 | 14 | 108 | 12 |
| `policy_search_set` | 170 | 8 | 130 | 12 |
| `policy_history_search` | 202 | 11 | 159 | 12 |
| `identity_search` | 466 | 9 | 426 | 12 |
| `data_operations` | 125 | 16 | 78 | 12 |
| `cross_tenancy_search` | 166 | 10 | 122 | 12 |

### Example Natural Language Queries

| User Question | Tool Used | Example Request |
|--------------|-----------|-----------------|
| "Show all users in the tenancy" | `identity_search` | `{ "entity_types": ["user"] }` |
| "Find all groups with 'admin' in the name" | `identity_search` | `{ "entity_types": ["group"], "name": ["admin"] }` |
| "Resolve this compartment OCID to a path" | `identity_search` | `{ "entity_types": ["compartment"], "ocid": ["ocid1.compartment.oc1..example"] }` |
| "Which policies allow manage on databases?" | `policy_search` | `{ "mode": "simple", "detail_level": "summary", "filters": { "verb": ["manage"], "resource": ["database"] } }` |
| "List all users in group 'cloud-engineering-domain-users'" | `identity_search` | `{ "operation": "members_for_group", "entity_types": ["user"], "name": ["cloud-engineering-domain-users"], "domain_name": ["cloud-engineering-domain"] }` |
| "Show cross-tenancy aliases" | `cross_tenancy_search` | `{ "operation": "list_aliases" }` |
| "Show policies for the Default Administrators group principal" | `policy_search` | `{ "mode": "simple", "filters": { "principal": { "principal_type": "group", "domain_name": "Default", "name": "Administrators" } } }` |
| "Find resource-principal policies for container instances" | `policy_search` | `{ "mode": "advanced", "detail_level": "full", "filters": { "principal": { "principal_type": "resource-principal", "resource_type": "containerinstance" } } }` |
| "Validate all policy pieces for this product install" | `policy_search_set` | `{ "intent": "install_validation", "searches": [...] }` |
| "Compare this search with last month's cache" | `policy_history_search` | `{ "query_type": "single", "query": {...}, "left": {"source": "as_of", "as_of": "2026-05-15T00:00:00Z"}, "right": {"source": "current"} }` |
| "List available caches" | `data_operations` | `{ "operation": "list_caches", "tenancy_name": "andgre5678" }` |
| "Reload live data" | `data_operations` | `{ "operation": "reload" }` |

---

The OCI Policy Analysis MCP Server exposes the following tools for querying OCI IAM data:

### policy_search
Primary policy-analysis tool. Use it for one statement search.

Common inputs:

- `mode`: `simple` for common statement filters, `advanced` for workload principals, parsed condition evidence, and tag-aware searches.
- `detail_level`: `summary`, `simple`, or `full`.
- `filters`: action, verb, resource, permission, subject type, policy name, compartment path, effective path, location, comments, condition text, validity, principal selectors, and raw statement text.
- `limit`: maximum returned rows.

Use structured `principal` filters for human, service, dynamic-group, instance-principal, and resource-principal lookups. Advanced workload-principal results can include `principal_evidence`, `condition_atoms`, `dynamic_group_rule_evidence`, `residual_conditions`, `resolved_compartments`, `match_confidence`, and `match_confidence_reason`.

Parsed tag filters are also supported: `tag_access_type`, `tag_access_semantics`, `tag_namespace`, `tag_key`, `tag_value`, `tag_operator`, `condition_atom_terms`, `policy_tag`, `policy_defined_tag`, and `policy_freeform_tag`. Advanced/full responses include `tag_conditions` and `tag_context_warnings`.

Example:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "resource-principal",
      "resource_type": "containerinstance",
      "compartment_ocid": "ocid1.compartment.oc1..app"
    },
    "resource": ["repos"]
  },
  "limit": 25
}
```

### tag_based_policy_search
Runs a guided parsed tag-condition search. It accepts the parsed tag filters above plus common policy filters such as `verb`, `resource`, `permission`, `principal_keys`, and `effective_path`. See [Tag-Based Policy Search](tag_based.md) for examples.

### policy_search_set
Runs multiple related policy searches and returns a conservative set summary. Use this for install validation, service enablement checks, or any workflow that needs human, service, and workload principal coverage together.

Each search has a `search_id`, label, optional `required` flag, and an embedded `policy_search` query. The result includes per-search counts plus `missing_required_searches`, `missing_or_ambiguous_items`, `likely_ready`, and set-level confidence.

### policy_history_search
Runs a single policy search or policy search set against two snapshots and compares the results. Use `left` and `right` snapshot selectors such as `current`, `cache`, or `as_of`, then choose a `diff_mode` such as statement identity comparison.

### identity_search
Consolidated identity lookup for users, groups, dynamic groups, and compartments.

Supported patterns:

- Search users, groups, dynamic groups, and compartments by `name`, `domain_name`, or `ocid`.
- Search dynamic groups by `matching_rule` or `in_use`.
- Resolve compartment OCIDs to names and paths.
- Fetch groups for an exact user with `operation: "groups_for_user"`.
- Fetch users for an exact group with `operation: "members_for_group"`.

Examples:

```json
{
  "entity_types": ["compartment"],
  "ocid": ["ocid1.compartment.oc1..app"],
  "limit": 10
}
```

```json
{
  "operation": "members_for_group",
  "entity_types": ["user"],
  "name": ["Administrators"],
  "domain_name": ["Default"]
}
```

### data_operations
Operational tool for cache and live-data actions.

Supported operations:

- `list_caches`: list available combined caches, optionally filtered by tenancy name.
- `cache_metadata`: inspect cache metadata.
- `reload`: reload live OCI policy and identity data through the same load service used by the main app.

`reload` requires a server started with profile, instance principal, resource principal, or session-token auth. It is not available for cache-only runs. Unless the server was started with `--dont-save-cache-after-load`, reload also writes a new combined cache.

### cross_tenancy_search
Cross-tenancy lookup tool.

Supported operations:

- `list_aliases`: list loaded cross-tenancy alias definitions.
- `policies_by_alias`: filter cross-tenancy policy statements that reference an alias.

Example:

```json
{
  "operation": "policies_by_alias",
  "alias": "partner-tenancy"
}
```

---

## Usage Tips

1. **Start broad, then filter**: Begin with empty filters `{}` to get summaries, then add specific criteria
2. **Combine filters**: Use multiple fields together (AND logic across fields, OR within fields)
3. **Use identity search first**: Find users, groups, dynamic groups, or compartments, then pass structured principal or compartment values to `policy_search`
4. **Use advanced mode for workload principals**: This surfaces confidence, residual conditions, dynamic group rule evidence, and resolved compartments
5. **Use search sets for product checks**: A set keeps related human, service, and workload searches together and reports missing or ambiguous items
6. **Use INFO logging while testing clients**: `--log-level INFO` logs full inputs and truncated outputs for every MCP tool call
