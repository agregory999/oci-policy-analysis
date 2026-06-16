# Project-Specific Context: Historical Analysis / Comparison Tab

This file documents the architecture, workflow, technical conventions, and UI/UX decisions for the Historical Analysis (Comparison) Tab of the OCI Policy Analysis tool as of 2026-02-02. It is updated to reflect the new architecture (per-section diffing, improved display, live dropdown tenancy info) and is meant to bring new contributors up to speed on all comparison and diff logic, grouping strategies, and user-facing behaviors.

---

## 1. Overview and Rationale

The Historical Analysis/Comparison tab enables users to **compare two cached OCI tenancy states**—typically, before and after a set of changes. This is crucial for audit, change review, and understanding the potential impact of policy or identity modifications over time.

- Users select "left" (baseline) and "right" (target) cache snapshots from dropdowns at the top of the tab.
- *Directly below each dropdown*, the UI now shows:  
    - **Tenancy Name**  
    - **Tenancy OCID**  
    - **data_as_of** (timestamp)  
  for the selected cache, updating instantly on selection change.
- DeepDiff (with canonicalization/normalization) is used to robustly compute and sort all differences—even for large, complex tenancy policy sets.

---

## 2. Workflow & Data Flow

### Key Steps in Comparison

1. **User selects 'left' and 'right' cache snapshots** by dropdown, representing two points-in-time. Tenancy info is displayed for each selection.
2. On clicking 'Compare':
    - Both caches are loaded and canonicalized using `canonical_filter`, ensuring consistent JSON structure and list ordering.
    - A **separate DeepDiff is then run for each of the following top-level elements:**

      **Top Display (Policies):**
      - Policies (`policies`)
      - Regular Statements (`policy_statements`)
      - Defined Aliases (`defined_aliases`)
      - Cross-Tenancy Statements (`cross_tenancy_statements`)

      **Bottom Display (Identity):**
      - Identity Domains (`domains`)
      - Groups (`groups`)
      - Dynamic Groups (`dynamic_groups`)
      - Users (`users`)

    - Each of these diffs is run independently, comparing only the target section list/dict between "left" and "right" caches (missing elements are treated as empty).
3. **Results are grouped and displayed as separate top-level nodes:**
    - Policies/Statements/Aliases/Cross-Tenancy each have a dedicated group in the top display.
    - Identity Domains/Groups/Dynamic Groups/Users each have a dedicated group in the bottom display.
    - **Sections with zero changes are still shown as empty nodes** (users always see the full analytical structure).
    - There is no multi-path filtering complexity: each group displays only the diffs for its section.
    - Entity labels and diff labels are as before, but are now always strictly matched to the appropriate per-section DeepDiff.

---

## 3. Logging, Technical Conventions, and UI Patterns

- **Tab Structure:**
  - Inherits from `BaseUITab` for Context Help, standard tab function, and dynamic styling.
  - Default Context Help clearly explains the per-section diff approach and tenancy info display.

- **UI Grouping and Tree Display:**
  - IDs for removals/additions are always computed from the correct cache for accurate labeling (left for removals, right for adds, etc).
  - **Each major element always appears as its own node in the display tree**, regardless of whether there are changes.
  - Display is always (for bottom tree): Identity Domains → Groups → Dynamic Groups → Users (fixed order).
  - For each section, changes are grouped by entity where meaningful, and by diff status (Added/Removed/Modified, with field-level diffs).

- **Diff Engine and Logging:**
  - Separate DeepDiffs are run per major element. This architecture:
    - Prevents cross-section noise/false positives.
    - Makes the codebase easier to extend (add new types as new sections).
    - Improves the clarity and predictability of results.
  - **Info-level logging is written for each section DeepDiff**, reporting:
    - Which section was compared (label and JSON key).
    - Types of diffs detected, counts, and a sample.
    - This makes it much easier to debug user/tester diff output.

- **Error Handling:**
  - If a cache fails to load, or an element is missing, the UI shows a descriptive error/status.
  - The display trees will show empty nodes (no differences) if there are no actual changes for the section selected.

---

## 4. Integration and Extensibility

- The comparison and display logic is built so that *new major resource types* can be added by extending the section list and wiring their DeepDiffs and display nodes. All canonicalization, grouping, and UI integration conventions are preserved by default.
- The Context Help system continues to follow [`CONTEXT_ui.md`](CONTEXT_ui.md) documentation.
- **No logic in this tab relies on unrelated tabs or business logic.**
- Candidate future extensions:
    - Support for other resource types (networks, compute, etc.), each as new, clearly separated nodes.
    - Diff export/reporting.
    - Advanced filtering and display controls at the section/group level.

---

## 5. File and Module References

| Area           | File/Module                                                                                              |
|----------------|---------------------------------------------------------------------------------------------------------|
| Main UI Tab    | [`src/oci_policy_analysis/presentation/desktop/historical_tab.py`](../../../src/oci_policy_analysis/presentation/desktop/historical_tab.py)  |
| Canonicalization Helper | [`logic/diff_utils.py`](../../../src/oci_policy_analysis/logic/diff_utils.py)                   |
| UI Context Help System  | [`presentation/desktop/base_tab.py`](../../../src/oci_policy_analysis/presentation/desktop/base_tab.py)                             |
| Example: Other Tab Context File  | [`CONTEXT_ui.md`](CONTEXT_ui.md)                                                       |

---

## 6. History and Evolution

| Date       | Change Summary                                                | Module(s) Impacted                                 |
|------------|---------------------------------------------------------------|----------------------------------------------------|
| 2026-02-02 | Switched to per-section DeepDiff; tenancy info below dropdowns; policy and identity groups as explicit nodes | historical_tab.py, CONTEXT_historical_analysis.md  |
| 2026-01-30 | Flattened identity/group diff levels                          | historical_tab.py                                  |
| 2026-01-28 | Entity labeling respects removals                             | historical_tab.py                                  |
| 2026-01-25 | Major context doc/UX update                                   | CONTEXT_historical_analysis.md, CONTEXT_ui.md      |
| 2026-01-10 | Context help and display overhaul                             | historical_tab.py, base_tab.py                     |

Expand this table as important features, refactors, and design rules change.

---

## 7. Related Context Files

- [CONTEXT_ui.md](CONTEXT_ui.md): UI/Context Help patterns and tab conventions
- [CONTEXT_policies_tab.md](CONTEXT_policies_tab.md): Policies tab/filter doc
- [CONTEXT_data_repo.md](CONTEXT_data_repo.md): Data model/repo context

---

**Summary:**  
As of the 2026-02-02 refactor, the Historical Comparison tab always shows all major element diffs as separate sections, displays immediate tenancy info for selected caches, logs and displays results per section, and maintains clear, stable UI patterns for audit, review, and extensibility.