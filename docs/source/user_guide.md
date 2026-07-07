# User Guide

This guide is the starting point for using OCI Policy Analysis after the
application is installed. The root README is intentionally a short launch
guide; this page and the linked references contain the detail.

## Choose an application mode

- [Desktop application](setup_desktop.md): local Tkinter workflow with the full
  tabbed interface.
- [Web application](setup_web.md): browser workflow for local or server-hosted
  use.
- [CLI](cli.md): scripted loading, filtering, and export.
- [MCP](mcp.md): policy and identity queries for MCP clients.

For a capability comparison and the relationship between the modes, see the
[overview](overview.md).

## First run

1. Complete the [general setup](setup.md).
2. Follow the [desktop](setup_desktop.md) or [web](setup_web.md) launch guide.
3. Configure OCI authentication and load a tenancy or an existing cache.
4. Start with the policy analysis workflow described in [UI usage](usage.md).

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
- [Limited mode](limited_mode.md) documents restricted web access profiles.

### Troubleshooting and deployment

Use [logging and troubleshooting](logging_and_troubleshooting.md) for runtime
diagnostics. For server deployments, see [web setup](setup_web.md), [MCP
container deployment](setup_mcp_container_instance.md), and [MCP OAuth](mcp_oauth.md).

## Reference map

The [architecture](architecture.md) page explains the runtime layers and data
flow. The [API reference](api/oci_policy_analysis) documents the maintained
Python surface. The [MCP examples](mcp_examples.md) provide concrete query
patterns.
