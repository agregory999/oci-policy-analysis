## Consolidation Strategy Modularity (Application Core)

### Purpose

This context explains how consolidation planning strategies are modularized so
engine behavior stays pluggable while package ownership moves from `logic/*`
to `application/core/*`.

### Canonical package

Built-in strategy protocol and implementations now live under:

- `oci_policy_analysis.application.core.engine.strategies`

Key modules:

- `base.py` – `Strategy` protocol (contract-only)
- `statement_density.py` – `PackPoliciesByStatementDensity`
- `move_to_root.py` – `MoveToRootCompartment`
- `move_closer_to_target.py` – `MoveCloserToTargetCompartment`
- `move_into_target.py` – `MoveIntoTargetCompartment`

### Engine coupling pattern

`ConsolidationEngine` depends on strategy interfaces/implementations through
the application-core package and preserves runtime pluggability via:

- `register_strategy(strategy)`
- `register_strategies([...])`
- constructor injection: `ConsolidationEngine(..., strategies=[...])`

This keeps strategy logic modular and replaceable without changing engine core.

### Compatibility policy during migration

Legacy import paths under `logic/consolidation_strategies/*` are retained as
thin shims that re-export from `application.core.engine.strategies`.

This ensures backward compatibility for:

- tests
- any remaining legacy imports
- external/internal extension points not yet migrated

Planned removal of shims is Phase 5 of the modular refactor.

### Helper boundaries

Strategy/helper shared utilities are now owned by:

- `application/core/common/consolidation_helpers.py`

Legacy `logic/consolidation_helpers.py` remains a strict re-export shim.

### Recent consolidation tightening (proposal + execution clarity)

Recent updates tightened proposal generation and execution guidance behavior
without changing the core strategy contract:

- **Canonical proposal row schema** now uses shared snake_case fields
  (`index`, `action`, `policy_name`, `details`, `status`, etc.) across service,
  web, and Tk flows, while preserving legacy display-key aliases for history
  backward compatibility.
- **Location rewrite logic** is centralized in
  `rewrite_statement_location_clause(...)` in
  `application/core/common/consolidation_helpers.py` and reused by all built-in
  strategies (`statement_density`, `move_to_root`, `move_closer_to_target`,
  `move_into_target`).
- **Progress semantics** for non-live datasets return persisted progress
  snapshots (when available) with consistent `executed`, `total`, and
  `completed` indicators, rather than flattening to zero-only no-op responses.
- **Script/instruction rendering** prepends a compact shared plan summary block
  (effort id, strategy, step count, step outline) before CLI/UI execution text
  to make generated guidance easier to review and validate.

### Extension guidance

To add a new strategy:

1. Implement `Strategy` protocol in `application/core/engine/strategies/<name>.py`
2. Register it in `ConsolidationEngine` (constructor list or `register_strategy`)
3. Optionally export in `application/core/engine/strategies/__init__.py`
4. Keep strategy-specific helper logic isolated; shared helper behavior belongs
   in `application/core/common/consolidation_helpers.py`

### Validation expectations

Every strategy-packaging move should keep this sequence green:

1. Targeted regression suite
2. CLI startup smoke (`python -m oci_policy_analysis.cli --help`)
3. MCP startup smoke (`python -m oci_policy_analysis.mcp_server --help`)
