# User Guide

This guide is the starting point for using OCI Policy Analysis after the
application is installed. The root README is intentionally a short launch
guide; this page and the linked references contain the detail.

## Choose an application mode

- [Desktop application](setup.md#desktop-application): local Tkinter workflow with the full
  tabbed interface.
- [Web application](setup.md#web-application): browser workflow for local or server-hosted
  use.
- [CLI](cli.md): scripted loading, filtering, and export.
- [MCP](mcp.md): policy and identity queries for MCP clients.

For a capability comparison and the relationship between the modes, see the
[overview](overview.md).

## First run

1. Complete the [general setup](setup.md).
2. Follow the [Desktop](setup.md#desktop-application) or [Web](setup.md#web-application) launch guide.
3. Choose the dataset you will analyze:
   - **Live tenancy data:** configure an OCI user/API-key profile, session token, instance principal, or resource principal. An OCI administrator must also grant the [required IAM permissions](setup.md#permissions-required) to the principal that runs the tool.
   - **CIS Compliance output:** use a directory produced by the [CIS Compliance script](setup.md#obtain-cis-compliance-output), then import it with **Load Compliance Data**. This path does not require OCI credentials in OCI Policy Analysis.
   - **Combined cache:** open a cache previously saved by the application when you need repeatable or offline analysis.
4. Load the chosen data source from **Settings** in desktop mode or the web home page, then start with the policy analysis workflow described in [UI usage](usage.md).

## Core workflows

### Policy and identity analysis

The UI supports policy browsing, principal analysis, policy history, workload
principals, permissions reports, and cross-tenancy analysis. The [UI usage
guide](usage.md) describes the available desktop tabs and web pages.

### Advanced policy analysis

- [Simulation](simulation.md) evaluates policy statements against OCI API
  operations.
- [Recommendations](recommendations.md) explains risk, overlap, cleanup, and
  consolidation analysis.
- [Tag-based policy search](tag_based.md) covers parsed tag conditions and
  policy metadata.
- [OKE workload identity](oke_workload_identity.md) covers namespace and
  service-account queries.
- [Limited Compliance Loading](limited_modes.md#limited-compliance-loading) explains policy-and-compartments-only CIS imports.
- [Limited Web User](limited_modes.md#limited-web-user) documents restricted web access profiles.

### Troubleshooting and deployment

Use [logging and troubleshooting](logging_and_troubleshooting.md) for runtime
diagnostics. For server deployments, see [web setup](setup.md#web-application), [containerized
MCP](setup.md#containerized-mcp-on-oci-container-instances), and [MCP OAuth](mcp_oauth.md).

## Reference map

The [architecture](architecture.md) page explains the runtime layers and data
flow. The [API reference](api/oci_policy_analysis) documents the maintained
Python surface. The [MCP examples](mcp_examples.md) provide concrete query
patterns.
