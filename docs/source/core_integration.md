# Embedding and Integrating OCI Policy Analysis

OCI Policy Analysis can be used as more than a desktop application. Its core
loads, preserves, validates, and analyzes OCI IAM and policy data; the desktop
app, CLI, web application, and MCP server are first-party adapters over that
same runtime.

This guide covers the small, supported Python embedding surface for the current
analysis snapshot. It does not define a persistent corpus, plugin SDK, or OCI
authorization decision service.

## The current analysis snapshot

The in-memory repository and its cache/export representation are analysis
snapshots. They are intentionally allowed to contain incomplete, unresolved,
or invalid data. For example, a policy can be retained with validation findings
so a caller can find and correct it rather than silently losing it during load.

An integration must therefore preserve the distinction between:

- a successful load and a complete load;
- no matching policy and an indeterminate result caused by incomplete data;
- a normalized statement and an OCI-authoritative authorization decision.

Treat validation findings, load warnings, collection timestamp, source mode,
and any scope limits as output that belongs beside the requested result.

## Saved snapshot compatibility in 7.0

The combined-cache format is unchanged from 6.5.7: `version: 2`, with current
writers using `schema_version: 3`. The existing `policies` and `policy_statements`
sections remain required. Optional inventory and metadata fields retain their
existing defaults, so older snapshots using the supported structure can load
without a fresh OCI collection. This does not add support for formats that 6.5.7
already rejected.

Regular and cross-tenancy corpora, intelligence overlays, and the permissions
report are rebuilt at runtime; they are not added to the combined-cache payload.
Statement records can contain updated derived fields, including canonical
principal keys and structured association endpoints. Original statement text
remains available. For old cross-tenancy association records without complete endpoint
structure, corpus construction reparses the source text on a detached copy;
it does not rewrite the cache file.

The breaking change is the removal of the former `common` and `logic` Python
import packages, not a requirement to discard saved tenancy data. Callers should
migrate imports and run the appropriate post-load profile after loading. Changes
in validation, permission mappings, and analysis can legitimately change derived
results when the same snapshot is processed by a newer version.

## Python embedding

`AppContext` is the reusable application wiring used by non-desktop consumers.
Construct it from settings, load data through `LoadService`, then use a focused
service for the task. The service boundary is preferable to reaching directly
into UI code.

```python
from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.application.services.mcp_query_service import MCPQueryService
from oci_policy_analysis.application.core.models.models_policy import PolicySearch

context = AppContext.from_settings(config.load_settings())
loaded = LoadService(context).load_from_cache('my-tenancy-cache', post_load_profile='minimal')
if not loaded.success:
    raise RuntimeError(loaded.message)

statements = MCPQueryService(context).filter_policy_statements(PolicySearch(resource=['buckets'], verb=['read']))
```

Use the current context and services rather than presentation modules or
private helpers. The former top-level `oci_policy_analysis.common` and
`oci_policy_analysis.logic` compatibility packages are removed in 7.0; import
models, repositories, and support helpers from `application.core` instead.
The top-level `oci_policy_analysis.web` aliases are also removed; ASGI integrations
should import `oci_policy_analysis.presentation.web.main:app`. The published
`oci-policy-analysis-web` command name is unchanged.
Keep integration tests close to the package version you run;
there is not yet a separately versioned plugin SDK.

### Qt desktop exploration

The optional `presentation.qt` package is a small PySide6 Widgets prototype over
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

The sidebar contains Overview & Settings, Policy browser, Policy graph, Dynamic groups,
MCP & assistant, and Resource principals. Every page except Overview is disabled
until the first successful load; a failed reload retains the previous snapshot
and keeps its pages available.
A prominent **Advanced mode** toggle on Overview persists the Qt experience
preference. Recommendations and Tools stay in Standard mode; Advanced adds
Prospective statements, Simulation, Consolidation and Tools → Maintenance.
Recommendations provides the shared read-only finding dashboard and explicit
full analysis; Consolidation and Maintenance remain planned. Logging in Tools
reuses the existing dock/settings. The other Tools tabs are Condition Tester
and Reports. Mode changes never run operations or reload data.

`experience.py` supplies one shared mode object: pages register advanced widgets
with `bind_advanced` / `bind_advanced_tab` or subscribe to `changed` for alternate
layouts. Navigation visibility is declared in the shell's `page_specs` registry.
A separate data-availability check still disables all non-Overview pages until
loading succeeds. Turning off Advanced on a hidden page returns to Overview.

`selection_table.py` supplies native check-state models and a checked table over
the shared record view/proxy. Inclusion follows stable service IDs through sort
and filter, independently of highlighted rows. Visible-only bulk actions show
hidden-checked counts; missing IDs are uncheckable, duplicate IDs reject a reset,
and source records are unchanged. Downstream services remain responsible for
eligibility and explicit operations. Recommendation display rows without IDs
remain read-only rather than receiving invented action identifiers.

Only the tenancy-loading area and experience toggle are expanded initially. Logging, MCP, Intelligence,
and Look and Feel are independent collapsed sections. Snapshot results appear
only after a successful load. The tenancy controls include profile, instance
principal, and resource principal authentication, policy recursion, user loading,
and identity-domain depth. OCI profile/authentication and Load from OCI share
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

**Show live log** or **View → Logs** opens a dock with Live log and Load activity
tabs. It opens only on explicit request, including when a load fails, and remains
usable across pages and during loading. Hiding it does not stop log capture.
Load failure messages remain visible on Overview and in the status bar. The window detaches
its UI handler and stops its timer on close. Choose all application components
or Qt-only output in the dock; file and shell handlers remain in place.

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
**MCP** uses host/port defaults and copies an explicit standalone server launch
command with the selected authentication and scope. It does not start a server or
share the Qt context. The separate **MCP & assistant** page starts a managed
loopback FastMCP server over the currently loaded context, lists seven query-only
tools, and provides an optional native Codex chat over app-server stdio. Loading
is locked while it serves that snapshot; Stop and window close shut down its
listener and child process. Connecting starts no model turn; questions are sent
only by pressing Send. See [Qt MCP and Codex](qt_mcp_codex.md) for setup, lifecycle,
configuration isolation, and validation limits.

The application/window icon uses the existing packaged PNG. The PNG is included
in the wheel. Packaged native executables additionally need platform metadata:
use the existing `.icns` for macOS and `.ico` for Windows when configuring
`pyside6-deploy`. Source-run OS application identity can still belong to Python;
the runtime icon does not replace native bundle/executable metadata. See
[Qt application icons](https://doc.qt.io/qtforpython-6/overviews/qtdoc-appicon.html).

### Qt module ownership

- `presentation/qt/main.py`: shell, page composition, navigation, and close handling.
- `controller.py`: active context and asynchronous load lifecycle.
- `loading.py`: worker-owned candidate context and `LoadService` calls.
- `pages/overview.py`, `browser.py`, `graph.py`, `dynamic_groups.py`, `mcp.py`, `activity.py`: independent pages.
- `mcp_host.py`, `codex_client.py`: managed loopback listener and native app-server transport.
- `logging_panel.py`: INFO+ log controls, bounded batching, and live log view.
- `settings_panels.py`: MCP, Intelligence, and Look and Feel controls.
- `tables.py`, `details.py`: reusable sortable tables, context menus, and source-record drawer.
- `themes.py`, `preferences.py`: shared palette/styles and saved Qt preferences.
- `logger_catalog.py`: optional-interface-safe discovery of declared and active loggers.
- `icons.py`: packaged runtime application icon.
- `profiles.py`, `widgets.py`, `sample_data.py`: focused helpers and fictional data.

Pages receive the newly published context after every successful load. They do
not retain old engines/corpora across reloads. The shell does not implement data
queries, table filtering, graph projection, or profile discovery.

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

### Current Tkinter comparison

| Capability | Qt exploration |
| --- | --- |
| Profile authentication, policy recursion, identity-domain depth | Available on Overview & Settings |
| Exported snapshot loading | Available; original file is not rewritten |
| Named cache loading | Available; management/history remains outside this page |
| CIS Compliance output | Directory-based loading through the shared core |
| Instance/resource principal | Available; explicit session-token controls remain to be explored |
| Policy filtering | Common core filters available; full identity/tag filter UI remains to be explored |
| Dynamic groups | Live inventory filters, exact multi-selection, related statements, and cross-page focus |
| Resource principals | Broad any-user/any-group evidence, resource type/compartment selectors, exact DG multi-selection, OKE selectors, confidence and right-click details |
| Statement details | Shared animated drawer, full source/parsed/validity fields, raw JSON and copy |
| Policy graph | Direct source grants, exclusions, filters, paging, and native evidence selection |
| Intelligence | Minimal/full loading and strategy/risk settings; dedicated results pages remain to be explored |
| Simulation, consolidation, report UI | Native simulation, Recommendations with explicit full enrichment, and on-demand Reports under Tools; consolidation remains planned |
| Logging | All declared/registered loggers, saved global/component controls, INFO+ live view |
| Appearance | Saved Light/Dark appearance, color palette, text sizes through Extra Large, optional fixed-width tables/Overview, and table density |
| Embedded MCP and assistant | Managed query-only snapshot host; optional native Codex chat; loading locked during serving |

### Qt load lifecycle

A worker creates a fresh `AppContext` and runs the selected minimal or full
post-load profile. Only a successful load replaces the displayed context; failed
loads retain the previous snapshot. Closing while loading is blocked until the
worker finishes; the prototype does not implement cancellation of OCI calls.
During embedded MCP serving, all load sources and controller requests are locked.
Closing with MCP/Codex active first shuts them down, then closes automatically.

This preview saves explicit appearance/settings choices through existing application settings. Opening a
snapshot does not rewrite its source file. Standard core cache-directory creation
and process-wide logging still apply; their isolation is separate future work.
Counts and successful loads do not establish complete inventory or an
OCI-authoritative authorization decision. Full recommendations and permissions
reports are built only when the full profile is selected.

PySide6 is confined to the `qt` extra and presentation package. Existing desktop,
CLI, web, and MCP commands remain unchanged. Native Nuitka builds and their offline Qt/MCP smoke test are documented in
`run/README.md`; they package the same source and core as this preview.

### Extension checklist

1. Create a context and load one input source.
2. Run the post-load profile appropriate to the caller (`minimal` for focused
   programmatic analysis; full profiles when their derived overlays are needed).
3. Query through a service or engine, retaining source statements and findings.
4. Return a task-level result plus data-quality and provenance information.
5. Test against valid, invalid, and partial snapshots.

For scripts and scheduled jobs, use the [CLI guide](cli.md). For agent-facing
queries, use the documented [MCP tools](mcp.md) instead of constructing or
mutating internal repositories. Both return analysis evidence, not an
OCI-authoritative allow/deny decision.


### Explain a run and draft scoped what-if candidates

After loading a context, use the shared workbench service for the same request
evidence shown by Qt. An explicit empty checked-ID list means no statements.
Execution appends runtime history; candidate generation does not save prospects
or change OCI. Serialize these calls with loads and prospective mutation.

```python
from oci_policy_analysis.application.services.simulation_service import SimulationService
from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

selection = SimulationService(context).statement_candidates(
    compartment_path='ROOT/Applications',
    principal_type='group',
    principal=('Default', 'AppDevelopers'),
)
workbench = SimulationWorkbenchService(context)
report = workbench.execute(
    {
        'principal_type': 'group',
        'principal': ('Default', 'AppDevelopers'),
        'principal_key': selection['principal_key'],
        'compartment_path': 'ROOT/Applications',
        'api_operation': 'objectstorage:CreateBucket',
        'checked_statement_ids': [row['internal_id'] for row in selection['statements'] if row['checkable']],
        'where_context': {},
    }
)
drafts = workbench.policy_candidates(
    report,
    principal_key=selection['principal_key'],
    granularity='permission',  # also resource or family
    policy_path='ROOT',
    effective_path='ROOT/Applications',
    where_clause="request.operation = 'CreateBucket'",
)
# Review drafts["candidates"], additional permissions, unmapped permissions
# and scoped corpus examples before explicitly saving through prospects.
original_runs = workbench.history()
related_choices = report['related_scenarios']
```

Use actual inventory paths/principals and catalog operation labels. History and
reports are detached copies with original inputs; runtime snapshot IDs reject
candidate generation after replacing the engine. A related operation requires a
new compartment selection, preparation and explicit run, not reuse of primary
checked IDs. Matching denies, conditions and inventory/reference coverage remain
constraints after any suggested allow. The current reverse mapping uses greedy
catalog coverage rather than proving globally minimal privilege.
