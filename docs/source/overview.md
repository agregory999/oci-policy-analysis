# Overview

**OCI Policy Analysis** is now a **multi-modal application** for Oracle Cloud Infrastructure (OCI) IAM analysis. You can run it as:

- a **Desktop UI** (Tkinter)
- a **Web UI** (FastAPI + static web client)
- a **CLI** for automation and offline workflows
- an **MCP Server** for AI tooling integrations (Claude, VS Code MCP, etc.)

The core goal across all modes is the same: analyze and explain OCI IAM policies, dynamic groups, principals, and effective access.

## Core Capabilities

- **Policy Analysis**: Parse/filter IAM policy statements by subject, verb, resource, compartment, and conditions.
- **Dynamic Group Analysis**: Review dynamic-group rules, usage, and related policy grants.
- **Principal-Centric Analysis**: Analyze access for users, groups, and resource principals.
- **Historical Comparison**: Compare policy snapshots over time.
- **Caching**: Save/load combined tenancy data for repeatable, offline, or remote workflows.
- **Export & Import**: Export analysis data to JSON/CSV and re-import as needed.
- **AI Insights**: Generate plain-language interpretation of policy statements.
- **Contextual Help**: In-app guidance based on page/section context.

## Advanced Capabilities

- **Condition Tester**: Evaluate hypothetical where-clause values.
- **Permissions Report**: Resolve effective OCI permissions by principal and compartment.
- **MCP Tooling**: Expose tenancy data as MCP tools/resources for AI assistants.
- **API Simulation**: Evaluate whether an OCI API call should be allowed under selected policies.
- **Recommendations Workbench**: Catalog and prioritize policy improvement suggestions.

The application supports **Instance Principal**, **OCI profile/config**, and **Session Token** authentication models.

## Feature Availability Matrix (by Startup Mode)

> This is a living matrix and can be updated as parity evolves.

| Capability | Desktop UI | Web UI | CLI | MCP |
|---|---|---|---|---|
| Load tenancy data from OCI | ✅ | ✅ | ✅ | ✅ |
| Load/use local combined cache | ✅ | ✅ | ✅ | ✅ |
| Rich tabbed interactive UI | ✅ | ⚠️ Partial | ❌ | ❌ |
| Policy filtering/search from command line | ❌ | ❌ | ✅ | ✅ (tool calls) |
| Historical comparison workflows | ✅ | ⚠️ Partial | ⚠️ Limited | ⚠️ Limited |
| Prospective statements editor/workbench | ✅ | ⚠️ Partial | ❌ | ⚠️ Via tools |
| Recommendations UX/workbench | ✅ | ⚠️ Partial | ❌ | ❌ |
| API simulation | ✅ | ⚠️ Partial | ❌ | ✅ |
| AI assistant integration | ✅ (embedded MCP tab) | ⚠️ Indirect | ⚠️ Indirect | ✅ Native purpose |
| Best fit: human exploratory analysis | ✅ Best | ✅ Good | ❌ | ❌ |
| Best fit: automation/scripting | ⚠️ | ⚠️ | ✅ Best | ✅ Best |

**Legend**
- ✅ Fully supported
- ⚠️ Partial/in progress
- ❌ Not intended for that mode


