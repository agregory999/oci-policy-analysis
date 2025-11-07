##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# policies_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import DynamicGroup, DynamicGroupSearch, PolicySearch
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.ui.data_table import DataTable
from oci_policy_analysis.ui.helpers import for_display_dynamic_group, for_display_policy

# Column Data
BASIC_DG_COLUMNS = ['Domain', 'DG Name', 'Matching Rule', 'In Use']
ALL_DG_COLUMNS = [
    'Domain',
    'DG Name',
    'Description',
    'Matching Rule',
    'In Use',
    'DG OCID',
    'DG ID',
    'Creation Time',
    'Created By',
    'Created By OCID',
]
DG_COLUMN_WIDTHS = {
    'Domain': 150,
    'DG Name': 300,
    'Description': 400,
    'DG OCID': 450,
    'DG ID': 300,
    'Matching Rule': 700,
    'In Use': 80,
    'Creation Time': 150,
    'Created By': 200,
    'Created By OCID': 250,
}
ALL_POLICY_COLUMNS = [
    'Policy Name',
    'Policy OCID',
    'Compartment OCID',
    'Policy Compartment',
    'Statement Text',
    'Valid',
    'Invalid Reasons',
    'Subject Type',
    'Subject',
    'Verb',
    'Resource',
    'Permission',
    'Location Type',
    'Location',
    'Effective Path',
    'Conditions',
    'Comments',
    'Parsing Notes',
    'Creation Time',
    'Parsed',
]
BASIC_POLICY_COLUMNS = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Effective Path', 'Valid']
POLICY_COLUMN_WIDTHS = {
    'Policy Name': 250,
    'Policy OCID': 450,
    'Compartment OCID': 450,
    'Policy Compartment': 250,
    'Statement Text': 700,
    'Valid': 80,
    'Invalid Reasons': 200,
    'Effective Path': 200,
    'Subject Type': 120,
    'Subject': 200,
    'Verb': 100,
    'Resource': 150,
    'Permission': 150,
    'Location Type': 120,
    'Location': 200,
    'Conditions': 200,
    'Comments': 200,
    'Parsing Notes': 250,
    'Creation Time': 150,
    'Parsed': 80,
}


logger = get_logger(component='dynamic_group_tab')


class DynamicGroupsTab(ttk.Frame):
    def __init__(
        self,
        parent,
        app,
        policy_compartment_analysis: PolicyAnalysisRepository,
    ):
        super().__init__(parent)
        self.app = app
        self.policy_compartment_analysis = policy_compartment_analysis
        self.create_tab()

    def create_tab(self):
        # Configure grid
        self.grid_rowconfigure(0, weight=2)
        self.grid_rowconfigure(1, weight=4)
        self.grid_rowconfigure(2, weight=4)
        self.grid_columnconfigure(0, weight=1)

        # Filter options (LabelFrame)
        label_frm = ttk.LabelFrame(self, text='Dynamic Group Filters')
        label_frm.pack(fill='both', padx=10, pady=10)

        # Clear filters function
        def clear_dg_filters():
            for entry in [self.domain_filter_var, self.dg_name_var, self.dg_rule_var]:
                entry.set('')
            self._update_dg_output()

        self.chk_show_instance_principals = tk.BooleanVar()
        self.chk_show_not_in_use = tk.BooleanVar()
        self.chk_show_dg_ocid = tk.BooleanVar()
        self.domain_filter_var = tk.StringVar()
        self.dg_name_var = tk.StringVar()
        self.dg_rule_var = tk.StringVar()

        # Top of frame
        frm_dg_filter = ttk.Frame(label_frm)
        frm_dg_filter.grid(row=0, column=0, sticky='w', padx=5, pady=5)
        frm_dg_filter.columnconfigure([1, 3], weight=1)
        ttk.Label(frm_dg_filter, text='Filters (| for OR, AND between fields)').grid(
            row=0, column=0, columnspan=5, pady=2, sticky='ew'
        )
        ttk.Label(frm_dg_filter, text='Domain').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_domain = ttk.Entry(
            frm_dg_filter, textvariable=self.domain_filter_var, state=tk.DISABLED, width=25
        )
        self.dg_entry_domain.grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Name').grid(row=1, column=2, padx=5, pady=2, sticky='w')
        self.dg_entry_name = ttk.Entry(frm_dg_filter, textvariable=self.dg_name_var, state=tk.DISABLED, width=25)
        self.dg_entry_name.grid(row=1, column=3, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Rule Component').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_type = ttk.Entry(frm_dg_filter, textvariable=self.dg_rule_var, state=tk.DISABLED, width=40)
        self.dg_entry_type.grid(row=2, column=1, padx=5, pady=2, sticky='ew')

        # Buttons
        self.dg_btn_clear = ttk.Button(frm_dg_filter, text='Clear Filters', state=tk.DISABLED, command=clear_dg_filters)
        self.dg_btn_clear.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        # Bottom of frame
        label_frm2 = ttk.LabelFrame(self, text='Output Filters')
        label_frm2.pack(fill='both', padx=10, pady=10)

        self.dg_label_statement_count = ttk.Label(label_frm2, text='Dynamic Groups (Filtered):')
        self.dg_label_statement_count.grid(row=0, column=0, columnspan=2, padx=5, pady=3, sticky='w')

        ttk.Checkbutton(
            label_frm2,
            text='Show Only Instance Principals',
            variable=self.chk_show_instance_principals,
            command=self._update_dg_output,
        ).grid(row=0, column=2, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2,
            text='Show Only Unused Dynamic Groups',
            variable=self.chk_show_not_in_use,
            command=self._update_dg_output,
        ).grid(row=0, column=4, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2,
            text='Show OCID and Creation Time',
            variable=self.chk_show_dg_ocid,
            command=self._update_dg_output,
        ).grid(row=0, column=5, padx=5, pady=3)

        ttk.Separator(label_frm2, orient=tk.VERTICAL).grid(row=0, column=6, sticky='ns', pady=5)
        self.label_policy_count = ttk.Label(label_frm2, text='Policy Statements\n(Shown Below): 0')
        self.label_policy_count.grid(row=0, column=7, padx=5, pady=3)

        def dg_selection_callback(selected_rows: list[dict]) -> None:
            """When a Dynamic Group is selected, update the policy statements below"""
            dgs_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.info(f"Selected DG: {row.get('Domain')}, {row.get('DG Name')}")
                dgs_for_filter.append((row.get('Domain'), row.get('DG Name')))
            logger.info(f'DGs for filter: {dgs_for_filter}')
            # Call the main filter
            exact_dg_filter: list[DynamicGroup] = [
                DynamicGroup(domain_name=dg[0], dynamic_group_name=dg[1]) for dg in dgs_for_filter
            ]  # type: ignore
            policy_filter: PolicySearch = PolicySearch(exact_dynamic_groups=exact_dg_filter)
            filtered = self.policy_compartment_analysis.filter_policy_statements(filters=policy_filter)
            # Normalize using helper
            filtered = [for_display_policy(stmt) for stmt in filtered]
            # Set them into the next table
            self.dg_policy_table.update_data(filtered)
            logger.info(f'Policies added to policy table: {len(filtered)}')

            # Update Policy shown label
            self.label_policy_count.config(text=f'Statements Shown: {len(self.dg_policy_table.data)}')

        def dg_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.app.policy_query_var.set(selected_statement)
            else:
                pass

        def policy_more_details_menu(row_index: int) -> tk.Menu:
            menu = tk.Menu(self, tearoff=0)
            row_data = self.dg_policy_table.data[row_index]
            logger.info(f'Creating more details menu for row {row_index}: {row_data}')

            # Create a policy search filter by policy name from selected row
            def switch_tab_policy_analysis():
                self.app.notebook.select(tab_id=1)  # Policy Analysis tab
                # Set the policy name entry
                logger.info(f'Switching to Policy Analysis tab for policy: {row_data.get("Policy Name", "")}')
                # Check the dynamic groups box and set the filter for policy name
                self.app.policies_tab.chk_show_dynamic.set(True)
                self.app.policies_tab.policy_filter_var.set(row_data.get('Policy Name', ''))

            menu.add_command(
                label=f'View Full Policy ({row_data.get("Policy Name", "")})', command=switch_tab_policy_analysis
            )
            return menu

        # Dynamic Groups
        self.custom_data_dynamic_group = DataTable(
            self,
            columns=ALL_DG_COLUMNS,
            display_columns=BASIC_DG_COLUMNS,
            column_widths=DG_COLUMN_WIDTHS,
            data=[],
            selection_callback=dg_selection_callback,
            multi_select=True,
        )
        self.custom_data_dynamic_group.pack(fill='both', expand=True, padx=10, pady=5)

        # Use a Policy Table here with fields
        self.dg_policy_table = DataTable(
            self,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            row_context_menu_callback=policy_more_details_menu,
            selection_callback=dg_policy_selection_callback,
            multi_select=False,
        )
        # self.dg_policy_table.grid(row=0, column=0, columnspan=3, sticky='nsew')
        self.dg_policy_table.pack(fill='both', expand=True, padx=10, pady=5)

        # Label for context menu
        ttk.Label(self, text='Matching Policies Table - right-click on a policy for more details').pack(
            anchor='w', padx=15, pady=(0, 5)
        )

        # Trace to update on change
        self.domain_filter_var.trace_add('write', lambda *args: self._update_dg_output())
        self.dg_name_var.trace_add('write', lambda *args: self._update_dg_output())
        self.dg_rule_var.trace_add('write', lambda *args: self._update_dg_output())

    def _update_dg_output(self):
        if self.chk_show_instance_principals.get():
            self.dg_entry_type.delete(0, tk.END)
            self.dg_entry_type.insert(0, 'instance.compartment.id|instance.id')
        else:
            if self.dg_entry_type.get() == 'instance.compartment.id|instance.id':
                self.dg_entry_type.delete(0, tk.END)
        # Filter the dynamic groups
        dg_filter: DynamicGroupSearch = DynamicGroupSearch(
            domain_name=self.dg_entry_domain.get().split('|') if self.dg_entry_domain.get() else None,  # type: ignore
            dynamic_group_name=self.dg_entry_name.get().split('|') if self.dg_entry_name.get() else None,  # type: ignore
            # Logic here - if you checked off instance principals, override the type filter
            matching_rule=['instance.compartment.id', 'instance.id']
            if self.chk_show_instance_principals.get()
            else self.dg_rule_var.get().split('|')
            if self.dg_rule_var.get()
            else None,  # type: ignore
        )

        logger.info(f'Filtering DG with {dg_filter}')
        filtered = self.policy_compartment_analysis.filter_dynamic_groups(dg_filter)
        display_dgs = [for_display_dynamic_group(dg) for dg in filtered]

        logger.info(
            f'Filtered dynamic groups from {len(self.policy_compartment_analysis.dynamic_groups)} to {len(filtered)} using filter: {dg_filter}'
        )

        # Apply additional filter for In Use
        output_filtered = []
        for dg in display_dgs:
            if self.chk_show_not_in_use.get():
                if not dg.get('In Use'):
                    output_filtered.append(dg)
            else:
                output_filtered.append(dg)
        self.custom_data_dynamic_group.update_data(output_filtered)

        # If expanded, show all columns, else show a subset
        if self.chk_show_dg_ocid.get():
            self.custom_data_dynamic_group.set_display_columns(ALL_DG_COLUMNS)
            logger.info('Setting dynamic group table to expanded view with all columns')
        else:
            self.custom_data_dynamic_group.set_display_columns(BASIC_DG_COLUMNS)
            logger.info('Setting dynamic group table to basic view with key columns')

        # Update label with counts
        self.dg_label_statement_count.config(
            text=f'Dynamic Groups (Total): {len(self.policy_compartment_analysis.dynamic_groups)}\nDynamic Groups (Filtered): {len(output_filtered)}'
        )

    def enable_controls(self):
        """
        Called from main app when data is loaded to enable the controls
        """
        for entry in [self.dg_entry_domain, self.dg_entry_name, self.dg_entry_type]:
            entry.config(state=tk.NORMAL)
        for btn in [self.dg_btn_clear]:
            btn.config(state=tk.NORMAL)
        # Set the data
        self._update_dg_output()
