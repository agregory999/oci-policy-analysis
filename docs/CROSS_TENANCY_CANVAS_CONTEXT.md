# Cross-tenancy corpus and desktop Canvas: saved execution context

Saved: 2026-10-12. Branch: `feat/7.0.0-policy-corpus-cross-tenancy`.
Status: plan approved and implemented on the 7.0 worktree on 2026-10-12; release QA remains.

## Implementation update (2026-10-12)

- Added a versioned `CrossTenancyCorpus` with isolated source occurrences, deterministic source IDs, normalized definitions/statements/relationships, findings, diagnostics, and a shared UI projection. The web route and desktop read the same snapshot.
- Corrected tenancy alias resolution for conflicting Defines and the special `any-tenancy` scope. Findings now preserve both source IDs for identical statement occurrences.
- Rebuilt the desktop tab with a scrollable Tk Canvas, three relationship lanes, clickable tenancy/link/entity/orphan nodes, a keyboard relationship selector, statement-text and defined-entity filters, findings table, and an in-tab detail inspector. Refresh view reads the current snapshot.
- Exposed the corpus by section in the JSON Debugger and wired it to full, minimal, and desktop post-load paths. Reset clears the old corpus.
- Verified 56 focused tests, Ruff, web JavaScript syntax, and a macOS Tk widget smoke test. Manual visual review with representative dense live and cached datasets, plus executable builds on supported operating systems, remain before release.
- Existing unrelated 7.0 work was preserved. No commit, pip release, deployment, or executable build was made.

## Resume instruction

When the user returns, read this file and the current git status, then execute the
cross-tenancy corpus, shared projection, JSON Debugger, and Tkinter Canvas plan
below on the existing 7.0 branch. Preserve the many unrelated uncommitted 7.0
changes. Do not assume that any earlier tests, preview servers, or browser tabs
are still running after the reboot. Do not commit, merge, publish, build a pip
release, or deploy unless the user asks.

## Goal and boundaries

Recreate the web Cross-Tenancy Analysis experience in the existing Tkinter
desktop tab using `tk.Canvas`: local tenancy center, admitted tenancies left,
endorsed tenancies right, clickable entity children, Associate links, a single
filtered statement table, and detailed statement/finding inspection. Give the
desktop and web views one shared, explicit cross-tenancy corpus and projection.
Expose the corpus in the desktop JSON Debugger for inspection.

The much larger regular Policy Corpus visual view is a later design task. Keep
Canvas drawing and selection mechanics reusable, but do not generalize the
cross-tenancy semantics into a premature universal graph framework or draw
every regular policy fact in this iteration.

## Current state and evidence

- The web page at `src/oci_policy_analysis/presentation/web/static/cross-tenancy-analysis.html`
  already draws a three-lane graph with tenancy nodes, group/dynamic-group/
  compartment/any-user child nodes, a separate orphan area, clickable filters,
  statement-text search, statement inspector, and finding inspector. It shows
  `any-tenancy` as a special scope without requiring a Define. Its Refresh view
  button re-fetches in-memory analysis; it does not call OCI.
- `CrossTenancyAnalysisService` at
  `src/oci_policy_analysis/application/services/cross_tenancy_analysis_service.py`
  currently builds both interpretation and UI payload directly from
  `repo.defined_aliases` and `repo.cross_tenancy_statements`. It infers ownership
  from parsed fields and `... of tenancy ...` text, builds graph nodes/links,
  and marks associations as deduced. Both UIs use this service, but the desktop
  still adds its own interpretation.
- The desktop `CrossTenancyTab` at
  `src/oci_policy_analysis/presentation/tk/cross_tenancy_tab.py` currently
  has a local tenancy panel, tenancy table, statement table, Findings notebook
  page, JSON popup details, and a Refresh button. It does not draw the graph.
  Its text filter searches serialized rows, unlike the web page's statement-only
  search. It independently rebuilds alias roles and status, including treating
  special `any-tenancy` as unresolved.
- `CrossTenancyFindingsStrategy` at
  `src/oci_policy_analysis/application/core/engine/intelligence_strategies/cross_tenancy_findings.py`
  reports unresolved tenancy aliases, conflicting Define OCIDs, and duplicate
  Admit/Endorse statements. It provides source references for the web finding
  inspector.
- `PolicyIntelligenceEngine.resolve_cross_tenancy_aliases()` currently mutates
  repository statements before findings. Its alias map overwrites duplicate
  names with the last OCID, so corpus construction should take over resolution
  and explicitly preserve ambiguity. Review the effect on `valid` and
  `invalid_reasons` so a conflict cannot be treated as a working policy.
- The regular `PolicyCorpus` at
  `src/oci_policy_analysis/application/core/policy_corpus.py` contains valid-only
  authorization facts and exclusions. Cross-tenancy needs a separate corpus
  because unresolved, ambiguous, special, and partially parsed statements must
  remain visible in the graph and diagnostics.
- `DebuggerTab` at `src/oci_policy_analysis/presentation/tk/debugger_tab.py`
  already has `Policy Corpus` as a source and both Text and lazy Tree modes.
  Its `_get_source_data()` calls `corpus.to_dict()` repeatedly, including on
  tree expansion; keep large data conversion costs in mind.
- The app context has `corpus: PolicyCorpus | None`; full/minimal post-load
  paths are in `application/post_load.py`, and the desktop also has a main.py
  intelligence/corpus path. Both must populate the CT corpus after loads and
  refreshes, with no stale data after switching datasets.
- `src/test/test_cross_tenancy_graph.py` covers graph direction, definitions,
  child nodes, ambiguous aliases, and `any-tenancy`. Focused CT/parser tests and
  Ruff passed on 2026-10-09. A broader policy-intelligence run then had six
  unrelated pre-existing failures from `PolicyCorpusBuilder.build()` using an
  unbound `index` at `policy_corpus.py:125`; verify current status before work.

## Architectural decisions

1. Keep the regular authorization corpus and new cross-tenancy corpus separate.
   Store immutable CT source facts and diagnostics; project graphs from those
   facts. Do not store web-specific labels or Tk coordinates as corpus facts.
2. The corpus is the single source for alias resolution, entity ownership,
   special scopes, association endpoints, findings, and source provenance.
   The web route and desktop tab consume one versioned projection, not separate
   sets of regex and role rules.
3. Preserve every source statement, including invalid and partially parsed
   statements. Record uncertainty instead of making unsupported tenancy claims.
   A link represents what a loaded policy states; it never proves a reciprocal
   policy exists in another tenancy.
4. Use stable per-occurrence source IDs. The current hash of policy OCID plus
   normalized text conflates identical statements in the same policy. Prefer a
   persisted parser/internal ID when unique, with deterministic source position
   fallback. Duplicate findings must retain both occurrences.
5. Build the desktop graph with `tk.Canvas` primitives and tag-based clicks.
   Reuse the shared graph projection. Keep a keyboard-accessible relationship
   list or equivalent controls alongside the Canvas.
6. Keep the visual Policy Corpus as a follow-on design. Its fact cardinality
   likely requires aggregation and drill-down, not one node per fact.

## Target CT corpus and projection

Introduce a versioned `CrossTenancyCorpus` in `application/core/` with
`to_dict()` and a compact `summary()`. A first schema should include:

- `definitions`: kind, alias, OCID, provenance/source ID, duplicate/conflict
  status, references, and inferred owner with evidence.
- `statements`: Admit/Endorse/Unknown, principal, action/resource, scopes,
  conditions, source text, parse/validity status, and provenance. Keep raw
  normalized fields available for detail inspection.
- `relationships` or per-statement edges: participant alias/OCID/special
  scope, direction, Associate endpoint roles, and source statement IDs.
- `diagnostics/findings`: unresolved or ambiguous definitions, duplicates,
  unplaced linked entities, parser uncertainty, and related source IDs.

Use explicit states such as `resolved`, `unresolved`, `ambiguous`, and `special`
for tenancy references. `any-tenancy` is `special` and needs no Define; `any-user`
is a special principal. For inferred ownership, record whether it came from an
explicit `of tenancy` clause, a parsed principal/scope, or remains unknown.
Association endpoint roles must retain uncertainty if the parser cannot prove
the relationship.

Project this corpus to one UI-neutral payload with local tenancy, graph nodes,
links, child entities, orphans/unplaced entities, statement rows, findings,
counts, and source ID sets used for selection. Give every node and link a stable
ID. Keep compatibility keys for the current web route during migration, then
remove them only after both UIs and tests use the new contract.

## Execution sequence

### 1. Lock the behavior with fixtures

Create focused parser/corpus fixtures for ordinary Admit and Endorse, Associate
with multiple endpoints, groups and dynamic groups, `any-user`, `any-tenancy`,
remote compartments, local principals, orphan and unplaced definitions,
unresolved aliases, same alias with conflicting OCIDs, identical statements in
one policy, unparsed statements, and cached/live reloads. Assert exact source
IDs and graph selection sets. Compare current web behavior before migration.

### 2. Build and wire the CT corpus

Add immutable model and builder. Move alias resolution and ownership deduction
out of display construction; adapt the intelligence findings strategy to read
the corpus, while retaining any repository fields required by existing
consumers. Build/update the corpus in full and minimal post-load flows and the
desktop main.py flow. Decide the single context slot (for example,
`AppContext.cross_tenancy_corpus`) and invalidate/rebuild it when a new dataset
or policy-only reload completes. Include schema version and provenance.

### 3. Create the shared projection and migrate web

Make `CrossTenancyAnalysisService` a projection adapter over the CT corpus.
Keep `GET /analysis/cross-tenancy` stable. The web page should only render,
filter by supplied source IDs, and show details; it should not infer owner or
resolution rules. Verify existing graph, child node, orphan, search, finding
panel, and Refresh view behavior in the browser.

### 4. Expose CT corpus in JSON Debugger

Add `Cross-Tenancy Corpus` to the source selector. Use the current Text/Tree
views, with a section selector (summary, definitions, statements,
relationships, findings) or lazy section conversion so large JSON need not be
materialized on every key expansion. Show a clear note before any dataset is
loaded. Confirm the debugger updates after live and cached loads.

### 5. Rebuild the desktop tab with Canvas

Replace the redundant tenancy table with a scrollable graph area above the
statement explorer. Draw incoming nodes left, the local tenancy center, and
outgoing nodes right; show group/dynamic-group/compartment/any-user children,
special `any-tenancy`, dashed Associate edges, and unplaced/orphan groups.
Redraw on resize with bounded/debounced work. Add mouse hover/selection and
keyboard navigation or a parallel accessible relationship list. Use stable
node/link IDs to filter the single statement table. Match web search semantics:
statement text only, plus a separate defined-entity selector and clear action.
Show Define tenancy associations as deduced or `<not associated>`. Provide an
in-tab right-side inspector for full statement and finding/source details,
instead of requiring the current JSON popup; retain a raw JSON option for
debugging if useful. Rename desktop Refresh to `Refresh view` unless it truly
reloads OCI; it currently only reads in-memory data.

### 6. Verify parity, packaging, and docs

Run focused pytest and Ruff for changed Python, contract tests comparing web
and desktop selection/filter results from the same projection, and manual
desktop checks on representative small and dense datasets. Check Canvas
scrolling/resizing, selection, keyboard access, duplicate statements, and
special/ambiguous states. Build/test desktop executables on supported OSes
before release, since executables are the main product. Update usage docs that
currently describe the older desktop tab and outdated web text-search scope.
Do not build or publish a pip release merely to test the local code.

## Acceptance criteria

- Both UIs display the same CT nodes, links, source counts, findings, and
  statement rows from the same loaded snapshot.
- Clicking a tenancy, direction, child entity, unplaced entity, or orphan
  definition selects exactly the associated source statements; identical text
  occurrences remain separately inspectable.
- `any-tenancy` works on either side without a Define or false unresolved
  finding. Ambiguous OCIDs remain unresolved and produce an Error finding.
- Ownership is shown as deduced only when evidence exists; otherwise it is
  visibly unassociated/unplaced. Associate links do not assert an unverified
  reciprocal policy.
- Desktop findings open related source statements and parsed detail in the
  in-tab inspector. JSON Debugger exposes the CT corpus after load/reload.
- Cached/offline datasets work without OCI calls. Refresh view only reads the
  current in-memory snapshot; live OCI reload remains a separate gated flow.

## Later visual Policy Corpus design

After CT parity is verified, measure regular corpus size and candidate node/
edge counts on real snapshots. Explore an aggregated, progressive view such as
compartment -> principal -> resource/permission, with counts, search, and
drill-down to individual facts/provenance. Reuse Canvas drawing/selection
mechanics only where they fit. Set an explicit node budget or virtualization
strategy before implementation. Keep this as a separate design and test cycle.

## Repo and workflow cautions

- The branch has extensive pre-existing uncommitted 7.0 work across corpus,
  parser, MCP, web, desktop, scripts, docs, and build files. Preserve it; no
  commit or deploy was requested. Use `git status` before touching files.
- Follow `AGENTS.md`: package code under `src/oci_policy_analysis`; use
  `uv sync --extra web --extra mcp`, focused pytest, and Ruff. Container images
  come from local source. Do not commit `run/.env`, OCI credentials, generated
  deployment JSON, or build artifacts. LB and NSG are managed elsewhere.
- Earlier web preview checks used a temporary server under `/private/tmp`;
  it was stopped. Recreate fixtures rather than relying on that process.
