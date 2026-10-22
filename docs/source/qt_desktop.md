# Qt desktop preview

Start with the [7.0 guide](release_7_0.md) for what changed and a concise
navigation walkthrough. This page gives the detailed loading, browsing, logging,
and lifecycle behavior.

## Load a snapshot

The optional `presentation.qt` package is a PySide6 Widgets preview over
the same services. Install and launch it from this checkout:

```bash
uv sync --extra qt --extra web --extra mcp
.venv/bin/oci-policy-analysis-qt --sample
```

`oci-policy-analysis-qt` is the optional Qt console command; install the `qt`
extra and refresh the editable install with `uv sync --extra qt --extra mcp --extra web`
if the command is absent. `python -m oci_policy_analysis.presentation.qt` is
equivalent. The existing `oci-policy-analysis-ui` command remains Tkinter.

Omit `--sample` to start empty. The profile selector reads section names from
`~/.oci/config` and accepts a manually entered name. **Load from OCI** uses
profile authentication, the selected policy recursion setting, and identity-domain
depth (1=root; 2=root plus immediate children). Authentication only starts on an
explicit load. **Open snapshot** accepts an exported combined-cache JSON file;
**Sample data** imports clearly fictional evidence through `LoadService`. The
packaged sample contains 100 policies / 325 statements, 25 groups, 50 users with
one to four memberships each, 12 dynamic groups, and a 22-compartment landing
zone hierarchy. Public policy patterns were reconstructed from an anonymized
CIS landing-zone snapshot; all names, identifiers, memberships and inventory are
fictional. Resource-principal and OKE examples and three intentionally invalid
records exercise the filters. This is demo evidence, not a deployable CIS
template. Runtime sample loading never reads operator caches.

For the current sidebar order and Standard/Advanced page availability, see the
[7.0 navigation walkthrough](release_7_0.md#qt-navigation-walkthrough).
Overview & Settings, Tools, and (in Advanced mode) Historical Comparison are
available before a tenancy is loaded. Other pages require a successful load.
A failed reload retains the previous displayed snapshot. Advanced mode controls
visibility; changing it does not run analysis or reload data.

`selection_table.py` supplies native check-state models and a checked table over
the shared record view/proxy. Inclusion follows stable service IDs through sort
and filter, independently of highlighted rows. Visible-only bulk actions show
hidden-checked counts; missing IDs are uncheckable, duplicate IDs reject a reset,
and source records are unchanged. Downstream services remain responsible for
eligibility and explicit operations. Recommendation display rows without IDs
remain read-only rather than receiving invented action identifiers.

Only the tenancy-loading area and experience toggle are expanded initially. Logging, MCP, Intelligence,
and Look and Feel are independent collapsed sections. Snapshot results appear
only after a successful load. The tenancy controls include profile and instance-principal authentication,
policy recursion, user loading, and identity-domain depth. Profiles can use session
tokens. Resource Principal is for hosted workloads, not the Qt desktop loader;
a saved Resource Principal choice falls back to profile authentication. OCI profile/authentication and Load from OCI share
one row, followed by scope options. Horizontal separators identify saved
cache/exported-snapshot and CIS Compliance output as independent load sources.
Named caches load through `LoadService.load_from_cache`; CIS selects an unzipped
`--raw` output directory and calls `load_from_compliance_output`. The latter
retains the core's existing automatic cache-save behavior after successful
processing. Cache listing refreshes after a successful load. All load modes use
the background worker and retain the previous displayed snapshot on failure.

Snapshot counts are compact and grouped: policies/statements/invalid statements
in one card; users/groups/dynamic groups together; resource-principal evidence;
and compartments. The resource-principal count is explicitly provisional: it
counts source statements whose parsed subject type is `any-user` or `any-group`,
including invalid statements that retain those subject types. It does not count
distinct resources, workloads, or proven resource principals. Invalid counts include source
statements explicitly marked `valid=False`; missing flags are not inferred to be
invalid. The footer shows the loaded repository's `data_as_of`, with an explicit
unrecorded state for older data. Coverage details remain on Overview.

## Browse source evidence

The browser has a local text filter plus a collapsible set of core-backed filters:
policy name, compartment, subject, resource, permission, condition text, effective
path, statement text, effect, verb, and validity. Core fields combine with AND;
pipe-separated alternatives use the existing search-builder semantics. Original
source records, including invalid statements, remain available in the inspector.
Text edits apply automatically after a 200 ms pause; dropdowns apply immediately.
The local text filter updates immediately across the displayed columns.

Right-click a statement in either table and select **Statement details** to open
the shared animated right-side drawer. Ordinary clicks only select rows.
It groups source, validity, parsed fields, conditions, and additional fields,
retains every supplied field, and includes raw JSON plus copy actions. Missing
validity/parse flags are labeled as unrecorded. Close or Escape hides the drawer;
the context-menu action reopens it. Navigation and successful reloads clear it.

**Dynamic groups** filters known inventory by domain, name, matching rule, OCID,
and in-use status. **All / In Use only / Not Used** is an exclusive button group
that applies immediately. Right-click a row for **Dynamic group details** to
inspect its matching rule; ordinary selection updates related statements. Ctrl/Cmd-click or
Shift-click selects several groups. The lower table shows the union of their
statements via `PrincipalAnalysisService.by_exact_dynamic_groups`, including
legacy ID-based references. Empty selection produces no statements. Inventory
filtering retains only visible selected groups, and the lower text search narrows
the displayed statements. Right-click a dynamic-group statement and choose
**Focus on Dynamic Group** to open this page, clear inventory filters, and select
the referenced known groups. Named navigation matches domain/name exactly without
case distinctions; opaque IDs retain their spelling. Missing inventory produces
an explicit coverage message. This page does not evaluate dynamic membership or
conditions against live resources.

The graph uses native Qt Graphics View items over `PolicyGraphService`, the same
service used by the existing graph interfaces. It shows principal → source grant
→ compartment path, with twelve grants per page, principal/path/resource or
permission/text/effect filters, pan, zoom, Fit, and selection-based evidence.
Conditions and source provenance remain in the inspector. Corpus exclusions are
shown separately (first 200, with an explicit count); all original statements
remain in the browser. Edges represent direct contributions, not inheritance or
evaluated allow/deny results.

## Logging and appearance

The **Logging** section lists declared application loggers (including unloaded
Tk/web/MCP modules) and registered runtime loggers in two compact columns, with
search and Refresh list. Discovery reads source declarations without importing
optional interfaces. Changing Global resets every component selector; **Apply
and save log levels** applies the result and saves it in the existing shared
application settings file. Component overrides can then be chosen independently.
Startup reads the saved INFO/WARNING/ERROR/CRITICAL global level and overrides;
without a saved choice, Qt defaults to INFO. Runtime loggers use a separate
`qt_runtime_log_levels` setting so their names are not remapped into the
application namespace. Unrelated application preferences are preserved.

Global DEBUG remains startup-only via `--verbose` (or `--debug`); its controls are
locked for that session and the startup override is not saved. Component DEBUG
is available during normal sessions, with output to shell/app.log only. The UI
handler rejects records below INFO before formatting/queueing, including direct
handler calls. The UI sink polls every 200 ms, batches at most 100 records per
tick, retains at most 5,000 pending records and 2,000 displayed lines, and reports
any overflow. The original core logger verbose behavior is unchanged.

**Show live log** or **View → Logs** opens a dock with Live log, Load activity and API Calls
tabs. Resize it, drag its title bar to float it as a separate window, or dock it
at the top or bottom. It opens only on explicit request, including when a load fails, and remains
usable across pages and during loading. Hiding it does not stop log capture.
Load failure messages remain visible on Overview and in the status bar. The window detaches
its UI handler and stops its timer on close. Choose all application components
or Qt-only output in the dock; file and shell handlers remain in place.

**API Calls** separates completed OCI request metadata from the live text log.
It captures calls independently of log levels: sort by time or duration, search,
select **Errors only**, and enable **Show details** for endpoints, targets,
request IDs and error interpretation. Pagination and retry attempts appear
separately. The in-memory history survives loads and retains up to 5,000 calls,
favoring errors; **Clear API history** leaves logs and snapshots unchanged.
See [logging and troubleshooting](logging_and_troubleshooting.md#qt-live-log-dock-and-separate-api-calls)
for capture scope and retention. MCP client activity has its own stream on
**MCP & Assistant**.

```bash
.venv/bin/python -m oci_policy_analysis.presentation.qt --verbose
```

**Intelligence** selects minimal query foundations (the default) or full post-load
intelligence, registered strategy checkboxes, and the same WHERE/service-principal
risk reductions used by desktop/web. Apply affects the next load, not the current
snapshot. **Look and Feel** applies and saves Light/Dark appearance, a separate
Forest/Ocean/Plum/Slate color palette, text size, and table density. The selectors
use compact widths. The sidebar never shows a horizontal scrollbar. A shared Fusion palette and stylesheet cover all current pages,
menus, selectors, scroll areas, log widgets, and the details drawer. Graph colors
are updated explicitly without reloading or querying the snapshot. File/directory
pickers use Qt dialogs so the selected theme also applies there.

## MCP and assistants

The **MCP** settings section copies a standalone server launch command; that
command runs a separate process and does not share the Qt context. In contrast,
**MCP & Assistant** in Advanced mode starts a managed loopback FastMCP server over
the loaded snapshot. Choose embedded Codex or Claude Code for streamed conversation
in Qt, or launch a separately configured Claude, ChatGPT, or Codex desktop app.
Loading is locked while this endpoint is running. Connecting an embedded CLI
starts no model turn; **Send** starts usage under its existing account and billing
configuration. Server-side MCP activity includes external clients.
See [Qt MCP and assistants](qt_mcp_codex.md) for setup and lifecycle details.

The application/window icon uses the existing packaged PNG. The PNG is included
in the wheel. The native build scripts also configure platform metadata using
the existing macOS `.icns` and Windows `.ico` assets. Source-run OS application identity can still belong to Python;
the runtime icon does not replace native bundle/executable metadata. See
[Qt application icons](https://doc.qt.io/qtforpython-6/overviews/qtdoc-appicon.html).

Pages receive the newly published context after every successful load. They do
not retain old engines or corpora across reloads. See the
[architecture](architecture.md#optional-qt-presentation) for presentation ownership.

**Resource principals** follows the existing desktop/web workload-principal flow.
Choose combined any-user/any-group, either subject alone, Dynamic Group, or OKE
Workload Identity. Resource types and OKE selector suggestions come from the
loaded conditions; OKE selectors also accept typed values. Resource compartment
filtering uses the principal's compartment OCID. Dynamic Group mode offers
multi-selection above the related policy table. Text search filters displayed
source evidence automatically. Right-click opens the shared detail drawer with
all conditions, validity, match confidence/reasons, and residual constraints;
dynamic-group statements also offer Focus on Dynamic Group. Counts represent
matching statements, not distinct resources or authorization decisions.

## Tkinter and Qt

Qt is a preview alongside the maintained Tkinter desktop, not a replacement for
`oci-policy-analysis-ui`. Both use shared application services. Qt adds its own
navigation, evidence drawer, Advanced workbench, and embedded assistants; do not
assume every Tkinter control has a direct Qt equivalent. The
[7.0 guide](release_7_0.md) and task guides describe the current workflows.

## Qt load lifecycle

A worker creates a fresh `AppContext` and runs the selected minimal or full
post-load profile. Only a successful load replaces the displayed context; failed
loads retain the previous snapshot. Closing while loading is blocked until the
worker finishes; the preview does not implement cancellation of OCI calls.
During embedded MCP serving, all load sources and controller requests are locked.
Closing with MCP or an embedded assistant active first shuts them down, then closes automatically.

This preview saves explicit appearance/settings choices through existing application settings. Opening a
snapshot does not rewrite its source file. Standard core cache-directory creation and process-wide logging still apply.
Counts and successful loads do not establish complete inventory or an
OCI-authoritative authorization decision. Full recommendations and permissions
reports are built only when the full profile is selected.

PySide6 is confined to the `qt` extra and presentation package. Existing desktop,
CLI, web, and MCP commands remain unchanged. Native Nuitka builds and their offline Qt/MCP smoke test are documented in
[run/README.md](https://github.com/agregory999/oci-policy-analysis/blob/main/run/README.md#local-build-and-clean); they package the same source and core as this preview.


## Policy limit controls


Qt Recommendations → Limits shows tenancy policy-object and compartment-hierarchy
statement limits, with their source, and recalculates inventory status when the
values change. Fetch limits from OCI is available only when the current repository
was live loaded and retains an OCI Limits client. Merely attaching a client to an
imported snapshot does not enable the action. Policy Inventory enforces the same
source check and shares the existing asynchronous worker and serialization gate.

For cache, exported JSON, CIS, or sample snapshots, Enter known limits opens a modal
with positive whole-number validation. It explains how to find the Identity limits
in Console → Limits, Quotas and Usage and supplies copyable OCI CLI commands:

```bash
oci limits value list --compartment-id TENANCY_OCID --service-name identity --name policies-count --all
oci limits value list --compartment-id TENANCY_OCID --service-name identity --name policy-statements-per-compartment-chain-count --all
```

See the [OCI CLI reference](https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/limits/value/list.html)
and [service limit documentation](https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm).
Use the actual tenancy values; the application does not assume 500.

`PolicyLimitsService` centralizes eligibility and explicit manual application.
Manual values update only the active snapshot and, for a named cache, its existing
optional `tenancy_policy_limits` metadata. Failure to save restores both in-memory
limit representations. Export/CIS source files and global preferences are not
rewritten. Cancel has no effect. The version-2/schema-3 format is unchanged and
older caches without limits remain supported; no migration is required.

Live `LoadService` collection automatically retrieves all Identity limit pages
before enrichment and cache saving, including minimal/none profiles. A missing
Limits permission or unavailable value produces a load warning and leaves limits
unknown; it does not fail otherwise successful policy collection. Both Qt views
are populated on initial publication. Fetch limits from OCI remains available as
an explicit refresh for live sessions.

Policy Inventory now uses the same manual-entry modal as Recommendations for
non-live snapshots; it no longer has separate inline limit editors. Recommendations
keeps a single limit summary and shows its feedback row only for progress or
errors. Snapshot resets clear previous limit metadata and the active cache name
so a new live load cannot inherit another snapshot's limits. Serialization stays
version 2/schema 3 with the existing optional metadata; no migration is required.
