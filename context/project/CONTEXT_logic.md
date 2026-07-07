# Project-Specific Project-Specific Context: Logic/Business Layer

This document provides an overview, history, and customized development standards for the logic (business rules, data processing, analysis engines) specific to the current project.

---

## 1. Area Overview

The logic layer processes OCI policy data, parses statements, normalizes conditions, manages data repositories, and contains the main analytical engines. Modules are under `src/oci_policy_analysis/logic/`.

---

## 2. Evolution Timeline and Major Changes

| Date      | Commit Hash | Change Summary                        | Modules Impacted          |
|-----------|-------------|---------------------------------------|---------------------------|
| 2026-01-08 | a2ae328d    | Merge Policy Intelligence Engine      | policy_intelligence.py, policy_statement_normalizer.py, data_repo.py |
| ...       | ...         | ...                                   | ...                       |

_(Expand this table with key merges/features/history as development continues. Use `git log` to backfill major events.)_

---

## 3. Local Coding Standards & Practices

- New analytical engines must live under `logic/` and be initialized via `main.py`
- All logic modules should use clear type annotations and meaningful docstrings
- Primary data flow should avoid side effects, emphasize testability (see `src/test/`)

---

## 4. Exceptions/Overrides from Generic Patterns

- Use project-defined interfaces and patterns even if they diverge from the generic baseline
- Each data repository or parser must register with main on initialization

---

For generic Python/coding rules, refer to [../generic/GENERIC_CODING_STANDARDS.md](../generic/GENERIC_CODING_STANDARDS.md).
