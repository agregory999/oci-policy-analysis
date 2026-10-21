"""Shared application context for orchestrated services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpus
from oci_policy_analysis.application.core.engine import (
    PolicyCorpus,
    PolicyIntelligenceEngine,
    PolicySimulationEngine,
)
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository, ReferenceDataRepo
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.core.support.logger import set_component_level, set_log_level
from oci_policy_analysis.application.services.cache_service import CacheService
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService
from oci_policy_analysis.application.services.settings_service import SettingsService


@dataclass
class AppContext:
    """Shared mutable runtime state for one active analysis snapshot.

    Construct with explicit dependencies or use ``from_settings`` for the standard
    wiring. The factory loads bundled reference data, but does not collect OCI
    IAM/policies or compile a corpus. Use LoadService before querying the snapshot.

    Attributes:
        settings: Active configuration dictionary, shared with settings services.
        policy_repo: Repository retaining source data and derived statement fields.
        reference_data: Bundled resource, permission, and API-operation mappings.
        intelligence: Engine holding validation findings and intelligence overlays.
        simulation: Engine for request-context analysis and prospective statements.
        cache: Persistent repository snapshot manager.
        cache_service: Cache import/export operations over the snapshot manager.
        settings_service: Settings access and persistence facade.
        reference_data_service: Query facade for bundled reference mappings.
        logging_service: Global and component logging configuration facade.
        status: Latest progress stage, detail, state, and UTC update timestamp.
        corpus: Compiled regular policy facts, or None before enrichment.
        cross_tenancy_corpus: Cross-tenancy sources/relationships, or None before enrichment.

    Notes:
        Loads replace derived engines and corpora. Consumers should read the current
        context after each load rather than retaining an old engine or corpus.
        Context state is not an OCI-authoritative authorization service or an
        automatic synchronization boundary for concurrent loads and queries.
    """

    settings: dict[str, Any]
    policy_repo: PolicyAnalysisRepository
    reference_data: ReferenceDataRepo
    intelligence: PolicyIntelligenceEngine
    simulation: PolicySimulationEngine
    cache: CacheManager
    cache_service: CacheService
    settings_service: SettingsService
    reference_data_service: ReferenceDataService
    logging_service: LoggingService
    status: dict[str, Any] = field(default_factory=dict)
    corpus: PolicyCorpus | None = None
    cross_tenancy_corpus: CrossTenancyCorpus | None = None

    def set_status(self, *, stage: str, detail: str | None = None, state: str = 'idle') -> None:
        """Replace the latest progress status for adapters and integrations.

        Args:
            stage: Human-readable operation stage.
            detail: Optional progress description; None is stored as an empty string.
            state: Adapter-facing state such as idle, running, success, or error.

        Notes:
            Adds a UTC timestamp. This records only the latest status, not an event log.
        """
        self.status = {
            'stage': stage,
            'detail': detail or '',
            'state': state,
            'updated_at': datetime.now(UTC).isoformat(),
        }

    @classmethod
    def from_settings(cls, settings: dict[str, Any], *, verbose_override: bool | None = None) -> AppContext:
        """Construct standard repositories, engines, and service wiring.

        Args:
            settings: Active configuration; retained by reference rather than copied.
            verbose_override: Explicit runtime logging lock. False applies saved
                levels exactly; None retains legacy root-DEBUG inference.

        Returns:
            AppContext: An unloaded runtime with bundled reference data and no corpus.

        Notes:
            Applies saved global/component logging levels as a process-wide side effect.
            Does not authenticate to OCI, load a tenancy/cache, or run post-load analysis.
        """

        # Apply persisted logging settings at startup for web/non-Tk flows.
        # Without this, root logger remains at default INFO from logger setup.
        runtime_options = {} if verbose_override is None else {'verbose_override': verbose_override}
        set_log_level(str(settings.get('global_log_level', 'WARNING')), **runtime_options)
        component_levels = settings.get('log_levels', {})
        if isinstance(component_levels, dict):
            for component, level in component_levels.items():
                if not component:
                    continue
                set_component_level(str(component), str(level), **runtime_options)

        reference_data = ReferenceDataRepo()
        reference_data.load_data()

        policy_repo = PolicyAnalysisRepository()
        # Inject settings and reference data for existing repo behavior.
        # These attributes are currently attached dynamically in main.py.
        cast(Any, policy_repo).settings = settings
        cast(Any, policy_repo).permission_reference_repo = reference_data

        simulation = PolicySimulationEngine(policy_repo=policy_repo, ref_data_repo=reference_data)
        intelligence = PolicyIntelligenceEngine(policy_repo)

        cache = CacheManager()
        cache_service = CacheService(cache=cache)
        settings_service = SettingsService(settings=settings)
        reference_data_service = ReferenceDataService(reference_data=reference_data)
        logging_service = LoggingService(settings=settings)

        return cls(
            settings=settings,
            policy_repo=policy_repo,
            reference_data=reference_data,
            intelligence=intelligence,
            simulation=simulation,
            cache=cache,
            cache_service=cache_service,
            settings_service=settings_service,
            reference_data_service=reference_data_service,
            logging_service=logging_service,
        )
