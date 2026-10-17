"""Desktop usage sessions with non-blocking, best-effort publication."""

from concurrent.futures import ThreadPoolExecutor
from string import ascii_letters, digits

from oci_policy_analysis.application.core.support.usage_tracking import init_usage_tracker


class UsageSession:
    """Own Qt tracking lifecycle while preserving legacy run/event JSON fields.

    Args:
        settings: Shared preferences; an absent enabled flag defaults to True.
        app_version: Installed application version for the run document.

    Notes:
        Only fixed UI identifiers and numeric counts are accepted here. Uploads
        run off the UI thread. Opt-out discards pending data; in-flight HTTP
        requests cannot be recalled. No disk queue is retained.
    """

    def __init__(self, settings: dict, app_version: str):
        self.version = app_version
        self.tracker = None
        self.tenancy_suffix = None
        self.closed = False
        self._pending = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='UsagePublisher')
        self.set_enabled(settings.get('usage_tracking_enabled', True))

    def set_enabled(self, enabled: bool) -> None:
        """Apply opt-out immediately, or begin a fresh run on opt-in."""
        if self.closed:
            return
        if not enabled:
            for tracker, future in self._pending:
                tracker.enabled = False
                future.cancel()
            self._pending.clear()
            self.tracker = init_usage_tracker({'usage_tracking_enabled': False}, self.version)
        elif self.tracker is None:
            self._start()

    def _start(self):
        self.tracker = init_usage_tracker({'usage_tracking_enabled': True}, self.version, interface='qt', new_run=True)
        self.tracker.set_tenancy_suffix(self.tenancy_suffix)
        self.tracker.track('app_start', interface='qt')

    def set_tenancy(self, tenancy_ocid: str | None) -> None:
        """Group runs by the existing six-character suffix, never a full OCID."""
        suffix = str(tenancy_ocid)[-6:] if tenancy_ocid else None
        if suffix and any(char not in ascii_letters + digits for char in suffix):
            suffix = None
        if suffix == self.tenancy_suffix:
            return
        if self.tracker is not None and self.tenancy_suffix is not None:
            self._pending.append((self.tracker, self._executor.submit(self.tracker.flush)))
            self.tracker = None
            self.tenancy_suffix = suffix
            self._start()
        else:
            self.tenancy_suffix = suffix
            if self.tracker is not None and suffix:
                self.tracker.set_tenancy_suffix(suffix)

    def view(self, name: str, sub_view: str | None = None) -> None:
        """Record code-defined page identifiers; callers must not pass user text."""
        allowed_pages = {
            'overview',
            'browser',
            'graph',
            'users_groups',
            'dynamic_groups',
            'resource_principals',
            'recommendations',
            'mcp',
            'prospective',
            'simulation',
            'consolidation',
            'historical',
            'tools',
        }
        allowed_subviews = {
            'tools': {'Condition Tester', 'Reports', 'Maintenance', 'Logging'},
            'recommendations': {
                'Summary',
                'Policy risk',
                'Statement risk',
                'Superseded',
                'Cross-tenancy',
                'Consolidation',
                'Cleanup / Fix',
                'Limits',
            },
            'users_groups': {'Group-based View', 'User-based View'},
            'simulation': {'1. Environment', '2. Statements', '3. Request context', '4. Results && history'},
        }
        if self.tracker is not None and not self.closed and name in allowed_pages:
            payload = {'tab_name': name}
            if sub_view in allowed_subviews.get(name, set()):
                payload['sub_view'] = sub_view
            self.tracker.track('tab_change', **payload)

    def operation(self, name: str, *, source: str = '', success: bool = True, counts: dict | None = None) -> None:
        """Record a fixed operation category, source enum and inventory counts."""
        if (
            self.tracker is None
            or self.closed
            or name
            not in {
                'data_load',
                'simulation_run',
                'report_generate',
                'recommendations_refresh',
                'historical_compare',
            }
        ):
            return
        payload = {'success': bool(success)}
        if source in {'tenancy', 'cache', 'json', 'compliance', 'sample'}:
            payload['source'] = source
        if counts:
            payload['counts'] = {
                key: value
                for key, value in counts.items()
                if key
                in {
                    'policies',
                    'statements',
                    'groups',
                    'users',
                    'dynamic_groups',
                    'compartments',
                }
                and type(value) is int
                and value >= 0
            }
        self.tracker.track_operation(name, **payload)

    def close(self, *, wait: bool = True) -> None:
        """Queue one final upload; optionally wait outside the GUI event loop."""
        if not self.closed:
            self.closed = True
            if self.tracker is not None:
                self.tracker.track('app_exit', interface='qt')
                self._pending.append((self.tracker, self._executor.submit(self.tracker.flush)))
        self._executor.shutdown(wait=wait)
