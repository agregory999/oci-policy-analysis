# Project Context: Parsing Architecture and Usage

This document describes the current parsing architecture, package relationships, and recommended usage patterns during the modular refactor.

---

## 1) Goals of the parsing refactor

- Keep ANTLR grammar/generated code isolated as implementation detail.
- Expose stable parser APIs through `application.core` so MCP/CLI/UI/Web depend on core contracts.
- Prevent consumer code from coupling directly to generated parser module paths.
- Enable future internal parser reorganization without broad import churn.

---

## 2) Package structure and division of labor

### A. Generated parser artifacts (ANTLR)

- Path: `src/oci_policy_analysis/logic/parsers/**`
- Contains:
  - `.g4` grammar files
  - generated lexer/parser/listener/visitor files
- Role:
  - Parse tree generation and low-level grammar artifacts only
  - Not intended as direct import surface for services/UI/web/mcp

### B. Parser implementation helpers (logic)

- Path examples:
  - `src/oci_policy_analysis/logic/policy_statement_normalizer.py`
  - `src/oci_policy_analysis/logic/policy_subject_parser.py`
  - `src/oci_policy_analysis/logic/condition_evaluator.py`
- Role:
  - Existing parser/normalization/evaluation implementations
  - Backward-compatible implementation layer during migration

### C. Stable parser contracts (application core)

- Path: `src/oci_policy_analysis/application/core/parser/**`
- Role:
  - Canonical import surface for parser behavior used by higher layers
  - Shields consumers from implementation/generator path changes

Current contract modules:

- `application/core/parser/condition_evaluator.py`
- `application/core/parser/policy_statement_normalizer.py`
- `application/core/parser/policy_subject_parser.py`
- `application/core/parser/tag_condition_collector.py`
- `application/core/parser/__init__.py` (aggregated exports)

---

## 3) Canonical imports (what to use)

Preferred import style:

```python
from oci_policy_analysis.application.core.parser import (
    PolicyStatementNormalizer,
    parse_policy_subjects,
    evaluate_condition_clause,
    extract_variable_names,
    format_policy_clause,
    collect_tag_conditions,
    TagCondition,
)
```

Avoid in service/engine/UI/web code:

- `from oci_policy_analysis.logic.parsers...`
- Direct imports of generated lexer/parser/visitor classes outside parser implementation modules

---

## 4) Relationship between parser layers

Flow (current state):

1. Consumers (services/engines/UI/web/mcp) import from `application.core.parser`.
2. Core parser facades delegate to logic parser implementations.
3. Logic implementations use ANTLR-generated modules under `logic/parsers`.

This keeps consumer-facing dependencies stable while parser internals evolve.

---

## 5) Practical usage patterns

### Condition clause evaluation

```python
from oci_policy_analysis.application.core.parser import evaluate_condition_clause

allowed, details = evaluate_condition_clause(clause, variables, return_structured=True)
```

### Extract variables from where clause

```python
from oci_policy_analysis.application.core.parser import extract_variable_names

names = extract_variable_names(clause)
```

### Normalize policy statements

```python
from oci_policy_analysis.application.core.parser import PolicyStatementNormalizer

normalizer = PolicyStatementNormalizer()
normalized = normalizer.normalize(statement_text, statement_type, base_fields)
```

### Collect tag conditions

```python
from oci_policy_analysis.application.core.parser import collect_tag_conditions

structure, conditions = collect_tag_conditions(where_clause)
```

---

## 6) Current migration status

- Parser contracts are established in `application.core.parser`.
- Key consumers (services/engines/UI tag analysis) are migrated to core parser imports.
- Direct non-parser-module imports of `logic.parsers.*` have been removed.

Remaining direct `logic.parsers.*` usage is intentionally limited to:

- parser implementation modules in `logic/*`
- adapter/facade modules in `application/core/parser/*`

---

## 7) Development rules going forward

1. **New consumer code** must import parser behavior from `application.core.parser`.
2. ANTLR grammar updates/regeneration should not require service/UI import changes.
3. If parser behavior expands, add/extend a core parser facade first.
4. Keep generated parser classes out of UI/service boundary code.
