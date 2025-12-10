##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# policy_overlap_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_policy
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.ui.data_table import DataTable

# Column data for Policy Overlap Table (extends basic policy columns)
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
    'Action': 80,
    'Policy Name': 250,
    'Policy Compartment': 250,
    'Effective Path': 200,
    'Statement Text': 700,
    'Valid': 80,
    'Policy Overlap': 500,
    'Internal ID': 100,
}

# Global logger for this module
logger = get_logger(component='policy_overlap')


class PolicyOverlapTab(ttk.Frame):
    """
    Tab for displaying policies and analyzing overlaps. Includes a button to trigger overlap analysis
    and a table to display the results. Selecting a policy statement shows detailed overlap information
    in a treeview below.
    """

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository, settings):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = policy_repo

        # Effective Compartment and Resource filter states
        self.effective_compartment_filter = 'ALL'
        self.resource_filter = 'ALL'

        # Configure tab
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Button frame
        button_frame = ttk.Frame(self)
        button_frame.pack(fill='x', padx=10, pady=10)

        self.btn_analyze = ttk.Button(
            button_frame,
            text='Analyze Overlaps',
            command=self._analyze_overlaps,
            state=tk.DISABLED,
        )
        self.btn_analyze.pack(side='left')

        # Label for compartments and resources
        ttk.Label(button_frame, text='Filter by Effective Compartment:').pack(side='left', padx=(10, 0))

        # Effective Compartment dropdown (will be initialized after data/table loads)
        self.compartment_values = ['ALL']
        self.combobox_compartment = ttk.Combobox(
            button_frame,
            state='readonly',
            values=self.compartment_values,
            width=30,
        )
        self.combobox_compartment.set('ALL')
        self.combobox_compartment.pack(side='left', padx=(10, 0))
        self.combobox_compartment.bind('<<ComboboxSelected>>', self._on_effective_compartment_selected)

        # Label for compartments and resources
        ttk.Label(button_frame, text='Filter by Resource:').pack(side='left', padx=(10, 0))

        # Resource dropdown (will be initialized after data/table loads)
        self.resource_values = ['ALL']
        self.combobox_resource = ttk.Combobox(
            button_frame,
            state='readonly',
            values=self.resource_values,
            width=30,
        )
        self.combobox_resource.set('ALL')
        self.combobox_resource.pack(side='left', padx=(6, 0))
        self.combobox_resource.bind('<<ComboboxSelected>>', self._on_resource_selected)

        # Label with instructions
        ttk.Label(button_frame, text='After analysis, select a policy statement to view overlaps below:').pack(
            side='left', padx=(10, 0)
        )

        # Policy table
        def on_overlap_select(selected_rows: list[dict]) -> None:
            if selected_rows:
                row = selected_rows[0]  # Single select for details
                logger.debug(f'Selected row for overlap details: {row}')
                # Use the internal ID to lookup to get the overlaps
                internal_id = row.get('Internal ID', [])
                # How do i get the overlaps for this internal ID?
                overlaps = self.policy_repo.get_policy_overlaps_by_internal_id(internal_id)
                self.overlap_tree.delete(*self.overlap_tree.get_children())
                logger.debug(f'Displaying overlaps for selected statement: {overlaps}')
                for _i, overlap in enumerate(overlaps):
                    superseded_by = overlap.get('superseded_by', 'N/A')
                    confidence = overlap.get('confidence', 'N/A')
                    reason = overlap.get('reason', 'N/A')
                    statement_text = overlap.get('statement_text', 'N/A')
                    permission_overlap = overlap.get('permission_overlap', [])

                    parent = self.overlap_tree.insert(
                        '',
                        'end',
                        open=True,
                        text=f"Policy Statement ({row.get('Statement Text', 'N/A')}) overlaps with Policy ('{superseded_by}')",
                    )
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Policy Name: {superseded_by}',
                    )
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Statement Text: {statement_text}',
                    )
                    # Always display permission_overlap as uppercase
                    perms_upper = [p.upper() for p in permission_overlap] if permission_overlap else []
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Overlapping Permissions: {perms_upper}',
                    )
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Confidence: {confidence}',
                    )
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Reason: {reason}',
                    )
                    if overlap.get('additional_notes'):
                        notes = overlap.get('additional_notes')
                        self.overlap_tree.insert(
                            parent,
                            'end',
                            text=f'Additional Notes: {notes}',
                        )

        self.policy_table = DataTable(
            self,
            columns=POLICY_OVERLAP_ALL_COLUMNS,
            display_columns=POLICY_OVERLAP_DISPLAY_COLUMNS,
            data=[],
            column_widths=POLICY_OVERLAP_COLUMN_WIDTHS,
            selection_callback=on_overlap_select,
            multi_select=True,
            highlights=[('Action', 'deny', '#FF0000')],
        )
        self.policy_table.pack(fill='both', expand=True, padx=10, pady=(10, 0))

        # Overlap details treeview below table
        overlap_frame = ttk.LabelFrame(self, text='Overlap Details')
        overlap_frame.pack(fill='x', padx=10, pady=(0, 10))
        overlap_frame.grid_rowconfigure(0, weight=1)
        overlap_frame.grid_columnconfigure(0, weight=1)

        self.overlap_tree = ttk.Treeview(
            overlap_frame,
            show='tree',
            height=10,
        )
        self.overlap_tree.heading('#0', text='Overlap Details')

        self.overlap_tree.column('#0', width=1200, stretch=True)

        scrollbar = ttk.Scrollbar(overlap_frame, orient='vertical', command=self.overlap_tree.yview)
        self.overlap_tree.configure(yscrollcommand=scrollbar.set)
        self.overlap_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def _analyze_overlaps(self):
        """Call analyze_policy_overlap and refresh the table."""
        if not self.policy_repo.regular_statements:
            logger.warning('No policies loaded for overlap analysis')
            return
        self.policy_repo.analyze_policy_overlap()
        self.effective_compartment_filter = 'ALL'
        self.update_overlap_output()
        logger.info('Policy overlap analysis completed and table refreshed')

    def update_overlap_output(self):  # noqa: C901
        """Update the policy overlap table using repository filtering, similar to update_policy_output in PoliciesTab."""
        if not self.policy_repo.regular_statements:
            self.policy_table.update_data([])
            self.combobox_compartment['values'] = ['ALL']
            self.combobox_compartment.set('ALL')
            self.combobox_resource['values'] = ['ALL']
            self.combobox_resource.set('ALL')
            return

        # Always build dropdowns from ALL available values among regular_statements (not filtered)
        statements_all = [
            for_display_policy(st) for st in self.policy_repo.regular_statements if 'policy_overlap' in st
        ]

        # Effective Path dropdown
        paths_raw = {st.get('Effective Path') for st in statements_all}
        paths = {p for p in paths_raw if isinstance(p, str)}
        compartment_list = ['ALL'] + sorted(paths)
        self.combobox_compartment['values'] = compartment_list
        if self.effective_compartment_filter not in compartment_list:
            self.effective_compartment_filter = 'ALL'
            self.combobox_compartment.set('ALL')

        # Resource dropdown: gather from all statements, deduped, skip None, flatten if multiple-per-row
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
        self.combobox_resource['values'] = resource_list
        if self.resource_filter not in resource_list:
            self.resource_filter = 'ALL'
            self.combobox_resource.set('ALL')

        # Build filter for repo (not client-side filter)
        from oci_policy_analysis.common.models import PolicySearch

        filters: PolicySearch = {}
        if self.effective_compartment_filter != 'ALL':
            filters['effective_path'] = [self.effective_compartment_filter]
        if self.resource_filter != 'ALL':
            filters['resource'] = [self.resource_filter]

        filtered_statements = self.policy_repo.filter_policy_statements(filters=filters)
        normalized = [for_display_policy(st) for st in filtered_statements if 'policy_overlap' in st]

        self.policy_table.update_data(normalized)
        logger.info(f'Updated policy overlap table with {len(normalized)} statements (filter = {filters})')

    def _on_effective_compartment_selected(self, event=None):
        """Callback for compartment dropdown selection."""
        selected = self.combobox_compartment.get()
        self.effective_compartment_filter = selected if selected != 'ALL' else 'ALL'
        self.update_overlap_output()

    def _on_resource_selected(self, event=None):
        """Callback for resource dropdown selection."""
        selected = self.combobox_resource.get()
        self.resource_filter = selected if selected != 'ALL' else 'ALL'
        self.update_overlap_output()

    def enable_widgets_after_load(self):
        """Enable widgets after data load."""
        self.btn_analyze.configure(state='normal')
        self.update_overlap_output()
