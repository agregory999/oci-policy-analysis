# OCI Policy Analysis

Analyze OCI IAM policies, compartments, identity domains, groups, users, and dynamic groups from a desktop app, web app, CLI, or MCP server. The tool is read-only: it analyzes data but does not change your tenancy.

The [full documentation](https://agregory999.github.io/oci-policy-analysis) covers setup, OCI access, sample and saved data, web hosting, command-line use, troubleshooting, and embedding.

For 7.0 highlights and a getting-started guide, see [What's new in 7.0](https://agregory999.github.io/oci-policy-analysis/release_7_0.html). The original desktop app remains available; the new desktop app is the recommended experience going forward.

## Quick Start: Download a desktop app

Download either maintained desktop app for macOS or Windows from the [Releases page](https://github.com/agregory999/oci-policy-analysis/releases). The modern app is the recommended experience going forward; the original app remains available and works as before. No Python setup is needed to run a downloaded app.

## Quick Start: Choose your data source

You do **not** have to connect this tool to a live tenancy. Choose from:

- **Sample data:** choose **Sample** in the modern app to explore fictional data without credentials.
- **Live OCI load:** requires an OCI user/API-key profile **and** IAM permissions granted to that principal. Before loading a tenancy, complete [tenancy access](#required-obtain-tenancy-access).
- **Offline CIS Compliance import:** import the directory of OCI CIS Compliance output files without connecting to the tenancy.

## Quick Start: Begin Analysis

Once data has been loaded, it will be available for access later via a local cache.  At this point you can navigate the application and start looking at policy data.

## REQUIRED for Live Tenancy: Obtain tenancy access

Using a downloaded executable from your desktop will enable you direct access to your OCI tenancy.  In order gain access, you will require an API Key for a tenancy.  It is recommended to limit this tool's access to the tenancy to a read-only set of operations.  

Admin API Keys with your DEFAULT profile will work, but it is easy to set up a limited access key specifically for this tool.

### OCI Limited User

1) From your OCI Console, create a new OCI Group in the Default Identity Domain - for example `PolicyAnalysisUsers`.   
2) Next, create a new OCI User in the Default Identity Domain called `policy-analysis-user` - place this user in the group from the previous step
3) Create an (API Key)[https://docs.oracle.com/en-us/iaas/Content/Identity/access/to_upload_an_API_signing_key.htm] for the user that was just created. 
4) Update your local `.oci/config` with a new named profile for this key, for example `POLICY-ANALYSIS`.
5) Create a new IAM Policy in the tenancy root, for example `PolicyAnalysisPolicy`.  The following statement is all that is needed:
```text
allow group <your_group> to {POLICY_READ, COMPARTMENT_INSPECT, DOMAIN_INSPECT, DYNAMIC_GROUP_INSPECT, GROUP_INSPECT, USER_INSPECT, LIMITS_VIEW_INSPECT} in tenancy
```

Once completed, the tool's profile selection dropdown should show `POLICY-ANALYSIS` and can be used to safely run the tool with limited permissions within the tenancy.

## REQUIRED for CIS COMPLIANCE scripts

Assuming you have access to an OCI tenancy already, you can run the supported (CIS Compliance scripts)[https://github.com/oci-landing-zones/oci-cis-landingzone-quickstart] with the `--raw` option.  This will produce a directory - if you were sent a zipped archive, simply unzip it locally.  Then in the Policy Analysis tool, point the CIS Compliance load directory to the unzipped location.   

## More help

The [full documentation](https://agregory999.github.io/oci-policy-analysis) covers mode-specific setup, OCI authentication and permissions, CIS compliance imports, web hosting, CLI and MCP usage, troubleshooting, architecture, and API reference.

