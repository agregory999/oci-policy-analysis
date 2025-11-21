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
    'Statement Text',
    'Valid',
    'Internal ID',
    'Policy Overlap',
]
POLICY_OVERLAP_DISPLAY_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Effective Path',
    'Statement Text',
]
POLICY_OVERLAP_COLUMN_WIDTHS = {
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
                    self.overlap_tree.insert(
                        parent,
                        'end',
                        text=f'Overlapping Permissions: {permission_overlap}',
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
        self.update_table()
        logger.info('Policy overlap analysis completed and table refreshed')

    def update_table(self):
        """Update the policy table with current statements including policy_overlap."""
        if not self.policy_repo.regular_statements:
            self.policy_table.update_data([])
            return

        # Get all statements
        statements = [for_display_policy(st) for st in self.policy_repo.regular_statements if 'policy_overlap' in st]

        self.policy_table.update_data(statements)
        logger.info(f'Updated policy overlap table with {len(statements)} statements')

    def enable_widgets_after_load(self):
        """Enable widgets after data load."""
        self.btn_analyze.configure(state='normal')
        self.update_table()
