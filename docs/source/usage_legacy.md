# Legacy Tkinter UI Usage

This guide covers the original Tkinter desktop app, launched with
`oci-policy-analysis-legacy-ui`. It remains supported for the 7.0 release line.
For the new desktop app, see the [new UI usage guide](usage.md). Installation,
authentication, permissions, and data-source requirements are in [Setup](setup.md).

## Start with Settings

Open **Settings (Start Here)** and choose how to load data. A live load uses an
OCI profile or the configured authentication method. You can also open a saved
snapshot or import supported CIS Compliance output. The app uses the loaded
dataset for the rest of the session. Loading another dataset replaces the one
being analyzed.

Settings also contains profile, compartment-depth, logging, cache, and display
options. Use **Import/Export Data** to move a saved snapshot between sessions.
For live tenancy setup and the available authentication methods, see [Setup](setup.md).

## Explore policies

### Policy Inventory

Use **Policy Inventory** to navigate compartments and the policies attached to
them. Expand the hierarchy to find a policy or statement, then use its details
or context menu to inspect it in another view.

### Policy Browser

Use **Policy Browser** to search and filter policy statements across the loaded
dataset. Narrow results by fields such as subject, verb, resource, permission,
compartment, policy name, statement text, or conditions. Select a statement to
inspect its parsed fields. Context-menu actions can move the selection to a
related view, such as Users / Groups or Permissions Analysis.

### Policy Graph

Use **Policy Graph** to follow relationships between principals, source grants,
and compartment paths. Select a node to narrow the view and inspect the related
statements. Conditions in policy statements are evidence to review; the graph
does not evaluate them as an OCI authorization decision.

## Investigate identities and access

- **Users / Groups** shows policies and statements associated with human
  principals. Start with a user or group when asking who may be affected by a
  policy.
- **Dynamic Groups** shows dynamic-group rules and related policies. Use it to
  inspect workload-oriented identity definitions and references.
- **Resource Principals** groups policy evidence involving resource principals
  and workload identities. Use the OKE workflow for namespace and service
  account details.
- **Cross-Tenancy Policies** shows tenancy aliases, cross-tenancy statements,
  and related findings.
- **Permissions Analysis** summarizes permissions represented by the loaded
  policy evidence. Review conditions, exclusions, scope, and collection
  coverage before drawing conclusions.

For detailed OKE identity guidance, see [OKE Workload Identity Querying](oke_workload_identity.md).

## Review and plan changes

- **Historical Comparison** compares saved snapshots so you can review changes
  between collection dates.
- **Policy Recommendations** highlights findings for review and possible
  cleanup. Recommendations are suggestions; the app does not change OCI
  policies.
- **Reports** creates policy and permissions reports from the loaded data.
- **Consolidation** helps prepare and review a policy-consolidation plan. Review
  proposed changes before applying anything in OCI; the workbench does not
  deploy changes.
- **API Simulation** evaluates a request against the available policy model and
  shows the statement evidence behind the result. It does not call the target
  service operation.
- **Prospective Editor** lets you prepare hypothetical statements for analysis
  and simulation. They are not sent to OCI.

## Additional tools

- **Condition Tester** lets you inspect a policy `where` clause with supplied
  sample values.
- **Tag-based Access** helps locate tag-based policy conditions and related
  access evidence.
- **Embedded MCP (Advanced)**, when the MCP extra is installed, exposes the
  loaded data to a compatible MCP client while the app is open. For protocol,
  connection, and client details, see the [MCP guide](mcp.md).
- **Console Logging** displays application messages. Use it to diagnose a load
  or analysis issue; the application log file is also available on disk.
- **Maintenance** provides cache and tenancy-state cleanup controls.
- **JSON Debugger** is an internal tool for inspecting structured data.

## Read results carefully

The app analyzes the snapshot you loaded. It does not change OCI resources or
make an authoritative authorization decision. Conditions, exclusions,
unresolved references, and incomplete collection can affect what the results
show. Check the source statements and coverage details before relying on a
summary.
