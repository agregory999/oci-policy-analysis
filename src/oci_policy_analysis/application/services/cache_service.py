"""Service facade for cache persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.core.support.logger import get_logger


@dataclass
class CacheService:
    """Expose cache operations to UI/API without direct CacheManager usage."""

    cache: CacheManager

    def __post_init__(self) -> None:
        """Initialize logger after dataclass construction.

        Returns:
            None
        """
        self.logger = get_logger(component='cache_service')

    def list_caches(self, tenancy_name: str | None = None) -> list[str]:
        """List available cache names.

        Args:
            tenancy_name: Optional tenancy name filter.

        Returns:
            list[str]: Cache names matching the filter.
        """
        self.logger.info('Listing caches: tenancy_name=%s', tenancy_name or '')
        return self.cache.get_available_cache(tenancy_name)

    def get_preserved_cache_set(self) -> set[str]:
        """Fetch the set of preserved cache names.

        Returns:
            set[str]: Preserved cache names.
        """
        return self.cache.get_preserved_cache_set()

    def load_cache(self, policy_repo, cache_name: str) -> str:
        """Load a named cache into the provided policy repository.

        Args:
            policy_repo: Policy repository receiving loaded data.
            cache_name: Cache entry name.

        Returns:
            str: Underlying cache manager status/result.
        """
        self.logger.info('Loading cache entry: %s', cache_name)
        return self.cache.load_combined_cache(policy_repo, cache_name)

    def load_cache_json(self, cache_name: str) -> dict[str, Any]:
        """Load a named cache file as JSON.

        Args:
            cache_name: Cache entry name.

        Returns:
            dict[str, Any]: Loaded JSON content.
        """
        return self.cache.load_cache_into_local_json(cache_name)

    def remove_cache(self, cache_name: str) -> bool:
        """Remove a cache entry.

        Args:
            cache_name: Cache entry name.

        Returns:
            bool: True when a cache entry was removed.
        """
        self.logger.info('Removing cache entry: %s', cache_name)
        return bool(self.cache.remove_cache_entry(cache_name))

    def rename_cache(self, old_cache_name: str, new_cache_name: str) -> bool:
        """Rename an existing cache entry.

        Args:
            old_cache_name: Existing cache name.
            new_cache_name: New cache name.

        Returns:
            bool: True when rename succeeded.
        """
        self.logger.info('Renaming cache entry: %s -> %s', old_cache_name, new_cache_name)
        return bool(self.cache.rename_cache_entry(old_cache_name, new_cache_name))

    def save_cache(self, policy_repo, export_file: Any | None = None, preserved: bool = False) -> str:
        """Save current repository state into cache storage.

        Args:
            policy_repo: Policy repository source.
            export_file: Optional explicit export destination.
            preserved: Whether to mark cache as preserved.

        Returns:
            str: Saved cache entry name or status.
        """
        self.logger.info('Saving cache entry: preserved=%s', preserved)
        return self.cache.save_combined_cache(policy_repo, export_file=export_file, preserved=preserved)

    def import_from_json(self, *, loaded_json: dict[str, Any], policy_repo: Any) -> bool:
        """Import repository state from pre-loaded JSON payload.

        Args:
            loaded_json: Parsed JSON payload.
            policy_repo: Policy repository target.

        Returns:
            bool: True when import succeeds.
        """
        self.logger.info('Importing cache data from JSON payload')
        return bool(self.cache.load_cache_from_json(loaded_json=loaded_json, policy_analysis=policy_repo))

    def update_policy_section(self, policy_repo: Any, *, policy_data_reloaded: str | None = None) -> None:
        """Update policy section in cache content.

        Args:
            policy_repo: Policy repository source.
            policy_data_reloaded: Optional policy data indicator.

        Returns:
            None
        """
        self.cache.update_policy_section(policy_repo, policy_data_reloaded=policy_data_reloaded)

    def get_consolidation_state(self, tenancy_ocid: str) -> dict:
        """Get or create consolidation state for a tenancy.

        Args:
            tenancy_ocid: Tenancy OCID key.

        Returns:
            dict: Consolidation state object.
        """
        return self.cache.get_or_create_consolidation_state(tenancy_ocid)

    def save_consolidation_state(self, tenancy_ocid: str, state: dict) -> None:
        """Persist consolidation state for a tenancy.

        Args:
            tenancy_ocid: Tenancy OCID key.
            state: Consolidation state payload.

        Returns:
            None
        """
        self.logger.info('Saving consolidation state: tenancy_ocid=%s', tenancy_ocid)
        self.cache.save_consolidation_state(tenancy_ocid, state)
