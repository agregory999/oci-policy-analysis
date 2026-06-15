"""Service facade for loading and persisting settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.core.support.logger import get_logger

DEFAULT_WHERE_CLAUSE_REDUCTION_PCT = 50
DEFAULT_SERVICE_PRINCIPAL_REDUCTION_PCT = 50


def _coerce_pct(value: Any, default: int) -> int:
    """Normalize percentage-like values to supported risk reduction options."""
    allowed = {0, 25, 50, 75, 90}
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed in allowed else default


@dataclass
class SettingsService:
    """Centralize settings persistence for UI and API consumers."""

    settings: dict[str, Any]

    def __post_init__(self) -> None:
        """Initialize logger after dataclass construction.

        Returns:
            None
        """
        self.logger = get_logger(component='settings_service')

    @classmethod
    def load(cls) -> SettingsService:
        """Load persisted settings into a service instance.

        Returns:
            SettingsService: Service initialized with persisted settings.
        """
        return cls(settings=config.load_settings())

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Apply a partial settings update.

        Args:
            updates: Settings values to merge.

        Returns:
            dict[str, Any]: Updated settings dictionary.
        """
        self.logger.info('Updating settings keys=%s', sorted(updates.keys()))
        self.settings.update(updates)
        return self.settings

    def set(self, key: str, value: Any, *, autosave: bool = False) -> dict[str, Any]:
        """Set a single settings key.

        Args:
            key: Setting name.
            value: Setting value.
            autosave: Whether to persist immediately.

        Returns:
            dict[str, Any]: Updated settings dictionary.
        """
        self.settings[key] = value
        if autosave:
            self.save()
        return self.settings

    def bulk_update(self, updates: dict[str, Any], *, autosave: bool = False) -> dict[str, Any]:
        """Apply multiple settings updates.

        Args:
            updates: Settings values to merge.
            autosave: Whether to persist immediately.

        Returns:
            dict[str, Any]: Updated settings dictionary.
        """
        self.logger.info('Bulk updating settings keys=%s', sorted(updates.keys()))
        self.settings.update(updates)
        if autosave:
            self.save()
        return self.settings

    def save(self) -> None:
        """Persist current settings to storage.

        Returns:
            None
        """
        self.logger.info('Saving settings to persistent storage')
        config.save_settings(self.settings)

    def get(self) -> dict[str, Any]:
        """Return current in-memory settings.

        Returns:
            dict[str, Any]: In-memory settings dictionary.
        """
        return self.settings

    def get_risk_reduction_settings(self) -> dict[str, int]:
        """Return normalized risk reduction settings used by intelligence runs."""
        where_pct = _coerce_pct(
            self.settings.get('risk_where_clause_reduction_pct'),
            DEFAULT_WHERE_CLAUSE_REDUCTION_PCT,
        )
        service_pct = _coerce_pct(
            self.settings.get('risk_service_principal_reduction_pct'),
            DEFAULT_SERVICE_PRINCIPAL_REDUCTION_PCT,
        )
        return {
            'where_clause_reduction_pct': where_pct,
            'service_principal_reduction_pct': service_pct,
        }
