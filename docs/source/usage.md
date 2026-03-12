# UI Application - Usage

## Getting Started

There are three main entry points to the OCI Policy Analysis application:

1. User Interface — the main UI
2. Command Line access — the CLI
3. Model Context Protocol — the MCP Server

For CLI/MCP details, see other documentation. This page covers getting the app open and how to use each tab and its functions.

If you have not yet built or installed the application, please see the [Setup Guide](./setup.md).

## Starting the UI

You can launch the UI in either of these ways:

**Double-click executable**  
Most users can simply double-click the downloaded executable. On first launch (Mac/Windows), you may need to allow permissions.

**Command Line (after build)**  
```bash
python3 -V              # Should be 3.12.x
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -e .
python -m oci_policy_analysis.main
```

If you run into issues, consult the [Setup Guide](./setup.md) for troubleshooting.

---

## Working with Tabs in the Application

Each tab in the UI provides a specific area of functionality. To understand the full technical rationale and data flow for each area, see the [Architecture](./architecture.md) page.

**Tabs include:**

### Settings Tab (Start Here)
<!-- Anchor link; do not change or remove this line! -->

Begin your journey with the Settings Tab, where you establish the foundation for your analysis. Here, you'll configure tenancy and environment options, import or export tenancy data for reuse across sessions, enable Generative AI capabilities, and adjust both simple and advanced display preferences. This is typically the first stop on first launch or when changing environments. Any application-wide changes here—such as importing different policy datasets—will affect the contents and behavior of all other tabs. After updating critical configuration, users should proceed to the Policy Browser or Policy tabs to explore the loaded data.

### Policy Browser Tab
<!-- Anchor link; do not change or remove this line! -->

The Policy Browser Tab is your hierarchical overview of the entire tenancy structure. You'll see all compartments, policies, and individual statements organized in an expandable, tree-style layout. Use this for high-level navigation and to gain quick, contextual understanding of how policies are distributed. Right-clicking a compartment, policy, or statement enables shortcut actions such as jumping to focused views in other tabs (like the Policy Tab), highlighting direct connections, or exporting selected scopes. If you want to quickly explore how policies are composed, this is your starting point, and it often links you deeper into focused policy or permissions views elsewhere in the app.

### Policy Tab
<!-- Anchor link; do not change or remove this line! -->

The main workspace for reviewing and analyzing policy statements across the entire tenancy. Here, you can search, filter, and sort all loaded policies by compartment, resource type, access level, or free-text. Drill down into policy statement structure using context expansion tools, or request AI-powered explanations for complex statements. Policy Tab provides direct linking to user or group contexts—if you're unsure who or what a policy affects, you can jump to Groups/Users or Resource Principals Tabs for specifics. This tab is best suited for audit, compliance, and deep-dive workflows.

### Groups / Users Tab
<!-- Anchor link; do not change or remove this line! -->

Use this tab to zero in on specific users or groups and understand exactly what permissions apply to them. Search for any user or group to see their memberships, inherited policies, and relevant policy statements. Advanced GenAI analysis can explain or summarize collected permissions. If you discover a policy or group you want to explore further, quick links take you to the Policy Tab or Policy Browser to see the broader context for that principal.

### Dynamic Groups Tab
<!-- Anchor link; do not change or remove this line! -->

Focused on non-human (dynamic group) identities, this tab aggregates and displays all dynamic groups defined in the tenancy, as well as associated policies. You can filter by usage status (to spot unused or risky dynamic groups), search for group names, and click into a group to see directly connected policies. Links are available to investigate those policies in more detail via the Policy Tab or Policy Browser, facilitating complete traceability from dynamic group to permissions.

### Resource Principals Tab
<!-- Anchor link; do not change or remove this line! -->

This tab highlights all policy statements regarding resource principals—entities like compute instances or cloud functions with their own access rights. The view consolidates statements that use dynamic group or “any-user” syntax, showing where non-human access is permitted. Quickly identify all resources approved for privileged access, and click through to cross-reference related statements or investigate effective permissions via the Permissions Report Tab.

### Cross Tenancy Tab
<!-- Anchor link; do not change or remove this line! -->

This tab is designed to surface all cross-tenancy arrangements within your tenancy. You can filter and review policy statements that “define”, “endorse”, or “admit” trust across tenancies, clarifying which permissions and relationships exist outside your root. Each entry displays principal and resource information as well as context, and often links to detailed breakdowns in the Policy or Permissions Report tabs for further investigation.

### Permissions Report Tab
<!-- Anchor link; do not change or remove this line! -->

The Permissions Report Tab is your comprehensive effective-access auditor. Generate detailed reports of every effective permission, organized by compartment and principal (user, group, dynamic group, or resource principal). Use advanced filters to hone in on specific entities, view permission sources, and export results for compliance documentation. This tab often surfaces the results of complex relationships mapped in other tabs, and it links back to Policy and Principal tabs for root-cause analysis.

### Historical Comparison Tab
<!-- Anchor link; do not change or remove this line! -->

Here you can review changes in IAM and policy data over time using snapshot caching. Load two or more points-in-time to visualize exactly what policies, statements, or memberships have changed—essential for audit scenarios, forensic analysis, or operational reviews. Results can be linked to exported policy lists or permission reports for offline review. If historical issues are detected, direct links enable jumping to relevant Policy or Principal views for live data comparisons.

### Embedded MCP Tab
<!-- Anchor link; do not change or remove this line! -->

This tab allows you to launch, monitor, and manage the embedded Model Context Protocol (MCP) server. Enable this for automation or integration scenarios where external systems need programmatic access to live policy and permission data. Controls are provided to start/stop the server, check status, and review connection logs. The MCP server can be leveraged in combination with local analysis in other tabs, for example to validate live recommendations or simulate API access.

By using this tab you will be exposing your loaded policy statement set via MCP.  Use local clients such as VSCode, Claude, or others to query this information.  

For more information, see [MCP Server](./mcp.md) - Note that if you use the embedded MCP server inside OCI Policy Analysis, you want to look for the sections in the MCP Server related to HTTP.  

This is different from starting the standalone MCP Server described.  That prevents loading the UI application altogether. In this tab, you have both an MCP server and teh UI application, while the UI is running.  When you close the UI Application, the MCP server stops.  An example of how you might run MCP more permanently on an OCI server is [here](/mcp.html#secure-deployment-on-oci-outline-steps).

### Condition Tester Tab
<!-- Anchor link; do not change or remove this line! -->

Use the Condition Tester Tab to interactively test any IAM policy “WHERE” clause. By entering sample input values, you can see how a policy would behave under various scenarios—whether a certain combination would result in a match or denial. Great for debugging or crafting complex conditions before deployment. This tool can work with policies found in the Policy Tab, and often complements reviews done in the API Simulation Tab.

### API Simulation Tab
<!-- Anchor link; do not change or remove this line! -->

This interactive area lets you script, configure, and execute simulated API calls to see how the loaded policies would evaluate real-world requests. Ideal for pre-deployment testing, security analysis, or exploring new policies. As you craft scenarios here, you’ll often refer to results in Condition Tester, Policy, or Permissions Report Tabs to understand outcomes or determine why a particular access is allowed or denied.

### Recommendations Tab
<!-- Anchor link; do not change or remove this line! -->

Centralize your review of security and compliance suggestions. This tab aggregates risk analyses, overlap detections, statement cleanup opportunities, and policy consolidation recommendations. Each suggested action links directly to offending or related statements, often directing you to the Policy Tab or Policy Browser for detailed follow-up. Designed to guide you toward a safer, more secure tenancy setup.

### Console & Maintenance Tabs
<!-- Anchor link; do not change or remove this line! -->

These tabs are your tools for backend visibility and ongoing operations. Use the Console Tab for real-time log inspection and debugging. The Maintenance Tab lets you handle periodic admin functions like rotating policy caches, refreshing reference data, or fixing broken dependencies. These actions may impact data visible across other tabs, so be sure to reload or revisit affected areas following maintenance.

---

For the underlying logic, data model, and architecture see the [Architecture page](./architecture.md).