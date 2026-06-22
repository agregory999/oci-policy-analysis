# Command-Line Interface (CLI)

The OCI Policy Analysis application provides a flexible command-line interface (CLI) for analyzing OCI policies, dynamic groups, users, and compartments. The CLI supports live OCI loading, compliance output ingestion, advanced filtering, and JSON export. It is an essential tool for both ad-hoc policy investigation and automated workflows.

## CLI Usage

Invoke the CLI with:

```sh
python -m oci_policy_analysis.cli [OPTIONS]
```

or directly (if installed as a script):

```sh
oci-policy-analysis [OPTIONS]
```

## Install Profiles (Core vs Web/Desktop)

For **CLI-only/core-only** usage (no Tk desktop UI and no web server runtime),
install the base package:

```bash
python -m pip install --upgrade pip
pip install -e .
```

This core install provides:

- `oci-policy-analysis` (CLI entrypoint)
- `python -m oci_policy_analysis.cli`

Use extras only when needed:

- `pip install -e ".[web]"` for FastAPI web mode
- desktop UI runs from the base install but requires local Tk availability

See also:

- [Desktop Setup](setup_desktop.md)
- [Web Setup](setup_web.md)
- [MCP Server](mcp.md)

## CLI Options

| Option                       | Description                                                                                                    |
|------------------------------|----------------------------------------------------------------------------------------------------------------|
| `--verbose`                  | Enable DEBUG logging                                                                                           |
| `--log-level LEVEL`          | Set CLI log level (`CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG`) without forcing verbose mode             |
| `--app-log`                  | Log output to `app.log` instead of console                                                                    |
| `--instance-principal`       | Use instance principal authentication                                                                         |
| `--get-caches TENANCY`       | List available caches for the given tenancy                                                                   |
| `--print-all`                | Print all policies and dynamic groups                                                                         |
| `--recursive`                | Recursively load across all compartments                                                                      |
| `--use-cache CACHE`          | Load data from a specified combined cache file                                                                |
| `--dont-save-cache-after-load` | Do not save a new combined cache after loading from OCI                                                     |
| `--profile PROFILE`          | OCI CLI profile to use (default: `DEFAULT`)                                                                  |
| `--filter-json FILTER`       | A JSON filter expression for policy statements                                                               |
| `--load-from-compliance DIR` | Load policy data from a directory of OCI CIS compliance output CSVs                                           |
| `--export-json FILE`         | Export all collected data to the specified JSON file                                                          |
| `--export-permissions-report PATH` | Export the calculated permissions report to `PATH.json`, `PATH.csv`, or both                         |
| `--export-permissions-report-format FORMAT` | Permissions report format: `json`, `csv`, or `both` (default: `both`)                         |
| `-h`, `--help`               | Show usage and options                                                                                        |

---

## Usage Examples

### 1. Displaying CLI Help

Show full help including all options:

```sh
python -m oci_policy_analysis.cli --help
```

Or, if installed as an application:

```sh
oci-policy-analysis --help
```

### Exporting the Permissions Report

The permissions report is not exposed through MCP. From the CLI, it is available as an explicit export option for offline review:

```sh
python -m oci_policy_analysis.cli --use-cache CACHE_NAME --export-permissions-report permissions_report
```

By default this writes `permissions_report.json` and `permissions_report.csv`. The flat rows list each permission at each effective compartment/principal, including whether the grant is direct or inherited from a higher compartment and the statement that granted it. For broad `any-user` or `any-group` statements with `request.principal.*` conditions, the principal key column uses derived resource-principal or OKE workload identity keys while preserving the original subject key in the export.

---

### 2. Loading a Tenancy into a Local Cache

To load all OCI policies and identity resources for a tenancy and save to a new cache (using a named profile):

```sh
python -m oci_policy_analysis.cli --profile MY_PROFILE --recursive
```

- This will connect to OCI, recursively load all compartments, users, groups, and policies, and generate a "combined cache" file for offline or repeated analysis.
- By default, the cache is saved after load (unless `--dont-save-cache-after-load` is provided).
- Use `--instance-principal` to run under an OCI Compute Instance with instance principal auth.
- Use `--log-level INFO` when you want normal progress/filter logging without full DEBUG verbosity.

---

### 3. Loading a Tenancy and Filtering Policy Statements

You can load a tenancy (from live or cache) and filter policy statements using a JSON expression:

```sh
python -m oci_policy_analysis.cli --profile MY_PROFILE --recursive --filter-json '{"Subject": "groupA", "Verb": "read"}'
```

- This command fetches all statements for group “groupA” with verb “read,” displaying results on the console.
- For advanced usage, combine with `--use-cache` to operate on a cached dataset:
  ```sh
  python -m oci_policy_analysis.cli --use-cache 2024-11-17T10-43-08+00-00 --filter-json '{"Subject": "groupA", "Resource": "instance"}'
  ```

---

### 4. Loading a Tenancy from CIS Compliance Output

To ingest OCI policy state from baseline compliance CSV output (as created for CIS benchmark reporting):

```sh
python -m oci_policy_analysis.cli --load-from-compliance /path/to/compliance_csv_output/
```

- This will parse all provided CSV files (in the directory), reconstructing users, groups, dynamic groups, and policies for analysis and reporting.

---

## Generating a Cache for Secure MCP Server Use

The CLI can be used to generate a combined policy analysis cache file (`.json`), capturing the full set of users, groups, dynamic groups, compartments, and policies in your tenancy. This cache is portable and can be used for offline analysis or transferred to another environment.

A powerful workflow is to use the CLI to generate and update the cache, then deploy this cache—as input for the Model Context Protocol (MCP) server—on an OCI Compute Instance or within a managed, load-balanced environment. In this model, the CLI acts as an extract-and-publish step, with the MCP server providing fast API access to policy data, supporting scalable automation or federated review by multiple consumers.

> For deployment and security considerations on running load-balanced MCP servers on OCI, see: [Secure Deployment on OCI — Outline Steps](/mcp.html#secure-deployment-on-oci-outline-steps)
