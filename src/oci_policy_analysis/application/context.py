"""Shared application context for orchestrated services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from oci_policy_analysis.application.services.cache_service import CacheService
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService
from oci_policy_analysis.application.services.settings_service import SettingsService
from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.logic.ai_repo import AI
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine


@dataclass
class AppContext:
    """Container for shared repositories and engines.

    This context is the primary dependency passed into application services and
    can be constructed from settings or custom configuration.
    """

    settings: dict[str, Any]
    policy_repo: PolicyAnalysisRepository
    reference_data: ReferenceDataRepo
    intelligence: PolicyIntelligenceEngine
    simulation: PolicySimulationEngine
    cache: CacheManager
    ai: AI
    cache_service: CacheService
    settings_service: SettingsService
    reference_data_service: ReferenceDataService
    logging_service: LoggingService
    status: dict[str, Any] = field(default_factory=dict)

    def set_status(self, *, stage: str, detail: str | None = None, state: str = 'idle') -> None:
        """Update shared status for web consumers."""
        self.status = {
            'stage': stage,
            'detail': detail or '',
            'state': state,
            'updated_at': datetime.now(UTC).isoformat(),
        }

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> AppContext:
        """Create a new context using current settings.

        This mirrors existing wiring in main.py but keeps it reusable for
        non-Tk consumers.
        """

        reference_data = ReferenceDataRepo()
        reference_data.load_data()

        policy_repo = PolicyAnalysisRepository()
        # Inject settings and reference data for existing repo behavior.
        # These attributes are currently attached dynamically in main.py.
        policy_repo.settings = settings
        policy_repo.permission_reference_repo = reference_data

        ai = AI()
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
            ai=ai,
            cache_service=cache_service,
            settings_service=settings_service,
            reference_data_service=reference_data_service,
            logging_service=logging_service,
        )
