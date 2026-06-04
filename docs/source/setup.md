# Setup

Setup is now split into mode-focused guides:

- **[Desktop Setup](setup_desktop.md)** — Tkinter/desktop installation and launch
- **[Web Setup](setup_web.md)** — non-Tk web install, server startup, host/port, load balancer, and browser access-key login flow
- **[MCP Container Instance Setup](setup_mcp_container_instance.md)** — build/push MCP image to OCIR and deploy to OCI Container Instances with instance principal

If you are not sure which to choose:

- Use **Desktop Setup** for single-user exploratory work on a local machine.
- Use **Web Setup** for team/server-hosted browser workflows.
- Use **MCP Container Instance Setup** for standalone MCP in OCI using OCIR + private subnet container runtime.

For a high-level capability comparison by startup mode, see [Overview](overview.md).

## Server-first pip installs (no git clone)

If you are starting on a non-desktop server and want quick copy/paste commands,
use one of the install profiles below.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### CLI only (minimal)

```bash
pip install oci-policy-analysis
oci-policy-analysis-cli --help
```

### MCP mode

```bash
pip install "oci-policy-analysis[mcp]"
oci-policy-analysis-mcp --help
```

### Web mode

```bash
pip install "oci-policy-analysis[web]"
oci-policy-analysis-web --host 0.0.0.0 --port 8000
```

On startup, the web server logs a runtime access key. Use that key in the
browser login modal to unlock pages for the current server session.

### All optional extras

```bash
pip install "oci-policy-analysis[all]"
```

### Pin a specific version

```bash
pip install "oci-policy-analysis[all]==5.1.1"
```

### See available versions on PyPI

```bash
pip index versions oci-policy-analysis
```
