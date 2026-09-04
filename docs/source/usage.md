# Usage

This guide explains how to use the interactive desktop and web applications after installation. For installation, authentication, OCI permissions, and deployment options, see the [Setup Guide](./setup.md). CLI and standalone MCP workflows have their own [CLI](./cli.md) and [MCP Server](./mcp.md) guides.

## The usual workflow

1. **Choose a data source.** Load current data from OCI, open a saved combined cache, or import OCI CIS Compliance output. The [data-source setup](./setup.md#choose-a-data-source) section explains what each option provides and where the data comes from.
2. **Load the dataset.** In the desktop application, start on **Settings**. In the web application, use the data operations on the home page. Every analysis page uses the currently loaded dataset.
3. **Investigate the question.** Start with Policy Browser or Policy Analysis, then move to the identity, permissions, historical, or specialist views that fit the question.
4. **Validate the result.** Use Condition Tester, API Simulation, Permissions Report, or the policy-statement detail view to understand why access is granted, denied, or flagged.
5. **Export, compare, or share.** Save a cache for later comparison, export a report, or expose the loaded dataset through MCP when appropriate.

### Pick the right data source

- **Live OCI load** reads the current tenancy through your configured OCI authentication. It is the best choice when current policy and identity data is required.
- **Combined cache** reopens data previously saved by the application. It is useful for repeatable analysis, historical comparison, and working without current OCI access.
- **CIS Compliance output** imports the supplied compliance CSV output directory. It is the best choice when the analysis environment must not connect directly to a tenancy. A policy-and-compartments-only export is supported for placement and limit work; see [Limited Compliance Loading](limited_modes.md#limited-compliance-loading) for the available and unavailable workflows.

The application analyzes the selected data; it does not change IAM policies or other OCI resources.

## Starting the interactive application

Use the startup command for the interface you installed:

```bash
oci-policy-analysis-ui                 # desktop
oci-policy-analysis-web                # web on http://127.0.0.1:8000
```

### Desktop startup options

```bash
oci-policy-analysis-ui --verbose
```

`--verbose` enables detailed application logging for troubleshooting. Desktop has no normal host, port, or data-source command-line options; select the data source from **Settings** after launch.

### Web startup options

```bash
oci-policy-analysis-web --host 127.0.0.1 --port 8000
oci-policy-analysis-web --host 0.0.0.0 --port 8080
oci-policy-analysis-web --reload       # local development only
```

`--host` controls the listening interface and defaults to `127.0.0.1`; `--port` defaults to `8000`. Use `0.0.0.0` only when clients or a reverse proxy must reach the server. `--reload` restarts the server when source files change and is not intended for production. On each startup, copy the runtime access key from the server log into the browser login modal.

For CLI and MCP startup options, use `oci-policy-analysis-cli --help` and `oci-policy-analysis-mcp --help`, then see their dedicated [CLI](./cli.md) and [MCP Server](./mcp.md) guides.

## Analysis Concepts

Before using the tabs, it helps to separate the search styles this app supports.

### Basic vs Advanced Filters

Basic filters are the fast, text-oriented controls you use for general policy browsing:

- statement text
- subject / principal text
- resource, verb, permission, and path filters
- validity and compartment scoping

Advanced filters are for parsed policy structure and identity evidence:

- structured principals
- parsed `where`-clause atoms
- tag conditions
- resource principals and OKE workload identities
- confidence and residual-condition details

Use basic filters when you know the text you want to find. Use advanced filters when you need to explain why a statement matches.

### Principals

This app treats principals as a first-class concept.

- **Human principals**: users and groups
- **Dynamic groups**: resource-based membership rules
- **Resource principals**: OCI services or compute-style principals represented by `any-user` / `any-group` statements with `request.principal.*` conditions
- **OKE workload identities**: a resource-principal variant constrained by `request.principal.type = 'workload'`, namespace, service account, and cluster OCID

The OKE workflow has its own dedicated page: [OKE Workload Identity Querying](./oke_workload_identity.md).

### Tag-Based Access

Tag-based policy search is also a distinct advanced path.

- Use the dedicated [Tag-based Policy Search](./tag_based.md) page for parsed tag conditions, semantic tag access, and tag metadata filters.
- The Policy tab still exposes a `Tag-based` helper for quick filtering.
- Tag-based workflows share the same underlying parsed-condition model as the tag-focused page and MCP tool.

## Desktop UI

Each tab in the UI provides a specific area of functionality. To understand the full technical rationale and data flow for each area, see the [Architecture](./architecture.md) page.

**Tabs include:**

### Settings Tab (Start Here)
<!-- Anchor link; do not change or remove this line! -->

The **Settings Tab** is where you establish the foundation for all analysis in the application. This is typically your first stop after launching the UI or whenever you switch tenancies/environments.

**Purpose**  
- Configure tenancy, identity, and environment options.  
- Import/export cached tenancy data (policies, users, groups, dynamic groups, etc.) for reuse across sessions or machines.  
- Adjust global display and performance preferences that impact how other tabs behave.
 - Control **anonymous usage tracking** (whether the app sends non-personal feature usage metrics to a write-only Object Storage endpoint).

**General Flow**  
1. Select or enter tenancy-specific details and any required authentication/region parameters.  
2. Load or import policy data for that tenancy (from OCI or from a previously exported cache file).  
3. Tune UI preferences such as table density, caching options, and logging levels.
4. Save your configuration so it is reused on subsequent launches.

**Key Widgets and Actions**  
- **Tenancy / Profile selectors:** Choose which tenancy or profile you are currently analyzing.  
- **Import/Export Data buttons:** Load existing cached data or save the currently loaded tenancy data to a file for reuse or sharing.  
- **Advanced Settings / Caching options:** Control snapshot retention, cache refresh behavior, and logging verbosity.  
 - **(Planned) Usage Tracking toggle:** A simple on/off control for anonymous usage tracking. Today this flag is stored as `"usage_tracking_enabled"` in the local settings file (`~/.oci-policy-analysis/settings.json`) and defaults to **On** on first run. You can see whether tracking is currently enabled in the status bar text ("Tool Usage Tracking: On/Off").

Changes made here are **application-wide**: once you import a different policy dataset or adjust global options, all other tabs (Policy Browser, Policy, Simulation, Recommendations, etc.) will immediately reflect the new environment.

### Policy Browser Tab
<!-- Anchor link; do not change or remove this line! -->

The **Policy Browser Tab** provides a hierarchical, tree-style view of your entire tenancy. It is designed for **navigation and context**, helping you see how compartments, policies, and statements are organized.

**Purpose**  
- Visualize the compartment hierarchy and attached policies at each level.  
- Quickly locate policies and statements that apply to a given compartment or path.  
- Act as a launching point for deeper analysis in more specialized tabs.

**General Flow**  
1. Expand the root compartment and drill down through child compartments to the area of interest.  
2. Inspect attached policies and their individual statements for the selected compartment.  
3. Use context/right-click actions to pivot into more detailed views (Policy Tab, Permissions Report, Cross Tenancy, etc.).  
4. Optionally export subsets of policies or paths for offline review.

**Key Widgets and Right-Click Actions**  
- **Compartment/Policy Tree:** Expandable nodes representing compartments and policies. Selecting a node shows details (statements, metadata) in the side panel.  
- **Statement Detail Pane:** Shows parsed statement text, subject, verbs, resource families, and where-clauses.  
- **Right-click on a Compartment:**
  - "Open in Policy Tab" – filters the Policy Tab to that compartment scope.  
  - "Open in Permissions Report" – jump to an effective-permissions view rooted at that path.  
  - "Export Policies under this Compartment" – generate a focused export.  
- **Right-click on a Policy or Statement:**
  - "Show in Policy Tab" – focus on this specific policy/statement for more advanced filtering and analysis.  
  - "Copy Path / OCID" – copy identifiers for documentation or scripting.  

Use this tab when you want a **top-down**, visually oriented understanding of your tenancy’s policies before diving into advanced analysis.

### Policy Tab
<!-- Anchor link; do not change or remove this line! -->

The **Policy Tab** is the primary workspace for **searching, filtering, and deeply inspecting** policy statements across the tenancy.

**Purpose**  
- Perform detailed audits of policy statements across compartments.  
- Search by text, subject, resource family, compartment, or access level.  
- Quickly isolate special policy patterns such as tag-based conditions, invalid statements, or prospective (what-if) statements.  
- Understand how individual statements are structured and which subjects they affect.

**General Flow**  
1. Select initial filters (compartment path, subject type, resource family, etc.) to narrow down the policy set.  
2. Use helper filter controls (for example `any-user|any-group`, `ROOTONLY`, and resource hierarchy expansion) to build broader or more precise filter sets.  
3. Use optional filter toggles (Action = Allow/Deny, Invalid Only, Tag-based, Show Prospective) to focus on specific policy classes.  
4. Use the main policy table to sort and refine (e.g., by path, access level, risk flags).  
5. Select a statement to see a structured breakdown (subject, verb, resource, where-clause).  
6. Pivot to Groups/Users, Dynamic Groups, or Resource Principals tabs when you want to see **who** is affected by a given statement.

**Key Widgets and Right-Click Actions**  
- **Filter Bar / Search Panel:** Filter by Subject, Verb, Resource, Permission, Location/Hierarchy, statement text, policy name, and raw conditions. Multiple values in a field can be entered with `|` for OR matching.  
- **Helper Filter Buttons:**
  - **Add any-user / any-group** inserts `any-user|any-group` in Subject.
  - **Add ROOTONLY** inserts `ROOTONLY` in Hierarchy.
  - **Add Hierarchy** expands resources to include `all-resources` and the containing family when known.
- **Filter Toggles / Options:**
  - **Action** selector (Both / Allow / Deny).
  - **Invalid Only** to focus on invalid statements.
  - **Tag-based** helper to quickly target statements with `.tag.` conditions.
  - **Show Prospective** to include prospective `[Prospective]` rows in the same filtered view.
- **Prospective Editor… button:** Opens the tenancy-scoped prospective statement editor popup for creating/editing what-if statements used by this tab and Simulation.  
- **Policy Statement Table:** Shows normalized statements with columns for path, subject, verb, resource, risk markers, and where-clauses.  
- **Statement Details / Inspector:** A side panel that breaks a statement into its parsed components and may show derived metadata (e.g., permissions, risk categorizations).  
- **Right-click on a Statement:**
  - "Open in Policy Browser" – highlight the statement in its original hierarchical context.  
  - "Show Affected Users/Groups" – pivot into the relevant principals tab.  
  - "Explain with AI" – request a human-readable explanation (if enabled).  

Use this tab for **compliance checks, policy clean-up, and forensic investigations** into particular statements.

### Prospective Editor Popup
<!-- Anchor link; do not change or remove this line! -->

The **Prospective Editor Popup** is a shared, tenancy-scoped window used to manage **prospective (what-if) policy statements**.

**Purpose**
- Create hypothetical IAM statements that are *not* deployed in OCI.
- Validate and organize these statements before using them in analysis/simulation.
- Maintain one shared prospective statement set used consistently across the UI.

**Where You Open It**
- **Policy Tab** via **Prospective Editor…**.
- **API Simulation Tab** via **Manage Prospective Statements…**.
- (In advanced workflows) from **Tag-based Access Tab** integrations.

**What It Contains**
- A CRUD grid for statement rows (compartment/location, description, statement text, parse status).
- Per-row **Parse** actions for validation and diagnostics.
- Per-row **Delete** actions.
- A statement builder area (including optional tag-based where-clause helpers) to synthesize complete Allow/Deny statements quickly.
- **Save and Close** to persist prospective statements for the current tenancy.

**How It Affects Other Tabs**
- On save, statements are persisted per tenancy and pushed to the simulation engine.
- **Policy Tab** can immediately show them when **Show Prospective** is enabled.
- **API Simulation Tab** includes them in scenario evaluation as what-if inputs.

Use this popup when your question is: **“What would happen if we added/changed this policy statement?”**

### Groups / Users Tab
<!-- Anchor link; do not change or remove this line! -->

The **Groups / Users Tab** centers the UI around **human principals** and their effective access.

**Purpose**  
- Find a specific user or group and see which policies and statements affect them.  
- Understand group memberships, inheritance, and the combined effect of multiple policies.  
- Summarize a principal’s access for documentation or review.

**General Flow**  
1. Search for a user or group by name or identifier.  
2. Select the principal to load their group memberships and relevant policies.  
3. Review associated policy statements and derived permissions.  
4. Pivot to the Policy, Policy Browser, or Permissions Report tabs to see the same information from a policy- or compartment-centric perspective.

**Key Widgets and Right-Click Actions**  
- **Principal Search / Selector:** Autocomplete or filter lists for users and groups.  
- **Membership View:** Table or tree showing which groups a user belongs to (and possibly nested memberships).  
- **Related Policies / Statements Panel:** Lists policies that reference the selected principal or its groups.  
- **Right-click on a Principal or Policy Entry:**
  - "Open in Policy Tab" – inspect the underlying statement set.  
  - "Open in Permissions Report" – view all effective permissions for this principal.  

Use this tab when the starting point of your question is **“What can this user or group do?”**

### Dynamic Groups Tab
<!-- Anchor link; do not change or remove this line! -->

The **Dynamic Groups Tab** focuses on **non-human identities** represented as dynamic groups.

**Purpose**  
- List and inspect all dynamic groups in the tenancy.  
- Understand which policies target each dynamic group and what resources they control.  
- Identify unused or overly permissive dynamic groups.

**General Flow**  
1. Use search or filters to locate dynamic groups by name, usage status, or attributes.  
2. Select a dynamic group to see its definition, matching rules, and linked policies.  
3. Review associated policy statements and, if necessary, pivot to Policy or Permissions Report tabs for deeper analysis.  
4. Use this information to refine dynamic group definitions or tighten access controls in OCI.

**Key Widgets and Right-Click Actions**  
- **Dynamic Group List / Filter Controls:** Search and filter by group name, tenancy, or usage indicators.  
- **Group Definition Panel:** Shows the rule expression that defines which resources are members of the dynamic group.  
- **Linked Policies / Statements Table:** Lists policy statements referencing the dynamic group.  
- **Right-click on a Dynamic Group or Policy:**
  - "Open in Policy Tab" – detailed statement inspection.  
  - "Open in Resource Principals" – see related resource principal views where applicable.  
  - "Open in Permissions Report" – inspect effective permissions for the dynamic group.  

Use this tab when you’re investigating **resource-based identities and their access footprint**.

### Resource Principals Tab
<!-- Anchor link; do not change or remove this line! -->

The **Resource Principals Tab** surfaces policies and permissions related to **resource principals and workload identities**.

**Purpose**  
- Identify where non-human identities have been granted access via dynamic groups or `any-user` statements.
- Understand which OCI services, compute-style principals, and OKE workload identities are allowed to call which services and APIs.
- Support security reviews focused on workload-to-service access and parsed `request.principal.*` evidence.

**General Flow**  
1. Browse or filter for dynamic groups and statements that correspond to resource principals.
2. Review which services, compartments, and operations those principals can access.
3. Pivot to Dynamic Groups or Policy tabs to refine or correct identified risks.
4. Use Permissions Report to generate a full list of effective permissions for a given resource principal identity.
5. Switch to the OKE mode described in [OKE Workload Identity Querying](./oke_workload_identity.md) when you want namespace/service-account/cluster filtering rather than generic resource-principal matching.

**Key Widgets and Right-Click Actions**  
- **Resource Principal Summary Table:** Shows which dynamic groups and policies are tied to resource-based identities.  
- **Statement Breakdown View:** Parses statements that mention dynamic groups or `any-user` in the context of resource principals and workload identities.
- **Right-click on a Row / Statement:**
  - "Open in Dynamic Groups" – see the underlying dynamic group configuration.  
  - "Open in Policy Tab" – detailed view of the source statement.  
  - "Open in Permissions Report" – generate or navigate to an effective-access view.

Use this tab when your question is **“What can this compute instance, function, or OKE workload actually do?”**

### Cross Tenancy Tab
<!-- Anchor link; do not change or remove this line! -->

The **Cross Tenancy Tab** highlights **trust relationships between tenancies**.

**Purpose**  
- Discover statements that define, endorse, or admit cross-tenancy access.  
- Understand which external tenancies can act in your tenancy, and where you have granted trust outward.  
- Support security and compliance reviews around external access.

**General Flow**  
1. Load the cross-tenancy view to see all detected cross-tenancy statements.  
2. Filter by direction (incoming vs outgoing trust), remote tenancy, or statement type (define/endorse/admit).  
3. Select an entry to see its full statement text and normalized breakdown.  
4. Use links to pivot to Policy, Policy Browser, or Permissions Report tabs to inspect the broader impact.

**Key Widgets and Right-Click Actions**  
- **Cross-Tenancy Summary Table:** Lists each cross-tenancy relationship with columns for local/remote tenancy identifiers, principal, resource, and type (define/endorse/admit).  
- **Detail Pane:** Shows parsed statement components and any detected risk or configuration notes.  
- **Right-click on a Row:**
  - "Open in Policy Tab" – focus on the originating policy and related statements.  
  - "Open in Permissions Report" – drill down into effective permissions associated with that cross-tenancy relationship.

Use this tab when you’re asking **“Where do we trust or get trusted by other tenancies?”**

### Permissions Report Tab
<!-- Anchor link; do not change or remove this line! -->

The **Permissions Report Tab** is the application’s **effective-access auditor**.

**Purpose**  
- Generate comprehensive reports of allow and deny permissions by effective compartment and principal.
- Trace each listed permission back to source policy statement text where available.
- Produce JSON artifacts from desktop/web, or JSON/CSV artifacts from CLI, for audits and offline reviews.

**General Flow**  
1. Load tenancy data through desktop or web so the full post-load pipeline builds the report.  
2. Expand an effective compartment path and select a principal key.  
3. Review explicit and inherited allow/deny permission rows.  
4. Right-click a permission row to open the source policy statement.  
5. Export the report for offline analysis or documentation.

**Principal Keys**
- Named identities use canonical keys such as `group:Default/Admins`, `dynamic-group:Default/Builders`, and `service:None/objectstorage`.
- Broad `any-user` and `any-group` statements remain visible as original subject keys unless their where clause identifies a resource principal or OKE workload identity.
- Resource-principal statements with `request.principal.type` are shown with keys like `resource-principal:computecontainerinstance/ocid1.compartment...`.
- OKE workload identity statements with workload conditions are shown with keys like `oke-workload-identity:<cluster_id>/<namespace>/<service_account>`.
- These keys come from policy condition evidence only; the report does not validate live OCI resources, Kubernetes namespaces, or service accounts.

**Key Widgets and Right-Click Actions**  
- **Effective Path / Subject Tree:** Lists effective compartment paths and principal keys.
- **Allow/Deny Permission Tables:** Lists each permission with condition status and source statement text.
- **Right-click on a Permission Row:**
  - "Show Policy Statement" – jump to the Policy Analysis tab with the statement text pre-applied.

Use this tab when you want a **clear, report-style view** of what access actually exists.

### Historical Comparison Tab
<!-- Anchor link; do not change or remove this line! -->

The **Historical Comparison Tab** lets you compare **snapshots of policy and IAM data over time**.

**Purpose**  
- Detect what changed between two points in time (policies, statements, memberships, etc.).  
- Support audit, incident response, and change-management reviews.  
- Correlate access changes with operational events.

**General Flow**  
1. Select two (or more) cached snapshots taken at different times.  
2. Run a comparison to identify added, removed, or modified policies, statements, and memberships.  
3. Review grouped results by compartment, principal, or policy.  
4. Drill into individual diffs and pivot to live views (Policy, Groups/Users, Permissions Report) to understand current state.  
5. Export or document differences as needed for audits or change records.

**Key Widgets and Right-Click Actions**  
- **Snapshot Selector:** Choose which historical snapshots to compare.  
- **Change Summary View:** High-level summary of added/removed/changed items.  
- **Detailed Diff Tables:** Show per-item changes, including before/after details where available.  
- **Right-click on a Change Row:**
  - "Open in Policy Tab" – inspect the current (or historical) version of a policy.  
  - "Open Principal" – jump to the corresponding principal tab where applicable.  

Use this tab whenever you’re asking **“What changed between then and now?”**

**Web flow update:** The web Historical Analysis page now keeps context help focused at the card/section level (instead of every per-entry diff row) for cleaner navigation during large compare sessions.

### Embedded MCP Tab
<!-- Anchor link; do not change or remove this line! -->

The **Embedded MCP Tab** lets you start and manage the **embedded Model Context Protocol (MCP) server** from within the UI.

**Purpose**  
- Expose your currently loaded policy and permissions data to MCP-compatible clients (such as VS Code, Claude, or other tools).  
- Support local automation, scripted analysis, and AI-assisted workflows using the same data the UI is showing.  
- Monitor basic MCP server status and activity while continuing to use the UI.

**General Flow**  
1. Configure any necessary MCP endpoint or port settings as exposed in the tab.  
2. Click **Start** to launch the embedded MCP server while the UI is running.  
3. Connect an MCP client (e.g., VS Code extension, Claude desktop) to the server using the URL/port indicated in the tab.  
4. Use MCP tools (e.g., policy queries, simulations, recommendations) from the client while watching logs or status in the Embedded MCP tab.  
5. Click **Stop** before closing the UI, or simply close the UI to stop the embedded server.

**Key Widgets and Actions**  
- **Server Control Buttons:** Start/Stop the embedded MCP server instance.  
- **Configuration Panel:** Shows or allows configuration of host, port, protocol (HTTP), and any authentication options used by the embedded server.  
- **Status Indicator:** Displays whether the MCP server is running and any recent errors.  
- **Log/Activity View:** Shows basic request/response or connection activity, useful for troubleshooting client connections.

When using this tab, you are exposing your **loaded policy statement set** over MCP. For detailed information about available tools, payloads, and security considerations, see the dedicated [MCP Server](./mcp.md) documentation (pay particular attention to the sections describing the HTTP server mode used by the embedded server).  

This is **different** from starting the standalone MCP server from the command line, which runs without the UI. In the Embedded MCP Tab, the MCP server and the UI share the same process lifecycle: when the UI closes, the embedded MCP server stops. For information about running MCP in a more permanent or remote configuration, see the [MCP Server](./mcp.md) documentation.

### Condition Tester Tab
<!-- Anchor link; do not change or remove this line! -->

The **Condition Tester Tab** is a focused utility for **parsing and evaluating IAM policy `where` clauses** in isolation.

**Purpose**  
- Experiment with and validate complex `where` clauses before committing them to live policies.  
- See exactly how a condition parses and which variables it expects.  
- Test sample variable values to understand match vs no-match behavior.

**General Flow**  
1. Paste or type a `where` clause (or a full policy statement with a `where` clause) into the input area.  
2. Let the tool parse the condition and list the discovered variables.  
3. Enter one or more sets of variable values to simulate different scenarios.  
4. Run the condition evaluation to see which scenarios match and why others fail.  
5. Use these results to refine your policy conditions, then copy updated conditions back into your policy authoring process.

**Key Widgets and Right-Click Actions**  
- **Condition Input Editor:** Text area for entering or editing `where` clauses or full statements.  
- **Parsed Variables Panel:** Lists variable names detected in the condition (e.g., `request.principal.name`, `user.department`).  
- **Variable Value Grid:** Lets you enter sample values for one or more test cases.  
- **Evaluation Results Table:** Shows per-test-case match/no-match status and any parse or evaluation errors.  
- **Integration Shortcuts:** From other tabs (e.g., Policy), you may be able to right-click a statement and send its condition to the Condition Tester for quick experimentation.

This tab complements the **API Simulation Tab** by focusing on **conditions only**. For full policy + permission evaluation against API operations, see the Simulation tab (and the dedicated [Simulation](./simulation.md) documentation).

### API Simulation Tab
<!-- Anchor link; do not change or remove this line! -->

The **API Simulation Tab** provides a full **what-if simulation environment** for OCI API calls.

**Purpose**  
- Test whether a specific OCI API operation would be allowed or denied under the currently loaded policies.  
- Understand which statements (including **prospective** what-if statements) contribute to a decision.  
- Perform pre-deployment validation of new or changed policies.

**General Flow**  
1. Select the **simulation environment**: effective compartment path and principal (user, group, dynamic group, resource principal via `any-user`, etc.).  
2. Load applicable statements (real + prospective) and select which ones to include in the scenario.  
3. Configure any required `where`-clause variables for the included statements.  
4. Choose an OCI API operation to test (e.g., `oci:ListBuckets`).  
5. Run the simulation, then review the allow/deny result, final permission set, and per-statement trace.  
6. Iterate by toggling statements, adjusting variables, or modifying prospective statements to explore different what-if outcomes.

**Key Widgets and Right-Click Actions**  
- **Simulation Environment Subtab:** Controls for effective path, principal type, and principal identity.  
- **Statements and Context Subtab:**
  - Table of applicable statements (real + `[Prospective]`), with checkboxes to include/exclude each one.  
  - **Manage Prospective Statements** button to add/edit/remove hypothetical statements stored per tenancy.  
  - Dynamic where-variable input panel that rebuilds when the set of included statements changes.  
- **API Operation Selector:** Drop-down or input for selecting the target OCI API operation.  
- **Simulation History Subtab:** Shows previous runs, their inputs (principal, operation, variables, included prospective statements), and trace details; supports JSON export.

For a deeper, engine-focused explanation of how simulation works (including prospective statements and MCP integration), see the dedicated [Simulation](./simulation.md) page. Maintainers can also consult the [simulation engine context](https://github.com/agregory999/oci-policy-analysis/blob/main/context/project/CONTEXT_simulation_engine.md).

## Web UI

The web interface mirrors the same analysis model, but the entry points are card- and page-based instead of tab-based.

### Policy Analysis Page

Use the Policy Analysis page for broad statement browsing and advanced filtering.

- Basic filters cover statement text, subject, resource, verb, permission, and path.
- Advanced filter panels expose tag conditions, parsed atoms, and structured principals.
- OKE workload identity filters are available in the advanced workload-principal mode and map into the same `policy_search`/principal model described in [OKE Workload Identity Querying](./oke_workload_identity.md).

### Workload Principals Analysis Page

Use this page for resource principals and workload identities.

- It supports the same OKE namespace, service-account, and cluster filters as the desktop resource-principal tab.
- It is the right place for advanced `request.principal.*` analysis when you do not want to work through raw policy text.

### Tag-based Access Tab
<!-- Anchor link; do not change or remove this line! -->

The **Tag-based Access Tab** is an advanced, mostly read-only workspace for understanding IAM statements that use `.tag.` conditions. For a more detailed breakdown of tag condition semantics, see [Tag-based Policy Search](./tag_based.md).

**Purpose**
- Discover and review policy statements that rely on tag-based access logic.
- Break complex `where` clauses into structured tag-condition components.
- Help you pivot quickly into testing and what-if authoring workflows.

**General Flow**
1. Load the tab to see statements containing tag-based conditions.
2. Apply filters by **Tag Namespace**, **Tag Key**, and **Access Type** (for example `target.resource` or `request.principal.group`).
3. Select a statement to inspect individual extracted tag conditions (operator, values, subexpression).
4. Use right-click actions to send full conditions or individual subexpressions to **Condition Tester**.
5. Optionally open **Prospective Editor…** (and/or use builder actions) for what-if statement workflows.

**Key Widgets and Actions**
- **Tag-based Policies Overview:** Upper table for statements plus parsed condition structure (for example `ANY { c1, ALL { c2, c3 } }`).
- **Tag Condition Detail Table:** Lower table showing condition ID, access type, namespace/key, operator, and value.
- **Filter Controls:** Namespace/key text filters, access-type selector, parsed-column toggle, and **Show Prospective**.
- **Prospective Editor… button:** Opens the shared prospective editor window.
- **Refresh from Loaded Policies:** Rebuilds the in-memory tag-based view from currently loaded data.

Use this tab when you’re asking: **“How are tags being used to gate access in our policies?”**

### Recommendations Tab
<!-- Anchor link; do not change or remove this line! -->

The **Recommendations Tab** centralizes **security and hygiene guidance** derived from your loaded policies and identities.

**Purpose**  
- Surface risky patterns (e.g., overly broad `any-user` access, unused groups, cross-tenancy risks).  
- Suggest policy clean-up and consolidation opportunities.  
- Provide a prioritized queue of issues to review and fix.

**General Flow**  
1. Load or refresh recommendations based on the current policy dataset.  
2. Review grouped categories (risk, overlap, clean-up, consolidation, etc.).  
3. Drill into individual findings to see why they were raised and which statements or principals are involved.  
4. Use quick links to open affected statements in the Policy or Policy Browser tabs.  
5. Optionally re-run or validate fixes using API Simulation, Condition Tester, or Permissions Report tabs.

**Key Widgets and Right-Click Actions**  
- **Recommendation List / Categories:** Grouping by type (e.g., high-risk, informational, clean-up).  
- **Finding Detail Panel:** Shows the evidence and reasoning behind each recommendation, including referenced statements and principals.  
- **Right-click on a Recommendation:**
  - "Open in Policy Tab" – inspect and edit the implicated statements.  
  - "Open in Policy Browser" – see the recommendation in hierarchical context.  
  - "Open in Permissions Report" – confirm the effective access behind a risk.  

For more context on how recommendations are generated and categorized, see the dedicated [Recommendations](./recommendations.md) documentation.

**Web flow:** Open a consolidation opportunity from Recommendations to inspect its evidence. Actionable opportunities can be sent to the Consolidation Workbench with their full statement set; the workbench replaces its current candidate selection but keeps saved plans and rollback data.

### Consolidation Workbench
<!-- Anchor link; do not change or remove this line! -->

The **Consolidation Workbench** web flow is designed for policy simplification planning.

**Purpose**
- Review consolidation candidates generated by analytics.
- Stage merge/rewrite follow-up actions in one place.
- Keep operator context while iterating policy hygiene improvements.

**General Flow**
1. Open Recommendations and inspect a consolidation opportunity.
2. Send an actionable opportunity to the Consolidation Workbench, or open the workbench directly.
3. Review the selected candidates, choose a strategy, and generate a proposal.
4. Apply reviewed CLI steps outside the application, then reload policy data and check plan progress.

Use this flow when your question is: **“Which policies should we combine or simplify next?”**

For advanced strategy behavior, plan lifecycle, rollback information, and extension guidance, see
[Consolidation planning](./consolidation.md).

### Reference Data Page (Web)
<!-- Anchor link; do not change or remove this line! -->

The **Reference Data** web page provides compact lookup utilities for permissions, overlap checks, and source mapping.

**Purpose**
- Resolve permissions by resource/family + verb/action.
- Check overlap between two statement-style selectors.
- Find source references for resource/family terms.
- Test API operation permission requirements quickly.

**Key Web Widgets**
- **Reference Mapping** (permission lookup)
- **API Operations Tester** (operation + selected permissions -> True/False style check)
- **Overlap Utility**
- **Reference Source**

Use this page when you want a fast, reference-data-driven validation workflow without leaving the browser.

### Console & Maintenance Tabs
<!-- Anchor link; do not change or remove this line! -->

The **Console** and **Maintenance** tabs support **operational monitoring and housekeeping**.

**Console Tab – Purpose & Flow**  
- View real-time application logs and debug information.  
- Diagnose issues with data loading, MCP integration, or tab behavior.

**Console – Key Widgets**  
- **Log Output Window:** Streams log messages as you interact with the app.  
- **Filter / Search Controls:** Filter by log level or search for specific text.  
- **Log Level Controls (if available):** Adjust verbosity for troubleshooting.

Use the Console tab when you need to **see what the app is doing under the hood**.

**Maintenance Tab – Purpose & Flow**  
- Run admin and clean-up tasks that keep local data and caches healthy.

**Maintenance – Key Widgets and Actions**  
- **Cache Management Buttons:** Clear or rotate policy caches; refresh reference data.  
- **Repair / Diagnostic Tools:** Run routines that check for inconsistent data or stale snapshots.  
- **Status Messages:** Indicate when maintenance tasks complete and whether any issues were found.

Because maintenance actions can affect data used by other tabs, re-open or refresh impacted tabs (Policy, Simulation, Recommendations, etc.) after performing operations here.

## MCP

The MCP server is documented separately in [MCP Server](./mcp.md). It is kept on its own page because it has its own tool catalog, transport modes, and client setup patterns.

Use MCP when you want AI tooling or automation to query the same policy model from outside the UI.

---

For the underlying logic, data model, and architecture see the [Architecture page](./architecture.md).
