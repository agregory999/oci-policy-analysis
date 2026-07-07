# Web Setup

Use this guide when you want OCI Policy Analysis in **web mode** (FastAPI + static web UI), without Tkinter/desktop requirements.

## Choose Web Setup When

- You want browser-based access.
- You want to host for a team or shared environment.
- You do **not** need desktop Tkinter mode.

## Prerequisites

- Python **3.12+**
- Network access from browser clients to the web server

Verify Python:

```bash
python3 -V
```

## Install (non-Tk web profile)

```bash
git clone https://github.com/agregory999/oci-policy-analysis.git
cd oci-policy-analysis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[web]"
```

## Install via Local Build Scripts (non-Tk web-only)

If you want to use the repository's local build helpers and explicitly avoid desktop/Tk paths, run build in **web mode**:

macOS/Linux:

```bash
./local-build.sh --mode web
```

Windows PowerShell:

```powershell
./local-build.ps1 --mode web
```

What this does:

- Creates/reuses `.venv`
- Installs package extras as `.[web]` (FastAPI/uvicorn/itsdangerous)
- Skips `mcp` extras unless you choose `--mode all` or `--mode mcp`
- Avoids any desktop/Tk run path (you will run `web` mode only)

Run web mode with local run scripts:

macOS/Linux:

```bash
./local-run.sh --mode web --host 0.0.0.0 --port 8080
```

Windows PowerShell:

```powershell
./local-run.ps1 --mode web --host 0.0.0.0 --port 8080
```

Optional local dev hot reload:

```bash
./local-run.sh --mode web --host 127.0.0.1 --port 8000 --reload
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[web]"
```

## Start the Web Server

### Local workstation

```bash
oci-policy-analysis-web --host 127.0.0.1 --port 8000
```

Open:

`http://127.0.0.1:8000`

### Server-hosted deployment

Bind to an interface reachable by clients:

```bash
oci-policy-analysis-web --host 0.0.0.0 --port 8080
```

Example background launch:

```bash
nohup oci-policy-analysis-web --host 0.0.0.0 --port 8080 > oci-policy-analysis-web.log 2>&1 &
```

## Load Balancer Guidance

For production/team setups, place the web service behind a load balancer or reverse proxy.

Typical pattern:

- LB listener: `443` (TLS)
- Backend target: app host `http://<server>:8080`
- Health check: `GET /health`
- Preserve/forward standard headers (for traceability/logging)

Notes:

- Terminate TLS at the load balancer.
- Restrict backend port access to LB/security group sources.
- Use DNS (for example `policy-ui.example.com`) mapped to LB public endpoint.

## First Browser Login: Runtime Access Key

On each web server startup, OCI Policy Analysis generates a **runtime access key** and prints it in server logs at startup.

You will see output similar to:

- `WEB UI ACCESS KEY REQUIRED`
- `WEB_UI_RUNTIME_ACCESS_KEY: <generated-key>`

Important behavior:

- The key is **generated at startup**.
- The key **rotates every server restart**.
- Browser users must **copy/paste** this key into the web login modal to unlock pages.

If users report “Invalid access key”:

1. Confirm they copied the exact current key from current server logs.
2. Confirm the server was not restarted after the key was shared.

## Permissions Required and Authentication

Web mode uses the shared OCI IAM permissions and authentication models.
For complete policy statements and auth details, see the [Setup guide](setup.md).

## Quick Post-Deploy Validation (Web)

After login, validate a few core pages:

- Policy Analysis
- Historical Analysis
- Recommendations
- Consolidation Workbench
- Reference Data (including API Operations Tester)

## Troubleshooting (Web)

- Cannot reach page: verify `--host/--port`, firewall/security lists, and LB backend health.
- 502/503 behind LB: verify backend target and `GET /health` response.
- Login blocked: use current startup runtime key from server logs.
- Dependency errors: confirm virtualenv active and `pip install -e ".[web]"` succeeded.

## Related Core-Only Setups

If you do **not** need web hosting and want a lighter install profile:

- CLI-only/core-only setup: [CLI docs](cli.md)
- MCP-only/core-only setup: [MCP docs](mcp.md)
