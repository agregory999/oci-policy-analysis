##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/aggregator.py
#
# Pure aggregation helpers for usage analytics. These functions operate on
# in-memory UsageDoc instances and return simple data structures suitable
# for binding into the Tkinter UI.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Aggregation helpers for usage analytics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime

from oci_policy_analysis.common.logger import get_logger

from .model import UsageDoc

logger = get_logger(component='analytics.aggregator')


def _safe_date(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    return dt.date()


def compute_overview_metrics(docs: Iterable[UsageDoc]) -> dict:
    """Compute high-level overview metrics from usage documents."""

    docs_list = list(docs)
    total_runs = len(docs_list)
    tenancies = {doc.tenancy_suffix for doc in docs_list if doc.tenancy_suffix}

    started_dates = [d for d in (_safe_date(doc.started_at) for doc in docs_list) if d is not None]
    ended_dates = [d for d in (_safe_date(doc.ended_at) for doc in docs_list) if d is not None]

    first_started = min(started_dates) if started_dates else None
    last_ended = max(ended_dates) if ended_dates else None

    os_distribution: Counter[str] = Counter(doc.os for doc in docs_list if doc.os)
    python_distribution: Counter[str] = Counter(doc.python for doc in docs_list if doc.python)
    app_version_distribution: Counter[str] = Counter(doc.app_version for doc in docs_list if doc.app_version)

    overview = {
        'total_runs': total_runs,
        'distinct_tenancies': len(tenancies),
        'first_started': first_started,
        'last_ended': last_ended,
        'os_distribution': os_distribution,
        'python_distribution': python_distribution,
        'app_version_distribution': app_version_distribution,
    }

    logger.debug('Overview metrics: runs=%d, tenancies=%d', overview['total_runs'], overview['distinct_tenancies'])
    return overview


@dataclass
class TenancyMetrics:
    """Aggregated metrics per tenancy suffix."""

    tenancy_suffix: str
    run_count: int = 0
    first_seen: date | None = None
    last_seen: date | None = None
    app_versions: Counter[str] = field(default_factory=Counter)


def compute_tenancy_metrics(docs: Iterable[UsageDoc]) -> dict[str, TenancyMetrics]:
    """Compute aggregated metrics per tenancy suffix."""

    metrics: dict[str, TenancyMetrics] = {}
    for doc in docs:
        suffix = doc.tenancy_suffix or 'unknown'
        tm = metrics.get(suffix)
        if tm is None:
            tm = TenancyMetrics(tenancy_suffix=suffix)
            metrics[suffix] = tm

        tm.run_count += 1
        started_date = _safe_date(doc.started_at)
        if started_date is not None:
            if tm.first_seen is None or started_date < tm.first_seen:
                tm.first_seen = started_date
            if tm.last_seen is None or started_date > tm.last_seen:
                tm.last_seen = started_date

        if doc.app_version:
            tm.app_versions[doc.app_version] += 1

    logger.debug('Computed tenancy metrics for %d tenancies', len(metrics))
    return metrics


@dataclass
class TabUsageMetrics:
    """Aggregated usage metrics for a single UI tab.

    ``tab_name`` is the high-level tab identifier (class name) recorded by
    the main UI :meth:`App._on_tab_changed` handler.
    """

    tab_name: str
    count: int = 0
    first_seen: date | None = None
    last_seen: date | None = None


def compute_tab_usage_metrics(docs: Iterable[UsageDoc]) -> dict[str, TabUsageMetrics]:
    """Compute tab usage metrics from tab_change events."""

    metrics: dict[str, TabUsageMetrics] = {}

    for doc in docs:
        for event in doc.events:
            if event.event_type != 'tab_change':
                continue
            tab_name = str(event.payload.get('tab_name', '<unknown>'))
            tm = metrics.get(tab_name)
            if tm is None:
                tm = TabUsageMetrics(tab_name=tab_name)
                metrics[tab_name] = tm

            tm.count += 1
            event_date = _safe_date(event.ts)
            if event_date is not None:
                if tm.first_seen is None or event_date < tm.first_seen:
                    tm.first_seen = event_date
                if tm.last_seen is None or event_date > tm.last_seen:
                    tm.last_seen = event_date

    logger.debug('Computed tab usage metrics for %d tabs', len(metrics))
    return metrics


@dataclass
class SubtabUsageMetrics:
    """Aggregated usage metrics for a sub-view within a parent tab.

    This is primarily used for the PolicyRecommendationsTab notebook
    subtabs (Risk, Overlap, Consolidation, Cleanup, Limits, Workbench),
    but is generic enough for any ``tab_change`` event that includes a
    ``sub_view`` payload field.
    """

    parent_tab: str
    sub_view: str
    count: int = 0
    first_seen: date | None = None
    last_seen: date | None = None


def compute_subtab_usage_metrics(docs: Iterable[UsageDoc]) -> dict[tuple[str, str], SubtabUsageMetrics]:
    """Compute subtab/sub-view usage metrics from ``tab_change`` events.

    Looks for events with ``event_type == 'tab_change'`` that include a
    ``sub_view`` field in the payload. Parent tab is derived from the
    existing ``tab_name`` payload used by the main UI.
    """

    metrics: dict[tuple[str, str], SubtabUsageMetrics] = {}

    for doc in docs:
        for event in doc.events:
            if event.event_type != 'tab_change':
                continue
            parent = str(event.payload.get('tab_name', '<unknown>'))
            sub = str(event.payload.get('sub_view', '')).strip()
            if not sub:
                continue
            key = (parent, sub)
            tm = metrics.get(key)
            if tm is None:
                tm = SubtabUsageMetrics(parent_tab=parent, sub_view=sub)
                metrics[key] = tm

            tm.count += 1
            event_date = _safe_date(event.ts)
            if event_date is not None:
                if tm.first_seen is None or event_date < tm.first_seen:
                    tm.first_seen = event_date
                if tm.last_seen is None or event_date > tm.last_seen:
                    tm.last_seen = event_date

    logger.debug('Computed subtab usage metrics for %d (parent, sub_view) pairs', len(metrics))
    return metrics


def compute_operation_summaries(docs: Iterable[UsageDoc]) -> dict[str, int]:
    """Return a summary count of operations by type across all documents."""

    counter: Counter[str] = Counter()
    for doc in docs:
        for op in doc.operations:
            if not op.op_type:
                continue
            counter[op.op_type] += 1

    logger.debug('Computed operation summaries for %d operation types', len(counter))
    # Convert to a plain dict for easier use/logging.
    return dict(counter)


def compute_mcp_tool_usage(docs: Iterable[UsageDoc]) -> dict[str, int]:
    """Summarize MCP tool usage by tool name.

    Looks for operations with ``op_type == 'mcp_tool'`` and groups them by
    the non-personal ``tool_name`` field in the payload. Older documents or
    runs without MCP activity will simply not contribute to these counts.
    """

    counter: Counter[str] = Counter()
    for doc in docs:
        for op in doc.operations:
            if op.op_type != 'mcp_tool':
                continue
            tool_name = str(op.payload.get('tool_name', 'unknown'))
            counter[tool_name] += 1

    logger.debug('Computed MCP tool usage for %d tools', len(counter))
    return dict(counter)


def compute_data_load_sources(docs: Iterable[UsageDoc]) -> dict[str, int]:
    """Summarize data load operations by source.

    Looks for operations with ``op_type == 'data_load'`` and groups them by the
    non-personal ``source`` field in the payload (e.g. ``live``, ``cache``,
    ``compliance``, ``json_file``). Older documents that do not contain
    ``data_load`` operations will simply not contribute to these counts.
    """

    counter: Counter[str] = Counter()
    for doc in docs:
        for op in doc.operations:
            if op.op_type != 'data_load':
                continue
            src = str(op.payload.get('source', 'unknown'))
            counter[src] += 1

    logger.debug('Computed data load source summaries for %d sources', len(counter))
    return dict(counter)


def compute_tenancy_source_metrics(docs: Iterable[UsageDoc]) -> dict[tuple[str, str], int]:
    """Summarize web operation counts by (tenancy_suffix, source).

    This supports a tenancy tab view where source is part of the composite key.
    Only ``web_operation`` records are considered.
    """

    counter: Counter[tuple[str, str]] = Counter()
    for doc in docs:
        tenancy = str(getattr(doc, 'tenancy_suffix', '') or '').strip() or 'unknown'
        for op in doc.operations:
            if op.op_type != 'web_operation':
                continue
            source = str(op.payload.get('source', '')).strip() or 'n/a'
            counter[(tenancy, source)] += 1

    logger.debug('Computed tenancy/source metrics for %d composite keys', len(counter))
    return dict(counter)


@dataclass
class AiAssistSummary:
    """Aggregated AI assist metrics across all runs.

    All fields are non-personal and derived solely from anonymous
    UsageOperation payloads.
    """

    total_calls: int = 0
    success_count: int = 0
    failure_count: int = 0
    # Average duration in milliseconds across all calls (best-effort)
    avg_duration_ms: float | None = None
    # Distribution of calls by model and by originating tab
    by_model: dict[str, int] = field(default_factory=dict)
    by_tab: dict[str, int] = field(default_factory=dict)


def compute_ai_assist_summary(docs: Iterable[UsageDoc]) -> AiAssistSummary:
    """Compute high-level metrics for ``ai_assist`` operations.

    Aggregates counts, success rate, average duration, and simple
    breakdowns by model and tab.
    """

    by_model: Counter[str] = Counter()
    by_tab: Counter[str] = Counter()

    total_calls = 0
    success_count = 0
    failure_count = 0
    durations: list[float] = []

    for doc in docs:
        for op in doc.operations:
            if op.op_type != 'ai_assist':
                continue

            total_calls += 1

            success = bool(op.payload.get('success', False))
            if success:
                success_count += 1
            else:
                failure_count += 1

            model = str(op.payload.get('model', 'unknown'))
            by_model[model] += 1

            tab = str(op.payload.get('tab', 'unknown'))
            by_tab[tab] += 1

            dur = op.payload.get('duration_ms')
            # Best-effort conversion; ignore values that cannot be parsed
            # as non-negative floats.
            try:
                dur_ms = float(dur) if dur is not None else None
            except (TypeError, ValueError):
                dur_ms = None
            if dur_ms is not None and dur_ms >= 0:
                durations.append(dur_ms)

    avg_duration_ms: float | None = None
    if durations:
        avg_duration_ms = sum(durations) / len(durations)

    summary = AiAssistSummary(
        total_calls=total_calls,
        success_count=success_count,
        failure_count=failure_count,
        avg_duration_ms=avg_duration_ms,
        by_model=dict(by_model),
        by_tab=dict(by_tab),
    )

    logger.debug(
        'Computed AI assist summary: calls=%d, success=%d, failure=%d',
        summary.total_calls,
        summary.success_count,
        summary.failure_count,
    )
    return summary


@dataclass
class McpToolSummary:
    """Aggregated MCP tool usage metrics across all runs."""

    total_invocations: int = 0
    # Counts by tool name
    by_tool: dict[str, int] = field(default_factory=dict)
    # Optional success/failure breakdown where available
    success_by_tool: dict[str, int] = field(default_factory=dict)
    failure_by_tool: dict[str, int] = field(default_factory=dict)


@dataclass
class WebTrafficSummary:
    """Aggregated web traffic metrics from ``web_operation`` events."""

    total_ops: int = 0
    by_route: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_tenancy_suffix: dict[str, int] = field(default_factory=dict)
    by_route_status: dict[tuple[str, str], int] = field(default_factory=dict)
    avg_duration_ms_by_route_status: dict[tuple[str, str], float] = field(default_factory=dict)
    by_tenancy_route_status: dict[tuple[str, str, str], int] = field(default_factory=dict)
    by_page: dict[str, int] = field(default_factory=dict)


def compute_mcp_tool_summary(docs: Iterable[UsageDoc]) -> McpToolSummary:
    """Compute high-level metrics for ``mcp_tool`` operations.

    Uses ``payload.tool_name`` as the grouping key. If a ``status`` field
    is present in the payload (e.g. "success" / "error"), it is used to
    derive simple success/failure counts.
    """

    by_tool: Counter[str] = Counter()
    success_by_tool: Counter[str] = Counter()
    failure_by_tool: Counter[str] = Counter()

    total_invocations = 0

    for doc in docs:
        for op in doc.operations:
            if op.op_type != 'mcp_tool':
                continue

            total_invocations += 1
            name = str(op.payload.get('tool_name', 'unknown'))
            by_tool[name] += 1

            status = str(op.payload.get('status', ''))
            if status.lower() in {'success', 'ok'}:
                success_by_tool[name] += 1
            elif status:
                # Treat any non-empty, non-success status as failure.
                failure_by_tool[name] += 1

    summary = McpToolSummary(
        total_invocations=total_invocations,
        by_tool=dict(by_tool),
        success_by_tool=dict(success_by_tool),
        failure_by_tool=dict(failure_by_tool),
    )

    logger.debug(
        'Computed MCP tool summary: tools=%d, invocations=%d',
        len(summary.by_tool),
        summary.total_invocations,
    )
    return summary


def compute_web_traffic_summary(docs: Iterable[UsageDoc]) -> WebTrafficSummary:
    """Compute high-level metrics for web traffic operations.

    Looks for ``op_type == 'web_operation'`` records and summarizes route,
    status, source, and tenancy hash counts.
    """

    by_route: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_tenancy_suffix: Counter[str] = Counter()
    by_route_status: Counter[tuple[str, str]] = Counter()
    by_tenancy_route_status: Counter[tuple[str, str, str]] = Counter()
    by_page: Counter[str] = Counter()
    duration_sum_by_route_status: dict[tuple[str, str], float] = {}
    duration_count_by_route_status: Counter[tuple[str, str]] = Counter()
    total_ops = 0

    for doc in docs:
        for op in doc.operations:
            if op.op_type != 'web_operation':
                continue
            total_ops += 1
            route = str(op.payload.get('route', 'unknown'))
            status = str(op.payload.get('status', 'unknown'))
            source = str(op.payload.get('source', '')).strip()
            tenancy_suffix = str(getattr(doc, 'tenancy_suffix', '') or '').strip() or 'unknown'
            route_status = (route, status)
            page = str(op.payload.get('page', '')).strip() or 'other'

            by_route[route] += 1
            by_status[status] += 1
            by_route_status[route_status] += 1
            by_tenancy_route_status[(tenancy_suffix, route, status)] += 1
            by_tenancy_suffix[tenancy_suffix] += 1
            by_page[page] += 1
            if source:
                by_source[source] += 1
            duration_val = op.payload.get('duration_ms')
            try:
                if duration_val is not None:
                    duration_ms = float(duration_val)
                    if duration_ms >= 0:
                        duration_sum_by_route_status[route_status] = (
                            duration_sum_by_route_status.get(route_status, 0.0) + duration_ms
                        )
                        duration_count_by_route_status[route_status] += 1
            except (TypeError, ValueError):
                pass

    avg_duration_ms_by_route_status: dict[tuple[str, str], float] = {}
    for key, total_ms in duration_sum_by_route_status.items():
        cnt = int(duration_count_by_route_status.get(key, 0))
        if cnt > 0:
            avg_duration_ms_by_route_status[key] = total_ms / cnt

    return WebTrafficSummary(
        total_ops=total_ops,
        by_route=dict(by_route),
        by_status=dict(by_status),
        by_source=dict(by_source),
        by_tenancy_suffix=dict(by_tenancy_suffix),
        by_route_status=dict(by_route_status),
        avg_duration_ms_by_route_status=avg_duration_ms_by_route_status,
        by_tenancy_route_status=dict(by_tenancy_route_status),
        by_page=dict(by_page),
    )


__all__ = [
    'TenancyMetrics',
    'TabUsageMetrics',
    'SubtabUsageMetrics',
    'AiAssistSummary',
    'McpToolSummary',
    'WebTrafficSummary',
    'compute_overview_metrics',
    'compute_tenancy_metrics',
    'compute_tab_usage_metrics',
    'compute_subtab_usage_metrics',
    'compute_operation_summaries',
    'compute_mcp_tool_usage',
    'compute_data_load_sources',
    'compute_tenancy_source_metrics',
    'compute_ai_assist_summary',
    'compute_mcp_tool_summary',
    'compute_web_traffic_summary',
]
