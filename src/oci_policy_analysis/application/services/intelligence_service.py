"""Service facade for policy intelligence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support.logger import get_logger


@dataclass
class IntelligenceResult:
    """Result wrapper for intelligence overlay runs."""

    overlay: dict[str, Any]


class IntelligenceService:
    """Run intelligence overlays without UI coupling."""

    def __init__(self, context: AppContext) -> None:
        """Initialize the intelligence service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='intelligence_service')

    def run_all(
        self, *, enabled_strategy_ids: list[str] | None = None, params: dict | None = None
    ) -> IntelligenceResult:
        """Run configured intelligence strategies and refresh overlay data.

        Args:
            enabled_strategy_ids: Optional subset of strategy identifiers.
            params: Optional strategy parameter map.

        Returns:
            IntelligenceResult: Latest overlay data after processing.
        """
        self.logger.info('Running intelligence overlay via IntelligenceService')
        engine = self.context.intelligence
        engine.calculate_all_effective_compartments()
        engine.run_all(enabled_strategy_ids=enabled_strategy_ids, params=params or {})
        engine.build_permissions_report()
        self.logger.info('Intelligence run complete: strategy_count=%s', len(enabled_strategy_ids or []))
        return IntelligenceResult(overlay=getattr(engine, 'overlay', {}) or {})

    def get_overlay(self) -> dict[str, Any]:
        """Return currently cached intelligence overlay data.

        Returns:
            dict[str, Any]: Overlay payload from the intelligence engine.
        """
        self.logger.info('Fetching intelligence overlay via IntelligenceService')
        return getattr(self.context.intelligence, 'overlay', {}) or {}
