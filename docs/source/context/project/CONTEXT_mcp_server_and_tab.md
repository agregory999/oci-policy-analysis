# Context: MCP Server and Embedded MCP Tab Integration

This context file documents how the MCP server (`mcp_server.py`) and the Embedded MCP Tab (`mcp_tab.py`) enable external Model Context Protocol (MCP) clients to directly query OCI Identity and Policies, expose post-analysis intelligence, and run policy simulations.

---

## 1. High-Level Architecture

- **MCP Server (`mcp_server.py`)**
  - Launches a [FastMCP](https://gofastmcp.com/getting-started/welcome) server exposing tools and resources for policy/identity/simulation queries.
  - Can run as a standalone process (with CLI, STDIO, or HTTP) or as an embedded server within the Policy Analysis UI (triggered by the Embedded MCP Tab).
  - Loads policy data, builds simulation engine, and exposes an extensible set of MCP tools reflecting the current state, intelligence overlays, and simulation capabilities.

- **Embedded MCP Tab (`mcp_tab.py`)**
  - UI component allowing the user to start/stop/control the MCP server without leaving the desktop application.
  - Displays live server logs and status, provides debug/monitoring controls.
  - When launching MCP, passes in the currently loaded policy repository, simulation engine, and analysis overlays, ensuring the server exposes in-memory state directly to external clients.

---

## 2. Tool Exposure and Data Sources

**Tools exposed by the MCP server can be grouped by their data/model source:**

### 2.1. Minimal Policy Intelligence Step on Load

Whenever the MCP server loads tenancy/policy data (from live OCI or from cache), it **always runs a post-load minimal policy intelligence suite** before exposing data to any tools or clients. This includes:

- Calculating all effective compartments for policy statements (`calculate_all_effective_compartments`)
- Validity checking and marking invalid policy statements (`find_invalid_statements`)
- Dynamic group in-use analysis (`run_dg_in_use_analysis`)

**Why this matters:**  
These overlays ensure that all MCP tools (e.g., policy filtering, group/user lookups, simulation scenarios) have access to up-to-date, derived data such as effective policy scopes, invalidity reasons, and active/inactive dynamic groups—even if the server loaded from a static cache. Logs will explicitly record this step, including elapsed analysis time and any exceptions.

**Extensibility:**  
Additional policy intelligence methods or analytics may be added to this post-load step as new overlays and tools are developed, ensuring a consistent data enhancement path for both core MCP server operations and future extensions.

---

- **Policy Set (PolicyAnalysisRepository)**
  - General IAM entity search: users, groups, dynamic groups.
  - Flexible policy statement filtering (`filter_policy_statements`), supporting exact/fuzzy identity and rich filtering criteria.
  - Cross-tenancy alias inspection, reference cache comparison, and reload tools.
- **Simulation Engine**
  - Tools for simulation setup and execution: `prepare_simulation`, `run_simulation_batch`.
  - Always computes applicable policies and "where" context according to canonical engine rules; no manual statement selection for MCP clients (see [MCP docs](../../../docs/source/mcp.md)).
- **Policy Intelligence/Overlay**
  - While not directly exposing all intelligence overlay analytics as top-level tools, policy-level tools can leverage intelligence (e.g., expose risk, overlap, or fix data via additional MCP endpoints as needed).
  - Designed for extensibility—new overlay tools can be added as feature needs grow.

---

## 3. MCP Server Access Modes

- **Standalone Mode:** Run as its own process, using STDIO or Streamable HTTP. Suitable for integration with Claude Desktop, VS Code, or remote/proxy clients.
- **Embedded/UI Mode:** Controlled via the Embedded MCP Tab in the Policy Analysis UI. Server exposes the in-app (live) state and can be managed and monitored directly from the GUI.

---

## 4. Refer to `mcp.md` for Tool Details

**For all tool API specifications, request/response schemas, filter logic, and practical usage tips, see:**  
[docs/source/mcp.md](../../../docs/source/mcp.md)

- `mcp.md` covers:
    - Architecture diagrams for STDIO/HTTP deployments (local, proxy, remote, load balancer)
    - The simulation flow, how context and required "where" variables are provided
    - Full inventory of available tools, with usage patterns, input/output contracts, and worked examples for each
    - Tips and scenarios for maximizing MCP utility from desktop, proxy, or remote deployments
    - Supported configuration/launch options for both standalone and embedded server operation

---

## 5. Extending the MCP Server

- **Adding new tools**: MCP tools can be registered to expose intelligence/overlays (risk, consolidation, policy fix suggestions), simulation flows (via the engine), or custom queries on the policy set. New analytics or actions should be documented here and in `mcp.md` prior to implementation.
- **UI-to-MCP integration**: The Embedded MCP Tab can be extended to monitor new server actions, display tool health/status, or even expose limited UI for tool-specific queries directly in the application.

---

## 6. References

- MCP Standalone/Embedded Server: [`src/oci_policy_analysis/mcp_server.py`](../../../src/oci_policy_analysis/mcp_server.py)
- Embedded MCP Tab (UI): [`src/oci_policy_analysis/ui/mcp_tab.py`](../../../src/oci_policy_analysis/ui/mcp_tab.py)
- Tool Inventory and Protocol Details: [`docs/source/mcp.md`](../../../docs/source/mcp.md)

---

**Summary:**  
The MCP server architecture (standalone or embedded via the MCP tab) surfaces fine-grained tools for policy, identity, and simulation analysis. Its modular design allows tools to be sourced from the core data set, simulation, or advanced overlays, and places complex analytics at the fingertips of any MCP-compliant client. Refer to `mcp.md` for all specific tool semantics and extension guidelines.