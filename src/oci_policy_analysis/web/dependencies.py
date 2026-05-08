"""Dependency wiring for FastAPI routes."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.common import config


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

    return AppContext.from_settings(get_settings())
