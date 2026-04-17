# Project-Specific Context: Policy Browser Tab

This file documents the architecture, user workflow, UI/UX decisions, and technical implementation for the "Policy Browser" tab in the OCI Policy Analysis tool. It is intended for maintainers and new contributors who wish to understand how all OCI compartments, policies, and their policy statements can be browsed in a hierarchical, interactive way as of 2026-04-16.

---

## Policy Statement Limits Display & Coloring

- The **Show Policy Statement Limits** checkbox (in the "Display Options" row, to the right of "Expand Compartments Only") toggles visibility of the statement count summary under each compartment in the tree.
- When this box is checked, each compartment will:
    - Show a row summarizing statement counts ("Statement count - direct: ..., cumulative: ...").
    - Display its background color-coded by cumulative statement count to quickly spot scaling or limit risks:
        - **Green:** Cumulative count under 450 (safe: below 90% of limit).
        - **Yellow:** Cumulative count 450–500 (warning: 90% or more of limit).
        - **Red:** Cumulative count above 500 (over the policy statement limit - action required).
- Unchecking the box hides the count summary row and removes the color coding for cleaner tree viewing.

---

## 1. Overview and Rationale

The **Policy Browser** tab provides a focused, read-only, hierarchical view of all compartments, policies, and policy statements for analysis or review.

- **Purpose:** Allow exploration of the entire OCI policy landscape in a single expandable tree, including statement text for each policy—regardless of policy type (regular, cross-tenant, service, etc.).
- **Scope:** No filtering, search, or policy type distinction is performed; the intent is visibility of all policy objects/statements as written, in their original compartmental context.

---

## 2. Workflow & Data Flow

- At startup, the tab now **builds UI only** (no repository data load side-effects).
- Data population happens only when app post-load orchestration calls:
    - `App._post_load_update_ui()` → `policy_browser_tab.post_load_update_ui()`.
- During that post-load call, the tab uses loaded repository data for:
    1. **Compartments:** Pulled from the main policy repo (flat list, includes parent/child OCIDs).
    2. **Policies:** Grouped by compartment OCID.
    3. **Policy Statements:** Grouped under their policy (by `policy_name`) and filtered by compartment/policy pair when rendered.
    4. **Defined Tag Catalog:** Namespaces/keys/values and namespace compartment path metadata (from `defined_tag_namespace_keys`).
- The tab reconstructs a tree with:
    - **Compartment** (rooted at tenancy, then recursively by parent)
        - **Policy** (all in that compartment)
            - **Statement** (statement text, with max display length for brevity)
- **Right-click on tree nodes** brings up a context menu, such as "Focus in Next Tab", for navigation or workflow integration.
- **Right-click on tag catalog rows** can open Tag-based Access tab with namespace/key/value filters pre-filled.

---

## 3. UI, Implementation, and Technical Conventions

- **Base Class:** Inherits from `BaseUITab` for context help and standard appearance.
- **Deferred data initialization:** Constructor builds static controls and placeholders only. Tree/tag data are populated later via `post_load_update_ui()`.
- **Tree Control:** Uses `ttk.Treeview` for compartments/policies/statements, with `open=False` for collapsed nodes by default.
- **Layout:** Main content is now left/right split instead of stacked:
    - **Left (~75%)**: Compartment/Policy/Statement tree.
    - **Right (~25%)**: Defined tag catalog panel.
- **Show Policy Statement Limits:** The "Show Policy Statement Limits" checkbox (next to "Expand Compartments Only") controls visibility of per-compartment policy statement counts and applies background color highlighting for limit awareness.
    - When checked, a per-compartment row shows "direct" and "cumulative" statement counts and compartment rows are color-coded:
        - _Green_: safely under limit.
        - _Yellow_: at/above 90% (450), up to 500.
        - _Red_: exceeded limit (over 500).
    - When unchecked, the count/limit row and highlighting are hidden for a cleaner navigation experience.
- **No Filtering/Distinction:** All statement types are shown together; the statement text is looked up by policy name across the flat statements list.
- **Tag Catalog Panel (right side):**
    - Top table: `Namespace | Compartment Path | Defined Key`
    - Bottom table: value detail rows for selected namespace/key (`User-Supplied` if values are not enumerated)
    - Namespace compartment path is resolved from repository metadata (`compartment_ocid` → hierarchy path).
- **Actions:**
    - Tree right-click (`<Button-3>`) supports cross-tab focus to Policies tab.
    - Tag catalog right-click supports opening Tag-based Access tab with namespace/key and optional selected value.
- **Help:** Contextual help is built into the tab via mouse-over and top help box.

---

## 4. Extensibility and Integration

- **Tab Registration:** The tab is integrated into the main app notebook directly after the Settings tab.
- **Cross-tab integration:** Tag catalog right-click now drives Tag-based Access filters (namespace/key/value), making Policy Browser a direct discovery entry point for tag-focused analysis.
- **Future Features:** Existing context menus can be extended further (e.g., richer value-aware navigation, export, deeper drilldown).
- **Style:** Follows context file documentation and modular Python engineering conventions for UI tabs in this application.

---

## 5. File and Module References

| Area                  | File/Module                                                                                      |
|-----------------------|-------------------------------------------------------------------------------------------------|
| Main UI Tab           | `src/oci_policy_analysis/ui/policy_browser_tab.py`                                              |
| Tab Registration      | `src/oci_policy_analysis/main.py`                                                               |
| Compartment/Policy Repo| `PolicyAnalysisRepository` object, from `logic/data_repo.py`, used as `app.policy_compartment_analysis` |
| UI Context Help System| `src/oci_policy_analysis/ui/base_tab.py`                                                        |

---

## 6. History and Changes

| Date       | Change Summary                                                   | Area/Module(s) Impacted                      |
|------------|------------------------------------------------------------------|----------------------------------------------|
| 2026-04-16 | Deferred Policy Browser data initialization to post-load call path; changed browser layout to left/right split; enhanced tag catalog into two-table namespace/key + value detail model; added right-click navigation from tag catalog to Tag-based Access with namespace/key/value prefill | policy_browser_tab.py, main.py, tag_based_access_tab.py, CONTEXT_policy_browser_tab.md |
| 2026-03-11 | Added "Show Policy Statement Limits" checkbox and per-compartment row color coding for statement count limits; documentation updated                 | policy_browser_tab.py, CONTEXT_policy_browser_tab.md |
| 2026-02-02 | Initial implementation and context documentation for new tab     | policy_browser_tab.py, main.py, CONTEXT_policy_browser_tab.md |

---

## 7. Related Context Files

- [CONTEXT_historical_analysis.md](CONTEXT_historical_analysis.md): Diffing tab
- [CONTEXT_policies_tab.md](CONTEXT_policies_tab.md): Policy statement/output tab
- [CONTEXT_ui.md](CONTEXT_ui.md): UI/Context Help and tab design conventions

---

**Summary:**  
The Policy Browser tab now uses a deferred-load lifecycle (quiet UI construction followed by explicit post-load population), a left/right layout that dedicates space to tag discovery, and a two-table tag catalog with value drilldown. It remains the primary read-only hierarchy browser while also acting as a jump-off point into Tag-based Access analysis via right-click namespace/key/value navigation.