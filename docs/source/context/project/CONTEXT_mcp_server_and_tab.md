# Project-Specific Context: MCP Server and Embedded MCP Tab Integration

This context file documents how the MCP server (`mcp_server.py`) and the Embedded MCP Tab (`mcp_tab.py`) enable external Model Context Protocol (MCP) clients to directly query OCI Identity and Policies, expose post-analysis intelligence, and run policy simulations – including prospective (what-if) scenarios.

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
  - Prospective (what-if) statements: editable via UI (Simulation tab) and now also via MCP tools, merged seamlessly into simulation.
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

## 5. Simulation and What-If Flow (Engine + MCP)

The **PolicySimulationEngine** is the single source of truth for policy simulation logic. Both the UI Simulation tab and MCP tools follow the same canonical flow:

1. **Context selection / normalization**
   - Inputs: `compartment_path`, `principal_type`, `principal` (user/group/dynamic-group/any-user/service).
   - MCP uses `SimulationPrepareRequest` → `prepare_simulation` → `SimulationPrepareResponse`.
   - The engine normalizes these into a `principal_key` like:
     - `user:Default/anita`
     - `group:Default/Admins`
     - `any-user:None/any-user`

2. **Applicable statement resolution**
   - Engine method: `get_applicable_statements(principal_key, effective_path)`.
   - Under the hood this:
     - Builds a `PolicySearch` filter from `principal_key`.
     - Filters the policy repository (`filter_policy_statements`).
     - Merges in any **prospective statements** that:
       - Apply to the effective path (exact or prefix match), and
       - Match the principal (re-using the same subject semantics as real tenancy policies).

3. **Where-clause variable discovery**
   - Engine method: `get_required_where_fields_for_context(compartment_path, principal_type, principal)`.
   - MCP uses this via `prepare_simulation`.
   - The engine inspects all applicable statements and extracts variable names from any `where` conditions using the ANTLR-based condition parser.

4. **Simulation execution**
   - Engine method: `simulate_and_record(principal_key, effective_path, api_operation, where_context, ...)`.
   - MCP uses this via `run_simulation_batch`.
   - The engine:
     - Evaluates all applicable allow/deny statements (including valid prospective ones) for the given API operation.
     - Computes a final permission set and determines whether the API call is allowed.
     - Records a full trace (`simulation_history`), used by the UI debugger and the Simulation History subtab.

**Important MCP-specific behavior:**

- MCP never exposes manual statement selection. All valid applicable statements for the context are always considered, ensuring reproducibility and correctness.
- The engine always computes a full trace; MCP tools decide how much detail to return (e.g., `trace` flag in `SimulationBatchRequest`).

### 5.1. Managing Prospective (What-If) Statements via MCP

The engine supports "prospective" statements – in-memory what-if policies that are treated just like real tenancy policies during simulation. The UI Simulation tab has an inline editor; MCP now exposes equivalent functionality through dedicated tools:

**Core engine APIs:**

- `PolicySimulationEngine.set_prospective_statements(list[dict])`
- `PolicySimulationEngine.get_prospective_statements() -> list[dict]`
- `PolicySimulationEngine.validate_prospective_statement(text: str) -> dict`

**MCP tools (see `mcp_server.py`):**

1. `list_prospective_statements`
   - No input.
   - Returns a list of `ProspectiveStatementSummary`:
     - `internal_id` (e.g. `prospective-1`)
     - `policy_name`
     - `compartment_path`
     - `parsed`, `valid`, `invalid_reasons`
     - `statement_text`

2. `set_prospective_statements`
   - Input: list of `ProspectiveStatementInput`:

     ```json
     [
       {
         "compartment_path": "ROOT/Finance",
         "description": "What-if: open Finance bucket read",
         "statement_text": "Allow group Finance-Admins to read buckets in compartment Finance"
       }
     ]
     ```

   - Behavior:
     - Replaces the entire in-memory prospective list.
     - Calls the engine’s `set_prospective_statements` to validate, normalize, and assign internal ids.
     - Returns updated `ProspectiveStatementSummary` list so clients can see what is now active.

3. `add_prospective_statement`
   - Input: a single `ProspectiveStatementInput`.
   - Behavior:
     - Validates the statement text using the engine’s `validate_prospective_statement`.
     - Does **not** modify state if parse/validation fails.
     - On success, appends the new statement to the current list and calls `set_prospective_statements`.
     - Returns a `ProspectiveStatementResult` including:
       - `parsed`, `valid`, `invalid_reasons`
       - `normalized` (full normalized policy payload, if valid)
       - `internal_id` for the newly added statement (when determinable)
       - A human-friendly `message`.

4. `clear_prospective_statements`
   - No input.
   - Behavior: calls `set_prospective_statements([])` to remove all prospective entries.
   - Returns a simple `{ "status": "success", "message": "All prospective statements have been cleared." }` payload.

**Typical MCP what-if flow:**

1. Add or set prospective statements with `add_prospective_statement` or `set_prospective_statements`.
2. Inspect them with `list_prospective_statements` (optional).
3. Call `prepare_simulation` to obtain `principal_key` and required `where` variables.
4. Call `run_simulation_batch` to execute one or more scenarios – prospective statements automatically participate.
5. Use `clear_prospective_statements` to reset to "tenancy-only" behavior when finished.

This design keeps UI Simulation tab behavior and MCP flows aligned, while allowing MCP clients to orchestrate rich what-if scenarios programmatically.

---

## 6. Extending the MCP Server

- **Adding new tools**: MCP tools can be registered to expose intelligence/overlays (risk, consolidation, policy fix suggestions), simulation flows (via the engine), or custom queries on the policy set. New analytics or actions should be documented here and in `mcp.md` prior to implementation.
- **UI-to-MCP integration**: The Embedded MCP Tab can be extended to monitor new server actions, display tool health/status, or even expose limited UI for tool-specific queries directly in the application.

---

## 7. References

- MCP Standalone/Embedded Server: [`src/oci_policy_analysis/mcp_server.py`](../../../src/oci_policy_analysis/mcp_server.py)
- Embedded MCP Tab (UI): [`src/oci_policy_analysis/ui/mcp_tab.py`](../../../src/oci_policy_analysis/ui/mcp_tab.py)
- Tool Inventory and Protocol Details: [`docs/source/mcp.md`](../../../docs/source/mcp.md)

---

**Summary:**  
The MCP server architecture (standalone or embedded via the MCP tab) surfaces fine-grained tools for policy, identity, and simulation analysis. Its modular design allows tools to be sourced from the core data set, simulation, or advanced overlays, and places complex analytics at the fingertips of any MCP-compliant client. Refer to `mcp.md` for all specific tool semantics and extension guidelines.