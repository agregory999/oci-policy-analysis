"""Shared post-load orchestration helpers for application consumers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.engine import (
    PolicyIntelligenceEngine,
    PolicySimulationEngine,
)
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.settings_service import (
    DEFAULT_SERVICE_PRINCIPAL_REDUCTION_PCT,
    DEFAULT_WHERE_CLAUSE_REDUCTION_PCT,
)

LOGGER = get_logger(component='post_load')


def run_post_load_pipeline(
    context: AppContext,
    *,
    on_stage: Callable[[str, str, str], None] | None = None,
) -> None:
    """Rebuild intelligence/simulation state after policy data loads.

    Args:
        context: Shared application context containing repo and engine state.
        on_stage: Optional stage callback used to emit progress details.

    Returns:
        None
    """

    def _emit(stage: str, detail: str, state: str = 'running') -> None:
        if callable(on_stage):
            on_stage(stage, detail, state)

    repo = context.policy_repo
    LOGGER.info('Running post-load pipeline: rebuilding intelligence and simulation engines')
    _emit('Preparing Intelligence', 'Initializing policy intelligence engine')

    context.intelligence = PolicyIntelligenceEngine(repo)
    _emit('Calculating Effective Paths', 'Computing effective path and principal-key foundations')
    context.intelligence.calculate_all_effective_compartments()

    enabled_ids = context.settings.get('enabled_intelligence_checks')
    enabled_strategy_ids = enabled_ids if isinstance(enabled_ids, list) and enabled_ids else None

    def _coerce_pct(value: Any, default: int) -> int:
        allowed = {0, 25, 50, 75, 90}
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return parsed if parsed in allowed else default

    risk_params = {
        'where_clause_reduction_pct': _coerce_pct(
            context.settings.get('risk_where_clause_reduction_pct'),
            DEFAULT_WHERE_CLAUSE_REDUCTION_PCT,
        ),
        'service_principal_reduction_pct': _coerce_pct(
            context.settings.get('risk_service_principal_reduction_pct'),
            DEFAULT_SERVICE_PRINCIPAL_REDUCTION_PCT,
        ),
    }
    LOGGER.info(
        'Running intelligence with risk reductions: where_clause=%s%% service_principal=%s%%',
        risk_params['where_clause_reduction_pct'],
        risk_params['service_principal_reduction_pct'],
    )

    _emit('Running Intelligence', 'Executing enabled intelligence strategies')
    context.intelligence.run_all(enabled_strategy_ids=enabled_strategy_ids, params=risk_params)

    _emit('Building Permissions Report', 'Generating in-memory permissions report model')
    context.intelligence.build_permissions_report()

    _emit('Refreshing Simulation Engine', 'Rebuilding simulation engine against active dataset')
    context.simulation = PolicySimulationEngine(policy_repo=repo, ref_data_repo=context.reference_data)
    _emit('Intelligence Complete', 'Post-load intelligence and permissions report are ready', 'success')
    LOGGER.info('Post-load pipeline completed successfully')
