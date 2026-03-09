# Context: CLI Policy Intelligence Analysis and Usage

This context file describes the design, options, and intent of the OCI Policy Analysis **CLI (`cli.py`)**. The CLI provides a streamlined, non-interactive interface for loading, filtering, and displaying OCI IAM policies, groups, users, and dynamic groups—using the same core data engine and overlays as the main UI, but geared for scripting, automation, and quick diagnostics.

---

## 1. CLI Purpose and Positioning

- The CLI is a **lightweight sibling of the full GUI application**. Its design is focused on _quick inspection, reporting, and automatable scripting_ rather than rich interactivity.
- It uses the **same repository/data loading code and PolicyIntelligenceEngine overlays** as the UI, ensuring all data displayed or exported by the CLI matches what the desktop app would show for the same source.
- **Intended Use Cases**:
  - Automated reporting of policy and user/group inventories.
  - Command-line filtering/export for integration into other tools or scripts.
  - Quick debugging of identity/policy data by operations or security staff _without_ launching the desktop UI.

---

## 2. Available CLI Options

All flags and arguments supported by `cli.py`:

| Option / Flag                    | Meaning / Usage                                                  |
|----------------------------------|------------------------------------------------------------------|
| `--verbose`                      | Enable DEBUG logging for troubleshooting.                        |
| `--app-log`                      | Log output to `app.log` instead of stdout.                       |
| `--instance-principal`           | Use OCI Instance Principal authentication (vs. config profile).  |
| `--get-caches <tenancy>`         | List available cached datasets for the given tenancy.             |
| `--print-all`                    | Print all policies and dynamic groups after loading.             |
| `--recursive`                    | Load policies recursively for all compartments (default: false). |
| `--use-cache <cachedate>`        | Load a specific named cache (does not contact OCI).              |
| `--load-from-compliance <dir>`   | Load data from a compliance output CSV bundle, not the API.      |
| `--dont-save-cache-after-load`   | Prevent saving a fresh cache after live OCI load.                |
| `--profile <name>`               | OCI config profile to use (default: DEFAULT).                    |
| `--filter-json <JSONstr>`        | JSON expression to filter policy statements.                     |
| `--export-json <file>`           | Export full loaded dataset (policies, DGs, users, etc.) as JSON. |

_Most session, filter, and export options are mutually compatible—e.g., you can load from cache and export JSON, or load fresh with a profile and filter statements in one invocation._

---

## 3. Core Workflow

1. **Parse Arguments & Configure Logging**  
   Handles all the above flags, sets up console or file-based logging, and controls verbosity as requested.
2. **Load Data**  
   Loads OCI IAM data from live API (default), a cache, or a compliance CSV directory. Throws if loading fails (with displayed error).
3. **Run Policy Intelligence Overlays (Post-Load Processing)**
   - Always runs a minimal policy intelligence suite (_effective compartments, invalid statement marks, dynamic group in-use analysis_) on the loaded repo, ensuring all downstream output benefits from these overlays.
   - Any exceptions in this step are logged as warnings and do not halt execution.
4. **Apply Output/Filter Option(s)**  
   - `--filter-json`: Applies the filter to loaded policy statements and prints a summary to the log.
   - `--print-all`: Prints out all loaded policies, their statements (with parsed fields), and dynamic groups.
   - `--export-json`: Dumps the complete repository (post-analysis) as a JSON file.
   - As each output mode is invoked, standard policy overlays (effective compartment, validity, DG in-use) are present.

---

## 4. Output/Intents

- Output is **plain text or JSON** only (no GUI, no HTML/Markdown, etc.).
- For `--print-all`, each statement is displayed with all known fields, overlays, and parse results.
- For filtered output, results include parsing and intelligence overlays (e.g., showing statements marked invalid, with compartment path, etc.).
- For JSON exports, the data matches what the main UI caches or operates on for maximum interchange.

---

## 5. CLI vs UI: Comparison

| Feature                   | CLI (`cli.py`)        | UI (Tkinter App)           |
|---------------------------|-----------------------|----------------------------|
| Data model                | Full  | Full (with overlays)      | Full (with overlays + live data) |
| Interaction               | Batch/scripting, non-interactive | Interactive (tabs, filters, analytics) |
| Filtering                 | JSON filter, print-all flag      | GUI table/field filtering, tab scoping |
| Visualization/Reports     | Log/text export, JSON            | Tables, charts, dashboards, context tabs |
| Advanced Analytics        | Overlays (minimal)    | Overlays + AI, recommendations, simulation tools |
| Use-case focus            | Automation, scripting, quick inspection | Analysis, exploration, remediation, policy authoring |

---

## 6. Example Usage Patterns

- Print full inventory with overlays:
  ```
  python -m oci_policy_analysis.cli --profile ADMIN --print-all
  ```
- Filter statements for a specific group/verb:
  ```
  python -m oci_policy_analysis.cli --filter-json '{"subject_type": "group", "verb": "manage"}'
  ```
- Export the live dataset with overlays:
  ```
  python -m oci_policy_analysis.cli --profile PROD --export-json prod-policies.json
  ```
- List available caches for a tenancy:
  ```
  python -m oci_policy_analysis.cli --get-caches example-tenancy
  ```

---

## 7. Key References

- CLI logic & overlays: [`src/oci_policy_analysis/cli.py`](../../../src/oci_policy_analysis/cli.py)
- Policy overlays code: [`src/oci_policy_analysis/logic/policy_intelligence.py`](../../../src/oci_policy_analysis/logic/policy_intelligence.py)
- UI context (desktop): [`src/oci_policy_analysis/main.py`](../../../src/oci_policy_analysis/main.py)
- MCP/Server context: [`CONTEXT_mcp_server_and_tab.md`](CONTEXT_mcp_server_and_tab.md)

---

**Summary:**  
The CLI is a focused, automation-friendly front end to the OCI Policy Analysis data engine. It is meant for users who need to quickly inspect, report, or filter policy/identity data (with overlays for effective compartment and correctness), and can always be used for offline/remote review, scripting, and hand-off to other automations. For richer exploration, visual deep dives, or policy remediation, the full UI is recommended.