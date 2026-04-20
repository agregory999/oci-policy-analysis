# Project-Specific Context: Policies Tab

The Policies tab presents all Oracle Cloud Infrastructure (OCI) policy statements relevant to the analyzed tenancy. This tab is designed to facilitate exploration, sorting, and filtering of policies for governance, audit, and troubleshooting purposes.

---

## 1. Display

- Policies are shown in a tabular format, with each row representing an individual **policy statement**.
- Columns are aligned with the internal `RegularPolicyStatement` display model, and typically include:
  - **Policy Name**
  - **Policy Compartment**
  - **Effective Path**
  - **Statement Text**
  - **Valid / Invalid Reasons**
  - **Subject Type / Subject**
  - **Verb / Resource / Permission**
  - **Location / Conditions**
  - **Parsed** and other analysis notes
- When the **Parsed Output** display option is enabled, additional columns are shown for deeper inspection.

---

## 2. Sorting

- Users can sort by any visible column (e.g., Policy Name, Policy Compartment, Effective Path).
- Clicking a column header toggles ascending/descending order.
- When **Prospective** rows are shown (see below), they participate in sorting like any other row. At initial load, real tenancy rows appear first and prospective rows are appended at the end; column sorting can then reorder them as needed.

---

## 3. Filtering

Filtering in the Policies tab is backed directly by the repository’s
`filter_policy_statements` helper (see `CONTEXT_data_repo.md`). The UI projects its
controls into a JSON filter that is then applied consistently across CLI, UI, and MCP.

Key filter inputs include:

- **Subject / Verb / Resource / Permission / Location** text fields (supporting `|` for OR within a field)
- **Hierarchy / Effective Path** filters (including special `ROOTONLY` semantics)
- **Text** (statement text search)
- **Policy Name**
- **Conditions** (raw where-clause text)
- **Action** dropdown (Both / Allow / Deny)
- **Invalid Only** toggle (filters to statements marked invalid)

Helper insertion buttons are also available for common values:

- **Add any-user / any-group** inserts `any-user|any-group` into Subject.
- **Add ROOTONLY** inserts `ROOTONLY` into Hierarchy.
- **Add Hierarchy** enriches Resource with `all-resources` plus family (when available).

### 3.1 Resource Hierarchy Helper

- The Resource filter row includes an **Add Hierarchy** button with help text:
  - `Loads containing family (if any) and all-resources`
- On click:
  - `all-resources` is always added to the Resource filter.
  - For each resource token, the UI asks `ReferenceDataRepo` for a containing
    family (case-insensitive).
  - If found, the family token is inserted before the resource token.
    - Example: `subnets` → `all-resources|virtual-network-family|subnets`
  - If no family is found, the resource is still preserved and a warning is
    displayed.
    - Example: `unknown-resource` → `all-resources|unknown-resource`

This helper only updates the filter text/value; it does not change statement
data in the repository.

### 3.2 Filter Layout Consistency

- Left-column entry fields are standardized to a shared width for more uniform
  alignment.
- Helper buttons on the left side use a consistent width to align visually.

Multiple filters are combined via **AND** across fields and **OR** within multi-valued fields.

> **Note on subjects / groups / dynamic groups**
> Some subject-based filters depend on identity-domain context (groups, users,
> dynamic groups). These are resolved through the repository’s user/group/DG
> search helpers; see `CONTEXT_data_repo.md` for details.

---

## 4. Additional UX Notes

- Sticky headers support scrolling through long lists.
- Statement formatting highlights risky or unusual patterns when identified.
- Export or copy actions may be included for selected sets.

### 4.1 Prospective (What-If) Statements in the Policies Tab

The Policies tab can optionally display **prospective (what-if)** policy
statements alongside real tenancy policies:

- A **Show Prospective** checkbox is available in the *Display Options* header.
  - When unchecked (default), only real tenancy policy statements are shown.
  - When checked, the tab:
    - Retrieves the tenancy-scoped prospective statements from the shared
      `ProspectiveStatementsService` (or simulation engine fallback).
    - Normalizes them into the same shape used for real statements.
    - Applies the **same JSON filter** used for real statements (subject,
      verb, resource, conditions, etc.) to this alternate set.
    - Appends the filtered prospective rows **after** the real rows.
- Prospective rows are clearly marked:
  - The **Policy Name** column is prefixed with `"[Prospective]"`.
  - The **Display Options** summary label adds a
    `Prospective Statements (Shown): N` line when they are visible.
- Some subject-based filters (e.g., those that expand fuzzy users into exact
  groups) may only partially apply to prospective statements, because there is
  no separate prospective user/group/dynamic group catalog. This is acceptable
  by design; existing identities are still honored where they match.

There is also a **Prospective Editor…** button next to the `Show Prospective`
checkbox. This opens the dedicated `ProspectiveEditorWindow`, where users can
perform CRUD operations on tenancy-scoped what-if statements. Changes are
persisted per-tenancy via `ProspectiveStatementsService` and are reflected in
both the Simulation tab and the Policies tab when Show Prospective is enabled.

Under the hood, the flow is:

- `ProspectiveStatementsService` (see
  `CONTEXT_prospective_statement_editor.md`) owns the tenancy-scoped list of
  prospective statements and pushes them into `PolicySimulationEngine` via
  `set_prospective_statements`.
- The Policies tab asks the repository/engine for this current list and
  reshapes each entry into a `RegularPolicyStatement`-like dict before calling
  `filter_policy_statements(filters=..., statements=prospective_like_list)`.
- This ensures that **the same JSON filter semantics** apply to both real and
  prospective statements, and that changes made in the Prospective Editor are
  immediately visible whenever `Show Prospective` is enabled.

---

## 5. Code Location

Implementation: [`src/oci_policy_analysis/ui/policies_tab.py`](../../../src/oci_policy_analysis/ui/policies_tab.py)

---

## 6. Reload Policy Data

The "Reload Policy Data" button is provided in the Filter Actions panel for advanced usage. 

- **Effect:** Reloads policies, compartments, and statements directly from the currently connected tenancy (using the original authentication and recursion settings).
- **When enabled:** Only available if your current data was loaded from tenancy (not cache or compliance). 
- **IAM Data:** Group, Dynamic Group, and User data are *not* reloaded; those are refreshed only on initial load or a full cache update.
- **Dual timestamps:** After a reload, the Settings tab will display both the original "Data as of" (the cache/IAM snapshot date) and a new "Policy data reloaded" date. This clarifies exactly which data is from which analysis point in time.
- **Progress UX:** Reload runs asynchronously and uses the shared modal progress popup with staged updates (reload source, policy intelligence, tab population/status update, final done summary).
- **Status bar:** The lower status bar remains authoritative for final loaded state/source/timestamp after reload completion.
- **UI:** Hover over the reload button for a full explanation of what is and isn't reloaded and which timestamps to expect in the Settings tab.

---

This context file will be updated as advanced features (such as saved views or policy diffing) are added to the Policies tab.
