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
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_policy
from oci_policy_analysis.common.logger import get_logger
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

    This tab contains an internal notebook with subtabs for:
      - Risk assessment and scores for policy statements
      - Policy overlap analysis (potential overrides/superseding statements)
      - Consolidation opportunities
      - Policy hygiene and clean-up actions
      - Future analytics extensions

    Args:
        parent (tk.Widget): The parent widget for this frame.
        app (Any): The main application object containing state and analysis engines.

    Attributes:
        app (Any): The main application reference with policy and intelligence engines.
        policy_repo: Reference to analysis data for rendering UI.
        recommendation_table: DataTable widget for summary.
        notebook: ttk.Notebook for switching between analytics views.
        risk_table: DataTable for risk scores.
        overlap_table: DataTable for policy overlaps.
        consolidation_table: CheckboxTable for consolidation findings.
        cleanup_table: CheckboxTable for actionable cleanup/fix items.
    """

    def __init__(self, parent, app):
        logger.debug('Initializing unified PolicyRecommendationsTab (notebook prototype).')
        super().__init__(
            parent,
            default_help_text=(
                'Review policy recommendations and analytics: '
                'overall security hygiene, risk, policy overlap, consolidation, and fix suggestions. '
                'Switch tabs below for different analysis views. '
                'Use the summary table to quickly see top issues and recommendations.'
            ),
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
        reload_btn = ttk.Button(button_frame, text='Reload All', command=self.reload_all_analytics)
        reload_btn.pack(side='left', padx=8)
        self.add_context_help(reload_btn, 'Recompute and reload all analytics/recommendations live.')

        # ==== Begin Notebook Prototype ====
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.add_context_help(
            self.notebook, 'Switch between risk, overlap, consolidation, and fix tabs for deep-dive analytics.'
        )

        # === Risk Overview Tab ===
        risk_frame = ttk.Frame(self.notebook)
        risk_frame.pack(fill='both', expand=True)
        self.add_context_help(risk_frame, 'View risk scoring and assessment for all policy statements.')
        self._build_risk_tab(risk_frame)
        self.notebook.add(risk_frame, text='Risk Overview')

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

        # === Future Tab (stubbed/demo) ===
        future_frame = ttk.Frame(self.notebook)
        lbl = ttk.Label(future_frame, text='Future analytics or visualizations can go here...')
        lbl.pack(padx=30, pady=30)
        self.add_context_help(future_frame, 'Reserved for future or custom analytics dashboards.')
        self.notebook.add(future_frame, text='[Future/More]')

        logger.debug('Unified PolicyRecommendationsTab: initial analytics reload.')
        self.reload_all_analytics()

    # ==== Risk Tab Logic ====
    def _build_risk_tab(self, parent):
        # Filter Controls - now inside risk tab only
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.add_context_help(filter_frame, 'Tune risk scoring by WHERE clause impact or risk threshold.')

        ttk.Label(filter_frame, text='WHERE clause risk reduction:').pack(side='left', padx=(0, 2))
        self.where_reduction_pct_var = tk.StringVar(value='50%')
        self.where_reduction_options = ['0%', '25%', '50%', '75%']
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

        self.risk_table = DataTable(
            parent,
            columns=POLICY_RECOMMENDATIONS_ALL_COLUMNS,
            display_columns=POLICY_RECOMMENDATIONS_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_RECOMMENDATIONS_COLUMN_WIDTHS,
            selection_callback=on_row_select,
            multi_select=True,
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
    def reload_all_analytics(self):
        logger.info('Reloading all policy intelligence analytics for unified recommendations tab.')

        # Always recalculate all analytics: risk, overlap, consolidation, cleanup, recommendations
        pct_str = self.where_reduction_pct_var.get().replace('%', '')
        try:
            where_pct = int(pct_str)
        except Exception:
            where_pct = 50

        logger.info(f'Recalculating analytics with WHERE clause reduction pct: {where_pct}%')
        pi = self.app.policy_intelligence
        pi.calculate_potential_risk_scores(where_clause_reduction_pct=where_pct)
        pi.analyze_policy_overlap()
        pi.build_policy_consolidation()
        pi.build_cleanup_items()
        pi.build_overall_recommendations()

        # Now update all display tables
        self.update_risk_tab_output()
        self.update_overlap_tab_output()
        self.update_consolidation_tab_output()
        self.update_cleanup_tab_output()

        # Recommendation Summary at top
        recs = self._get_recommendation_summary()
        logger.info(f'Updating recommendation summary with {len(recs)} entries.')
        if recs and hasattr(logger, 'info'):
            logger.info(
                f"[DEBUG] First recommendation keys: {list(recs[0].keys()) if isinstance(recs[0], dict) else 'Not a dict'}"
            )
        # Ensure all required columns are present for every row (prevent blank table w/ field mismatch)
        required_cols = ['Recommendation', 'Priority', 'Category', 'Notes', 'Action']
        normalized_recs = []
        for row in recs:
            norm = {col: row.get(col, '') for col in required_cols}
            normalized_recs.append(norm)
        self.recommendation_table.update_data(normalized_recs)

    # ---- Risk Tab update logic ----
    def update_risk_tab_output(self):  # noqa: C901
        # (Direct port of previous update_recommendations_output)
        pct_str = self.where_reduction_pct_var.get().replace('%', '')
        try:
            where_pct = int(pct_str)
        except Exception:
            where_pct = 50
        self.app.policy_intelligence.calculate_potential_risk_scores(where_clause_reduction_pct=where_pct)

        statements = self.policy_repo.regular_statements
        risk_score_map = {}
        risk_scores = self.app.policy_intelligence.overlay.get('risk_scores', [])
        for entry in risk_scores:
            rid = entry.get('statement_internal_id')
            risk_score_map[rid] = (entry.get('score'), entry.get('notes'))

        import math

        data_to_display = []
        missing_risk_scores = 0
        scores_list = []
        for st in statements:
            if st.get('action', '').lower() != 'allow':
                continue
            pd = for_display_policy(st)
            internal_id = st.get('internal_id')
            score, notes = risk_score_map.get(internal_id, (None, ''))
            if score is None:
                missing_risk_scores += 1
                score = 0
            pd['Score'] = score
            pd['Risk Notes'] = notes
            risk_score_entry = next((x for x in risk_scores if x.get('statement_internal_id') == internal_id), {})
            recommendations = risk_score_entry.get('recommendations')
            if recommendations:
                pd['Recommendations'] = recommendations
            scores_list.append(score)
            data_to_display.append(pd)

        max_score = max(scores_list) if scores_list else 1
        for row in data_to_display:
            raw = row.get('Score') or 0
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

        def on_take_action(selected):
            tkinter.messagebox.showinfo('Not Implemented', 'Policy consolidation actions are not implemented yet.')

        self.consolidation_table = CheckboxTable(
            parent,
            columns=POLICY_CONSOLIDATION_COLUMNS,
            data=[],
            column_widths=POLICY_CONSOLIDATION_COLUMN_WIDTHS,
            action_button_text='Take Actions',
            action_callback=on_take_action,
            enable_select_all=True,
            checked_by_default=True,
        )
        self.consolidation_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(
            self.consolidation_table, 'Review consolidation candidates and organize statements as indicated.'
        )

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
    def _build_cleanup_tab(self, parent):
        """
        Build the Cleanup / Fix notebook sub-tab using CheckboxTable for issues/actions.
        Adds a vertical scrollbar and positions the Take Action button so it never scrolls out of view.
        """

        self.cleanup_columns = ['Type', 'Name', 'Reason', 'Action']
        cleanup_column_widths = {'Type': 150, 'Name': 330, 'Reason': 650, 'Action': 270}

        def on_take_action(selected):
            tkinter.messagebox.showinfo('Not Implemented', 'Take Action for cleanup/fix is not implemented yet.')

        self.cleanup_table = CheckboxTable(
            parent,
            columns=self.cleanup_columns,
            data=self._get_cleanup_issues(),
            column_widths=cleanup_column_widths,
            action_button_text='Take Action',
            action_callback=on_take_action,
            enable_select_all=True,
            checked_by_default=True,
        )
        # Make the table (and thus all internal widgets) expand to full width
        self.cleanup_table.pack(fill='both', expand=True, padx=10, pady=(10, 10))
        self.add_context_help(self.cleanup_table, 'Select and resolve security hygiene issues for policies.')

        # Anchor Take Action button to always be visible at the bottom (also part of CheckboxTable, but double-sure)
        # This is handled by CheckboxTable, but if you have a custom action bar, you would add it here.

    def update_cleanup_tab_output(self):
        """Refresh the cleanup tab's data after analytics reload."""
        issues = self._get_cleanup_issues()
        if hasattr(self, 'cleanup_table'):
            self.cleanup_table.update_data(issues)

    # (Obsolete: update_cleanup_tab and _refresh_cleanup_items removed,
    # all update logic now handled by CheckboxTable in _build_cleanup_tab.)

    def _get_cleanup_issues(self):
        """
        Returns a list of dicts for issues: type, name/statement, reason, action.
        Dynamically loads actionable items from overlay['cleanup_items'].
        """
        intelligence = getattr(self.app, 'policy_intelligence', None)
        overlay = getattr(intelligence, 'overlay', {}) if intelligence else {}
        cleanup = overlay.get('cleanup_items', {})
        issues = []

        # Invalid statements
        for item in cleanup.get('invalid_statements', []):
            issues.append(
                {
                    'Type': 'Invalid Statement',
                    'Name': item.get('statement_text', '[unknown statement]'),
                    'Reason': '; '.join(item.get('invalid_reasons', [])) or 'Failed validation',
                    'Action': 'Fix invalid statement or resolve identity/reference issues.',
                }
            )

        # Unused groups
        for group in cleanup.get('unused_groups', []):
            group_name = f"{group.get('domain_name', 'Default')}/{group.get('group_name', '[unknown]')}"
            issues.append(
                {
                    'Type': 'Group w/ No Users',
                    'Name': group_name,
                    'Reason': 'Group has zero user members.',
                    'Action': 'Remove, repurpose, or assign users.',
                }
            )

        # Unused dynamic groups
        for dg in cleanup.get('unused_dynamic_groups', []):
            dg_name = f"{dg.get('domain_name', 'Default')}/{dg.get('dynamic_group_name', '[unknown]')}"
            issues.append(
                {
                    'Type': 'Unused Dynamic Group',
                    'Name': dg_name,
                    'Reason': 'Not referenced by any policy statement.',
                    'Action': 'Delete dynamic group or document why kept.',
                }
            )

        # Over-broad manage all-resources
        for st in cleanup.get('statements_too_open', []):
            issues.append(
                {
                    'Type': 'Overly Broad Statement',
                    'Name': st.get('statement_text', '[unknown statement]'),
                    'Reason': "Grants 'manage all-resources' to principal outside root/admin.",
                    'Action': 'Restrict scope and replace with least privilege permissions.',
                }
            )

        # Any-user without where clause
        for st in cleanup.get('anyuser_no_where', []):
            issues.append(
                {
                    'Type': 'Any-user Without Where',
                    'Name': st.get('statement_text', '[unknown statement]'),
                    'Reason': 'Statement grants access to any-user with no where clause.',
                    'Action': 'Limit subject with a concise where clause.',
                }
            )

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
