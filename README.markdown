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

This guide is designed for users new to Python, covering setup on Windows and Linux. The application requires Python 3.13 or higher and specific dependencies.

### Prerequisites
1. **Python 3.13+**:
   - **Windows**:
     - Download and install Python from [python.org](https://www.python.org/downloads/). Choose the latest version (3.13 or higher).
     - During installation, check "Add Python to PATH" to make Python accessible from the command line.
   - **Linux**:
     - Most distributions include Python. Verify with `python3 --version`.
     - If not installed or outdated, install it:
       ```bash
       sudo apt update && sudo apt install python3.13 python3-pip  # Ubuntu/Debian
       sudo dnf install python3.13 python3-pip  # Fedora/RHEL
       ```
2. **OCI SDK and Dependencies**:
   - The application requires the `oci`, `ttkbootstrap`, and `tksheet` Python packages.
3. **OCI Configuration**:
   - For non-Instance Principal authentication, create an OCI configuration file at `~/.oci/config` (Linux) or `%USERPROFILE%\.oci\config` (Windows) with a profile (e.g., `DEFAULT`). Example:
     ```ini
     [DEFAULT]
     user=ocid1.user.oc1..<your-user-ocid>
     fingerprint=<your-api-key-fingerprint>
     key_file=<path-to-private-key.pem>
     tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
     region=<your-region, e.g., us-ashburn-1>
     ```
     See [OCI SDK Configuration](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for details.
   - For Instance Principal authentication, ensure the application runs on an OCI compute instance with appropriate IAM policies.

### Installation
1. **Clone or Download the Code**:
   - Download the `oci_policy_dg_viewer.py` script or clone the repository:
     ```bash
     git clone <repository-url>
     cd <repository-directory>
     ```
   - Alternatively, save `oci_policy_dg_viewer.py` to a local directory.

2. **Install Dependencies**:
   - Open a terminal (Windows: Command Prompt or PowerShell; Linux: any terminal).
   - Install required packages:
     ```bash
     pip install oci ttkbootstrap tksheet
     ```
   - If you encounter permission errors on Linux, use:
     ```bash
     pip install --user oci ttkbootstrap tksheet
     ```

3. **Run the Application**:
   - Navigate to the directory containing `oci_policy_dg_viewer.py`.
   - Run the script:
     ```bash
     python3 oci_policy_dg_viewer.py
     ```
     On Windows, you may use:
     ```bash
     python oci_policy_dg_viewer.py
     ```
   - For verbose logging (useful for debugging), add the `-v` flag:
     ```bash
     python3 oci_policy_dg_viewer.py -v
     ```

4. **Using the Application**:
   - **Authentication**:
     - If running on an OCI compute instance, check "Instance Principal" to use instance-based authentication.
     - Otherwise, select a profile from the dropdown (e.g., `DEFAULT`) matching your OCI config file.
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
To run the application without installing Python, you can package it as a standalone executable using `PyInstaller`:
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