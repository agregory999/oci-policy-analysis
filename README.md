# OCI Policy and Dynamic Group Viewer

## Overview
The **OCI Policy and Dynamic Group Viewer** is a graphical desktop application built with Python and Tkinter for Oracle Cloud Infrastructure (OCI) administrators. It allows you to analyze and visualize OCI policies, dynamic groups, and user permissions within a tenancy. Key features include:

- **Policy Analysis**: View and filter IAM policy statements across compartments, with details like subject, verb, resource, and conditions.
- **Dynamic Group Analysis**: Display dynamic groups, their matching rules, and check for unused groups.
- **User Analysis**: Filter policy statements applicable to a user based on their group memberships, with compartment filtering.
- **Advanced Analysis**: Placeholder for principal-based analysis (e.g., Instance Principal, Resource Principal).
- **Caching**: Save and load data to/from a local cache for faster access.
- **Export**: Export filtered data to CSV for further analysis.
- **Cross-Platform**: Runs on Windows and Linux with a user-friendly GUI.

The application supports both Instance Principal authentication (for OCI compute instances) and OCI configuration file-based authentication (using named profiles).

## Getting Started

This guide is designed for users new to Python, covering setup on Windows and Linux. The application was tested with Python 3.11+ and specific dependencies.

There are 3 ways you can use the tool -
1) Via pre-built executables, which are built for Linux, MacOS, and Windows.  
2) Install the required Python version, python packages, ensure TKInter UI elements are working, and run from your system with full UI.
3) Install the required Python version, python packages, and run directly from the command line only.

All 3 options require either a configured OCI Profile or Instance Principal, see [below](#oci-configuration) for details.

## Prerequisites

All of what you need to get started.  

### Python 3.11+

This is only required if you are not running the executables, which have the appropriate Python version baked in

- **Windows**:
  - Download and install Python from [python.org](https://www.python.org/downloads/). Choose the latest version (3.11 or higher).
  - During installation, check "Add Python to PATH" to make Python accessible from the command line.
- **Linux**:
  - Most distributions include Python. Verify with `python3 --version`.
  - If not installed or outdated, install it:
    ```bash
    sudo apt update && sudo apt install python3.11 python3-pip  # Ubuntu/Debian
    sudo dnf install python3.11 python3-pip  # Fedora/RHEL
    ```

### OCI SDK and Dependencies
   - The application requires the `oci`, `ttkbootstrap`, and `deepdiff` Python packages. These can be installed using `pip install` or `uv pip install`.  See below for details

### OCI Configuration

This section is **REQUIRED** in order to use the tool, regardless of whether you use the executable, the script with UI, or the script without UI.

For non-Instance Principal authentication, create an OCI configuration file at `~/.oci/config` (Linux) or `%USERPROFILE%\.oci\config` (Windows) with a profile (e.g., `DEFAULT`). Example:
```ini
[DEFAULT]
user=ocid1.user.oc1..<your-user-ocid>
fingerprint=<your-api-key-fingerprint>
key_file=<path-to-private-key.pem>
tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
region=<your-region, e.g., us-ashburn-1>
```

See [OCI SDK Configuration](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for details.

For Instance Principal authentication, simply ensure the application runs on an OCI compute instance with appropriate IAM policies.

### OCI Permissions

This section is **REQUIRED** in order to use the tool, regardless of whether you use the executable, the script with UI, or the script without UI.

This tool requires minimal permissions to OCI.  Permissions to operate can be granted in 2 ways and are the same set of overall permissions.  

The minimal policy statement looks like this:

```
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT} in tenancy
```

**NOTE** If you already have read access to policies, compartments, and domains, you should be good to go.  

In a new tenancy or a tenancy where you are not sure about changing existing permissions, you can have a user created for yourself by the admin, and then have them create a Group and add you (and others).  Suppose this group is called `PolicyAuditorGroup`.  Then add a policy called `PolicyAnalysisPolicy` in the tenancy root, where the only statement is what is above.

If you plan to use Instance Principal via an OCI Compute Instance you run the tool from, you must have that instance part of a dynamic group.  For example, create a Dynamic Group in the Default Identity Domain called `PolicyAnalysisDynamicGroup`, defined by a matching rule `instance.id = 'your instance ocid'`.  Then, define your `PolicyAnalysisPolicy` like this:

```
allow dynamic-group 'Default'/'PolicyAnalysisDynamicGroup' to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT} in tenancy
```

Once created, download the tool or clone the repository from your OCI instance and give it a try.

### TKInter / TTKBootstrap Configuration

Only required for locally running the scripts.

   - TKInter for UI - Detailed information is maintained here: [Python TKInter](https://docs.python.org/3/library/tkinter.html#)
   - Both `deepdiff` and `ttkbootstrap` are in addition to the core TKInter installation and are installed via PIP.
   - TTKBootstrap improves the look and feel of TKInter applications.  Many of the widgets (ie dropdowns) are based on TTKBootstrap.  More on that here: [TTKBootstrap](https://ttkbootstrap.readthedocs.io/en/latest/)

## Installation

Basic steps to get started.

### Executable

Download the latest release from your platform from the [Releases](https://github.com/agregory999/oci-policy-analysis/releases) page in the repository

Click on it.

If you have a valid PROFILE or Instance Principal set up already, you should be able to Load from Tenancy

### Build and Run

This requires cloning the repository, setting up your Python environment, and running the script with or without UI from the command line. 

### Clone Repo

```bash
git clone <repository-url>
cd <repository-directory>
```

All source code will be under the `src/` directory.

### Python Version and PIP

To verify python is installed on yoru system, from the command line, and within the repo directory:

```bash
prompt: repo dir> python -V
```
or 
```bash
prompt: repo dir> python3 -V
```

If you get python 3.11 or up, do the same with PIP and get a list of currently installed packages:

```bash
prompt: repo dir> python -m ensurepip
prompt: repo dir> pip -V
prompt: repo dir> pip list
```

#### Virtual Environments (recommended)
For users utilizing Virtual Environments, feel free to create a new VENV using:
```bash
prompt: repo dir> python -m venv venv
prompt: repo dir> source venv/bin/activate
prompt: repo dir> pip list
```

Once PIP is ready, proceed to the next section
### Install Dependencies

Install required packages for the tool:
```bash
pip install oci ttkbootstrap deepdiff markdown
```
If you encounter permission errors on Linux, use a user install.  Note that for virtual environments, this is unlikely to happen to you.  It can happen for the machine-based python installation, if you are not an administrator:
```bash
pip install --user oci ttkbootstrap deepdiff markdown
```

### Ensure TKInter 

As mentioned, ensure that tkinter is working.

```bash
prompt: repo dir> python -m tkinter
```

If you get the popup, close it and proceed.  If not, refer to the TKInter documentation to get it running on your platform.

## Run the Application with UI

Navigate to the repository.  You can run the program directly from the repository directory.

Run the UI using `python` or `python3`, depending on how you have your Python installation:
```bash
prompt: repo dir> python3 src/oci_policy_dg_viewer.py
```
On Windows, you may use:
```bash
prompt: repo dir> python src\oci_policy_dg_viewer.py
```

For verbose logging (useful for debugging), add the `-v` flag:
```bash
prompt: repo dir> python3 src/oci_policy_dg_viewer.py -v
```
Logging output may assist you with issue tracking, but it is better to leave verbose logging disabled (no option given) unless there are issues.   

## Using the Application UI

   - **Authentication**:
     - If running on an OCI compute instance, check "Instance Principal" to use instance-based authentication.
     - Otherwise, select a profile from the dropdown (e.g., `DEFAULT`) matching your OCI config file.
     - TODO
   - **Load Data**:
     - Click "Load from Tenancy" to fetch policies, dynamic groups, and user data from OCI.
     - Click "Load from Cache" to use previously saved data (stored in `~/.oci/cache/` or `%USERPROFILE%\.oci\cache\`).
   - **Tabs**:
     - **All Policies**: Filter and view all policy statements.
     - **Dynamic Groups**: Analyze dynamic groups and their usage.
     - **User Analysis**: Select an identity domain, user, and compartment, then click "Analyze User" to view applicable policies.
     - **Advanced Analysis**: Placeholder for principal-based analysis.
   - **Export**: Use the "Export CSV" buttons to save filtered data.

### Running as an Executable
To run the application without installing Python, you use the pre-built standalone executable (built using `PyInstaller --one-file`) :
1. **Install PyInstaller**:
   ```bash
   pip install pyinstaller
   ```
2. **Create the Executable**:
   - In the directory with `oci_policy_dg_viewer.py`, run:
     ```bash
     pyinstaller --onefile oci_policy_dg_viewer.py
     ```
   - This creates a single executable in the `dist/` folder.
3. **Run the Executable**:
   - On Windows: Double-click `dist\oci_policy_dg_viewer.exe` or run it from the command line.
   - On Linux: Run `./dist/oci_policy_dg_viewer` from a terminal.
   - Note: The executable requires the OCI config file for non-Instance Principal authentication, and Instance Principal still requires running on an OCI compute instance.
4. **Troubleshooting**:
   - Ensure the OCI config file is in the correct location.
   - For large tenancies, the executable may take longer to start due to bundled dependencies.
   - If issues arise, run with `-v` for verbose logging: `oci_policy_dg_viewer.exe -v`.

### Notes
- **Permissions**: Ensure your OCI user or instance has IAM permissions to read policies, dynamic groups, compartments, identity domains, and user group memberships.
- **Cache**: Data is cached in `~/.oci/cache/` (Linux) or `%USERPROFILE%\.oci\cache\` (Windows) to speed up subsequent loads.
- **Support**: This is not an official Oracle application and is not supported by Oracle Support. For issues, check the logs or contact the repository maintainer.

## Run the Application (non-UI)

To run with no UI, this section is in progress.  Essentially we can run the core, which loads the policies from cache or the tenancy, and simply outputs them to the console.  Filtering and export will be added in a later release

```bash 
prompt: repo dir> python src/oci_policy_dg_viewer/oci_policy_dg_core.py
```
