# Desktop Setup

Use this guide when you want to run OCI Policy Analysis as a **desktop application** (Tkinter).

## Choose Desktop Setup When

- You want a local, single-user workflow.
- You prefer the full tabbed desktop UI.
- You do not need browser/server deployment.

## Installation Options

### Option A: Platform executable (no Python required)

1. Go to the [GitHub releases page](https://github.com/agregory999/oci-policy-analysis/releases).
2. Download the latest build for your platform:
   - **Windows:** `.exe` installer
   - **macOS:** `.app` bundle (possibly in `.zip`/`.dmg`)
3. Launch the app normally from your OS.

### Option B: Run from source (recommended for development)

#### 1) Verify Python version

Desktop/source runs require **Python 3.12+**.

```bash
python3 -V
```

#### 2) Verify Tkinter availability

```bash
python3 - << 'EOF'
import tkinter
print("Tkinter is available.")
EOF
```

If missing:

- **Linux (Debian/Ubuntu):** `sudo apt-get install -y python3-tk`
- **macOS/Windows:** prefer official Python installer from python.org.

#### 3) Create and activate virtual environment

```bash
git clone https://github.com/agregory999/oci-policy-analysis.git
cd oci-policy-analysis
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
```

#### 4) Install and run desktop mode

```bash
python -m pip install --upgrade pip
pip install -e .
python -m oci_policy_analysis.main
```

## Helper Scripts (optional)

- macOS/Linux:

```bash
./local-build.sh --mode desktop
./local-run.sh --mode desktop
```

- Windows PowerShell:

```powershell
./local-build.ps1 --mode desktop
./local-run.ps1 --mode desktop
```

## Permissions & Authentication

Desktop mode uses the shared OCI IAM permissions and authentication models.
For complete policy statements and auth details, see [Setup: Permissions Required and Authentication](setup.md#permissions-required-and-authentication).

## Troubleshooting (Desktop)

- Tkinter import failures: confirm OS Tk package / python.org build.
- Python mismatch: use Python 3.12+.
- Dependency issues: re-activate `.venv`, reinstall with `pip install -e .`.

## Related Core-Only Setups

If you want to run **without desktop UI** and keep pip install minimal:

- CLI-only/core-only setup: [CLI docs](cli.md#install-profiles-core-vs-webdesktop)
- MCP-only/core-only setup: [MCP docs](mcp.md#core-only-install-for-mcp-no-webdesktop-extras)
