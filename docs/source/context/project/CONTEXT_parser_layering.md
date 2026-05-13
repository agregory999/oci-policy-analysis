# Parser Layering and Division of Labor

This note defines the intended parser responsibilities during the modular refactor.

## Layers

### 1) Generated parser artifacts (ANTLR)
- Location: `src/oci_policy_analysis/logic/parsers/**`
- Includes:
  - `.g4` grammars
  - generated lexer/parser/visitor/listener modules
- Responsibility:
  - Syntax tree generation only
  - No application orchestration or service coupling

### 2) Parser implementation helpers (logic)
- Location: `src/oci_policy_analysis/logic/`
  - `policy_statement_normalizer.py`
  - `policy_subject_parser.py`
  - `condition_evaluator.py`
- Responsibility:
  - ANTLR-driven parsing/normalization/evaluation behavior
  - Backward-compatible implementation while migration is in progress

### 3) Stable parser contracts (application core)
- Location: `src/oci_policy_analysis/application/core/parser/**`
- Responsibility:
  - Export stable parser-facing APIs consumed by services/engines/UI/web/MCP
  - Isolate callers from direct dependency on grammar/generated layout

## Current contract exports

- `application.core.parser` exports:
  - `PolicyStatementNormalizer`
  - `parse_policy_subjects`
  - `evaluate_condition_clause`
  - `extract_variable_names`
  - `format_policy_clause`
  - `collect_tag_conditions`
  - `TagCondition`

## Migration rule of thumb

- New service/engine code should import parser contracts from:
  - `oci_policy_analysis.application.core.parser`
- Direct imports from `logic.parsers.*` should be limited to parser implementation modules only.
