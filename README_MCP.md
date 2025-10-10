# 🧠 OCI Policy Analysis MCP Server

This repository provides a **Model Context Protocol (MCP)** server exposing OCI IAM data (users, groups, dynamic groups, and policy analysis) as structured tools and resources consumable by **Claude**, **VS Code MCP**, or any MCP-compliant proxy client.

---

## ⚙️ Setup Overview

### Install
```bash
pip install -e .[mcp]
```

### Run Locally
```bash
python -m sec.mcp_server --profile DEFAULT --host 0.0.0.0 --port 8000
```
Or with Instance Principal on OCI:
```bash
python -m sec.mcp_server --instance-principal --host 0.0.0.0 --port 8000
```

### Connect via MCP Proxy
Claude or VS Code connect via a **proxy**, not directly.
```bash
mcp-proxy add oci-policy-analysis --url https://oci-policy-analysis-mcp.ocidemo.app/mcp
```

---

## 🧭 Architecture

```mermaid
flowchart LR
    subgraph Clients
        C1[Claude Desktop]:::client
        C2[VS Code MCP]:::client
    end

    subgraph Bridge["MCP Proxy Layer"]
        P1[mcp-proxy<br>(local or cloud)]:::proxy
    end

    subgraph OCI["OCI Cloud Environment"]
        LB[(OCI HTTPS Load Balancer)]:::lb
        S1[MCP Server<br>FastMCP + Instance Principal]:::server
        OCIDB[(OCI IAM / API Data)]:::oci
    end

    C1 -->|MCP JSON-RPC| P1
    C2 -->|MCP JSON-RPC| P1
    P1 -->|HTTPS 443| LB
    LB -->|TCP 8000| S1
    S1 -->|SDK Calls / Cached Data| OCIDB

    classDef client fill:#eaf2ff,stroke:#7ea6ff,stroke-width:2px;
    classDef proxy fill:#fff8e5,stroke:#ffcc00,stroke-width:2px;
    classDef server fill:#eaffea,stroke:#66cc66,stroke-width:2px;
    classDef lb fill:#f0f0f0,stroke:#aaa,stroke-width:2px;
    classDef oci fill:#f7e9ff,stroke:#a37aff,stroke-width:2px;
```

---

## 🔐 Secure Deployment on OCI

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

## ✅ Example Tools

| Tool | Description |
|------|--------------|
| `users://all` | List all users in tenancy |
| `groups://all` | List all IAM groups |
| `policies://filter` | Filter policy statements |
| `findings://invalid` | List invalid policy statements |

---

Mermaid diagrams render automatically on **GitHub**, **GitLab**, or in MkDocs/Furo using `pymdownx.mermaid`.

