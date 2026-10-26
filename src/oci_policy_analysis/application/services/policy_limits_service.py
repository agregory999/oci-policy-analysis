"""Snapshot-scoped eligibility and persistence for tenancy policy limits."""

from copy import deepcopy


class PolicyLimitsService:
    """Share policy-limit rules between inventory and recommendation controls.

    Args:
        context: Current application context with repository and cache store.

    Attributes:
        context: Snapshot whose source controls live-fetch eligibility.
    """

    def __init__(self, context):
        self.context = context

    @property
    def is_live_loaded(self) -> bool:
        """Whether policy data came from a live load in the current session."""
        repo = self.context.policy_repo
        return bool(
            getattr(repo, 'policies_loaded_from_tenancy', False)
            and not getattr(repo, 'current_cache_name', '')
            and not getattr(repo, 'loaded_from_compliance_output', False)
        )

    @property
    def can_fetch_live(self) -> bool:
        """Whether this live snapshot also has an initialized OCI Limits client."""
        return self.is_live_loaded and getattr(self.context.policy_repo, 'limits_client', None) is not None

    def apply_manual(self, policies_count: str, chain_count: str) -> dict:
        """Validate manual limits and persist only an active named cache.

        Args:
            policies_count: Positive whole-number policy object limit.
            chain_count: Positive whole-number compartment hierarchy statement limit.

        Returns:
            dict: Snapshot metadata marked as user supplied.

        Raises:
            ValueError: For a live-loaded snapshot or invalid values.
            OSError: If the active cache cannot be updated. Both in-memory limit
                representations are restored on failure. Export/CIS input files
                and global preferences are never modified.
        """
        if self.is_live_loaded:
            raise ValueError('Fetch policy limits from OCI for a live-loaded tenancy.')
        repo = self.context.policy_repo
        previous = deepcopy(getattr(repo, 'tenancy_policy_limits', {}) or {})
        previous_legacy = getattr(repo, 'tenancy_policy_statement_limit', None)
        try:
            limits = repo.set_user_supplied_tenancy_policy_limits(policies_count, chain_count)
            cache_name = getattr(repo, 'current_cache_name', '')
            if cache_name and not self.context.cache.update_tenancy_policy_limits(cache_name, limits):
                raise OSError('Could not save policy limits to the active cache. No limits were changed.')
        except Exception:
            repo.tenancy_policy_limits = previous
            repo.tenancy_policy_statement_limit = previous_legacy
            raise
        return limits
