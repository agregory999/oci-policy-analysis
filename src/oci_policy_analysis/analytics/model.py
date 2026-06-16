##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/model.py
#
# Read-side data model for anonymous usage tracking documents written by
# oci_policy_analysis.application.core.support.usage_tracking. Provides defensive parsing
# helpers that keep a single malformed document or item from breaking
# analytics loading.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Read-side models for usage analytics.

The structures in this module intentionally mirror the JSON shape produced
by :mod:`oci_policy_analysis.application.core.support.usage_tracking`, but with parsed
datetimes and a derived tenancy suffix attached at the document level.

All ``from_dict`` helpers are defensive: they log and return ``None`` when
encountering malformed data instead of raising.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='analytics.model')


def _parse_iso_dt(value: Any, *, field_name: str) -> datetime | None:
    """Best-effort ISO8601 datetime parser.

    Returns ``None`` and logs at DEBUG if parsing fails.
    """

    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        logger.debug('Expected str for %s, got %r', field_name, type(value))
        return None
    try:
        # usage_tracking uses datetime.now(UTC).isoformat(), which includes
        # offset information. fromisoformat handles this in 3.12.
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        logger.debug('Failed to parse datetime for %s: %r', field_name, value)
        return None


@dataclass
class UsageEvent:
    """Single usage event captured during a run (read model)."""

    event_type: str
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> UsageEvent | None:
        """Create a :class:`UsageEvent` from a raw dict.

        Returns ``None`` if mandatory fields are missing or invalid.
        """

        if not isinstance(raw, dict):  # defensive
            logger.debug('UsageEvent.from_dict expected dict, got %r', type(raw))
            return None

        event_type = raw.get('event_type')
        ts_raw = raw.get('ts')
        if not isinstance(event_type, str):
            logger.debug('UsageEvent missing/invalid event_type: %r', raw)
            return None

        ts = _parse_iso_dt(ts_raw, field_name='UsageEvent.ts')
        if ts is None:
            return None

        payload = raw.get('payload')
        if not isinstance(payload, dict):
            payload = {}

        return cls(event_type=event_type, ts=ts, payload=payload)


@dataclass
class UsageOperation:
    """Single high-level operation captured during a run (read model)."""

    op_type: str
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> UsageOperation | None:
        """Create a :class:`UsageOperation` from a raw dict.

        Returns ``None`` if mandatory fields are missing or invalid.
        """

        if not isinstance(raw, dict):
            logger.debug('UsageOperation.from_dict expected dict, got %r', type(raw))
            return None

        op_type = raw.get('op_type')
        ts_raw = raw.get('ts')
        if not isinstance(op_type, str):
            logger.debug('UsageOperation missing/invalid op_type: %r', raw)
            return None

        ts = _parse_iso_dt(ts_raw, field_name='UsageOperation.ts')
        if ts is None:
            return None

        payload = raw.get('payload')
        if not isinstance(payload, dict):
            payload = {}

        return cls(op_type=op_type, ts=ts, payload=payload)


@dataclass
class UsageDoc:
    """Single usage document corresponding to one app run."""

    run_id: str
    app_version: str
    started_at: datetime
    ended_at: datetime | None
    os: str
    python: str
    tenancy_suffix: str | None
    events: list[UsageEvent] = field(default_factory=list)
    operations: list[UsageOperation] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        tenancy_suffix: str | None,
    ) -> UsageDoc | None:
        """Create a :class:`UsageDoc` from a raw document dict.

        Returns ``None`` if core fields cannot be parsed. Individual events
        and operations are parsed best-effort and filtered.
        """

        if not isinstance(raw, dict):
            logger.debug('UsageDoc.from_dict expected dict, got %r', type(raw))
            return None

        run_id = raw.get('run_id')
        app_version = raw.get('app_version')
        started_raw = raw.get('started_at')
        ended_raw = raw.get('ended_at')
        os_name = raw.get('os')
        python_ver = raw.get('python')

        if not isinstance(run_id, str) or not isinstance(app_version, str):
            logger.debug('UsageDoc missing run_id/app_version: %r', raw)
            return None

        started_at = _parse_iso_dt(started_raw, field_name='UsageDoc.started_at')
        if started_at is None:
            return None

        ended_at = None
        if ended_raw is not None:
            ended_at = _parse_iso_dt(ended_raw, field_name='UsageDoc.ended_at')

        if not isinstance(os_name, str):
            os_name = 'unknown'
        if not isinstance(python_ver, str):
            python_ver = 'unknown'

        events_raw: Iterable[dict[str, Any]] = raw.get('events') or []
        operations_raw: Iterable[dict[str, Any]] = raw.get('operations') or []

        events: list[UsageEvent] = []
        for item in events_raw:
            ev = UsageEvent.from_dict(item)
            if ev is not None:
                events.append(ev)

        operations: list[UsageOperation] = []
        for item in operations_raw:
            op = UsageOperation.from_dict(item)
            if op is not None:
                operations.append(op)

        return cls(
            run_id=run_id,
            app_version=app_version,
            started_at=started_at,
            ended_at=ended_at,
            os=os_name,
            python=python_ver,
            tenancy_suffix=tenancy_suffix,
            events=events,
            operations=operations,
        )


@dataclass
class AnalyticsState:
    """Container for loaded usage documents and future aggregates."""

    docs: list[UsageDoc] = field(default_factory=list)
