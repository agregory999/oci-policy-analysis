# Project-Specific Context: Pluggable Intelligence Strategies

This file describes the pluggable intelligence strategy pattern used by the Policy Intelligence Engine and how to add a new check or strategy.

---

## 1. Overview

- **IntelligenceStrategy** (protocol in `logic/intelligence_strategies/base.py`):  
  Contract for a single analytics “strategy” that runs on the policy repository and writes results into the overlay.
- **PolicyIntelligenceEngine** (`logic/policy_intelligence.py`):  
  Holds a registry of strategies and runs them in a fixed order via `run_all(enabled_strategy_ids=None, params=None)`.
- **Settings** (“Recommendation / Consolidation”):  
  User can enable/disable each strategy via checkboxes; the list is persisted as `enabled_intelligence_checks` (list of strategy_ids; `None` or `[]` = all enabled).
- **Recommendations tab**:  
  Calls `policy_intelligence.run_all(enabled_strategy_ids=..., params=...)` with params (e.g. risk reduction %, consolidation strategy names for workbench cross-link).

The same coding standards and pattern as the **Consolidation Workbench** strategies apply: protocol in base, implementations in separate modules, engine does not depend on concrete classes in its public API.

---

## 2. Strategy Protocol and Overlay Contract

Each strategy has:

- **strategy_id** (str): Unique machine-readable id (e.g. `'risk_scores'`, `'invalid_statements'`). Used in settings and run order.
- **display_name** (str): Human-readable name for Settings checkboxes and UI.
- **category** (str): One of `'risk'`, `'overlap'`, `'cleanup'`, `'consolidation_suggestion'`, `'recommendation'`. Used for grouping and run order.
- **run(repo, overlay, params)** (method): Runs the strategy and mutates `overlay`. Receives `params` (e.g. `where_clause_reduction_pct`, `engine` reference for compartment index, `consolidation_strategy_names`).

Overlay keys by category:

| Category                 | Overlay key / shape |
|--------------------------|---------------------|
| risk                     | `overlay['risk_scores']` (list of dicts) |
| overlap                  | `overlay['overlaps']` (list) |
| cleanup                  | `overlay.setdefault('cleanup_items', {})[strategy_id] = ...` (one key per cleanup strategy) |
| consolidation_suggestion | `overlay['consolidations']` (list of dicts) |
| recommendation           | `overlay['recommendations']` (list of dicts) |

Run order is fixed in the engine (`DEFAULT_STRATEGY_RUN_ORDER`) so that e.g. cleanup runs before recommendations (recommendations aggregate cleanup and consolidation).

---

## 3. How to Add a New Intelligence Check

1. **Implement the strategy**
   - Create a new module under `logic/intelligence_strategies/` (e.g. `cleanup_my_check.py`).
   - Implement the `IntelligenceStrategy` protocol: `strategy_id`, `display_name`, `category`, and `run(repo, overlay, params)`.
   - For cleanup: write to `overlay.setdefault('cleanup_items', {})[self.strategy_id] = <list>`.
   - For other categories: write to the appropriate overlay key (see table above).
   - Use the same style (dataclass, docstrings, logger) as existing strategies in `logic/intelligence_strategies/`.

2. **Register the strategy**
   - In `logic/intelligence_strategies/__init__.py`:
     - Import the new strategy class.
     - Add an instance to the list returned by `get_default_intelligence_strategies()` in the correct position (e.g. cleanup strategies together, before `OverallRecommendationStrategy`).
   - Add the new `strategy_id` to `DEFAULT_STRATEGY_RUN_ORDER` in `logic/policy_intelligence.py` in the desired position.

3. **Settings**
   - The Settings tab builds checkboxes from `policy_intelligence.get_strategies_for_settings()`, which returns all registered strategies in run order. No hand-wiring needed: the new strategy will appear as a checkbox in “Recommendation / Consolidation” once registered.

4. **Recommendations tab**
   - If the new strategy writes to an existing overlay key (e.g. `cleanup_items[my_check]`), the existing Cleanup/Fix tab logic that iterates over `cleanup.get('invalid_statements', [])`, etc. will need to handle the new key (e.g. add a branch in `_get_cleanup_issues()` for `cleanup.get('my_check', [])` and the columns/labels for that type).
   - If the new strategy introduces a new overlay key or subtab, add the corresponding table/section and read from that key.

5. **Optional: discovery**
   - To avoid editing `__init__.py` for every new strategy, you could add a registry pattern (e.g. strategies register themselves via a decorator or entry point). The current design keeps the default list explicit in `get_default_intelligence_strategies()`.

---

## 4. Consolidation Workbench Cross-Link

- When consolidation opportunities are present, the overall recommendations strategy adds a recommendation that directs the user to the **Consolidation Workbench** and suggests strategy names (e.g. “Consider **Move to Root Compartment** or **Statement Density (Pack Policies)**”).
- Strategy names are passed into the engine via `params['consolidation_strategy_names']`, which the recommendations tab sets from `app.consolidation_engine.get_strategy_display_names()` so the intelligence layer does not depend on the consolidation engine instance.

---

## 5. Key Files

| Purpose              | Path |
|----------------------|------|
| Protocol             | `logic/intelligence_strategies/base.py` |
| Default strategy list | `logic/intelligence_strategies/__init__.py` (get_default_intelligence_strategies) |
| Run order            | `logic/policy_intelligence.py` (DEFAULT_STRATEGY_RUN_ORDER) |
| Engine registry      | `logic/policy_intelligence.py` (run_all, register_strategy, get_strategies_for_settings) |
| Settings UI          | `ui/settings_tab.py` (“Recommendation / Consolidation” frame) |
| Invocation           | `ui/policy_recommendations_tab.py` (reload_all_analytics → run_all) |
