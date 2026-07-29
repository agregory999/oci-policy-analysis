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

## Permissions Required and Authentication

All modes use the same OCI IAM permissions and auth choices:

- Named OCI profile
- Instance principal
- Session token
- Resource principal for OCI Container Instance deployments

Required baseline policies:

```text
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow group <your_group> to use generative-ai-family in tenancy
```

For dynamic-group/instance-principal usage, grant equivalent policies to the dynamic group.

```text
allow dynamic-group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow dynamic-group <your_group> to use generative-ai-family in tenancy
```

For resource principal usage with a container instance, grant as follows:

```text
allow any-user to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy where all { request.principal.type = 'computecontainerinstance', request.principal.id = '<ocid of container instance>' }
```

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
