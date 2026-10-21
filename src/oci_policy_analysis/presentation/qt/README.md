# Qt workbench status

The Qt workbench is an optional desktop presentation of the existing analysis
core. It is a working exploration of a replacement for Tkinter, with working analysis/settings pages and clearly labeled planned workflows. It is not yet a complete replacement or a separately released desktop
package. Keep this file current when adding a page, changing a core dependency,
or closing one of the gaps below.

## Start

From a source checkout, install the Qt extra and refresh the console commands:

```bash
uv sync --extra qt --extra web --extra mcp
source .venv/bin/activate
oci-policy-analysis-qt
oci-policy-analysis-qt --sample
oci-policy-analysis-qt --verbose
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. Without activation, use
`.venv/bin/oci-policy-analysis-qt` on macOS/Linux, or
`.venv\Scripts\oci-policy-analysis-qt.exe` on Windows. The equivalent module
command is `python -m oci_policy_analysis.presentation.qt`.

For an installed build that includes Qt, use `python -m pip install
"oci-policy-analysis[qt]"`, or install that build's wheel with the `qt` extra.
This branch's additions must be released before they are available from PyPI.
Add the `mcp` extra only when using embedded MCP. Codex additionally requires its
external CLI and the operator's login; it is not installed by either extra.
The existing `oci-policy-analysis-ui` command continues to launch Tkinter.

## Design goals and current assessment

| Goal | Current position |
| --- | --- |
| Core can be embedded without a desktop | Qt imports installed `application` APIs; core has no PySide6 dependency. |
| Shell owns navigation, not analysis | `main.py` composes pages, load publication, theme and window lifetime. Queries live in pages and shared services. |
| Reuse domain behavior | `LoadService`, `AnalysisService`, `PolicyGraphService` and `PrincipalAnalysisService` perform the work. Qt does not maintain a second policy parser, corpus or permissions engine. |
| Consistent interactions | Shared record/statement tables, right-click menus and one detail drawer retain all supplied fields. |
| Clear initial experience | Only Overview is enabled before loading. Settings start collapsed, filters are automatic in source/principal tables, and logs open only on request. |
| Responsive loading | A worker owns each candidate context. Success replaces the snapshot on every page; failure retains the previous one. Queries after loading still run on the GUI thread. |
| Evidence stays visible | Original text, validity, parsed conditions, residual constraints, exclusions and coverage remain inspectable. Counts are not OCI authorization decisions. |
| Deployable from installed dependencies | Console entry point, icon, reference data and sample are packaged. See the installed-wheel validation below. Local Nuitka executable builds include packaged startup checks; GitHub Actions builds and smoke-tests macOS arm64 and Windows x64 archives alongside the existing installers. Signing and notarization remain separate. |

The direction is sound: most Qt code is widgets, rendering and lifecycle glue.
The largest extra integration is the optional native Codex protocol client.
Avoid adding policy interpretation to pages or introducing a large generic UI
framework merely to reduce a few repeated widget layouts.

## Available now

| Page or shared feature | Scope |
| --- | --- |
| Overview & settings | OCI profile/instance principal, recursion and identity depth; named cache/export/CIS imports; grouped counts and data timestamp; collapsed settings sections. |
| Policy inventory | Non-advanced compartment, policy, tag and tenancy-limit inventory. |
| Policy browser | Live core filters and local text search; retained invalid statements; right-click details/copy/DG focus. |
| Policy graph | Native principal → source grant → compartment graph; live debounced search over all canonical and declared principals, conditions, exclusions and evidence inspector. All matching grants and related statements scroll without pagination; node selection fills the principal/path filters. |
| Users / Groups | Group-based and user-based subtabs; live domain/name/OCID filters, multi-selection, per-user membership evidence (including unresolved group IDs), selected group members, related policy statements and right-click details. |
| Dynamic groups | Known inventory, All/In Use/Not Used, exact domain/ID matching, multi-selection and related statements. |
| Resource principals | any-user/any-group modes, resource type and principal-compartment selectors, exact DG multi-selection, OKE selectors, confidence and full evidence details. |
| MCP & assistant (Advanced) | Explicit loopback snapshot server, query-only tools, readiness check, stop/restart; optional model selection and streaming Codex conversation. |
| Reports (Tools) | Explicit background generation, JSON/Markdown/rendered HTML previews, portable exports and snapshot/task locking. |
| Logging | Global reset and component controls, saved levels, bounded INFO+ live view. Startup DEBUG and component DEBUG remain in shell/file output. |
| Appearance | Light/Dark, four accent palettes, Small through Extra Large text sizes, optional fixed-width table/Overview font, responsive Overview rows and row density; shared widget and graph theming. |

The sample has 100 policies / 325 statements, 25 groups, 50 users with one to four
memberships, 12 dynamic groups, 22 compartments and three deliberately invalid
records. It reconstructs anonymized CIS landing-zone patterns with fictional
inventory and additional resource/OKE examples. It is not a CIS deployment
template. Loading it uses the packaged JSON and `LoadService`, never an operator
cache or OCI connection.

## Module and core boundaries

- `launcher.py` / `__main__.py`: lazy console/module launch and missing-extra guidance.
- `main.py`: shell, page composition, navigation and window shutdown.
- `controller.py` / `loading.py`: serialized background loads and snapshot publication.
- `pages/`: independent views; receive the current `AppContext` on successful load.
- `tables.py` / `details.py` / `widgets.py`: reusable presentation elements.
- `preferences.py`, `settings_panels.py`, `logging_panel.py`, `logger_catalog.py`:
  shared settings/logging services with Qt-specific controls and delivery.
- `themes.py` / `icons.py` / `sample_data.py`: appearance and packaged resources.
- `mcp_host.py`: optional host using `oci_policy_analysis.mcp_server.create_snapshot_server`.
- `codex_client.py`: optional external-process protocol adapter; no model request
  occurs until Send.

Never retain an engine or corpus across reloads; read the newly published
context. Constructing `AppContext` loads reference data and changes process-wide
logging levels, but does not load a tenancy. A failed load must not partially
replace visible data. While embedded MCP/Codex is active, loading stays locked
until shutdown so all consumers see one snapshot.

Shared settings and caches intentionally use the core's existing storage.
Source snapshot files are not rewritten by inspection. CIS import retains the
core loader's automatic cache-save behavior. The core's mutable contexts and
process-wide logging are not isolation guarantees for multiple embedded apps.

## Path to a separate pip-installed Qt app

It can already run from this project's installed wheel without repository
scripts, a source checkout, Tkinter UI imports or a local web server. That is
not yet the same as independent distribution.

Before extracting it:

1. Give the Qt app its own import namespace and packaging metadata. Internal Qt
   imports currently use `oci_policy_analysis.presentation.qt`; move those
   together while keeping backend imports on the published application APIs.
2. Declare PySide6 and a tested compatible `oci-policy-analysis` version range.
   Keep MCP optional; the current snapshot factory lives in the core package's
   top-level MCP adapter and needs its `mcp` extra.
3. Preserve installed-resource access with `importlib.resources`; move app-owned
   icons/sample/README with the app, and leave permission reference data with core.
4. Add an installed-wheel compatibility test against each supported core version,
   plus native macOS/Windows/Linux launch and shutdown checks.
5. Decide whether the app should share the core's preferences/cache location or
   use an explicit application settings namespace.

Existing coupling to track: pages read repository inventory dictionaries, the
Overview/controller read a private collection-error attribute, and logger
catalog discovery scans installed core Python sources. Those work in a normal
wheel but are weaker contracts than focused public service results, especially
for frozen or source-stripped builds. The base distribution also still installs
Tkinter-related `tkhtmlview`; the empty `core` extra does not remove base
requirements. None of these facts requires duplicating core behavior in Qt.

## Experience modes and navigation

`experience.py` owns the window's `ExperienceMode`. The prominent Overview
checkbox switches immediately and persists only `qt_advanced_mode`. Standard is
the default. Mode changes do not change snapshot data or enrichment settings.
This is an ease-of-use preference, not an authorization or security boundary.

The `main.py` `page_specs` registry defines navigation labels and advanced-only
pages in one place. Overview and Tools are available before a snapshot load; analysis destinations require a
successful load. Mode and data availability are independent conditions. Turning
off Advanced mode on an advanced page returns to Overview; widget state stays
owned by the page so future draft editors need not lose unsaved work.

- Standard: existing overview/browsing/graph/principal/MCP pages, Recommendations,
  and Tools. Recommendations is explicitly not an advanced feature.
- Advanced adds: Prospective statements, Simulation, Consolidation and the
  Maintenance tab within Tools.
- Tools is one left-nav destination with native `QTabWidget` tabs for Condition
  Tester, Reports, Maintenance and Logging. Logging opens the existing dock and
  Overview settings rather than creating another handler or settings copy.
- Consolidation implements a four-stage workbench: Protect / Lock, Statements &
  Strategy, Review plan, and Execution / History. Shared services persist protection,
  plans, notes, and progress; checkbox IDs survive filtering. Console/CLI instructions
  and rollback can be copied or exported. Live progress checks run in a retained worker,
  gate competing tasks, and rebuild derived snapshot analysis after policy refresh.
  OCI policy changes remain manual. Maintenance supports saved-cache rename,
  lock/unlock and confirmed deletion, plus tenancy-specific consolidation reset.
  Reset removes local protection/history/rollback snapshots and refreshes the active
  workbench without changing OCI or inventory caches.
- The Logs dock includes API Calls, a bounded, process-local journal independent of
  log levels. The repository observes SDK HTTP attempts (including pagination and
  retries) and retains timing, status, reason, and request IDs without bodies or
  credentials. Collection errors remain errors; policy 404s explain possible stale
  search results or insufficient authorization. Clear/restart discards the journal.

For future controls, call `experience.bind_advanced(widget)` or
`experience.bind_advanced_tab(tab_widget, index)` during page construction.
For a different layout or display density, subscribe to `experience.changed`
and read `experience.advanced`. Do not read persisted settings independently in
every widget. Keep source evidence, validity and coverage available in Standard
mode too. Mode changes must never implicitly start an operation or discard drafts.

Prospective statements now provides a tenancy-scoped saved list with Add/Edit
modal dialogs. The guided builder uses existing principals (including inventory
principals without grants), resources, compartment/effective paths and tag/custom
conditions from shared builder services. Copy the generated preview into Text &
validation, or paste an ad-hoc statement directly. Validation uses the existing
simulation engine. Invalid drafts may be saved and retain diagnostics.

Saving/deleting persists through `ProspectiveStatementsService`, updates simulation,
and refreshes the policy browser and graph. Advanced mode includes clearly marked
prospective evidence in both views; Standard mode hides every prospective row,
grant and exclusion, including records saved in prior sessions. Risk selection
uses the existing potential-risk heuristic on a detached statement/repository;
it does not alter source intelligence or evaluate conditions into OCI decisions.
Persistence remains the existing standalone per-tenancy prospects format; combined
cache version/schema and source snapshots are unchanged. No migration is needed.
Simulation implements Environment, Statements, Request context and Results & history. Environment provides identity
and compartment controls, a live summary and a separate saved what-if preview.
Manage prospective statements opens the existing editor. Next prepares candidates
in an owned worker. Statements provides native checks, source/effect/path/reason
columns, filtering, scoped bulk actions, inclusion counts and Back/Next navigation.
Request context provides catalog operation selection, primary permissions,
advisory related checks, condition inputs and a copyable request preview.
Run evaluates the loaded model in an owned worker. Results explain missing
permissions, conditions and denies, retain full evidence/history, and offer
related scenarios and reviewed local what-if policy candidates.

## Scoped next workflow: checkbox tables and simulation

Design scope reviewed on 2026-10-16 against desktop `data_table.CheckboxTable`
and `simulation_tab.SimulationTab`. This is a proposed implementation sequence;
the reusable checkbox component and all four simulation screens are implemented.
The sections below retain the original design contract and implementation order.

### Native Qt checkbox table

Implemented in `selection_table.py` as `CheckableRecordModel` and
`CheckedRecordTable`, sharing `RecordTable` rather than duplicating its view,
proxy or context menu. Downstream workflows have not been wired yet.

Extend the existing `QTableView` / `QAbstractTableModel` approach. Expose a
leading checkbox column through `Qt.CheckStateRole`, `Qt.ItemIsUserCheckable`
and `setData`; let the standard delegate paint and toggle it. Use model change
signals instead of rebuilding the whole table or inserting one widget per row.
Retain the shared sorting/filter proxy, statement context menu and detail drawer.

Checked inclusion and highlighted-row selection are separate concepts. Ordinary
clicks inspect/select a row; checking explicitly includes it in the next step.
Space toggles the focused checkbox using Qt's standard delegate behavior.

Keep one authoritative checked-ID set for the workflow, outside source evidence.
Require stable, unique statement IDs from core; never use display row numbers or
object identity as the selection contract. Sorting and filtering must preserve
checks. Show total checked and hidden-checked counts. Provide **Check visible**,
**Clear visible**, and a separate **Clear all checks**; filtering must not silently
remove previously included statements. Retain ineligible evidence as visible,
uncheckable rows with an explanation. Displaying invalid evidence must not imply
that it can be evaluated successfully.

Preserve checkbox/action callbacks as Qt signals and pass checked source IDs to
the workflow controller. Do not insert Qt variables or `checked` fields into the
core statement dictionaries. On snapshot replacement, clear checks and all
snapshot-bound downstream state. This component can also serve future comparison,
consolidation and report-selection flows.

### Simulation page shape

The desktop currently has three subtabs implementing four logical steps.
Prefer one Qt Simulation navigation page containing a native `QTabWidget` with
four focused subpages, Back/Next actions and prerequisite validation. This suits
iterative what-if work: users can return to earlier inputs and rerun. `QWizard`
is an alternative for a strictly guided, linear workflow; it is not required for
an embedded workbench page.

| Subpage | Interaction | Core boundary |
| --- | --- | --- |
| 1. Environment | Principal/type and effective compartment; scenario summary; clearly separate prospective what-if editor/preview. | Canonical principal resolution and candidate discovery through the simulation service; prospective validation/storage through existing services. |
| 2. Statements | Native checkbox table, filters, visible-only bulk actions, counts, source/prospective badges and right-click details. | Candidate source records and evaluation eligibility, not a new UI policy matcher. |
| 3. Request context | API/catalog group and operation, required permissions, condition inputs derived from checked statements; preserve values for fields still needed. | Reference-data APIs and selected-statement condition-field extraction; blank values stay unsupplied. |
| 4. Results & history | Model outcome, required/missing permissions, per-statement evaluation table, trace details, saved-run selection and explicit JSON export. | `SimulationService.run`, engine trace/history exposed through focused service methods. |

A controller should own a plain Python scenario state: snapshot identity,
principal/key/path, checked IDs, operation, condition values and last result.
Upstream changes invalidate downstream results; do not present an old result as
current. Changing only checkbox inclusion preserves values for still-relevant
condition fields. Results/history retain the original inputs and provenance;
history from a prior snapshot must be cleared or explicitly detached and labeled.
Keep prospective evidence separate from collected policies and source caches.

### Reviewed downstream service contracts

| Service | Table contract and boundary |
| --- | --- |
| `SimulationService` | `run` accepts explicit `checked_statement_ids`; keep `None` distinct from an empty list. Candidate discovery is available through `statement_candidates`; `request_context_schema` prepares per-statement condition inputs for checked-subset projection. |
| `ConsolidationWorkbenchService` | Candidate/protection rows expose `internal_id`; checked IDs can feed explicit `create_proposal` or `set_protected_set` actions. Service exclusions remain authoritative. Proposal creation persists a run, so never trigger it on checkbox changes. |
| `RecommendationsService` | Read-only sections have different shapes and often no stable action ID. Display them with `RecordTable`; any checked-action adapter must receive a proper ID from core, never a row number or fuzzy text match. Some display text is truncated, so full-source details also need a source reference. |

The checked model accepts a caller-provided `key(record)` and eligibility
predicate, supporting source IDs, candidate IDs or plan-step IDs. It stores
checks outside evidence, rejects duplicate IDs, disables missing-ID rows, and
clears inclusion on replacement by default. `preserve_checks=True` is only for
an intentional refresh within the same snapshot and workflow. It must not cross
tenancy/snapshot boundaries. `add_checked_action` receives the current ID list
only on an explicit click; pages own domain validation and service calls.

### Core work and implementation order

`SimulationService.prepare` already resolves the canonical principal key and
condition fields for the whole context; `run` already accepts explicit checked
IDs. It now provides the candidate statement list through `statement_candidates`.
`request_context_schema` supplies per-statement condition variables and diagnostics
for checked-subset projection. Operation metadata comes from ReferenceDataService;
`SimulationWorkbenchService` supplies history, execution explanations, related
scenarios and reverse permission mappings. Expose orchestration
through focused shared APIs rather than copying the desktop's key construction,
condition parsing or engine orchestration into Qt. Reuse
`ProspectiveStatementsService` and `ProspectiveBuilderService` for what-if data.

1. Implemented and tested the reusable checkbox model/table:
   stable checks across sort/filter, bulk scope, disabled rows, source immutability,
   keyboard toggles, details, and reset on snapshot replacement.
2. Add focused simulation service APIs with compatibility coverage. Preserve the
   engine distinction: `checked_statement_ids=None` means all applicable rows;
   `[]` means no rows. Never turn an empty selection into a run of all policies.
3. Build Environment → Statements → Request context → Results using separate page
   modules and one controller. Preserve the current default of checking eligible
   candidate statements, with explicit counts before running. Offer baseline and
   what-if runs before adding a richer comparison view.
4. Run preparation/evaluation in an owned worker and serialize mutation of the
   active simulation engine, prospective state, history and snapshot loads.
   Audit interaction with embedded MCP before permitting concurrent mutations.
   Keep validation, unsupported conditions and coverage visible in results.

The UI must describe a model result from the loaded snapshot, including missing
inputs and residual/unsupported conditions, not an authoritative OCI decision.
No cache schema migration is needed for the proposed UI-only selection state.
Do not add simulated results or corpora to combined-cache snapshots.

Qt references: [model/view programming](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-model-view-programming.html),
[QTabWidget](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTabWidget.html),
and [QWizard](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWizard.html).

## Next milestones and review record

- [ ] Complete parity inventory before porting more pages: identity membership,
  cross-tenancy, tags, intelligence results, simulation, consolidation and reports.
- [ ] Exercise large real snapshots; measure GUI-thread filter/graph work and move
  expensive queries to owned workers if needed. Add load cancellation/timeouts.
- [ ] Improve keyboard/screen-reader workflows, narrow-window layouts, state
  restoration and native application/installer metadata.
- [ ] Introduce public inventory/diagnostic results where extraction needs a
  stable contract; avoid adding shims for removed 7.0 import paths.
- [ ] Add Qt-specific CI, native packaging (including any pyside-deploy choice),
  and installed-wheel regression checks. Existing frozen desktop checks cover Tk.
- [ ] Test the optional assistant against supported live Codex CLI versions.
  Protocol stubs cover failures and streaming, not every future CLI release.

Review on 2026-10-15: inspected the Qt modules, core boundaries, source/evidence
handling, worker/process lifetime, optional dependencies and packaging. No
blocking correctness defect was identified in the existing page or MCP/Codex
paths. Added a console launcher with actionable missing-extra guidance. The
working-tree tests use isolated settings/cache storage and fictional snapshots;
they do not exercise live OCI collection or paid model turns.

Installed-wheel validation on macOS/Python 3.13: built the source distribution
and wheel, installed only the wheel's `qt` extra in a fresh virtual environment,
and ran outside the checkout with Python isolated mode. The console help,
six-page shell, packaged icon/reference/sample data, sample load, graph,
resource-principal filter and detail drawer passed. Tkinter, tkhtmlview,
FastAPI, FastMCP and the other presentation adapters were blocked from importing.
Full project suite: 567 passed; Ruff, project/docstring checks and Sphinx passed.
These checks do not certify other native platforms or frozen Qt installers.

For focused checks, run `python -m pytest src/test/test_qt_launcher.py
src/test/test_qt_workbench.py -q`. Before release, run the full project checks in
[AGENTS.md](../../../../AGENTS.md), build a wheel and verify it from a directory
outside the checkout. See [embedding and lifecycle guidance](../../../../docs/source/core_integration.md)
and the [MCP/Codex guide](../../../../docs/source/qt_mcp_codex.md).

Update on 2026-10-16: added the saved central experience-mode switch, navigation
registry and planned workflow destinations, native Tools tabs, and reusable
checked-record model/table. Real simulation/consolidation/recommendation row
shapes were exercised without running proposal mutations. Full suite: 570
passed; Ruff, project/docstring checks and Sphinx passed. Native checkbox
keyboard behavior, sorting/filter retention, visible-only bulk scope, duplicate
IDs, missing IDs, reset semantics and source immutability are covered. Future
workflow destinations are explicitly labeled planned; the simulation and
prospective editors were not built at that point. The prospective workspace described above supersedes that placeholder.

Graph selection now populates a Related statements table. A grant selects the
principal/resource/effect/effective-path combination across all source statements,
including contributions beyond the current graph page; principal and path nodes
show their related combinations. Right-click a row for the shared details drawer,
which retains the source record and adds complete direct permission facts with
conditions, effect, scope and provenance. Facts remain modeled contributions,
not evaluated OCI decisions. Graph refresh, pagination and mode changes clear
stale table and drawer evidence. The default window is 1440 pixels wide. Collection
time appears only in the app status-bar footer, outside all page content.

## Condition tester

Tools → Condition Tester works in Standard and Advanced modes without loading a
tenancy. Enter a condition, leading `where` clause or complete statement, then
**Parse and generate inputs**. JSON shows the logical structure, predicate atoms
and diagnostics. Fields cover variables on either side of comparisons, including
list references. Quoted literals stay in the parsed expression.

Supply simulated values and choose **Test condition** for the boolean condition
result, individual comparisons and complete result JSON. Blank fields and explicit
**Null / not supplied** toggles use shared null semantics; `!variable` matches when
the variable is absent. Missing right-hand variable references fail comparisons,
including inequality, rather than being interpreted as literal variable names.
Changes to the expression disable testing until reparsed; input edits clear old
results. Formatting preserves existing inputs for variables still present.

Statement tables in the browser, graph, principal views and prospective workspace
have a **Test condition…** context action when a clause is available. Known dynamic
group inventory can hand off its matching rule through the same action. A handoff
clears old simulated values, parses the selected clause and opens Tools. No test cases are saved to settings or caches, and a matching condition does not establish OCI access.

Regression fixtures harvest 81 distinct clauses from checked-in tests (including
unsupported syntax) with their source locations. The test matrix checks parsing,
variable discovery and format/evaluation equivalence for absent, null and supplied
contexts, alongside explicit expected outcomes for nulls, RHS variables, lists,
patterns, timestamps and nested logic.


### Simulation Environment implementation

`SimulationService.environment_options` supplies read-only inventory and policy
reference choices, including distinct identity domains and opaque principal IDs.
Users appear only with loaded user inventory. Wildcard identities do not require
a separate principal selection. Missing compartment inventory leaves the scenario
incomplete instead of inventing a target path. A snapshot replacement clears the
selected environment and returns to the first tab. Environment selection does not evaluate policies or record history. Statement
preparation runs in an owned worker and blocks competing snapshot/prospective
mutations; an active embedded MCP server must stop before preparation.
Saved prospective records are shown separately without claiming they are in scope
or eligible. Combined-cache compatibility is unchanged; no migration is required.


### Simulation statement selection

`SimulationService.statement_candidates` uses the engine's principal/scope
matching on detached repository records because legacy principal reconstruction
can enrich its input. Corpus facts and exclusions supply selection eligibility;
the Qt adapter does not implement policy matching. Invalid prospective drafts
are shown uncheckable with scope explicitly unverified. Missing IDs cannot be
checked. Identical repeated records with the same ID are collapsed on detached
copies at both source and candidate stages. Conflicting records sharing an ID
still fail preparation rather than selecting ambiguous evidence. Source evidence and cache payloads remain unchanged.

Eligible rows are initially checked. Highlighting and checked inclusion stay
independent, and filters preserve hidden checks. Back/Next retains an explicit
empty selection. Changing identity, compartment, saved prospects or snapshot
invalidates candidates and downstream state. A controller revision rejects
obsolete worker results; worker lifetime is owned through completion and window
close is deferred during preparation. The shell blocks reload, prospective editing
and embedded MCP startup during preparation; starting preparation while embedded
MCP is active shows a stop-server instruction. No access decision or history entry
is produced in this stage. Combined-cache version/schema remain unchanged and no
migration is needed.


Simulation diagnostics are logged at INFO by `qt.simulation` and
`application.services.simulation`, both available in Overview → Logging.
The live log scope **Simulation** includes these components, the simulation
engine and corpus builder. Logs include source/candidate counts, identical
duplicates collapsed (ID, policy and path), corpus fact versus distinct statement
counts, eligibility totals and preparation failures with tracebacks. Conflicts
identify the stage and differing fields. Source IDs are hashes of policy ID plus
statement text, so identical repeated statement evidence can legitimately reuse
an ID; corpus permission facts also share statement IDs but are not selection rows.
De-duplication changes neither loaded source records nor cache files.


### Simulation request context

Environment places principal type and identity on the same horizontal row.
Request context uses API catalog groups and case-insensitive operation filtering.
Choosing an operation uses its qualified catalog label, shows primary permissions
and notes, and keeps advisory related checks in a separate tab. Filtering out the
selected operation clears it; it never silently selects another operation.

Condition schemas are parsed during the owned preparation worker. Only checked
statement variables appear; values survive checkbox changes for fields still
needed and are removed when their field is no longer needed. Unsupported clauses
retain their source and warnings in Condition evidence. `request.operation` is
automatically derived from operation metadata, matching the engine, and has no
manual override. Blank and explicit null values are omitted from the request
context, and no condition is evaluated during preparation.

A Request preview tab and Copy request JSON action show the exact environment,
qualified operation, explicit checked-ID list (including `[]`) and supplied values
for review. Snapshot/environment changes clear all request state. Run now
evaluates these explicit inputs and opens Results & history. These inputs live
only in memory; combined-cache version/schema and persisted sources are unchanged.
No migration is required.


### Execution, results and guided follow-up

Run records the original principal, operation, effective compartment, explicit
checked IDs, condition values, provenance and outcome. Native permission tables,
expandable statement evidence and condition comparisons explain missing grants,
failed conditions and matching denies. Full JSON remains available for export.
Edited inputs mark saved results as historical; original runs are not rewritten.
History includes primary, related and prospective reruns. Refresh includes other
engine consumers; legacy runs retain full raw trace. A snapshot replacement clears
the active history view. Runtime snapshot IDs prevent using old results to draft
against a different loaded engine.

Related simulations resolve structured dependency metadata to valid catalog
operations. The user must choose a target compartment and prepare a fresh
statement set. Primary-path advisory permission checks do not prove access in a
different compartment. LaunchInstance now links to the existing LaunchInstance
(Subnet) operation; the reference source is documented in the simulation guide.

The policy-candidate service reverse maps missing permissions through the bundled
resource/family catalog and includes corpus source examples with principal, path,
condition and provenance intact. Users choose a grant-bearing principal, explicit
permissions/resource/family granularity, policy and effective compartments, and
optional operation/custom restrictions. Resource/family choices list additional
permissions; greedy coverage may produce multiple statements and is not a proof
of globally minimal privilege. Unmapped permissions remain visible. Generated
text must pass parser validation. Direct user grants are not generated; wildcard
principals require a restriction. Matching denies still apply.

Select one or more drafts and use the existing prospective editor to review and
save each locally. Cancel changes nothing. After a save, a fresh preparation
retains previously checked IDs, adds new eligible prospects, restores the original
operation and surviving values, and returns to Request context. New fields remain
unsupplied for review; the user explicitly runs again. No OCI policy is created.
Workers serialize execution, corpus preparation and suggestion generation against
reload/prospective mutations and embedded MCP; shutdown waits for active work.
History and reports remain runtime-only. Standalone prospective persistence and
combined-cache version 2/schema 3 are unchanged; no cache migration is needed.

Scoped reference-operation entries may declare optional `request_operation`
metadata. The engine, request preview and saved report use that actual API name
for conditions; absent metadata retains the existing operation-name fallback.
The subnet helper maps to LaunchInstance. This is bundled reference metadata,
not a stored snapshot field, and requires no cache migration.


## Local Qt executable builds

Use `run/build-executable.sh qt` or `run/build-executable.ps1 qt` to build the
checked-out source with Nuitka and its PySide6 plugin. `--mode onefile` selects a
single executable on the native platform; macOS standalone builds produce an app bundle.
`--dry-run` prints the exact command. The shared Python builder runs source
startup checks, compiles, exercises the resulting executable with an offline
`--self-test`, then archives it under `dist/qt/`. See `run/README.md` for compiler
prerequisites, output paths and platform limits. The existing `build.yml` also
uses the official Nuitka action with persistent compiler caches and attaches
verified macOS arm64 and Windows x64 archives to the branch release. Extract the
entire Windows ZIP before running `oci-policy-analysis-qt/oci-policy-analysis-qt.exe`.
Signing and notarization remain separate.

The browser's Subject types menu selects an exact union of loaded parsed types;
its shared `exact_subject_types` filter keeps `group` distinct from
`dynamic-group`, `group-id` and `any-group`. Existing substring filters retain
their behavior. Detailed Filters appears below the main search. Subject type
remains in source records and details while its table column is hidden.

Simulation's Request JSON tab shows the read-only local simulation input,
including the principal, operation, target, condition context and statement
selections. Opening/copying it does not send an OCI request.


## Reports

Tools → Reports offers Policy Inventory, Effective Permissions, Policy Supersession
and Full Policy Overlaps through the same service as Tk/web. Press Run report to
generate in the background, preview JSON/Markdown/rendered HTML, and explicitly
export. Snapshot replacement clears previews; simultaneous loads, simulation,
prospective editing and embedded MCP are blocked during report work. Full
permissions require Full enrichment; supersession depends on existing strategy
findings. Report counts and empty findings do not establish authoritative access.


## Native Recommendations

Recommendations is a Standard-mode page using the shared dashboard service:
Summary, policy/statement risk, supersession, cross-tenancy, consolidation,
cleanup guidance and limits. Search/filter/sort tables and right-click or
double-click for evidence. Supersession has a formatted resizable dialog with
full source, scope, conditional qualifications, and separate permission coverage.

Run analysis explicitly rebuilds full derived state and report prerequisites with
configured checks and risk reductions. The worker retains the context and gates
loads, simulation, reports, prospective edits and MCP until finished. Consumers
rebind even after partial failure; local prospective statements and their CRUD
manager survive simulation-engine replacement. Stale completions are discarded.
Tk cleanup tracking/ignores and consolidation plan handoff are not yet exposed.


## Historical comparison

Advanced mode adds Historical comparison immediately above Tools. It compares
named caches or explicit JSON files independently of the active AppContext.
A retained worker reads each source once and calls HistoricalAnalysisService.
The shell gates competing tasks and closing; input-generation checks discard
obsolete results. Policy and IAM queues preserve per-section coverage reasons.

A resizable inspector renders presence-aware typed deltas as expandable field
paths and complete original records using a lazy QAbstractItemModel JSON tree.
No browser component or JSON UI dependency is required. Export/copy retain full
JSON. Default comparison omits only entity-level ephemeral IDs, uses exact source
identity for statements, and preserves duplicate statement occurrences. Nested
JSON/tag keys remain literal; original sources are never normalized in place.


Successful live OCI loads always request a new combined-cache snapshot through
LoadService, including Query foundations loads. Overview and Historical comparison
refresh their cache choices after publishing the load. Opening an existing cache,
JSON file or fictional sample stays read-only and does not create another cache.

Qt historical comparison enables **Compare incomplete snapshots with warnings**
by default. Collection errors mark an entire snapshot incomplete, even when the
policy inventory contains useful differences. Observed additions/removals remain
unverified: a missing record can reflect a collection gap. Warnings accompany
section counts, JSON inspection, copy and exports. Turning this option off keeps
strict coverage gating and explicitly reports when no sections were compared.
Missing sections, incompatible scope and inherited IAM remain excluded. The shared
service retains strict behavior by default; callers opt in with `include_incomplete=True`.

Maintenance is an Advanced tab under Tools. Search and select a cache to rename,
lock/unlock or delete it. Names use `tenancy_label` and cannot contain paths or
Windows-invalid filename characters. Rename retains source bytes and lock state
and never overwrites another file. A lock is the existing index `preserved` flag:
it prevents automatic cleanup and manual deletion until unlocked. Delete requires
confirmation. Cache selectors refresh after changes; the loaded snapshot stays in
memory. Mutations are blocked during loads, analysis, reports, simulation, historical
comparison and embedded MCP. Combined-cache version 2/schema 3 and index field
names are unchanged; no migration is required and old snapshots remain readable.


## Usage publication and companion analytics

Overview & settings includes a Usage tracking section. Publication defaults on
while preserving an existing shared opt-out; disabling immediately discards
pending data. The launcher creates a UsageSession; embedding WorkbenchWindow
keeps publication off unless `record_usage=True` is explicit. Events use fixed
page/subview identifiers and aggregate counts; no user input or policy contents
are recorded by the Qt adapter. Background uploads occur on exit and tenancy
changes; there is no disk spool or retry.

Run `python -m oci_policy_analysis.analytics.qt` or `oci-policy-analysis-analytics`
for the companion Qt viewer. The native executable supports `--analytics` and
`--days 0` for all history. It requires a separate runtime read/list PAR via
`OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL` or its masked input, or local JSON exports.
It uses shared models and aggregations, keeps old documents readable, reports
partial reads, follows listing pagination, and never publishes tracking. The
frozen smoke check covers both windows offline. Full review and setup details
are in `docs/source/usage_tracking.md`.


## Startup preferences and policy browser presentation

Overview restores the shared `named_profile`, `instance_principal`, `recursive`,
`load_all_users` and `domain_compartment_depth` preferences at startup. Qt retains
profile/instance-principal selection in `qt_auth_mode`. Changes save after a short debounce;
an explicit OCI load or orderly close flushes pending edits. Unchanged controls do
not overwrite newer settings written by another interface. All saves merge only
the affected keys. No authentication or collection happens while restoring them.

Intelligence's Apply button persists the full/minimal post-load profile, enabled
checks and both risk reductions. The reductions share a row, with a narrow-layout
fallback, and the checkbox grid is labeled Enabled intelligence checks. Applying
changes configures future loads without modifying the active analysis. Appearance
Apply continues to save theme, color palette, text size, compact rows and fixed-width
fonts. Restart coverage verifies these alongside canonical and runtime log levels.
Saved DEBUG is distinct from the explicit `--verbose` session lock; component
overrides survive startup and subsequent loads. The live GUI log remains INFO+.

The Policy Browser uses the shared compartment/policy formatter for a single Policy
column, followed by Effective path and Original statement. It no longer displays
Valid or Subject type columns; existing validity and subject filters remain. Rows
with explicit `valid=False` are italic and use a theme-aware red foreground. Missing
validity retains normal styling. A legend beside the counts explains the highlighting
and right-click inspection. Invalid reasons appear in a bounded, scrollable plain-
text summary above the fly-in tabs, with Validity expanded before Source. Records,
conditions, invalid evidence and raw JSON are retained unchanged. No cache migration
is needed.


## Shared policy evidence and cross-tenancy

Statement tables share combined compartment/policy labels, effective paths, and
red italic styling for explicitly invalid rows. Right-click opens the retained
source record. The drawer groups source evidence under Basic Details, keeps
internal IDs and tags under Additional Details, hides empty optional fields, and
opens Validity with bulleted reasons for invalid statements. Raw JSON remains
complete, including fields omitted from the formatted display.

The group-based Users / Groups view can filter groups by a known member's
username or display name. Alternatives separated by `|` are ORed; other inventory
filters are ANDed. Missing user or membership inventory cannot establish membership.
This query lives in `PrincipalAnalysisService.filter_groups_by_user` for reuse.

Cross-tenancy uses `CrossTenancyAnalysisService` and the current immutable corpus,
matching the web and Tk interpretation. Select tenancy nodes, directed links,
relationships, entities, or findings to narrow parsed source evidence. Graph
selection filters without opening the details drawer. The combined Define, Admit,
and Endorse table opens source details from its right-click menu; unresolved
statements appear in Findings. The Entities / definitions tab labels local
ownership with the tenancy name. **Generate single Cross-Tenancy Policy** orders
valid, resolved statements as Define, Admit, then Endorse and reports omitted
invalid, unresolved, and unclassified statements. Duplicate source occurrences
remain separate. Local relationships do not establish that remote reciprocal
policies exist.
Local relationships do not establish that remote reciprocal policies exist.
Recommendations' Cross-tenancy tab reads the same corpus findings; run analysis
there to build findings when loading only query foundations. No cache schema
migration is needed; these views do not rewrite source caches.


The non-advanced Policy Inventory page shows compartment hierarchy counts,
policies, source statements and tag values from the active snapshot. Select a
compartment or policy to narrow the linked evidence; text search applies across
all inventory tabs. Live OCI tenancy limits are fetched only when requested.
Cached and CIS snapshots allow positive limits to be entered; applying them
updates the active cache when one is named and refreshes Recommendations. A CIS
load without a named cache retains that override only for the current session.

Supported consolidation recommendations offer **Create consolidation plan…** on the row context menu. This opens Advanced Consolidation with currently eligible source IDs selected and the recommended strategy; protected, invalid, system, or missing IDs remain excluded. Review the selection and explicitly generate a plan to save it. Recommendation details display an expandable Evidence JSON tree.

The Advanced **Live tenancy** controls include a saved **Policy loading** selector:
Resource Search (default) or Compartment-based Policy Get. Both use the shared
live-policy loader and identical parsing; the compartment option bypasses the
policy search index. Recursive scope remains independent of identity-domain depth.
The Logs dock can be resized without being constrained by the hidden pages' minimum
heights. API Calls gives its table all available space by default; **Show details**
or the row context menu opens a resizable details pane. Hide it again for more rows.

Recommendations → Limits shares Policy Inventory's explicit live fetch. It requires
policies live loaded in the current session and a Limits client. Offline snapshots
instead offer Enter known limits, a validated modal with Console/CLI guidance and
copyable commands. Both pages immediately reflect applied limits; named caches
retain manual values, while exported/CIS files and global settings are unchanged.

Live loads now fetch policy limits automatically before enrichment/cache saving
regardless of the analysis profile; unavailable limits remain unknown with a load
warning. Both limit views populate immediately. Inventory uses the same modal as
Recommendations for manual entry, with no separate inline editors. Recommendations
shows one summary; its extra feedback row is reserved for progress or errors.


### Tag-Based Policies (Advanced)

The application window is titled **OCI Policy Analysis · Preview**. Advanced navigation
includes **Tag-Based Policies**, with searchable statements, parsed tag predicates and a
snapshot defined-tag catalog. Scope, namespace, key and value filters apply to the same
predicate. Invalid statements and unparsed references remain visible; details retain the
complete source condition. Select a row to populate the Condition Tester with the full
condition or a selected tag predicate. Evaluation requires user-supplied values and does
not establish OCI authorization. Tag-based consolidation is deferred.

Desktop loading offers profiles/session tokens and Instance Principal. Stale saved Resource
Principal selections fall back to profiles. Container web/MCP authentication is unchanged.
The legacy desktop OCI GenAI query pane and configuration were removed in 7.0.
