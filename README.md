# Policy and Dynamic Group Analysis

This tool is a python-based utility that can run either via command line or with a UI.  The main purpose of this tool set is to load, filter, and analyze both OCI Policy Statements and Dynamic Groups from a given tenancy.  It is possible to determine many things by using these tools:
* What permissions a group or dynamic group has
* Where in the compartment hierarchy are all relevant statements that meet the search criteria
* What additional policies exist for cross-tenancy enablement
* What permissions are granted to services, and in which compartments
* Whether the components of any or all dynamic groups point to valid OCIDs
* If any dynamic groups have no policy statements attached (means they are unused)
* If a policy statement containing dynamic group statements refers to a non-existent Dynamic Group

## Installation and Setup

Python 3.9 and tkinter were tested and are required for the UI.  The UI is written using tkinter, tkbootstrap, and tksheets, all of which are required to use the UI.  In the command line mode, standard Python libraries are used

Once installed, it is recommended to run in a virtual environment, using the included requirements.txt file to install any required packages via `pip`.  If TKinter is properly installed on the host system, the widgets should look good no matter which OS the code is run from.

### Requirements

The repository contains a `requirements.txt` file, which should be used to install the required libraries.

For the command-line version, the only requirement is the `oci` library, which you may already have if you had run `pip install oci` at any point.  

For the UI version, you must also have 
* `tk` - The main TKIntter pacakge, for the UI on top of Python.  [Read more here](https://www.tutorialspoint.com/how-to-install-tkinter-in-python)
* `tksheet` - An extension used to build and display the excel-style tables in the UI
* `tkbootstrap` - For the UI to look better.

### Install via Virtual Environment (Option 1)

To set up a basic Virtual Environment from scratch, first ensure that Python3 installed on the target machine.  An example from MacOS:
```bash
shell ~ % which python3
/opt/homebrew/bin/python3
shell ~ % python3 --version
Python 3.12.5
```
Then create and activate the virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```
At this point the python virtual environment is running, and you must install the requirements:
```bash
pip install -r requirements.txt
```

### Install via Python No Virtual Environment (Option 2)
If you already have python3 and are comfortable installing packaged via pip, the following will do:
```bash
python3 -m pip install -r requirements.txt
```

## Running the Utility
As mentioned, the utility can run in a UI (interactive), or via the command line.  Once the environment is ready, the following will launch the program:

```bash
# Running the CLI version
(.venv) shell oci-policy-analysis % python ./oci_policy_analysis.py

# Running the TkInter UI version
(.venv) shell oci-policy-analysis % python ./oci_policy_analysis_tkinter.py
```

### Command Line Help (Command Line Version)

Run the program with `--help` or `-h` to see all of the command line options available.  These allow you to select a named OCI Profile, operate with Instance Principal (on an OCI instance), set up filters, and export to JSON.  All of the filters are optional, and if quoted, support the `|` as a logical OR.  For example, `-sf "abc|def"` will bring back policy statements with abc or def in the subject (group or gynamic group) that is allowed to do something.  

For convenience, here is the output:
```bash
(.venv) agregory@agregory-mac oci-policy-analysis % python ./oci_policy_analysis.py --help
usage: oci_policy_analysis.py [-h] [-v] [-pr PROFILE] [-sf SUBJECTFILTER] [-vf VERBFILTER] [-rf RESOURCEFILTER] [-lf LOCATIONFILTER] [-hf HIERARCHYFILTER] [-cf CONDITIONFILTER]
                              [-pf POLICYNAMEFILTER] [-tf TEXTFILTER] [-dgdf DYNAMICGROUPDOMAINFILTER] [-dgnf DYNAMICGROUPNAMEFILTER] [-dgof DYNAMICGROUPOCIDFILTER]
                              [-dgtf DYNAMICGROUPTYPEFILTER] [-r] [-c] [-w] [-ip] [-t THREADS]

options:
  -h, --help            show this help message and exit
  -v, --verbose         increase output verbosity
  -pr PROFILE, --profile PROFILE
                        Config Profile, named. If not given, will use DEFAULT from ~/.oci/config
  -sf SUBJECTFILTER, --subjectfilter SUBJECTFILTER
                        Filter all statement subjects by this text
  -vf VERBFILTER, --verbfilter VERBFILTER
                        Filter all verbs (inspect,read,use,manage) by this text
  -rf RESOURCEFILTER, --resourcefilter RESOURCEFILTER
                        Filter all resource (eg database or stream-family etc) subjects by this text
  -lf LOCATIONFILTER, --locationfilter LOCATIONFILTER
                        Filter all location (eg compartment name)
  -hf HIERARCHYFILTER, --hierarchyfilter HIERARCHYFILTER
                        Filter by compartment hierarchy (eg compartment in tree)
  -cf CONDITIONFILTER, --conditionfilter CONDITIONFILTER
                        Filter by Condition
  -pf POLICYNAMEFILTER, --policynamefilter POLICYNAMEFILTER
                        Filter by Policy Name
  -tf TEXTFILTER, --textfilter TEXTFILTER
                        Filter by Text (anything in policy statement)
  -dgdf DYNAMICGROUPDOMAINFILTER, --dynamicgroupdomainfilter DYNAMICGROUPDOMAINFILTER
                        Filter by Dynamic Group Domain Name
  -dgnf DYNAMICGROUPNAMEFILTER, --dynamicgroupnamefilter DYNAMICGROUPNAMEFILTER
                        Filter by Dynamic Group Name
  -dgof DYNAMICGROUPOCIDFILTER, --dynamicgroupocidfilter DYNAMICGROUPOCIDFILTER
                        Filter by Dynamic Group OCID (as part of rule)
  -dgtf DYNAMICGROUPTYPEFILTER, --dynamicgrouptypefilter DYNAMICGROUPTYPEFILTER
                        Filter by Dynamic Group Type (as part of rule)
  -r, --recurse         Recursion or not (default True)
  -c, --usecache        Load from local cache (if it exists)
  -w, --writejson       Write filtered output to JSON
  -ip, --instanceprincipal
                        Use Instance Principal Auth - negates --profile
  -t THREADS, --threads THREADS
                        Concurrent Threads (def=5)
```

### Command Line Help (UI Version)

For the UI version, the only available option is `-v` or `--verbose` for verbose output.

### Profile Selection

Instance principals do not support the ability to operate on tenancies other than the one where the Instance is running.  However, since OCI API-key or profile-based auth allows you to have multiple entries in your `$HOME/.oci/config` file, the UI and CLI version allow you to select which profile to operate with.  This can be handy for administrators who work on multiple tenancies.

The docs for each version explain how to do profile selection.

Running with no arguments implies using API Keys and the `DEFAULT` OCI profile, which must be set up using the standard OCI CLI documentation, located [HERE](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm)

The UI version allows this selection of profile as a dropdown, while the CLI version takes a command line option, documented above.

### Authentication (User) and Required Policy

The utility can take advantage of either profile-based (API-key) or Instance Principal.  If you are running from your desktop or have no desire to use Instance Principals, simply use an existing or new OCI Profile.  By default, if you have enabled OCI CLI, you have a profile named `DEFAULT` that authhenticates and runs using the configured User OCID.  This means that you need to be covered by a policy statement that, at a minimum, has the following:

```
allow group <your group name> to inspect policies in tenancy
allow group <your group name> to inspect dynamic-groups in tenancy
allow group <your group name> to inspect compartments in tenancy
```
If the tenancy is enabled for IAM Domains, the following additional policy statement must be place in order for the user running the program to load IAM Domains, as Dynamic Groups can be located within a non-Default Identity Domain:
```
allow group <your group name> to inspect domains in tenancy
```

### Authentication (Instance Principal)

To run using instance principals, you must ensure that there is a dynamic group containing either the Instance OCID or the Instance Compartment OCID for the instance you plan to run from.  Then you need a policy statement somewhere, which grants read permission on the policy and dynamic groups:

```
allow dynamic-group <your dynamic group name> to inspect policies in tenancy
allow dynamic-group <your dynamic group name> to inspect dynamic-groups in tenancy
allow dynamic-group <your dynamic group name> to inspect compartments in tenancy

```
As above, if the tenancy is enabled for IAM Domains, the following additional policy statement must be place in order for the dynamic group running the program to load IAM Domains, as Dynamic Groups can be located within a non-Default Identity Domain:
```
allow dynamic-group <your dynamic group name> to inspect domains in tenancy
```
### Fail Safe Policy
The program will also happily run with the following policy statement and a group or dynamic-group permission as follows:
```
allow group <your group name> to inspect all-resources in tenancy
allow dynamic-group <your dynamic group name> to inspect all-resources in tenancy
```
This policy will prevent the user from seeing or manipulating anything in the tenancy, but still be able to read what is necessary for this program to operate.

## Caching

Using the UI or the CLI version begins with choosing where to load policies and dynamic groups from.  The tool supports a cached (offline) mode, in which policy statements and dynamic groups from a previous (non-cached) run are saved into a local cache file, per tenancy OCID analyzed.  What this means is that if no changes occur, you can work using cached policies instead of calling the OCI API potentiallly 1000s of times to load the data.  At any time, you can simply run again against the actual tenancy and the results will populate from fresh data, again updating the cache for subsequent work.

It is completely fine to operate with multiple tenancies, as cache files are keyed from the tenancy OCID.  Therefore, you can have multiple tenancies with cached policies locally, and select ar runtime on which to operate. 

Caching is enabled using the `-c` command line option, or via checkbox in the UI.  For each tenancy, the un-cached option must be run, so that the initial cache is loaded from real data.  

Files will be located in the location the program was started from in the following format:
```
.dynamic-group-cache-<tenancy-ocid>.dat
.policy-statement-cache-<tenancy-ocid>.dat
```

Cache does not expire, but may be out of sync with live tenancy data.  So it is good to run the program without caching once in a while in order to catch up with changes. 

## Filtering

One of the main features of the tool set is the ability to filter a large list of policy statements.  In OCI, statements are organized into policies, which can have up to 50 statements by default.  Policies are located in compartments (often not the tenancy root), and thus valid statements for a given group or dynamic group can exist in multiple compartments and in multiple policies.  Therefore, the total set of permissions granted to a group is the union of all valid statements, and is evaluated each time an API call is made.   Without a tool that can load and organize ALL statements, it is very difficult to quickly determine whether permission to "do something" exists, and if so, whether more than sufficient permission has been granted.  

A simple example of filtering might be to load 3000 total statements and then ask the tool to filter out a specific group and verb.  For example, group `InstanceAdmins` and verb `manage`.  You could filter on both of these at the same time, and derive a list of all policy statements that have both of these characteristcs.  Results will also include the name and location in compartment hierarchy of the containing policy.

### Filter Chaining

Filtering for policies can be done via 8 possible ways:  
- Subject (group or dynamic-group name)
- Verb (inspect. read, use, manage)
- Resource (ie instance-family or subnets)
- Location (compartment name)
- Compartment Hierarchy (compartment name anywhere in hierarchy)
- Conditions (anything in where clause)
- Text (anything in the statement text)
- Policy Name (to see a specific policy)

Individual filters support an | (OR) within the filter, and are chained using AND.  This means that if we define a filter for subject as `abc|def` and we also define a verb filter of `read|use`, the combined filter will give policy statements where `abc` OR `def` appears in the group name AND `read` OR `use` is the verb.   As more filters are refined, the list of statements is reduced to the relevant ones only.

There are more advanced filter examples, as well as more documentation on what is valid, further below.

### Any User/Group, Root Only, Tenancy Checkboxes

These filter checkbox options simply set the filter for that field to the hard-coded values that apply.  These filters can be in addition to other filtered fields.

- **Any User/Group** filters the subject to statements pertaining to the allowed `any-user` or `any-group` keywords in [OCI policy Syntax](https://docs.oracle.com/en-us/iaas/Content/Identity/Concepts/policysyntax.htm#one) for Subjects.
- **Root Only** filters the location of the policy to only include policy statements that appear in policies located in the tenancy root compartment (tenancy OCID).
- **Tenancy** filters the location portion of the policy statement, showing only policy statements that apply some permission to the location `in tenancy`.  

These can be used to find statements that are too permissive, for example, with a verb filter of `manage` and the tenancy checkbox, we can see policy statements that allow full management of some type of resource within the entire tenancy.

## Load, Save, Clear (UI)

The UI includes convenience buttons to clear all filters, as well as buttons to save the filtered output to a file.  Saving to a file to either JSON or CSV will export with all filtered statements,  It does not take into account the display options, shown below.  Only the filter options are taken into account.

Loading a previously saved filtered output brings only the policy statements into view - Dynamic Groups are not loaded at all.  This feature is good for a quick view of statements previously analyzed.  Use the cached or full load to get all statements and dynamic groups.

## Display Options

The UI version of the tool supports additional output filtering.  For example, once the list of policies has been filtered by subject, verb, etc, the UI allows you to further filter the display by policy type.  This can be helpful if you want to see just dynamic-group statements or service statements.  These are implemented as checkboxes, so you can see all or some of the available policy statements that came from the filtered output.

Additionally the UI will display both the total number of statements from the aggregate filter operation, as well as the number of statements actually being shown at the moment, based on display filters.

Finally, the UI has a checkbox option for "Extended View", which shows all information that it was able to parse from all statements that are currently displayed.  This contains full OCIDs, policy comments, and parsed fields for each filter-able category, such as subject, verb, resource, location, and conditions.

### Copy / Paste

The UI display grid supports copy and paste.  To copy, simply click on any result cell (or multiple, using ctrl or shift), and then copy with ctrl-C or a right click.  The text is able to be pasted.

## Advanced Analysis

There are additional anaylsis functions available as buttons within the UI version of the tool.  Once policies and dynamic groups have been loaded, these functions operate on the entire set of unfiltered data, and add additional context.  Findings are marked with <span style="color:pink">pink rows</span> in the output grid.

### Policy Statement Containing non-existent Dynamic Group

From the UI Policy Statement View tab, there is a button to "Analyze Dynamic Group Statements".  Clicking this button causes the policy analysis engine to look at all dynamic group policy statements and determine if the referenced dynamic group exists.  If it does not, the statement is marked in pink.  The policy statement could need modification or deletion.

### Dynamic Group not referenced by any policy

From the UI Dynamic Group View tab, there is a button to "Run In Use Analysis".  Clicking this button causes the dynamic group analysis engine to look at all dynamic groups to determine if any policy statements exist that reference the dynamic group.  If there are no statements referencing the dynamic group, it is marked in pink.  The dynamic group is thus a candidate for deletion.

### Dynamic Group OCID Analysis

From the UI Dynamic Group View tab, there is a button to "Run OCID Analysis".  Clicking this button causes the dynamic group analysis engine to look at all OCIDs contained within any dynamic group's matching rules.  If that OCID does not refer to an object that does not exist any more, then it flagged and reflected.

## More Filter Chaining

A few more examples....

Using the command line, this example sets a profile from the user's `.oci/config` and then applies 2 filters on policy subject and a text filter which includes text anywhere in the policy statement.  Using the `-w` flag, the results are output to a local JSON file.

```
python ./oci_policy_analysis.py --profile NON-DEFAULT-PROFILE -c -sf "mra-iam-admin-group|appdev" -tf "users in tenancy" -w
```