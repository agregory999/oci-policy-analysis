# Reports

Reports are explicit, downloadable artifacts. They use native JSON as the canonical result and can be previewed or exported as JSON or Markdown.

## Available reports

- **Full Policy Overlaps** runs the expensive all-statement overlap analysis only when requested.
- **Policy Inventory** exports loaded policy statements with policy compartment, effective path, principal, verb, resource, conditions, and resolved permissions.
- **Effective Permissions** exports the effective-permission data already calculated for Permissions Analysis; it does not repeat that calculation.

Use **Policy Inventory** for interactive browsing of loaded compartments, policies, and statements. Use **Permissions Analysis** for its interactive effective-permission tree and detail tables. Use Reports when a frozen artifact is needed.
