# Setup

This section will help you set up and run OCI Policy Analysis regardless of platform.

## Prerequisites

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
    allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
    allow group <your_group> to use generative-ai-family in tenancy
    ```
  - See [Permissions Section](./overview.md) for instance principal option and dynamic group setup.

- **Install Dependencies if running from source**
```bash
pip install oci==2.164.0 deepdiff==8.5.0 fastmcp==2.12.5
```

NOTE -- if not using PIP via Python Virtual Environment, it is still possible, but you may need to add these packages to your system directly.

## Installation Details

Here are the options for running the code.   This will work from your desktop or from an OCI instance running Windows or Linux (Desktop).   If on OCI, you will be able to use the "Instance Principal" mechanism to authenticate.

**Option A: Run as a platform executable**
  - Download the appropriate binary (.exe for Windows, .app for macOS, Linux build) from the [releases page](https://github.com/agregory999/oci-policy-analysis/releases).
  - Double-click/run as any other application.

**Option B: Run from source (recommended for advanced users/developers)**
  ```bash
  python3 -V              # Should be 3.12.x
  python3 -m venv .venv
  source .venv/bin/activate    # On Windows: .venv\Scripts\activate
  pip install -e .
  python -m oci_policy_analysis.main
  ```

## Authentication and Session Token Setup

You can authenticate using:
- Named OCI Profile
- Instance Principal on OCI Compute
- Session Token (`oci session authenticate`, see Settings tab for input)

See [OCI Authentication](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for more.

## Permissions (REQUIRED)

In order for the OCI Policy Analysis app to pull the data it needs from the OCI tenancy, it must have a minimal set of permissions.  If using your OCI Admin (not recommended) user, the permissions will already be there.  It is recommended to use a non-privileged account or create a new user if you aren't sure.

The minimal policy statement looks like this:

```
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT} in tenancy
allow group <your_group> to use generative-ai-family in tenancy
```

If you plan to use instance principals on an OCI instance with a dynamic group, the permissions look like this:

```
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT} in tenancy
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to use generative-ai-family in tenancy
```

### Group or Dynamic Group

If you have an existing group or dynamic group for your instance or compartment, you may already have all of the permissions needed.  If you need to create a new user and group, the set of permissions above dictate what policy should exist for that user.

**See also**:
- [Overview](overview.md) for a feature/architecture summary.
