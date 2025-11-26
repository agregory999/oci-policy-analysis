# Usage

## Getting Started

This section will help you set up and run OCI Policy Analysis regardless of platform.

### 1. Prerequisites

- **Python 3.12+** if running from source. (Not needed for platform executables.)
  - Get Python from [python.org](https://www.python.org/downloads/), or use your OS package manager.
- **OCI Configuration** (`~/.oci/config` or `%USERPROFILE%\.oci\config`)
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

- **OCI IAM Policy Permissions**
  - Minimal permissions:
    ```
    allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT} in tenancy
    allow group <your_group> to use generative-ai-family in tenancy
    ```
  - See [Permissions Section](./overview.md) for instance principal option and dynamic group setup.

- **Install Dependencies if running from source**
  ```bash
  pip install oci ttkbootstrap deepdiff markdown
  ```

### 2. Installation

**Option A: Run as a platform executable**
  - Download the appropriate binary (.exe for Windows, .app for macOS, Linux build) from the [releases page](https://github.com/agregory999/oci-policy-analysis/releases).
  - Double-click/run as any other application.

**Option B: Run from source (recommended for advanced users/developers)**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate    # On Win: .venv\Scripts\activate
  pip install -e .
  python -m oci_policy_analysis
  ```

**Option C: Command-line only (no UI, experimental)**
  ```bash
  python src/oci_policy_dg_viewer/core.py --help
  # (see CLI options)
  ```

#### Checking that TKInter is working

After installing prerequisites:
```bash
```
If you get a popup window, you’re set.

### 3. Authentication and Session Token Setup

You can authenticate using:
- Named OCI Profile
- Instance Principal on OCI Compute
- Session Token (`oci session authenticate`, see Settings tab for input)

See [OCI Authentication](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for more.

### 4. Running/Using the App

**Load Data**:
- Choose authentication in the Settings tab.
- Use **Load from Tenancy** or **Load from Cache**.

**Tabs**:

- **Policies** — Browse & filter policy statements.
- **Users / Groups / Dynamic Groups** — Explore relationships/memberships.
- **Overlap Detection** — Find potential redundant/conflicting statements.
- **Historical Comparison** — Compare cached snapshots.
- **MCP / AI** — Run as FastMCP server and get GenAI analysis.

**Export/Import**:
- Use Export/Import buttons for CSV/JSON as needed.

**See also**:
- [Overview](overview.md) for a feature/architecture summary.
