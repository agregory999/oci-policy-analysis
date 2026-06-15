"""Dependency wiring for FastAPI routes."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from oci_policy_analysis._version import get_app_version
from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.core.support.usage_tracking import init_usage_tracker


def _resolve_app_version() -> str:
    """Resolve package version for usage tracking documents."""

    return get_app_version()


@lru_cache(maxsize=1)
def get_settings() -> dict[str, Any]:
    """Return settings for the web app.

    Loads persisted settings from the shared config file.
    """

    settings = config.load_settings()
    if 'usage_tracking_enabled' not in settings:
        settings['usage_tracking_enabled'] = True
        try:
            config.save_settings(settings)
        except Exception:
            pass
    return settings


@lru_cache(maxsize=1)
def get_context() -> AppContext:
    """Singleton AppContext for FastAPI routes."""
    settings = get_settings()
    # Ensure usage tracker is initialized in web runtime when enabled.
    # Desktop initializes this in main.App, but web has separate startup wiring.
    init_usage_tracker(settings, _resolve_app_version())
    return AppContext.from_settings(settings)
