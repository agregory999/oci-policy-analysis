# OCI Policy Analysis

Analyze Oracle Cloud IAM policies and identity data through a desktop application,
a browser-based application, the CLI, or MCP.

## Getting started

Choose one of the two interactive applications.

### Desktop application

Requires Python 3.12+ and a working Tk installation.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
oci-policy-analysis-ui
```

You can also launch the source entry point with `python -m oci_policy_analysis.main`.

### Web application

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"
oci-policy-analysis-web --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> in a browser.

## Full documentation

See the [full documentation](https://agregory999.github.io/oci-policy-analysis)
for setup details, authentication, UI workflows, CLI and MCP usage, deployment,
architecture, and the API reference.

The repository also contains [maintainer context](https://github.com/agregory999/oci-policy-analysis/blob/main/context/README.md),
which is kept separate from the published user documentation.

## Other entry points

- `oci-policy-analysis-cli` for non-interactive policy analysis.
- `oci-policy-analysis-mcp` for the standalone MCP server.

The project is licensed under the UPL-1.0 license.
