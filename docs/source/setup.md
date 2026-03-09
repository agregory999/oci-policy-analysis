# Setup

**Tip:** The full Setup Guide can be quickly accessed from within the application UI — just click the “Setup Guide” link in the Settings tab, to the right of the “Compartment Level for Additional Domains” dropdown. All core setup details, tips, and troubleshooting are always just a click away.

This section will help you set up and run OCI Policy Analysis regardless of platform. Both a web UI and CLI invocation are supported.

## Prerequisites

- **Python 3.12+** is required if running from source (not needed for platform executables).
  - Install from [python.org](https://www.python.org/downloads/), or use your OS package manager.
  - **Check with:** `python3 -V`

- **OCI Configuration** (`~/.oci/config` for Linux/macOS, `%USERPROFILE%\.oci\config` for Windows)
  - Example:
    ```ini
    [DEFAULT]
    user=ocid1.user.oc1..<your-user-ocid>
    fingerprint=<your-api-key-fingerprint>
    key_file=<path-to-private-key.pem>
    tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
    region=<your-region>
    ```
  - See [OCI Configuration Docs](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm)
  - If your config is not found, the app’s Settings tab will highlight the missing/wrong file.

- **OCI IAM Policy Permissions**
  - Minimal required policies for functionality (see below).
  - Grant to your non-admin user/group or a dynamic group for instance principal use.

- **Dependency Installation (if running from source)**
  ```bash
  python3 -m pip install --upgrade pip
  pip install oci==2.164.0 deepdiff==8.5.0 fastmcp==2.12.5
  ```
  - **Best practice:** Always use a Python virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate   # On Windows: .venv\Scripts\activate
    pip install -e .
    ```

  - If not using a venv, you may need to add these packages system-wide using administrative rights.

## Installation Details

You have two options to run the code — either from an official platform-specific executable or from source.

**Option A: Platform Executable (no Python required)**
  - Download the latest installer for your OS from the [releases page](https://github.com/agregory999/oci-policy-analysis/releases).
  - Windows: `.exe` installer; macOS: `.app` bundle; Linux: appropriate build.
  - Double click/run as any application.

**Option B: Run from Source (recommended for advanced users/developers)**
  ```bash
  python3 -V              # Should report Python 3.12.x
  python3 -m venv .venv
  source .venv/bin/activate    # On Windows: .venv\Scripts\activate
  pip install -e .
  python -m oci_policy_analysis.main
  ```

## Authentication and Session Token Setup

You can authenticate using:

- **Named OCI Profile** (from your OCI CLI config)
- **Instance Principal** (if running on an OCI Compute instance)
- **Session Token** (use `oci session authenticate` to create a temporary token — paste this into the *Session Token* field in the Settings tab, or provide the file path).

Authentication options are all selectable in the *Settings* tab of the UI. The “Session Token” field accepts copy-and-paste text or a file.

See [OCI Authentication](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for more OCI API details.

## Permissions (REQUIRED)

The OCI Policy Analysis app requires a minimal set of permissions. For basic analysis, grant these to your user-group (less privileged is recommended):

```
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow group <your_group> to use generative-ai-family in tenancy
```

For dynamic group (instance principal) usage on OCI Compute:

```
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to use generative-ai-family in tenancy
```

### Group or Dynamic Group

If your user, group, or dynamic group already has these permissions, nothing further is needed. Otherwise, an administrator can create a group and add an appropriate policy.

**See also**: [Overview](overview.md) for feature summary.

## Troubleshooting & Tips

- **Missing dependencies?** Activate your venv (`source .venv/bin/activate`) and re-install packages (`pip install -e .`). The UI will warn about missing libraries as needed.
- **Python version errors?** Must be 3.12+. Confirm with `python3 -V`.
- **Browser links don’t open?** The app will always display the needed URL if automatic opening fails. Copy/paste it into your browser as needed.
- **OCI config not found or missing values?** The Settings tab guides you step by step and highlights config errors.
- **Firewall or network issues?** If the app fails to connect to OCI or open documentation, confirm your network/firewall/proxy settings and try again.
- **Platform support:** The UI works on Windows, macOS, and Linux (desktop). Some Linux builds may require additional GUI libraries.
- **Logs and debugging:** Check the terminal/console output for errors or run with increased verbosity for debugging.
- **Having issues setting up your tenancy or permissions?** Review the [Permissions](#permissions-required) section and OCI docs, and double-check group assignments in the OCI Console.

If you’re still stuck, open an issue at [GitHub issues](https://github.com/agregory999/oci-policy-analysis/issues) — include your setup steps and environment details.