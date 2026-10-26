# Reports

Reports are explicit, downloadable artifacts. They use native JSON as the canonical result and can be previewed or exported as JSON or Markdown.

## Available reports

- **Full Policy Overlaps** runs the expensive all-statement overlap analysis only when requested.
- **Policy Inventory** exports loaded policy statements with policy compartment, effective path, principal, verb, resource, conditions, and resolved permissions.
- **Effective Permissions** exports the effective-permission data already calculated for Permissions Analysis; it does not repeat that calculation.
- **Policy Supersession** exports all instances where a policy has been superseded by one or more other policy statements.  It provides the evidence and confidence in the claim.

Other reports will be added as necessary.


## Qt Reports

Open **Tools → Reports**, select a report and press **Run report**. Generation
runs in a background worker; loading, simulation, prospective editing and
embedded MCP are serialized until it finishes. Closing is deferred during a run.
Switch between read-only JSON, Markdown and rendered HTML, then explicitly export
the selected format. Changing the report choice or loading a new snapshot clears
old previews. Report generation never starts merely by opening the page.

Effective Permissions requires an existing permissions report from Full
intelligence enrichment. Supersession uses existing strategy results; enable that
strategy and use Full enrichment to populate it. Full Overlaps performs its
expensive analysis on demand and refreshes derived intelligence evidence.
Source collection time, conditions, exclusions and inventory coverage remain
relevant; a completed or empty report is not an OCI authorization decision.

Qt and Tk share `ReportsService.catalog` and portable export serialization.
Rendered Qt previews use the active palette and block linked resources and
navigation. Exported HTML is a self-contained readable document. Reports remain
runtime artifacts and are not added to combined-cache payloads; no migration is
required.
