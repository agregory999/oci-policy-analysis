"""Verify locally tracked cleanup actions after a complete live analysis."""

from oci_policy_analysis.application.core.engine.recommendation_actions import (
    CLEANUP_ACTION_IDS,
    cleanup_finding_identity,
    current_supersession_identities,
    reconcile_cleanup_actions,
)


class CleanupProgressService:
    """Reconcile tenancy-scoped saved actions using the active live analysis."""

    def __init__(self, context):
        """Use the shared repository, intelligence engine, settings, and local cache."""
        self.context = context

    def reconcile(self):
        """Persist verification results only when a complete live refresh is available."""
        repo = self.context.policy_repo
        tenancy = repo.tenancy_ocid
        if not tenancy or not getattr(repo, '_cleanup_live_refresh_complete', False):
            return
        actions = self.context.cache.load_cleanup_progress(tenancy)
        if not actions:
            return
        cleanup = self.context.intelligence.overlay.get('cleanup_items', {})
        current = set()
        for label, key in CLEANUP_ACTION_IDS.items():
            for item in cleanup.get(key, []) or []:
                name = item.get('statement_text') or '/'.join(
                    [
                        item.get('domain_name') or 'Default',
                        item.get('dynamic_group_name') or item.get('group_name') or '',
                    ]
                )
                current.add(cleanup_finding_identity({'Type': label, 'Name': name}, item))
        current.update(
            current_supersession_identities(
                self.context.intelligence.overlay, getattr(repo, 'regular_statements', []) or []
            )
        )
        updated = reconcile_cleanup_actions(
            actions,
            tenancy,
            current,
            enabled=self.context.settings.get('enabled_intelligence_checks'),
            users_loaded=getattr(repo, 'load_all_users', True),
        )
        self.context.cache.save_cleanup_progress(tenancy, updated)
