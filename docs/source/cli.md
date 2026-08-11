# Command-Line Interface (CLI)

The CLI is a limited, non-interactive way to load OCI policy and identity data, inspect or filter it, and export it for offline use. It is useful for scripting, cache creation, CIS Compliance imports, and report exports.

It does not replace the desktop or web experience: use those interfaces for interactive analysis, historical comparison, simulation, recommendations, and other guided workflows. The CLI is read-only with respect to OCI resources.

## Install and start

Install the base package and configure authentication as described in the [Setup guide](setup.md). Then run:

```bash
oci-policy-analysis-cli --help
```

The source-module equivalent is:

```bash
python -m oci_policy_analysis.cli --help
```

## Choose a data source

Each CLI run loads one dataset. Choose one of these sources:

| Source | Use when | Main option |
|---|---|---|
| Live OCI tenancy | You need current data and have an OCI profile or instance principal with the required permissions. | `--profile` or `--instance-principal` |
| Combined cache | You need repeatable or offline analysis of a previously saved dataset. | `--use-cache` |
| CIS Compliance output | You received a CIS Compliance output directory and do not want this tool to connect to OCI. | `--load-from-compliance` |

For live loads, use the [Authentication and principals](setup.md#authentication-and-principals) and [Permissions required](setup.md#permissions-required) sections first.

## Common workflows

### List available caches

```bash
oci-policy-analysis-cli --get-caches <tenancy-name>
```

This lists the saved combined caches for the named tenancy and exits without loading OCI data.

### Load current tenancy data and save a cache

```bash
oci-policy-analysis-cli --profile MY_PROFILE --recursive --log-level INFO
```

This reads the tenancy using `MY_PROFILE`, includes child compartments, runs the CLI’s minimal post-load analysis, and saves a combined cache by default. Add `--dont-save-cache-after-load` when you do not want a new cache.

For OCI Compute, replace the profile option with `--instance-principal`:

```bash
oci-policy-analysis-cli --instance-principal --recursive
```

### Inspect a saved cache

```bash
oci-policy-analysis-cli --use-cache <cache-name> --print-all
```

`--print-all` writes policy statements, cross-tenancy statements, and dynamic groups to the terminal. Use it only for small datasets or targeted troubleshooting because the output can be large.

### Import CIS Compliance output

```bash
oci-policy-analysis-cli \
  --load-from-compliance /path/to/compliance-output \
  --export-permissions-report permissions_report
```

The directory may contain either legacy `raw_data_*.csv` files or current directory-prefixed files such as `<output-directory>_raw_data_identity_compartments.csv`. See [Obtain CIS Compliance output](setup.md#obtain-cis-compliance-output) for how to create the directory.

### Filter policy statements

```bash
oci-policy-analysis-cli \
  --use-cache <cache-name> \
  --filter-json '{"Subject": "groupA", "Verb": "read"}'
```

The filter is applied to the loaded dataset and matching statements are written to the terminal. Use a cache for repeated filters so the CLI does not reload the tenancy each time.

### Export data and permissions

Export the full loaded dataset as a combined-cache JSON file:

```bash
oci-policy-analysis-cli --use-cache <cache-name> --export-json policy_data.json
```

Export the calculated permissions report:

```bash
oci-policy-analysis-cli \
  --use-cache <cache-name> \
  --export-permissions-report permissions_report \
  --export-permissions-report-format both
```

The permissions report can be `json`, `csv`, or `both` (the default). It records permissions by effective compartment and principal, including direct/inherited context and source statements where available.

## Options reference

### Data loading

| Option | Description |
|---|---|
| `--profile PROFILE` | OCI profile for a live load. Defaults to `DEFAULT`. |
| `--instance-principal` | Use OCI instance-principal authentication for a live load. |
| `--recursive` | Load child compartments during a live load. |
| `--dont-save-cache-after-load` | Do not save a combined cache after a live load. |
| `--use-cache CACHE` | Load a named combined cache. |
| `--get-caches TENANCY` | List saved caches for a tenancy and exit. |
| `--load-from-compliance DIR` | Import a CIS Compliance output directory. |

### Inspection and exports

| Option | Description |
|---|---|
| `--filter-json FILTER` | Filter policy statements in the loaded dataset. |
| `--print-all` | Print policies and dynamic groups to the terminal. |
| `--export-json FILE` | Export the full loaded dataset as JSON. |
| `--export-permissions-report PREFIX` | Export the permissions report with the supplied file-path prefix. |
| `--export-permissions-report-format FORMAT` | Select `json`, `csv`, or `both` (default). |

### Logging

| Option | Description |
|---|---|
| `--log-level LEVEL` | Set `CRITICAL`, `ERROR`, `WARNING`, `INFO`, or `DEBUG`. |
| `--verbose` | Enable DEBUG logging. |
| `--app-log` | Enable application-log output in addition to normal terminal use. |
| `--help` | Show the authoritative option list for the installed version. |

For troubleshooting guidance, see [Logging and Troubleshooting](logging_and_troubleshooting.md). For MCP workflows, see [MCP Server](mcp.md).
