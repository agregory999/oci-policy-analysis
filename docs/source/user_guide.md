# User Guide

This guide is the starting point for using OCI Policy Analysis after the
application is installed. The root README is intentionally a short launch
guide; this page and the linked references contain the detail.

## Choose an application mode

- [New desktop app](usage.md): the default desktop experience starting in 7.0.
- [Legacy desktop app](usage_legacy.md): the maintained Tkinter interface for
  the 7.0 release line.
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
4. Load the chosen data source from **Overview & Settings** in the new desktop app, **Settings** in the legacy app, or the web home page. Start with the [new UI usage guide](usage.md) or the [legacy UI guide](usage_legacy.md).

## Clean, build, and run from a source checkout

The root scripts are short adapters to the maintained scripts in `run/`:
`local-build` calls `run/build`, `local-run` calls `run/local`, and `local-clean`
calls `run/clean`. Use the same UI names across setup, source running, and
cleanup:

| Task | macOS / Linux | Windows PowerShell |
| --- | --- | --- |
| Prepare the environment | `./local-build.sh --mode ui` | `./local-build.ps1 --mode ui` |
| Run the new desktop app | `./local-run.sh --mode ui` | `./local-run.ps1 --mode ui` |
| Run the Tkinter app | `./local-run.sh --mode legacy-ui` | `./local-run.ps1 --mode legacy-ui` |
| Clean one UI's executable files | `./local-clean.sh --mode ui` | `./local-clean.ps1 --mode ui` |

Use `legacy-ui` in place of `ui` to prepare or clean Tkinter files. Both desktop
modes include MCP dependencies for the embedded server or assistant. Build
dependencies for the other interfaces with `--mode web`, `cli`, or `mcp`;
`--mode all` prepares Qt, web, and MCP dependencies and is the default for
`local-build`.

`local-clean` with no mode performs a full reset, including the shared virtual
environment. The UI-specific clean modes remove only that UI's executable
artifacts and keep the environment. Choose the mode carefully before a full
clean.

To package a native desktop executable, use the executable builder directly:

```bash
./run/build-executable.sh ui          # New Qt-based desktop app
./run/build-executable.sh ui --mode onefile # Single-file executable .exe (Windows) or .app (Mac bundle)
./run/build-executable.sh legacy-ui   # Tkinter desktop app
```

On Windows, use `./run/build-executable.ps1` with the same `ui` or `legacy-ui`
selector. The Qt builder accepts additional Nuitka options such as
`--mode onefile`; Tkinter uses PyInstaller. The old
`local-build-with-pyinstaller.sh` and `.ps1` names remain as compatibility
adapters, but
the `run/build-executable` commands are the clear entry point for both apps.
See the [run operations guide](https://github.com/agregory999/oci-policy-analysis/blob/main/run/README.md)
for executable options, configuration, container builds, and deployment.

## Core workflows

### Policy and identity analysis

The UI supports policy browsing, principal analysis, policy history, workload
principals, permissions reports, and cross-tenancy analysis. The [UI usage
guide](usage.md) describes the new desktop pages; the [legacy UI guide](usage_legacy.md) covers Tkinter.

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
