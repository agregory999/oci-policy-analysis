# Usage

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

Set up tenancy/config, import/export tenancy data, enable GenAI, adjust display, and tweak all advanced configurations.

### Policy Browser Tab

Explore all compartments, policies, and statements in a hierarchical tree. Use right-click to jump to focused views.

### Policy Tab

Search, filter, and sort policy statements in the tenancy. Provides tools for drilling down into policy structure and getting AI explanations.

### Groups / Users Tab

Find policy statements for a particular user or group. Shows group memberships, user policies, and enables GenAI analysis.

### Dynamic Groups Tab

See all dynamic groups, filter or check which are unused, and inspect associated policies.

### Resource Principals Tab

View statements that allow actions for resource principals (non-human access), including dynamic-group or "any-user" syntaxes.

### Cross Tenancy Tab

View and filter cross-tenancy statements: "define", "endorse", "admit". See which permissions are granted between tenancies.

### Permissions Report Tab

Report of granted permissions by compartment and principal. Useful for audits of effective access.

### Historical Comparison Tab

Compare IAM and policy data over time (across snapshot caches) to see what changed.

### Embedded MCP Tab

Start and monitor the embedded Model Context Protocol server for integration and automation.

### Condition Tester Tab

Test any "WHERE" clause from a policy to see if specific input combinations result in a match.

### API Simulation Tab

Script and run access simulations to see how different API calls would be allowed/denied given the loaded policies.

### Recommendations Tab

Review security/compliance recommendations, risk, overlap, statement cleanup, and consolidation suggestions.

### Console & Maintenance Tabs

Inspect logs, debug, and manage maintenance tasks like cache rotation and permission reference lookups.

---

For the underlying logic, data model, and architecture see the [Architecture page](./architecture.md).