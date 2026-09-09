##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# policy_recommendations_tab.py
#
# Unified UI tab for Policy Recommendations: risk, overlap, and more.
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import csv
import json
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tkinter.messagebox
from datetime import UTC
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.application.core.common.consolidation_opportunities import build_consolidation_opportunities
from oci_policy_analysis.application.core.engine.recommendation_actions import (
    ATTEMPT_FIX_HELP,
    RECOMMENDATION_PRIORITY_HIGH,
    RECOMMENDATION_PRIORITY_MEDIUM,
    cleanup_detail_sections,
    cleanup_finding_identity,
    current_supersession_identities,
    overly_broad_statement_guidance,
    reconcile_cleanup_actions,
    supersession_finding_identity,
)
from oci_policy_analysis.application.core.support.helpers import for_display_policy
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker
from oci_policy_analysis.presentation import format_compartment_policy_name
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import CheckboxTable, DataTable

# Note: CheckboxTable now supports a `column_widths` dict argument (pixel widths only).


def _compartment_filter_label(path: object) -> str:
    """Format a compartment path with its hierarchy level for filter display."""
    normalized = _normalize_compartment_path(path)
    level = len([segment for segment in normalized.split('/') if segment])
    return f'{normalized or "Unknown"} (Level {level or 1})'


def _normalize_compartment_path(path: object) -> str:
    """Normalize a display path and use the canonical uppercase ROOT segment."""
    segments = [segment for segment in str(path or '').strip('/').split('/') if segment]
    if segments and segments[0].casefold() == 'root':
        segments[0] = 'ROOT'
    return '/'.join(segments)


def _path_is_same_or_descendant(path: object, ancestor: object) -> bool:
    """Return whether ``path`` is ``ancestor`` or belongs below it in the hierarchy."""
    path_segments = tuple(segment.casefold() for segment in str(path or '').strip('/').split('/') if segment)
    ancestor_segments = tuple(segment.casefold() for segment in str(ancestor or '').strip('/').split('/') if segment)
    return bool(ancestor_segments) and path_segments[: len(ancestor_segments)] == ancestor_segments


# Risk View Table Layout
POLICY_RECOMMENDATIONS_ALL_COLUMNS = [
    'Score',
    'Relative Risk',
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Action',
    'Statement Text',
    'Risk Notes',
    'Internal ID',
]
POLICY_RECOMMENDATIONS_DISPLAY_COLUMNS = [
    'Score',
    'Relative Risk',
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Action',
    'Statement Text',
    'Risk Notes',
]
POLICY_RECOMMENDATIONS_COLUMN_WIDTHS = {
    'Score': 80,
    'Relative Risk': 80,
    'Policy Name': 250,
    'Policy Compartment': 250,
    'Effective Path': 200,
    'Statement Text': 700,
    'Action': 80,
    'Risk Notes': 500,
    'Internal ID': 100,
}

# Overlap View Table Layout
POLICY_OVERLAP_ALL_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Action',
    'Statement Text',
    'Valid',
    'Internal ID',
    'Policy Overlap',
]
POLICY_OVERLAP_DISPLAY_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Action',
    'Statement Text',
]
POLICY_OVERLAP_COLUMN_WIDTHS = {
    'Policy Name': 250,
    'Policy Compartment': 250,
    'Effective Path': 200,
    'Action': 80,
    'Statement Text': 700,
    'Valid': 80,
    'Policy Overlap': 500,
    'Internal ID': 100,
}

POLICY_SUPERSESSION_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Statement Text',
    'Classification',
    'Superseded By',
    'Internal ID',
]
POLICY_SUPERSESSION_DISPLAY_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Statement Text',
    'Classification',
    'Superseded By',
]
POLICY_SUPERSESSION_COLUMN_WIDTHS = {
    'Policy Name': 220,
    'Policy Compartment': 220,
    'Effective Path': 200,
    'Statement Text': 480,
    'Classification': 150,
    'Superseded By': 240,
    'Internal ID': 100,
}

# Policy Consolidation Table Layout
POLICY_CONSOLIDATION_COLUMNS = [
    'Opportunity ID',
    'Type',
    'Policies',
    'Statements',
    'Scope',
    'Summary',
    'Recommended Action',
    'Statement Internal IDs',
    'Recommended Strategy',
    'Handoff Mode',
    'Evidence',
    'checkable',
]
POLICY_CONSOLIDATION_DISPLAY_COLUMNS = [
    '☑',
    'Type',
    'Policies',
    'Statements',
    'Scope',
    'Summary',
    'Recommended Action',
]
POLICY_CONSOLIDATION_COLUMN_WIDTHS = {
    'Type': 190,
    'Policies': 75,
    'Statements': 90,
    'Scope': 180,
    'Summary': 420,
    'Recommended Action': 230,
}

logger = get_logger(component='policy_recommendations_tab')


class PolicyRecommendationsTab(BaseUITab):
    """
    Unified UI tab for displaying Oracle Cloud Policy Recommendations and analytics.
    """

    STATEMENTS_PER_COMPARTMENT_LIMIT = 500  # Hard OCI Limit

    def __init__(self, parent, app):
        self.logger = get_logger(component='policy_recommendations_tab')
        self.logger.debug('Initializing unified PolicyRecommendationsTab (notebook prototype).')
        super().__init__(
            parent,
            default_help_text=(
                'Review policy recommendations and analytics: '
                'overall security hygiene, risk, policy overlap, consolidation, and fix suggestions. '
                'Switch tabs below for different analysis views. '
                'Use the summary table to quickly see top issues and recommendations.'
            ),
            page_help_link='/recommendations.html',
        )
        self.app = app
        self.policy_repo = app.policy_compartment_analysis
        allowed_pct = {0, 25, 50, 75, 90}
        where_pct = int(self.app.settings.get('risk_where_clause_reduction_pct', 50) or 50)
        service_pct = int(self.app.settings.get('risk_service_principal_reduction_pct', 50) or 50)
        self._default_where_reduction_label = f'{where_pct if where_pct in allowed_pct else 50}%'
        self._default_service_reduction_label = f'{service_pct if service_pct in allowed_pct else 50}%'
        # Do NOT cache self.intelligence_engine here; always use self.app.policy_intelligence at use-time!

        # Configure tab grid layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- TOP: Recommendation Summary Table ---
        summary_frame = ttk.LabelFrame(self, text='Overall Recommendation Summary')
        summary_frame.pack(fill='x', padx=10, pady=(8, 0))
        self.add_context_help(summary_frame, 'Top recommendations and actions based on full OCI policy analysis.')

        self.recommendation_table = DataTable(
            summary_frame,
            columns=['Recommendation', 'Priority', 'Category', 'Notes', 'Action'],
            display_columns=['Recommendation', 'Priority', 'Category', 'Notes', 'Action'],
            data=self._get_recommendation_summary(),
            column_widths={'Recommendation': 420, 'Priority': 90, 'Category': 130, 'Notes': 500, 'Action': 250},
            multi_select=True,
        )
        self.recommendation_table.pack(fill='x', padx=2, pady=4)
        self.add_context_help(
            self.recommendation_table, 'High-level summary of all recommended changes or mitigations.'
        )

        # Outer controls for notebook itself (title, reload)
        button_frame = ttk.Frame(self)
        button_frame.pack(fill='x', padx=10, pady=(5, 5))
        self.add_context_help(button_frame, 'Reload or review all policy analytics in unified tabs below.')
        ttk.Label(button_frame, text='Policy Intelligence: Unified Analytics (prototype)').pack(side='left')

        # ==== Begin Notebook Prototype ====
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.add_context_help(
            self.notebook, 'Switch between risk, overlap, consolidation, and fix tabs for deep-dive analytics.'
        )

        # Anonymous usage tracking: record subtab changes for analytics. We
        # treat each recommendations subtab as a named "sub_view" so that
        # usage analytics can see which views are most used.
        def _on_subtab_changed(event):
            try:
                tracker = get_usage_tracker()
                if tracker is None:
                    return
                selected_id = self.notebook.select()
                widget = self.notebook.nametowidget(selected_id) if selected_id else None
                tab_text = self.notebook.tab(selected_id, 'text') if selected_id else ''
                tracker.track(
                    'tab_change',
                    tab_name=type(self).__name__,
                    sub_view=str(tab_text or getattr(widget, '_title', '') or ''),
                )
            except Exception:
                logger.debug('Usage tracking for recommendations subtab change failed', exc_info=True)

        self.notebook.bind('<<NotebookTabChanged>>', _on_subtab_changed)

        # === Risk Overview - Policy Tab ===
        policy_risk_frame = ttk.Frame(self.notebook)
        policy_risk_frame.pack(fill='both', expand=True)
        self.add_context_help(
            policy_risk_frame, 'View aggregated risk summary for each policy (roll-up of all statements).'
        )
        self._build_policy_risk_tab(policy_risk_frame)
        self.notebook.add(policy_risk_frame, text='Risk Overview - Policy')

        # === Risk Overview - Statement Tab ===
        statement_risk_frame = ttk.Frame(self.notebook)
        statement_risk_frame.pack(fill='both', expand=True)
        self.add_context_help(statement_risk_frame, 'View risk scoring and assessment for all policy statements.')
        self._build_statement_risk_tab(statement_risk_frame)
        self.notebook.add(statement_risk_frame, text='Risk Overview - Statement')

        # === Complete Supersession Tab ===
        supersession_frame = ttk.Frame(self.notebook)
        supersession_frame.pack(fill='both', expand=True)
        self.add_context_help(
            supersession_frame,
            'Statements here are fully covered by unconditional allow statements at ancestor compartments. '
            'Protected policies remain evidence and are never modified by this analysis.',
        )
        self._build_supersession_tab(supersession_frame)
        self.notebook.add(supersession_frame, text='Superseded')

        # === Policy Consolidation Tab ===
        consolidation_frame = ttk.Frame(self.notebook)
        consolidation_frame.pack(fill='both', expand=True)
        self.add_context_help(consolidation_frame, 'Opportunities for consolidating or organizing policy statements.')
        self._build_consolidation_tab(consolidation_frame)
        self.notebook.add(consolidation_frame, text='Policy Consolidation')

        # === Cleanup / Fix Tab ===
        cleanup_frame = ttk.Frame(self.notebook)
        cleanup_frame.pack(fill='both', expand=True)
        self.add_context_help(cleanup_frame, 'Identify invalid, dangerous, or redundant policies to clean up.')
        # self.cleanup_frame = cleanup_frame
        self._build_cleanup_tab(cleanup_frame)
        self.notebook.add(cleanup_frame, text='Cleanup / Fix')

        # === Limits Tab (Compartment Policy Statement Limits) ===
        self.limits_frame = ttk.Frame(self.notebook)
        self.limits_frame.pack(fill='both', expand=True)
        self.add_context_help(
            self.limits_frame,
            'Review compartments for policy statement limits. Clean up or consolidate to avoid exceeding OCI’s per-compartment or tenancy statement limits.',
        )
        self._build_limits_tab(self.limits_frame)
        self.notebook.add(self.limits_frame, text='Limits')

        # === Cleanup In Progress Tab ===
        self._workbench_actions = []
        self._workbench_counter = 0
        self._cleanup_payload_by_key = {}
        # Ignored cleanup item action_keys (persisted per tenancy in consolidation state)
        self.ignored_cleanup_keys = set()
        self.workbench_frame = ttk.Frame(self.notebook)
        self.workbench_frame.pack(fill='both', expand=True)
        self.add_context_help(
            self.workbench_frame,
            'Track cleanup actions, review instructions, and reload live IAM and policy data to verify resolution.',
        )
        self._build_recommendation_workbench_tab(self.workbench_frame)
        self.notebook.add(self.workbench_frame, text='Cleanup In Progress')

    def populate_data(self):
        """
        Called after policy analysis/intelligence is refreshed. Reload all analytics/tables, using timing.
        Also launches OCI tenancy limits fetch for policy objects and hierarchy statements.
        """
        import threading

        self.logger.info('Populating PolicyRecommendationsTab data...')

        # Get the data for the limits tab and update the output; this is separate from reload_all_analytics since it can run in parallel and may involve API calls to fetch tenancy limits
        self.timed_step('load_compartment_limits', self.update_limits_tab_output)

        # Fetch tenancy limits in the background; update label when done
        def update_tenancy_limit_label():
            if not (
                hasattr(self.app.policy_compartment_analysis, 'limits_client')
                and self.app.policy_compartment_analysis.limits_client
            ):
                txt = self._tenancy_limits_summary()
            else:
                self.app.policy_compartment_analysis.fetch_tenancy_policy_statement_limits()
                txt = self._tenancy_limits_summary()
            if hasattr(self, 'tenancy_limit_label_var'):
                # Set from worker thread: use "after" to update GUI label safely
                self.after(0, self.tenancy_limit_label_var.set, txt)

        threading.Thread(target=update_tenancy_limit_label, daemon=True).start()

        self.timed_step('reload_all_analytics', self.reload_all_analytics)
        self.logger.info('Finished PolicyRecommendationsTab.populate_data')

    def _build_limits_tab(self, parent):
        # Dropdown and all top controls on single row for compactness
        controls_frame = ttk.Frame(parent)
        controls_frame.pack(fill='x', padx=10, pady=(10, 2))

        # Check up-front if we have a live OCI limits client
        can_check_limits = hasattr(self.policy_repo, 'limits_client') and self.policy_repo.limits_client

        ttk.Label(controls_frame, text='Show:').pack(side='left', padx=(0, 2))
        self.limits_filter_var = tk.StringVar(value='All compartments')
        self.limits_filter_options = ['All compartments', 'Nearing/Over Limit', 'Over Limit']
        limits_combo = ttk.Combobox(
            controls_frame,
            textvariable=self.limits_filter_var,
            state='readonly',
            values=self.limits_filter_options,
            width=22,
        )
        limits_combo.pack(side='left', padx=(3, 8))
        limits_combo.bind('<<ComboboxSelected>>', lambda e: self.update_limits_tab_output())
        self.add_context_help(limits_combo, 'Filter compartments by statement count status.')

        # Tenancy limit summary and offline/cache entry controls.
        label_initial = (
            self._tenancy_limits_summary() if not can_check_limits else 'Tenancy policy statement limit: [not fetched]'
        )
        self.tenancy_limit_label_var = tk.StringVar(value=label_initial)
        self.tenancy_limit_label = ttk.Label(
            controls_frame,
            textvariable=self.tenancy_limit_label_var,
            font=('TkDefaultFont', 9, 'normal'),
            foreground='#333333',
        )
        self.tenancy_limit_label.pack(side='left', padx=(0, 4), pady=2)
        self.add_context_help(
            self.tenancy_limit_label, 'Shows policy-object and hierarchy-statement limits for this tenancy snapshot.'
        )

        doc_url = (
            'https://docs.oracle.com/en-us/iaas/Content/Identity/policymgmt/policy-limits-compartment-hierarchy.htm'
        )
        doc_link = ttk.Label(
            controls_frame, text='Policy Statement Limits Documentation', foreground='#0645AD', cursor='hand2'
        )
        doc_link.pack(side='left', padx=(1, 4))

        def open_doc_link(event):
            try:
                self.open_link(doc_url)
            except Exception:
                tkinter.messagebox.showinfo('Documentation', f'Learn more: {doc_url}')

        doc_link.bind('<Button-1>', open_doc_link)
        self.add_context_help(
            doc_link, 'Open Oracle documentation for policies-count and policy statement hierarchy limits.'
        )

        # Data Table for compartment statement limits
        limits_columns = [
            'Compartment Hierarchy Path',
            'Direct Statements',
            'Cumulative Statements',
            'Status',
            'Recommendation',
        ]
        limits_column_widths = {
            'Compartment Hierarchy Path': 300,
            'Direct Statements': 120,
            'Cumulative Statements': 140,
            'Status': 120,
            'Recommendation': 440,
        }
        self.limits_table = DataTable(
            parent,
            columns=limits_columns,
            display_columns=limits_columns,
            data=[],
            column_widths=limits_column_widths,
        )
        self.limits_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(
            self.limits_table, 'Compartments that are at, near, or over the statement limit for policy definitions.'
        )

        # self.update_limits_tab_output()

    def update_limits_tab_output(self):
        # Thresholds
        limits = getattr(self.policy_repo, 'tenancy_policy_limits', {}) or {}
        LIMIT = limits.get('policy_statements_per_compartment_chain_count')
        NEAR = 0.85
        compartments = getattr(self.app.policy_compartment_analysis, 'compartments', None)
        results = []
        # Debug/log the state and fields for troubleshooting
        logger = get_logger(component='limits_tab')
        if not compartments:
            logger.warning('[LimitsTab] compartments is None or empty. Data population issue.')
        else:
            logger.info(f'[LimitsTab] compartments list length: {len(compartments)}')
        for i, comp in enumerate(compartments or []):
            path = comp.get('hierarchy_path')
            direct = comp.get('statement_count_direct')
            cumulative = comp.get('statement_count_cumulative')
            # If data missing, log fields for diagnostic
            if path is None or direct is None or cumulative is None:
                logger.warning(f'[LimitsTab] Compartment {i} missing key fields: {comp}')
                continue
            if not LIMIT:
                status = 'Limit Not Supplied'
                rec = 'Enter policy-statements-per-compartment-chain-count to assess this hierarchy.'
            elif cumulative > LIMIT:
                status = 'Over Limit'
                rec = (
                    'Reduce or consolidate policy statements in this compartment/hierarchy to avoid enforcement errors.'
                )
            elif cumulative >= int(LIMIT * NEAR):
                status = 'Nearing Limit'
                rec = 'Proactively clean up or consolidate policies to stay under the statement limit.'
            else:
                status = 'OK'
                rec = ''
            results.append(
                {
                    'Compartment Hierarchy Path': path,
                    'Direct Statements': direct,
                    'Cumulative Statements': cumulative,
                    'Status': status,
                    'Recommendation': rec,
                }
            )

        # Dropdown filter logic
        current_filter = self.limits_filter_var.get()
        if current_filter == 'Over Limit':
            filtered = [r for r in results if r['Status'] == 'Over Limit']
        elif current_filter == 'Nearing/Over Limit':
            filtered = [r for r in results if r['Status'] in ('Over Limit', 'Nearing Limit')]
        else:
            filtered = results

        # Sort descending by cumulative statements
        filtered.sort(key=lambda x: x['Cumulative Statements'], reverse=True)
        self.limits_table.update_data(filtered)

    def _tenancy_limits_summary(self) -> str:
        limits = getattr(self.policy_repo, 'tenancy_policy_limits', {}) or {}
        policies_limit = limits.get('policies_count')
        chain_limit = limits.get('policy_statements_per_compartment_chain_count')
        if not policies_limit or not chain_limit:
            return 'Limits not supplied for this dataset: enter them in Policy Browser > Show Limit Data.'
        max_chain = max(
            (
                int(c.get('statement_count_cumulative', 0) or 0)
                for c in getattr(self.policy_repo, 'compartments', []) or []
            ),
            default=0,
        )
        return (
            f'Limits: policies-count: {policies_limit} '
            f'(currently {len(getattr(self.policy_repo, "policies", []) or [])} in tenancy), '
            f'policy-statements-per-compartment-chain-count: {chain_limit} '
            f'(maximum compartment: {max_chain}) | Source: {limits.get("source", "unknown")}'
        )

    # Button callback to fetch tenancy policy/statement limits and update label
    def fetch_tenancy_policy_statement_limits(self):
        import threading

        def update_label():
            repo = self.app.policy_compartment_analysis
            if not (hasattr(repo, 'limits_client') and repo.limits_client):
                txt = self._tenancy_limits_summary()
            else:
                repo.fetch_tenancy_policy_statement_limits()
                txt = self._tenancy_limits_summary()
            if hasattr(self, 'tenancy_limit_label_var'):
                self.after(0, self.tenancy_limit_label_var.set, txt)

        threading.Thread(target=update_label, daemon=True).start()

    # In summary: show only one limit row if any compartment is at risk, refer to Limits tab for details
    def _get_recommendation_summary(self):
        """
        Guarantee deduplication of the limit recommendation: only ONE row in the summary table,
        no matter how many compartments are over/nearing the limit. Direct users to Limits subtab, do not enumerate.
        """
        pi = self.app.policy_intelligence
        recs = pi.overlay.get('recommendations', [])
        LIMIT = 500
        NEAR = 0.85
        compartments = getattr(self.app.policy_compartment_analysis, 'compartments', [])
        # Remove all existing limit recommendations (by category/title) before inserting
        title = 'Compartment Policy Statement Limits'
        new_recs = [
            r for r in recs if not ((r.get('Category', '') == 'Limits') or (title in r.get('Recommendation', '')))
        ]
        has_over = any((c.get('statement_count_cumulative', 0) > LIMIT) for c in compartments)
        has_near = any(
            (
                c.get('statement_count_cumulative', 0) >= int(LIMIT * NEAR)
                and c.get('statement_count_cumulative', 0) <= LIMIT
            )
            for c in compartments
        )
        if has_over or has_near:
            first_status = 'over limit' if has_over else 'nearing the limit'
            rec = {
                'Recommendation': title,
                'Priority': RECOMMENDATION_PRIORITY_HIGH if has_over else RECOMMENDATION_PRIORITY_MEDIUM,
                'Category': 'Limits',
                'Notes': (
                    f'At least one compartment is {first_status} for the OCI 500 policy statement-per-compartment limit. '
                    'Review the Limits tab below for details and mitigation steps.'
                ),
                'Action': 'Use the Limits tab to review and reduce/consolidate compartment statements as needed.',
                'ActionDetail': 'Review the affected compartment hierarchy paths in the Limits tab before planning policy cleanup.',
            }
            new_recs.insert(0, rec)
        return new_recs

    # ==== Risk Tab Logic ====

    def _get_policy_path(self, policy_ocid=None, policy_obj=None):
        """
        Given a policy OCID or policy object, return its full path as "ROOT/Compartment/.../PolicyName".
        """
        if policy_obj is not None:
            comp_path = policy_obj.get('compartment_path') or ''
            name = policy_obj.get('policy_name') or ''
            return format_compartment_policy_name(comp_path, name, separator='/', empty='[Unknown Policy Path]')
        if policy_ocid:
            pol = None
            for p in self.policy_repo.policies:
                if p.get('policy_ocid') == policy_ocid:
                    pol = p
                    break
            if pol:
                comp_path = pol.get('compartment_path') or ''
                name = pol.get('policy_name') or ''
                return format_compartment_policy_name(comp_path, name, separator='/', empty='[Unknown Policy Path]')
        return '[Unknown Policy Path]'

    def _show_recommendation_details(self, title: str, sections: list[tuple[str, list[str]]]) -> None:
        """Open a consistent read-only details window for a recommendation row."""
        popup = tk.Toplevel(self.winfo_toplevel())
        popup.title(title)
        popup.transient(self.winfo_toplevel())
        popup.resizable(True, True)
        popup.geometry('980x680')
        outer = ttk.Frame(popup)
        outer.pack(fill='both', expand=True, padx=12, pady=12)
        for section_title, lines in sections:
            frame = ttk.LabelFrame(outer, text=section_title)
            frame.pack(fill='x', pady=(0, 8))
            for line in lines:
                ttk.Label(frame, text=line, wraplength=900, justify='left').pack(anchor='w', padx=8, pady=(6, 1))
        ttk.Button(outer, text='Close', command=popup.destroy).pack(anchor='e', pady=(0, 4))

    def _build_statement_risk_tab(self, parent):
        # Filter Controls - now inside risk tab only
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.add_context_help(
            filter_frame,
            'Tune risk scoring: WHERE clause and Service Principal reduction percentages, and relative risk threshold filter.',
        )

        ttk.Label(filter_frame, text='WHERE clause risk reduction:').pack(side='left', padx=(0, 2))
        self.where_reduction_pct_var = tk.StringVar(value=self._default_where_reduction_label)
        self.where_reduction_options = ['0%', '25%', '50%', '75%', '90%']
        where_pct_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.where_reduction_pct_var,
            state='readonly',
            values=self.where_reduction_options,
            width=7,
        )
        where_pct_combo.pack(side='left', padx=2)
        where_pct_combo.bind('<<ComboboxSelected>>', lambda e: self.reload_all_analytics())
        self.add_context_help(where_pct_combo, 'Adjust how much WHERE clauses reduce statement risk.')

        ttk.Label(filter_frame, text='Service Principal risk reduction:').pack(side='left', padx=(15, 2))
        self.service_reduction_pct_var = tk.StringVar(value=self._default_service_reduction_label)
        service_pct_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.service_reduction_pct_var,
            state='readonly',
            values=self.where_reduction_options,
            width=7,
        )
        service_pct_combo.pack(side='left', padx=2)
        service_pct_combo.bind('<<ComboboxSelected>>', lambda e: self.reload_all_analytics())
        self.add_context_help(
            service_pct_combo,
            'Reduce risk for statements with service as subject type (use/manage verbs); inherently lower than group or dynamic-group.',
        )

        ttk.Label(filter_frame, text='Relative Risk threshold:').pack(side='left', padx=(15, 2))
        self.risk_threshold_var = tk.StringVar(value='Show all')
        threshold_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.risk_threshold_var,
            state='readonly',
            values=['Show all', 'Relative Risk > 50', 'Relative Risk > 80'],
            width=14,
        )
        threshold_combo.pack(side='left', padx=2)
        threshold_combo.bind('<<ComboboxSelected>>', lambda e: self.update_risk_tab_output())
        self.add_context_help(threshold_combo, 'Show only statements above a relative risk threshold.')

        def risk_table_context_menu_callback(row_index):
            row = self.risk_table.data[row_index]
            menu = tk.Menu(self.risk_table, tearoff=0)
            menu.add_command(
                label='Risk Details',
                command=lambda: self._show_recommendation_details(
                    'Risk Details',
                    [
                        (
                            'Candidate Statement',
                            [
                                f'Policy: {row.get("Policy Path") or "(none)"}',
                                f'Statement: {row.get("Statement Text") or "(none)"}',
                            ],
                        ),
                        (
                            'Risk Assessment',
                            [f'Raw Score: {row.get("Score")}', f'Relative Risk: {row.get("Relative Risk")}'],
                        ),
                    ],
                ),
            )
            menu.add_command(
                label='Analyze Statement',
                command=lambda: self._analyze_selected_statement_in_main_analysis(row.get('Statement Text', '') or ''),
            )
            return menu

        self.risk_table = DataTable(
            parent,
            columns=['Policy Path', 'Effective Path', 'Score', 'Relative Risk', 'Statement Text'],
            display_columns=['Policy Path', 'Effective Path', 'Score', 'Relative Risk', 'Statement Text'],
            data=[],
            column_widths={
                'Policy Path': 420,
                'Effective Path': 200,
                'Score': 80,
                'Relative Risk': 80,
                'Statement Text': 700,
            },
            row_context_menu_callback=risk_table_context_menu_callback,
            multi_select=True,
            initial_sort_column='Relative Risk',
            initial_sort_descending=True,
        )
        self.risk_table.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        self.add_context_help(self.risk_table, 'Full list of policy statements, with risk and mitigation guidance.')

        ttk.Label(parent, text='Right-click a row to view details or analyze the statement.').pack(
            anchor='w', padx=10, pady=(2, 10)
        )

    def _show_policy_statements_in_main_analysis(self, policy_path: str):
        """
        Given Policy Path (ROOT/Comp/PolicyName), switch to Policy Analysis tab and apply filters to show all its statements.
        """
        try:
            # Split path into hierarchy and policy_name
            if '/' in policy_path:
                components = policy_path.strip('/').split('/')
                policy_name = components[-1]
                hierarchy_path = '/'.join(components[:-1])
            else:
                policy_name = policy_path
                hierarchy_path = 'ROOT'
            # Switch to main Policy Analysis tab
            self.app.notebook.select(tab_id=2)  # Policy Analysis tab
            # Set filters and output filters
            logger.info(
                f'Switching to Policy Analysis tab and applying filters for policy name: {policy_name} and hierarchy path: {hierarchy_path}'
            )
            self.app.policies_tab.hierarchy_filter_var.set(hierarchy_path)
            self.app.policies_tab.policy_filter_var.set(policy_name)
            # Enable checkboxes for output
            self.app.policies_tab.chk_show_dynamic.set(True)
            self.app.policies_tab.chk_show_service.set(True)
            # Force a search
            self.app.policies_tab.update_policy_output()
        except Exception as ex:
            tkinter.messagebox.showinfo('Show All Statements', f'Could not focus Policy Analysis tab: {ex}')

    def _show_full_policy_in_main_analysis(self, policy_name: str, compartment_path: str) -> None:
        """Open one policy in Policy Analysis with every unrelated filter cleared."""
        try:
            self.app.notebook.select(tab_id=2)  # Policy Analysis tab
            policies_tab = self.app.policies_tab
            policies_tab.clear_policy_filters()
            policies_tab.hierarchy_filter_var.set(compartment_path)
            policies_tab.policy_filter_var.set(policy_name)
            policies_tab.update_policy_output()
            logger.info(
                'Opened full policy in Policy Analysis: policy_name=%s compartment_path=%s',
                policy_name,
                compartment_path,
            )
        except Exception as ex:
            tkinter.messagebox.showinfo('Show Full Policy', f'Could not focus Policy Analysis tab: {ex}')

    def _analyze_selected_statement_in_main_analysis(self, statement_text: str):
        """
        Switch to policies_tab, set text_filter_var to the statement_text, and update.
        """
        try:
            self.app.notebook.select(tab_id=2)
            self.app.policies_tab.text_filter_var.set(statement_text)
            # Enable checkboxes for output
            self.app.policies_tab.chk_show_dynamic.set(True)
            self.app.policies_tab.chk_show_service.set(True)
            # Force a search
            self.app.policies_tab.update_policy_output()
        except Exception as ex:
            tkinter.messagebox.showinfo('Analyze Statement', f'Could not focus Policy Analysis tab: {ex}')

    def _build_policy_risk_tab(self, parent):  # noqa: C901
        """
        Build the policy-level risk analytics tab.
        """
        # Filter Controls - policy risk tab
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.add_context_help(
            filter_frame,
            'Tune risk scoring: WHERE clause and Service Principal reduction percentages, and relative risk threshold filter (policy view).',
        )

        self.where_reduction_pct_var_policy = tk.StringVar(value=self._default_where_reduction_label)
        self.where_reduction_options = ['0%', '25%', '50%', '75%', '90%']
        ttk.Label(filter_frame, text='WHERE clause risk reduction:').pack(side='left', padx=(0, 2))
        where_pct_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.where_reduction_pct_var_policy,
            state='readonly',
            values=self.where_reduction_options,
            width=7,
        )
        where_pct_combo.pack(side='left', padx=2)
        where_pct_combo.bind('<<ComboboxSelected>>', lambda e: self.reload_all_analytics())
        self.add_context_help(where_pct_combo, 'Adjust how much WHERE clauses reduce statement risk for policy tab.')

        ttk.Label(filter_frame, text='Service Principal risk reduction:').pack(side='left', padx=(15, 2))
        self.service_reduction_pct_var_policy = tk.StringVar(value=self._default_service_reduction_label)
        service_pct_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.service_reduction_pct_var_policy,
            state='readonly',
            values=self.where_reduction_options,
            width=7,
        )
        service_pct_combo.pack(side='left', padx=2)
        service_pct_combo.bind('<<ComboboxSelected>>', lambda e: self.reload_all_analytics())
        self.add_context_help(service_pct_combo, 'Reduce risk for statements with service as subject in policy tab.')

        ttk.Label(filter_frame, text='Relative Risk threshold:').pack(side='left', padx=(15, 2))
        self.policy_risk_threshold_var = tk.StringVar(value='Show all')
        threshold_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.policy_risk_threshold_var,
            state='readonly',
            values=['Show all', 'Relative Risk > 50', 'Relative Risk > 80'],
            width=14,
        )
        threshold_combo.pack(side='left', padx=2)
        threshold_combo.bind('<<ComboboxSelected>>', lambda e: self.update_policy_risk_tab_output())
        self.add_context_help(threshold_combo, 'Show only policies above a relative risk threshold.')

        # Policy risk table
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill='both', expand=True)

        def policy_risk_context_menu_callback(row_index):
            row = self.policy_risk_table.data[row_index]
            policy_path = row.get('Policy Path', '')
            menu = tk.Menu(self.policy_risk_table, tearoff=0)
            menu.add_command(
                label='Policy Risk Details',
                command=lambda: self._show_recommendation_details(
                    'Policy Risk Details',
                    [
                        ('Policy', [f'Policy Path: {policy_path or "(none)"}']),
                        (
                            'Risk Assessment',
                            [
                                f'Total Statements: {row.get("Total Statements", "")}',
                                f'Maximum Score: {row.get("Max Score", "")}',
                                f'Average Score: {row.get("Avg Score", "")}',
                                f'Risk Summary: {row.get("Risk Summary/Notes", "")}',
                            ],
                        ),
                    ],
                ),
            )
            menu.add_command(
                label='Show All Statements', command=lambda: self._show_policy_statements_in_main_analysis(policy_path)
            )
            return menu

        self.policy_risk_table = DataTable(
            table_frame,
            columns=[
                'Policy Path',
                'Total Statements',
                'Max Score',
                'Avg Score',
                'Max Statement Risk (Global %)',
                'Total Raw Risk',
                'Risk Summary/Notes',
                'Example Statement',
            ],
            display_columns=[
                'Policy Path',
                'Total Statements',
                'Max Score',
                'Avg Score',
                'Max Statement Risk (Global %)',
                'Total Raw Risk',
                'Risk Summary/Notes',
                'Example Statement',
            ],
            data=[],
            row_context_menu_callback=policy_risk_context_menu_callback,
            column_widths={
                'Policy Path': 400,
                'Total Statements': 90,
                'Max Score': 80,
                'Avg Score': 80,
                'Max Statement Risk (Global %)': 100,
                'Total Raw Risk': 120,
                'Risk Summary/Notes': 500,
                'Example Statement': 700,
            },
            initial_sort_column='Max Statement Risk (Global %)',
            initial_sort_descending=True,
            multi_select=True,
        )
        self.policy_risk_table.pack(fill='both', expand=True, padx=10, pady=(8, 8))
        self.add_context_help(self.policy_risk_table, 'Aggregated risk summary for each policy.')

        ttk.Label(parent, text='Right-click a row to view policy details or show its statements.').pack(
            anchor='w', padx=10, pady=(0, 10)
        )

    # ==== Overlap Tab Logic ====
    def _build_overlap_tab(self, parent):
        # Filtering (compartment/resource) ONLY for overlap tab for now, as demo
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.add_context_help(filter_frame, 'Filter overlap analysis by compartment or resource for focused review.')

        ttk.Label(filter_frame, text='Filter by Effective Compartment:').pack(side='left')
        self.overlap_compartment_filter = 'ALL'
        self.overlap_compartment_values = ['ALL']
        self.overlap_compartment_combo = ttk.Combobox(
            filter_frame,
            state='readonly',
            values=self.overlap_compartment_values,
            width=30,
        )
        self.overlap_compartment_combo.set('ALL')
        self.overlap_compartment_combo.pack(side='left', padx=(4, 8))
        self.overlap_compartment_combo.bind('<<ComboboxSelected>>', self._on_overlap_compartment_selected)
        self.add_context_help(self.overlap_compartment_combo, 'Limit view to policies for a specific compartment.')

        ttk.Label(filter_frame, text='Filter by Resource:').pack(side='left')
        self.overlap_resource_filter = 'ALL'
        self.overlap_resource_values = ['ALL']
        self.overlap_resource_combo = ttk.Combobox(
            filter_frame,
            state='readonly',
            values=self.overlap_resource_values,
            width=30,
        )
        self.overlap_resource_combo.set('ALL')
        self.overlap_resource_combo.pack(side='left', padx=(4, 8))
        self.overlap_resource_combo.bind('<<ComboboxSelected>>', self._on_overlap_resource_selected)
        self.add_context_help(
            self.overlap_resource_combo, 'Limit view to policies for a specific type of OCI resource.'
        )

        ttk.Label(filter_frame, text='(Only statements with overlaps appear)').pack(side='left', padx=10)

        ttk.Button(filter_frame, text='Export to CSV', command=self._export_overlap_to_csv).pack(side='right', padx=4)

        def overlap_context_menu(row_index: int) -> tk.Menu | None:
            """Create the row action menu for overlap results."""
            if row_index < 0 or row_index >= len(self.overlap_table.data):
                return None
            row = self.overlap_table.data[row_index]
            overlaps = self.app.policy_intelligence.get_policy_overlaps_by_internal_id(row.get('Internal ID', ''))
            sections = [
                (
                    'Candidate Statement',
                    [
                        f'Policy: {row.get("Policy Name") or "(none)"}',
                        f'Statement: {row.get("Statement Text") or "(none)"}',
                        f'Effective Path: {row.get("Effective Path") or "(none)"}',
                    ],
                )
            ]
            for number, overlap in enumerate(overlaps, start=1):
                sections.append(
                    (
                        f'Overlap Evidence {number}',
                        [
                            f'Policy: {overlap.get("superseded_by") or "(none)"}',
                            f'Statement: {overlap.get("statement_text") or "(none)"}',
                            f'Overlapping Permissions: {", ".join(overlap.get("permission_overlap") or []) or "(none)"}',
                            f'Confidence: {overlap.get("confidence") or "(none)"}',
                            f'Reason: {overlap.get("reason") or "(none)"}',
                            f'Notes: {overlap.get("additional_notes") or "(none)"}',
                        ],
                    )
                )
            menu = tk.Menu(self.overlap_table, tearoff=0)
            menu.add_command(
                label='Overlap Details',
                command=lambda: self._show_recommendation_details('Overlap Details', sections),
            )
            return menu

        self.overlap_table = DataTable(
            parent,
            columns=POLICY_OVERLAP_ALL_COLUMNS,
            display_columns=POLICY_OVERLAP_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_OVERLAP_COLUMN_WIDTHS,
            row_context_menu_callback=overlap_context_menu,
            multi_select=True,
            highlights=[('Action', 'deny', '#FF0000')],
        )
        self.overlap_table.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        self.add_context_help(self.overlap_table, 'See where custom policies may override or duplicate one another.')

        ttk.Label(parent, text='Right-click a row to view overlap evidence.').pack(anchor='w', padx=10, pady=(2, 10))

    def _build_supersession_tab(self, parent):
        """Build the complete-supersession recommendations and tracking controls."""
        controls = ttk.Frame(parent)
        controls.pack(fill='x', padx=10, pady=(10, 4))
        controls.columnconfigure(1, weight=1)
        filter_frame = ttk.Frame(controls)
        filter_frame.grid(row=0, column=0, sticky='w')
        ttk.Label(filter_frame, text='Compartment:').pack(side='left')
        self.supersession_compartment_filter = 'ALL'
        self._supersession_filter_paths = {'All compartments': 'ALL'}
        self.supersession_compartment_combo = ttk.Combobox(
            filter_frame,
            values=['All compartments'],
            state='readonly',
            width=44,
        )
        self.supersession_compartment_combo.set('All compartments')
        self.supersession_compartment_combo.pack(side='left', padx=(4, 8))
        self.supersession_compartment_combo.bind('<<ComboboxSelected>>', self._on_supersession_compartment_selected)
        self.add_context_help(
            self.supersession_compartment_combo,
            'Show supersession findings in this compartment and its descendant compartments. '
            'The number in parentheses is the compartment hierarchy level.',
        )
        intro = ttk.Label(
            controls,
            text=(
                'Complete supersession identifies an allow statement whose full permission set is already granted by '
                'a single unconditional statement for the same principal at the same or an ancestor scope. '
                'Conditional evidence is shown for review but is never used as automatic proof.'
            ),
            justify='left',
            wraplength=780,
        )
        intro.grid(row=0, column=1, sticky='ew', padx=(12, 0))
        self.add_context_help(
            intro, 'Review this evidence before making any policy change; this view never changes policies.'
        )

        def show_supersession_details(row: dict) -> None:
            """Open the selected statement's full coverage evidence in a modal."""
            finding = self.app.policy_intelligence.get_policy_supersession_by_internal_id(
                str(row.get('Internal ID') or '')
            )
            if not finding:
                return
            popup = tk.Toplevel(self.winfo_toplevel())
            popup.title('Supersession Details')
            popup.transient(self.winfo_toplevel())
            popup.resizable(True, True)
            popup.geometry('980x680')
            outer = ttk.Frame(popup)
            outer.pack(fill='both', expand=True, padx=12, pady=12)
            ttk.Label(
                outer,
                text=f'{finding.get("classification", "Supersession")}: {row.get("Policy Name", "Unknown Policy")}',
                font=('TkDefaultFont', 11, 'bold'),
            ).pack(anchor='w', pady=(0, 6))
            candidate_frame = ttk.LabelFrame(outer, text='Candidate Statement')
            candidate_frame.pack(fill='x', pady=(0, 8))
            ttk.Label(
                candidate_frame,
                text=f'Policy: {row.get("Policy Name") or "(none)"}',
            ).pack(anchor='w', padx=8, pady=(6, 1))
            ttk.Label(
                candidate_frame,
                text=f'Statement: {row.get("Statement Text") or "(none)"}',
                wraplength=900,
                justify='left',
            ).pack(anchor='w', padx=8, pady=1)
            ttk.Label(
                candidate_frame,
                text=f'Effective Path: {row.get("Effective Path") or "(none)"}',
            ).pack(anchor='w', padx=8, pady=(1, 6))

            notes_frame = ttk.LabelFrame(outer, text='Coverage Notes')
            notes_frame.pack(fill='x', pady=(0, 8))
            ttk.Label(notes_frame, text=finding.get('notes') or '(none)', wraplength=900, justify='left').pack(
                anchor='w', padx=8, pady=6
            )

            evidence_frame = ttk.LabelFrame(outer, text='Applicable Evidence')
            evidence_frame.pack(fill='x', pady=(0, 8))
            for number, evidence in enumerate(finding.get('evidence', []), start=1):
                evidence_title = ttk.Label(
                    evidence_frame,
                    text=(
                        f'{number}. {evidence.get("policy_name") or "Unknown Policy"}  —  '
                        f'{evidence.get("effective_path") or "Unknown Effective Path"} '
                        f'({evidence.get("relationship") or "Applicable scope"})'
                    ),
                    font=('TkDefaultFont', 10, 'bold'),
                )
                evidence_title.pack(anchor='w', padx=8, pady=((6 if number == 1 else 10), 2))
                ttk.Label(
                    evidence_frame,
                    text=f'Policy: {evidence.get("policy_name") or "(none)"}',
                ).pack(anchor='w', padx=20, pady=1)
                ttk.Label(
                    evidence_frame,
                    text=f'Statement: {evidence.get("statement_text") or "(none)"}',
                    wraplength=900,
                    justify='left',
                ).pack(anchor='w', padx=20, pady=1)
                ttk.Label(
                    evidence_frame,
                    text=f'Effective Path: {evidence.get("effective_path") or "(none)"}',
                ).pack(anchor='w', padx=20, pady=(1, 2))
                if evidence.get('conditional'):
                    ttk.Label(
                        evidence_frame,
                        text='Conditional evidence: review required; not used to prove complete coverage.',
                    ).pack(anchor='w', padx=20, pady=(1, 2))

            comparison_frame = ttk.LabelFrame(outer, text='Permission Coverage')
            comparison_frame.pack(fill='both', expand=True)
            columns = ('candidate_permission', 'covered_by')
            permission_table = ttk.Treeview(comparison_frame, columns=columns, show='headings', height=8)
            permission_table.heading('candidate_permission', text='Candidate Permission')
            permission_table.heading('covered_by', text='Covered By Applicable Evidence')
            permission_table.column('candidate_permission', width=340, anchor='w', stretch=True)
            permission_table.column('covered_by', width=550, anchor='w', stretch=True)
            by_permission: dict[str, list[str]] = {}
            for evidence in finding.get('evidence', []):
                source = (
                    f'{evidence.get("policy_name") or "Unknown Policy"} '
                    f'({evidence.get("effective_path") or "Unknown Effective Path"}; '
                    f'{evidence.get("relationship") or "Applicable scope"})'
                )
                for permission in evidence.get('covered_permissions', []):
                    by_permission.setdefault(str(permission), []).append(source)
            for permission in finding.get('candidate_permissions', []):
                permission_table.insert(
                    '',
                    'end',
                    values=(permission, '; '.join(by_permission.get(str(permission), [])) or '(not resolved)'),
                )
            permission_scrollbar = ttk.Scrollbar(comparison_frame, orient='vertical', command=permission_table.yview)
            permission_table.configure(yscrollcommand=permission_scrollbar.set)
            permission_table.pack(side='left', fill='both', expand=True, padx=(6, 0), pady=6)
            permission_scrollbar.pack(side='right', fill='y', padx=(0, 6), pady=6)
            ttk.Button(outer, text='Close', command=popup.destroy).pack(anchor='e', pady=(8, 0))

        def supersession_context_menu(row_index: int) -> tk.Menu | None:
            """Create the row action menu for complete-supersession results."""
            if row_index < 0 or row_index >= len(self.supersession_table.data):
                return None
            row = self.supersession_table.data[row_index]
            menu = tk.Menu(self.supersession_table, tearoff=0)
            menu.add_command(label='Supersession Details', command=lambda: show_supersession_details(row))
            policy_name = str(row.get('Policy Name') or '')
            compartment_path = str(row.get('Policy Compartment') or '')
            if policy_name:
                menu.add_command(
                    label='Show Full Policy',
                    command=lambda: self._show_full_policy_in_main_analysis(policy_name, compartment_path),
                )
            return menu

        ignored_button = ttk.Button(
            parent, text='Show Previously Ignored', command=lambda: self._on_show_previously_ignored(supersession=True)
        )
        ignored_button.pack(anchor='w', padx=10, pady=(8, 2))
        self.add_context_help(ignored_button, 'Review ignored supersession findings and choose which to show again.')
        self.supersession_table = CheckboxTable(
            parent,
            columns=POLICY_SUPERSESSION_COLUMNS,
            display_columns=['☑'] + POLICY_SUPERSESSION_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_SUPERSESSION_COLUMN_WIDTHS,
            row_context_menu_callback=supersession_context_menu,
            checked_by_default=False,
            action_buttons=[
                ('Attempt/Fix', self._on_supersession_attempt_fix),
                ('Ignore Selected', self._on_supersession_ignore),
            ],
        )
        # Request three fewer rows so the action bar fits on smaller displays.
        self.supersession_table.data_table.tree.configure(height=7)
        self.supersession_table.pack(fill='both', expand=True, padx=10, pady=(4, 4))
        self._add_finding_action_help(self.supersession_table)
        self.add_context_help(
            self.supersession_table,
            'Right-click a statement for complete supersession details.',
        )
        ttk.Label(parent, text='Right-click a row to view complete supersession evidence.').pack(
            anchor='w', padx=10, pady=(2, 10)
        )

    def update_supersession_tab_output(self) -> None:
        """Refresh complete-supersession rows from policy-intelligence output."""
        self.supersession_table.update_data(self._get_supersession_rows())

    def _get_supersession_rows(self, include_ignored=False):
        findings = self.app.policy_intelligence.overlay.get('supersessions', []) or []
        statements = {
            str(statement.get('internal_id') or ''): statement
            for statement in (self.policy_repo.regular_statements or [])
        }
        known_paths: dict[str, str] = {}
        for compartment in getattr(self.policy_repo, 'compartments', []) or []:
            if not isinstance(compartment, dict):
                continue
            path = _normalize_compartment_path(compartment.get('hierarchy_path') or compartment.get('path'))
            if path:
                known_paths.setdefault(path.casefold(), path)
        for statement in statements.values():
            path = _normalize_compartment_path(statement.get('effective_path') or statement.get('compartment_path'))
            if path:
                known_paths.setdefault(path.casefold(), path)
        self._update_supersession_compartment_filter(set(known_paths.values()))

        rows = []
        for finding in findings:
            statement = statements.get(str(finding.get('statement_internal_id') or ''))
            if not statement:
                continue
            display = for_display_policy(statement)
            effective_path = str(display.get('Effective Path') or '')
            if (
                not include_ignored
                and self.supersession_compartment_filter != 'ALL'
                and not _path_is_same_or_descendant(effective_path, self.supersession_compartment_filter)
            ):
                continue
            evidence = finding.get('evidence', []) or []
            rows.append(
                {
                    'Policy Name': display.get('Policy Name', ''),
                    'Policy Compartment': display.get('Policy Compartment', ''),
                    'Effective Path': display.get('Effective Path', ''),
                    'Statement Text': display.get('Statement Text', ''),
                    'Classification': finding.get('classification', ''),
                    'action_key': json.dumps(supersession_finding_identity(statement)),
                    'finding_identity': supersession_finding_identity(statement),
                    'Superseded By': ', '.join(
                        f'{item.get("policy_name", "")} ({item.get("effective_path", "")})' for item in evidence
                    ),
                    'Internal ID': finding.get('statement_internal_id', ''),
                }
            )
        rows.sort(key=lambda row: (str(row['Effective Path']), str(row['Policy Name'])))
        if not include_ignored:
            ignored = getattr(self, 'ignored_cleanup_keys', set())
            rows = [row for row in rows if row['action_key'] not in ignored]
        return rows

    def _add_finding_action_help(self, table):
        for button in table.action_btns:
            help_text = (
                ATTEMPT_FIX_HELP
                if button.cget('text') == 'Attempt/Fix'
                else (
                    'Hide selected findings for this tenancy. Use Show Previously Ignored to restore them. '
                    'Ignoring a finding does not resolve it or change OCI.'
                )
            )
            self.add_context_help(button, help_text)

    def _on_supersession_ignore(self, selected):
        if not selected:
            tkinter.messagebox.showinfo('No selection', 'Select one or more supersession findings first.')
            return
        self.ignored_cleanup_keys.update(row['action_key'] for row in selected)
        self._save_ignored_cleanup_keys_to_state()
        self.update_supersession_tab_output()

    def _on_supersession_attempt_fix(self, selected):
        if not selected:
            tkinter.messagebox.showinfo('No selection', 'Select one or more supersession findings first.')
            return
        actions = []
        for row in selected:
            actions.append(
                {
                    'Source': 'Supersession',
                    'Type': 'Superseded Statement',
                    'tenancy_ocid': self.app.policy_compartment_analysis.tenancy_ocid,
                    'finding_identity': row['finding_identity'],
                    'Description': f'{row.get("Policy Name", "")}: {row.get("Statement Text", "")}',
                    'ui_instructions': (
                        f'Review Supersession Details for this statement: {row.get("Statement Text", "")}\n'
                        f'Classification: {row.get("Classification", "")}\n'
                        f'Superseded by: {row.get("Superseded By", "")}\n'
                        'Confirm the superseding permissions, conditions, and scope still meet requirements. '
                        'Resolve any review qualifications in the evidence before making changes. '
                        'If redundant, remove only the superseded statement from its policy in OCI. '
                        'Keep a copy for rollback. Then use Reload All to verify the finding is resolved.'
                    ),
                    'rollback_command': f'Restore the original statement: {row.get("Statement Text", "")}',
                }
            )
        self._add_workbench_actions(actions)

    def _update_supersession_compartment_filter(self, paths: set[str]) -> None:
        """Refresh filter choices from loaded compartments while preserving selection."""
        if not hasattr(self, 'supersession_compartment_combo'):
            return
        ordered_paths = sorted(
            paths,
            key=lambda path: (len([segment for segment in path.split('/') if segment]), path.casefold()),
        )
        filter_paths = {'All compartments': 'ALL'}
        for path in ordered_paths:
            filter_paths[_compartment_filter_label(path)] = path
        self._supersession_filter_paths = filter_paths
        self.supersession_compartment_combo['values'] = list(filter_paths)
        if self.supersession_compartment_filter not in set(filter_paths.values()):
            self.supersession_compartment_filter = 'ALL'
            self.supersession_compartment_combo.set('All compartments')
            return
        selected_label = next(
            label for label, path in filter_paths.items() if path == self.supersession_compartment_filter
        )
        self.supersession_compartment_combo.set(selected_label)

    def _on_supersession_compartment_selected(self, _event=None) -> None:
        """Filter supersession findings to the selected compartment subtree."""
        selected = self.supersession_compartment_combo.get()
        self.supersession_compartment_filter = self._supersession_filter_paths.get(selected, 'ALL')
        self.update_supersession_tab_output()

    def _export_overlap_to_csv(self):
        if not self.policy_repo.regular_statements:
            tkinter.messagebox.showinfo('Export', 'No overlap data to export.')
            return

        # Build the same filtered set that the overlap table displays
        from oci_policy_analysis.application.core.models.models import PolicySearch

        filters: PolicySearch = {}
        if self.overlap_compartment_filter != 'ALL':
            filters['effective_path'] = [self.overlap_compartment_filter]
        if self.overlap_resource_filter != 'ALL':
            filters['resource'] = [self.overlap_resource_filter]

        statements_with_overlaps = [
            st
            for st in self.policy_repo.filter_policy_statements(filters=filters)
            if self.app.policy_intelligence.get_policy_overlaps_by_internal_id(st.get('internal_id'))
        ]

        if not statements_with_overlaps:
            tkinter.messagebox.showinfo('Export', 'No overlap data to export.')
            return

        filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
        if not filepath:
            return

        export_columns = [
            'Policy Name',
            'Policy Compartment',
            'Effective Path',
            'Action',
            'Statement Text',
            'Valid',
            'Overlap Count',
            'Overlapping Policies',
            'Overlapping Statements',
            'Overlapping Permissions',
            'Confidence Levels',
            'Reasons',
        ]
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(export_columns)
            for st in statements_with_overlaps:
                overlaps = self.app.policy_intelligence.get_policy_overlaps_by_internal_id(st.get('internal_id'))
                writer.writerow(
                    [
                        st.get('policy_name', ''),
                        st.get('compartment_path', ''),
                        st.get('effective_path', ''),
                        st.get('action', ''),
                        st.get('statement_text', ''),
                        st.get('valid', ''),
                        len(overlaps),
                        ' | '.join(o.get('superseded_by', '') for o in overlaps),
                        ' | '.join(o.get('statement_text', '') for o in overlaps),
                        ' | '.join(', '.join(p.upper() for p in o.get('permission_overlap', [])) for o in overlaps),
                        ' | '.join(str(o.get('confidence', '')) for o in overlaps),
                        ' | '.join(o.get('reason', '') for o in overlaps),
                    ]
                )
        logger.info(f'Exported {len(statements_with_overlaps)} overlap statements to {filepath}')
        tkinter.messagebox.showinfo(
            'Export Complete', f'Exported {len(statements_with_overlaps)} overlap statements to {filepath}'
        )

    # ==== Data/Logic Methods ====
    def _update_reload_all_button_state(self):
        """Enable Reload All only when data was loaded from tenancy (not cache/compliance)."""
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        can_reload = bool(
            repo
            and getattr(repo, 'policies_loaded_from_tenancy', False)
            and not getattr(repo, 'loaded_from_compliance_output', False)
            and getattr(self.app, '_live_tenancy_load_options', None)
            and not getattr(self, '_cleanup_reload_pending', False)
            and not getattr(self.app, '_tenancy_load_in_progress', False)
            and not getattr(self.app, '_policy_reload_in_progress', False)
        )
        if hasattr(self, 'reload_all_btn'):
            self.reload_all_btn['state'] = tk.NORMAL if can_reload else tk.DISABLED

    def _on_reload_all(self):
        """Refresh live IAM/policies, then reconcile tracked findings after successful intelligence."""
        self._update_reload_all_button_state()
        if str(self.reload_all_btn['state']) == str(tk.DISABLED):
            return
        self._cleanup_reload_pending = True
        self._update_reload_all_button_state()

        def complete(success, message, is_error):
            self._cleanup_reload_pending = False
            if success:
                self._reconcile_cleanup_progress()
                self.app.policy_compartment_analysis._cleanup_live_refresh_complete = False
            else:
                tkinter.messagebox.showerror('Reload All Failed', message)
            self._update_reload_all_button_state()
            # The shared progress dialog releases its busy flag after closing.
            self.after(2000, self._update_reload_all_button_state)

        self.app.reload_policies_and_compartments_and_update_cache_async(
            callback={'complete': complete, 'error': complete},
            show_popup=True,
            reload_iam=True,
        )

    def reload_all_analytics(self):
        self._activate_cleanup_tenancy()
        self._update_reload_all_button_state()
        logger.info('Reloading all policy intelligence analytics for unified recommendations tab.')

        # Select filter vars for statement and policy tab separately
        pct_str_st = (
            self.where_reduction_pct_var.get().replace('%', '') if hasattr(self, 'where_reduction_pct_var') else '50'
        )
        pct_str_policy = (
            self.where_reduction_pct_var_policy.get().replace('%', '')
            if hasattr(self, 'where_reduction_pct_var_policy')
            else pct_str_st
        )
        try:
            where_pct = int(pct_str_policy)
        except Exception:
            where_pct = 50
        svc_str_policy = getattr(self, 'service_reduction_pct_var_policy', None)
        if svc_str_policy:
            try:
                service_pct = int(svc_str_policy.get().replace('%', ''))
            except Exception:
                service_pct = 50
        else:
            # fallback
            service_pct = 50
        logger.info(
            f'Recalculating analytics with WHERE clause reduction pct: {where_pct}%, Service Principal: {service_pct}%'
        )
        pi = self.app.policy_intelligence
        enabled_strategy_ids = self.app.settings.get('enabled_intelligence_checks', None)
        consolidation_names = []
        if hasattr(self.app, 'consolidation_engine') and self.app.consolidation_engine:
            consolidation_names = self.app.consolidation_engine.get_strategy_display_names() or []
        params = {
            'where_clause_reduction_pct': where_pct,
            'service_principal_reduction_pct': service_pct,
            'consolidation_strategy_names': consolidation_names,
        }
        pi.run_all(enabled_strategy_ids=enabled_strategy_ids, params=params)

        # Load ignored cleanup keys from per-tenancy state
        self._load_ignored_cleanup_keys_from_state()

        # Now update all display tables
        self.update_risk_tab_output()
        self.update_policy_risk_tab_output()
        self.update_supersession_tab_output()
        self.update_consolidation_tab_output()
        self.update_cleanup_tab_output()

        # Recommendation Summary at top
        recs = self._get_recommendation_summary()
        logger.info(f'Updating recommendation summary with {len(recs)} entries.')
        if recs and hasattr(logger, 'info'):
            logger.info(
                f'First recommendation keys: {list(recs[0].keys()) if isinstance(recs[0], dict) else "Not a dict"}'
            )
        # Ensure all required columns are present for every row (prevent blank table w/ field mismatch)
        required_cols = ['Recommendation', 'Priority', 'Category', 'Notes', 'Action']
        normalized_recs = []
        for row in recs:
            norm = {col: row.get(col, '') for col in required_cols}
            action_detail = row.get('ActionDetail')
            action_steps = row.get('ActionSteps')
            if action_detail or action_steps:
                detail_parts = [str(action_detail or '')]
                if isinstance(action_steps, list) and action_steps:
                    detail_parts.append(' Steps: ' + ' | '.join(str(step) for step in action_steps))
                norm['Action'] = f'{norm.get("Action", "")} -- {" ".join(part for part in detail_parts if part)}'
            normalized_recs.append(norm)
        self.recommendation_table.update_data(normalized_recs)
        repo = self.app.policy_compartment_analysis
        if getattr(repo, '_cleanup_live_refresh_complete', False) and not getattr(
            self, '_cleanup_reload_pending', False
        ):
            self._reconcile_cleanup_progress()
            repo._cleanup_live_refresh_complete = False

    def on_enabled_cleanup_checks_changed(self):
        """Called when Settings > Recommendation/Consolidation cleanup check toggles change. Re-runs analytics with new checks."""
        self.reload_all_analytics()

    def update_policy_risk_tab_output(self):  # noqa: C901
        """
        Aggregates risk per policy (from statement risk) and updates the table.
        Adds globally normalized risk and supporting stats.
        """
        policies = self.policy_repo.policies
        policy_by_ocid = {p.get('policy_ocid'): p for p in policies if p.get('policy_ocid')}
        statements = self.policy_repo.regular_statements
        risk_scores = self.app.policy_intelligence.overlay.get('risk_scores', [])
        risk_score_map = {entry.get('statement_internal_id'): entry for entry in risk_scores}

        # Map policy_ocid to list of statements (allow only)
        from collections import defaultdict

        policy_stmt_map = defaultdict(list)
        for st in statements:
            # Exclude deny
            if st.get('action', '').lower() == 'deny':
                continue
            pol_oid = st.get('policy_ocid')
            if pol_oid:
                policy_stmt_map[pol_oid].append(st)

        # Gather all max scores for proper normalization
        global_max = 1
        for stmts in policy_stmt_map.values():
            for st in stmts:
                internal_id = st.get('internal_id')
                risk_entry = risk_score_map.get(internal_id, {})
                score = risk_entry.get('score', 0)
                if score > global_max:
                    global_max = score

        data_to_display = []
        for pol_oid, stmts in policy_stmt_map.items():
            policy_obj = policy_by_ocid.get(pol_oid, {})
            policy_path = self._get_policy_path(policy_obj=policy_obj)
            scores = []
            note_summaries = set()
            example_statement = ''
            example_score = -1
            for st in stmts:
                internal_id = st.get('internal_id')
                risk_entry = risk_score_map.get(internal_id, {})
                score = risk_entry.get('score', 0)
                scores.append(score)
                if score > example_score:
                    example_score = score
                    example_statement = st.get('statement_text', '') or ''
                notes = risk_entry.get('notes')
                if notes:
                    note_summaries.add(notes)
            if scores:
                max_score = max(scores)
                avg_score = round(sum(scores) / len(scores), 1)
                total_raw_risk = sum(scores)
                try:
                    max_risk_global_pct = 1
                    if global_max > 0:
                        import math

                        if max_score == 0:
                            max_risk_global_pct = 1
                        elif global_max > 1:
                            max_risk_global_pct = int((math.log(max_score) / math.log(global_max)) * 100)
                            if max_risk_global_pct < 1:
                                max_risk_global_pct = 1
                    else:
                        max_risk_global_pct = 1
                except Exception:
                    max_risk_global_pct = 1
            else:
                max_score = 0
                avg_score = 0
                max_risk_global_pct = 0
                example_statement = ''
                total_raw_risk = 0
            data_to_display.append(
                {
                    'Policy Path': policy_path,
                    'Total Statements': len(stmts),
                    'Max Score': max_score,
                    'Avg Score': avg_score,
                    'Max Statement Risk (Global %)': max_risk_global_pct,
                    'Total Raw Risk': total_raw_risk,
                    'Risk Summary/Notes': ';  '.join(note_summaries)[:500],
                    'Example Statement': example_statement[:300],
                }
            )

        threshold_val = (
            self.policy_risk_threshold_var.get() if hasattr(self, 'policy_risk_threshold_var') else 'Show all'
        )
        if threshold_val == 'Relative Risk > 50':
            filtered = [row for row in data_to_display if (row.get('Max Statement Risk (Global %)') or 0) > 50]
        elif threshold_val == 'Relative Risk > 80':
            filtered = [row for row in data_to_display if (row.get('Max Statement Risk (Global %)') or 0) > 80]
        else:
            filtered = data_to_display

        self.policy_risk_table.update_data(filtered)
        # Obsolete timing removed; handled by timed_step at top level

    # ---- Risk Tab update logic ----
    def update_risk_tab_output(self):  # noqa: C901
        """
        Update statement risk table: only allow statements, columns: Policy Path, Effective Path, Score, Relative Risk, Risk Notes, Statement Text (truncated).
        """
        statements = self.policy_repo.regular_statements
        risk_scores = self.app.policy_intelligence.overlay.get('risk_scores', [])
        risk_score_map = {entry.get('statement_internal_id'): entry for entry in risk_scores}

        import math

        data_to_display = []
        scores_list = []
        for st in statements:
            if st.get('action', '').lower() == 'deny':
                continue
            policy_path = self._get_policy_path(policy_ocid=st.get('policy_ocid'))
            effective_path = st.get('effective_path') or st.get('Effective Path') or ''
            internal_id = st.get('internal_id')
            score = 0
            notes = ''
            risk_entry = risk_score_map.get(internal_id, None)
            if risk_entry:
                score = risk_entry.get('score', 0)
                notes = risk_entry.get('notes', '')
            # Relative risk calculation in table context (using all allowed statement scores)
            scores_list.append(score)
            row = {
                'Policy Path': policy_path,
                'Effective Path': effective_path,
                'Score': score,
                'Risk Notes': notes,
                'Statement Text': (st.get('statement_text') or '')[:120],
            }
            data_to_display.append(row)

        # Compute relative risk globally over allowed statements (not per policy)
        all_scores = [row['Score'] for row in data_to_display]
        max_score = max(all_scores) if all_scores else 1
        for row in data_to_display:
            raw = row['Score']
            rel_val = 0
            if raw == 0:
                rel_val = 1
            elif max_score > 0:
                rel_val = int((math.log(raw) / math.log(max_score)) * 100) if raw > 0 and max_score > 1 else 0
            else:
                rel_val = 0
            if rel_val < 1:
                rel_val = 1
            row['Relative Risk'] = rel_val

        threshold = self.risk_threshold_var.get()
        if threshold == 'Relative Risk > 50':
            filtered = [row for row in data_to_display if (row.get('Relative Risk') or 0) > 50]
        elif threshold == 'Relative Risk > 80':
            filtered = [row for row in data_to_display if (row.get('Relative Risk') or 0) > 80]
        else:
            filtered = data_to_display

        self.risk_table.update_data(filtered)

    # ---- Overlap Tab update logic ----
    def update_overlap_tab_output(self):  # noqa: C901
        # Build dropdowns and filtered table, like overlap_tab's update_overlap_output
        if not self.policy_repo.regular_statements:
            self.overlap_table.update_data([])
            self.overlap_compartment_combo['values'] = ['ALL']
            self.overlap_compartment_combo.set('ALL')
            self.overlap_resource_combo['values'] = ['ALL']
            self.overlap_resource_combo.set('ALL')
            return

        # Only include statements with overlaps in the overlay
        statements_with_overlaps = []
        for st in self.policy_repo.regular_statements:
            internal_id = st.get('internal_id')
            overlaps = self.app.policy_intelligence.get_policy_overlaps_by_internal_id(internal_id)
            if overlaps:
                statements_with_overlaps.append(st)

        statements_all = [for_display_policy(st) for st in statements_with_overlaps]

        # Effective Path dropdown
        paths_raw = {st.get('Effective Path') for st in statements_all}
        paths = {p for p in paths_raw if isinstance(p, str)}
        compartment_list = ['ALL'] + sorted(paths)
        self.overlap_compartment_combo['values'] = compartment_list
        if self.overlap_compartment_filter not in compartment_list:
            self.overlap_compartment_filter = 'ALL'
            self.overlap_compartment_combo.set('ALL')

        # Resource dropdown
        resources_raw = set()
        for st in statements_all:
            val = st.get('Resource')
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        resources_raw.add(v)
            elif isinstance(val, str):
                resources_raw.add(val)
        resource_list = ['ALL'] + sorted(resources_raw)
        self.overlap_resource_combo['values'] = resource_list
        if self.overlap_resource_filter not in resource_list:
            self.overlap_resource_filter = 'ALL'
            self.overlap_resource_combo.set('ALL')

        from oci_policy_analysis.application.core.models.models import PolicySearch

        filters: PolicySearch = {}
        if self.overlap_compartment_filter != 'ALL':
            filters['effective_path'] = [self.overlap_compartment_filter]
        if self.overlap_resource_filter != 'ALL':
            filters['resource'] = [self.overlap_resource_filter]

        filtered_statements = [
            st
            for st in self.policy_repo.filter_policy_statements(filters=filters)
            if self.app.policy_intelligence.get_policy_overlaps_by_internal_id(st.get('internal_id'))
        ]
        normalized = [for_display_policy(st) for st in filtered_statements]

        self.overlap_table.update_data(normalized)

    # --- Overlap filters event handlers ---
    def _on_overlap_compartment_selected(self, event=None):
        selected = self.overlap_compartment_combo.get()
        self.overlap_compartment_filter = selected if selected != 'ALL' else 'ALL'
        self.update_overlap_tab_output()

    def _on_overlap_resource_selected(self, event=None):
        selected = self.overlap_resource_combo.get()
        self.overlap_resource_filter = selected if selected != 'ALL' else 'ALL'
        self.update_overlap_tab_output()

    # --- Consolidation Sub-Tab ---
    def _build_consolidation_tab(self, parent):
        """
        Build the Policy Consolidation notebook sub-tab.
        """
        # Workbench area routes selected findings to the advanced consolidation
        # workflow without duplicating its strategy selection and validation.
        workbench_frame = ttk.Frame(parent)
        workbench_frame.pack(fill='x', padx=10, pady=(8, 4))
        workbench_frame.columnconfigure(0, weight=1)
        workbench_frame.columnconfigure(1, weight=0)
        ttk.Label(
            workbench_frame,
            text=(
                'Consolidation suggestions and Policy Placement findings identify statements to review. '
                'Use Show Consolidation Opportunity to review evidence. Check only opportunities marked ready '
                'for the Consolidation Workbench.'
            ),
            # wraplength=700,
            justify='left',
        ).grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.add_context_help(
            workbench_frame,
            'The table is a compact opportunity queue. Right-click any row to inspect all policies, statements, and evidence.',
        )

        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(2, 4))
        ttk.Label(filter_frame, text='Consolidation type:').pack(side='left', padx=(0, 4))
        self.consolidation_type_var = tk.StringVar(value='All')
        self.consolidation_type_combo = ttk.Combobox(
            filter_frame, textvariable=self.consolidation_type_var, state='readonly', values=['All'], width=34
        )
        self.consolidation_type_combo.pack(side='left', padx=(0, 12))
        self.consolidation_type_combo.bind('<<ComboboxSelected>>', lambda _event: self._apply_consolidation_filters())
        ttk.Label(filter_frame, text='Search:').pack(side='left', padx=(0, 4))
        self.consolidation_search_var = tk.StringVar()
        search_entry = ttk.Entry(filter_frame, textvariable=self.consolidation_search_var, width=34)
        search_entry.pack(side='left', fill='x', expand=True)
        self.consolidation_search_var.trace_add('write', lambda *_args: self._apply_consolidation_filters())
        ttk.Button(filter_frame, text='Clear', command=self._clear_consolidation_filters).pack(side='left', padx=(6, 0))

        self.consolidation_guidance_var = tk.StringVar(
            value='Choose a consolidation type to see the strategy best suited to that finding.'
        )
        ttk.Label(parent, textvariable=self.consolidation_guidance_var, justify='left', wraplength=1000).pack(
            fill='x', padx=10, pady=(0, 2)
        )

        self.consolidation_table = CheckboxTable(
            parent,
            columns=POLICY_CONSOLIDATION_COLUMNS,
            display_columns=POLICY_CONSOLIDATION_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_CONSOLIDATION_COLUMN_WIDTHS,
            action_buttons=[('Create Consolidation Plan', self._on_create_consolidation_plan)],
            enable_select_all=True,
            checked_by_default=False,
            row_context_menu_callback=self._consolidation_row_context_menu,
        )
        self.consolidation_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.consolidation_plan_button = self.consolidation_table.action_btns[0]
        self.update_consolidation_plan_availability()
        self.add_context_help(
            self.consolidation_table,
            'Only actionable opportunities show a checkbox. Use the context menu to review the complete evidence before handoff.',
        )

    # REMOVED: _on_open_consolidation_workbench() (workbench not available)

    def update_consolidation_tab_output(self):
        """Refresh the consolidation tab's data after analytics reload."""
        self._all_consolidation_rows = self._get_policy_consolidation_rows()
        types = sorted({str(row.get('Type') or '') for row in self._all_consolidation_rows if row.get('Type')})
        if hasattr(self, 'consolidation_type_combo'):
            self.consolidation_type_combo['values'] = ['All', *types]
            if self.consolidation_type_var.get() not in {'All', *types}:
                self.consolidation_type_var.set('All')
        self._apply_consolidation_filters()

    def _clear_consolidation_filters(self) -> None:
        self.consolidation_type_var.set('All')
        self.consolidation_search_var.set('')

    def _apply_consolidation_filters(self) -> None:
        rows = list(getattr(self, '_all_consolidation_rows', []) or [])
        selected_type = self.consolidation_type_var.get() if hasattr(self, 'consolidation_type_var') else 'All'
        query = (
            self.consolidation_search_var.get().strip().casefold() if hasattr(self, 'consolidation_search_var') else ''
        )
        if selected_type != 'All':
            rows = [row for row in rows if row.get('Type') == selected_type]
        if query:
            rows = [row for row in rows if query in ' '.join(str(value) for value in row.values()).casefold()]
        logger.info('Updating consolidation tab with %d filtered records.', len(rows))
        if hasattr(self, 'consolidation_table'):
            self.consolidation_table.update_data(rows)
        if hasattr(self, 'consolidation_guidance_var'):
            guidance = {
                'Single-statement policy': 'Strategy: review nearby policies with the same principal and scope; merge only when the combined policy remains clear and within statement limits.',
                'Duplicate scope across policies': 'Strategy: compare the grouped policies, retain the least-privileged effective statements, then consolidate duplicates into one clearly named policy.',
                'Policy placement': 'Strategy: use the Policy Placement workbench to move statements nearer their effective scope after checking inherited access.',
                'Group similar statements': 'Strategy: review the grouped evidence, then send the complete statement set to Group Similar Statements.',
            }
            self.consolidation_guidance_var.set(
                guidance.get(
                    selected_type, 'Choose a consolidation type to see the strategy best suited to that finding.'
                )
            )

    def update_consolidation_plan_availability(self):
        """Enable the workbench handoff only while Advanced Tabs are visible."""
        if not hasattr(self, 'consolidation_plan_button'):
            return
        enabled = bool(
            getattr(self.app, 'advanced_tabs_visible', False) and getattr(self.app, 'consolidation_tab', None)
        )
        self.consolidation_plan_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _on_create_consolidation_plan(self, selected_rows):
        """Transfer complete actionable opportunities to the advanced workbench."""
        if not getattr(self.app, 'advanced_tabs_visible', False) or not getattr(self.app, 'consolidation_tab', None):
            tkinter.messagebox.showinfo(
                'Advanced Tabs required',
                'Enable Settings > Show Advanced Tabs to create a consolidation plan from selected findings.',
            )
            return
        actionable = [row for row in selected_rows if row.get('Handoff Mode') == 'supported']
        if len(actionable) != len(selected_rows):
            tkinter.messagebox.showinfo(
                'Review-only opportunity selected',
                'Only supported opportunities can be sent to the Consolidation Workbench. Use Show Consolidation Opportunity for advisory rows.',
            )
            return
        strategy_names = {str(row.get('Recommended Strategy') or '') for row in actionable}
        if len(strategy_names) > 1:
            tkinter.messagebox.showinfo(
                'Select one opportunity type',
                'Send one supported opportunity type at a time so the Consolidation Workbench can use its recommended strategy.',
            )
            return
        statement_ids = {
            str(statement_id)
            for row in actionable
            for statement_id in (row.get('Statement Internal IDs') or [])
            if str(statement_id)
        }
        if not statement_ids:
            tkinter.messagebox.showinfo(
                'Select an actionable opportunity',
                'Select one or more checked opportunities with statement evidence.',
            )
            return
        if not tkinter.messagebox.askyesno(
            'Create Consolidation Plan',
            (
                f'Open Candidate Selection with {len(statement_ids)} selected statement(s)?\n\n'
                + (
                    f'The recommended strategy, {next(iter(strategy_names))}, will be preselected. '
                    if next(iter(strategy_names))
                    else 'Choose the appropriate placement strategy in the Consolidation Workbench. '
                )
                + 'The resulting proposal applies only to these statements and replaces the current workbench candidate selection.'
            ),
        ):
            return
        accepted_ids = self.app.consolidation_tab.select_candidate_statements(
            statement_ids, strategy_display_name=next(iter(strategy_names)) or None
        )
        if not accepted_ids:
            tkinter.messagebox.showwarning(
                'No available candidates',
                'The selected statements are protected, invalid, or belong to a system policy and cannot be consolidated.',
            )
            return
        self.app.notebook.select(self.app.consolidation_tab)

    def _consolidation_row_context_menu(self, row_index):
        """Expose the detailed evidence without overcrowding the opportunity table."""
        row = self.consolidation_table.data[row_index]
        menu = tk.Menu(self.consolidation_table, tearoff=0)
        menu.add_command(
            label='Show Consolidation Opportunity', command=lambda: self._show_consolidation_opportunity(row)
        )
        return menu

    def _show_consolidation_opportunity(self, opportunity: dict) -> None:
        """Display a read-only policy-and-statement evidence dialog for one opportunity."""
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(f"Consolidation Opportunity: {opportunity.get('Type', 'Unknown')}")
        dialog.transient(self.winfo_toplevel())
        dialog.geometry('960x620')
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text=(
                f"{opportunity.get('Type', '')}  |  {opportunity.get('Policies', 0)} policies  |  "
                f"{opportunity.get('Statements', 0)} statements\n{opportunity.get('Summary', '')}"
            ),
            justify='left',
            wraplength=900,
        ).grid(row=0, column=0, sticky='ew', padx=12, pady=(12, 6))
        text = tk.Text(dialog, wrap='word', height=25)
        text.grid(row=1, column=0, sticky='nsew', padx=12, pady=6)
        evidence = opportunity.get('Evidence') or {}
        lines = [
            f"Recommended action: {opportunity.get('Recommended Action', '')}",
            f"Handoff: {opportunity.get('Handoff Mode', '')}",
            '',
            'Why this is an opportunity:',
            str(evidence.get('reason') or ''),
            '',
            'Commonality:',
            str(evidence.get('commonality') or ''),
            '',
            'Policies and statements:',
        ]
        for item in evidence.get('members') or []:
            lines.extend(
                [
                    f"• {item.get('policy_name') or 'Unknown policy'} ({item.get('policy_ocid') or 'no OCID'})",
                    f"  [{item.get('internal_id') or 'no internal ID'}] {item.get('statement_text') or ''}",
                ]
            )
        proposed = evidence.get('proposed_statement')
        if proposed:
            lines.extend(['', 'Proposed grouped statement:', str(proposed)])
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')
        actions = ttk.Frame(dialog)
        actions.grid(row=2, column=0, sticky='ew', padx=12, pady=(4, 12))
        if opportunity.get('Handoff Mode') == 'supported':
            ttk.Button(
                actions,
                text='Send to Consolidation Workbench',
                command=lambda: (dialog.destroy(), self._on_create_consolidation_plan([opportunity])),
            ).pack(side='left')
        ttk.Button(actions, text='Close', command=dialog.destroy).pack(side='right')

    def _get_policy_consolidation_rows(self):
        """Return shared opportunity rows for the desktop consolidation table."""
        intelligence = getattr(self.app, 'policy_intelligence', None)
        overlay = getattr(intelligence, 'overlay', {}) if intelligence else {}
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        return build_consolidation_opportunities(overlay, repo)

    # --- Cleanup / Fix Tab ---
    def _load_ignored_cleanup_keys_from_state(self):
        """Load ignored_cleanup_keys from per-tenancy consolidation state. No-op if no tenancy_ocid."""
        self.ignored_cleanup_keys = set()
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        tenancy_ocid = getattr(repo, 'tenancy_ocid', None) if repo else None
        if not tenancy_ocid or str(tenancy_ocid).lower() in ('unknown', '', 'none'):
            return
        try:
            state = self.app.caching.get_or_create_consolidation_state(tenancy_ocid)
            self.ignored_cleanup_keys = set(state.get('ignored_cleanup_keys', []))
        except Exception as e:
            logger.debug('Could not load ignored cleanup keys from state: %s', e)

    def _save_ignored_cleanup_keys_to_state(self):
        """Persist ignored_cleanup_keys to per-tenancy consolidation state. No-op if no tenancy_ocid."""
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        tenancy_ocid = getattr(repo, 'tenancy_ocid', None) if repo else None
        if not tenancy_ocid or str(tenancy_ocid).lower() in ('unknown', '', 'none'):
            return
        try:
            state = self.app.caching.get_or_create_consolidation_state(tenancy_ocid)
            state['ignored_cleanup_keys'] = list(self.ignored_cleanup_keys)
            self.app.caching.save_consolidation_state(tenancy_ocid, state)
        except Exception as e:
            logger.warning('Could not save ignored_cleanup_keys to state: %s', e)

    def _on_show_previously_ignored(self, supersession=False):
        """Open a dialog listing currently ignored cleanup items; user can re-show selected or all."""
        label = 'supersession' if supersession else 'cleanup'
        refresh = self.update_supersession_tab_output if supersession else self.update_cleanup_tab_output
        all_issues = (
            [
                dict(row, Type='Superseded Statement', Name=row['Statement Text'], Reason=row['Classification'])
                for row in self._get_supersession_rows(include_ignored=True)
            ]
            if supersession
            else self._get_cleanup_issues(include_ignored=True)
        )
        ignored = getattr(self, 'ignored_cleanup_keys', set())
        ignored_list = [i for i in all_issues if i.get('action_key') in ignored]
        if not ignored_list:
            tkinter.messagebox.showinfo(
                'No ignored items',
                f'There are no current ignored {label} findings. Use "Ignore Selected" to hide items.',
            )
            return

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title(f'Previously ignored {label} items')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.geometry('720x380')

        ttk.Label(
            dialog,
            text=f'Select {label} items to show again (they will no longer be ignored).',
            wraplength=680,
        ).pack(fill='x', padx=12, pady=(12, 6))

        # Treeview: Type, Name, Reason (and we keep action_key in row for lookup)
        tree_frame = ttk.Frame(dialog)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=6)
        cols = ('Type', 'Name', 'Reason')
        tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=12, selectmode='extended')
        tree.column('Type', width=140)
        tree.column('Name', width=220)
        tree.column('Reason', width=320)
        for c in cols:
            tree.heading(c, text=c)
        scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        key_by_iid = {}
        for item in ignored_list:
            key = item.get('action_key')
            key_by_iid[
                tree.insert(
                    '',
                    'end',
                    values=(
                        item.get('Type', ''),
                        (item.get('Name', '') or '')[:80],
                        (item.get('Reason', '') or '')[:100],
                    ),
                )
            ] = key

        def re_show_selected():
            sel = tree.selection()
            if not sel:
                tkinter.messagebox.showinfo('No selection', 'Select one or more rows, then click Re-show selected.')
                return
            for iid in sel:
                k = key_by_iid.get(iid)
                if k:
                    self.ignored_cleanup_keys.discard(k)
            self._save_ignored_cleanup_keys_to_state()
            refresh()
            dialog.destroy()

        def re_show_all():
            for k in key_by_iid.values():
                self.ignored_cleanup_keys.discard(k)
            self._save_ignored_cleanup_keys_to_state()
            refresh()
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill='x', padx=12, pady=(6, 12))
        ttk.Button(btn_frame, text='Re-show selected', command=re_show_selected).pack(side='left', padx=(0, 8))
        ttk.Button(btn_frame, text='Re-show all', command=re_show_all).pack(side='left', padx=(0, 8))
        ttk.Button(btn_frame, text='Cancel', command=dialog.destroy).pack(side='left')

    def _build_cleanup_tab(self, parent):  # noqa: C901
        """
        Build the Cleanup / Fix notebook sub-tab using CheckboxTable for issues/actions.
        Which cleanup checks run is controlled in Settings > Recommendation / Consolidation.
        """
        self.cleanup_columns = ['Type', 'Name', 'Reason', 'Action', 'action_key']
        cleanup_column_widths = {'Type': 150, 'Name': 330, 'Reason': 650, 'Action': 270, 'action_key': 1}
        cleanup_display_columns = ['☑', 'Type', 'Name', 'Reason', 'Action']

        # Row with "Show Previously Ignored" so user can re-add ignored items
        cleanup_btn_frame = ttk.Frame(parent)
        cleanup_btn_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.btn_show_previously_ignored = ttk.Button(
            cleanup_btn_frame,
            text='Show Previously Ignored',
            command=self._on_show_previously_ignored,
        )
        self.btn_show_previously_ignored.pack(side='left', padx=(0, 8))
        self.add_context_help(
            self.btn_show_previously_ignored,
            'Open a list of cleanup items you previously ignored. Choose which to re-show in the table (removes from ignored).',
        )

        def on_take_fix_action(selected):
            if not selected:
                tkinter.messagebox.showinfo('No selection', 'Select one or more cleanup items, then try again.')
                return
            actions = self._build_cleanup_fix_workbench_actions(selected)
            if actions:
                self._add_workbench_actions(actions)
            else:
                tkinter.messagebox.showinfo('No actions', 'Could not build actions for the selected items.')

        def on_ignore_selected(selected):
            if not selected:
                tkinter.messagebox.showinfo(
                    'No selection', 'Select one or more cleanup items to ignore, then click Ignore Selected.'
                )
                return
            for row in selected:
                key = row.get('action_key')
                if key:
                    self.ignored_cleanup_keys.add(key)
            self._save_ignored_cleanup_keys_to_state()
            self.update_cleanup_tab_output()

        def row_context_menu_callback(row_index):
            row = self.cleanup_table.data[row_index]
            t = row.get('Type', '')
            # Select menu label based on item type
            if t == 'Invalid Statement' or t == 'Any-user Without Where' or t == 'Overly Broad Statement':
                label = 'Policy Statement Detail'
            elif t == 'Group w/ No Users':
                label = 'Group Detail'
            elif t == 'Unused Dynamic Group':
                label = 'Dynamic Group Detail'
            else:
                label = 'Detail'
            menu = tk.Menu(self.cleanup_table, tearoff=0)
            menu.add_command(label='Show Cleanup Details', command=lambda: self._show_cleanup_details(row))
            menu.add_separator()
            menu.add_command(label=label, command=lambda: self._on_focus_cleanup_row(row))
            return menu

        self.cleanup_table = CheckboxTable(
            parent,
            columns=self.cleanup_columns,
            data=self._get_cleanup_issues(),
            column_widths=cleanup_column_widths,
            display_columns=cleanup_display_columns,
            action_buttons=[
                ('Attempt/Fix', on_take_fix_action),
                ('Ignore Selected', on_ignore_selected),
            ],
            enable_select_all=True,
            checked_by_default=False,
            row_context_menu_callback=row_context_menu_callback,
        )
        # Make the table (and thus all internal widgets) expand to full width
        self.cleanup_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(self.cleanup_table, 'Select and track security hygiene issues for policies.')
        self._add_finding_action_help(self.cleanup_table)

    def _show_cleanup_details(self, row: dict) -> None:
        """Show selectable, scrollable guidance without changing the policy or identity."""
        payload = getattr(self, '_cleanup_payload_by_key', {}).get(row.get('action_key'), {})
        sections = cleanup_detail_sections(row, payload)
        popup = tk.Toplevel(self.winfo_toplevel())
        popup.title(f'Cleanup Details — {row.get("Type", "Cleanup")}')
        popup.transient(self.winfo_toplevel())
        popup.geometry('920x660')
        popup.minsize(600, 400)
        outer = ttk.Frame(popup, padding=12)
        outer.pack(fill='both', expand=True)
        text = ScrolledText(outer, wrap='word', font=('TkDefaultFont', 11), padx=12, pady=12)
        text.pack(fill='both', expand=True)
        text.tag_configure('heading', font=('TkDefaultFont', 12, 'bold'), spacing1=12, spacing3=8)
        text.tag_configure('body', spacing3=10)
        for heading, lines in sections:
            text.insert('end', heading + '\n', 'heading')
            for line in lines:
                text.insert('end', line + '\n', 'body')
        text.configure(state='disabled')
        ttk.Button(outer, text='Close', command=popup.destroy).pack(anchor='e', pady=(10, 0))

    def _on_focus_cleanup_row(self, row):  # noqa: C901
        """
        Handle the 'Focus' action from right-click menu on a cleanup row.
        Navigates to the relevant tab and focuses/searches as appropriate.
        """
        t = row.get('Type', '')
        name = row.get('Name', '')

        # Defensive fallback to message
        fallback_msg = f'Focus action is not fully implemented for this item.\n\nType: {t}\nName: {name}'

        # Policy statement cleanup types
        policy_types = ('Invalid Statement', 'Any-user Without Where', 'Overly Broad Statement')
        if t in policy_types:
            # Switch to main Policy Analysis tab, then Policy Statements subview if possible
            try:
                # Switch to main Policy Analysis tab (top-level, NOT this subnotebook!)
                self.app.notebook.select(tab_id=2)  # Policy Analysis tab
                logger.info(f'Switching to Policy Analysis tab for policy: {name}, type: {t}')
                # Enable checkboxes for output
                self.app.policies_tab.chk_show_dynamic.set(True)
                self.app.policies_tab.chk_show_service.set(True)
                # Set the filter for text
                self.app.policies_tab.text_filter_var.set(name)
                # Update the policy statements table to apply the filter and show results
                self.app.policies_tab.update_policy_output()

            except Exception as ex:
                tkinter.messagebox.showinfo('Policy Statement Detail', f'Could not focus Policy Analysis tab: {ex}')
            return

        # Unused group cleanup
        if t == 'Group w/ No Users':
            try:
                # Switch to main Groups tab at top level, not recommendations notebook
                self.app.notebook.select(tab_id=3)  # Groups tab
                # Set the filter in the Groups tab to the group name (which may require parsing if name includes path)
                group_name = name.split('/', 1)[-1] if '/' in name else name
                if hasattr(self.app, 'groups_tab') and hasattr(self.app.groups_tab, 'group_filter_var'):
                    self.app.groups_tab.group_filter_var.set(group_name)
                    if hasattr(self.app.groups_tab, 'update_output'):
                        self.app.groups_tab.update_output()
                else:
                    tkinter.messagebox.showinfo(
                        'Group Detail',
                        f"Switched to Groups tab but could not set filter for '{group_name}'. Please search manually.",
                    )

            except Exception as ex:
                tkinter.messagebox.showinfo('Group Detail', f'Could not focus Group tab: {ex}')
            return

        # Unused dynamic group
        if t == 'Unused Dynamic Group':
            try:
                dg_tab = self.app.dynamic_groups_tab
                self.app.notebook.select(tab_id=dg_tab)
                domain, group_name = name.split('/', 1) if '/' in name else ('Default', name)
                # Clear previous filters so the selected group remains visible,
                # including when an old cleanup row is no longer unused.
                dg_tab.chk_show_instance_principals.set(False)
                dg_tab.chk_show_not_in_use.set(False)
                dg_tab.dg_rule_var.set('')
                dg_tab.dg_ocid_var.set('')
                dg_tab.domain_filter_var.set(domain)
                dg_tab.dg_name_var.set(group_name)
                dg_tab._update_dg_output()
            except Exception as ex:
                tkinter.messagebox.showinfo('Dynamic Group Detail', f'Could not focus Dynamic Groups: {ex}')
            return

        # Fallback: notify user
        tkinter.messagebox.showinfo('Detail', fallback_msg)

    # --- Cleanup In Progress Tab ---
    def _build_recommendation_workbench_tab(self, parent):
        """Build Cleanup In Progress: tracked actions, instructions, and reload history."""
        lbl = ttk.Label(
            parent,
            text='Items added from Cleanup/Fix and Superseded appear here. Make the change in OCI, then use Reload All to refresh IAM and policies and rerun intelligence. Findings that no longer appear are marked Resolved and retained here for review.',
            wraplength=900,
            justify='left',
        )
        lbl.pack(fill='x', padx=12, pady=(12, 5))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill='x', padx=12, pady=(0, 4))
        clear_btn = ttk.Button(btn_row, text='Clear', command=self._on_workbench_clear)
        clear_btn.pack(side='left', padx=(0, 8))
        self.add_context_help(
            clear_btn,
            'Clear tracked cleanup items and their history, including resolved items. This does not change OCI resources.',
        )
        self.reload_all_btn = ttk.Button(btn_row, text='Reload All', command=self._on_reload_all)
        self.reload_all_btn.pack(side='left', padx=(0, 8))
        self.add_context_help(
            self.reload_all_btn,
            'Refresh IAM, compartments, and policies using the last successful live load settings, then rerun intelligence. Available only for live tenancy data.',
        )
        self._update_reload_all_button_state()

        workbench_columns = ['#', 'Source', 'Type', 'Description', 'Status', 'History']
        workbench_display_columns = ['#', 'Source', 'Type', 'Description', 'Status', 'History']
        self.workbench_table = DataTable(
            parent,
            columns=workbench_columns + ['wb_id', 'cli_command', 'rollback_command', 'ui_instructions'],
            display_columns=workbench_display_columns,
            data=[],
            sortable=False,
            column_widths={
                '#': 40,
                'Source': 100,
                'Type': 160,
                'Description': 380,
                'Status': 80,
                'History': 200,
            },
            selection_callback=self._on_workbench_row_selected,
        )
        self.workbench_table.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        self.add_context_help(
            self.workbench_table,
            'One-off actions from Take Action. Select a row to view CLI/UI and rollback in the script area below.',
        )

        script_frame = ttk.LabelFrame(parent, text='OCI CLI / UI instructions')
        script_frame.pack(fill='both', expand=True, padx=12, pady=(2, 8))
        format_row = ttk.Frame(script_frame)
        format_row.pack(fill='x', padx=(6, 6), pady=(4, 2))
        ttk.Label(format_row, text='Show:').pack(side='left', padx=(0, 4))
        self.workbench_script_section_var = tk.StringVar(value='Execution')
        workbench_section_combo = ttk.Combobox(
            format_row,
            textvariable=self.workbench_script_section_var,
            state='readonly',
            values=['Execution', 'Rollback', 'Both'],
            width=12,
        )
        workbench_section_combo.pack(side='left', padx=(0, 8))
        workbench_section_combo.bind('<<ComboboxSelected>>', lambda e: self._refresh_workbench_script())
        self.workbench_script_text = tk.Text(script_frame, height=10, width=100, wrap='word', state='disabled')
        self.workbench_script_text.pack(fill='both', expand=True, padx=(6, 6), pady=(2, 6))

        audit_frame = ttk.LabelFrame(parent, text='History / Audit (per action)')
        audit_frame.pack(fill='x', padx=12, pady=(2, 12))
        self.workbench_audit_text = tk.Text(
            audit_frame, height=4, wrap='word', state='disabled', font=('TkDefaultFont', 9)
        )
        self.workbench_audit_text.pack(fill='both', expand=True, padx=4, pady=4)
        self.add_context_help(
            audit_frame,
            'Records when the item was added and whether each successful live reload found it open or resolved.',
        )

    def _on_workbench_clear(self):
        """Clear all tracked items and refresh the table and instructions."""
        self._workbench_actions = []
        self._workbench_counter = 0
        self._save_cleanup_progress()
        self._refresh_workbench_table()
        self._refresh_workbench_script(selected_rows=[])
        if hasattr(self, 'workbench_audit_text'):
            self.workbench_audit_text.config(state='normal')
            self.workbench_audit_text.delete('1.0', tk.END)
            self.workbench_audit_text.config(state='disabled')
        logger.debug('Cleanup In Progress cleared.')

    def _on_workbench_row_selected(self, selected_rows):
        """Update script and audit areas when a workbench row is selected."""
        self._refresh_workbench_script(selected_rows)
        if selected_rows:
            row = selected_rows[0]
            history = row.get('History', '') or ''
            self.workbench_audit_text.config(state='normal')
            self.workbench_audit_text.delete('1.0', tk.END)
            self.workbench_audit_text.insert('1.0', history or '—')
            self.workbench_audit_text.config(state='disabled')
        else:
            self.workbench_audit_text.config(state='normal')
            self.workbench_audit_text.delete('1.0', tk.END)
            self.workbench_audit_text.config(state='disabled')

    def _refresh_workbench_script(self, selected_rows=None):
        """Refresh the workbench script text from the selected row or first row."""
        if selected_rows is None and hasattr(self, 'workbench_table') and self.workbench_table.data:
            selected_rows = [self.workbench_table.data[0]] if self.workbench_table.data else []
        section = getattr(self, 'workbench_script_section_var', None)
        section_val = section.get() if section else 'Execution'
        parts = []
        if selected_rows:
            row = selected_rows[0]
            cli = (row.get('cli_command') or '').strip()
            rollback = (row.get('rollback_command') or '').strip()
            ui = (row.get('ui_instructions') or '').strip()
            if section_val == 'Execution':
                if cli:
                    parts.append('# OCI CLI\n' + cli)
                if ui:
                    parts.append('\n# UI steps\n' + ui)
            elif section_val == 'Rollback':
                if rollback:
                    parts.append(rollback)
            else:
                if cli or ui:
                    parts.append('# Execution\n' + (cli or '') + ('\n' + ui if ui else ''))
                if rollback:
                    parts.append('\n# Rollback\n' + rollback)
        self.workbench_script_text.config(state='normal')
        self.workbench_script_text.delete('1.0', tk.END)
        self.workbench_script_text.insert('1.0', '\n'.join(parts) if parts else 'Select an action above.')
        self.workbench_script_text.config(state='disabled')

    def _add_workbench_actions(self, actions):
        """Append one or more workbench action dicts and refresh the workbench table; switch to workbench tab."""
        self._activate_cleanup_tenancy()
        for a in actions:
            if a.get('finding_identity') and any(
                tuple(existing.get('finding_identity') or ()) == tuple(a['finding_identity'])
                and existing.get('Status') == 'Open'
                for existing in self._workbench_actions
            ):
                continue
            self._workbench_counter += 1
            a['#'] = self._workbench_counter
            a.setdefault('Status', 'Open')
            a.setdefault('History', '')
            if 'created_ts' not in a:
                from datetime import datetime

                a['created_ts'] = datetime.now(UTC).isoformat()  # noqa: ISC001
            if 'History' not in a or not a['History']:
                a['History'] = f'Added {a.get("created_ts", "")[:19]}'
            a['wb_id'] = f'wb-{self._workbench_counter}'
            self._workbench_actions.append(a)
        self._save_cleanup_progress()
        self._refresh_workbench_table()
        self.notebook.select(self.workbench_frame)

    def _refresh_workbench_table(self):
        """Refresh the workbench table from self._workbench_actions."""
        display_cols = ['#', 'Source', 'Type', 'Description', 'Status', 'History']
        all_cols = display_cols + ['wb_id', 'cli_command', 'rollback_command', 'ui_instructions']
        rows = []
        for a in self._workbench_actions:
            row = {k: a.get(k, '') for k in all_cols}
            rows.append(row)
        if hasattr(self, 'workbench_table'):
            self.workbench_table.update_data(rows)

    def _reconcile_cleanup_progress(self):
        """Compare tracked items with fresh findings, including ignored items."""
        current_rows = self._get_cleanup_issues(include_ignored=True)
        current = {
            cleanup_finding_identity(row, self._cleanup_payload_by_key.get(row.get('action_key'), {}))
            for row in current_rows
        }
        repo = self.app.policy_compartment_analysis
        current.update(
            current_supersession_identities(
                getattr(getattr(self.app, 'policy_intelligence', None), 'overlay', {}),
                getattr(repo, 'regular_statements', []) or [],
            )
        )
        self._workbench_actions = reconcile_cleanup_actions(
            self._workbench_actions,
            repo.tenancy_ocid,
            current,
            enabled=self.app.settings.get('enabled_intelligence_checks'),
            users_loaded=getattr(repo, 'load_all_users', True),
        )
        self._save_cleanup_progress()
        self._refresh_workbench_table()
        self._refresh_workbench_script(selected_rows=[])
        self._on_workbench_row_selected([])

    def _activate_cleanup_tenancy(self):
        """Drop old tenancy UI state and restore only the active tenancy's saved progress."""
        tenancy = getattr(self.app.policy_compartment_analysis, 'tenancy_ocid', None)
        if tenancy == getattr(self, '_cleanup_tenancy_ocid', None):
            return
        self._cleanup_tenancy_ocid = tenancy
        self._workbench_actions = []
        self._workbench_counter = 0
        self._cleanup_payload_by_key = {}
        self.ignored_cleanup_keys = set()
        if tenancy:
            try:
                self._workbench_actions = self.app.caching.load_cleanup_progress(tenancy)
                self._workbench_counter = max((int(a.get('#', 0)) for a in self._workbench_actions), default=0)
            except Exception as exc:
                logger.warning('Could not restore cleanup progress: %s', exc)
                tkinter.messagebox.showwarning('Cleanup Progress', f'Could not restore saved cleanup progress: {exc}')
        self._refresh_workbench_table()
        self._on_workbench_row_selected([])

    def _save_cleanup_progress(self):
        tenancy = getattr(self, '_cleanup_tenancy_ocid', None)
        if not tenancy:
            return
        try:
            self.app.caching.save_cleanup_progress(tenancy, self._workbench_actions)
        except Exception as exc:
            logger.warning('Could not save cleanup progress: %s', exc)
            tkinter.messagebox.showwarning(
                'Cleanup Progress', f'Progress is available in this session but could not be saved: {exc}'
            )

    def _build_cleanup_fix_workbench_actions(self, selected_rows):
        """Build workbench action dicts from selected cleanup table rows (with action_key and _cleanup_payload_by_key)."""
        actions = []
        payloads = getattr(self, '_cleanup_payload_by_key', {})
        for row in selected_rows:
            action_key = row.get('action_key')
            if not action_key:
                continue
            payload = payloads.get(action_key)
            if not payload:
                continue
            cleanup_type = payload.get('cleanup_type', '')
            issue_type = row.get('Type', '')
            desc = (row.get('Name') or '')[:120]
            if payload.get('policy_name'):
                desc = f'{payload.get("policy_name", "")}: {desc}'
            cli = ''
            rollback = ''
            ui = ''

            if cleanup_type == 'invalid_statement':
                po = payload.get('policy_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Policies > find policy (OCID: {po}). Edit or fix the invalid statement.'
                cli = f'# Get current policy and edit statements, then update:\noci iam policy get --policy-id {po}'
                rollback = (
                    f"Re-add the statement via Console or: oci iam policy update --policy-id {po} --statements '[...]'"
                )
            elif cleanup_type == 'unused_group':
                go = payload.get('group_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Groups (or Identity Domains) > find group (OCID: {go}) and delete or assign users.'
                cli = f'# Delete unused group (Identity Domains): use Console or API; OCID: {go}'
                rollback = 'Re-create the group in Console if needed.'
            elif cleanup_type == 'unused_dynamic_group':
                do = payload.get('dynamic_group_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Dynamic Groups > find (OCID: {do}) and delete.'
                cli = f'# Delete dynamic group via Console; OCID: {do}'
                rollback = 'Re-create the dynamic group in Console if needed.'
            elif cleanup_type in ('statement_too_open', 'anyuser_no_where'):
                po = payload.get('policy_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Policies > find policy (OCID: {po}). Edit statement to restrict scope or add WHERE clause.'
                cli = f'# Get policy and edit statement, then update:\noci iam policy get --policy-id {po}'
                rollback = (
                    f"Revert the statement via Console or: oci iam policy update --policy-id {po} --statements '[...]'"
                )

            actions.append(
                {
                    'Source': 'Cleanup/Fix',
                    'finding_identity': cleanup_finding_identity(row, payload),
                    'tenancy_ocid': self.app.policy_compartment_analysis.tenancy_ocid,
                    'Type': issue_type,
                    'Description': desc,
                    'cli_command': cli,
                    'rollback_command': rollback,
                    'ui_instructions': ui,
                }
            )
        return actions

    def _build_cleanup_delete_workbench_actions(self, selected_rows):
        """Build workbench action dicts from selected cleanup table rows (with action_key and _cleanup_payload_by_key)."""
        actions = []
        payloads = getattr(self, '_cleanup_payload_by_key', {})
        for row in selected_rows:
            action_key = row.get('action_key')
            if not action_key:
                continue
            payload = payloads.get(action_key)
            if not payload:
                continue
            cleanup_type = payload.get('cleanup_type', '')
            issue_type = row.get('Type', '')
            desc = (row.get('Name') or '')[:120]
            if payload.get('policy_name'):
                desc = f'{payload.get("policy_name", "")}: {desc}'
            cli = ''
            rollback = ''
            ui = ''

            if cleanup_type == 'invalid_statement':
                po = payload.get('policy_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Policies > find policy (OCID: {po}). Remove the invalid statement. If the policy only has the invalid statement, delete the entire policy.'
                cli = f'# Get current policy and remove statements, then update:\noci iam policy get --policy-id {po}\n# If the policy only has the invalid statement, delete the entire policy:\noci iam policy delete --policy-id {po}'
                rollback = (
                    f"Re-add the statement via Console or: oci iam policy update --policy-id {po} --statements '[...]'"
                )
            elif cleanup_type == 'unused_group':
                go = payload.get('group_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Groups (or Identity Domains) > find group (OCID: {go}) and delete or assign users.'
                cli = f'# Delete unused group (Identity Domains): use Console or API; OCID: {go}'
                rollback = 'Re-create the group in Console if needed.'
            elif cleanup_type == 'unused_dynamic_group':
                do = payload.get('dynamic_group_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Dynamic Groups > find (OCID: {do}) and delete.'
                cli = f'# Delete dynamic group via Console; OCID: {do}'
                rollback = 'Re-create the dynamic group in Console if needed.'
            elif cleanup_type in ('statement_too_open', 'anyuser_no_where'):
                po = payload.get('policy_ocid') or ''
                ui = f'In OCI Console: Identity & Security > Policies > find policy (OCID: {po}). Edit statement to restrict scope or add WHERE clause.'
                cli = f'# Get policy and edit statement, then update:\noci iam policy get --policy-id {po}'
                rollback = (
                    f"Revert the statement via Console or: oci iam policy update --policy-id {po} --statements '[...]'"
                )

            actions.append(
                {
                    'Source': 'Cleanup/Fix',
                    'finding_identity': cleanup_finding_identity(row, payload),
                    'tenancy_ocid': self.app.policy_compartment_analysis.tenancy_ocid,
                    'Type': issue_type,
                    'Description': desc,
                    'cli_command': cli,
                    'rollback_command': rollback,
                    'ui_instructions': ui,
                }
            )
        return actions

    def update_cleanup_tab_output(self):
        """Refresh the cleanup tab's data after analytics reload."""
        issues = self._get_cleanup_issues()
        if hasattr(self, 'cleanup_table'):
            self.cleanup_table.update_data(issues)

    def _get_cleanup_issues(self, include_ignored: bool = False):
        """
        Returns a list of dicts for issues: type, name/statement, reason, action, action_key.
        Populates self._cleanup_payload_by_key for Take Action CLI/rollback generation.
        When include_ignored is True, returned list includes items that are currently ignored.
        """
        intelligence = getattr(self.app, 'policy_intelligence', None)
        overlay = getattr(intelligence, 'overlay', {}) if intelligence else {}
        cleanup = overlay.get('cleanup_items', {})
        issues = []
        self._cleanup_payload_by_key = {}

        # Invalid statements
        for item in cleanup.get('invalid_statements', []):
            internal_id = item.get('internal_id') or ''
            action_key = f'invalid|{internal_id}' if internal_id else f'invalid|{len(issues)}'
            name = (item.get('statement_text') or '[unknown statement]')[:200]
            issues.append(
                {
                    'Type': 'Invalid Statement',
                    'Name': name,
                    'Reason': '; '.join(item.get('invalid_reasons', [])) or 'Failed validation',
                    'Action': 'Fix invalid statement or resolve identity/reference issues.',
                    'action_key': action_key,
                }
            )
            self._cleanup_payload_by_key[action_key] = {
                'cleanup_type': 'invalid_statement',
                'internal_id': internal_id,
                'policy_ocid': item.get('policy_ocid'),
                'policy_name': item.get('policy_name'),
                'statement_text': item.get('statement_text'),
            }

        # Unused groups
        for group in cleanup.get('unused_groups', []):
            group_ocid = group.get('group_ocid') or ''
            action_key = f'group|{group_ocid}' if group_ocid else f'group|{len(issues)}'
            group_name = f'{group.get("domain_name", "Default")}/{group.get("group_name", "[unknown]")}'
            issues.append(
                {
                    'Type': 'Group w/ No Users',
                    'Name': group_name,
                    'Reason': 'Group has zero user members.',
                    'Action': 'Remove, repurpose, or assign users.',
                    'action_key': action_key,
                }
            )
            self._cleanup_payload_by_key[action_key] = {
                'cleanup_type': 'unused_group',
                'group_ocid': group_ocid,
                'domain_name': group.get('domain_name'),
                'group_name': group.get('group_name'),
            }

        # Unused dynamic groups
        for dg in cleanup.get('unused_dynamic_groups', []):
            dg_ocid = dg.get('dynamic_group_ocid') or ''
            action_key = f'dg|{dg_ocid}' if dg_ocid else f'dg|{len(issues)}'
            dg_name = f'{dg.get("domain_name", "Default")}/{dg.get("dynamic_group_name", "[unknown]")}'
            issues.append(
                {
                    'Type': 'Unused Dynamic Group',
                    'Name': dg_name,
                    'Reason': 'Not referenced by any policy statement.',
                    'Action': 'Delete dynamic group or document why kept.',
                    'action_key': action_key,
                }
            )
            self._cleanup_payload_by_key[action_key] = {
                'cleanup_type': 'unused_dynamic_group',
                'dynamic_group_ocid': dg_ocid,
                'domain_name': dg.get('domain_name'),
                'dynamic_group_name': dg.get('dynamic_group_name'),
            }

        # Over-broad manage all-resources
        for st in cleanup.get('statements_too_open', []):
            internal_id = st.get('internal_id') or ''
            action_key = f'too_open|{internal_id}' if internal_id else f'too_open|{len(issues)}'
            name = (st.get('statement_text') or '[unknown statement]')[:200]
            issues.append(
                {
                    'Type': 'Overly Broad Statement',
                    'Name': name,
                    **overly_broad_statement_guidance(st),
                    'action_key': action_key,
                }
            )
            self._cleanup_payload_by_key[action_key] = {
                'cleanup_type': 'statement_too_open',
                'internal_id': internal_id,
                'policy_ocid': st.get('policy_ocid'),
                'policy_name': st.get('policy_name'),
                'statement_text': st.get('statement_text'),
            }

        # Any-user without where clause
        for st in cleanup.get('anyuser_no_where', []):
            internal_id = st.get('internal_id') or ''
            action_key = f'anyuser|{internal_id}' if internal_id else f'anyuser|{len(issues)}'
            name = (st.get('statement_text') or '[unknown statement]')[:200]
            issues.append(
                {
                    'Type': 'Any-user Without Where',
                    'Name': name,
                    'Reason': 'Statement grants access to any-user with no where clause.',
                    'Action': 'Limit subject with a concise where clause.',
                    'action_key': action_key,
                }
            )
            self._cleanup_payload_by_key[action_key] = {
                'cleanup_type': 'anyuser_no_where',
                'internal_id': internal_id,
                'policy_ocid': st.get('policy_ocid'),
                'policy_name': st.get('policy_name'),
                'statement_text': st.get('statement_text'),
            }

        # Exclude ignored items (persisted per tenancy) unless include_ignored=True
        if not include_ignored:
            ignored = getattr(self, 'ignored_cleanup_keys', set())
            issues = [i for i in issues if i.get('action_key') not in ignored]
        return issues

    def apply_settings(self, context_help: bool, font_size: str):
        """Apply context help and font size settings for the recommendations tab."""
        super().apply_settings(context_help, font_size)

    # NOTE: _get_recommendation_summary is defined earlier in this class with
    # limits-aware aggregation behavior and is intentionally the single source
    # of truth for summary rows.
