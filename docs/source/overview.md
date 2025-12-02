# Overview

**OCI Policy Analysis** is a graphical desktop application built with Python and Tkinter for Oracle Cloud Infrastructure (OCI) administrators. It allows you to analyze and visualize OCI policies, dynamic groups, and user permissions within a tenancy—across all compartments and users.

## Core Features

- **Policy Analysis**: View and filter parsed IAM policy statements across compartments, seeing key fields like subject, verb, resource, and conditions.
- **Dynamic Group Analysis**: Display dynamic groups, review their matching rules, and check for unused groups.
- **Resource Principal & User Analysis**: Explore resource principals and analyze policy statements applicable to a user's group memberships.
- **Historical Comparison**: Find differences between policy sets from current vs previous data loads.
- **Policy Overlap**: See where policy statements overlap in what they are granting
- **Caching**: Save/load all policy and identity data to local cache for fast/remote use.
- **Export & Import**: Export filtered analysis results to CSV or JSON for sharing or offline audit.
- **Cross-Platform GUI**: Runs on Windows and Linux with an easy-to-use GUI.
- **AI Insights**: Get GenAI explanations to help interpret each policy statement.
- **MCP Server**: Expose your tenancy as an MCP server and answer policy questions from tools like Claude or VSCode using your real data.

The application supports both Instance Principal authentication (OCI compute instances) and OCI CLI/config file-based authentication (using named profiles).


