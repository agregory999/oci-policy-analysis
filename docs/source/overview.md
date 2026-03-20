# Overview

**OCI Policy Analysis** is a graphical desktop application built with Python and Tkinter for Oracle Cloud Infrastructure (OCI) administrators. It allows you to analyze and visualize OCI policies, dynamic groups, and user permissions within a tenancy—across all compartments and users.

## Core Features

- **Policy Analysis**: View and filter parsed IAM policy statements across compartments, seeing key fields like subject, verb, resource, and conditions.
- **Dynamic Group Analysis**: Display dynamic groups, review their matching rules, and check for unused groups.
- **Resource Principal & User Analysis**: Explore resource principals and analyze policy statements applicable to a user's group memberships.
- **Historical Comparison**: Find differences between policy sets from current vs previous data loads.
- **Caching**: Save/load all policy and identity data to local cache for fast/remote use.
- **Export & Import**: Export filtered analysis results to CSV or JSON for sharing or offline audit.
- **Cross-Platform GUI**: Runs on Windows and Linux with an easy-to-use GUI.
- **AI Insights**: Get GenAI explanations to help interpret each policy statement.
- **Context Help**: Context Sensitive help is displayed throughout the tool, depending on page, section, and UI widget.

## Advanced Features
- **Condition Tester**: Evaluates a hypothetical where clause based on user inputs for known variables.
- **Permissions Report**: Show all granted or denied underlying OCI permissions by compartment and principal
- **MCP Server**: Expose your tenancy as an MCP server and answer policy questions from tools like Claude or VSCode using your real data.
- **API Simulation**: Attempt to determine *if* an OCI API call can be made, based on the principal and where clause values.  Allows prospective statements to be added per tenancy, which are evaluated as if they were real.
- **Recommendations**: Generate and catalog potential issues, changes, overlaps, limit issues, and other suggestions with a workbench-style approach that supports offline activity.

The application supports Instance Principal authentication (OCI compute instances), OCI CLI/config file-based authentication (using named profiles), and Session Token Authentication.


