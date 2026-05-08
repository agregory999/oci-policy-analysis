# Project-Specific Context: Cross-Tenancy Display & Advanced Actions

This document defines the architecture, data flow, and conventions for displaying and filtering cross-tenancy (Admit/Endorse/Define) policy statements in the OCI Policy Analysis tool, and documents advanced features for composing and consolidating cross-tenancy policies.  

---

## 1. Area Overview

Cross-tenancy policy analysis provides the ability to discover, display, and filter "admit", "endorse", and "define" statements that enable resource access between tenancies. The cross-tenancy display tab enables end-users to:
- View all defined tenancy aliases (`define` statements), with their type, name, and OCID alias.
- Explore all associated `admit` and `endorse` policy statements relevant to cross-tenancy.
- Filter admits/endorses by selecting one or more defined tenancy aliases, showing only those statements that reference the selected alias by exact (case-insensitive) match.
- Review detailed, normalized metadata for each policy statement as derived from canonical models.
- **[New]** Compose "opposing" cross-tenancy policy statements for review or authoring.
- **[New]** Consolidate all define/admit/endorse policy statements (scoped to the root policy) for the selected tenancies, via the consolidation engine.

This flow allows users not only to reason about trust boundaries and cross-tenant permissions, but also to act upon, simulate, and optimize cross-tenancy relationships in a fine-grained and programmatic manner.

---

## 2. Evolution Timeline and Major Changes

| Date       | Commit Hash | Change Summary                                                              | Modules Impacted                                             |
|------------|-------------|----------------------------------------------------------------------------|--------------------------------------------------------------|
| 2026-01-24 | (pending)   | Refactor: robust exact-match filtering, add context doc                    | cross_tenancy_tab.py, data_repo.py, CONTEXT_cross_tenancy.md |
| 2026-03-16 | (pending)   | Add "Opposing Tenancy" and "Consolidate Cross-Tenancy" workflows, UI mods  | cross_tenancy_tab.py, common/models.py, consolidation_engine.py, CONTEXT_cross_tenancy.md |
| ...        | ...         | ...                                                                        | ...                                                          |

---

## 3. Cross-Tenancy Rules and Conventions

- **UI Display:**  
  - All cross-tenancy statements are available in a dedicated tab (`CrossTenancyTab`, Tkinter/ttk), split into defined alias, admit, and endorse tables.
  - **Tables for Admits and Endorses are now displayed with shortened heights (fewer visible rows) for improved page layout; scrollbars are provided for full access.**

- **Filtering Behavior:**
    - Selecting one or more rows in the "Defined Aliases" table restricts the admit and endorse tables to only those referencing the corresponding defined tenancy/alias.
    - Filtering is an **exact, case-insensitive, trimmed string match** (not a substring or regex) on `admitted_tenancy` and `endorse_tenancy`, compared to the selected `defined_name` from parsed `DefineStatement`.
    - Filtering may later be expanded to include matching via OCID alias, if referenced in policies.

- **Models and Data Flow:**
    - All cross-tenancy statements conform to normalized schema in `common/models.py`:
        - `DefineStatement`, `AdmitStatement`, `EndorseStatement`.
    - The business/data layer (`data_repo.py`) loads and normalizes policy data from on-disk or server sources.
    - The UI (`cross_tenancy_tab.py`) manages filtering, selection callbacks, table updates, and advanced workflows.

---

## 4. Advanced Features and Workflows

### 4.1 Generate Opposing Tenancy Statements

- **Purpose:**  
  Allow the user to automatically generate the "opposite" of selected cross-tenancy relationships (for example, producing an admit policy in the opposing tenancy based on currently selected defines/admit/endorse).
- **UI Integration:**  
  - A "Generate Opposing Tenancy Statements" button is displayed above or near the "Defined Aliases" section.
  - Enabled only when one or more defines are selected.
  - Prompts the user to define the name for the opposing tenancy.
- **Logic:**  
  - For each selected define (and optionally associated admit/endorse), a proposed ("opposing") policy statement is composed.
  - The "opposite" inverts the direction of permission, swapping principal-tenancy fields (e.g., "our" tenancy becomes the reference in the admit).
  - All relevant fields (principal type, name, permissions, resource, where clause, etc.) are preserved or adapted for accurate inversion.
- **Display:**  
  - All proposed policy statements are presented in a popup or messagebox for review/copying.
- **Security/Correctness:**  
  - Only fields meaningful to both source/target tenancies are included in the logic; advanced "associate" patterns are supported if referenced.

### 4.2 Consolidate Cross-Tenancy (Root Policy Scope)

- **Purpose:**  
  Enable bulk consolidation of all define/admit/endorse statements (for selected tenancies) residing in the **root policy**.
- **UI Integration:**  
  - "Consolidate Cross-Tenancy" button in the define area.
  - Enabled when any define is selected.
- **Logic:**  
  - Upon activation, collects all admit/endorse for selected define(s), using robust matching and restricting to root policy (compartment_path == ROOT).
  - Invokes the consolidation engine, using the "pack" strategy or a custom one as required.
  - Produces a consolidation "plan" which is displayed to the user (UI popup or side-panel).
- **Testing/Robustness:**  
  - Edge cases (e.g., multi-tenancy overlap, invalid or incomplete definitions) are handled via error messaging or in plan instructions.

---

## 5. UI Implementation Notes

- **Admit/Endorse Table Height:**  
  - The tables for admit and endorse statements have their visible height reduced for a more compact layout. The row count can be adjusted in the DataTable widget construction or after instantiation using `.grid()` or parent frame configuration.
- **Button Actions:**  
  - UI elements for "Generate Opposing Tenancy" and "Consolidate Cross-Tenancy" are context-aware and disabled unless selection conditions are met.
  - Callbacks for these buttons leverage existing selection/filter infrastructure to produce, display, or pass data to advanced business logic.

---

## 6. Cross-References

| Purpose                   | File/Module                                                                                                                  |
|---------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Model Definitions         | [`common/models.py`](../../../src/oci_policy_analysis/common/models.py)                                                     |
| Data Loading/Filtering    | [`logic/data_repo.py`](../../../src/oci_policy_analysis/logic/data_repo.py)                                                 |
| UI (Tab & Filter Logic)   | [`ui/cross_tenancy_tab.py`](../../../src/oci_policy_analysis/ui/cross_tenancy_tab.py)                                       |
| Consolidation Engine      | [`logic/consolidation_engine.py`](../../../src/oci_policy_analysis/logic/consolidation_engine.py)                           |

Further context: for UI style, see [CONTEXT_ui.md](CONTEXT_ui.md); for general logic conventions, see [CONTEXT_logic.md](CONTEXT_logic.md).

### External OCI Reference: Cross-Tenancy Association Policies

For OCI Database Tools cross-tenancy **associate** statement patterns and
constraints, see Oracle documentation:

- https://docs.oracle.com/en-us/iaas/database-tools/doc/cross-tenancy-association-policies.html

This is useful when validating or expanding parser support for statements like:

- `admit ... to associate <resource A> in tenancy <X> with <resource B> in compartment/tenancy <Y>`
- `endorse ... to associate <resource A> in compartment/tenancy <X> with <resource B> in tenancy <Y>`

Implementation note:

- The parser currently preserves associate-oriented fields (`*_associate_*` and
  `associate_clause_raw`) and can be enhanced further by aligning additional
  edge-case rules with Oracle's documented association patterns.

---

## 7. Known Limitations and Roadmap

- Filtering, opposition logic, and root-policy scope are robust but may require expansion if OCI supports advanced aliasing or referencing patterns.
- "Opposing Tenancy" and consolidation workflows currently require selection of defined tenancies and acknowledge only statements that meet normalization/validation criteria.
- Additional UX improvements may be considered if large-scale multi-tenancy navigation or authoring becomes a common use-case.
- All test suites should exercise edge cases for matching logic, opposition correctness, and plan generation.

---