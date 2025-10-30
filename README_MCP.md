# OCI Policy Analysis MCP Server

This repository provides a **Model Context Protocol (MCP)** server exposing OCI IAM data (users, groups, dynamic groups, and policy analysis) as structured tools and resources consumable by **Claude**, **VS Code MCP**, or any MCP-compliant proxy client.

---

## ⚙️ Setup Overview

### Install
```bash
pip install -e .[mcp]
```

## MCP Architecture Diagrams

Mermaid diagrams render automatically on **GitHub**, **GitLab**, or in MkDocs/Furo using `pymdownx.mermaid`.


Locally (STDIO):
```mermaid
flowchart LR
    subgraph CLIENT["Client Machine"]
        C1[Claude Desktop]
        C2[VS Code Co-Pilot]
        P1[mcp-proxy local]
        S1[MCP Server FastMCP]
    end

    subgraph OCI["OCI Cloud"]
        OCI-API[(OCI IAM and API Data)]
    end

    C1 -->|MCP JSON-RPC| P1
    C2 -->|MCP JSON-RPC| P1
    P1 -->|MCP Server STDIO| S1
    S1 -->|SDK Calls via<br/>Profile or Session token| OCI-API

    %% Styles
    style C1 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style C2 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style P1 fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style OCI fill:#f7e9ff,stroke:#a37aff,stroke-width:2px
```

For a Server-based architecture on OCI, this looks like
```mermaid
flowchart LR
    subgraph CLIENT["Client Machine"]
        C1[Claude Desktop]
        C2[VS Code MCP]
        P1[mcp-proxy remote]
    end

    subgraph SERVER["OCI LB / Instance / MCP Server"]
        LB[(OCI HTTPS Load Balancer)]
        S1[MCP Server FastMCP]
    end

    subgraph OCI["OCI Cloud"]
        OCI-API[(OCI IAM and API Data)]
    end

    C1 -->|MCP JSON-RPC| P1
    C2 -->|MCP JSON-RPC| P1
    P1 -->|HTTPS 443| LB
    LB -->|HTTP 8765| S1
    S1 -->|SDK Calls via IP| OCI-API

    %% Styles
    style C1 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style C2 fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style P1 fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style S1 fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style LB fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style OCI fill:#f7e9ff,stroke:#a37aff,stroke-width:2px

```

---

## Running MCP

MCP Servers have 2 basic modes: STDIO and Streamable-HTTP.  STDIO mode is good for embedding in an AI Desktop client such as Claude, Oracle Code Assist, or VSCode.  More details on setups later on in the document.

Streamable HTTP is good for a server, where MCP is not local to the client, or in the OCI Policy Analysis Embedded MCP tab, the clients connect to the app over HTTP on the configured port.

In either case, the OCI Policy Analysis tool has a handful of options that can be applied.  See the usage for details:
```bash
usage: mcp_server.py [-h] (--profile PROFILE | --instance-principal | --use-cache USE_CACHE | --session-token SESSION_TOKEN) [--recursive] [--transport {stdio,streamable-http}] [--port PORT]
                     [--host HOST]

options:
  -h, --help            show this help message and exit
  --profile PROFILE
  --instance-principal
  --use-cache USE_CACHE
                        provide the combined cache date to use
  --session-token SESSION_TOKEN
                        OCI session token for instance principal auth
  --recursive           Recursively load all compartments (default: True)
  --transport {stdio,streamable-http}
  --port PORT
  --host HOST
  ```


### MCP Option 1 - Locally with STDIO and Claude

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        CD[Claude Desktop]
        MCP[MCP Server STDIO]
        CACHE[(Local Cache or<br/>OCI Profile)]
    end

    subgraph OCI["OCI Cloud (Optional)"]
        API[(OCI IAM API)]
    end

    CD -->|JSON-RPC STDIO| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Live: SDK Calls| API

    style CD fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

In order to use Claude with MCP, you update a file called `claude_desktop_config.json` and simply restart Claude after changes.  To add the MCP server using STDIO mode, you likely want to start with a cached copy of the tenancy data, from a previous run from the UI or CLI, where the cache file exists.  

You can use the CLI to show caches for a given tenancy:
```
agregory@agregory-mac ~ % MCP_STDIO_MODE=1 /Users/agregory/oci-policy-analysis/.venv/bin/python /Users/agregory/oci-policy-analysis/src/oci_policy_analysis/cli.py --get-caches naceoci01
2025-10-29 16:10:45,260 [INFO] [root] Root logger initialized (stdout + app.log).
2025-10-29 16:10:45,385 [INFO] [oci.circuit_breaker] Default Auth client Circuit breaker strategy enabled
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] Logging to Console
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.data_repo] Initialized PolicyAnalysisRepo
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.caching] Initialized Caching at /Users/agregory/.oci-policy-analysis/cache
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.caching] Successfully loaded cache with 7 entries
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.caching] Entries found in cache_entries.json: 4
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] Available caches:
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] naceoci01_2025-10-29-16-52-22-UTC
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] naceoci01_2025-10-29-12-14-47-UTC
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] naceoci01_2025-10-28-20-30-55-UTC
2025-10-29 16:10:45,540 [INFO] [oci-policy-analysis.cli] naceoci01_2025-10-28-19-26-08-UTC
2025-10-29 16:10:45,541 [INFO] [oci-policy-analysis.cli] Exiting after listing caches as --get-caches was provided
``` 

With the cache name and date (for example, `naceoci01_2025-10-28-19-26-08-UTC`), set up MCP within the Claude config file.

#### Flavor 1 - Cached Data
```json
{
  "mcpServers": {
    "oci-policy-local": {
      "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
      "args": [
        "/Users/agregory/oci-policy-analysis/src/oci_policy_analysis/mcp_server.py",
        "--use-cache",
        "tenancy_2025-10-29-16-52-22-UTC"
      ],
      "env": {
        "MCP_STDIO_MODE": "1"
      },
      "type": "stdio"
    }
  }
}
```
#### Flavor 2 - Live Data

**Hint** Your `YOUR-OCI-NAMED-PROFILE` may be `DEFAULT` if that is the only profile on your machine.
```json
{
  "mcpServers": {
    "oci-policy-local": {
      "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
      "args": [
        "/Users/agregory/oci-policy-analysis/src/oci_policy_analysis/mcp_server.py",
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

When Claude starts it will automatically run the code from your local git repo, assuming you set up a virtual environment similar to the path above.

### MCP Option 2 - Streamable HTTP and Claude

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        CD[Claude Desktop]
        PROXY[mcp-proxy]
    end

    subgraph SERVER["Server (Local or Remote)"]
        MCP[MCP Server HTTP]
        DATA[(Cache or<br/>OCI Profile or<br/>Instance Principal)]
    end

    subgraph OCI["OCI Cloud (Optional)"]
        API[(OCI IAM API)]
    end

    CD -->|JSON-RPC| PROXY
    PROXY -->|HTTP/HTTPS| MCP
    MCP -->|Reads| DATA
    MCP -.->|Live: SDK Calls| API

    style CD fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style PROXY fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style DATA fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

In this model, the MCP server is standalone.  It could be on your computer, using the MCP Server standalone server, or via the embedded MCP tab in the OCI Policy Analysis UI.  Or it could be on a remote server, such as an OCI compute server with instance principals, hosting the MCP Server and exposing it via an OCI Load Balancer.  Either way, configure Claude like this:

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
When you start Claude, it will conenct if your MCP is running

### MCP Option 3 - VSCode Co-Pilot and STDIO (Local)

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        VSC[VS Code<br/>GitHub Copilot]
        MCP[MCP Server STDIO]
        CACHE[(Local Cache or<br/>OCI Profile)]
    end

    subgraph OCI["OCI Cloud (Optional)"]
        API[(OCI IAM API)]
    end

    VSC -->|JSON-RPC STDIO| MCP
    MCP -->|Reads Cache| CACHE
    MCP -.->|Live: SDK Calls| API

    style VSC fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style CACHE fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

Similar to Claude, VSCode will start your MCP standalone process and communicate directly with it.  To set this up, follow VSCode MCP Server setup and use the full command that you can test ahead of time:
```
full command
```

When done, you will have an mcp.json file with the configuration that you can try to start:

#### Flavor 1 - Cached
```json
    "mcp-local-stdio": {
        "type": "stdio",
        "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
        "env": {
            "MCP_STDIO_MODE": "1"
        },
        "args": [
            "/Users/agregory/oci-policy-analysis/src/oci_policy_analysis/mcp_server.py",
            "--use-cache",
            "tenancy_2025-10-29-16-52-22-UTC"
        ]
    }
```
#### Flavor 2 - Live
```json
		"mcp-local-stdio-live": {
			"type": "stdio",
			"command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
			"env": {
				"MCP_STDIO_MODE": "1"
			},
			"args": [
				"/Users/agregory/oci-policy-analysis/src/oci_policy_analysis/mcp_server.py",
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

From there, use the chat and ask it a question like "Show me my OCI Policies that have a verb of manage"

### MCP Option 4 - VSCode Remote HTTP

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        VSC[VS Code<br/>GitHub Copilot]
    end

    subgraph SERVER["Server (Local or Remote)"]
        MCP[MCP Server HTTP]
        DATA[(Cache or<br/>OCI Profile or<br/>Instance Principal)]
    end

    subgraph OCI["OCI Cloud (Optional)"]
        LB[Load Balancer]
        API[(OCI IAM API)]
    end

    VSC -->|HTTPS| LB
    LB -->|HTTP| MCP
    MCP -->|Reads| DATA
    MCP -.->|Live: SDK Calls| API

    style VSC fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px
    style MCP fill:#eaffea,stroke:#66cc66,stroke-width:2px
    style DATA fill:#f0f0f0,stroke:#aaa,stroke-width:2px
    style LB fill:#fff8e5,stroke:#ffcc00,stroke-width:2px
    style API fill:#f7e9ff,stroke:#a37aff,stroke-width:2px,stroke-dasharray: 5 5
```

In this case, your MCP server is already running like above, on your PC, on an OCI server with Load Balancer, or in the OCI Policy Analysis tool in the embedded MCP tab.  The host and port are available and open for connections. 

Set up VSCode for a remote MCP Server:
```
    "mcp-policy-remote": {
        "url": "https://mcp-host:port/mcp",
        "type": "http"
    }
```

## Runing MCP Locally or on a Server

Running locally offers similar options, around loading of data, or using cached data.  Similar to the CLI, you can run with a cached data set or load the tenancy.  For this way of running, STDIO doesn't make sense, as you are expecting a client to access via HTTP.  

Load the tenancy via PROFILE:
```bash
python src/oci_policy_analysis/mcp_server.py --use-cache andgre5678_2025-10-17-17-54-09-UTC --transport streamable-http --host 0.0.0.0
```

Load the tenancy via Instance Principal:
```bash
python src/oci_policy_analysis/mcp_server.py --instance-principal --transport streamable-http --host 0.0.0.0
```

Use a cached data set from a previous load:
```bash
python src/oci_policy_analysis/mcp_server.py --use-cache andgre5678_2025-10-17-17-54-09-UTC --transport streamable-http --host 0.0.0.0
```

### Adding OCI Load Balancer
To run behind a Load Balancer on a server, see above.  Following that, In your VCN's public subnet, run a standard Layer 7 Load Balancer, listening on port 443 (HTTPS) with health check and backend set with your private host and port (default 8765).  Once the LB is up, point Claude or VSCode (option 2 or 4 above) to the LB's public domain and port - below there is a cert running on the LB, so the https address and cert are valid.  But it points to the MCP server on the backend.

```bash
mcp-proxy add oci-policy-analysis --url https://oci-policy-analysis-mcp.ocidemo.app/mcp
```


#### 🔐 Secure Deployment on OCI (Steps)

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

---

## 🔧 Available MCP Tools

The OCI Policy Analysis MCP Server exposes the following tools for querying OCI IAM data:

### 1. `filter_policy_statements`
**Primary tool for policy analysis** - Filter OCI IAM policy statements with flexible criteria.

**Features:**
- OR logic within each field, AND logic across fields
- Returns summary for large result sets (>50 statements), full details for smaller sets
- Supports exact matching and fuzzy search

**Filter Options:**
- `verb`: ["inspect", "read", "use", "manage"]
- `resource`: Resource types (e.g., "instance-family", "database")
- `subject_type`: ["user", "group", "dynamic-group", "any-user"]
- `subject`: Exact subject matches with domain and name
- `location`: Compartment paths where resources are accessed
- `policy_compartment`: Compartment where policy is defined (use "ROOTONLY" for root only)
- `policy_text`: Text search within statement
- `exact_groups`, `exact_users`, `exact_dynamic_groups`: Precise identity matching
- `search_groups`, `search_users`, `search_dynamic_groups`: Fuzzy search with partial matches

**Examples:**
```json
// Get all manage permissions
{"verb": ["manage"]}

// Find policies for specific group
{"exact_groups": [{"group_name": "Administrators", "domain_name": "Default"}]}

// Find database-related permissions with manage or use
{"verb": ["manage", "use"], "resource": ["database"]}

// Search for users by name
{"search_users": {"search": ["andrew", "bob"]}}
```

**Response Types:**
- **Summary** (>50 results): Counts, breakdowns by policy/compartment/subject/verb, sample statements
- **Full** (≤50 results): Complete list of matching policy statements

---

### 2. `search_users`
Search and retrieve OCI IAM users with optional filtering.

**Filter Options:**
- `search`: List of partial username/email strings (fuzzy match)
- `user_ocid`: List of full or partial user OCIDs
- `domain_name`: List of identity domain names

**Examples:**
```json
// Get all users
{}

// Search by username
{"search": ["andrew", "mark", "noah"]}

// Find users by OCID
{"user_ocid": ["ocid1.user.oc1..aaaaaa..."]}
```

**Response:**
- **Summary** (>50 users): Total count, domain breakdown, sample usernames
- **Full** (≤50 users): Complete user details with name, email, OCID, domain

---

### 3. `search_groups`
Search and retrieve OCI IAM groups.

**Filter Options:**
- `group_name`: List of partial group names (fuzzy match)
- `group_ocid`: List of full or partial group OCIDs
- `domain_name`: List of identity domain names

**Examples:**
```json
// Get all groups
{}

// Search by name
{"group_name": ["admin", "developer"]}

// Find specific groups by OCID
{"group_ocid": ["ocid1.group.oc1..aaaaaa...", "ocid1.group.oc1..bbbbbb..."]}

// Filter by domain
{"domain_name": ["Default", "cloud-engineering-domain"]}
```

**Response:**
- **Summary** (>50 groups): Total count, domain breakdown, sample group names
- **Full** (≤50 groups): Complete group details with name, OCID, domain, description

---

### 4. `search_dynamic_groups`
Search and retrieve OCI dynamic groups.

**Filter Options:**
- `dynamic_group_name`: List of partial dynamic group names (fuzzy match)
- `matching_rule`: List of partial matching rule strings
- `domain_name`: List of identity domain names

**Examples:**
```json
// Get all dynamic groups
{}

// Search by name
{"dynamic_group_name": ["compute", "function"]}

// Find by matching rule content
{"matching_rule": ["instance.compartment.id"]}
```

**Response:**
- **Summary** (>50 groups): Total count, domain breakdown, usage breakdown, samples
- **Full** (≤50 groups): Complete dynamic group details with rules and policy usage

---

### 5. `get_groups_for_user`
Get all groups that a specific user belongs to (exact match only).

**Input:**
```json
{
  "user_name": "andrew.gregory@oracle.com",
  "domain_name": "cloud-engineering-domain"
}
```

**Response:** List of all groups the user is a member of.

---

### 6. `get_users_for_group`
Get all users in a specific group (exact match only).

**Input:**
```json
{
  "group_name": "Administrators",
  "domain_name": "Default"
}
```

**Response:** List of all users who are members of the group.

---

### 7. `cross-tenancy-alias-list`
List all cross-tenancy aliases defined in OCI policies.

**Input:** None

**Response:** List of all DEFINE statements with tenancy OCIDs and aliases.

---

### 8. `cross-tenancy-policies-by-alias`
Filter cross-tenancy policy statements that reference a specific alias.

**Input:**
```json
{
  "alias": "partner-tenancy"
}
```

**Response:** List of policy statements using the specified cross-tenancy alias.

---

## 💡 Usage Tips

1. **Start broad, then filter**: Begin with empty filters `{}` to get summaries, then add specific criteria
2. **Combine filters**: Use multiple fields together (AND logic across fields, OR within fields)
3. **Use fuzzy search**: `search_users`, `search_groups` support partial string matching
4. **OCID filtering**: All `*_ocid` fields support partial OCID matching
5. **Check response type**: Large result sets return summaries - add filters to get full details

---

