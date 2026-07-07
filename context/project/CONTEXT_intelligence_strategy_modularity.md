## Intelligence Strategy Modularity (Application Core)

### Purpose

This context captures how policy intelligence checks/recommendations are kept
modular while migrating ownership from `logic/intelligence_strategies/*` to
`application/core/engine/intelligence_strategies/*`.

### Canonical package

Intelligence strategy protocol + built-ins now live under:

- `oci_policy_analysis.application.core.engine.intelligence_strategies`

Primary modules:

- `base.py` – `IntelligenceStrategy` protocol
- `risk.py` – `RiskScoreStrategy`
- `overlap.py` – `OverlapStrategy`
- `consolidation_suggestion.py` – `ConsolidationSuggestionStrategy`
- cleanup strategies (`cleanup_*`)
- `recommendations.py` – `OverallRecommendationStrategy`
- `__init__.py` – default strategy registry (`get_default_intelligence_strategies`)

### Engine coupling model

`PolicyIntelligenceEngine` remains strategy-driven and modular:

- constructor strategy injection: `PolicyIntelligenceEngine(..., strategies=[...])`
- dynamic registration: `register_strategy(...)`
- controlled execution order via internal `_run_order`
- registry discovery for settings UI via `get_strategies_for_settings()`

### Compatibility during migration

Legacy imports remain supported via strict shims in:

- `logic/intelligence_strategies/*`

Shims re-export from application-core package and are slated for removal in
Phase 5 once all consumers are migrated.

### Extension guidance

To add a new intelligence strategy:

1. Implement `IntelligenceStrategy` in
   `application/core/engine/intelligence_strategies/<name>.py`
2. Add it to `get_default_intelligence_strategies()` if it should run by default
3. Ensure `strategy_id`, `display_name`, and `category` are stable
4. Keep strategy logic independent of UI/web consumers; rely on repository + overlay

### Validation expectations

For each intelligence strategy packaging move:

1. Targeted regression suite must pass
2. CLI startup smoke must pass
3. MCP startup smoke must pass
