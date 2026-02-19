# Context: Policy Browser Tab

This file documents the architecture, user workflow, UI/UX decisions, and technical implementation for the "Policy Browser" tab in the OCI Policy Analysis tool. It is intended for maintainers and new contributors who wish to understand how all OCI compartments, policies, and their policy statements can be browsed in a hierarchical, interactive way as of 2026-02-02.

---

## 1. Overview and Rationale

The **Policy Browser** tab provides a focused, read-only, hierarchical view of all compartments, policies, and policy statements for analysis or review.

- **Purpose:** Allow exploration of the entire OCI policy landscape in a single expandable tree, including statement text for each policy—regardless of policy type (regular, cross-tenant, service, etc.).
- **Scope:** No filtering, search, or policy type distinction is performed; the intent is visibility of all policy objects/statements as written, in their original compartmental context.

---

## 2. Workflow & Data Flow

- At startup, the tab loads:
    1. **Compartments:** Pulled from the main policy repo (flat list, includes parent/child OCIDs).
    2. **Policies:** Grouped by compartment OCID.
    3. **Policy Statements:** All statement objects (including statement text) are grouped under their policy (by `policy_name`), not directly denormalized in the Policy object.
- The tab reconstructs a tree with:
    - **Compartment** (rooted at tenancy, then recursively by parent)
        - **Policy** (all in that compartment)
            - **Statement** (statement text, with max display length for brevity)
- **Right-click on any node** brings up a context menu, such as "Focus in Next Tab", for navigation or workflow integration.

---

## 3. UI, Implementation, and Technical Conventions

- **Base Class:** Inherits from `BaseUITab` for context help and standard appearance.
- **Tree Control:** Uses `ttk.Treeview` for compartments/policies/statements, with `open=False` for collapsed nodes by default.
- **No Filtering/Distinction:** All statement types are shown together; the statement text is looked up by policy name across the flat statements list.
- **Actions:** Right-click (`<Button-3>`) on any tree element shows a context menu (actions may be stubs or extended for downstream features).
- **Help:** Contextual help is built into the tab via mouse-over and top help box.

---

## 4. Extensibility and Integration

- **Tab Registration:** The tab is integrated into the main app notebook directly after the Settings tab.
- **Future Features:** The right-click action is implemented as a stub, but can be extended as UX or workflow evolves (e.g., deeper drilldown, export, tab focus control).
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
| 2026-02-02 | Initial implementation and context documentation for new tab     | policy_browser_tab.py, main.py, CONTEXT_policy_browser_tab.md |

---

## 7. Related Context Files

- [CONTEXT_historical_analysis.md](CONTEXT_historical_analysis.md): Diffing tab
- [CONTEXT_policies_tab.md](CONTEXT_policies_tab.md): Policy statement/output tab
- [CONTEXT_ui.md](CONTEXT_ui.md): UI/Context Help and tab design conventions

---

**Summary:**  
The Policy Browser tab reveals the entire structure and text of all OCI policies—organized by compartment, grouped by policy, statements shown by name lookup—enabling full visibility of written policies for analysis, review, or audit, while matching the app’s standard tab and context help conventions.