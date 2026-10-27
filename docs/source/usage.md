# New Desktop UI Usage

This guide covers the new desktop app, launched with
`oci-policy-analysis-ui`. It walks through loading data, using the analysis
pages, and finding logs and supporting tools. For installation, OCI access, and
permissions, see [Setup](setup.md). The original Tkinter app has a separate
[legacy UI guide](usage_legacy.md).

## Start with Overview & Settings

When the app opens, use **Overview & Settings** to choose a data source and
load the data you want to review. The source choices are:

- **Live Tenancy** — connect to OCI using a profile or instance principal.
- **Local Snapshot** — open a saved snapshot or cache from disk.
- **CIS Compliance** — import supported CIS Compliance output.
- **Sample** — load fictional data to explore the app without connecting to
  OCI or using credentials.

For live data, choose an authentication method and profile, then select the
compartment depth for identity-domain searches. Advanced options include
loading all users and all compartments, and choosing the policy-loading scope.
Select **Load from OCI** when the options are ready.

For CIS imports, see [Limited Compliance Loading](limited_modes.md#limited-compliance-loading)
for the available data and its limits.

After a successful load, the **Active Data Set** card shows the current source,
profile or connection, status, data summary, and recent load activity. A failed
load leaves the last successfully loaded data active. Other analysis pages
become available after data loads.

The sample snapshot includes fictional compartments, policies, identities,
and workload examples. Use it to learn the navigation and filters before
connecting to a tenancy.

## Find policy information

### Policy Inventory

Use **Policy Inventory** for a compartment-first view. The **Hierarchy** tab
shows the loaded compartment tree and associated policies. The other tabs let
you browse compartments, policies, policy statements, and tags as tables.
Select a row to inspect it. Right-click a row to open its details, including
all available fields, or to move to a related view.

### Policy Browser

Use **Policy Browser** to search and filter source policy statements. Combine
text searches with filters for policy, compartment, principal, resource,
permission, verb, effect, validity, and conditions. Select a row to see its
statement details; use the context menu for related actions and complete
evidence.

The browser preserves source text, including invalid or unresolved statements.
Review the original statement and its conditions when a parsed field or summary
does not tell the whole story.

### Policy Graph

Use **Policy Graph** to explore relationships between principals, source
grants, and compartment paths. Search by principal, path, resource or
permission, policy or statement text, and effect. Selecting a node updates the
search and narrows the graph. The lower panel shows related statements and
selected evidence. Use **Fit**, **+**, and **−** to adjust the view; drag to pan.

The graph shows direct policy evidence. It does not evaluate conditions or
make an OCI authorization decision.

## Review identities and access

- **Users / Groups** — find a user or group and review memberships and related
  policy statements.
- **Dynamic Groups** — inspect dynamic-group rules and the policies that refer
  to each group. Filter to groups that are in use or not in use, then select a
  group to see its statements.
- **Resource Principals** — explore policies for resource-oriented identities,
  including dynamic groups and OKE workload identities. Use the OKE filters
  when reviewing namespace, service account, or cluster evidence.
- **Cross-Tenancy** — review tenancy aliases, cross-tenancy statements, and
  unresolved references or findings.
- **Permissions Analysis** — inspect permissions represented in the loaded
  policy evidence. Keep conditions, exclusions, and data coverage in view when
  interpreting results.

Use the row context menus to inspect complete details or navigate between
related records. Details include source fields even when they are not displayed
as table columns.

## Review findings and plan changes

- **Recommendations** — review findings and possible policy cleanups. The
  **Cleanup** view shows the source records behind a recommendation; right-click
  a row to inspect all available details. The **Limits** view shows policy and
  compartment-hierarchy limits. For saved or imported data, you can enter
  known limits; a live-loaded dataset can fetch them from OCI.
- **Prospective Statements** — create hypothetical statements for analysis.
  They are kept separate from the loaded source policies and are not sent to
  OCI.
- **Simulation** — select a principal, operation, and request context to see
  how the loaded policy evidence relates to a proposed request. Use the result
  tabs to inspect statement evidence and condition comparisons.
- **Consolidation Workbench** — review policy consolidation proposals, their
  changes, skipped statements, and rollback information. The workbench prepares
  a plan; it does not apply changes in OCI.
- **Historical Comparison** — compare two saved snapshots or JSON files. Use
  the change tables and details to see what changed. For a policy change,
  **Find OCI Audit Records** can prepare an OCI Logging Search command using
  the policy and compartment information from the selected change. Choose
  POSIX shell or PowerShell output, and enable instance-principal
  authentication when running the command from an OCI instance with the
  required permissions.

These pages analyze the selected snapshot and any explicitly included
prospective statements. They do not update OCI policies or perform the service
operations shown in a simulation.

## Tools

Open **Tools** for the supporting work areas:

- **Condition Tester** — enter a policy `where` clause and sample values to
  inspect how its conditions behave.
- **Reports** — generate and preview supported policy and permissions reports.
- **Maintenance** — manage saved caches and tenancy-specific consolidation
  data.
- **Logging** — adjust the displayed application log level and component
  overrides.

Use the **Live Log** button at the bottom of the left navigation to open the
log and activity window from any page.

## Live logs and OCI call details

The log window has three tabs:

- **Live log** shows application messages as they arrive. Filter by component
  or severity while troubleshooting.
- **Load activity** shows stages and status messages for the current or most
  recent load.
- **API Calls** shows completed OCI request metadata, including time, duration,
  status, service code, reason, and request ID when available. Search the list
  or select **Errors only**, then select a row to inspect its details.

The API call history is held in memory and can be cleared from the API Calls
tab. It does not include request or response bodies. A request error does not
by itself prove that a resource was deleted or inaccessible; review its status,
reason, and request ID alongside the load activity.

The **Logging** tool controls application log levels. The Live Log button opens
the viewer; it does not change which data source is loaded.

## Advanced pages

Turn on **Advanced mode** to show additional pages and workflows:

- **Tag-Based Policies** helps search statements that use tag conditions.
- **Prospective Statements**, **Simulation**, and **Consolidation Workbench**
  support what-if analysis and plan review.
- **Historical Comparison** compares saved snapshots and can help trace policy
  changes to OCI audit records.
- **MCP & Assistant** shares the loaded snapshot with compatible MCP clients
  and offers in-app Codex CLI and Claude Code conversations. Read the
  [MCP Assistant guide](mcp_assistant.md) before connecting a client; Codex or
  Claude tools need to be installed and signed in first.

The MCP Assistant uses the loaded snapshot and remains active only while the
app is open. Its answers are based on returned policy evidence, not an OCI
authorization decision.

## Appearance and analysis settings

Use **Overview & Settings** to adjust the appearance, table density, logging,
and post-load analysis options. The intelligence setting affects what analysis
is prepared on the next load; changing it does not refresh the current data.
Theme and display choices apply across the app.

For OCI authentication, available data sources, saved snapshots, and required
permissions, see [Setup](setup.md). For policy condition limits, unresolved
evidence, and other interpretation details, see the relevant topic pages in
the documentation index.
