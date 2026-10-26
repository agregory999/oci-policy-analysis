"""Shared post-load orchestration helpers for application consumers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpusBuilder
from oci_policy_analysis.application.core.engine import (
    PolicyCorpusBuilder,
    PolicyIntelligenceEngine,
    PolicySimulationEngine,
)
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.settings_service import (
    DEFAULT_SERVICE_PRINCIPAL_REDUCTION_PCT,
    DEFAULT_WHERE_CLAUSE_REDUCTION_PCT,
)

LOGGER = get_logger(component='post_load')


def run_minimal_post_load_enrichment(
    context: AppContext,
    *,
    on_stage: Callable[[str, str, str], None] | None = None,
) -> None:
    """Rebuild the foundations needed for focused snapshot queries.

    Args:
        context: Loaded context to enrich in place.
        on_stage: Optional callback receiving stage, detail, and state strings.
            Callback exceptions propagate to the caller.

    Notes:
        Replaces the intelligence engine, calculates effective paths and validity,
        marks dynamic-group usage, resolves cross-tenancy aliases, and builds both
        corpora. Attaches the regular corpus to the existing simulation engine.
        Does not run the full recommendation strategies or project a permissions
        report. No OCI refresh occurs here; results reflect the loaded repository.
        Call through LoadService when progress should also update context.status.
    """

    def _emit(stage: str, detail: str, state: str = 'running') -> None:
        if callable(on_stage):
            on_stage(stage, detail, state)

    repo = context.policy_repo
    context.cross_tenancy_corpus = None
    LOGGER.info('Running minimal post-load enrichment: effective paths, invalid statements, dynamic-group usage')
    _emit('Preparing Enrichment', 'Initializing policy intelligence engine')

    context.intelligence = PolicyIntelligenceEngine(repo)
    _emit('Calculating Effective Paths', 'Computing effective path and principal-key foundations')
    context.intelligence.calculate_all_effective_compartments()

    _emit('Validating Statements', 'Checking invalid policy statements')
    context.intelligence.find_invalid_statements()

    _emit('Analyzing Dynamic Groups', 'Marking dynamic groups referenced by policy statements')
    context.intelligence.run_dg_in_use_analysis()

    _emit('Building Cross-Tenancy Corpus', 'Resolving aliases and preserving cross-tenancy sources')
    context.intelligence.resolve_cross_tenancy_aliases()
    context.cross_tenancy_corpus = CrossTenancyCorpusBuilder().build(repo)

    _emit('Building Policy Corpus', 'Compiling valid authorization facts')
    context.corpus = PolicyCorpusBuilder().build(repo)
    if context.simulation is not None:
        context.simulation.set_corpus(context.corpus)

    _emit('Enrichment Complete', 'Minimal post-load enrichment is ready', 'success')
    LOGGER.info('Minimal post-load enrichment completed successfully')


def run_post_load_pipeline(
    context: AppContext,
    *,
    on_stage: Callable[[str, str, str], None] | None = None,
) -> None:
    """Rebuild full intelligence, corpora, reports, and simulation state.

    Args:
        context: Loaded context to enrich in place using its active settings.
        on_stage: Optional callback receiving stage, detail, and state strings.
            Callback exceptions propagate to the caller.

    Notes:
        Replaces the intelligence engine, applies configured strategies and risk
        parameters, builds cross-tenancy and regular corpora, projects the permissions
        report, and replaces the simulation engine. Existing simulation/prospective
        state is not preserved. Some strategies can use available OCI clients.
        This mutates the context incrementally; failures do not roll back earlier
        stages. It analyzes the current snapshot, not OCI-authoritative access.
        Call through LoadService when progress should also update context.status.
    """

    def _emit(stage: str, detail: str, state: str = 'running') -> None:
        if callable(on_stage):
            on_stage(stage, detail, state)

    repo = context.policy_repo
    context.cross_tenancy_corpus = None
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
    context.intelligence.run_all(
        enabled_strategy_ids=enabled_strategy_ids,
        params=risk_params,
        on_stage=lambda detail: _emit('Running Intelligence', detail),
    )
    _emit('Building Cross-Tenancy Corpus', 'Compiling cross-tenancy sources and relationships')
    context.cross_tenancy_corpus = CrossTenancyCorpusBuilder().build(
        repo, context.intelligence.overlay.get('cross_tenancy_findings', [])
    )

    _emit('Building Policy Corpus', 'Compiling valid authorization facts')
    context.corpus = PolicyCorpusBuilder().build(repo)

    _emit('Building Permissions Report', 'Projecting effective permissions from policy corpus')
    context.intelligence.build_permissions_report(context.corpus)

    _emit('Refreshing Simulation Engine', 'Rebuilding simulation engine against active dataset')
    context.simulation = PolicySimulationEngine(
        policy_repo=repo,
        ref_data_repo=context.reference_data,
        corpus=context.corpus,
    )
    _emit('Intelligence Complete', 'Post-load intelligence and permissions report are ready', 'success')
    LOGGER.info('Post-load pipeline completed successfully')
