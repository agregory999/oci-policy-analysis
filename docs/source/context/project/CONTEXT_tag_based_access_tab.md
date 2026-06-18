##########################################################################
# CONTEXT_tag_based_access_tab.md
#
# Project-Specific Context: Tag-based Access Tab (Design & Architecture)
##########################################################################

## Purpose and Positioning

The **Tag-based Access** tab is an advanced UI surface focused on
understanding and exploring **tag-based OCI IAM policies**, with a strong
emphasis on the anatomy of tag conditions and how they affect access. As of
2026-04, the tab is intentionally **read-only**: authoring and editing of
statements happens elsewhere (e.g. Policies tab, Prospective Editor), while
this tab remains the place to discover, inspect, and filter tag-based
conditions.

Its goals are to:

- Discover and summarize all **tag-based policy statements** in the loaded
  tenancy (where conditions reference `.tag.`).
  - Surface each tag condition as a structured model, plus a compact
    **structure string** that shows how individual conditions are grouped
    with `ALL` / `ANY` blocks (e.g. `ANY { c1, ALL { c2, c3 } }`).
  - Break down each tag condition into:
    - Access type (e.g. `target.resource`, `request.principal.group`).
    - Tag namespace and key (e.g. `Operations.Project`).
    - Operator (`=`, `!=`, `IN`, `NOT IN`, etc.) and value(s).
- Provide quick access to supporting tooling (Condition Tester, Prospective
  Editor) so users can pivot from analysis to testing/authoring when needed.
- Reuse the existing **Condition Tester** and **Simulation Engine** so users
  can test tag-based conditions and what-if policies without duplicating
  business logic.

The tab is intended as an advanced/educational surface: it helps users
understand and safely adopt tag-based access control, rather than modifying
policies directly.


## Background and Existing Building Blocks

Several existing components already support generic condition parsing and
evaluation:

- **Condition Parser & Evaluator**
  - Grammar and ANTLR artifacts in
    `logic/parsers/condition_parser/` (e.g. `OciIamPolicyCondition.g4`).
  - Evaluation logic in `WhereClauseEvaluator.py` and
    `condition_parser.py`.
  - The Condition Tester tab (`ui/condition_tester_tab.py`) uses these to
    pretty-print and evaluate arbitrary `where` clauses with simulated
    variables.

- **Policies Tab**
  - Displays parsed policy statements and raw `Conditions` text.
  - As of 2026-03, includes a **Tag-based** helper checkbox that simply
    injects `.tag.` into the Condition filter to quickly focus on
    tag-based statements.

- **Simulation Engine**
  - See `CONTEXT_simulation_engine.md` for the canonical simulation flow.
  - Already evaluates conditions and supports prospective (what-if)
    statements; it will naturally respect any tag-based conditions as long
    as they are valid according to the condition grammar.

The Tag-based Access tab will sit on top of these foundations, adding a
structured view and builder for tag-specific conditions, without changing
the core parsing/evaluation rules.


## TagCondition Model and Structure String (Current Design)

For each tag-based comparison inside a `where` clause, we surface two
related artifacts:

1. A normalized **TagCondition** record that describes a single tagged
   comparison.
2. A compact **structure string** that shows how those conditions are
   grouped logically using `ALL`/`ANY`, referencing each TagCondition by a
   stable identifier (e.g. `c1`, `c2`, `c3`).

The parser-side model is implemented in
`logic/parsers/condition_parser/TagConditionCollector.py` as:

```python
@dataclass(slots=True)
class TagCondition:
    """Normalized view of a single tag-based condition element."""

    condition_id: str          # e.g. 'c1', 'c2', unique per clause
    access_type: str           # e.g. 'request.principal.group'
    tag_namespace: str         # e.g. 'Operations'
    tag_key: str               # e.g. 'Project'
    operator: str              # '=', '!=', 'in', 'not in', ...
    value: str                 # scalar or comma-separated list
    subexpression: str         # raw single-condition text from the AST
```

Notes:

- **Access Type** captures *which side* of the condition we are talking
  about:
  - `request.principal.group.tag.Operations.Project` →
    `request.principal.group`.
  - `request.principal.compartment.tag.Operations.Project` →
    `request.principal.compartment`.
  - `target.resource.tag.Operations.Project` → `target.resource`.
  - `target.resource.compartment.tag.Operations.Project` →
    `target.resource.compartment`.
- The `.tag.` segment itself is not part of the model; it is implicit once
  we know this is a tag-based condition.
- Everything after `.tag.` is split into `tag_namespace` and `tag_key`. For
  example, `target.resource.tag.Operations.Project` is parsed as:
  - Namespace: `Operations`
  - Tag Key: `Project`

In more complex conditions (e.g. with `AND`/`OR` or nested groupings), we may
end up with multiple TagCondition records for a single statement. The
**structure string** captures how they are grouped. Examples:

- A single tag condition:

  ```text
  request.principal.group.tag.Operations.Project = 'X'
  ```

  might yield:

  ```text
  structure: c1
  conditions: [TagCondition(condition_id='c1', ...)]
  ```

- A simple `ALL` block with two tag conditions:

  ```text
  all { request.principal.group.tag.Operations.Project = 'X',
        target.resource.tag.Operations.Env IN ('dev','test') }
  ```

  yields something like:

  ```text
  structure: ALL { c1, c2 }
  conditions: [TagCondition('c1', ...), TagCondition('c2', ...)]
  ```

- A nested `ANY`/`ALL` expression:

  ```text
  any { request.principal.group.tag.Operations.Project = 'X',
        all { target.resource.tag.Operations.Env IN ('dev','test'),
              target.resource.tag.Operations.Region != 'us-phoenix-1' } }
  ```

  becomes:

  ```text
  structure: ANY { c1, ALL { c2, c3 } }
  conditions: [TagCondition('c1', ...),
               TagCondition('c2', ...),
               TagCondition('c3', ...)]
  ```

The **Tag-based Access** tab’s top table shows the structure string (e.g.
`ANY { c1, ALL { c2, c3 } }`) for each statement, and the bottom table shows
the corresponding TagCondition rows for the selected statement.


## TagConditionCollector Visitor (Parser-Side Design)

To extract TagCondition records from arbitrary where clauses and build the
structure string, we added a dedicated helper module:

- **Module:** `logic/parsers/condition_parser/TagConditionCollector.py`
- Responsibilities:
  - Imports `OciIamPolicyConditionLexer`, `OciIamPolicyConditionParser`, and
    `OciIamPolicyConditionVisitor`.
  - Defines the `TagCondition` dataclass (parser/analysis-focused; the UI
    maps this into row dictionaries).
  - Implements an internal `_TagConditionVisitor` that:
    - Walks the parse tree for a `condition_clause`.
    - Identifies comparison expressions where the left-hand side variable
      matches one of the supported access-type prefixes and contains
      `.tag.`.
    - Parses the left-hand side variable name into `access_type`,
      `tag_namespace`, and `tag_key`.
    - Extracts operator and right-hand side literal(s) from the
      comparison.
    - Allocates a stable `condition_id` such as `c1`, `c2`, ... and
      appends a `TagCondition` instance to an internal list.
    - Builds a **structure string** by recursively visiting
      `condition_expression` nodes, returning either `cN` for tagged
      single conditions or raw text for non-tag conditions, and wrapping
      nested lists in `ALL { ... }` / `ANY { ... }`.

The public helper used by the UI is:

```python
def collect_tag_conditions(condition_str: str) -> tuple[str, list[TagCondition]]:
    """Parse a where-clause string and return (structure, TagConditions).

    - Returns ("", []) if the string is empty.
    - On syntax or runtime errors, logs a warning and returns a fallback
      structure like "(unparsed: <trimmed text>)" with an empty
      conditions list.
    """
```

`TagBasedAccessTab.populate_data` calls this helper for each statement whose
`conditions` text contains `.tag.` and then:

- Uses the **structure string** for the top table’s
  `Parsed Condition Structure` column.
- Stores the list of TagCondition objects in an internal mapping so the
  bottom table can show `c1`, `c2`, etc. when the user selects a row.


## Tag-based Access Tab: UI Layout

The tab is implemented as `TagBasedAccessTab(BaseUITab)` under
`src/oci_policy_analysis/presentation/desktop/tag_based_access_tab.py` and added to the
application's notebook as an **advanced** tab (toggled via Settings).

### Page-Level Behavior

- Inherits from `BaseUITab`:
  - Uses the page help area at the top to describe tag-based access
    concepts and how to use the tab.
  - Provides a permanent documentation link to this context file.
- Default page help text explains that:
  - The top half of the tab focuses on **finding and filtering** tag-based
    statements.
  - The bottom half focuses on **constructing and testing** new
    tag-based conditions (where-clauses and full statements).


### Top Half: Discovery & Structure View

**LabelFrame:** `Tag-based Policies Overview`

This section surfaces two coordinated `DataTable` instances plus a filter
row and context-sensitive right-click actions.

#### Filter Row

The filter row sits above both tables and applies to the in-memory tag
condition model (no re-parsing required):

- **Tag Namespace** (`self.tag_namespace_var`):
  - Free-text filter; case-insensitive substring match on
    `TagCondition.tag_namespace`.
- **Tag Key** (`self.tag_key_var`):
  - Free-text filter; case-insensitive substring match on
    `TagCondition.tag_key`.
- **Access Type** (`self.access_type_var`):
  - `ttk.Combobox` with values:
    - `Any`
    - `request.principal.group`
    - `request.principal.compartment`
    - `target.resource`
    - `target.resource.compartment`
  - When set to anything other than `Any`, filters TagConditions by
    exact match against `cond.access_type`.
- **Show parsed statement** checkbox:
  - Toggles additional parsed columns (`Subject Type`, `Subject`, `Verb`,
    `Resource`) in the statement overview table by updating
    `statement_table.display_columns`.
- **Show Prospective** checkbox:
  - When enabled, `populate_data` merges in prospective (what-if)
    statements provided by `ProspectiveStatementsService`/simulation engine
    so that the overview includes statements authored via the Prospective
    editor. Prospective rows are prefixed with `[Prospective]` and can be
    filtered/searched just like real tenancy statements.
- **Prospective Editor…** button:
  - Opens the Prospective Editor window, allowing users to create or edit
    prospective statements. Upon save, the editor refreshes the Tag-based
    tab, Policies tab, and Simulation tab so changes are immediately visible.
- **Refresh from Loaded Policies** button:
  - Re-runs `TagBasedAccessTab.populate_data()` to rebuild the in-memory view
    from the latest repository snapshot (safe after tenancy reloads or cache
    imports).

All filter variables react via `trace_add('write', ...)` to refresh the
in-memory structures without re-reading the repository.

#### Statement-level table (upper)

- Backed by `self.statement_table: DataTable`.
- Columns (`STATEMENT_COLUMNS`):
  - `Policy Name`
  - `Effective Path`
  - `Statement Text`
  - `Raw Condition`
  - `Parsed Condition Structure`
  - `Subject Type`
  - `Subject`
  - `Verb`
  - `Resource`
- Default visible columns (can be expanded via the checkbox):
  - `Policy Name`, `Effective Path`, `Statement Text`,
    `Raw Condition`, `Parsed Condition Structure`.
- Each row corresponds to a single policy statement whose `conditions`
  string contains `.tag.`. The tab associates a synthetic `_Statement ID`
  (e.g. `s1`, `s2`, ...) with each row and stores a mapping:

  ```python
  self._statement_to_conditions: dict[str, list[TagCondition]]
  ```

  so that TagCondition lists can be retrieved by selection.
- `Parsed Condition Structure` is set to the structure string returned by
  `collect_tag_conditions`, or falls back to the raw condition text if
  parsing fails or returns an empty structure.

**Selection behavior**

`DataTable`'s `selection_callback` for this table is `_on_select_statement`.
When a row is selected:

- The tab extracts the `_Statement ID` from the selected row.
- Looks up the list of `TagCondition` instances for that statement.
- Projects each TagCondition into a flat dict using `_project_condition_row`.
- Populates `_condition_rows` and refreshes the lower table via
  `_update_condition_table`.

**Right-click behavior – “Show in condition tester”**

The upper table exposes a context-menu action that sends the full
where-clause for the clicked statement to the **Condition Tester** tab.
This uses `DataTable`’s built-in `row_context_menu_callback` hook:

```python
def _statement_row_menu(row_index: int) -> tk.Menu:
    row = self._statement_rows[row_index]
    menu = tk.Menu(self.statement_table, tearoff=0)
    menu.add_command(
        label="Show in condition tester",
        command=lambda r=row: self._on_statement_show_in_condition_tester(r),
    )
    return menu

self.statement_table.row_context_menu_callback = _statement_row_menu
```

The handler `_on_statement_show_in_condition_tester` does:

```python
raw = (row.get("Raw Condition") or "").strip()
self._send_condition_to_tester(raw, show_empty_message=True)
```

This reliably opens the Condition Tester and injects the full `Raw Condition`
string into its clause editor.

#### Tag condition table (lower)

- Backed by `self.condition_table: DataTable`.
- Columns (`CONDITION_DETAIL_COLUMNS`):
  - `Condition ID`
  - `Policy Name`
  - `Effective Path`
  - `Access Type`
  - `Tag Namespace`
  - `Tag Key`
  - `Operator`
  - `Value`
  - `Subexpression`
- One row per parsed TagCondition for the current context (selected
  statement and active filters). When no statement is selected, the tab can
  show all matching conditions across the visible statements.
- The table has a fixed height (about 5 rows) to keep the overview compact
  but scrollable.

**Right-click behavior – “Test individual condition”**

The lower table exposes a context-menu action that sends only a single
condition subexpression to the Condition Tester. This is also wired via
`row_context_menu_callback`:

```python
def _condition_row_menu(row_index: int) -> tk.Menu:
    row = self._condition_rows[row_index]
    menu = tk.Menu(self.condition_table, tearoff=0)
    menu.add_command(
        label="Test individual condition",
        command=lambda r=row: self._on_condition_test_individual(r),
    )
    return menu

self.condition_table.row_context_menu_callback = _condition_row_menu
```

The handler `_on_condition_test_individual` does:

```python
subexpr = (row.get("Subexpression") or "").strip()
self._send_condition_to_tester(subexpr, show_empty_message=True)
```

This lets users quickly isolate and test a single tag condition (e.g.
`all { request.principal.group.tag.Operations.Project = 'X' }`) in the
Condition Tester without the surrounding boolean logic.


### Bottom Half: Construction & Testing

**LabelFrame:** `Tag-based Condition Builder & Tester`

This section is a guided surface for building new tag-based `where`
clauses and full policy statements, and for sending those clauses to the
Condition Tester and (prospectively) the Simulation tab.

The current implementation is divided into three conceptual parts:

1. **Statement-specific fields (left column)**
2. **Tag condition pieces and snippet generation (middle column)**
3. **Generated statement preview and actions (right column)**

#### 1. Statement-specific fields (left)

These widgets help construct the non-`where` portion of a policy statement
and expose distinct values observed in existing policies:

- `Principal` (`builder_principal_var`, `ttk.Combobox`):
  - Values are discovered from all regular statements in the repository.
  - Internal principal keys use the same shapes as the simulation engine
    (e.g. `group:domain/name`, `group-id:ocid1...`).
  - A separate `_builder_principal_details` map records `(type, domain, name)`
    so the generated statement can render natural phrases such as
    `group 'MyDomain'/'Developers'` or `group id ocid1.group.oc1...`.
- `Verb` (`builder_verb_var`, `ttk.Combobox`):
  - Choices: `inspect`, `read`, `use`, `manage`.
- `Resource` (`builder_resource_var`, `ttk.Combobox`):
  - Populated from distinct `Resource` values seen in loaded policies.
- `Location / Compartment` (`builder_location_var`):
  - Distinct effective paths from existing statements; interpreted as a
    base location for the statement.
- `Effective Path` (`builder_effective_path_var`):
  - Also populated from distinct effective paths.
  - Logic in `_update_previews` ensures that the chosen Effective Path is
    within the selected Location; otherwise it is reset with a warning.

The preview logic synthesizes a location clause (`in tenancy` or
`in compartment <name>`) based on the relationship between Location and
Effective Path. The final statement text uses this to generate:

```text
Allow <subject_phrase> to <verb> <resource> in compartment <name> where <snippet>
```

or, if no snippet is present:

```text
Allow <subject_phrase> to <verb> <resource> in compartment <name>
```

#### 2. Tag condition pieces and snippet generation (middle)

This column builds the actual tag-based condition snippet that goes into the
`where` clause.

Inputs:

- `Access Type` (`builder_access_type_var`, `ttk.Combobox`):
  - Same choices as the filter row: `request.principal.group`,
    `request.principal.compartment`, `target.resource`,
    `target.resource.compartment`.
- `Tag Namespace` (`builder_namespace_var`, `ttk.Entry`).
- `Tag Key` (`builder_key_var`, `ttk.Entry`).
- `Operator` (`builder_operator_var`, `ttk.Combobox`):
  - `=`, `!=`, `IN`, `NOT IN`.
- `Value(s)` (`builder_value_var`, `ttk.Entry`):
  - For `IN`/`NOT IN`, the UI treats this as a comma-separated list and
    generates a parenthesized list of quoted values.

Live previews:

- **Generated variable** (`builder_variable_preview_var`):
  - Constructed as:

    ```text
    <access_type>.tag.<namespace>.<key>
    ```

  - Example: `target.resource.tag.Operations.Project`.

- **Condition snippet** (`builder_condition_preview_var`):
  - For scalar operators:

    ```text
    all { <var_name> <op> '<value>' }
    ```

  - For `IN`/`NOT IN` operators, using a comma-separated list of values:

    ```text
    all { <var_name> IN ('dev','test','prod') }
    ```

  - This snippet is what gets sent to the Condition Tester when the
    bottom **Test Condition** button is clicked.

Any change to the builder variables or principal / location / verb fields
triggers `_update_previews`, which recomputes both the condition snippet and
the full statement preview.

#### 3. Generated statement preview and actions (right)

The right-hand column provides:

- **Location label** – shows the resolved location/compartment path
  (e.g. `Location (Compartment): root/Prod`).
- **Generated policy statement** – bound to
  `builder_statement_preview_var`, displaying a full `Allow ... to ...` OCI
  policy statement including the `where` clause if present.

Action buttons:

1. **Copy Statement** (`_on_copy_statement`)
   - Copies the generated full statement text to the clipboard.
   - No-op if the statement is empty.

2. **Test Condition** (`_on_test_condition`)
   - Reads `builder_condition_preview_var` and delegates to the shared
     helper `_send_condition_to_tester(snippet, show_empty_message=True)`.
   - If there is no snippet, shows an informational message box so users
     understand why nothing happened.
   - When a snippet is present, the helper:
     - Calls `ConditionTesterTab.set_clause_text(snippet)`.
     - Brings the Condition Tester tab to the foreground via
       `app.open_condition_tester_with_condition(snippet)` if available,
       or selects `app.condition_tester_tab` on the notebook as a
       fallback.

3. **Add to Simulation Prospects** (`_on_add_to_simulation`) – *future behavior*

   This button is wired to a best-effort stub today and is documented here
   to clarify the intended behavior for a future implementation.

   - Current behavior:
     - Reads the generated full statement from
       `builder_statement_preview_var`.
     - If non-empty and `app.simulation_tab.add_prospective_statement`
       exists, it calls that method and attempts to select the
       Simulation tab in the notebook.
     - If the Simulation tab or method is absent, it fails silently.

   - Planned behavior (to be implemented):
     - Treat the builder’s generated statement as a **prospective**
       (what-if) policy statement that does not yet exist in OCI.
     - Invoke a well-defined API on `SimulationTab`, e.g.

       ```python
       simulation_tab.add_prospective_statement(statement_text: str,
                                                source_tab: str = "Tag-based Access")
       ```

       which will:
       - Add the statement to a dedicated "Prospective Statements" list
         in the simulation UI.
       - Optionally tag it with metadata indicating it came from the
         Tag-based Access builder.
     - Automatically switch the notebook to the Simulation tab so users
       can immediately run scenarios with the newly added statement.
     - In the simulation engine, treat these prospective statements as
       if they were deployed at the chosen Effective Path / Location,
       without modifying the real policy repository.

   In effect, **Add to Simulation Prospects** will be the bridge from
   "I’ve designed a safe tag-based statement" in this tab to
   "What would this do to real access?" in the Simulation tab, while still
   avoiding any live changes to OCI policies.

This overall design keeps the Tag-based Access tab focused on
**understanding and authoring** tag conditions, while delegating detailed
evaluation and what-if analysis to the Condition Tester and Simulation
engine.


## Data Flow and Dependencies

- The Tag-based Access tab will depend on:
  - `PolicyAnalysisRepository` (via `app.policy_compartment_analysis`) to
    obtain policy statements and their `Conditions` fields.
  - `TagConditionCollector` / `extract_tag_conditions` helper to derive
    TagCondition records from raw condition text.
  - `BaseUITab` for context help, doc links, and styling.
  - `DataTable` for the overview grid.
  - `ConditionTesterTab` (and optionally SimulationTab) for integration
    buttons.

- **No new parsing or evaluation logic** will be implemented in the
  Tag-based Access tab itself. All syntax and semantics remain owned by the
  existing condition parser and simulation engine.


## Roadmap and Future Enhancements

Initial implementation will focus on:

1. Creating the `TagCondition` model and the `TagConditionCollector`
   visitor + `extract_tag_conditions` helper.
2. Implementing the Tag-based Access tab skeleton:
   - Page help text and documentation link.
   - Top overview frame with filters and a `DataTable` bound to a
     TagCondition list.
   - Bottom builder frame with form controls and live snippet generation.
3. Wiring basic discovery flow:
   - A `Refresh from Loaded Policies` button that scans all policies and
     populates the TagCondition overview.

Potential follow-ons include:

- Richer explanation text for each TagCondition (e.g. "This policy requires
  that the request principal group has tag X=Y"), which could leverage the
  GenAI "AI Assist" flow.
- Grouping/visualization of complex expressions where multiple tag
  conditions appear in the same logical group (`AND`/`OR`).
- Integration with the **Policy Recommendations** and **Intelligence**
  layers, surfacing insights like "policies missing symmetric tag
  conditions" or "unused tag-based policies".


## Related Context and References

## Current Service Contract

Tag-based policy discovery now flows through
`src/oci_policy_analysis/application/services/tag_based_policy_service.py`.
The desktop tab should consume enriched `tag_conditions` and
`tag_context_warnings` from that service/repository path. Do not add new
tab-local `.tag.` raw-text scanning except as an explicitly degraded fallback
for unparsed legacy rows.

Supported shared filters include `tag_access_type`,
`tag_access_semantics`, `tag_namespace`, `tag_key`, `tag_value`,
`tag_operator`, `condition_atom_terms`, `policy_tag`,
`policy_defined_tag`, and `policy_freeform_tag`.

Desktop UX notes:

- `tag_operator` should stay a finite dropdown, with `Any` plus the parser-supported operators.
- `tag_access_semantics` needs explanatory context help because it is a normalized service concept, not Oracle syntax.
- `condition_atom_terms` should be described as a broad parsed-condition search across atom fields, not as tag-only search.
- A dedicated web UI page is deferred until the shared service and desktop UX settle; current web support is API-level plus statement inspector fields.

- Condition parser and tester:
  - `src/oci_policy_analysis/logic/parsers/condition_parser/`
  - `src/oci_policy_analysis/presentation/desktop/condition_tester_tab.py`
  - [`CONTEXT_simulation_engine.md`](CONTEXT_simulation_engine.md)

- Policies tab and filters:
  - `src/oci_policy_analysis/presentation/desktop/policies_tab.py`
  - [`CONTEXT_policies_tab.md`](CONTEXT_policies_tab.md)

- UI architecture and BaseUITab:
  - `src/oci_policy_analysis/presentation/desktop/base_tab.py`
  - [`CONTEXT_ui.md`](CONTEXT_ui.md)
