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

import tkinter as tk
import tkinter.messagebox
from datetime import UTC
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_policy
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.usage_tracking import get_usage_tracker
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import CheckboxTable, DataTable

# Note: CheckboxTable now supports a `column_widths` dict argument (pixel widths only).

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

# Policy Consolidation Table Layout
POLICY_CONSOLIDATION_COLUMNS = [
    'Statement',
    'Policy Name(s)',
    'Compartment',
    'Principal',
    'Service/Resource',
    'Consolidation Reason',
    'Action',
]
POLICY_CONSOLIDATION_COLUMN_WIDTHS = {
    'Statement': 350,
    'Policy Name(s)': 180,
    'Compartment': 180,
    'Principal': 180,
    'Service/Resource': 160,
    'Consolidation Reason': 280,
    'Action': 180,
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
        self.reload_all_btn = ttk.Button(button_frame, text='Reload All', command=self._on_reload_all)
        self.reload_all_btn.pack(side='left', padx=8)
        self.add_context_help(
            self.reload_all_btn,
            'Reload policies from OCI and re-run policy intelligence. Enabled only when data was loaded from tenancy (not cache/compliance).',
        )

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

        # === Overlap Analysis Tab ===
        overlap_frame = ttk.Frame(self.notebook)
        overlap_frame.pack(fill='both', expand=True)
        self.add_context_help(overlap_frame, 'Analyze statement overlap, potential policy overrides, and conflicts.')
        self._build_overlap_tab(overlap_frame)
        self.notebook.add(overlap_frame, text='Overlap Analysis')

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

        # === Recommendation Workbench Tab ===
        self._workbench_actions = []
        self._workbench_counter = 0
        self._cleanup_payload_by_key = {}
        # Ignored cleanup item action_keys (persisted per tenancy in consolidation state)
        self.ignored_cleanup_keys = set()
        self.workbench_frame = ttk.Frame(self.notebook)
        self.workbench_frame.pack(fill='both', expand=True)
        self.add_context_help(
            self.workbench_frame,
            'One-off actions from Take Action buttons (Cleanup/Fix, etc.). Review CLI/UI instructions and rollback; reload policies to see resolved items disappear.',
        )
        self._build_recommendation_workbench_tab(self.workbench_frame)
        self.notebook.add(self.workbench_frame, text='Recommendation Workbench')

    def populate_data(self):
        """
        Called after policy analysis/intelligence is refreshed. Reload all analytics/tables, using timing.
        Also launches OCI tenancy limits fetch (policies-count, statements-count).
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
                txt = 'Tenancy Limits: n/a'
            else:
                limits = self.app.policy_compartment_analysis.fetch_tenancy_policy_statement_limits()
                pol_limit, stmt_limit = limits if limits else (None, None)
                txt = 'Tenancy Limits: '
                txt_parts = []
                txt_parts.append(f"{pol_limit if pol_limit is not None else 'n/a'} policies / tenancy")
                txt_parts.append(f"{stmt_limit if stmt_limit is not None else 'n/a'} statements / policy")
                txt += ', '.join(txt_parts)
            # Always append the hard OCI statements/compartment limit label
            txt = f'{txt} | Statements / Compartment: {self.STATEMENTS_PER_COMPARTMENT_LIMIT}'
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

        # Tenancy Limit Label - now inline, smaller font and lighter weight
        label_initial = (
            'Tenancy Limits: n/a (Not available from cache/compliance load)'
            if not can_check_limits
            else 'Tenancy policy statement limit: [not fetched]'
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
            self.tenancy_limit_label,
            'Tenancy limits shown as "n/a" if unavailable because data was loaded from cache or compliance output. The statements / compartment limits is always 500, as this is a hard limit from OCI. See the link to Docs on the Limits tab.',
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
                tk.messagebox.showinfo('Documentation', f'Learn more: {doc_url}')

        doc_link.bind('<Button-1>', open_doc_link)
        self.add_context_help(
            doc_link, 'Open Oracle documentation on OCI policy compartment hierarchy statement limits.'
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
        LIMIT = 500
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
            if cumulative > LIMIT:
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

    # Button callback to fetch tenancy policy/statement limits and update label
    def fetch_tenancy_policy_statement_limits(self):
        import threading

        def update_label():
            repo = self.app.policy_compartment_analysis
            if not (hasattr(repo, 'limits_client') and repo.limits_client):
                txt = 'Tenancy Limits: n/a'
            else:
                limits = repo.fetch_tenancy_policy_statement_limits()
                pol_limit, stmt_limit = limits if limits else (None, None)
                txt = 'Tenancy Limits: '
                txt_parts = []
                txt_parts.append(f"{pol_limit if pol_limit is not None else 'n/a'} policies / tenancy")
                txt_parts.append(f"{stmt_limit if stmt_limit is not None else 'n/a'} statements / policy")
                txt += ', '.join(txt_parts)
            # Always append the hard OCI statements/compartment limit label
            txt = f'{txt} | Statements / Compartment: {self.STATEMENTS_PER_COMPARTMENT_LIMIT}'
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
                'Priority': 'HIGH' if has_over else 'WARN',
                'Category': 'Limits',
                'Notes': (
                    f'At least one compartment is {first_status} for the OCI 500 policy statement-per-compartment limit. '
                    'Review the Limits tab below for details and mitigation steps.'
                ),
                'Action': 'Use the Limits tab to review and reduce/consolidate compartment statements as needed.',
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
            # Remove duplicate slashes and trim
            return f"{comp_path.strip('/')}/{name}".replace('//', '/')
        if policy_ocid:
            pol = None
            for p in self.policy_repo.policies:
                if p.get('policy_ocid') == policy_ocid:
                    pol = p
                    break
            if pol:
                comp_path = pol.get('compartment_path') or ''
                name = pol.get('policy_name') or ''
                return f"{comp_path.strip('/')}/{name}".replace('//', '/')
        return '[Unknown Policy Path]'

    def _build_statement_risk_tab(self, parent):
        # Filter Controls - now inside risk tab only
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.add_context_help(
            filter_frame,
            'Tune risk scoring: WHERE clause and Service Principal reduction percentages, and relative risk threshold filter.',
        )

        ttk.Label(filter_frame, text='WHERE clause risk reduction:').pack(side='left', padx=(0, 2))
        self.where_reduction_pct_var = tk.StringVar(value='50%')
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
        self.service_reduction_pct_var = tk.StringVar(value='50%')
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

        # Table
        def on_row_select(selected_rows: list[dict]) -> None:
            if selected_rows:
                row = selected_rows[0]
                self.risk_detail_tree.delete(*self.risk_detail_tree.get_children())
                notes = row.get('Risk Notes') or ''
                rel_risk = row.get('Relative Risk')
                score = row.get('Score')
                self.risk_detail_tree.insert('', 'end', text=f'Raw Score: {score}, Relative Risk: {rel_risk}')
                if notes:
                    self.risk_detail_tree.insert('', 'end', text=f'Details: {notes}')
                recommendations = row.get('Recommendations')
                if recommendations:
                    if isinstance(recommendations, list):
                        for rec in recommendations:
                            self.risk_detail_tree.insert('', 'end', text=f'Recommendation: {rec}')
                    else:
                        self.risk_detail_tree.insert('', 'end', text=f'Recommendations: {recommendations}')

        def risk_table_context_menu_callback(row_index):
            row = self.risk_table.data[row_index]
            menu = tk.Menu(self.risk_table, tearoff=0)
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
            selection_callback=on_row_select,
            row_context_menu_callback=risk_table_context_menu_callback,
            multi_select=True,
            initial_sort_column='Relative Risk',
            initial_sort_descending=True,
        )
        self.risk_table.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        self.add_context_help(self.risk_table, 'Full list of policy statements, with risk and mitigation guidance.')

        # Lower tree/frame for risk detail
        risk_detail_frame = ttk.LabelFrame(parent, text='Risk Statement Details & Recommendations')
        risk_detail_frame.pack(fill='x', padx=10, pady=(0, 10))
        risk_detail_frame.grid_rowconfigure(0, weight=1)
        risk_detail_frame.grid_columnconfigure(0, weight=1)
        self.add_context_help(
            risk_detail_frame, 'More granular details and action items for the selected risky statement.'
        )

        self.risk_detail_tree = ttk.Treeview(
            risk_detail_frame,
            show='tree',
            height=8,
        )
        self.risk_detail_tree.heading('#0', text='Detail')
        self.risk_detail_tree.column('#0', width=1200, stretch=True)
        scrollbar = ttk.Scrollbar(risk_detail_frame, orient='vertical', command=self.risk_detail_tree.yview)
        self.risk_detail_tree.configure(yscrollcommand=scrollbar.set)
        self.risk_detail_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.add_context_help(self.risk_detail_tree, 'Expanded statement details, scoring notes, recommendations.')

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

        self.where_reduction_pct_var_policy = tk.StringVar(value='50%')
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
        self.service_reduction_pct_var_policy = tk.StringVar(value='50%')
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

        # UI: policy risk table & detail
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill='both', expand=True)

        def on_row_select_policy(selected_rows):  # noqa: C901
            self.policy_risk_detail_tree.delete(*self.policy_risk_detail_tree.get_children())
            if selected_rows:
                row = selected_rows[0]
                policy_path = row.get('Policy Path')
                # Find policy_ocid for selected Policy Path
                policy_obj = None
                for p in self.policy_repo.policies:
                    path = self._get_policy_path(policy_obj=p)
                    if path == policy_path:
                        policy_obj = p
                        break
                if not policy_obj:
                    return
                pocid = policy_obj.get('policy_ocid')
                statements = [
                    st
                    for st in self.policy_repo.regular_statements
                    if st.get('policy_ocid') == pocid and st.get('action', '').lower() == 'allow'
                ]
                risk_scores = self.app.policy_intelligence.overlay.get('risk_scores', [])
                risk_by_id = {entry.get('statement_internal_id'): entry for entry in risk_scores}
                for st in statements:
                    internal_id = st.get('internal_id')
                    risk_entry = risk_by_id.get(internal_id) or {}
                    score = risk_entry.get('score', 0)
                    notes = risk_entry.get('notes', '')
                    recs = risk_entry.get('recommendations')
                    rel_risk = None
                    # Rel risk for this statement, as on statement tab
                    try:
                        all_scores = [risk_by_id.get(bb.get('internal_id'), {}).get('score', 0) for bb in statements]
                        import math

                        mx = max(all_scores) if all_scores else 1
                        if score == 0:
                            rel_risk = 1
                        elif mx > 1:
                            rel_risk = int((math.log(score) / math.log(mx)) * 100)
                            if rel_risk < 1:
                                rel_risk = 1
                        else:
                            rel_risk = 1
                    except Exception:
                        rel_risk = 1
                    text_main = f'Score: {score}  (Relative: {rel_risk})'
                    self.policy_risk_detail_tree.insert('', 'end', text=text_main)
                    txt = st.get('statement_text', '---')
                    self.policy_risk_detail_tree.insert('', 'end', text=f'Statement: {txt[:100]}')
                    if notes:
                        self.policy_risk_detail_tree.insert('', 'end', text=f'Risk Notes: {notes}')
                    if recs:
                        if isinstance(recs, list):
                            for rec in recs:
                                self.policy_risk_detail_tree.insert('', 'end', text=f'Rec: {rec}')
                        else:
                            self.policy_risk_detail_tree.insert('', 'end', text=f'Rec: {recs}')
                    self.policy_risk_detail_tree.insert('', 'end', text='')  # spacer

        def policy_risk_context_menu_callback(row_index):
            row = self.policy_risk_table.data[row_index]
            policy_path = row.get('Policy Path', '')
            menu = tk.Menu(self.policy_risk_table, tearoff=0)
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
            selection_callback=on_row_select_policy,
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

        detail_frame = ttk.LabelFrame(parent, text='Policy Risk Details (Select row for breakdown)')
        detail_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.policy_risk_detail_tree = ttk.Treeview(
            detail_frame,
            show='tree',
            height=8,
        )
        self.policy_risk_detail_tree.heading('#0', text='Detail')
        self.policy_risk_detail_tree.column('#0', width=1200, stretch=True)
        scrollbar = ttk.Scrollbar(detail_frame, orient='vertical', command=self.policy_risk_detail_tree.yview)
        self.policy_risk_detail_tree.configure(yscrollcommand=scrollbar.set)
        self.policy_risk_detail_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.add_context_help(
            self.policy_risk_detail_tree, 'Expanded policy details and risk explanations, as available.'
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

        # Table
        def on_overlap_select(selected_rows: list[dict]) -> None:
            if selected_rows:
                row = selected_rows[0]
                self.overlap_detail_tree.delete(*self.overlap_detail_tree.get_children())
                internal_id = row.get('Internal ID', [])
                overlaps = self.app.policy_intelligence.get_policy_overlaps_by_internal_id(internal_id)
                for overlap in overlaps:
                    superseded_by = overlap.get('superseded_by', 'N/A')
                    confidence = overlap.get('confidence', 'N/A')
                    reason = overlap.get('reason', 'N/A')
                    statement_text = overlap.get('statement_text', 'N/A')
                    permission_overlap = overlap.get('permission_overlap', [])
                    parent = self.overlap_detail_tree.insert(
                        '',
                        'end',
                        open=True,
                        text=f"Statement overlaps with Policy '{superseded_by}'",
                    )
                    self.overlap_detail_tree.insert(
                        parent,
                        'end',
                        text=f'Policy Name: {superseded_by}',
                    )
                    self.overlap_detail_tree.insert(
                        parent,
                        'end',
                        text=f'Statement Text: {statement_text}',
                    )
                    perms_upper = [p.upper() for p in permission_overlap] if permission_overlap else []
                    self.overlap_detail_tree.insert(
                        parent,
                        'end',
                        text=f'Overlapping Permissions: {perms_upper}',
                    )
                    self.overlap_detail_tree.insert(
                        parent,
                        'end',
                        text=f'Confidence: {confidence}',
                    )
                    self.overlap_detail_tree.insert(
                        parent,
                        'end',
                        text=f'Reason: {reason}',
                    )
                    if overlap.get('additional_notes'):
                        notes = overlap.get('additional_notes')
                        self.overlap_detail_tree.insert(
                            parent,
                            'end',
                            text=f'Additional Notes: {notes}',
                        )

        self.overlap_table = DataTable(
            parent,
            columns=POLICY_OVERLAP_ALL_COLUMNS,
            display_columns=POLICY_OVERLAP_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_OVERLAP_COLUMN_WIDTHS,
            selection_callback=on_overlap_select,
            multi_select=True,
            highlights=[('Action', 'deny', '#FF0000')],
        )
        self.overlap_table.pack(fill='both', expand=True, padx=10, pady=(10, 0))
        self.add_context_help(self.overlap_table, 'See where custom policies may override or duplicate one another.')

        # Lower tree/frame for overlap detail
        overlap_detail_frame = ttk.LabelFrame(parent, text='Overlap Details')
        overlap_detail_frame.pack(fill='x', padx=10, pady=(0, 10))
        overlap_detail_frame.grid_rowconfigure(0, weight=1)
        overlap_detail_frame.grid_columnconfigure(0, weight=1)
        self.add_context_help(overlap_detail_frame, 'For a selected statement, see detailed overlap/override notes.')

        self.overlap_detail_tree = ttk.Treeview(
            overlap_detail_frame,
            show='tree',
            height=10,
        )
        self.overlap_detail_tree.heading('#0', text='Overlap Details')
        self.overlap_detail_tree.column('#0', width=1200, stretch=True)
        scrollbar = ttk.Scrollbar(overlap_detail_frame, orient='vertical', command=self.overlap_detail_tree.yview)
        self.overlap_detail_tree.configure(yscrollcommand=scrollbar.set)
        self.overlap_detail_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.add_context_help(self.overlap_detail_tree, 'Details of all overlapping/conflicting policy relationships.')

    # ==== Data/Logic Methods ====
    def _update_reload_all_button_state(self):
        """Enable Reload All only when data was loaded from tenancy (not cache/compliance)."""
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        can_reload = bool(repo and getattr(repo, 'policies_loaded_from_tenancy', False))
        if hasattr(self, 'reload_all_btn'):
            self.reload_all_btn['state'] = tk.NORMAL if can_reload else tk.DISABLED

    def _on_reload_all(self):
        """Reload policies from OCI (only enabled when loaded from tenancy), then re-run policy intelligence."""
        if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache'):
            ok = self.app.reload_policies_and_compartments_and_update_cache()
            if ok:
                logger.info('Reload All: policies and compartments reloaded; intelligence and UI updated.')
                return
        self.reload_all_analytics()

    def reload_all_analytics(self):
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
        self.update_overlap_tab_output()
        self.update_consolidation_tab_output()
        self.update_cleanup_tab_output()

        # Recommendation Summary at top
        recs = self._get_recommendation_summary()
        logger.info(f'Updating recommendation summary with {len(recs)} entries.')
        if recs and hasattr(logger, 'info'):
            logger.info(
                f"First recommendation keys: {list(recs[0].keys()) if isinstance(recs[0], dict) else 'Not a dict'}"
            )
        # Ensure all required columns are present for every row (prevent blank table w/ field mismatch)
        required_cols = ['Recommendation', 'Priority', 'Category', 'Notes', 'Action']
        normalized_recs = []
        for row in recs:
            norm = {col: row.get(col, '') for col in required_cols}
            normalized_recs.append(norm)
        self.recommendation_table.update_data(normalized_recs)

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

        from oci_policy_analysis.common.models import PolicySearch

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
        # Workbench area with instructions and button to open consolidation workbench (not implemented yet - manual process for now)
        workbench_frame = ttk.Frame(parent)
        workbench_frame.pack(fill='x', padx=10, pady=(8, 4))
        workbench_frame.columnconfigure(0, weight=1)
        workbench_frame.columnconfigure(1, weight=0)
        ttk.Label(
            workbench_frame,
            text='Consolidation suggestions show opportunities to streamline policy statements. To act on these suggestions, manage policies manually using the Policy Analysis and Browser tabs. Automated batch consolidation is not available in this version.',
            # wraplength=700,
            justify='left',
        ).grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.add_context_help(
            workbench_frame,
            'The table below lists detected consolidation opportunities; review and act on these in the main Policy Analysis and Browser tabs as desired.',
        )

        def on_take_action(selected):
            tkinter.messagebox.showinfo('Not Implemented', 'Policy consolidation actions are not implemented yet.')

        self.consolidation_table = CheckboxTable(
            parent,
            columns=POLICY_CONSOLIDATION_COLUMNS,
            data=[],
            column_widths=POLICY_CONSOLIDATION_COLUMN_WIDTHS,
            # action_buttons=[('Take Actions', on_take_action)],
            enable_select_all=True,
            checked_by_default=False,
        )
        self.consolidation_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(
            self.consolidation_table, 'Review consolidation candidates and organize statements as indicated.'
        )

    # REMOVED: _on_open_consolidation_workbench() (workbench not available)

    def update_consolidation_tab_output(self):
        """Refresh the consolidation tab's data after analytics reload."""
        consolidations = self._get_policy_consolidation_rows()
        logger.info(f'Updating consolidation tab with {len(consolidations)} records.')
        if hasattr(self, 'consolidation_table'):
            self.consolidation_table.update_data(consolidations)

    def _get_policy_consolidation_rows(self):
        """
        Normalize/present policy consolidation records for CheckboxTable row format.

        Always uses overlay['consolidations'].
        Ensures all columns exist, defaulting to '' if missing.
        """
        # do this more like _get_cleanup_issues
        intelligence = getattr(self.app, 'policy_intelligence', None)
        overlay = getattr(intelligence, 'overlay', {}) if intelligence else {}
        consolidations = overlay.get('consolidations', {})
        # consolidations = getattr(self.app.policy_intelligence.overlay, "consolidations", []) if hasattr(self.app.policy_intelligence, "overlay") else []

        normalized = []
        required_cols = POLICY_CONSOLIDATION_COLUMNS
        for row in consolidations:
            norm = {col: row.get(col, '') for col in required_cols}
            # Human-friendly blank for missing values
            for k, v in norm.items():
                if v is None:
                    norm[k] = ''
            normalized.append(norm)
        return normalized

    # --- Cleanup / Fix Tab ---
    def _load_ignored_cleanup_keys_from_state(self):
        """Load ignored_cleanup_keys from per-tenancy consolidation state. No-op if no tenancy_ocid."""
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        tenancy_ocid = getattr(repo, 'tenancy_ocid', None) if repo else None
        if not tenancy_ocid or str(tenancy_ocid).lower() in ('unknown', '', 'none'):
            return
        try:
            from oci_policy_analysis.common.caching import CacheManager

            state = CacheManager().get_or_create_consolidation_state(tenancy_ocid)
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
            from oci_policy_analysis.common.caching import CacheManager

            state = CacheManager().get_or_create_consolidation_state(tenancy_ocid)
            state['ignored_cleanup_keys'] = list(self.ignored_cleanup_keys)
            CacheManager().save_consolidation_state(tenancy_ocid, state)
        except Exception as e:
            logger.warning('Could not save ignored_cleanup_keys to state: %s', e)

    def _on_show_previously_ignored(self):
        """Open a dialog listing currently ignored cleanup items; user can re-show selected or all."""
        all_issues = self._get_cleanup_issues(include_ignored=True)
        ignored = getattr(self, 'ignored_cleanup_keys', set())
        ignored_list = [i for i in all_issues if i.get('action_key') in ignored]
        if not ignored_list:
            tkinter.messagebox.showinfo(
                'No ignored items',
                'There are no previously ignored cleanup items. Use "Ignore Selected" on the Cleanup tab to hide items.',
            )
            return

        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.title('Previously ignored cleanup items')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.geometry('720x380')

        ttk.Label(
            dialog,
            text='Select items to re-show in the Cleanup table (they will no longer be ignored).',
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
            self.update_cleanup_tab_output()
            dialog.destroy()

        def re_show_all():
            for k in key_by_iid.values():
                self.ignored_cleanup_keys.discard(k)
            self._save_ignored_cleanup_keys_to_state()
            self.update_cleanup_tab_output()
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

        def on_take_delete_action(selected):
            if not selected:
                tkinter.messagebox.showinfo('No selection', 'Select one or more cleanup items, then try again.')
                return
            actions = self._build_cleanup_delete_workbench_actions(selected)
            if actions:
                self._add_workbench_actions(actions)
            else:
                tkinter.messagebox.showinfo('No actions', 'Could not build actions for the selected items.')

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
            menu.add_command(label=label, command=lambda: self._on_focus_cleanup_row(row))
            return menu

        self.cleanup_table = CheckboxTable(
            parent,
            columns=self.cleanup_columns,
            data=self._get_cleanup_issues(),
            column_widths=cleanup_column_widths,
            display_columns=cleanup_display_columns,
            action_buttons=[
                ('Delete', on_take_delete_action),
                ('Attempt Fix', on_take_fix_action),
                ('Ignore Selected', on_ignore_selected),
            ],
            enable_select_all=True,
            checked_by_default=False,
            row_context_menu_callback=row_context_menu_callback,
        )
        # Make the table (and thus all internal widgets) expand to full width
        self.cleanup_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(self.cleanup_table, 'Select and resolve security hygiene issues for policies.')

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
                # Switch to main Dynamic Groups tab at top level, not recommendations notebook
                self.app.notebook.select(tab_id=4)  # Dynamic Groups tab
                # set the filter in the Dynamic Groups tab to the group name (which may require parsing if name includes path)
                group_name = name.split('/', 1)[-1] if '/' in name else name
                if hasattr(self.app, 'dynamic_groups_tab') and hasattr(self.app.dynamic_groups_tab, 'dg_filter_var'):
                    self.app.dynamic_groups_tab.dg_filter_var.set(group_name)
                    if hasattr(self.app.dynamic_groups_tab, 'update_output'):
                        self.app.dynamic_groups_tab.update_output()
                else:
                    tkinter.messagebox.showinfo(
                        'Dynamic Group Detail',
                        f"Switched to Dynamic Groups tab but could not set filter for '{group_name}'. Please search manually.",
                    )
            except Exception as ex:
                tkinter.messagebox.showinfo('Dynamic Group Detail', f'Could not focus Dynamic Groups: {ex}')
            return

        # Fallback: notify user
        tkinter.messagebox.showinfo('Detail', fallback_msg)

        # Anchor Delete button to always be visible at the bottom (also part of CheckboxTable, but double-sure)
        # This is handled by CheckboxTable, but if you have a custom action bar, you would add it here.

    # --- Recommendation Workbench Tab ---
    def _build_recommendation_workbench_tab(self, parent):
        """Build the Recommendation Workbench subtab: actions table, script area, history/audit placeholder."""
        lbl = ttk.Label(
            parent,
            text='Actions from "Take Action" buttons (e.g. Cleanup/Fix) appear here. Select a row to see OCI CLI or UI instructions; rollback is the opposite action. Use Reload All to refresh policies and re-run intelligence—fixed issues will disappear from source tabs.',
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
            'Remove all Open items from the workbench. Resolved items are not tracked; if an issue no longer appears in Cleanup/Fix after reload, it is effectively done.',
        )

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
            'Placeholder for per-action history (e.g. Added, Reload: still open / Resolved) and future OCI Audit data.',
        )

    def _on_workbench_clear(self):
        """Remove all Open items from the workbench and refresh the table and script/audit areas."""
        self._workbench_actions = []
        self._workbench_counter = 0
        self._refresh_workbench_table()
        self._refresh_workbench_script(selected_rows=[])
        if hasattr(self, 'workbench_audit_text'):
            self.workbench_audit_text.config(state='normal')
            self.workbench_audit_text.delete('1.0', tk.END)
            self.workbench_audit_text.config(state='disabled')
        logger.debug('Recommendation Workbench cleared.')

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
        for a in actions:
            self._workbench_counter += 1
            a['#'] = self._workbench_counter
            a.setdefault('Status', 'Open')
            a.setdefault('History', '')
            if 'created_ts' not in a:
                from datetime import datetime

                a['created_ts'] = datetime.now(UTC).isoformat()  # noqa: ISC001
            if 'History' not in a or not a['History']:
                a['History'] = f"Added {a.get('created_ts', '')[:19]}"
            a['wb_id'] = f'wb-{self._workbench_counter}'
            self._workbench_actions.append(a)
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
                desc = f"{payload.get('policy_name', '')}: {desc}"
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
                desc = f"{payload.get('policy_name', '')}: {desc}"
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
            group_name = f"{group.get('domain_name', 'Default')}/{group.get('group_name', '[unknown]')}"
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
            dg_name = f"{dg.get('domain_name', 'Default')}/{dg.get('dynamic_group_name', '[unknown]')}"
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
                    'Reason': "Grants 'manage all-resources' to principal outside root/admin.",
                    'Action': 'Restrict scope and replace with least privilege permissions.',
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

    # --- Recommendation Summary source (prototype/stub) ---
    def _get_recommendation_summary(self):
        """
        Returns list of dicts for populating the recommendation summary table.
        Uses overlay["recommendations"] from intelligence engine only.
        """
        # Always get from latest self.app.policy_intelligence
        # overlay_recs = getattr(self.app.policy_intelligence.overlay, "recommendations", []) if hasattr(self.app.policy_intelligence, "overlay") else []
        logger.info(
            f'Built recommendations list: {len(self.app.policy_intelligence.overlay.get("recommendations", []))} total.'
        )
        return self.app.policy_intelligence.overlay.get('recommendations', [])
