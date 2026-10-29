# New Desktop UI Usage

This guide covers the new desktop app, launched with
`oci-policy-analysis-ui`. It walks through loading data, using the analysis
pages, and finding logs and supporting tools. For installation, OCI access, and
permissions, see [Setup](setup.md). The original Tkinter app has a separate
[legacy UI guide](usage_legacy.md).

(overview)=
## Start with Overview & Settings

When the app opens, use **Overview & Settings** to choose a data source and
load the data you want to review. The source choices are:

- **Live Tenancy** — connect to OCI using an API-key profile, session-token profile, or instance principal.
- **Local Snapshot** — open a saved snapshot or cache from disk.
- **CIS Compliance** — import supported CIS Compliance output.
- **Sample** — load fictional data to explore the app without connecting to
  OCI or using credentials.

For live data, choose an authentication method and profile, then select the
compartment depth for identity-domain searches. Advanced options include
loading all users and all compartments, and choosing the policy-loading scope.
Select **Load from OCI** when the options are ready. For temporary credentials, choose
**Session token profile** and select the named OCI config profile created by
`oci session authenticate`. The profile name may be the same as one used for
API-key loading; the authentication choice selects the signer. Use the reload
icon beside Profile to refresh the list after session authentication creates a
new config profile. Reloading keeps your current selection or typed profile name. See
[Authentication and principals](setup.md#authentication-and-principals) for setup,
session renewal, and required permissions.

For CIS imports, see [Limited Compliance Loading](limited_modes.md#limited-compliance-loading)
for the available data and its limits.

After a successful load, the **Active Data Set** card shows the current source,
profile or connection, status, data summary, and recent load activity. A failed
load leaves the last successfully loaded data active. Other analysis pages
become available after data loads.

The sample snapshot includes fictional compartments, policies, identities,
and workload examples. Use it to learn the navigation and filters before
connecting to a tenancy.

Each app page has a **Usage guide** link in its header that opens its section below.

## Find policy information

(policy-inventory)=
### Policy Inventory

Use **Policy Inventory** for a compartment-first view. The **Hierarchy** tab
shows the loaded compartment tree and associated policies. The other tabs let
you browse compartments, policies, policy statements, and tags as tables.
Select a row to inspect it. Right-click a row to open its details, including
all available fields, or to move to a related view.

(browser)=
### Policy Browser

Use **Policy Browser** to search and filter source policy statements. Combine
text searches with filters for policy, compartment, principal, resource,
permission, verb, effect, validity, and conditions. Select a row to see its
statement details; use the context menu for related actions and complete
evidence.

The browser preserves source text, including invalid or unresolved statements.
Review the original statement and its conditions when a parsed field or summary
does not tell the whole story.

(graph)=
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

(tools)=
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

## Page reference

These sections are stable targets for the app’s page help links. Advanced pages
appear when Advanced mode is enabled.

(users-groups)=
### Users / Groups

Search loaded users and groups, select an identity to inspect group memberships and related policy statements, and use row details to follow source evidence. Missing users can reflect the load scope; check whether all users were collected.

(dynamic-groups)=
### Dynamic Groups

Filter dynamic groups by use, inspect matching rules, and select a group to find policies that name it. Review the original rule and policy conditions before drawing conclusions about workload access.

(resource-principals)=
### Resource Principals

Explore dynamic-group and OKE workload identity evidence. Narrow OKE results by namespace, service account, or cluster, then inspect the related statements and their conditions. The page models loaded evidence rather than testing a live workload.

(cross-tenancy)=
### Cross-Tenancy

Review Admit and Endorse statements alongside tenancy aliases and entity definitions. Use findings and unresolved references to identify missing or ambiguous evidence; both sides of a cross-tenancy relationship may require separate snapshots.

(recommendations)=
### Recommendations

Review findings, cleanup candidates, and policy limits. Inspect the source records supporting a finding before planning a change. Saved or imported snapshots can use manually entered known limits; a live dataset can fetch limits from OCI.

(mcp)=
### MCP & Assistant

Start the embedded MCP endpoint to share the active snapshot with a compatible client, or use the in-app CLI assistants. Configure and sign in to the assistant CLI first. Stop MCP before replacing the snapshot. See the [MCP Assistant guide](mcp_assistant.md) for connection and client setup.

(tag-based)=
### Tag-Based Policies

Search statements with tag conditions and filter by tag scope, namespace, key, and value. Inspect the full source condition and loaded tag catalog, then send a condition to the Condition Tester with explicit sample values. Unresolved tags and incomplete inventory remain relevant.

(permissions)=
### Permissions Analysis

Inspect the permissions contributed by the loaded policy evidence and follow related statements for provenance. Review conditions, exclusions, unsupported expressions, and collection coverage. Use the condition-testing and analysis actions for further investigation.

(prospective)=
### Prospective Statements

Create and manage hypothetical policy statements for analysis and simulation. Review their parsing and scope before including them in a run. These drafts are separate from source policies and are never applied to OCI by this page.

(simulation)=
### Simulation

Choose an environment, include source or prospective statements, and provide a principal, operation, resource, and request context. Run the simulation, then inspect statement evidence, condition comparisons, and history. Results describe the snapshot model and do not establish an OCI authorization decision.

(consolidation)=
### Consolidation Workbench

Review consolidation candidates and protections, create a proposal explicitly, and inspect changed statements, skipped evidence, and rollback information. Review saved run history before exporting a plan. Proposal creation records a local run; it does not change OCI policies.

(historical)=
### Historical Comparison

Select two caches or exported JSON snapshots and compare their policy and inventory changes. Inspect complete row details and use Find OCI Audit Records to prepare a command for a selected policy change. Choose the shell and authentication appropriate to where you will execute that command.
