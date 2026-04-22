"""Shared post-load orchestration helpers for application consumers."""

from __future__ import annotations

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine

LOGGER = get_logger(component='post_load')


def run_post_load_pipeline(context: AppContext) -> None:
    """Rebuild intelligence/simulation state after policy data loads.

    Args:
        context: Shared application context containing repo and engine state.

    Returns:
        None
    """
    repo = context.policy_repo
    LOGGER.info('Running post-load pipeline: rebuilding intelligence and simulation engines')

    context.intelligence = PolicyIntelligenceEngine(repo)
    context.intelligence.calculate_all_effective_compartments()
    context.intelligence.run_all(enabled_strategy_ids=None, params={})
    context.intelligence.build_permissions_report()

    context.simulation = PolicySimulationEngine(policy_repo=repo, ref_data_repo=context.reference_data)
    LOGGER.info('Post-load pipeline completed successfully')
