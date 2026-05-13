# OCI Policy Analysis

Analyze Oracle Cloud IAM policies and identity data.

📘 **Full documentation:**  
👉 [https://agregory999.github.io/oci-policy-analysis](https://agregory999.github.io/oci-policy-analysis)

## Limited Mode (Web)

- Overview doc: [docs/source/limited_mode.md](docs/source/limited_mode.md)

## Quick Start (Desktop App)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m oci_policy_analysis.main
```

## Quick Start (Web App Only)

If you want web mode only (no desktop/Tk workflow):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"
oci-policy-analysis-web --host 127.0.0.1 --port 8000
```

Then open: `http://127.0.0.1:8000`

## Quick Start (Using Local Helper Scripts)

Build and run by mode:

```bash
./local-build.sh --mode web
./local-run.sh --mode web --host 127.0.0.1 --port 8000
```

Other supported modes:

- `desktop`
- `web`
- `cli`
- `mcp`
- `all` (build script only)

## Server / Nohup Example (Web)

```bash
nohup ./local-run.sh --mode web --host 0.0.0.0 --port 8080 > oci-policy-analysis-web.log 2>&1 &
```

Check process/logs:

```bash
ps -ef | grep oci-policy-analysis-web
tail -f oci-policy-analysis-web.log
```

## Run the Web App via PyPI (no repo clone)

(Won't work until out of beta)

Install in a virtual environment and run the packaged web entrypoint:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install "oci-policy-analysis[web]"
oci-policy-analysis-web
```

For server usage, you can run with explicit bind options:

```bash
oci-policy-analysis-web --host 0.0.0.0 --port 8080
```

Example startup script (`start-oci-policy-analysis-web.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

source /opt/oci-policy-analysis/.venv/bin/activate
exec oci-policy-analysis-web --host 0.0.0.0 --port 8080
```

Then make executable and run:

```bash
chmod +x start-oci-policy-analysis-web.sh
./start-oci-policy-analysis-web.sh
```

Or run a packaged release right from your desktop:
```bash
oci-policy-analysis.exe   # Windows
oci-policy-analysis.app   # macOS
```

For the executables, disable the OS Security for the application so it can run.  
- MAC: Settings -> Privacy & Security - Open Anyway
- Windows: Double-click EXE -> More Info - Run Anyway

![Mac](/images/mac_security_bypass.png)
![Windows](/images/windows_security_bypass.png)
