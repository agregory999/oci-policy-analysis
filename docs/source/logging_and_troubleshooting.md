# Logging and Troubleshooting

This page provides guidance on logging configuration, debugging, and troubleshooting for the application.

## New UI live logs and API calls

Open **View → Logs**, **Show live log** on Overview & Settings, or
**Tools → Logging → Show live log**. The resizable Logs dock stays available
while navigating and loading. Drag its title bar to float it as a separate
window, or dock it at the top or bottom. Hiding it does not stop capture.

| Tab | What it shows |
| --- | --- |
| Live log | Component log messages at INFO and above, subject to logging settings; choose all application components or UI-only output |
| Load activity | Load progress and stage messages from the background worker |
| API Calls | Completed, instrumented OCI SDK requests in a sortable table, independent of component log levels |

The New UI separates routine API success/timing messages from the live text log so a
large collection does not bury other messages. Those text messages use DEBUG in
the New UI; the **API Calls** table still captures the metadata without enabling DEBUG
or **Always log API calls**. Other application diagnostics and failures can still
appear in the component log.

In **API Calls**, search by operation, target, status, reason or request ID; use
**Errors only** to focus on failures. Columns show UTC start time, operation,
duration, outcome, HTTP status, service code and reason. Enable **Show details**
and select a row for the target, endpoint, method, tenancy, request ID and any
available error interpretation. Drag the divider to resize the details area.
Pagination requests and retry attempts appear separately. A call appears when it
completes, so this is not a list of currently running requests.

API history lasts for the application process and survives successful or failed
loads. It retains up to 5,000 records, favoring errors over successes when full;
the counters show retained, filtered and omitted/evicted calls. **Clear API
history** clears only this in-memory journal. It does not clear log files, change
the snapshot or write a cache. Request/response bodies, credentials and raw
headers are not stored in the journal; diagnostic metadata can contain tenancy
and resource identifiers.

This table covers instrumented OCI requests made by this application process.
For client requests to the snapshot MCP endpoint, use the activity tab on
**MCP & Assistant**, which includes external MCP clients. Model-provider API
traffic from separate assistant applications is not captured here. See
[MCP Assistant guide](mcp_assistant.md) for that activity stream and the
[new desktop usage guide](usage.md#live-logs-and-oci-call-details) for logging controls.

## Global logging by component

You can enable or adjust logging granularity across different components within the system. Logging levels can typically be set (ERROR, WARNING, INFO, DEBUG) to control verbosity.

- Each major code component/module supports logging, allowing for tracking of operations and detection of issues.
- Logs may be viewed in the shell when started from the command line.
- In the New UI, use the live log dock. In the Legacy UI, use the Console tab.

In the Legacy UI, open **Settings → Show Console/Debugger Tab** to view logs and logging controls.

There is a single Global Logger dropdown, which if set, will change the log level for all componenets to the configured level.

Additionally, there is a "Show Loggers" checkbox, which allows inidividual override per component.  For example, set the global level to WARNING, and then override a compoment to INFO.  Doing this will allow you to see additional details for that component.

For corpus diagnostics, set **Core Repo / Engine → core.policy_corpus** to INFO to see direct/effective fact and exclusion counts. Set **core.cross_tenancy_corpus** to INFO for definition, relationship, finding, diagnostic, and resolution counts. Set **cross_tenancy** to INFO for cross-tenancy findings and graph refresh summaries. These summaries appear on the Console tab after a load or **Refresh view**; they do not include statement text.

For graphical policy search, set **Application Services → application.services.policy_graph** to INFO in either the desktop Console logging controls or the web Logging page. Each search reports the active filter categories, effect, overview state, page/page size, corpus and exclusion counts, matching principals, grants and effective paths, visible grants, and elapsed milliseconds. An unloaded corpus is reported explicitly. DEBUG additionally records filter values; INFO does not print statement text or permission lists.

On desktop, **UI → policy_graph_tab** at INFO reports tab construction and each populated view's principal/resource/path card counts, table row count, guidance state, and elapsed time. It does not log every resize or scroll. **core.policy_corpus** covers the underlying corpus build; **application.services.policy_graph** covers shared searches. Each Console logger category uses one column; categories wrap into additional rows to fit the window. The logger panel scrolls independently from the log output.

During desktop loads, the modal names each intelligence prerequisite and strategy, then the corpus, permissions report, and simulation phases. The **core.engine.policy_intelligence_engine** component at INFO records elapsed time for each check and prerequisite; **main** at INFO records the larger post-load phases. The final live tenancy load time includes intelligence and corpus construction.

Desktop post-load intelligence runs once per successful load. Recommendations then renders the completed overlay without rerunning strategies. Changing analytics controls explicitly recalculates intelligence. Engine-initialization messages can also appear during reset; initialization alone does not execute strategies.

### Debugging from the command line

Due to the volume of logging, DEBUG output, if set, is only available on the shell.  Therefore debug logging is not really available via executable.   There are 2 ways to enable debug

- Enable DEBUG-level log output using the UI to see detailed processing information in the command line.
- Launch the application with an explicit `--verbose` parameter to force global DEBUG 
  ```bash
  oci-policy-analysis-ui --verbose
  ```

**NOTE:** Global DEBUG is very noisy, so only do this if you really need to.

### API and timing logging

The New UI's API Calls journal described above is independent of these text-log settings.

In addition to standard component-based logging levels, the application offers dedicated logging for specific events such as API calls (external integrations, requests to OCI, etc.) and timing/performance data.

- **API Logging:**  
  - API-related logs can be configured to output at higher levels (such as `CRITICAL`), allowing you to always see important API activity or errors even if the global logger is set to `WARNING` or above.
  - This ensures that key API successes, failures, or latencies are always visible for troubleshooting, regardless of the overall log verbosity.
  - Some API and external integration logs may include timing or performance diagnostics for requests and responses.

- **Timing Logging:**  
  - Timing/performance logs (operation durations, critical-path timings, long-running queries) can also be emitted at high log levels (`CRITICAL` or `ERROR`) so they're never missed, regardless of global settings.
  - Useful for investigating slowness or identifying bottlenecks without increasing general log noise.

- **How Levels Affect Visibility:**  
  - When a message is logged at a high level like `CRITICAL`, it is always output unless logging is globally silenced.
  - This approach makes sure operationally significant API/timing events get through, even if most components are set to `WARNING` or lower.

**Example:**  
If the global logger is set to `WARNING`, but API logger is emitting certain messages at `CRITICAL`, those API log entries will still appear in your logs/Console.

*To configure more granular logging for API and timing, use either the UI log level overrides (via the "Show Loggers" checkbox) or set log levels programmatically in your environment/setup scripts.*

## IAM Loading Diagnostics

Use these temporary environment controls only when investigating a live-tenancy IAM load. They apply to identity-domain, group, user, and dynamic-group collection; they do not change OCI resources.

### Reduce identity API concurrency

The normal identity-detail load uses six workers. If OCI Identity Domains returns HTTP 429 responses, retry with one worker to serialize dynamic-group and user detail calls:

```bash
OCI_POLICY_ANALYSIS_IDENTITY_API_WORKERS=1 ./local-run.sh --mode ui
```

Values from `1` through `6` are accepted. Invalid values retain the normal six-worker setting. This flag does not change policy or compartment loading concurrency.

### Capture IAM API results to CSV

Set `OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV` to a local output path before starting the application:

```bash
OCI_POLICY_ANALYSIS_IDENTITY_API_WORKERS=1 \
OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV="$PWD/iam-api-diagnostics.csv" \
./local-run.sh --mode ui
```

The CSV records the API call, identity-domain context, resource ID, elapsed time, outcome, HTTP status, OCI service code, request ID, and error message. It covers identity-domain discovery plus group, user, and dynamic-group list/detail calls. CSV writing is best-effort: an output-file error is logged and does not stop the tenancy load.

Successful response bodies are omitted by default. To include them for a narrowly scoped troubleshooting run, also set `OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_RESPONSES=1`. Response bodies can contain user and group data, so keep that CSV local and remove it when it is no longer needed.

On PowerShell, set the variables before starting the app:

```powershell
$env:OCI_POLICY_ANALYSIS_IDENTITY_API_WORKERS = "1"
$env:OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV = "$PWD\iam-api-diagnostics.csv"
.\local-run.ps1 --mode ui
```

## Parsing Diagnostics

Set `OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV` to capture the canonical parsing results produced when a live tenancy or CIS compliance output is loaded. This is useful when a statement, `where` clause, or dynamic-group matching rule appears to be accepted or rejected unexpectedly.

```bash
OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV="$PWD/parsing-diagnostics.csv" \
./local-run.sh --mode ui
```

The CSV has one row for every policy statement, one additional row for each non-empty `where` clause, and one row for every dynamic-group matching rule. It includes the load source, policy and compartment context, identity-domain and dynamic-group context where applicable, the original text, parse status, validity, warnings, errors, parsing notes, and a compact JSON result summary. Failed policy statements are included too, so they remain discoverable even though they are excluded from the compiled policy corpus.

For a quick local capture without specifying a filename, set the value to `1`, `true`, `yes`, or `on`. The application creates a timestamped `parsing-diagnostics-*.csv` under its cache directory. CSV writing is best-effort and cannot interrupt the load.

Both policy statements and dynamic-group rules can contain sensitive tenancy details. Keep this file local and remove it after troubleshooting. On PowerShell:

```powershell
$env:OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV = "$PWD\parsing-diagnostics.csv"
.\local-run.ps1 --mode ui
```

## Web UI and command-line logging

The desktop application, web server, CLI, and MCP server use the same application logging system, but the place to inspect output differs by mode.

| Mode | Useful startup options | Where to inspect issues |
|---|---|---|
| New UI | `oci-policy-analysis-ui --verbose` | Live Log and the application log; verbose detail is available when launched from a shell. |
| Legacy UI | `oci-policy-analysis-legacy-ui --verbose` | Console/Debugger tab and the application log. |
| Web UI | `oci-policy-analysis-web --host 127.0.0.1 --port 8000` | Server terminal/application log, browser developer console, and the web **Logging** page. `--reload` is for local development only. |
| CLI | `oci-policy-analysis-cli --log-level INFO`, `--verbose`, `--app-log` | Terminal output by default; use `--app-log` when the application log is needed. |
| MCP | `oci-policy-analysis-mcp --log-level INFO` | Server terminal/application log and the MCP client’s connection or tool-call error output. |

Use `--help` with each command for the complete option list. For web startup, a runtime access key is printed in the server log; it is required to unlock the browser session and rotates after every server restart.

## JSON Debugger tab (Legacy UI only)

The JSON Debugger is available only in the Legacy UI. Open **Settings → Show Console/Debugger Tab** to access it. The New UI does not include a JSON debugger.

- The *JSON Debugger* tab is primarily a troubleshooting tool, intended to help developers and advanced users debug and inspect the application's internal state.
- This tab displays internal JSON objects and data structures used by the app for policy analysis, simulation history, reference data, and policy intelligence overlays.
- These objects are shown in their raw or near-raw form for maximum diagnostic value, making it possible to review exact internal representations, nested relationships, and unprocessed values that may not appear in regular user-facing UI components.

For a large **Policy Corpus**, the debugger opens on a count summary. Choose `facts`, `effective_facts`, or `exclusions` to inspect 100 records per page. Search filters the selected section, and Text and Tree modes show only the current page. This keeps permission and compartment expansion from filling the Tk text widget with the entire corpus.

- Use it to:
  - Review raw input/output for policy analysis steps
  - Trace errors back to their source with contextual JSON data
  - Explore application internals for debugging advanced problems or reporting detailed bug information

- The JSON Debugger is an evolving part of the toolset: available sources, schemas, and presentation may change with future updates as more internal objects and debug scenarios are supported. The objects displayed here are subject to change and may reveal data that is intended primarily for troubleshooting, rather than polished consumption.

- More internal objects will be added as needed.  

## Troubleshooting topics

- **Common Errors:** Review the live log in the New UI, or the Console and JSON Debugger in the Legacy UI.
- **No Output or Silent Failure:**  
  - Ensure logging is not set to ERROR or CRITICAL for all components.
  - Check that the appropriate components are enabled.
  - Check IAM permissions for the tool itself.  Permissions needed are [detailed here](./setup.md#permissions-required)
- **Unexpected Behavior:**  
  - Use INFO level for the affected component(s), repeat the action, and consult logs/Console output.
  - DEBUG logging is available with the shell only, and should be used with caution as it is very verbose.
- **UI Not Responding:**
  - New UI: check **View → Logs** or shell logs.
  - Legacy UI: check the Console/Debugger tab or shell logs.
  - Web: check the server log, browser console, and `GET /health` when hosted behind a proxy or load balancer.
- **Web login blocked:** confirm that the runtime access key came from the current server startup, not an earlier restart.

*If you need more detailed guidance, refer to the main documentation or contact the maintainers.*

---

## Further Reading

For deep technical details—covering logging architecture, log-level wiring, log persistence, per-component overrides, and programmatic/debug workflows—consult:

- [Logging maintainer context](https://github.com/agregory999/oci-policy-analysis/blob/main/context/project/CONTEXT_logging.md)

_(Additional 3rd-party or advanced troubleshooting links may be added here in future updates. For a reference of architecture, simulation, and usage topics, see also: [Recommendations](recommendations.md) and the context section of the docs.)_
