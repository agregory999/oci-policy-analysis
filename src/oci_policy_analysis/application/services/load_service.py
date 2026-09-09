"""Load and reload workflows for policy data."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.engine import PolicyIntelligenceEngine, PolicySimulationEngine
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.post_load import run_minimal_post_load_enrichment, run_post_load_pipeline

PostLoadProfile = str


@dataclass
class LoadResult:
    """Result wrapper for policy load operations."""

    success: bool
    message: str
    summary: dict[str, int] | None = None


class LoadService:
    """Orchestrate tenancy/cache/compliance loads without UI coupling."""

    def __init__(self, context: AppContext) -> None:
        """Initialize the load service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='load_service')

    def _emit_stage(
        self,
        *,
        stage: str,
        detail: str = '',
        state: str = 'running',
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> None:
        """Emit stage updates to context status and optional callback.

        Args:
            stage: Current stage name.
            detail: Optional stage detail text.
            state: Stage state value.
            on_stage: Optional callback for stage notifications.

        Returns:
            None
        """
        if hasattr(self.context, 'set_status'):
            self.context.set_status(stage=stage, detail=detail, state=state)
        if callable(on_stage):
            on_stage(stage, detail, state)

    def _reset_repo_state_before_load(self) -> None:
        """Reset repository state to avoid stale cross-tenancy residue."""
        repo = self.context.policy_repo
        reset_fn = getattr(repo, 'reset_state', None)
        if callable(reset_fn):
            reset_fn()
            self.logger.info('Reset policy repository state before load operation.')
        repo._cleanup_live_refresh_complete = False
        repo._cleanup_reload_api_errors = []
        self.context.intelligence = PolicyIntelligenceEngine(repo)
        self.context.simulation = PolicySimulationEngine(repo, getattr(self.context, 'reference_data', None))
        self.context._prospective_service = None
        self.context.data_generation = getattr(self.context, 'data_generation', 0) + 1
        on_reset = getattr(self.context, 'on_data_reset', None)
        if callable(on_reset):
            on_reset()

    def load_from_cache(
        self,
        cache_name: str,
        *,
        run_post_load_intelligence: bool = True,
        post_load_profile: PostLoadProfile = 'full',
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> LoadResult:
        """Load repository data from a named cache entry.

        Args:
            cache_name: Cache entry to load.
            run_post_load_intelligence: Whether to run post-load processing.
            post_load_profile: ``full`` for UI overlays/recommendations, ``minimal`` for CLI/MCP enrichment, ``none`` to skip.
            on_stage: Optional stage progress callback.

        Returns:
            LoadResult: Load status and data summary.
        """
        self.logger.info('Loading cache via LoadService: %s', cache_name)
        self._emit_stage(stage='Loading Cache', detail=f'Loading cache {cache_name}', on_stage=on_stage)
        repo = self.context.policy_repo
        self._reset_repo_state_before_load()
        success = self.context.cache.load_combined_cache(repo, named_cache=cache_name)
        if success and run_post_load_intelligence:
            self._run_post_load_with_stage(post_load_profile=post_load_profile, on_stage=on_stage)
        elif not success:
            self.logger.error('Cache load failed: cache_name=%s', cache_name)
        summary = self._build_summary(repo)
        msg = f'Loaded cache {cache_name}' if success else f'Failed to load cache {cache_name}'
        self._emit_stage(
            stage='Complete' if success else 'Failed',
            detail=msg,
            state='success' if success else 'error',
            on_stage=on_stage,
        )
        return LoadResult(success=bool(success), message=msg, summary=summary)

    def load_from_export_json(
        self,
        file_path: str,
        *,
        run_post_load_intelligence: bool = True,
        post_load_profile: PostLoadProfile = 'full',
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> LoadResult:
        """Load repository data from an exported JSON file.

        Args:
            file_path: Path to export JSON file.
            run_post_load_intelligence: Whether to run post-load processing.
            post_load_profile: ``full`` for UI overlays/recommendations, ``minimal`` for CLI/MCP enrichment, ``none`` to skip.
            on_stage: Optional stage progress callback.

        Returns:
            LoadResult: Load status and data summary.
        """
        self.logger.info('Loading export JSON via LoadService: %s', file_path)
        self._emit_stage(stage='Loading Export', detail=f'Reading {file_path}', on_stage=on_stage)
        repo = self.context.policy_repo
        self._reset_repo_state_before_load()
        try:
            with open(file_path, encoding='utf-8') as jsonfile:
                loaded_json = json.load(jsonfile)
        except Exception as exc:
            msg = f'Failed to read export JSON: {exc}'
            self.logger.exception('Failed reading export JSON file: %s', file_path)
            self._emit_stage(stage='Failed', detail=msg, state='error', on_stage=on_stage)
            return LoadResult(success=False, message=msg)

        success = bool(self.context.cache_service.import_from_json(loaded_json=loaded_json, policy_repo=repo))
        if success and run_post_load_intelligence:
            self._run_post_load_with_stage(post_load_profile=post_load_profile, on_stage=on_stage)
        elif not success:
            self.logger.error('Export JSON import failed: file_path=%s', file_path)
        summary = self._build_summary(repo)
        msg = f'Loaded export JSON from {file_path}' if success else f'Failed to load export JSON: {file_path}'
        self._emit_stage(
            stage='Complete' if success else 'Failed',
            detail=msg,
            state='success' if success else 'error',
            on_stage=on_stage,
        )
        return LoadResult(success=success, message=msg, summary=summary)

    def load_from_compliance_output(
        self,
        dir_path: str,
        *,
        load_all_users: bool = True,
        run_post_load_intelligence: bool = True,
        post_load_profile: PostLoadProfile = 'full',
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> LoadResult:
        """Load repository data from compliance output directory.

        Args:
            dir_path: Directory containing compliance output artifacts.
            load_all_users: Whether to load all users from identity data.
            run_post_load_intelligence: Whether to run post-load processing.
            post_load_profile: ``full`` for UI overlays/recommendations, ``minimal`` for CLI/MCP enrichment, ``none`` to skip.
            on_stage: Optional stage progress callback.

        Returns:
            LoadResult: Load status and data summary.
        """
        self.logger.info('Loading compliance output via LoadService: %s', dir_path)
        self._emit_stage(stage='Loading Compliance', detail=f'Loading from {dir_path}', on_stage=on_stage)
        repo = self.context.policy_repo
        self._reset_repo_state_before_load()
        success = repo.load_from_compliance_output_dir(dir_path, load_all_users=load_all_users)
        if success and run_post_load_intelligence:
            self._run_post_load_with_stage(post_load_profile=post_load_profile, on_stage=on_stage)
            try:
                self.context.cache_service.save_cache(repo)
            except Exception as exc:
                self.logger.warning('Compliance load succeeded but cache save failed: %s', exc)
        elif not success:
            self.logger.error('Compliance output load failed: dir_path=%s', dir_path)
        summary = self._build_summary(repo)
        msg = f'Loaded compliance output from {dir_path}' if success else f'Compliance load failed: {dir_path}'
        self._emit_stage(
            stage='Complete' if success else 'Failed',
            detail=msg,
            state='success' if success else 'error',
            on_stage=on_stage,
        )
        return LoadResult(success=bool(success), message=msg, summary=summary)

    def load_from_tenancy(
        self,
        *,
        use_instance_principal: bool,
        use_resource_principal: bool = False,
        profile: str | None = None,
        session_token: str | None = None,
        recursive: bool = False,
        load_all_users: bool = True,
        compartment_domain_search_depth: int = 1,
        run_post_load_intelligence: bool = True,
        post_load_profile: PostLoadProfile = 'full',
        save_cache_after_load: bool = True,
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> LoadResult:
        """Load policy data directly from OCI tenancy.

        Args:
            use_instance_principal: Whether to authenticate with instance principal.
            use_resource_principal: Whether to authenticate with resource principal.
            profile: Optional OCI profile name.
            session_token: Optional session token for auth.
            recursive: Whether tenancy traversal should be recursive.
            load_all_users: Whether to load all users for identity domains.
            compartment_domain_search_depth: Identity domain search depth.
            run_post_load_intelligence: Whether to run post-load processing.
            post_load_profile: ``full`` for UI overlays/recommendations, ``minimal`` for CLI/MCP enrichment, ``none`` to skip.
            save_cache_after_load: Whether to persist a fresh cache entry after live load.
            on_stage: Optional stage progress callback.

        Returns:
            LoadResult: Load status and data summary.
        """
        self.logger.info(
            'Loading tenancy via LoadService: instance_principal=%s resource_principal=%s profile=%s recursive=%s',
            use_instance_principal,
            use_resource_principal,
            profile or '',
            recursive,
        )
        self._emit_stage(stage='Initializing', detail='Configuring OCI client', on_stage=on_stage)
        repo = self.context.policy_repo
        self._reset_repo_state_before_load()
        self.logger.info(
            'Starting tenancy client initialization: auth_mode=%s profile=%s session_token=%s recursive=%s',
            (
                'resource_principal'
                if use_resource_principal
                else (
                    'instance_principal'
                    if use_instance_principal
                    else ('session_token' if session_token else 'profile')
                )
            ),
            profile or '',
            bool(session_token),
            recursive,
        )
        success = repo.initialize_client(
            use_instance_principal=use_instance_principal,
            use_resource_principal=use_resource_principal,
            session_token=session_token,
            recursive=recursive,
            profile=profile or '',
        )
        if not success:
            self.logger.error('Tenancy client initialization failed')
            self._emit_stage(
                stage='Failed', detail='Failed to initialize tenancy client', state='error', on_stage=on_stage
            )
            return LoadResult(success=False, message='Failed to initialize tenancy client')
        self.logger.info(
            'Tenancy client initialized: tenancy_ocid=%s tenancy_name=%s',
            getattr(repo, 'tenancy_ocid', None),
            getattr(repo, 'tenancy_name', None),
        )

        self._emit_stage(stage='Loading Compartments', detail='Fetching tenancy compartments', on_stage=on_stage)
        if not repo.load_compartments_only():
            self.logger.error('Tenancy load failed while loading compartments')
            self._emit_stage(stage='Failed', detail='Failed to load compartments', state='error', on_stage=on_stage)
            return LoadResult(success=False, message='Failed to load compartments')

        self._emit_stage(
            stage='Loading Identity Domains',
            detail='Fetching identity domains, groups, and users',
            on_stage=on_stage,
        )
        repo.compartment_domain_search_depth = compartment_domain_search_depth
        if not repo.load_complete_identity_domains(
            load_all_users=load_all_users,
            compartment_domain_search_depth=compartment_domain_search_depth,
        ):
            self.logger.error('Tenancy load failed while loading identity domains')
            self._emit_stage(stage='Failed', detail='Failed to load identity domains', state='error', on_stage=on_stage)
            return LoadResult(success=False, message='Failed to load identity domains')

        self._emit_stage(stage='Loading Policies', detail='Fetching policy statements', on_stage=on_stage)
        if not repo.load_policies_only():
            self.logger.error('Tenancy load failed while loading policies')
            self._emit_stage(stage='Failed', detail='Failed to load policies', state='error', on_stage=on_stage)
            return LoadResult(success=False, message='Failed to load policies')

        if run_post_load_intelligence:
            self._run_post_load_with_stage(post_load_profile=post_load_profile, on_stage=on_stage)

        if save_cache_after_load:
            # Persist a fresh cache entry for web/API-driven tenancy loads.
            try:
                self.context.cache_service.save_cache(repo)
            except Exception as exc:
                self.logger.warning('Tenancy load succeeded but cache save failed: %s', exc)

        summary = self._build_summary(repo)
        self._emit_stage(
            stage='Complete',
            detail=f"Loaded {summary.get('policies', 0)} policies and {summary.get('statements', 0)} statements",
            state='success',
            on_stage=on_stage,
        )
        self.logger.info(
            'Tenancy load completed: policies=%s statements=%s',
            summary.get('policies', 0),
            summary.get('statements', 0),
        )
        repo._cleanup_live_refresh_complete = not bool(repo._cleanup_reload_api_errors)
        if run_post_load_intelligence and post_load_profile == 'full' and repo._cleanup_live_refresh_complete:
            from oci_policy_analysis.application.services.cleanup_progress_service import CleanupProgressService

            try:
                CleanupProgressService(self.context).reconcile()
            except Exception as exc:
                self.logger.warning('Could not verify saved cleanup progress after live load: %s', exc)
        return LoadResult(success=True, message='Loaded tenancy data', summary=summary)

    def _run_post_load_with_stage(
        self,
        *,
        post_load_profile: PostLoadProfile,
        on_stage: Callable[[str, str, str], None] | None = None,
    ) -> None:
        """Run the selected post-load processing profile."""

        profile = str(post_load_profile or 'full').lower()
        if profile == 'none':
            self.logger.info('Skipping post-load processing by requested profile.')
            return
        if profile == 'minimal':
            self.logger.info('Running minimal post-load profile for non-UI consumer.')
            run_minimal_post_load_enrichment(self.context, on_stage=on_stage)
            return
        if profile != 'full':
            self.logger.warning('Unknown post-load profile %s; defaulting to full UI profile.', post_load_profile)
        self.logger.info('Running full post-load profile for UI consumer.')
        run_post_load_pipeline(self.context, on_stage=on_stage)

    @staticmethod
    def _build_summary(repo: Any) -> dict[str, int]:
        """Build a summary of loaded repository entity counts.

        Args:
            repo: Policy repository instance.

        Returns:
            dict[str, int]: Counts for key loaded entity types.
        """
        return {
            'compartments': len(getattr(repo, 'compartments', []) or []),
            'policies': len(getattr(repo, 'policies', []) or []),
            'statements': len(getattr(repo, 'regular_statements', []) or []),
            'groups': len(getattr(repo, 'groups', []) or []),
            'users': len(getattr(repo, 'users', []) or []),
        }
