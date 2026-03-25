##########################################################################
# CONTEXT_tag_based_access_tab.md
#
# Project-Specific Context: Tag-based Access Tab (Design & Architecture)
##########################################################################

## Purpose and Positioning

The **Tag-based Access** tab (planned) is an advanced UI surface focused on
understanding and designing **tag-based OCI IAM policies**, with a strong
emphasis on the anatomy of tag conditions and how they affect access.

Its goals are to:

- Discover and summarize all **tag-based policy statements** in the loaded
  tenancy (where conditions reference `.tag.`).
- Break down each tag condition into a structured model:
  - Access type (e.g. `target.resource`, `request.principal.group`).
  - Tag namespace and key (e.g. `Operations.Project`).
  - Operator (`=`, `!=`, `IN`, etc.) and value(s).
- Provide a **builder** that helps users construct valid, well-formed
  tag-based `where` clauses.
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


## TagCondition Model (Conceptual)

For each tag-based comparison inside a `where` clause, we want to surface a
normalized **TagCondition** record. Conceptually:

```python
@dataclass
class TagCondition:
    access_type: Literal[
        'request.principal.group',
        'request.principal.compartment',
        'target.resource',
        'target.resource.compartment',
    ]
    tag_namespace: str          # e.g. "Operations"
    tag_key: str                # e.g. "Project"
    operator: str               # '=', '!=', 'IN', 'NOT IN', 'EXISTS', ...
    value: str | list[str] | None
    source_condition_text: str  # original condition/where clause
    policy_name: str | None
    policy_ocid: str | None
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
end up with multiple TagCondition records for a single statement. For the
first version of this tab, we plan to treat each tag comparison independently;
future work may add grouping metadata.


## TagConditionCollector Visitor (Parser-Side Design)

To extract TagCondition records from arbitrary where clauses, we will
introduce a dedicated visitor in the condition parser package:

- New module: `logic/parsers/condition_parser/tag_condition_collector.py`.
- This module will:
  - Import `OciIamPolicyConditionLexer`, `OciIamPolicyConditionParser`, and
    `OciIamPolicyConditionVisitor`.
  - Define the `TagCondition` dataclass (or a TypedDict equivalent in
    `common/models.py` for cross-layer use).
  - Implement a `TagConditionCollector` visitor that:
    - Walks the parse tree for a `condition_clause`.
    - Identifies comparison expressions where the left-hand side variable
      matches one of the supported access-type prefixes and contains
      `.tag.`.
    - Parses the left-hand side variable name into `access_type`,
      `tag_namespace`, and `tag_key`.
    - Extracts operator and right-hand side literal(s) from the
      comparison.
    - Appends a TagCondition instance to an internal list.

A simple public helper will wrap this visitor:

```python
def extract_tag_conditions(condition_str: str) -> list[TagCondition]:
    """Parse a where-clause string and return all TagCondition records.

    - Returns an empty list if the string is empty or has no tag-based
      comparisons.
    - Any parse errors are logged but result in an empty list, not an
      exception.
    """
```

This helper will be used by the Tag-based Access tab (and potentially by
other modules such as analytics or recommendations) to derive tag anatomy
from raw condition text.


## Tag-based Access Tab: UI Layout

The new tab will be implemented as `TagBasedAccessTab(BaseUITab)` under
`src/oci_policy_analysis/ui/tag_based_access_tab.py` and added to the
application's notebook as an **advanced** tab (toggled via Settings).

### Page-Level Behavior

- Inherits from `BaseUITab`:
  - Uses the page help area at the top to describe tag-based access
    concepts and how to use the tab.
  - Provides a permanent documentation link (e.g. to OCI official docs on
    tag-based access) via `create_doc_link_label`.
- Default page help text will explain that:
  - The top half of the tab focuses on **finding and filtering** tag-based
    statements.
  - The bottom half focuses on **constructing and testing** new
    tag-based conditions.

### Top Half: Discovery & Filtering

**LabelFrame:** `Tag-based Policies Overview`

This section surfaces a flat, per-tag-condition view across all policies in
the tenancy.

Planned widgets:

- **Filter Row**
  - `Tag Namespace:` `ttk.Entry` or `ttk.Combobox`.
  - `Tag Key:` `ttk.Entry` or `ttk.Combobox`.
  - `Access Type:` `ttk.Combobox` with values:
    - `Any`
    - `request.principal.group`
    - `request.principal.compartment`
    - `target.resource`
    - `target.resource.compartment`
  - `Refresh from Loaded Policies` button:
    - Iterates over the repository's policy statements.
    - For each statement with non-empty `Conditions` containing `.tag.`,
      calls `extract_tag_conditions` to get TagCondition records.
    - Stores results in an in-memory list and applies namespace/key/access
      type filters.

- **Results Table**
  - Backed by the shared `DataTable` component for consistency.
  - Columns (initial sketch):
    - `Policy Name`
    - `Effective Path`
    - `Subject Type`
    - `Subject`
    - `Verb`
    - `Resource`
    - `Access Type`
    - `Tag Namespace`
    - `Tag Key`
    - `Operator`
    - `Value`
    - `Raw Condition`
  - Each row corresponds to a single TagCondition record tied back to a
    specific policy statement.

- **Right-click / Double-click Actions** (future wiring):
  - "Open Policy in Browser" – jump to the OCI console policy URL.
  - "Show in Policies Tab" – focus the Policies tab on this policy
    (e.g. by name filter).
  - "Send to Tag Condition Builder" – pre-populate the bottom builder
    with the selected tag anatomy (access type, namespace, key, operator,
    value).
  - "Test Condition in Condition Tester Tab" – send the full condition
    text to the Condition Tester (similar to existing Policies tab
    integration).


### Bottom Half: Construction & Testing

**LabelFrame:** `Tag-based Condition Builder & Tester`

This section acts as a guided surface for building new tag-based `where`
clauses that users can then evaluate using the existing Condition Tester and
Simulation tabs.

Planned substructure:

1. **Builder Form (left)**
   - `Access Type:` `ttk.Combobox` with the same choices listed above.
   - `Tag Namespace:` `ttk.Entry`.
   - `Tag Key:` `ttk.Entry`.
   - `Operator:` `ttk.Combobox` where values are constrained to what the
     condition grammar supports (e.g. `=`, `!=`, `IN`, `NOT IN`, `EXISTS`).
   - `Value:`
     - A `ttk.Entry` for simple scalar values (shown for operators like
       `=` or `!=`).
     - A separate multi-value entry or guidance text for `IN`/`NOT IN`
       (e.g. values separated by `|` or using a JSON-style array,
       depending on grammar support).
   - Read-only labels showing live generated strings:
     - Generated **variable name**:
       - e.g. `target.resource.tag.Operations.Project`.
     - Generated **condition snippet**:
       - e.g. `all { target.resource.tag.Operations.Project = 'project-x' }`.

   - Buttons:
     - `Copy Condition Snippet` – copy the full where-clause snippet to
       the clipboard for manual policy editing.
     - `Send to Condition Tester` – open the Condition Tester tab,
       calling `ConditionTesterTab.set_clause_text(snippet)`.

2. **Tester / Simulation Integration (right)**
   - Rather than re-implementing condition evaluation, the builder will
     integrate with existing tabs:
     - `Open in Condition Tester` button:
       - Switch the notebook to the Condition Tester tab.
       - Set its clause text to the generated condition (or append to
         whatever is there).
     - Future: `Open in Simulation Tab` shortcut that pre-fills the
       simulation environment and passes the built condition as a
       prospective statement.

This design keeps the Tag-based Access tab focused on **understanding and
authoring** tag conditions, while delegating evaluation and simulation to the
established engines.


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

- Condition parser and tester:
  - `src/oci_policy_analysis/logic/parsers/condition_parser/`
  - `src/oci_policy_analysis/ui/condition_tester_tab.py`
  - [`CONTEXT_simulation_engine.md`](CONTEXT_simulation_engine.md)

- Policies tab and filters:
  - `src/oci_policy_analysis/ui/policies_tab.py`
  - [`CONTEXT_policies_tab.md`](CONTEXT_policies_tab.md)

- UI architecture and BaseUITab:
  - `src/oci_policy_analysis/ui/base_tab.py`
  - [`CONTEXT_ui.md`](CONTEXT_ui.md)
