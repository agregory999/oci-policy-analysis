# Usage

There are 3 main entry points to the OCI Policy Analysis application:

1) User Interface -- the main UI
2) Command Line access -- the CLI
3) Model Context Protocol -- the MCP Server

MCP is covered in its ![own document](./mcp.html), so keep reading for what the main application is capable of and how to use it.

## Starting the UI

This page does not cover building the application or setting up Python and the libraries.  For that, see the complete ![Setup Guide](./setup.html).

The UI can be started from a downloaded executable file simply by double-clicking on it.  For Mac and Windows you will need to give permission for the app to run locally until which time the python executable can be shipped as a trusted publisher.

From the command line, after building the application, start via python:

```bash
python src/oci_policy_analysis/main.py
```

## Settings Tab (Start Here)

All settings and loading of tenancy information is controlled on this tab.   

### Tenancy and Config

Tenancy data consists of IAM data (users, groups, dynamic groups) and policy data (statements).  The compartment hierarchy is also loaded here.  Loading involves the program making API calls to OCI, and thus the configuration section surfaces multiple means of accessing the tenancy.  

1) Profile-based -- Load all available profiles from the machine the UI is started from, and allow the choice of a profile to load from.  Profiles are tied to an OCI User, which must be in a Group where the required permissions to load IAM and Policy data exist.  See ![Setup / Permissions](./setup.html) for more detail.

2) Instance Principal -- If you have an Instance Principal, you must have a Dynamic Group with permissions.  This only works on an OCI Compute Instance.

3) Session Token -- If you use session tokens for temporary access, you can define the token and load data, provided that the OCI User has the appropriate Group and Permission to load data. 

**Recursion Option** -- This allows you to avoid loading the entire tenancy compartment hierarchy.  It will only load Policy data from the root compartment.  If your tenancy has all policies in the root compartment and 100s or 1000s of nested compartements with no policy data at lower levels, this will help with loading time.

Once one of the loading options is selected, you can watch the progress using the indicator under the export button, or look at the logs from your console or the UI option for "Console Tab".  Once loaded, the date of the data load is displayed and other tabs will display data.

### Import and Export

The UI allows for import and export of data.  Internally and within the cache, a large JSON object is stored, containing all available data.  This can be exported into a JSON file, for example if required by Oracle personnel to look at a policy problem.   

For import, this can be used instead of loading data from a tenancy or cache.  In cases where a user has no tenancy access but aims to help a customer, the export is imported and can be looked at using the tool as if it was loaded locally.

### Generative AI Enablement

GenAI is optional.   To use it, you must use the Settings tab and follow the steps here.

1) Refresh the GenAI Models.  Choose one that makes sense, such as "Grok 4 - fast, non-reasoning".  Others work as well, but not all have been tested.
2) Confirm Regional Endpoint -- this defaults to your OCI home region, so it is unlikely to change, but could if necessary.
3) Confirm Compartment (for GenAI) -- this defaults to your tenancy OCID, so it is unlikely to change, but could if necessary.
4) Apply and Test GenAI -- Run a test AI call, which should succeed if permissions are set up properly and the model works
5) Toggle AI Pane -- Adds the AI pane to the bottom of the window, which then appears on all tabs and can be used.

Once AI has been enabled and the AI pane is toggled, each tab in the UI will have varying uses for it.  For example, on the Policy tab, it is used to generate additional insights about a specific policy statement.

### Display Options

Settings for font size, additional tabs.

### Embedded MCP Server

The only options here are a host and port.  If the MCP embedded server is started, it will use these settings to start.  Provided there isn't a listening service on the selected port, the service will start from the "Embedded MCP" tab using these.

**0.0.0.0** - Listens on all addresses for the machine, including publicly accessible IP addresses
**127.0.0.1** - Listens only on `localhost` on the machine, only accessible from other local processes.  For example, VSCode or Claude Desktop on your machine.

**See also**:
- [Overview](overview.md) for a feature/architecture summary.

## Policy Tab

## Groups / Users Tab

## Dynamic Groups Tab

## Resource Principals Tab

## Cross Tenancy Tab

## Policy Overlap Tab

## Permissions Report Tab

## Reports w/Search Tab

Displays all Policy data in text form with a search box.  The search highlights in yellow anywhere a given string is found in the data.

## Embedded MCP Tab

Starts (cannot stop) the embedded MCP server.  Logs which are MCP-specific appear here

The Debug option allows for the logs to display more information as each call is recieved and processed.

## Console Tab

If enabled, shows the `sysout` information.  This is helpful when starting from an executable file, where there is no log output.  

## Maintenance Tab

Allows for rename, delete, or preservation of cache files.  Caches are rotated as new data is loaded, but if they are preserved here, they can remain after they normally would be pruned.  

Also here are permissions information, with the ability to query the loaded permission reference files.  TODO: in a future release, adding permission to resource mappings may be possible via this tab.