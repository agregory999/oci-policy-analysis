# Reports

Reports can be previewed and exported as JSON, Markdown, or HTML.

## Available reports

- **Full Policy Overlaps** runs the expensive all-statement overlap analysis only when requested.
- **Policy Inventory** exports loaded policy statements with policy compartment, effective path, principal, verb, resource, conditions, and resolved permissions.
- **Effective Permissions** exports the effective-permission data already calculated for Permissions Analysis; it does not repeat that calculation.
- **Policy Supersession** exports all instances where a policy has been superseded by one or more other policy statements.  It provides the evidence and confidence in the claim.

Other reports will be added as necessary.

## Open and run reports

Load policy data, then open reports:

- **New UI:** Open **Tools → Reports**.
- **Legacy UI:** Open the **Reports (On-Demand)** tab.

Select a report and click **Run report**. Choose JSON, Markdown, or Rendered HTML
to preview the result, then click **Export** to save it.

Effective Permissions requires Full intelligence enrichment. Policy Supersession
also requires its strategy to be enabled. Results reflect the loaded data,
including its conditions, exclusions, and coverage limits.
