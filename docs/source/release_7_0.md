# Version 7.0: What's new

Version 7.0 adds a new desktop app around the same analysis tools used by the
CLI, web app, and MCP server. The new app is the default desktop experience
going forward. The original Tkinter app remains maintained for the 7.0 release
line and continues to work as designed.

## Highlights

- **Explore before connecting.** The new desktop app includes fictional sample
  data, so you can try the pages and filters without OCI credentials.
- **A clearer desktop workflow.** Load data, browse policy inventory and
  relationships, inspect findings, and open live logs from one app. See the
  [new UI usage guide](usage.md) for a tour of its pages and tools.
- **MCP Assistant.** Connect supported assistants to the loaded snapshot or
  start an in-app Codex CLI or Claude Code conversation. The assistant uses
  your existing CLI setup and account.
- **History/Audit.** Generate an OCI Audit Log search that corresponds to a historical policy change
- **Build on the same core.** The analysis services can be embedded in Python
  applications. See the [embedding guide](core_integration.md).
- **Keep your saved data.** Supported snapshots remain readable in 7.0.
- **Keep using the original desktop.** Launch it with
  `oci-policy-analysis-legacy-ui`; launch the new app with
  `oci-policy-analysis-ui`.

## Getting started

Built desktop apps are available from the
[Releases page](https://github.com/agregory999/oci-policy-analysis/releases).
Download the version for your computer; Python setup is not needed to run a
built app. In the new app, choose **Sample** on **Overview & Settings** to
explore, or load a saved snapshot or live tenancy.

Python 3.12 or later and pip are needed when running the CLI or starting the web
interface from your computer. **uv** is optional for managing PIP - more details on [uv here](https://docs.astral.sh/uv/).

The [Setup guide](setup.md)
covers command-line setup, web startup, and the two maintained desktop versions.
