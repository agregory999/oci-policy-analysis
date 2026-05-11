##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/ui.py
#
# Tkinter tab implementations for the standalone usage analytics UI. Tabs
# reuse the shared BaseUITab component for consistent look-and-feel with the
# main OCI Policy Analysis application.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""UI components for the usage analytics notebook."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterable
from datetime import date
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.ui.base_tab import BaseUITab

from .aggregator import (
    AiAssistSummary,
    McpToolSummary,
    SubtabUsageMetrics,
    TabUsageMetrics,
    TenancyMetrics,
    WebTrafficSummary,
)
from .model import UsageDoc

logger = get_logger(component='analytics.ui')


def _format_date_range(start: date | None, end: date | None) -> str:
    if start is None and end is None:
        return '(n/a)'
    if start is None:
        return f'to {end}'
    if end is None:
        return f'from {start}'
    return f'{start} to {end}'


class OverviewTab(BaseUITab):
    """Overview metrics and recent runs table."""

    def __init__(self, parent: tk.Widget):
        # BaseUITab does not accept a "title" kwarg; pass only the supported
        # parameters and build the body directly on ``self``.
        super().__init__(parent, default_help_text='High-level usage metrics.')

        body = self

        # Summary labels
        self.total_runs_var = tk.StringVar(value='Total runs: 0')
        self.tenancies_var = tk.StringVar(value='Distinct tenancies: 0')
        self.date_range_var = tk.StringVar(value='Date range: (n/a)')

        summary_frame = ttk.Frame(body)
        summary_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)

        ttk.Label(summary_frame, textvariable=self.total_runs_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(summary_frame, textvariable=self.tenancies_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(summary_frame, textvariable=self.date_range_var).pack(side=tk.LEFT, padx=4)

        # Recent runs table (include data load source column)
        columns = ('tenancy', 'started', 'duration', 'version', 'os', 'python', 'load_source')
        tree = ttk.Treeview(body, columns=columns, show='headings', height=20)
        tree.heading('tenancy', text='Tenancy suffix')
        tree.heading('started', text='Started')
        tree.heading('duration', text='Duration')
        tree.heading('version', text='App version')
        tree.heading('os', text='OS')
        tree.heading('python', text='Python')
        tree.heading('load_source', text='Load source')

        tree.column('tenancy', width=140, anchor='w')
        tree.column('started', width=160, anchor='w')
        tree.column('duration', width=140, anchor='w')
        tree.column('version', width=100, anchor='w')
        tree.column('os', width=220, anchor='w')
        tree.column('python', width=100, anchor='w')
        tree.column('load_source', width=120, anchor='w')

        scrollbar = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=4)

        self.tree = tree

    # Public API used by AnalyticsApp
    def refresh(
        self, overview_metrics: dict, docs: Iterable[UsageDoc], load_sources: dict[str, int] | None = None
    ) -> None:
        """Refresh labels and recent runs table from metrics and documents.

        ``load_sources`` is an optional mapping of data load sources (live,
        cache, compliance, json_file, etc.) to counts. Older usage documents
        that predate load-source tracking will not contribute to this mapping;
        in that case, the UI will show ``n/a`` for the load source summary.
        """

        docs_list = list(docs)
        total_runs = overview_metrics.get('total_runs', len(docs_list))
        distinct_tenancies = overview_metrics.get('distinct_tenancies', 0)
        first_started = overview_metrics.get('first_started')
        last_ended = overview_metrics.get('last_ended')

        self.total_runs_var.set(f'Total runs: {total_runs}')
        self.tenancies_var.set(f'Distinct tenancies: {distinct_tenancies}')
        # Build a compact load-source summary string.
        summary = 'n/a'
        if load_sources:
            parts = [f'{k}={v}' for k, v in sorted(load_sources.items())]
            summary = ', '.join(parts)
        self.date_range_var.set(
            f'Date range: {_format_date_range(first_started, last_ended)}  |  Load sources: {summary}'
        )

        # Populate recent runs (latest first), capped at 50.
        for item in self.tree.get_children():
            self.tree.delete(item)

        sorted_docs = sorted(docs_list, key=lambda d: d.started_at, reverse=True)[:50]
        for doc in sorted_docs:
            tenancy = doc.tenancy_suffix or 'unknown'
            started = doc.started_at.isoformat(sep=' ') if doc.started_at else ''
            # Derive a simple duration string when possible.
            duration = '(unknown)'
            started_at = getattr(doc, 'started_at', None)
            ended_at = getattr(doc, 'ended_at', None)
            if started_at is not None and ended_at is not None:
                delta = ended_at - started_at
                total_seconds = int(delta.total_seconds())
                if total_seconds < 0:
                    duration = '(invalid)'
                else:
                    hours, rem = divmod(total_seconds, 3600)
                    minutes, seconds = divmod(rem, 60)
                    if hours:
                        duration = f'{hours:d}h {minutes:02d}m'
                    elif minutes:
                        duration = f'{minutes:d}m {seconds:02d}s'
                    else:
                        duration = f'{seconds:d}s'
            # Derive load source from operations, if any; fall back to "n/a" for older docs.
            load_src = 'n/a'
            for op in doc.operations:
                if getattr(op, 'op_type', None) == 'data_load':
                    load_src = str(op.payload.get('source', 'unknown'))
                    break

            values = (tenancy, started, duration, doc.app_version, doc.os, doc.python, load_src)
            self.tree.insert('', 'end', values=values)


class TenancyTab(BaseUITab):
    """Aggregated metrics per tenancy suffix."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent, default_help_text='Usage grouped by tenancy suffix.')

        body = self

        columns = ('tenancy', 'source', 'runs', 'first', 'last', 'versions')
        tree = ttk.Treeview(body, columns=columns, show='headings', height=20)
        tree.heading('tenancy', text='Tenancy suffix')
        tree.heading('source', text='Source')
        tree.heading('runs', text='Run count')
        tree.heading('first', text='First seen')
        tree.heading('last', text='Last seen')
        tree.heading('versions', text='App versions')

        tree.column('tenancy', width=160, anchor='w')
        tree.column('source', width=120, anchor='w')
        tree.column('runs', width=80, anchor='e')
        tree.column('first', width=120, anchor='w')
        tree.column('last', width=120, anchor='w')
        tree.column('versions', width=400, anchor='w')

        scrollbar = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=4)

        self.tree = tree

    def refresh(
        self,
        tenancy_metrics: dict[str, TenancyMetrics],
        tenancy_source_metrics: dict[tuple[str, str], int] | None = None,
    ) -> None:
        """Refresh the tenancy metrics table."""

        for item in self.tree.get_children():
            self.tree.delete(item)

        if tenancy_source_metrics:
            rows = sorted(
                tenancy_source_metrics.items(),
                key=lambda kv: (-int(kv[1]), kv[0][0], kv[0][1]),
            )
            for (tenancy, source), count in rows:
                tm = tenancy_metrics.get(tenancy)
                versions_str = ', '.join(f'{ver} ({c})' for ver, c in tm.app_versions.most_common()) if tm else ''
                first_seen = tm.first_seen if tm else ''
                last_seen = tm.last_seen if tm else ''
                self.tree.insert('', 'end', values=(tenancy, source, count, first_seen, last_seen, versions_str))
            return

        rows = sorted(tenancy_metrics.values(), key=lambda tm: int(tm.run_count), reverse=True)
        for tm in rows:
            versions_str = ', '.join(f'{ver} ({count})' for ver, count in tm.app_versions.most_common())
            values = (tm.tenancy_suffix, 'n/a', tm.run_count, tm.first_seen or '', tm.last_seen or '', versions_str)
            self.tree.insert('', 'end', values=values)


class TabUsageTab(BaseUITab):
    """Aggregated tab usage metrics."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent, default_help_text='Tab change counts by tab name.')

        body = self
        columns = ('tab', 'count', 'first', 'last')
        tree = ttk.Treeview(body, columns=columns, show='headings', height=20)
        tree.heading('tab', text='Tab name')
        tree.heading('count', text='Tab changes')
        tree.heading('first', text='First seen')
        tree.heading('last', text='Last seen')

        tree.column('tab', width=240, anchor='w')
        tree.column('count', width=100, anchor='e')
        tree.column('first', width=120, anchor='w')
        tree.column('last', width=120, anchor='w')

        scrollbar = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=4)

        self.tree = tree

    def refresh(self, tab_metrics: dict[str, TabUsageMetrics]) -> None:
        """Refresh the tab usage metrics table."""

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Sort descending by count so most-used tabs are at the top.
        rows = sorted(tab_metrics.values(), key=lambda tm: tm.count, reverse=True)
        for tm in rows:
            values = (
                tm.tab_name,
                tm.count,
                tm.first_seen or '',
                tm.last_seen or '',
            )
            self.tree.insert('', 'end', values=values)


class SubtabUsageTab(BaseUITab):
    """Aggregated subtab/sub-view usage metrics.

    This tab focuses on sub-views within higher-level tabs, such as the
    notebook subtabs inside PolicyRecommendationsTab. It expects metrics
    keyed by (parent_tab, sub_view).
    """

    def __init__(self, parent: tk.Widget):
        super().__init__(
            parent,
            default_help_text=(
                'Subtab and sub-view usage (e.g. PolicyRecommendationsTab subtabs). '
                'Counts are based on tab_change events that include a sub_view payload.'
            ),
        )

        body = self

        columns = ('parent', 'sub_view', 'count', 'first', 'last')
        tree = ttk.Treeview(body, columns=columns, show='headings', height=20)
        tree.heading('parent', text='Parent tab')
        tree.heading('sub_view', text='Subtab / view')
        tree.heading('count', text='Changes')
        tree.heading('first', text='First seen')
        tree.heading('last', text='Last seen')

        tree.column('parent', width=220, anchor='w')
        tree.column('sub_view', width=280, anchor='w')
        tree.column('count', width=90, anchor='e')
        tree.column('first', width=120, anchor='w')
        tree.column('last', width=120, anchor='w')

        scrollbar = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=4)

        self.tree = tree

    def refresh(self, subtab_metrics: dict[tuple[str, str], SubtabUsageMetrics]) -> None:
        """Refresh the subtab usage metrics table."""

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Sort primarily by parent tab name, then by descending count.
        def _sort_key(tm: SubtabUsageMetrics) -> tuple[str, int]:
            parent = tm.parent_tab or ''
            # Use negative count for descending sort; fall back to 0 defensively.
            cnt = int(tm.count) if isinstance(tm.count, int) else 0
            return (parent, -cnt)

        rows = sorted(subtab_metrics.values(), key=_sort_key)
        for tm in rows:
            values = (
                tm.parent_tab,
                tm.sub_view,
                tm.count,
                tm.first_seen or '',
                tm.last_seen or '',
            )
            self.tree.insert('', 'end', values=values)


class OperationsTab(BaseUITab):
    """High-level operation summaries, including MCP tool usage.

    This tab is intentionally simple: it shows counts per operation type
    and, for ``mcp_tool`` operations, a per-tool breakdown.
    """

    def __init__(self, parent: tk.Widget):
        super().__init__(
            parent,
            default_help_text=(
                'Operation summaries across all runs (op_type counts and MCP tool usage). '
                'Use this to see which high-level operations and MCP tools are actually in use.'
            ),
        )

        body = self

        # Top: operation type summary table
        top_frame = ttk.Frame(body)
        top_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

        op_cols = ('op_type', 'count')
        op_tree = ttk.Treeview(top_frame, columns=op_cols, show='headings', height=8)
        op_tree.heading('op_type', text='Operation type')
        op_tree.heading('count', text='Total count')
        op_tree.column('op_type', width=220, anchor='w')
        op_tree.column('count', width=120, anchor='e')

        op_scroll = ttk.Scrollbar(top_frame, orient='vertical', command=op_tree.yview)
        op_tree.configure(yscrollcommand=op_scroll.set)

        op_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        op_scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

        self.op_tree = op_tree

        # Bottom: MCP tool usage table
        bottom_frame = ttk.LabelFrame(body, text='MCP tool usage')
        bottom_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        tool_cols = ('tool_name', 'count')
        tool_tree = ttk.Treeview(bottom_frame, columns=tool_cols, show='headings', height=8)
        tool_tree.heading('tool_name', text='Tool name')
        tool_tree.heading('count', text='Total invocations')
        tool_tree.column('tool_name', width=260, anchor='w')
        tool_tree.column('count', width=140, anchor='e')

        tool_scroll = ttk.Scrollbar(bottom_frame, orient='vertical', command=tool_tree.yview)
        tool_tree.configure(yscrollcommand=tool_scroll.set)

        tool_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        tool_scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

        self.tool_tree = tool_tree

    def refresh(self, op_summaries: dict[str, int], mcp_tool_usage: dict[str, int]) -> None:
        """Refresh operation and MCP tool summary tables."""

        # Operation types
        for item in self.op_tree.get_children():
            self.op_tree.delete(item)
        for op_type, count in sorted(op_summaries.items(), key=lambda kv: kv[0]):
            self.op_tree.insert('', 'end', values=(op_type, count))

        # MCP tools
        for item in self.tool_tree.get_children():
            self.tool_tree.delete(item)
        for name, count in sorted(mcp_tool_usage.items(), key=lambda kv: (-kv[1], kv[0])):
            self.tool_tree.insert('', 'end', values=(name, count))


class AiOperationsTab(BaseUITab):
    """AI assist usage metrics (filtered from operations).

    Shows total calls, success rate, average duration, and breakdowns
    by model and originating tab.
    """

    def __init__(self, parent: tk.Widget):
        super().__init__(
            parent,
            default_help_text=(
                'AI assist usage across all runs (calls, success rate, ' 'average duration, grouped by model and tab).'
            ),
        )

        body = self

        # Summary labels
        self.summary_var = tk.StringVar(value='AI calls: 0 | Success rate: n/a | Avg duration: n/a')
        summary_frame = ttk.Frame(body)
        summary_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        ttk.Label(summary_frame, textvariable=self.summary_var).pack(side=tk.LEFT, padx=4)

        # Bottom split: by model (left) and by tab (right)
        bottom = ttk.Frame(body)
        bottom.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # By model
        model_frame = ttk.LabelFrame(bottom, text='By model')
        model_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        model_cols = ('model', 'count')
        self.model_tree = ttk.Treeview(model_frame, columns=model_cols, show='headings', height=10)
        self.model_tree.heading('model', text='Model')
        self.model_tree.heading('count', text='Calls')
        self.model_tree.column('model', width=260, anchor='w')
        self.model_tree.column('count', width=80, anchor='e')

        model_scroll = ttk.Scrollbar(model_frame, orient='vertical', command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=model_scroll.set)

        self.model_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        model_scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

        # By tab
        tab_frame = ttk.LabelFrame(bottom, text='By tab')
        tab_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0))

        tab_cols = ('tab', 'count')
        self.tab_tree = ttk.Treeview(tab_frame, columns=tab_cols, show='headings', height=10)
        self.tab_tree.heading('tab', text='Tab')
        self.tab_tree.heading('count', text='Calls')
        self.tab_tree.column('tab', width=260, anchor='w')
        self.tab_tree.column('count', width=80, anchor='e')

        tab_scroll = ttk.Scrollbar(tab_frame, orient='vertical', command=self.tab_tree.yview)
        self.tab_tree.configure(yscrollcommand=tab_scroll.set)

        self.tab_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        tab_scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

    def refresh(self, summary: AiAssistSummary) -> None:
        """Refresh AI metrics from aggregator output."""

        total = summary.total_calls
        if total:
            success_rate = (summary.success_count / total) * 100.0
            success_str = f'{success_rate:.1f}%'
        else:
            success_str = 'n/a'

        if summary.avg_duration_ms is not None:
            avg_ms = summary.avg_duration_ms
            if avg_ms >= 1000.0:
                avg_str = f'{avg_ms / 1000.0:.2f}s'
            else:
                avg_str = f'{avg_ms:.0f}ms'
        else:
            avg_str = 'n/a'

        self.summary_var.set(f'AI calls: {total} | Success rate: {success_str} | Avg duration: {avg_str}')

        # By model
        for item in self.model_tree.get_children():
            self.model_tree.delete(item)
        for model, count in sorted(summary.by_model.items(), key=lambda kv: (-kv[1], kv[0])):
            self.model_tree.insert('', 'end', values=(model, count))

        # By tab
        for item in self.tab_tree.get_children():
            self.tab_tree.delete(item)
        for tab, count in sorted(summary.by_tab.items(), key=lambda kv: (-kv[1], kv[0])):
            self.tab_tree.insert('', 'end', values=(tab, count))


class McpOperationsTab(BaseUITab):
    """MCP tool usage metrics (filtered from operations)."""

    def __init__(self, parent: tk.Widget):
        super().__init__(
            parent,
            default_help_text=(
                'MCP tool usage across all runs (invocations per tool '
                'and simple success/failure counts when available).'
            ),
        )

        body = self

        self.summary_var = tk.StringVar(value='MCP tool invocations: 0')
        summary_frame = ttk.Frame(body)
        summary_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        ttk.Label(summary_frame, textvariable=self.summary_var).pack(side=tk.LEFT, padx=4)

        frame = ttk.Frame(body)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        cols = ('tool', 'total', 'success', 'failure')
        self.tree = ttk.Treeview(frame, columns=cols, show='headings', height=16)
        self.tree.heading('tool', text='Tool name')
        self.tree.heading('total', text='Invocations')
        self.tree.heading('success', text='Success')
        self.tree.heading('failure', text='Failure')

        self.tree.column('tool', width=260, anchor='w')
        self.tree.column('total', width=100, anchor='e')
        self.tree.column('success', width=100, anchor='e')
        self.tree.column('failure', width=100, anchor='e')

        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        scroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

    def refresh(self, summary: McpToolSummary) -> None:
        self.summary_var.set(f'MCP tool invocations: {summary.total_invocations}')

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Merge counts by tool
        tools = set(summary.by_tool.keys()) | set(summary.success_by_tool.keys()) | set(summary.failure_by_tool.keys())

        def _counts(name: str) -> tuple[int, int, int]:
            total = int(summary.by_tool.get(name, 0))
            succ = int(summary.success_by_tool.get(name, 0))
            fail = int(summary.failure_by_tool.get(name, 0))
            return total, succ, fail

        for tool in sorted(tools):
            total, succ, fail = _counts(tool)
            self.tree.insert('', 'end', values=(tool, total, succ, fail))


class WebTrafficTab(BaseUITab):
    """Web traffic metrics based on ``web_operation`` operations."""

    def __init__(self, parent: tk.Widget):
        super().__init__(
            parent,
            default_help_text=(
                'Web traffic summary from tracked high-value operations only '
                '(auth/load/simulation/intelligence/prospective/consolidation).'
            ),
        )

        body = self
        self.summary_var = tk.StringVar(value='Web operations: 0 | Tenancy suffixes: 0')
        summary_frame = ttk.Frame(body)
        summary_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        ttk.Label(summary_frame, textvariable=self.summary_var).pack(side=tk.LEFT, padx=4)

        bottom = ttk.Frame(body)
        bottom.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # Left: tenancy + operation + status with avg duration
        left = ttk.LabelFrame(bottom, text='Tenancy / Operation / Status')
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        cols = ('tenancy', 'operation', 'status', 'count', 'avg_duration_ms')
        self.left_tree = ttk.Treeview(left, columns=cols, show='headings', height=16)
        self.left_tree.heading('tenancy', text='Tenancy suffix')
        self.left_tree.heading('operation', text='Operation')
        self.left_tree.heading('status', text='Status')
        self.left_tree.heading('count', text='Count')
        self.left_tree.heading('avg_duration_ms', text='Avg duration (ms)')
        self.left_tree.column('tenancy', width=130, anchor='w')
        self.left_tree.column('operation', width=220, anchor='w')
        self.left_tree.column('status', width=90, anchor='w')
        self.left_tree.column('count', width=90, anchor='e')
        self.left_tree.column('avg_duration_ms', width=130, anchor='e')
        lscroll = ttk.Scrollbar(left, orient='vertical', command=self.left_tree.yview)
        self.left_tree.configure(yscrollcommand=lscroll.set)
        self.left_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2), pady=2)
        lscroll.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4), pady=2)

        # Removed secondary distribution pane; tenancy/source rollup now lives on Tenancies tab.

    def refresh(self, summary: WebTrafficSummary) -> None:
        self.summary_var.set(
            f'Web operations: {summary.total_ops} | Tenancy suffixes: {len(summary.by_tenancy_suffix)}'
        )

        for item in self.left_tree.get_children():
            self.left_tree.delete(item)
        for (tenancy, route, status), count in sorted(
            summary.by_tenancy_route_status.items(),
            key=lambda kv: (-kv[1], kv[0][0], kv[0][1], kv[0][2]),
        ):
            avg_duration = summary.avg_duration_ms_by_route_status.get((route, status))
            avg_display = f'{avg_duration:.1f}' if avg_duration is not None else 'n/a'
            self.left_tree.insert('', 'end', values=(tenancy, route, status, count, avg_display))

        # No secondary distribution table by design.


__all__ = [
    'OverviewTab',
    'TenancyTab',
    'TabUsageTab',
    'SubtabUsageTab',
    'OperationsTab',
    'AiOperationsTab',
    'McpOperationsTab',
    'WebTrafficTab',
]
