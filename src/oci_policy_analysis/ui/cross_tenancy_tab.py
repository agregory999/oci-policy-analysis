##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# cross_tenancy_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_admit, for_display_define, for_display_endorse
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.ui.data_table import DataTable

# For cross-tenancy policies, just show all details we have
DEFINED_ALIAS_COLUMNS = ['Policy Name', 'Defined Type', 'Defined Name', 'OCID Alias']
ADMIT_POLICY_BASIC_COLUMNS = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Creation Time', 'Parsed']
ADMIT_POLICY_ALL_COLUMNS = [
    'Policy Name',
    'Policy Compartment',
    'Statement Text',
    'Creation Time',
    'Parsed',
    'Action Type',
    'Admitted Principal Type',
    'Admitted Principals',
    'Admitted Tenancy',
    'Admitted Action (or Permission)',
    # 'Admitted Resource',
    # 'Admitted Permission Set',
    'Location Type',
    'Location',
    'Where Clause',
    'Comments',
]
ENDORSE_POLICY_BASIC_COLUMNS = ['Policy Name', 'Policy OCID', 'Statement Text', 'Creation Time', 'Parsed']
ENDORSE_POLICY_ALL_COLUMNS = [
    'Policy Name',
    'Policy OCID',
    'Statement Text',
    'Creation Time',
    'Parsed',
    'Action Type',
    'Endorsed Principal Type',
    'Endorsed Principals',
    'Endorsed Action (or Permission)',
    # 'Endorsed Resource',
    # 'Endorsed Permissions',
    'Endorsed Tenancy Name',
    'Where Clause',
    'Comments',
]
DEFINED_ALIAS_COLUMN_WIDTHS = {'Policy Name': 200, 'Defined Name': 150, 'Defined Type': 150, 'OCID Alias': 500}
ADMIT_POLICY_COLUMN_WIDTHS = {col: 170 for col in ADMIT_POLICY_ALL_COLUMNS}

ADMIT_POLICY_COLUMN_WIDTHS['Statement Text'] = 450
ADMIT_POLICY_COLUMN_WIDTHS['Creation Time'] = 150

ENDORSE_POLICY_COLUMN_WIDTHS = {col: 220 for col in ENDORSE_POLICY_ALL_COLUMNS}
ENDORSE_POLICY_COLUMN_WIDTHS['Statement Text'] = 400
ENDORSE_POLICY_COLUMN_WIDTHS['Creation Time'] = 150

logger = get_logger(component='cross_tenancy_tab')


class CrossTenancyTab(ttk.Frame):
    """
    Cross-Tenancy Tab for OCI Policy Analysis UI.
    Allows viewing defined aliases and associated cross-tenancy policy statements.
    Methods:
         __init__: Initializes the CrossTenancyTab with UI components and callbacks.
         update_cross_tenancy_output: Updates the defined aliases and cross-tenancy policy statements displayed.  Called from main app and when selections are changed.
    """

    def __init__(
        self,
        parent,
        main_app,
        policy_compartment_analysis: PolicyAnalysisRepository,
    ):
        super().__init__(parent)
        self.main_app = main_app
        self.policy_compartment_analysis = policy_compartment_analysis
        self.create_tab()

    def create_tab(self):
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=6)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=6)

        logger.info('Creating Cross-Tenancy Tab')

        ttk.Label(
            self,
            text='Select one or more rows to the right\nin order to narrow down cross-tenancy policies\n\nSort by clicking column headers',
            font=('TkFixedFont', 10, 'normal'),
        ).grid(row=0, column=0, padx=5, pady=5, sticky='w')

        def cross_tenancy_define_selection_callback(selected_rows: list[dict]) -> None:
            # Selection callback for Defined Aliases (adapt or remove as appropriate in the split-table UI)
            # To support filtering admits/endorses by alias, this would need refactor to filter/refresh both tables.
            # As currently handled, leave as no-op or implement advanced filter logic later.
            logger.info(f'Defined Alias selection callback triggered. Selected rows: {selected_rows}')
            # Get the selected defined names
            selected_defined_names = [row.get('Defined Name', '') for row in selected_rows]
            logger.info(f'Selected Defined Names: {selected_defined_names}')
            # Filter admit and endorse tables based on selected defined names
            # For admit statements, we use "admitted_principal_tenancy" as the field to filter on
            # For endorse statements, we use "endorse_tenancy" as the field to filter on
            # If no rows are selected, show all entries
            if selected_defined_names:
                filtered_admits = [
                    st
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('admit', 'deny admit'))
                    and any(
                        defined_name.lower() in st.get('admitted_tenancy', '').lower()
                        for defined_name in selected_defined_names
                    )
                ]
                filtered_endorses = [
                    st
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('endorse', 'deny endorse'))
                    and any(
                        defined_name.lower() in st.get('endorse_tenancy', '').lower()
                        for defined_name in selected_defined_names
                    )
                ]
                display_admits = [for_display_admit(st) for st in filtered_admits]
                display_endorses = [for_display_endorse(st) for st in filtered_endorses]
                self.admit_table.update_data(display_admits)
                self.endorse_table.update_data(display_endorses)
            else:
                display_admits = [
                    for_display_admit(st)
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('admit', 'deny admit'))
                ]
                display_endorses = [
                    for_display_endorse(st)
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('endorse', 'deny endorse'))
                ]
                self.admit_table.update_data(display_admits)
                self.endorse_table.update_data(display_endorses)
            pass

        def cross_tenancy_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.main_app.policy_query_var.set(selected_statement)
            else:
                pass

        # def switch_tab_policy_analysis():
        #     self.notebook.select(tab_id=1)  # Policy Analysis tab
        #     # Set the policy name entry
        #     # self.policy_name_var.set(self.defined_aliases_table.get_row_data(row_index).get('Defined Name', ''))

        def defined_aliases_row_details(row_index: int) -> tk.Menu:
            menu = tk.Menu(self, tearoff=0)
            # menu.add_command(label=f'View Details (Row {row_index})', command=switch_tab_policy_analysis)

            return menu

        # Defined Aliases
        # Show all possible fields for defines (extract from first dict if available)
        self.defined_aliases_table = DataTable(
            self,
            columns=DEFINED_ALIAS_COLUMNS,
            display_columns=DEFINED_ALIAS_COLUMNS,
            data=[],
            column_widths=DEFINED_ALIAS_COLUMN_WIDTHS,
            selection_callback=cross_tenancy_define_selection_callback,
            row_context_menu_callback=defined_aliases_row_details,
            multi_select=True,
        )
        self.defined_aliases_table.grid(row=0, column=1, sticky='nsew')

        # Checkbox for Admit policies: "Show All"
        self.show_all_admit = tk.BooleanVar(value=True)
        admit_checkbox = tk.Checkbutton(
            self, text='Show All Fields (Admit)', variable=self.show_all_admit, command=self.toggle_admit_columns
        )
        admit_checkbox.grid(row=1, column=2, sticky='e', padx=5, pady=4)

        # Admit Policies Table
        self.admit_table = DataTable(
            self,
            columns=ADMIT_POLICY_ALL_COLUMNS,
            display_columns=ADMIT_POLICY_ALL_COLUMNS,
            data=[],
            column_widths=ADMIT_POLICY_COLUMN_WIDTHS,
            selection_callback=None,  # add as needed
            multi_select=False,
        )
        self.admit_table.grid(row=1, column=0, columnspan=2, sticky='nsew')

        # Checkbox for Endorse policies: "Show All"
        self.show_all_endorse = tk.BooleanVar(value=True)
        endorse_checkbox = tk.Checkbutton(
            self, text='Show All Fields (Endorse)', variable=self.show_all_endorse, command=self.toggle_endorse_columns
        )
        endorse_checkbox.grid(row=2, column=2, sticky='e', padx=5, pady=4)

        # Endorse Policies Table
        self.endorse_table = DataTable(
            self,
            columns=ENDORSE_POLICY_ALL_COLUMNS,
            display_columns=ENDORSE_POLICY_ALL_COLUMNS,
            data=[],
            column_widths=ENDORSE_POLICY_COLUMN_WIDTHS,
            selection_callback=None,  # add as needed
            multi_select=False,
        )
        self.endorse_table.grid(row=2, column=0, columnspan=2, sticky='nsew')

    def toggle_admit_columns(self):
        if self.show_all_admit.get():
            self.admit_table.set_display_columns(ADMIT_POLICY_ALL_COLUMNS)
        else:
            self.admit_table.set_display_columns(ADMIT_POLICY_BASIC_COLUMNS)

    def toggle_endorse_columns(self):
        if self.show_all_endorse.get():
            self.endorse_table.set_display_columns(ENDORSE_POLICY_ALL_COLUMNS)
        else:
            self.endorse_table.set_display_columns(ENDORSE_POLICY_BASIC_COLUMNS)

    def update_cross_tenancy_output(self):
        logger.info(f'Displaying: {len(self.policy_compartment_analysis.cross_tenancy_statements)} CT Statements')
        defined_aliases = self.policy_compartment_analysis.defined_aliases
        cross_tenancy_statements = self.policy_compartment_analysis.cross_tenancy_statements

        display_defined = [for_display_define(defined_alias) for defined_alias in defined_aliases]

        # Split out admit and endorse
        admits = []
        endorses = []
        for st in cross_tenancy_statements:
            # Pick type by presence of startswith fields
            statement_text = st.get('statement_text', '')
            if statement_text.lower().startswith('admit') or statement_text.lower().startswith('deny admit'):
                admits.append(st)
                logger.info(f'Admit detected: {st}')
            elif statement_text.lower().startswith('endorse') or statement_text.lower().startswith('deny endorse'):
                endorses.append(st)
                logger.info(f'Endorse detected: {st}')
            else:
                logger.warning(f'Unknown cross-tenancy statement type: {st}')
        display_admits = [for_display_admit(st) for st in admits]
        display_endorses = [for_display_endorse(st) for st in endorses]

        logger.debug(f'Defined Aliases: {json.dumps(defined_aliases, indent=2)}')
        # Pretty-print lists of admits and endorses
        logger.debug(f'Cross-Tenancy - Admits: {json.dumps(admits, indent=2)}')
        logger.debug(f'Cross-Tenancy - Endorses: {json.dumps(endorses, indent=2)}')

        self.defined_aliases_table.update_data(display_defined)
        self.admit_table.update_data(display_admits)
        self.endorse_table.update_data(display_endorses)
