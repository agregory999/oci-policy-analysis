# Setup

**Tip:** The full Setup Guide can be quickly accessed from within the application UI — just click the “Setup Guide” link in the Settings tab, to the right of the “Compartment Level for Additional Domains” dropdown. All core setup details, tips, and troubleshooting are always just a click away.

This page walks you through getting OCI Policy Analysis installed and running on any supported platform. You can:

- install a **platform-specific executable** (no local Python required), or
- run the application **from source** (recommended if you want to fork the repository, make code changes, or keep up with local development).

If you are using the official executables from the releases page, there are **no specific Python requirements** on your system — Python is only required when running from source.

The sections below cover:

1. [Installation](#installation)
2. [Permissions](#permissions-required)
3. [Authentication](#authentication)
4. [Troubleshooting](#troubleshooting)

---

## Installation

You have two primary options for installing and running OCI Policy Analysis.

### Option A: Platform Executable (no Python required)

Use this option if you just want to run the tool and do **not** plan to modify the source code.

1. Go to the [GitHub releases page](https://github.com/agregory999/oci-policy-analysis/releases).
2. Download the latest build for your platform:
   - **Windows:** `.exe` installer
   - **macOS:** `.app` bundle (may be wrapped in a `.dmg` or `.zip`)
3. Run the installer or application as you would any other program on your OS.

When using a platform executable:

- You **do not** need to install Python.
- Python dependencies are bundled inside the executable.
- You can still follow the sections below on **Permissions**, **Authentication**, and **Troubleshooting** — these apply regardless of how the app was installed.

### Option B: Run from Source (required for development/forks)

Running from source is **more flexible** and is required if you:

- plan to fork the repository,
- want to modify or extend the application,
- want to run directly from a local checkout (e.g., for testing or contributing).

This section walks through, in order:

1. Ensuring you have a supported Python version
2. Verifying that Tkinter (the UI toolkit) is available
3. Creating and using a Python virtual environment (per platform)
4. Installing and running the project using helper scripts

#### 1. Verify Python version

OCI Policy Analysis expects **Python 3.12+** when running from source.

1. Install Python 3.12+ if needed:
   - Download from [python.org](https://www.python.org/downloads/), **or**
   - Use your OS package manager (e.g., `brew`, `apt`, `dnf`, `choco`).
2. Confirm your Python version:

```bash
python3 -V
```

You should see something like:

```text
Python 3.12.x
```

If your system uses `py` (Windows) or `python` as the primary command, adjust accordingly (e.g., `py -3.12 -V` or `python -V`).

#### 2. Verify Tkinter (UI toolkit)

The desktop UI is built with Tkinter. You must have Tkinter available in your Python installation.

From a terminal or command prompt, run:

```bash
python3 - << 'EOF'
import tkinter
print("Tkinter is available.")
EOF
```

If this succeeds and prints `Tkinter is available.`, you are good to go. If you see an `ImportError`, you likely need to install an OS-level Tk package and/or reinstall Python with Tkinter support:

- **macOS:**
  - Prefer the official installer from [python.org](https://www.python.org/downloads/) (includes Tk by default).
  - On some platforms, you may need to install `tcl-tk` via Homebrew and ensure Python is built/linked against it.

- **Linux (Debian/Ubuntu-based):**
  ```bash
  sudo apt-get update
  sudo apt-get install -y python3-tk
  ```

- **Windows:**
  - The standard Python installer from [python.org](https://www.python.org/downloads/windows/) includes Tkinter by default.
  - If Tkinter is missing, re-run the installer and make sure the `tcl/tk` or `Tkinter` option is selected.

Once Tkinter is available, continue to virtual environment setup.

#### 3. Create a virtual environment (per platform)

Using a virtual environment keeps project dependencies isolated and avoids conflicts with system Python packages. All commands below assume you are in the root of the cloned repository.

Clone the repository (if you have not already):

```bash
git clone https://github.com/agregory999/oci-policy-analysis.git
cd oci-policy-analysis
```

Create and activate a virtual environment:

- **macOS / Linux:**

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

- **Windows (PowerShell or cmd):**

  ```powershell
  py -3.12 -m venv .venv
  .venv\Scripts\activate
  ```

After activation, your prompt will typically show `(.venv)` at the beginning. All subsequent `python`/`pip` commands will use this environment.

#### 4. Install and run from source

Once your virtual environment is active, install the project and its dependencies:

```bash
python -m pip install --upgrade pip
pip install -e .
```

You can then run the application directly:

```bash
python -m oci_policy_analysis.main
```

##### Helper scripts (local install, run, clean)

For convenience, the repository includes helper scripts for local install, run, and clean. These wrap the steps above so you can copy/paste and not worry about the underlying Python details.

In the project root, you will find:

- **Shell scripts (macOS / Linux):**
  - `local-install.sh` *(if present; otherwise install via `pip install -e .` as shown above)*
  - `local-run.sh`
  - `local-clean.sh`
- **PowerShell scripts (Windows):**
  - `local-install.ps1` *(if present)*
  - `local-run.ps1`
  - `local-clean.ps1`

Typical usage on macOS / Linux:

```bash
cd oci-policy-analysis
python3 -m venv .venv
source .venv/bin/activate
./local-run.sh
```

Typical usage on Windows (PowerShell):

```powershell
cd oci-policy-analysis
py -3.12 -m venv .venv
.venv\Scripts\activate
./local-run.ps1
```

The `local-run` scripts generally handle installing dependencies if needed, running the app, and may be combined with the `local-clean` scripts to remove build artifacts.

---

## Permissions (REQUIRED)

The OCI Policy Analysis app requires a minimal set of IAM permissions in your tenancy. These permissions are the same whether you are using a platform executable or running from source.

For basic analysis, grant the following policies to a **less-privileged group** that your user belongs to:

```text
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow group <your_group> to use generative-ai-family in tenancy
```

For **dynamic group** (instance principal) usage on OCI Compute, grant the equivalent policies to a dynamic group (for example `PolicyAnalysisDynamicGroup`):

```text
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to use generative-ai-family in tenancy
```

### Group or Dynamic Group

If your user, group, or dynamic group already has these permissions, nothing further is needed. Otherwise, an administrator can:

1. Create a group or dynamic group.
2. Attach a policy with the statements above.
3. Add your user (for groups) or configure matching rules (for dynamic groups) via the OCI Console.

**See also**: [Overview](overview.md) for a feature summary and context on how these permissions are used.

---

## Authentication

Authentication options are the same whether you use an executable or run from source. You can configure authentication entirely from within the application’s **Settings** tab.

You can authenticate using:

- **Named OCI Profile** (from your OCI CLI config)
- **Instance Principal** (if running on an OCI Compute instance)
- **Session Token** (interactive, time-limited authentication)

### OCI configuration file

For profile-based authentication, the app uses the standard OCI configuration file:

- **Linux / macOS:** `~/.oci/config`
- **Windows:** `%USERPROFILE%\.oci\config`

Example `config` entry:

```ini
[DEFAULT]
user=ocid1.user.oc1..<your-user-ocid>
fingerprint=<your-api-key-fingerprint>
key_file=<path-to-private-key.pem>
tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
region=<your-region>
```

See the official [OCI configuration documentation](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for more details and examples.

If your config file is missing or mis-configured, the **Settings** tab in OCI Policy Analysis will highlight the problem and guide you to the missing values.

### Session token authentication

You can also authenticate using an OCI **session token**, typically created via the OCI CLI. For example:

```bash
oci session authenticate
```

Follow the prompts to generate a token. Then:

1. Open the **Settings** tab in OCI Policy Analysis.
2. In the **Session Token** section:
   - Paste the token text directly, **or**
   - Provide a path to the token file created by the CLI.

The app will use the session token for API calls until it expires.

### Instance principal authentication

When running on an OCI Compute instance configured with appropriate dynamic group policies, you can select **Instance Principal** in the Settings tab. The app will then use the instance’s identity and attached policies for authentication.

---

## Troubleshooting

This section lists common setup issues and quick checks you can run. These apply whether you are running from source or using the platform executables (except where Python-specific).

- **Python version errors (source installs only):**
  - Ensure you are using Python **3.12+**.
  - Check with:
    ```bash
    python3 -V
    ```

- **Missing dependencies (source installs only):**
  - Make sure your virtual environment is active:
    ```bash
    source .venv/bin/activate        # macOS / Linux
    .venv\Scripts\activate          # Windows
    ```
  - Re-install in editable mode:
    ```bash
    pip install -e .
    ```
  - The UI will warn about missing libraries when needed.

- **Tkinter / UI errors (source installs only):**
  - Run the Tkinter test snippet above and ensure `import tkinter` works.
  - On Linux, verify `python3-tk` (or equivalent) is installed.

- **OCI config not found or missing values:**
  - Confirm that `~/.oci/config` (Linux/macOS) or `%USERPROFILE%\.oci\config` (Windows) exists.
  - Ensure the profile name selected in the Settings tab matches an entry in the file.
  - The Settings tab will highlight missing or invalid configuration values.

- **Browser links don’t open automatically:**
  - The app always displays the URL next to any button that tries to open a browser.
  - Copy/paste the URL into your browser manually if automatic opening fails.

- **Firewall or network issues:**
  - If the app cannot reach OCI endpoints or documentation, confirm:
    - outbound HTTPS access is allowed,
    - any proxy settings are configured correctly,
    - your corporate firewall permits access to OCI endpoints and GitHub (if pulling updates).

- **Platform support:**
  - The UI is supported on Windows, macOS, and Linux desktop.
  - Some Linux distributions may require additional GUI libraries (e.g., X11/Wayland and Tk dependencies).

- **Logs and debugging:**
  - If you started the app from a terminal (source or executable), watch the console output for errors.
  - Increase logging verbosity via the app’s Settings or CLI options where available.

- **Tenancy / permissions problems:**
  - If you see access-denied errors or incomplete data:
    - Re-check the [Permissions](#permissions-required) section above.
    - Confirm your user or dynamic group is associated with the policy.
    - Use the OCI Console to verify group membership and dynamic group matching rules.

If you are still stuck, open an issue at [GitHub issues](https://github.com/agregory999/oci-policy-analysis/issues) and include:

- Your OS and version
- How you installed the app (executable vs. source)
- Python version (if running from source)
- Relevant console/log output
- The steps you followed before the issue occurred

This information will help us reproduce and resolve your issue more quickly.