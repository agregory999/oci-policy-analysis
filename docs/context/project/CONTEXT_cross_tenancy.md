# Project-Specific Context: Cross-Tenancy Display & Filtering

This document defines the architecture, data flow, and conventions for displaying and filtering cross-tenancy (Admit/Endorse/Define) policy statements in the OCI Policy Analysis tool. It aligns with project standards and clarifies how the cross-tenancy tab integrates data modeling, business logic, and user interface, with references to major implementation files.

---

## 1. Area Overview

Cross-tenancy policy analysis provides the ability to discover, display, and filter "admit", "endorse", and "define" statements that enable resource access between tenancies. The cross-tenancy display tab enables end-users to:
- View all defined tenancy aliases (`define` statements), with their type, name, and OCID alias.
- Explore all associated `admit` and `endorse` policy statements relevant to cross-tenancy.
- Filter admits/endorses by selecting one or more defined tenancy aliases, showing only those statements that reference the selected alias by exact (case-insensitive) match.
- Review detailed, normalized metadata for each policy statement as derived from canonical models.

This flow allows users to reason about trust boundaries, cross-tenant permissions, and access paths in a fine-grained manner.

---

## 2. Evolution Timeline and Major Changes

| Date       | Commit Hash | Change Summary                                           | Modules Impacted                                             |
|------------|-------------|---------------------------------------------------------|--------------------------------------------------------------|
| 2026-01-24 | (pending)   | Refactor: robust exact-match filtering, add context doc | cross_tenancy_tab.py, data_repo.py, CONTEXT_cross_tenancy.md |
| ...        | ...         | ...                                                     | ...                                                          |

_(Expand this table as new behaviors, filtering logic, or UI features are added.)_

---

## 3. Cross-Tenancy Rules and Conventions

- **UI Display**: All cross-tenancy statements are available in a dedicated tab (`CrossTenancyTab`, Tkinter/ttk), split into defined alias, admit policy, and endorse policy tables.
- **Filtering Behavior**:
    - Selecting one or more rows in the "Defined Aliases" table restricts the admit and endorse tables to only those referencing the corresponding defined tenancy/alias.
    - Filtering is an **exact, case-insensitive, trimmed string match** (not a substring or regex) on `admitted_tenancy` and `endorse_tenancy`, compared to the selected `defined_name` from parsed `DefineStatement`.
    - Future enhancements may also allow filtering by OCID alias, if policy statements or the UI support referencing aliases.
- **Models and Data Flow**:
    - All cross-tenancy policy statements conform to the normalized models in `common/models.py` (see `DefineStatement`, `AdmitStatement`, `EndorseStatement`).
    - The business/data layer (`data_repo.py`) is responsible for loading, normalizing, and storing cross-tenancy statements from source OCI policies.
    - The UI logic (`cross_tenancy_tab.py`) implements selection callbacks and updates tables based on view/filter actions, consuming only normalized model data.
- **Refactoring/Testing**:
    - All changes must keep UI callbacks free of substring/loose matching for tenancies.
    - Filtering bugs related to loose/partial matching should be prevented by strict normalization.

---

## 4. Exceptions & Project-Specific Overrides

- The cross-tenancy tab diverges from generic table-filtering patterns by enforcing model-driven, not freeform, filtering logic.
- Exact matching policy is project-mandated to avoid cross-tenant confusion and security risks.
- Any changes to data extraction/parsing for cross-tenancy statements must be reflected in the matcher for both admit and endorse cases.

---

## 5. Cross-References

| Purpose                   | File/Module                                                                                                                  |
|---------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Model Definitions         | [`common/models.py`](../../../src/oci_policy_analysis/common/models.py)                                                     |
| Data Loading/Filtering    | [`logic/data_repo.py`](../../../src/oci_policy_analysis/logic/data_repo.py)                                                 |
| UI (Tab & Filter Logic)   | [`ui/cross_tenancy_tab.py`](../../../src/oci_policy_analysis/ui/cross_tenancy_tab.py)                                       |

Further context: for UI style, see [CONTEXT_ui.md](CONTEXT_ui.md); for general logic conventions, see [CONTEXT_logic.md](CONTEXT_logic.md).

---

## 6. Known Limitations and Roadmap

- The current filtering logic is robust for most real-world cases but may need enhancement if OCI starts allowing alias-based or advanced tenancy references in policies.
- Future UI/UX improvements could include advanced search, wildcard/regex filtering, and easier cross-navigation between policies and resource views.
- Ensure all test suites cover filtering edge cases to prevent regressions.

---