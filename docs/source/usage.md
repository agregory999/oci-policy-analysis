# Usage

There are 3 main entry points to the OCI Policy Analysis application:

1) User Interface -- the main UI
2) Command Line access -- the CLI
3) Model Context Protocol -- the MCP Server

MCP is covered in its [own document](./mcp.md), so keep reading for what the main application is capable of and how to use it.

## Starting the UI

This page does not cover building the application or setting up Python and the libraries.  For that, see the complete [Setup Guide](./setup.md).

The UI can be started from a downloaded executable file simply by double-clicking on it.  For Mac and Windows you will need to give permission for the app to run locally until which time the python executable can be shipped as a trusted publisher.

The UI can also be run the command line, after building the application, start via python:

```bash
python3 -V              # Should be 3.12.x
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -e .
python -m oci_policy_analysis.main
```

## Settings Tab (Start Here)

All settings and loading of tenancy information is controlled on this tab.   

### Tenancy and Config

Tenancy data consists of IAM data (users, groups, dynamic groups) and policy data (statements).  The compartment hierarchy is also loaded here.  Loading involves the program making API calls to OCI, and thus the configuration section surfaces multiple means of accessing the tenancy.  

1) Profile-based -- Load all available profiles from the machine the UI is started from, and allow the choice of a profile to load from.  Profiles are tied to an OCI User, which must be in a Group where the required permissions to load IAM and Policy data exist.  See [Setup / Permissions](./setup.md) for more detail.

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

#### Contextual Help

On each page, there is a contextual help area at the top of the tab.  Mousing over a section that has a specific message causes the message to be displayed at the top.  Enable the help on the Settings Tab with the "Context Help" checkbox.

#### Show Console / Debug

Enables tabs that show live console (shell) and is configurable down the level of individual loggers.  The JSON debugger gives access to larger internal JSON structures, primarily for debugging.

#### Show Maintenance Tab

Enables various maintenance operations, such as renaming caches, testing permissions, etc.

#### Show Advanced Tabs

Enabled multiple advanced tabs - Permissions Report, COndition Tester, API Simulation, and Recommendations tabs.

### Embedded MCP Server

The only options here are a host and port.  If the MCP embedded server is started, it will use these settings to start.  Provided there isn't a listening service on the selected port, the service will start from the "Embedded MCP" tab using these.

**0.0.0.0** - Listens on all addresses for the machine, including publicly accessible IP addresses
**127.0.0.1** - Listens only on `localhost` on the machine, only accessible from other local processes.  For example, VSCode or Claude Desktop on your machine.

**See also**:
- [Overview](overview.md) for a feature/architecture summary.


## Policy Browser Tab

This tab simply shows all compartments and policies in a hierarchy, with the ability to search for anything that appears in names, descriptions, or statements.  From there, it is possible to right-click and focus in on a specific policy, statement, or compartment.

## Policy Tab

Searching, sorting and filtering of all policy statements in a tenancy is available on this page.  When the policies are parsed into parts, each field is available in this tab.  Filters can be chained by simply by setting multiple fields and looking at the results.

### Sorting

Click the column headers to sort the results by that column

### Output Filters

Use the checkboxes to further filter the results by category.  For example, if the search in the top was for resource of `database`, statements returned could be for user, service, or dynamic groups.  The output filters control what is displayed.

#### Invalid Only

The invalid only checkbox controls whether to show only invalid statements (and reasons) matching the filter at the top.

#### Expanded Output

The parsed output from each policy is not shown by default, but can be enabled with this checkbox.  All available data is shown in the table, which will involve scrolling to the right.

### Policy Display

The list of matching policies is shown in a table format with columns determined by the output filters.  Additionally, there are some right-click options, such as a means to go to the OCI Console in a logged-in broweser, or further filter by similar effective path.  

Copy (Ctrl-C or Command-C on Mac) is available by clicking on a field in the output first.

### AI Insights

If the AI Insights is toggled on (see above), then by clicking on a row in the output of the policy data, the statement is placed in the AI policy analysis display input.  Clicking on the button below to generate insights runs a GenAI call to ask for the potential meaning and impact of the policy statement, which is then shown in the output area.

## Groups / Users Tab

Allows searching for policy statements by either Group or User.  All Policy Statements refer to groups, not users, so in order to determine the statements pertinent to a specific user or set of individual users (who may be in multiple and different groups), the selection of a user causes the program to determine the groups that user (or if multiple users are selected) is a member of, and then the policy statements for that collective set of groups is displayed.

Searching for users or groups is supported by username or user display name if the selector is ser to Users.  If set to groups, the name of the group is searched.

### GenAI Insights
Similar to other tabs, if AI Insights is toggled on, the selection of a policy statement will allow the user to generate insights as to the meaning of the policy statement.

## Dynamic Groups Tab

Lists all dynamic groups in all identity domains, with filters available.  Choosing a dynamic group will update the policy list below with policy statements pertaining to the selected dynamic group.

### Unused Dynamic Groups
This tab also allows you to see which Dynamic Groups are unused.  If hte Dynamic Group is not referenced in any policy statement, it is considered unused.  This isn't a problem, but can cause confusion.

If a dynamic group is show as unused but you think it shouldn't be, it is likely that the policy statement or dynamic group is not referring to correct identity domain.  Policy statements granting permission to a dynamic group within an identity domain MUST refer to the domain name in the policy statement like this:
```
allow dynamic-group 'id-domain-name'/'dynamic-group-name' to <verb> <resource> in <location>
```

### GenAI Insights
For Dynamic Groups, if AI Insights is toggled on, the selection of a policy statement will allow the user to generate insights as to the meaning of the policy statement, with the additional dynamic group detail as context.  

## Resource Principals Tab

Shows statements that are scoped by resource principal.  OCI Resource Principals are a specific ways to allow non-humans to perform actions within OCI.  Consider a [Autonomous Database](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/resource-principal.html) needing to access Object Storage.  The Resource in this case is defined as `resource.type = 'autonomousdatabase'`.  The syntax allows for 2 methods of defining and using Resource Principals, each with syntax that the tool can detect.

### Dynamic Group Resource Principals

A dynamic group is required, and in that dynamic group, the matching rule may contain the resource type or be chained with multiple other conditions.  Membership in the dynamic group is based on all or any rules, as per dynamic group syntax.

### Any-User Resource Principals

Resource Principals can also be defined using policy statements that avoid the need for Dynamic Groups.  The general format if using multiple conditions (per the ADB doc):

```
allow any-user to <verb> <resource> in <location> where ALL {resource.type = 'autonomousdatabase', resource.id = 'ocid.xx.yy'}
```
or if a single condition (for example, all ADB instances):
```
allow any-user to <verb> <resource> in <location> where resource.type = 'autonomousdatabase'

```
When searching for policy statements by the `any-user` style, the Resource Type selector allows selection of a specific type.  So for example all statements where `autonomousdatabase` is referenced in the resource principal statement.

## Cross Tenancy Tab

Shows the [cross-tenancy statements](https://docs.public.content.oci.oraclecloud.com/en-us/iaas/Content/Identity/policieshow/iam-cross-domain.htm), which are separated from "normal" policy statements.  These contain the following:

- **Define** - Gives a friendly name to an OCID from another tenancy.  This could refer to the tenancy OCID, compartment OCID, group OCID, or dynamic group OCID.  The friendly name (or alias) is used in cross-tenancy statements.

- **endorse or deny endorse** - Allows (or denies) a group or user from YOUR tenancy to access resources in ANOTHER tenancy using an alias  from a define statement 

- **admit or deny admit** - Allows (or denies) a named alias from ANOTHER tenancy to access resources in YOUR tenancy 

By selecting a define statement, the related cross-tenancy statements are shown.  

**NOTE:** No parsing is being done at this time - it is a TODO.

## Permissions Report Tab

Allows for a report of permissions granted by compartment and principal (group, service, dynamic group).  This information is generated using the policy data, the IAM data, and a set of reference data containing resource to permission mappings.  These mappings form the basis of actually is checked at runtime.  

## Historical Comparison Tab

Allows a comparison of policy data over time.  For example, if the tenancy IAM and policy set was loaded on some interval (ex: every 2 weeks), this tab allows a full comparison of policy and IAM data between now and then.  If anything changed, it will be highlighted.

## Embedded MCP Tab

Starts (cannot stop) the embedded MCP server.  Logs which are MCP-specific appear here

The Debug option allows for the logs to display more information as each call is recieved and processed.

## Condition Tester Tab

Allows a test of a specific where clause with parsing and analysis.  The potential values from the where clause are loaded and can be tested with values to see if the where clause passes.  

## API Simulation

Creates and runs a scenario where a test of an OCI API is available.  See [Simulation](./simulation.md) for more details.

## Recommendations Tab

**NOTE:** Work in Progress

This tab and sub-tabs are where the intelligence that is gathered is displayed.  It shows the general recommendations, derived as counts of specific items identified as potential issues or risks.

### Risk Details

Scores each policy statement with a risk number, normalized against all statements in tenancy.  Based on the overall number of permissions granted, and the compartment exposures.  For example, `manage` verbs against a family resource will score higher, and if exposed to a large compartment hierarchy, the overall score will be higher.

Where clauses can limit exposure, so there is control over estimating the reduction of exposure against unlimited (no where clause) statements.

### Overlap Details
Allows for inspection of overlapping policies for each policy statement.  Each policy statement references a given list of subjects, applies to a specific effective path, and covers a verb/resource or set of individual permissions.  If any other policy has an overlap, this can be detected.  

Resources in OCI are comprised of underlying permissions, so it is possible to conflict where a resource from one policy statement and a permission from another conflict.

When there are conflicts, it is not necessarily a problem.  However, if a statement is removed, the permission may still be covered by another statement.  Seeing this information can help detect what will happen if changes are made.

### Consolidation Details

Consolidation is where it may be possible to detect and take action on reducing multiple statements or policies into more concise or more succinct policy statements.  Currently partially implemented, but will feed into the overall recommendations.

## Console Tab

If enabled, shows the `sysout` information.  This is helpful when starting from an executable file, where there is no log output.  Global logging level is set via this tab.   You can also clear the output prior to a specific operation.

### Log Override

By component, you can select a higher or lower log level for all components.  Overriding with DEBUG allows you to see the detailed debug only in the shell, not the console tab.

## Maintenance Tab

Allows for rename, delete, or preservation of cache files.  Caches are rotated as new data is loaded, but if they are preserved here, they can remain after they normally would be pruned.  

Also here are permissions information, with the ability to query the loaded permission reference files.  TODO: in a future release, adding permission to resource mappings may be possible via this tab.