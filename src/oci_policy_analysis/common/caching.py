##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# caching.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from oci.identity.models import Domain

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'
# AI result cache support has been removed (2025-11, per project guidance)

# Global logger for this module
logger = get_logger(component='caching')


class CacheManager:
    """
    Handles saving and loading cached JSON data (IAM + AI).
    Also supports canonical consolidation session persistence: per-tenancy state files for protected_set + plan history.
    Each cache is tied to a tenancy name and date.
    The cache directory is ~/.oci-policy-analysis/cache by default, but can be overridden.
    Caches have the concept of being "preserved" to avoid automatic deletion during culling.
    """

    # ----
    # Canonical per-tenancy consolidation session file with protected_set & history
    # ----

    def _consolidation_state_path(self, tenancy_ocid):
        """Return path to per-tenancy consolidation state file."""
        if not tenancy_ocid or str(tenancy_ocid).lower() in ['unknown', '', 'none']:
            raise ValueError('tenancy_ocid required for consolidation session persistence.')
        outdir = self.cache_dir / 'consolidation'
        outdir.mkdir(parents=True, exist_ok=True)
        return outdir / f'consolidation_{tenancy_ocid}.json'

    def get_or_create_consolidation_state(self, tenancy_ocid) -> dict:
        """
        Load the canonical consolidation state file for this tenancy_ocid.
        If it does not exist, create a blank state (protected_set={}, history=[]).
        Returns the state dict; saves it if it was new.
        """
        full_path = self._consolidation_state_path(tenancy_ocid)
        if full_path.exists():
            try:
                with open(full_path, encoding='utf-8') as f:
                    data = json.load(f)
                if 'protected_set' not in data:
                    data['protected_set'] = {}
                if 'history' not in data:
                    data['history'] = []
                return data
            except Exception as e:
                logger.error(f'Failed to load consolidation state for {tenancy_ocid}: {e}')
                # Try to reinitialize state if corrupt
        # New or failed to load: write default, return blank state
        state = {'protected_set': {}, 'history': []}
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        logger.info(f'Created new consolidation state file for tenancy_ocid={tenancy_ocid} at {full_path}')
        return state

    def save_consolidation_state(self, tenancy_ocid, state: dict):
        """Overwrite the canonical consolidation state file for this tenancy_ocid."""
        full_path = self._consolidation_state_path(tenancy_ocid)
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        logger.info(f'Saved consolidation state for tenancy_ocid={tenancy_ocid} at {full_path}')

    def get_protected_set(self, tenancy_ocid):
        """Return the protected_set from consolidation state. Creates file if needed."""
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        return state.get('protected_set', {})

    def set_protected_set(self, tenancy_ocid, protected_set: dict):
        """Update and persist the protected_set in the canonical consolidation state file."""
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        state['protected_set'] = protected_set
        self.save_consolidation_state(tenancy_ocid, state)
        logger.info(f'Updated protected_set for tenancy_ocid={tenancy_ocid}')

    def get_history(self, tenancy_ocid):
        """
        Return the list of run/plan history for this tenancy_ocid.
        If no tenancy_ocid, returns empty list (safe for new sessions).
        """
        if not tenancy_ocid or str(tenancy_ocid).lower() in ['unknown', '', 'none']:
            logger.info('get_history: No tenancy_ocid provided, returning empty history list.')
            return []
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        return state.get('history', [])

    def add_run_record(self, tenancy_ocid, run_record: dict):
        """Append a new run/plan record to history and save the canonical file."""
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        if 'history' not in state:
            state['history'] = []
        state['history'].append(run_record)
        self.save_consolidation_state(tenancy_ocid, state)
        logger.info(
            f"Added run_record ({run_record.get('consolidation_effort_id', 'unknown')}) for tenancy_ocid={tenancy_ocid}"
        )

    def update_run_record(self, tenancy_ocid: str, consolidation_effort_id: str, updates: dict) -> bool:
        """
        Update an existing run record in history by consolidation_effort_id.

        Args:
            tenancy_ocid: Tenancy OCID.
            consolidation_effort_id: Run identifier (plan_id).
            updates: Dict of fields to merge into the run record (e.g. status, step_status).
        """
        if not tenancy_ocid or str(tenancy_ocid).lower() in ('unknown', '', 'none'):
            return False
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        history = state.get('history', [])
        for i, run in enumerate(history):
            if run.get('consolidation_effort_id') == consolidation_effort_id:
                history[i] = {**run, **updates}
                self.save_consolidation_state(tenancy_ocid, state)
                logger.info(f'Updated run_record {consolidation_effort_id} for tenancy_ocid={tenancy_ocid}')
                return True
        return False

    def remove_run_record(self, tenancy_ocid: str, consolidation_effort_id: str) -> bool:
        """
        Remove a run record from history by consolidation_effort_id.

        Args:
            tenancy_ocid: Tenancy OCID.
            consolidation_effort_id: Run identifier (plan_id) to remove.
        """
        if not tenancy_ocid or str(tenancy_ocid).lower() in ('unknown', '', 'none'):
            return False
        state = self.get_or_create_consolidation_state(tenancy_ocid)
        history = state.get('history', [])
        new_history = [r for r in history if r.get('consolidation_effort_id') != consolidation_effort_id]
        if len(new_history) == len(history):
            return False
        state['history'] = new_history
        self.save_consolidation_state(tenancy_ocid, state)
        logger.info(f'Removed run_record {consolidation_effort_id} from tenancy_ocid={tenancy_ocid}')
        return True

    def list_consolidation_tenancy_ocids(self) -> list[str]:
        """Return list of tenancy OCIDs that have consolidation state files."""
        outdir = self.cache_dir / 'consolidation'
        if not outdir.exists():
            return []
        ids = []
        for f in outdir.glob('consolidation_*.json'):
            name = f.stem
            if name.startswith('consolidation_'):
                ids.append(name[14:])
        return ids

    def list_all_consolidation_plans(self) -> list[dict]:
        """
        Return a flat list of all consolidation plans across tenancies.
        Each item has tenancy_ocid, consolidation_effort_id, created_at, and run (full record).
        """
        result = []
        for tenancy_ocid in self.list_consolidation_tenancy_ocids():
            history = self.get_history(tenancy_ocid)
            for run in history:
                result.append(
                    {
                        'tenancy_ocid': tenancy_ocid,
                        'consolidation_effort_id': run.get('consolidation_effort_id', ''),
                        'created_at': run.get('created_at', ''),
                        'run': run,
                    }
                )
        return result

    def __init__(
        self,
        cache_dir: Path = None,
    ):
        # logger = get_logger(component="caching")
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f'Initialized Caching at {self.cache_dir}')

    # ----
    # Consolidation Session Save/Load
    # ----

    def save_consolidation_session(
        self, session_data: dict, plan_id: str = None, tenancy_ocid: str = None, preserved: bool = False
    ) -> str:
        """
        Save a consolidation session (see models_consolidation.ConsolidationSession) to disk as JSON.
        Returns file name/path.
        Args:
            session_data: The dict/TypedDict structure matching ConsolidationSession (pluggable, robust to version drift)
            plan_id: Optional label/ID for file naming, else uses timestamp.
            tenancy_ocid: Optional for nested cache structure.
            preserved: Mark this session as not-to-be-deleted.
        Returns:
            The output file path string.
        """
        # imports already present at the top

        CACHE_DATE = datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S-%Z')
        tag = plan_id or f'session_{CACHE_DATE}'
        tenancy_subdir = Path(str(tenancy_ocid)) if tenancy_ocid else Path()
        outdir = self.cache_dir / 'consolidation' / tenancy_subdir
        outdir.mkdir(parents=True, exist_ok=True)
        file_path = outdir / f'{tag}.json'

        def _serialize_for_json(obj):
            if isinstance(obj, dict):
                return {k: _serialize_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_serialize_for_json(x) for x in obj]
            elif isinstance(obj, tuple):
                return tuple(_serialize_for_json(x) for x in obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            else:
                return obj

        data = _serialize_for_json(session_data)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f'Saved consolidation session to {file_path}')
        return str(file_path)

    def load_consolidation_session(self, plan_id: str, tenancy_ocid: str = None) -> dict | None:
        """
        Load a consolidation session from cache.
        Args:
            plan_id: Label/filename (w/o json) for the session/plan.
            tenancy_ocid: Optional subdir
        Returns:
            session_data (dict) or None
        """
        # imports already present at the top
        tenancy_subdir = Path(str(tenancy_ocid)) if tenancy_ocid else Path()
        input_file = self.cache_dir / 'consolidation' / tenancy_subdir / f'{plan_id}.json'
        try:
            with open(input_file, encoding='utf-8') as f:
                session_data = json.load(f)
            logger.info(f'Loaded consolidation session from {input_file}')
            return session_data
        except Exception as e:
            logger.error(f'Failed to load consolidation session {input_file}: {e}')
            return None

    # Utility functions for loading and saving cache, using combined caching strategy
    def save_combined_cache(
        self, policy_analysis: PolicyAnalysisRepository, export_file=None, preserved: bool = False
    ) -> str:
        """
        Save combined cache for policies and dynamic groups. Returns file name.

        Args:
            export_file: Optional file handle to export to instead of saving to cache directory
            preserved: Whether to mark this cache as preserved (not auto-deleted)

        Returns:
            The name of the file saved"""

        # Date of the cache
        CACHE_DATE = datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S-%Z')

        # BREAKING: Only support new structure: "policies" (BasePolicy objects), "policy_statements" (statements list)
        combined_data = {
            'version': 2,
            'tenancy_name': policy_analysis.tenancy_name,
            'tenancy_ocid': policy_analysis.tenancy_ocid,
            'policies': policy_analysis.policies,  # BasePolicy objects only!
            'policy_statements': policy_analysis.regular_statements,  # List of statements
            'defined_tag_namespace_keys': getattr(policy_analysis, 'defined_tag_namespace_keys', {}),
            'dynamic_groups': policy_analysis.dynamic_groups,
            'defined_aliases': policy_analysis.defined_aliases,
            'cross_tenancy_statements': policy_analysis.cross_tenancy_statements,
            'compartments': policy_analysis.compartments,
            'identity_domains': policy_analysis._get_domains(),
            'groups': policy_analysis.groups,
            'users': policy_analysis.users,
            'data_as_of': policy_analysis.data_as_of,
            'load_all_users': getattr(policy_analysis, 'load_all_users', True),
        }
        logger.info(
            'Saving cache with BREAKING format: "policies"=BasePolicy objects, "policy_statements"=statement list. Old cache files are no longer supported.'
        )

        def _serialize_for_json(obj):
            """Recursively convert datetime objects to ISO format (str)."""
            if isinstance(obj, dict):
                return {k: _serialize_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_serialize_for_json(x) for x in obj]
            elif isinstance(obj, tuple):
                return tuple(_serialize_for_json(x) for x in obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            else:
                return obj

        combined_data_serializable = _serialize_for_json(combined_data)

        if export_file:
            with open(export_file.name, 'w', newline='', encoding='utf-8') as filehandle:
                json.dump(combined_data_serializable, filehandle, ensure_ascii=False, default=str)
            logger.info(f'Exported combined cache to: {export_file.name}')
            return str(export_file.name)

        else:
            combined_cache_file = self.cache_dir / f'combined_cache_{policy_analysis.tenancy_name}_{CACHE_DATE}.json'
            with open(combined_cache_file, 'w', encoding='utf-8') as filehandle:
                json.dump(combined_data_serializable, filehandle, ensure_ascii=False)
            logger.info(f'Saved combined cache to: {combined_cache_file}')

        # Update cache entries
        entry = {
            'tenancy_name': policy_analysis.tenancy_name,
            'cache_date': CACHE_DATE,
            'preserved': preserved,
        }
        entries_path = self.cache_dir / 'cache_entries.json'
        with open(entries_path, 'a', encoding='utf-8') as date_file:
            json.dump(entry, date_file, ensure_ascii=False)
            date_file.write('\n')  # Write a newline after each entry
        logger.info(f'Updated cache entries with: {entry}')

        # Cull old cache files and entries to keep only 10 most recent per tenancy
        self._cull_old_caches(policy_analysis.tenancy_name)

        # Return the name of the file
        return str(combined_cache_file)

    def _cull_old_caches(self, tenancy_name: str):  # noqa: C901
        """Keep only the 10 most recent cache files/entries for this tenancy_name.
        Preserved caches are never deleted."""

        cache_files = list(self.cache_dir.glob(f'combined_cache_{tenancy_name}_*.json'))

        # Gather preserved cache file names from entries
        preserved_files = set()
        entries_path = self.cache_dir / 'cache_entries.json'
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            for line in entry_lines:
                try:
                    cache = json.loads(line)
                    if cache.get('tenancy_name') == tenancy_name and cache.get('preserved'):
                        preserved_files.add(f"combined_cache_{cache['tenancy_name']}_{cache['cache_date']}.json")
                except Exception:
                    continue

        # Only include files whose name matches date pattern
        def parse_date_from_file(f):
            # Example: combined_cache_andrew_2025-11-20-16-22-49-UTC.json
            m = re.search(r'_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-[A-Z]+)\.json$', f.name)
            if m:
                try:
                    return datetime.strptime(m.group(1), '%Y-%m-%d-%H-%M-%S-%Z')
                except Exception:
                    return None
            return None

        dated_files = [(dt, f) for f in cache_files if (dt := parse_date_from_file(f)) is not None]
        dated_files.sort(key=lambda x: x[0], reverse=True)
        to_delete = [f for dt, f in dated_files[10:] if f.name not in preserved_files]
        pruned = 0
        # Do not delete preserved files or non-date-named
        for old_file in to_delete:
            try:
                old_file.unlink()
                logger.info(f'Pruned old cache file: {old_file}')
                pruned += 1
            except Exception as e:
                logger.error(f'Could not remove old cache file {old_file}: {e}')
        # Note: non-dated (renamed) caches are never automatically deleted here.

        # Cull the cache_entries.json as well
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            remaining = []
            count = 0
            # Newest to oldest, keep up to 10 for tenancy_name, but never remove preserved
            for line in reversed(entry_lines):
                try:
                    cache = json.loads(line)
                    if cache.get('tenancy_name') == tenancy_name:
                        if cache.get('preserved', False):
                            remaining.append(line)
                        elif count < 10:
                            remaining.append(line)
                            count += 1
                        # else skip (remove)
                    else:
                        remaining.append(line)
                except Exception:
                    remaining.append(line)  # keep malformed
            # Write updated file (restore reversed order to maintain recency at top)
            with open(entries_path, 'w', encoding='utf-8') as f:
                for line in reversed(remaining):
                    f.write(line)

    def load_combined_cache(self, policy_analysis: PolicyAnalysisRepository, named_cache: str) -> str:
        """Load combined cache for policies and dynamic groups.

        Given the name and data of a cache, loads the data into both of the centralized structures
        for Compartment/Policy JSON storage.

        Args:
            named_cache: The tenancy_date string of the cache name to load

        Returns:
            A string indicating the name of the file used
        """
        combined_cache_file = self.cache_dir / f'combined_cache_{named_cache}.json'
        logger.info(f'Loading combined cache from: {combined_cache_file}')
        if combined_cache_file.exists():
            try:
                with open(combined_cache_file, encoding='utf-8') as filehandle:
                    cache_data = json.load(filehandle)
                    # Grab all of the elements of the cache
                    # BREAKING: Require new structure - "policies" and "policy_statements" must be present
                    if 'policies' not in cache_data or 'policy_statements' not in cache_data:
                        logger.error(
                            "Loaded cache file is missing required keys: 'policies' and/or 'policy_statements'."
                        )
                        raise RuntimeError(
                            'This cache file is not compatible with the current application version. '
                            'Please reload OCI data to generate a new cache file via the application UI.'
                        )
                    policy_analysis.policies = cache_data['policies']
                    policy_analysis.regular_statements = cache_data['policy_statements']
                    policy_analysis.defined_tag_namespace_keys = cache_data.get('defined_tag_namespace_keys', {})

                    dynamic_groups = cache_data.get('dynamic_groups', [])
                    cross_tenancy_data = cache_data.get('cross_tenancy_statements', [])
                    defined_aliases = cache_data.get('defined_aliases', [])
                    policy_analysis.tenancy_name = cache_data.get('tenancy_name', '')
                    policy_analysis.tenancy_ocid = cache_data.get('tenancy_ocid', '')
                    policy_analysis.compartments = cache_data.get('compartments', [])
                    policy_analysis.defined_aliases = defined_aliases
                    policy_analysis.cross_tenancy_statements = cross_tenancy_data
                    policy_analysis.dynamic_groups = dynamic_groups
                    policy_analysis.identity_domains = [
                        Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
                        for d in cache_data.get('identity_domains', [])
                    ]
                    policy_analysis.groups = cache_data.get('groups', [])
                    policy_analysis.users = cache_data.get('users', [])
                    policy_analysis.version = cache_data.get('version', 1)
                    policy_analysis.load_all_users = cache_data.get('load_all_users', True)
                    # Set the data as of time, always a str
                    policy_analysis.data_as_of = cache_data.get('data_as_of') or ''
                    # --- Load the last policy reload timestamp if present
                    policy_analysis.policy_data_reloaded = cache_data.get('policy_data_reloaded', '')
                    logger.info(f'Loaded combined cache (strict mode) from: {combined_cache_file}')
                    logger.info(
                        f'Loaded {len(policy_analysis.policies)} BasePolicy objects, {len(dynamic_groups)} dynamic groups, '
                        f'{len(cross_tenancy_data)} cross-tenancy policies, '
                        f'{len(policy_analysis.identity_domains)} identity domains, '
                        f'{len(policy_analysis.groups)} groups, and {len(policy_analysis.users)} users from cache. '
                        f'Policy statements: {len(policy_analysis.regular_statements)}. '
                        f'Defined tag namespaces: {len(getattr(policy_analysis, "defined_tag_namespace_keys", {}) or {})}.'
                    )

            except json.JSONDecodeError as e:
                logger.error(f'Error decoding JSON from combined cache file: {e}')
                return 'no cache'
            except Exception as e:
                logger.error(f'Error loading combined cache file: {e}')
                return 'no cache'
        # logger.warning(f'Unable to load data from cache: {combined_cache_file}')
        else:
            logger.warning(f'Unable to load data from cache: {combined_cache_file}')
            raise ValueError('no cache')
        return str(combined_cache_file)

    def load_cache_from_json(self, policy_analysis: PolicyAnalysisRepository, loaded_json: dict) -> bool:
        """
        Load combined cache data from a given JSON dict.
        Given loaded JSON data, loads the data into both of the centralized structures
        for Compartment/Policy JSON storage.

        Args:
            loaded_json: The loaded JSON data as a dict
        """
        try:
            # Grab all of the elements of the cache
            # BREAKING: Require both "policies" and "policy_statements" keys
            if 'policies' not in loaded_json or 'policy_statements' not in loaded_json:
                logger.error("Loaded cache (from JSON) missing required keys: 'policies' and/or 'policy_statements'.")
                raise RuntimeError(
                    'This cache structure is incompatible with the current application version. '
                    'Please reload OCI data to create a new cache file.'
                )
            policy_analysis.policies = loaded_json['policies']
            policy_analysis.regular_statements = loaded_json['policy_statements']
            policy_analysis.defined_tag_namespace_keys = loaded_json.get('defined_tag_namespace_keys', {})

            dynamic_groups = loaded_json.get('dynamic_groups', [])
            cross_tenancy_data = loaded_json.get('cross_tenancy_statements', [])
            defined_aliases = loaded_json.get('defined_aliases', [])

            policy_analysis.tenancy_name = loaded_json.get('tenancy_name', '')
            policy_analysis.tenancy_ocid = loaded_json.get('tenancy_ocid', '')
            policy_analysis.compartments = loaded_json.get('compartments', [])
            policy_analysis.defined_aliases = defined_aliases
            policy_analysis.cross_tenancy_statements = cross_tenancy_data
            policy_analysis.dynamic_groups = dynamic_groups
            policy_analysis.identity_domains = [
                Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
                for d in loaded_json.get('identity_domains', [])
            ]
            policy_analysis.groups = loaded_json.get('groups', [])
            policy_analysis.users = loaded_json.get('users', [])
            policy_analysis.version = loaded_json.get('version', 1)
            policy_analysis.load_all_users = loaded_json.get('load_all_users', True)
            # Set the data as of time, always a str
            policy_analysis.data_as_of = loaded_json.get('data_as_of') or ''
            # --- Load last policy reload timestamp if present
            policy_analysis.policy_data_reloaded = loaded_json.get('policy_data_reloaded', '')
            logger.info(
                f'Loaded {len(policy_analysis.policies)} BasePolicy objects, {len(dynamic_groups)} dynamic groups, '
                f'{len(cross_tenancy_data)} cross-tenancy policies, '
                f'{len(policy_analysis.identity_domains)} identity domains, '
                f'{len(policy_analysis.groups)} groups, and {len(policy_analysis.users)} users from cache (JSON input). '
                f'Policy statements: {len(policy_analysis.regular_statements)}. '
                f'Defined tag namespaces: {len(getattr(policy_analysis, "defined_tag_namespace_keys", {}) or {})}.'
            )
            return True
        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from combined cache file: {e}')
            return False
        except Exception as e:
            logger.error(f'Error loading combined cache file: {e}')
            return False

    def get_preserved_cache_set(self) -> set:
        """Get a set of cache names which are marked as preserved."""
        preserved_files = set()
        entries_path = self.cache_dir / 'cache_entries.json'
        import json

        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        key = f"{entry['tenancy_name']}_{entry['cache_date']}"
                        if entry.get('preserved', False):
                            preserved_files.add(key)
                    except Exception:
                        continue
        return preserved_files

    def get_available_cache(self, tenancy_name: str | None) -> list[str]:
        """Get available cache files for a given profile

        If given no argument, simply return the list of all avialable cache files that
        exist in the cache directory.  Entries will contain the tenancy name and date loaded.

        Args:
            tenancy_name: The name of an OCI tenancy, which will filter the cache list down to only
            caches for that tenancy.

        Returns:
            a list of the available named caches
        """
        return_entries = []
        try:
            with open(self.cache_dir / 'cache_entries.json', encoding='utf-8') as date_file:
                entries = date_file.readlines()
            logger.debug(f'Entries found in cache_entries.json: {entries}')
            entries.reverse()  # Show most recent first
            logger.debug(f'Entries found in cache_entries.json (Reversed): {entries}')

            for entry in entries:
                cache = json.loads(entry)
                if tenancy_name and cache['tenancy_name'] != tenancy_name:
                    continue
                return_entries.append(cache['tenancy_name'] + '_' + cache['cache_date'])
        except json.JSONDecodeError:
            logger.warning('No cache entries found or cache_entries.json is empty.')
        except FileNotFoundError:
            logger.warning('cache_entries.json file not found. No cache entries available.')

        logger.info(f'Entries found in cache_entries.json: {len(return_entries)}')
        return return_entries

    def load_cache_into_local_json(self, cached_tenancy: str) -> dict:
        """
        Takes a named cache (tenancy_date) and returns the loaded JSON data as a dict.
        Used for exporting or other purposes.

        Args:
            cached_tenancy: The tenancy_date string of the cache name to load

        Returns:
            The loaded cache data as a dict
        """
        combined_cache_file = self.cache_dir / f'combined_cache_{cached_tenancy}.json'
        if combined_cache_file.exists():
            try:
                with open(combined_cache_file, encoding='utf-8') as filehandle:
                    cache_data = json.load(filehandle)
                    logger.info(f'Loaded combined cache from: {combined_cache_file}')
                    # Show counts of each loaded element
                    # Return data as object
                    return cache_data
            except json.JSONDecodeError as e:
                logger.error(f'Error decoding JSON from combined cache file: {e}')
                return {}
            except Exception as e:
                logger.error(f'Error loading combined cache file: {e}')
                return {}
        logger.warning(f'Unable to load data from cache: {combined_cache_file}')
        return {}

    def remove_cache_entry(self, named_cache: str) -> bool:
        """
        Remove specified cache file AND its entry from cache_entries.json.

        Args:
            named_cache: The tenancy_date string of the cache name to remove

        Returns:
            True if both file and entry were removed, False otherwise
        """
        cache_file = self.cache_dir / f'combined_cache_{named_cache}.json'
        removed_file = False
        if cache_file.exists():
            try:
                cache_file.unlink()
                removed_file = True
                logger.info(f'Removed cache file: {cache_file}')
            except Exception as e:
                logger.error(f'Could not remove cache file {cache_file}: {e}')
        # Remove entry from cache_entries.json
        entries_path = self.cache_dir / 'cache_entries.json'
        updated = False
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            with open(entries_path, 'w', encoding='utf-8') as f:
                for line in entry_lines:
                    try:
                        cache = json.loads(line)
                        entry_name = f"{cache['tenancy_name']}_{cache['cache_date']}"
                        if entry_name == named_cache:
                            updated = True
                            continue  # Skip (remove) this entry
                    except Exception:
                        pass
                    f.write(line)
        return removed_file and updated

    def rename_cache_entry(self, old_named_cache: str, new_named_cache: str) -> bool:  # noqa: C901
        """
        Rename both the cache file and its entry in cache_entries.json.

        Args:
            old_named_cache: The current tenancy_date string of the cache name
            new_named_cache: The new tenancy_date string of the cache name

        Returns:
            True if both file and entry were renamed, False otherwise.
            Returns False (and does NOT rename) if a cache file or entry already exists with the new name.
        """
        old_file = self.cache_dir / f'combined_cache_{old_named_cache}.json'
        new_file = self.cache_dir / f'combined_cache_{new_named_cache}.json'

        # Defensive: if new_file exists, refuse to rename.
        if new_file.exists():
            logger.error(f'Refusing to rename: target exists: {new_file}')
            return False

        # Defensive: refuse if target new_named_cache already in entries
        entries_path = self.cache_dir / 'cache_entries.json'
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            for line in entry_lines:
                try:
                    cache = json.loads(line)
                    entry_name = f"{cache['tenancy_name']}_{cache['cache_date']}"
                    if entry_name == new_named_cache:
                        logger.error(
                            f'Refusing to rename: entry already exists in cache_entries.json as {new_named_cache}'
                        )
                        return False
                except Exception:
                    continue

        renamed_file = False
        if old_file.exists():
            try:
                old_file.rename(new_file)
                renamed_file = True
                logger.info(f'Renamed cache file {old_file} -> {new_file}')
            except Exception as e:
                logger.error(f'Could not rename cache file {old_file}: {e}')
        updated = False
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            with open(entries_path, 'w', encoding='utf-8') as f:
                for line in entry_lines:
                    try:
                        cache = json.loads(line)
                        entry_name = f"{cache['tenancy_name']}_{cache['cache_date']}"
                        if entry_name == old_named_cache:
                            # Must split new_named_cache into tenancy_name, cache_date
                            tn, cd = new_named_cache.split('_', 1)
                            cache['tenancy_name'] = tn
                            cache['cache_date'] = cd
                            line = json.dumps(cache, ensure_ascii=False) + '\n'
                            updated = True
                    except Exception:
                        pass
                    f.write(line)
        return renamed_file and updated

    def preserve_cache_entry(self, named_cache: str, preserve: bool = True) -> bool:
        """
        Mark or unmark a cache entry as preserved in cache_entries.json.

        Args:
            named_cache: The tenancy_date string of the cache name to update
            preserve: True to mark as preserved, False to unmark

        Returns:
            True if the entry was updated, False otherwise
        """
        entries_path = self.cache_dir / 'cache_entries.json'
        updated = False
        if entries_path.exists():
            with open(entries_path, encoding='utf-8') as f:
                entry_lines = f.readlines()
            with open(entries_path, 'w', encoding='utf-8') as f:
                for line in entry_lines:
                    try:
                        cache = json.loads(line)
                        entry_name = f"{cache['tenancy_name']}_{cache['cache_date']}"
                        if entry_name == named_cache:
                            cache['preserved'] = preserve
                            line = json.dumps(cache, ensure_ascii=False) + '\n'
                            updated = True
                    except Exception:
                        pass
                    f.write(line)
        return updated

    def update_policy_section(self, policy_analysis: PolicyAnalysisRepository, policy_data_reloaded: str | None):
        """
        Update ONLY the policies, policy_statements, tag catalog, compartments, defined_aliases, and cross_tenancy_statements in
        the most recent cache file for a given tenancy, and set 'policy_data_reloaded' with the supplied timestamp.
        This preserves IAM/user/group data and other session metadata. No effect if no cache is present.

        Args:
            policy_analysis: PolicyAnalysisRepository with fresh policy/compartment data in memory
            policy_data_reloaded: ISO timestamp string for reloaded policy data
        """
        cache_files = list(self.cache_dir.glob(f'combined_cache_{policy_analysis.tenancy_name}_*.json'))
        if not cache_files:
            logger.warning(
                f"[CacheManager.update_policy_section] No existing cache file for tenancy '{policy_analysis.tenancy_name}', skipping."
            )
            return
        # Use newest cache file (sorted by filename so creation time works due to naming convention)
        cache_files.sort(reverse=True)
        cache_file = cache_files[0]
        try:
            with open(cache_file, encoding='utf-8') as f:
                cache_data = json.load(f)
        except Exception as e:
            logger.error(f"[CacheManager.update_policy_section] Failed to load cache file '{cache_file}': {e}")
            return

        # Update the compartment/policy section fields (other identity data are left untouched)
        cache_data['policies'] = policy_analysis.policies
        cache_data['policy_statements'] = policy_analysis.regular_statements
        cache_data['defined_tag_namespace_keys'] = getattr(policy_analysis, 'defined_tag_namespace_keys', {})
        cache_data['compartments'] = policy_analysis.compartments
        cache_data['defined_aliases'] = policy_analysis.defined_aliases
        cache_data['cross_tenancy_statements'] = policy_analysis.cross_tenancy_statements
        cache_data['policy_data_reloaded'] = policy_data_reloaded
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(
                f'[CacheManager.update_policy_section] Updated policy/compartment section of {cache_file} with new policy_data_reloaded: {policy_data_reloaded}'
            )
        except Exception as e:
            logger.error(f"[CacheManager.update_policy_section] Could not save cache file '{cache_file}': {e}")
