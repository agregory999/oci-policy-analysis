##########################################################################
# CONTEXT_dynamic_groups_tab.md
#
# Architectural and behavioral context for the Dynamic Groups tab UI.
#
# This document describes how the Dynamic Groups tab is wired to the
# PolicyAnalysisRepository, what filters and tables it exposes, and which
# public methods are intended for cross-tab integrations.
##########################################################################

## Overview

The **Dynamic Groups** tab allows you to browse, filter, and analyze
OCI IAM Dynamic Groups and see the policy statements that reference
them. It is primarily a read-only exploration and analysis surface
backed by data from `PolicyAnalysisRepository`.

Key capabilities:

- Filter dynamic groups by **Domain**, **Name**, **Rule Component**, and
  **Dynamic Group OCID** (using `|` for OR semantics within a field).
- Toggle output to show only **Instance Principals** or only **Unused**
  dynamic groups.
- Switch between a compact view and a **Show all Data** view that
  includes additional ID, OCID, and metadata columns.
- Select dynamic groups to display all **matching policy statements**
  below.
- From the policy table, jump directly to the Policies tab to analyze
  the full policy.
- (Planned) Accept cross-tab actions (e.g., from Policies tab) to
  focus on one or more dynamic groups by OCID.


## Data and Models

The Dynamic Groups tab is backed by the main
`PolicyAnalysisRepository` instance exposed on the app as
`policy_compartment_analysis`.

Primary model types:

- `DynamicGroup` – basic identity-domain + dynamic group identity.
- `DynamicGroupSearch` – filter object used by
  `PolicyAnalysisRepository.filter_dynamic_groups`.
- `PolicySearch` – used to fetch policy statements that reference the
  selected dynamic groups.

Normalization helpers:

- `for_display_dynamic_group` – converts repository dynamic group
  objects into dicts suitable for the UI `DataTable` (includes
  Domain, DG Name, Matching Rule, In Use, DG OCID, IDs, timestamps,
  etc.).
- `for_display_policy` – similar helper for policy statements.


## UI Structure

### 1. Dynamic Group Filters

The top **Dynamic Group Filters** label frame contains:

- **Domain** – text filter (`domain_filter_var`), disabled until
  controls are enabled after data load.
- **Name** – text filter (`dg_name_var`).
- **Rule Component** – text filter (`dg_rule_var`), which can be
  overridden automatically when *Show Only Instance Principals* is
  checked.
- **DG OCID** – text filter (`dg_ocid_var`) used to filter by one or
  more dynamic group OCIDs. Multiple values are separated with `|` for
  logical OR behavior.
- **Clear Filters** – button that clears all four filter fields and
  refreshes the output.

All filters use `|` for OR within each field and are combined with AND
across fields via `DynamicGroupSearch`.

### 2. Output Filters and AI Assist

The **Dynamic Group Output Filters** frame exposes:

- **Show Only Instance Principals** – when checked, the matching rule
  filter is overridden to `instance.compartment.id|instance.id`.
- **Show Only Unused Dynamic Groups** – additionally filters the
  displayed rows to only those not marked `In Use`.
- **Show all Data** – a checkbox that controls whether the dynamic
  groups table displays a compact set of columns
  (`BASIC_DG_COLUMNS`) or all available columns
  (`ALL_DG_COLUMNS`). Context help explains that this adds extra
  ID/OCID and metadata fields.
- **AI Assist** – toggles the shared AI analysis pane for contextual
  explanation of selected policy statements.

Two label-based counters are maintained:

- `Dynamic Groups (Filtered)` – shows total vs filtered dynamic group
  counts.
- `Policy Statements (Shown Below)` – number of policies currently in
  the lower table.

### 3. Dynamic Groups Table

The **Dynamic Groups Table** uses the shared `DataTable` widget with:

- `columns=ALL_DG_COLUMNS`
- `display_columns=BASIC_DG_COLUMNS` by default.

Behavior:

- Selecting rows triggers `dg_selection_callback`, which:
  - Builds a `PolicySearch(exact_dynamic_groups=[...])` using
    `(domain_name, dynamic_group_name)` for each selection.
  - Calls `policy_compartment_analysis.filter_policy_statements` to
    retrieve matching policy statements.
  - Normalizes them via `for_display_policy` and pushes them into the
    lower policy table.
- Right-clicking a row opens a context menu allowing the user to open
  the dynamic group directly in the OCI console in the browser.

The table’s visible columns are controlled by
`DynamicGroupsTab.set_show_all_data` and the associated
`show_all_data_var` BooleanVar.


### 4. Policies Matching Selected Dynamic Groups

The bottom **Policies Matching Selected Dynamic Groups** label frame
contains another `DataTable`:

- Columns are derived from `ALL_POLICY_COLUMNS` but the default view is
  `BASIC_POLICY_COLUMNS`.
- Selecting a single policy row configures the shared AI context on the
  main app (`policy_query_var`, `policy_query_label_text`, and
  `ai_additional_instructions`) to analyze that statement.
- Right-clicking a row provides a **View Full Policy** action that
  switches to the Policies tab, shows the policy name filter, and
  ensures the dynamic-group-related statements are highlighted there.


## Filtering Semantics

Dynamic groups are filtered via `DynamicGroupSearch` with these
parameters:

- `domain_name` – list of domain names from `domain_filter_var`.
- `dynamic_group_name` – list from `dg_name_var`.
- `matching_rule` – either explicit values from `dg_rule_var` or the
  fixed `['instance.compartment.id', 'instance.id']` when *Show Only
  Instance Principals* is checked.
- `dynamic_group_ocid` – a list built from `dg_ocid_var`, when present.

Downstream, after the repository filter, an additional in-memory pass
optionally discards rows that are `In Use` when *Show Only Unused
Dynamic Groups* is checked.


## Public Methods and Integration Points

The Dynamic Groups tab exposes a small set of public methods intended
for the main app and other tabs.

### `populate_data()`

```python
def populate_data(self) -> None:
    """Populate / refresh Dynamic Groups tab data after a load.

    This is the single entry point used by the main application after
    repository data is (re)loaded. It enables filter controls and refreshes
    the dynamic groups table using the current filter state.
    """
```

Used by `App._post_load_update_ui` as the timed step:

```python
step('dynamic_groups_tab.populate_data', self.dynamic_groups_tab.populate_data)
```

This method currently delegates to `enable_controls()` which enables all
filter widgets and triggers `_update_dg_output()`.

### `enable_controls()`

```python
def enable_controls(self) -> None:
    """Called from main app when data is loaded to enable the controls"""
```

- Enables the Domain, Name, Rule Component, and DG OCID filter entry
  widgets and the Clear Filters button.
- Triggers an initial `_update_dg_output()` pass.

While still public, orchestration after load should go through
`populate_data()` for consistent timing logs.

### `set_show_all_data(checked: bool | None = None)`

```python
def set_show_all_data(self, checked: bool | None = None) -> None:
    """Sync table display columns with the *Show all Data* checkbox.

    If *checked* is provided, force the checkbox to that state. If
    *checked* is ``None``, rely on the current BooleanVar value.
    """
```

Responsibilities:

- Keeps `show_all_data_var` and the displayed columns in sync.
- Chooses between `BASIC_DG_COLUMNS` and `ALL_DG_COLUMNS` on the
  primary dynamic groups `DataTable`.

This method is safe to call from other tabs when they want to ensure all
metadata (especially OCIDs) are visible before driving a focus action.

### `set_ocid_filter_and_search(ocids: list[str] | None)`

```python
def set_ocid_filter_and_search(self, ocids: list[str] | None) -> None:
    """Set the DG OCID filter from a list of OCIDs and refresh the table.

    Intended for cross-tab integrations (e.g., Policies tab right-click
    actions) to programmatically focus on one or more dynamic groups by
    OCID. OCIDs are joined with ``|`` to leverage existing OR semantics.
    """
```

Behavior:

- Accepts a list of dynamic group OCIDs.
- Joins them with `|` and assigns the result to `dg_ocid_var`.
- Immediately calls `_update_dg_output()` to apply the new filter and
  refresh the table.

This method is the primary hook for future cross-tab interactions (for
example, from a policy statement that mentions a particular dynamic
group or set of groups).


## Example Future Integration from Policies Tab

While not yet wired in `policies_tab.py`, the intended usage pattern for
cross-tab integration is:

```python
def focus_dynamic_groups_for_ocids(self, ocids: list[str]) -> None:
    # Switch to Dynamic Groups tab
    self.app.notebook.select(self.app.dynamic_groups_tab)

    # Ensure all columns (including DG OCID) are visible
    self.app.dynamic_groups_tab.set_show_all_data(True)

    # Apply OCID filter and refresh output
    self.app.dynamic_groups_tab.set_ocid_filter_and_search(ocids)
```

Such a helper could be called from a right-click menu item on the
Policies tab, where the set of relevant dynamic group OCIDs is derived
from the selected policy statement.


## Performance and Timing Notes

- The main app uses `_post_load_update_ui` to time each tab’s initial
  refresh after data and intelligence are loaded.
- For the Dynamic Groups tab, only a single step is logged:

  ```text
  [UI Timing] dynamic_groups_tab.populate_data: 0.XXs
  ```

- Any additional intra-tab timing (e.g., breaking out filter building vs
  repository calls) can be added later using `BaseUITab` helpers if
  needed, but the current surface is intentionally simple.


## Summary

The Dynamic Groups tab is a focused exploration surface for IAM
Dynamic Groups and the policies that reference them. Its public API is
small but sufficient to support future integrations from other tabs,
especially the Policies tab, which may wish to direct the user to a
pre-filtered view based on the dynamic groups implicated in a given
policy statement.
