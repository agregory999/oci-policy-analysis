##########################################################################
# CONTEXT_prospective_statement_editor.md
#
# Project-Specific Context: Prospective (What‑If) Statement Editor
##########################################################################

## Purpose and Positioning

The **Prospective Statement Editor** is a dedicated, tenancy‑scoped UI for
managing **prospective (what‑if) policy statements**. These are hypothetical
OCI IAM policy statements that do **not** exist in the live tenancy but are
evaluated as if they did for simulation and analysis.

The editor lives in a standalone `tk.Toplevel` window implemented in
`ui/prospective_editor_window.py` and is opened from multiple places:

- **Policies Tab** – via the **Prospective Editor…** button in the
  *Display Options* header.
- **Simulation Tab** – via the **Manage Prospective Statements…** button
  in the *Simulation Environment* subtab’s prospective preview.
- (Future) Other builders such as **Tag-based Access** may link directly
  to it when creating what‑if statements.

Key goals:

- Provide a single, tenancy‑aware CRUD surface for all prospective
  statements (shared across tabs and MCP tools).
- Delegate validation, normalization, and engine integration to the
  central `ProspectiveStatementsService` and `PolicySimulationEngine`.
- Keep the Simulation and Policies tabs **read‑only** with respect to
  prospective data; they consume the shared service rather than owning
  separate copies.


## High‑Level Architecture

Prospective statements flow through three main components:

- **ProspectiveStatementsService** (`logic/prospective_statements_service.py`)
  - Tenancy‑scoped manager created once per active tenancy and exposed as
    `app.prospective_service`.
  - Owns the in‑memory list of `ProspectiveStatementRecord` objects.
  - Loads and persists data under the shared settings key
    `simulation_prospective_statements_by_tenancy` (see
    `CONTEXT_simulation_engine.md`, section 10).
  - Delegates validation and normalization of statement text to
    `PolicySimulationEngine.validate_prospective_statement` and pushes the
    current list into the engine via `set_prospective_statements`.

- **ProspectiveEditorWindow** (`ui/prospective_editor_window.py`)
  - A modal top‑level window bound to the active `App` instance.
  - Reads and writes prospective statements exclusively through
    `app.prospective_service`.
  - Provides a CRUD grid and a full‑featured builder to synthesize new
    statements (including tag‑based where‑clause support).

- **PolicySimulationEngine** (`logic/simulation_engine.py`)
  - Maintains the normalized, engine‑internal prospective list and merges
    it with real tenancy statements when computing applicable statements.
  - Provides `validate_prospective_statement` and
    `set_prospective_statements` used by the service.

### Data Flow Overview

```mermaid
flowchart LR
  Settings[(settings.json
  simulation_prospective_*
  by_tenancy)]
  Svc[ProspectiveStatementsService]
  UI[ProspectiveEditorWindow
  + other tabs]
  Eng[PolicySimulationEngine]

  Settings --> Svc
  UI <--> Svc
  Svc <--> Eng
  Eng --> SimTab[Simulation Tab]
  Eng --> PoliciesTab[Policies Tab
  (prospective view)]
```

- On service construction, the current tenancy’s list is loaded from
  settings and converted into `ProspectiveStatementRecord` instances.
- The editor and any builders call service CRUD helpers to modify the
  in‑memory records.
- On **Save**, the service serializes the records back to a simple list,
  writes it under `simulation_prospective_statements_by_tenancy` for the
  active tenancy, saves settings, and calls
  `PolicySimulationEngine.set_prospective_statements(simple_list)`.
- The engine normalizes the input, assigns engine‑internal `internal_id`
  values, and later exposes merged real+prospective statements to the
  Simulation and Policies tabs.


## ProspectiveStatementsService (`logic/prospective_statements_service.py`)

The service is the canonical, tenancy‑scoped API for what‑if statements.

### Data Model: `ProspectiveStatementRecord`

```python
@dataclass
class ProspectiveStatementRecord:
    id: str                 # UUID (stable across edits)
    tenancy_ocid: str
    compartment_path: str   # e.g. "ROOT/Finance"
    description: str        # human‑friendly label
    statement_text: str     # full OCI IAM statement
    parsed: bool = False
    valid: bool = False
    invalid_reasons: list[str] = field(default_factory=list)
    normalized: dict[str, Any] | None = None
```

- Records are always attached to a single tenancy via `tenancy_ocid`.
- `parsed` / `valid` / `invalid_reasons` / `normalized` are populated by
  `validate_and_update_text` using the simulation engine; they are
  preserved across saves so the editor can show parse state without
  re‑validating every time.

### Service Responsibilities

- **Construction**
  - `ProspectiveStatementsService(settings, simulation_engine, tenancy_ocid)`
  - Validates that `tenancy_ocid` is non‑empty, initializes an empty
    `_records` mapping, and calls `_load_from_settings()`.

- **Query Helpers**
  - `list_all()` – return all records.
  - `list_valid()` – return only `parsed and valid` records.
  - `get(record_id)` – fetch a single record or `None`.

- **CRUD**
  - `create(compartment_path, description, statement_text)` – create a new
    record with a fresh UUID; does **not** auto‑validate or persist.
  - `upsert(record)` – insert or replace a record after external mutation
    (requires `record.tenancy_ocid` to match the service tenancy).
  - `delete(record_id)` – remove a record if present.
  - `replace_all_from_simple_list(entries)` – convenience helper to
    rebuild `_records` from a list of simple dicts such as:

    ```python
    {
        "compartment_path": "ROOT/Finance",
        "description": "Finance what‑if",
        "statement_text": "Allow ...",
    }
    ```

    Used by the editor’s **Save and Close** handler.

- **Validation**
  - `validate_and_update_text(record_id, new_text)`
    - Updates `statement_text` on the record.
    - If text is empty, marks the record as not parsed/invalid and clears
      diagnostics.
    - If the simulation engine or its `validate_prospective_statement`
      helper is missing, marks the record as unvalidated and sets a
      friendly message in `invalid_reasons`.
    - Otherwise calls `engine.validate_prospective_statement(text)` and
      mirrors `parsed`, `valid`, `invalid_reasons`, and `normalized` into
      the record.

- **Persistence and Engine Integration**
  - `persist_and_push_to_engine()`
    - Builds a **simple list** of dicts for all non‑empty statements:

      ```python
      {
          "compartment_path": rec.compartment_path,
          "description": rec.description,
          "statement_text": rec.statement_text,
          "parsed": rec.parsed,
          "valid": rec.valid,
          "invalid_reasons": [...],
          "normalized": {...},
      }
      ```

    - Calls `engine.set_prospective_statements(simple_list)` when
      available. The engine owns internal IDs and merged evaluation.
    - Writes the same list under
      `simulation_prospective_statements_by_tenancy[tenancy_ocid]` and
      calls `config.save_settings(settings)`.

### Settings Key

- All persisted prospective data uses the constant
  `SETTINGS_KEY_PROSPECTIVE_BY_TENANCY = "simulation_prospective_statements_by_tenancy"`.
- See `CONTEXT_simulation_engine.md` (Prospective section) for the legacy
  description of this structure; the service now centralizes its use.


## ProspectiveEditorWindow (`ui/prospective_editor_window.py`)

The `ProspectiveEditorWindow` class provides the UI for managing the
tenancy‑scoped records owned by the service.

### Window Lifecycle and Preconditions

- Constructed on demand via:
  - `ProspectiveEditorWindow(self, self.app)` (Policies tab, Simulation
    tab, or other tabs).
- On `__init__`:
  - Configures basic window chrome (title, transient, grab) and matches
    the main app’s background.
  - Resolves `self.service` from `app.prospective_service`.
  - If the service is missing, shows a warning message and closes; the
    editor is not usable without a tenancy‑scoped service instance.
  - Builds four main sections:
    1. Intro text (scope explanation).
    2. CRUD editor grid.
    3. Statement builder (including tag‑based where‑clause helpers).
    4. Bottom **Save and Close** button row.


### CRUD Grid

The top **Prospective Policy Statements (CRUD)** label frame presents a
compact grid where each row corresponds to a `ProspectiveStatementRecord`:

- Columns:
  - **Location (Compartment)** – `compartment_path` combobox seeded from
    Simulation tab’s `_sim_index_compartments` (defaults to `ROOT`).
  - **Description** – free‑text label for the statement.
  - **Statement Text** – a small scrollable `tk.Text` widget (approx. two
    lines high) holding the full OCI IAM policy statement.
  - **Status** – simple text indicator (`Not parsed`, `Parsed`,
    `Invalid`, `Error`, etc.).
  - **Actions** – per‑row **Parse** and **Delete** buttons.

Behavior:

- **Row Models**
  - Each row stores its widgets and associated `StringVar`s in a dict in
    `self._row_models`.
  - `text_var` is kept in sync with the `tk.Text` widget via `FocusOut`
    and `KeyRelease` bindings.

- **Parse Button**
  - If the row has a `record_id` and the service is available, calls
    `service.validate_and_update_text(record_id, stmt_text)` and updates
    `Status` and an inline orange **parse notes** label beneath the row.
  - If no service/record ID is available, falls back to
    `simulation_engine.validate_prospective_statement` and surfaces its
    diagnostics.
  - For invalid or unparseable statements, also shows a
    `messagebox.showwarning` with the combined reasons.

- **Delete Button**
  - If `record_id` is present, calls `service.delete(record_id)`.
  - Destroys the row’s frame and notes label and removes its row model
    from `self._row_models`.

- **Initial Rows**
  - On startup, the editor calls `service.list_all()` and seeds a row per
    record (preserving `id` so validation state can be reused).
  - If there are no existing records, it creates a single empty row.
  - A bottom **Add Free‑Form Statement** button appends a new blank row
    using the same helper.


### Statement Builder Section

The **Prospective Statement Builder** label frame provides a higher‑level
builder that can synthesize a full OCI statement and drop it into the CRUD
grid.

#### Builder Inputs

- **Effect / Action** – `Allow` or `Deny`.
- **Principal** – combobox of normalized principal keys derived from
  `policy_repo.regular_statements` (users, groups, dynamic groups,
  services, and id‑based principals). Principal formatting is shared with
  `TagBasedAccessTab` and uses `builder_helpers.build_subject_phrase`.
- **Include Default** – toggle controlling whether the literal `Default`
  identity domain appears in generated group/dynamic‑group phrases.
- **Verb** – `inspect | read | use | manage`.
- **Resource** – either in‑use resources from `policy_repo` or, when
  **All Possible Resources** is checked, the union of resources and
  families from `reference_repo.data`.
- **Location / Compartment** – base compartment path (typically from
  Simulation tab’s indexed compartments).
- **Effective Path** – effective scope used to build the location
  clause; must be equal to or a descendant of `Location`. If the user
  selects an effective path outside the chosen location, the builder
  resets it to match the location and warns once via a messagebox.
- **Where Clause Mode** – one of:
  - `No Where Clause`
  - `Tag-based Where Clause`
  - `Other Where Clause` (free‑form text area)

#### Tag‑Based Where Helper

When **Tag-based Where Clause** is selected, the right‑hand panel surfaces
inputs for:

- `Access Type` – e.g. `request.principal.group`, `target.resource`.
- `Tag Namespace` and **Tag Key**.
- `Operator` – `=`, `!=`, `IN`, `NOT IN`.
- `Value(s)` – scalar value or comma‑separated list.

The builder reuses `builder_helpers.build_tag_variable_and_snippet` to
compute:

- **Generated variable** – e.g.
  `request.principal.group.tag.Operations.Project`.
- **Condition snippet** – small `all { ... }` expression that becomes the
  body of the `where` clause.

When **Other Where Clause** is selected, a free‑form `tk.Text` editor
captures arbitrary where expressions (without the `where` keyword); the
builder simply splices the raw text into the final statement.

#### Generated Statement and Add‑Row Action

- The builder continuously updates `builder_statement_preview_var` with
  the full OCI statement text by calling `builder_helpers.build_full_statement`:

  ```text
  Allow <subject_phrase> to <verb> <resource> <location_clause> where <snippet>
  ```

  or, if there is no where‑clause snippet:

  ```text
  Allow <subject_phrase> to <verb> <resource> <location_clause>
  ```

- **Add to Statements** button:
  - Validates that a non‑empty statement has been generated.
  - Derives a description using effect, subject phrase, resource, and
    where‑mode (e.g. *"Allow group 'Developers' / buckets with tag‑based
    where clause (tag Operations.Project)"*).
  - Invokes the same `add_row` helper used by the CRUD section to append
    a new row populated with:
    - `compartment_path` – chosen effective path or location.
    - `description` – synthesized label.
    - `statement_text` – generated statement.
  - Immediately calls the row’s `on_parse` callback so the new statement
    is validated via the service/engine.


### Save and Cross‑Tab Refresh

The bottom **Save and Close** button runs `on_save_and_close`:

1. Gathers all non‑empty rows from `self._row_models` into a simple list
   of dicts, preserving existing `id` fields when present so prior parse
   state is not lost.
2. Calls `service.replace_all_from_simple_list(simple_list)`.
3. Calls `service.persist_and_push_to_engine()` to:
   - Push the list into the simulation engine.
   - Persist to `settings.json` for the active tenancy.
4. Best‑effort refresh of dependent tabs:
   - **PoliciesTab** – calls `policies_tab.populate_data()` so the
     **Show Prospective** view reflects the new set.
   - **SimulationTab** – calls `simulation_tab.populate_data()` so the
     *Simulation Environment* preview and applicable‑statement lists see
     the updated prospective set.
5. Closes the window.

Any errors from persistence are surfaced via `messagebox.showerror`, but
downstream tab refresh failures are only logged; they never block closing
the editor.


## Relationships to Other Tabs and Builders

### Policies Tab

- The Policies tab’s **Show Prospective** checkbox causes it to read the
  current prospective list from `ProspectiveStatementsService` (or, as a
  fallback, directly from `PolicySimulationEngine`).
- It reshapes each prospective record into a `RegularPolicyStatement`‑like
  dict and applies **the same JSON filter** used for real tenancy
  policies.
- Prospective rows are clearly marked by prefixing `"[Prospective]"` in
  the **Policy Name** column and are counted separately in the summary
  label when visible.
- The **Prospective Editor…** button in the Display Options header opens
  `ProspectiveEditorWindow` for the active tenancy.

See `CONTEXT_policies_tab.md` for full details.

### Simulation Tab

- On tenancy load, `SimulationTab.populate_data()` calls
  `prospective_service.persist_and_push_to_engine()` so the engine is
  always hydrated from the current settings/service state.
- The **Simulation Environment** subtab shows a read‑only preview of
  prospective statements for the tenancy (compartment, description, and
  statement text) and includes a **Manage Prospective Statements…**
  button that opens `ProspectiveEditorWindow`.
- `SimulationTab.load_statements()` asks
  `PolicySimulationEngine.get_statements_for_context(...)` for the
  **merged** list of applicable real and prospective statements for the
  selected environment. Prospective entries are distinguished only by an
  `[Prospective]` prefix in the **Policy Path/Name** column and an
  `is_prospective` marker in the underlying dict.

See `CONTEXT_simulation_engine.md` for canonical engine behavior.

### Tag-based Access Tab

- The Tag‑based Access builder can generate full OCI statements with
  tag‑based where clauses. The existing design describes an
  **Add to Simulation Prospects** action that should bridge into the
  prospective set.
- In the current implementation, `SimulationTab.add_prospective_statement_from_builder`
  accepts a generated statement and delegates to the same tenancy‑scoped
  `ProspectiveStatementsService` (when available) or directly to the
  simulation engine as a fallback. After adding, it refreshes the
  inline prospective preview and marks the environment as changed.

This keeps both Tag‑based Access and Simulation aligned on a single,
shared source of truth for prospective what‑if statements.


## References

- Prospective service and model:
  - `src/oci_policy_analysis/logic/prospective_statements_service.py`
- Prospective editor window (this UI):
  - `src/oci_policy_analysis/presentation/desktop/prospective_editor_window.py`
- Simulation engine and prospective behavior:
  - [`CONTEXT_simulation_engine.md`](CONTEXT_simulation_engine.md)
  - `src/oci_policy_analysis/logic/simulation_engine.py`
- Policies tab (prospective view and editor entry point):
  - [`CONTEXT_policies_tab.md`](CONTEXT_policies_tab.md)
  - `src/oci_policy_analysis/presentation/desktop/policies_tab.py`
- Tag‑based Access tab (builder integration):
  - [`CONTEXT_tag_based_access_tab.md`](CONTEXT_tag_based_access_tab.md)
  - `src/oci_policy_analysis/presentation/desktop/tag_based_access_tab.py`
