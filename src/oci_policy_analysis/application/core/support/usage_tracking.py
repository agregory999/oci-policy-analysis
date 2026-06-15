##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# usage_tracking.py
#
# Lightweight, opt-in, non-personal usage tracking for the OCI Policy Analysis UI.
#
# - Tracks app/session lifecycle and high-level load/tab usage metrics only.
# - Never sends policy text, user names, resource OCIDs, or other sensitive content.
# - Uses a write-only Object Storage PAR owned by the tool author.
# - Writes a single JSON document per app run at shutdown containing all events.
# - All network/serialization failures are swallowed (best-effort only).
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

from __future__ import annotations

import json
import os
import platform
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib import error as urlerror
from urllib import request

from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='usage_tracking')


# Base PAR URL (write-only) provided by project owner. The actual object key
# will be appended to this base path per run, so each run is a distinct object.
#
# NOTE: This can be overridden at runtime using the
# OCI_POLICY_ANALYSIS_USAGE_PAR_URL environment variable if needed.

PAR_BASE_URL_DEFAULT = (
    'https://objectstorage.us-ashburn-1.oraclecloud.com/p/'
    'rLkvSya24knxp2fiI1q-iwKti7QCi1E__56peO3NFc51I_Qc91GcYZvIreVn8MgQ/'
    'n/idxhxzdpc23m/b/policy-analysis-tracking/o/'
)


def _get_par_base_url() -> str | None:
    """Return the base PAR URL for usage uploads, or None if disabled.

    Environment variable OCI_POLICY_ANALYSIS_USAGE_PAR_URL takes precedence
    over the built-in default so the project owner can rotate/change buckets
    without a code change.
    """

    override = os.environ.get('OCI_POLICY_ANALYSIS_USAGE_PAR_URL', '').strip()
    if override:
        return override
    return PAR_BASE_URL_DEFAULT or None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class UsageEvent:
    """Single usage event captured during a run.

    This is intentionally minimal and non-personal. Fields may be extended
    over time as needed, but MUST NOT include policy text, usernames,
    resource OCIDs, or other sensitive content.
    """

    event_type: str
    ts: str
    # app_version, run_id, and tenancy_suffix are recorded at the
    # UsageRunDocument level and are also encoded into the object
    # name (tenancy suffix + run_id). They are intentionally omitted
    # from individual events to keep the per-event payload minimal.
    #
    # Historical data in Object Storage will still contain these
    # fields in each event; new uploads will not.
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageOperation:
    """Single high-level operation captured during a run.

    Operations represent *meaningful actions* the user performs, such as
    simulation runs. They are tracked separately from lightweight UI events
    (tab changes, loads, etc.) so that analytics can focus on feature usage
    without overloading the event stream.

    IMPORTANT: As with UsageEvent, this payload must never contain policy
    text, usernames, full tenancy OCIDs, or other sensitive content. Only
    non-personal aggregates and identifiers (like internal ids) are allowed.
    """

    op_type: str
    ts: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageRunDocument:
    """Document persisted per app run.

    Written as a single JSON object to Object Storage using the configured
    write-only PAR. Contains high-level metadata plus the list of events and
    operations.
    """

    run_id: str
    app_version: str
    started_at: str
    ended_at: str | None
    os: str
    python: str
    events: list[UsageEvent] = field(default_factory=list)
    operations: list[UsageOperation] = field(default_factory=list)


class UsageTracker:
    """In-memory usage tracker for a single app run.

    Thread-safe for simple add/flush operations. All network failures are
    swallowed and logged at INFO/DEBUG only.
    """

    def __init__(self, enabled: bool, app_version: str):
        self.enabled = enabled
        self.app_version = app_version
        self.run_id = str(uuid.uuid4())
        self.started_at = _utc_now_iso()
        self.ended_at: str | None = None
        self.tenancy_suffix: str | None = None
        self._events: list[UsageEvent] = []
        self._operations: list[UsageOperation] = []
        self._lock = threading.Lock()
        self._flushed = False

    # --- public API ---

    def set_tenancy_suffix(self, tenancy_suffix: str | None) -> None:
        """Set or update the tenancy suffix (last 6 of tenancy OCID).

        Safe to call multiple times. If a different tenancy is detected after
        events have already been recorded, this will flush the current run
        document and start a new run for the new tenancy. That way mid-flight
        tenancy changes produce separate usage files per tenancy.
        """
        if not tenancy_suffix:
            return

        with self._lock:
            # If this is the first tenancy for this tracker, just set it.
            if self.tenancy_suffix is None:
                self.tenancy_suffix = tenancy_suffix
                return

            # If the tenancy is unchanged, nothing to do.
            if self.tenancy_suffix == tenancy_suffix:
                return

            # Tenancy change detected. If we already have events for the
            # previous tenancy, flush them as a completed run before
            # resetting. This ensures usage is tracked in separate files
            # per-tenancy when users switch mid-session.
            if self._events:
                try:
                    logger.warning(
                        'Usage tracking: tenancy suffix changed from %s to %s; flushing current run and starting new',
                        self.tenancy_suffix,
                        tenancy_suffix,
                    )
                    # Temporarily release the lock while flushing to avoid
                    # deadlocks; flush itself takes a copy of events under
                    # its own lock.
                finally:
                    pass
            # Flush outside the inner lock to avoid re-entrant locking
        # Call flush() without holding the lock (it manages its own locking)
        if self._events:
            self.flush()

        # Start a new run for the new tenancy
        with self._lock:
            self.run_id = str(uuid.uuid4())
            self.started_at = _utc_now_iso()
            self.ended_at = None
            self.tenancy_suffix = tenancy_suffix
            self._events = []
            self._flushed = False
            logger.warning('Usage tracking: started new run for tenancy suffix %s', tenancy_suffix)

    def track(self, event_type: str, **payload: Any) -> None:
        """Record a usage event if tracking is enabled.

        This is intentionally lightweight and never raises.
        """

        if not self.enabled:
            return
        try:
            ev = UsageEvent(
                event_type=event_type,
                ts=_utc_now_iso(),
                payload=payload or {},
            )
            with self._lock:
                self._events.append(ev)
        except Exception:
            # Silent failure is acceptable; log at DEBUG only.
            logger.debug('UsageTracker.track failed', exc_info=True)

    def track_operation(self, op_type: str, **payload: Any) -> None:
        """Record a high-level operation if tracking is enabled.

        This is a sibling to :meth:`track` but is intended for substantive
        user actions (e.g., simulation runs) rather than general UI events.

        The payload should contain only non-personal, aggregate metrics.
        """

        if not self.enabled:
            return
        try:
            op = UsageOperation(op_type=op_type, ts=_utc_now_iso(), payload=payload or {})
            with self._lock:
                self._operations.append(op)
            logger.info(
                'Usage tracking operation recorded: op_type=%s run_id=%s payload_keys=%s',
                op_type,
                self.run_id,
                sorted((payload or {}).keys()),
            )
        except Exception:
            logger.debug('UsageTracker.track_operation failed', exc_info=True)

    def flush(self) -> None:
        """Serialize and upload the run document via PAR.

        Safe to call multiple times; only the first successful call will
        attempt an upload. All errors are swallowed.
        """

        if not self.enabled:
            return

        with self._lock:
            if self._flushed:
                return
            self._flushed = True
            self.ended_at = self.ended_at or _utc_now_iso()
            events_copy = list(self._events)
            operations_copy = list(self._operations)

        base_url = _get_par_base_url()
        if not base_url:
            # Log at DEBUG so this never clutters normal logs; usage
            # tracking is strictly best-effort.
            logger.debug('Usage tracking PAR URL is not configured; skipping upload.')
            return

        # Build object key: events/YYYY/MM/DD/<tenancy|unknown>/<run_id>.json
        now = datetime.now(UTC)
        date_prefix = now.strftime('events/%Y/%m/%d')
        tenancy_part = self.tenancy_suffix or 'unknown'
        object_key = f'{date_prefix}/{tenancy_part}/{self.run_id}.json'
        full_url = base_url + object_key

        doc = UsageRunDocument(
            run_id=self.run_id,
            app_version=self.app_version,
            started_at=self.started_at,
            ended_at=self.ended_at,
            os=platform.platform(),
            python=platform.python_version(),
            events=events_copy,
            operations=operations_copy,
        )

        try:
            body = json.dumps(asdict(doc), ensure_ascii=False).encode('utf-8')
            req = request.Request(full_url, data=body, method='PUT')
            req.add_header('Content-Type', 'application/json')
            logger.info(
                'Usage tracking flush: uploading run_id=%s events=%d operations=%d object_key=%s',
                self.run_id,
                len(events_copy),
                len(operations_copy),
                object_key,
            )
            # Use a fairly short timeout so app shutdown never feels slow
            # if the tracking endpoint is unreachable (e.g., offline).
            with request.urlopen(req, timeout=3) as resp:  # noqa: S310
                logger.info(
                    'Usage tracking upload succeeded: status=%s run_id=%s',
                    getattr(resp, 'status', 'unknown'),
                    self.run_id,
                )
        except (urlerror.URLError, OSError, ValueError) as e:
            # Swallow all network/serialization errors; this must never impact
            # the main app experience.
            logger.info('Usage tracking upload failed: run_id=%s error=%s', self.run_id, e)
        except Exception as e:  # pragma: no cover - defensive catch-all
            logger.info('Unexpected error during usage tracking upload: run_id=%s error=%s', self.run_id, e)


# Global singleton, initialized from main.App using init_usage_tracker.
_tracker: UsageTracker | None = None


def init_usage_tracker(settings: dict, app_version: str) -> UsageTracker | None:
    """Initialize the global UsageTracker from settings.

    Returns the tracker instance or None if disabled.
    """

    enabled = bool(settings.get('usage_tracking_enabled', False))
    global _tracker
    if not enabled:
        logger.info('Usage tracking is disabled in settings.')
        _tracker = None
        return None

    _tracker = UsageTracker(enabled=True, app_version=app_version)
    logger.info('Usage tracking initialized (run_id=%s)', _tracker.run_id)
    return _tracker


def get_usage_tracker() -> UsageTracker | None:
    """Return the global UsageTracker instance if initialized."""

    return _tracker
