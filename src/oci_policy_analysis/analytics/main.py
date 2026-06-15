##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# analytics/main.py
#
# Standalone Tkinter application that loads anonymous usage tracking
# documents from the analytics PAR and presents basic aggregate metrics.
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""Standalone usage analytics application for OCI Policy Analysis."""

from __future__ import annotations

import argparse
import os
import tkinter as tk
from datetime import UTC, date, datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

from oci_policy_analysis.application.core.support.logger import get_logger

from .aggregator import (
    compute_ai_assist_summary,
    compute_data_load_sources,
    compute_mcp_tool_summary,
    compute_mcp_tool_usage,
    compute_operation_summaries,
    compute_overview_metrics,
    compute_subtab_usage_metrics,
    compute_tab_usage_metrics,
    compute_tenancy_metrics,
    compute_tenancy_source_metrics,
    compute_web_traffic_summary,
)
from .loader import load_usage_docs_from_par
from .model import AnalyticsState
from .ui import (
    AiOperationsTab,
    McpOperationsTab,
    OperationsTab,
    OverviewTab,
    SubtabUsageTab,
    TabUsageTab,
    TenancyTab,
    WebTrafficTab,
)

logger = get_logger(component='analytics.main')


class AnalyticsApp(tk.Tk):
    """Standalone Tkinter app for viewing usage analytics."""

    def __init__(self, days: int = 30):
        super().__init__()

        self.title('OCI Policy Analysis ' + '')
        self.geometry('1200x800')

        self.state_model = AnalyticsState()

        # Require runtime PAR URL entry (unless already provided via env var)
        # so analytics access is explicitly authorized by the operator.
        existing_par = os.environ.get('OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL', '').strip()
        if not existing_par:
            par_url = simpledialog.askstring(
                'Analytics PAR URL',
                'Enter Analytics PAR base URL to load usage data:\n' '(example: https://.../b/<bucket>/o/)',
                parent=self,
            )
            if not par_url or not par_url.strip():
                messagebox.showinfo(
                    'Analytics PAR URL Required',
                    'No PAR URL was provided. Analytics UI will close without loading data.',
                    parent=self,
                )
                self.after(100, self.destroy)
                return
            os.environ['OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL'] = par_url.strip()
        # Internal representation of the date-range selection. Historically
        # this was just an integer day window; we now support a small set of
        # predefined options exposed via a dropdown in the toolbar.
        #
        # Supported keys:
        #   "1", "7", "30"  -> last N days
        #   "MTD"             -> month-to-date (from 1st of current month)
        #   "ALL"             -> all data (no date filter)
        #
        # For backward compatibility with the existing --days CLI, we
        # initialize the selection based on the provided days value.
        if days <= 1:
            self._range_key = '1'
        elif days <= 7:
            self._range_key = '7'
        elif days <= 30:
            self._range_key = '30'
        else:
            # Any larger window maps to "ALL" by default.
            self._range_key = 'ALL'

        # Toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.status_var = tk.StringVar(value='Ready')

        # Toggle to include or exclude runs with unknown tenancy suffix.
        # Default to *excluding* unknown tenancy runs from aggregate views.
        self.include_unknown_var = tk.BooleanVar(value=False)

        # Date-range selector: small dropdown driving the loader window.
        # Options are intentionally compact, matching the CLI defaults but
        # exposed directly in the UI for quicker exploration.
        ttk.Label(toolbar, text='Range:').pack(side=tk.LEFT, padx=(4, 0))
        self.range_var = tk.StringVar(value=self._range_key)
        range_dropdown = ttk.OptionMenu(
            toolbar,
            self.range_var,
            self._range_key,
            '1',
            '7',
            '30',
            'MTD',
            'ALL',
            command=lambda _value: self.refresh_from_par(),
        )
        range_dropdown.pack(side=tk.LEFT, padx=4, pady=4)

        refresh_btn = ttk.Button(toolbar, text='Refresh from PAR', command=self.refresh_from_par)
        refresh_btn.pack(side=tk.LEFT, padx=4, pady=4)

        ttk.Checkbutton(
            toolbar,
            text="Include 'unknown' tenancy",
            variable=self.include_unknown_var,
            command=self.refresh_from_par,
        ).pack(side=tk.LEFT, padx=4)

        status_label = ttk.Label(toolbar, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT, padx=8)

        # Notebook and tabs
        notebook = ttk.Notebook(self)
        notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.overview_tab = OverviewTab(notebook)
        self.tenancy_tab = TenancyTab(notebook)
        self.tab_usage_tab = TabUsageTab(notebook)
        self.subtab_usage_tab = SubtabUsageTab(notebook)
        self.operations_tab = OperationsTab(notebook)
        self.ai_operations_tab = AiOperationsTab(notebook)
        self.mcp_operations_tab = McpOperationsTab(notebook)
        self.web_traffic_tab = WebTrafficTab(notebook)

        notebook.add(self.overview_tab, text='Overview')
        notebook.add(self.tenancy_tab, text='Tenancies')
        notebook.add(self.tab_usage_tab, text='Tab usage')
        notebook.add(self.subtab_usage_tab, text='Subtab usage')
        notebook.add(self.operations_tab, text='Operations')
        notebook.add(self.ai_operations_tab, text='AI operations')
        notebook.add(self.mcp_operations_tab, text='MCP operations')
        notebook.add(self.web_traffic_tab, text='Web traffic')

        # Trigger an initial load.
        self.after(100, self.refresh_from_par)

    # --- internal helpers -------------------------------------------------

    def _compute_date_range(self) -> tuple[date | None, date | None]:
        """Return (start_date, end_date) based on the selected range key.

        The mapping is:

        * "1", "7", "30" -> last N days window ending today.
        * "MTD"             -> month-to-date (1st of this month through today).
        * "ALL"             -> no date filter (``None, None``).

        Unknown keys fall back to the default 30-day window.
        """

        key = getattr(self, '_range_key', None) or self.range_var.get() if hasattr(self, 'range_var') else '30'

        today = datetime.now(UTC).date()

        if key == 'ALL':
            return None, None
        if key == 'MTD':
            start = today.replace(day=1)
            end = today
            return start, end
        if key in {'1', '7', '30'}:
            days = int(key)
            start = today - timedelta(days=days)
            end = today
            return start, end

        # Fallback: historical behavior was a 30-day window.
        start = today - timedelta(days=30)
        end = today
        return start, end

    # --- public actions ---------------------------------------------------

    def refresh_from_par(self) -> None:
        """Load documents from the analytics PAR and update the UI."""

        start_date, end_date = self._compute_date_range()
        logger.info(
            'Refreshing analytics from PAR (range_key=%s, start=%s, end=%s)',
            getattr(self, '_range_key', None) or self.range_var.get(),
            start_date,
            end_date,
        )
        self.status_var.set('Loading usage documents from PAR...')
        self.update_idletasks()

        docs = load_usage_docs_from_par(start_date, end_date)
        self.state_model.docs = docs

        # Optionally filter out runs with unknown tenancy suffix for aggregation.
        visible_docs = docs
        if not self.include_unknown_var.get():
            visible_docs = [d for d in docs if d.tenancy_suffix and d.tenancy_suffix != 'unknown']

        overview_metrics = compute_overview_metrics(visible_docs)
        tenancy_metrics = compute_tenancy_metrics(visible_docs)
        tab_metrics = compute_tab_usage_metrics(visible_docs)
        subtab_metrics = compute_subtab_usage_metrics(visible_docs)
        op_summaries = compute_operation_summaries(visible_docs)
        mcp_tool_usage = compute_mcp_tool_usage(visible_docs)
        ai_summary = compute_ai_assist_summary(visible_docs)
        mcp_summary = compute_mcp_tool_summary(visible_docs)
        web_summary = compute_web_traffic_summary(visible_docs)
        load_sources = compute_data_load_sources(visible_docs)
        tenancy_source_metrics = compute_tenancy_source_metrics(visible_docs)

        logger.info(
            'Analytics refresh complete: runs=%d, tenancies=%d, tabs=%d, op_types=%d',
            overview_metrics.get('total_runs', 0),
            overview_metrics.get('distinct_tenancies', 0),
            len(tab_metrics),
            len(op_summaries),
        )

        # Update tabs.
        self.overview_tab.refresh(overview_metrics, visible_docs, load_sources)
        self.tenancy_tab.refresh(tenancy_metrics, tenancy_source_metrics)
        self.tab_usage_tab.refresh(tab_metrics)
        self.subtab_usage_tab.refresh(subtab_metrics)
        self.operations_tab.refresh(op_summaries, mcp_tool_usage)
        self.ai_operations_tab.refresh(ai_summary)
        self.mcp_operations_tab.refresh(mcp_summary)
        self.web_traffic_tab.refresh(web_summary)

        self.status_var.set(
            f"Loaded {overview_metrics.get('total_runs', 0)} runs "
            f"from {overview_metrics.get('distinct_tenancies', 0)} tenancies."
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='OCI Policy Analysis usage analytics UI')
    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days of analytics to load from PAR (<=0 for all)',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for ``oci-policy-analytics`` CLI and ``-m`` usage."""

    args = _parse_args(argv)
    logger.info('Starting AnalyticsApp (days=%s)', args.days)
    app = AnalyticsApp(days=args.days)
    app.mainloop()


__all__ = ['AnalyticsApp', 'main']
