# Project-Specific Context: In-Memory Policy Change Sets

This file describes the architecture and design for enabling *in-memory, non-destructive modeling of policy diffs ("change sets")*. It explains the core data types, integration with analysis and UI, and rationale for choosing overlay/patch-based modeling rather than repository duplication.  


---

## 1. Area Overview

- **Purpose**:  
  Allow analysis tools and UI to simulate *add/delete/modify* of policy statements without editing the original, so that all downstream filtering, simulation, and risk analysis can operate on a dynamically derived "current state" (original + all staged changes).

- **Scope**:  
  Supports modeling of new, changed, or deleted statements for use in simulations, analysis, and user previews—enabling workflows like "what if these changes were applied?" across all views without side effects.

---

## 2. Evolution and Rationale

- **Motivation**:  
  Traditional pattern would require copying the full repo or policy list any time the user wanted to test a change. This is error-prone, memory-inefficient, and introduces potential for data divergence or accidental mutation.

- **Project Decision**:  
  Instead, we use the *change set overlay* model: a top-level object tracks "diffs" (add, remove, modify) to policies by statement identity, applied dynamically atop read-only repository data. This matches project emphasis on strong typing, solid separation of original versus derived state, and enables all downstream flows to support real-time "change what-if" analysis.

---

## 3. Core Data Model and API

### 3.1 PolicyChangeSet Object

- **Definition**:  
  A `PolicyChangeSet` class describes a bundle of proposed changes: 
  - `added_statements` (list of canonical policy statements, see models.py)
  - `removed_statement_ids` (list of statement "id" or tuple keys)
  - `modified_statements` (optional: mapping from id to new/candidate statement)

- **Key Properties**:  
  - All fields conform to canonical statement types (`RegularPolicyStatement`/similar from `models.py`)
  - Never holds full policy copies—tracks diffs only
  - Immutable by default; use explicit API to mutate/change

### 3.2 Overlay Mechanism

- **Mechanics**:
  - Exposes a "patched view" API: given a `PolicyAnalysisRepository` and a `PolicyChangeSet`, produces all current policy statements as though the changes had been applied.
  - Feeds into all downstream engine/filter/search calls.
  - Patch logic:
    - All statements from the base repo except any matching a removal/modification
    - Any `modified_statement` replaces the base statement
    - All `added_statements` are appended as new

- **Example Usage**:
```python
patched_statements = PolicyChangeSet.apply(repo.list_policy_statements())
# Or: repo.get_filtered_statements(filters, changeset=my_changes)
```

---

## 4. Filtering, Search, and UI Integration

- All filter/search methods in the repository (e.g., `filter_policy_statements`) accept an *optional* `changeset` argument.
- Filter logic always runs on the *patched* "current state".
- UI, simulation, and result export flows reflect the change set as user models edits; no original repo mutation.
- Undo/redo/change history can be built by stacking or replacing PolicyChangeSet overlays.

---

## 5. Alternatives Considered

### 5.1 Full-Repo Copy
- *Pros*: Simple to reason about; fully isolated copy can be mutated at will.
- *Cons*: High memory use, slow (for big environments), risk of falling out of sync, easy to accidentally mutate baseline, doesn’t scale for concurrent overlays or undo/redo stacks.

### 5.2 Patch/Overlay Model (**chosen**)
- *Pros*: Memory efficient, leverages all existing types and filter/search, easily supports multi-stage/undo, avoids divergence, and ensures baseline data remains immutable.
- *Cons*: Patch logic and keying must be robust (statement identity, deep equality checks, etc).

---

## 6. Implementation Practices and Coding Standards

- All patch/overlay logic is in-memory; the on-disk/canonical repo is unchanged by design.
- Minimize side effects: no repo mutation, no disk writes as part of changeset application.
- All external APIs that support policy listing/filtering should accept an *optional* `changeset`.
- All changesets are typed and validated against canonical statement models (`models.py`).
- Patch calculation is fast; layered overlays (undo/redo) are lightweight.
- Test edge cases for modifications/removals where multiple policies/statements may share labels, but not unique IDs.

---

## 7. References

- Data Models: [`src/oci_policy_analysis/common/models.py`](../../../src/oci_policy_analysis/common/models.py)
- Repository/Filtering: [`src/oci_policy_analysis/logic/data_repo.py`](../../../src/oci_policy_analysis/logic/data_repo.py)

---