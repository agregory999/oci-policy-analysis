# OCI Policy Analysis

Analyze OCI IAM policies, compartments, identity domains, groups, users, and dynamic groups from a desktop app, web app, CLI, or MCP server. The tool is read-only: it analyzes data but does not change your tenancy.

## Quick start

Choose the path that fits you:

- **Desktop:** local, single-user visual analysis.
- **Web:** browser-based access, locally or for a team.
- **CLI:** scripting, exports, and automation.
- **MCP:** use OCI policy data with an MCP client.

### Easiest: download an application

Download the latest macOS or Windows application from the [Releases page](https://github.com/agregory999/oci-policy-analysis/releases). If your operating system asks for approval, allow the downloaded application to run.

### Install with pip

You need Python 3.12 or later. Create and activate a virtual environment:

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install only the mode you intend to use:

```bash
# Desktop application (requires a working Tkinter installation)
python -m pip install oci-policy-analysis

# Browser-based web server
python -m pip install "oci-policy-analysis[web]"

# Command-line interface
python -m pip install oci-policy-analysis

# MCP server
python -m pip install "oci-policy-analysis[mcp]"
```

Start the selected mode:

```bash
oci-policy-analysis-ui                 # Desktop
oci-policy-analysis-web                # Web: open http://127.0.0.1:8000
oci-policy-analysis-cli --help         # CLI
oci-policy-analysis-mcp --help         # MCP
```

For the desktop app, confirm Tkinter works before starting if needed - one time test:

```bash
python -m tkinter
```

## Choose your data source

You do **not** have to connect this tool to a live tenancy.

- **Live OCI load:** requires an OCI user/API-key profile, session token, instance principal, or resource principal **and** IAM permissions granted to that principal. Before loading a tenancy, complete [Authentication and principals](docs/source/setup.md#authentication-and-principals) and [Permissions required](docs/source/setup.md#permissions-required).
- **Offline CIS compliance import:** import the directory of OCI CIS Compliance output files instead. This lets you analyze the supplied data without the tool connecting to your tenancy. In the desktop or web app, choose **Load Compliance Data**; from the CLI, use:

  ```bash
  oci-policy-analysis-cli --load-from-compliance /path/to/compliance_csv_output
  ```

  See the [CLI guide](docs/source/cli.md) for expected files and options.

## More help

The [full documentation](https://agregory999.github.io/oci-policy-analysis) covers mode-specific setup, OCI authentication and permissions, CIS compliance imports, web hosting, CLI and MCP usage, troubleshooting, architecture, and API reference.

## License and support

Licensed under UPL-1.0.

This is not an Oracle-supported application. It uses supported OCI Python SDK calls and is designed to request the minimum access needed to read and analyze the selected data.
