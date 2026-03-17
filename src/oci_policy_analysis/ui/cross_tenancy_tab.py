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
from tkinter import messagebox, ttk

from oci_policy_analysis.common.helpers import for_display_admit, for_display_define, for_display_endorse
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.ui.base_tab import BaseUITab
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


class CrossTenancyTab(BaseUITab):
    """
    Cross-Tenancy Tab for OCI Policy Analysis UI.

    Allows viewing defined aliases and associated cross-tenancy policy statements.
    Features label frames, page help, and proper context help wiring.
    """

    def __init__(self, parent, main_app):
        super().__init__(
            parent,
            default_help_text='View and analyze cross-tenancy OCI policies, including defined OCID aliases, Admit, and Endorse statement details.',
            page_help_link='/usage.html#cross-tenancy-tab',
        )
        self.main_app = main_app
        self.policy_compartment_analysis = main_app.policy_compartment_analysis
        self._build_ui()

    def _build_ui(self):
        logger.info('Creating Cross-Tenancy Tab')
        # Layout: vertical sections (Defined Aliases; Admits; Endorses) using pack/LabelFrames.

        # ---- Defined Aliases Section ----
        defined_labelframe = ttk.LabelFrame(self, text='Defined Aliases')
        defined_labelframe.pack(fill='x', padx=6, pady=(8, 3))
        self.add_context_help(defined_labelframe, 'Shows OCID alias definitions used in cross-tenancy policies.')

        defined_labelframe.grid_columnconfigure(0, weight=1)
        defined_labelframe.grid_rowconfigure(0, weight=1)

        # --- Action Buttons (stubbed) ---
        button_frame = ttk.Frame(defined_labelframe)
        button_frame.grid(row=0, column=0, sticky='w', padx=2, pady=(2, 2))

        self.btn_generate_opposing = ttk.Button(
            button_frame,
            text='Generate Opposing Tenancy Statements',
            command=self._on_generate_opposing_clicked,
            state='disabled',
        )
        self.btn_generate_opposing.pack(side='left', padx=(0, 6))

        self.btn_consolidate_xt = ttk.Button(
            button_frame,
            text='Consolidate Cross-Tenancy',
            command=self._on_consolidate_xt_clicked,
            state='disabled',
        )
        self.btn_consolidate_xt.pack(side='left')

        ttk.Label(
            defined_labelframe,
            text='Select alias rows to filter cross-tenancy policies below. Sort via column headers.',
            font=('TkFixedFont', 10),
        ).grid(row=1, column=0, sticky='w', padx=5, pady=(4, 3))

        def cross_tenancy_define_selection_callback(selected_rows: list[dict]) -> None:
            # Selection callback for Defined Aliases (adapt or remove as appropriate in the split-table UI)
            # To support filtering admits/endorses by alias, this would need refactor to filter/refresh both tables.
            # As currently handled, leave as no-op or implement advanced filter logic later.
            logger.info(f'Defined Alias selection callback triggered. Selected rows: {selected_rows}')

            # Normalize selection set for robust matching
            selected_defined_names = {
                n.strip().lower()
                for n in [row.get('Defined Name', '') for row in selected_rows if row.get('Defined Name')]
            }
            logger.info(f'Selected Defined Names: {selected_defined_names}')

            # Enable/disable action buttons based on selection
            if hasattr(self, 'btn_generate_opposing'):
                if selected_defined_names:
                    self.btn_generate_opposing.config(state='normal')
                    self.btn_consolidate_xt.config(state='normal')
                else:
                    self.btn_generate_opposing.config(state='disabled')
                    self.btn_consolidate_xt.config(state='disabled')

            def admit_filter(st):
                admitted_tenancy = (st.get('admitted_tenancy') or '').strip().lower()
                return admitted_tenancy in selected_defined_names

            def endorse_filter(st):
                endorse_tenancy = (st.get('endorse_tenancy') or '').strip().lower()
                return endorse_tenancy in selected_defined_names

            if selected_defined_names:
                filtered_admits = [
                    st
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('admit', 'deny admit')) and admit_filter(st)
                ]
                filtered_endorses = [
                    st
                    for st in self.policy_compartment_analysis.cross_tenancy_statements
                    if st.get('statement_text', '').lower().startswith(('endorse', 'deny endorse'))
                    and endorse_filter(st)
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

        # Defined Aliases Table
        self.defined_aliases_table = DataTable(
            defined_labelframe,
            columns=DEFINED_ALIAS_COLUMNS,
            display_columns=DEFINED_ALIAS_COLUMNS,
            data=[],
            column_widths=DEFINED_ALIAS_COLUMN_WIDTHS,
            selection_callback=cross_tenancy_define_selection_callback,
            row_context_menu_callback=defined_aliases_row_details,
            multi_select=True,
        )
        self.defined_aliases_table.grid(row=2, column=0, sticky='nsew', padx=3, pady=(2, 6))

        # ---- Admit Policies Section ----
        admit_labelframe = ttk.LabelFrame(self, text='Admit Policies')
        admit_labelframe.pack(fill='x', padx=6, pady=(3, 3))
        self.add_context_help(
            admit_labelframe, "OCI 'Admit' policies define which external tenancy principals may act on resources here."
        )

        admit_labelframe.grid_columnconfigure(0, weight=1)
        admit_labelframe.grid_rowconfigure(2, weight=1)

        self.show_all_admit = tk.BooleanVar(value=True)
        admit_checkbox = ttk.Checkbutton(
            admit_labelframe, text='Show All Fields', variable=self.show_all_admit, command=self.toggle_admit_columns
        )
        admit_checkbox.grid(row=0, column=0, sticky='w', padx=(6, 2), pady=(4, 3))
        self.add_context_help(admit_checkbox, 'Toggle between basic and full details for Admit policy view.')

        # Admit Policies Table
        self.admit_table = DataTable(
            admit_labelframe,
            columns=ADMIT_POLICY_ALL_COLUMNS,
            display_columns=ADMIT_POLICY_ALL_COLUMNS,
            data=[],
            column_widths=ADMIT_POLICY_COLUMN_WIDTHS,
            selection_callback=None,  # add as needed
            multi_select=False,
            height=6,  # Show fewer lines by default for compact display
        )
        self.admit_table.grid(row=1, column=0, sticky='nsew', padx=3, pady=(1, 6))

        # ---- Endorse Policies Section ----
        endorse_labelframe = ttk.LabelFrame(self, text='Endorse Policies')
        endorse_labelframe.pack(fill='x', padx=6, pady=(3, 8))
        self.add_context_help(
            endorse_labelframe,
            "OCI 'Endorse' policies allow local tenancy to authorize actions in external OCI tenancies.",
        )

        endorse_labelframe.grid_columnconfigure(0, weight=1)
        endorse_labelframe.grid_rowconfigure(2, weight=1)

        self.show_all_endorse = tk.BooleanVar(value=True)
        endorse_checkbox = ttk.Checkbutton(
            endorse_labelframe,
            text='Show All Fields',
            variable=self.show_all_endorse,
            command=self.toggle_endorse_columns,
        )
        endorse_checkbox.grid(row=0, column=0, sticky='w', padx=(6, 2), pady=(4, 3))
        self.add_context_help(endorse_checkbox, 'Toggle between basic and full details for Endorse policy view.')

        # Endorse Policies Table
        self.endorse_table = DataTable(
            endorse_labelframe,
            columns=ENDORSE_POLICY_ALL_COLUMNS,
            display_columns=ENDORSE_POLICY_ALL_COLUMNS,
            data=[],
            column_widths=ENDORSE_POLICY_COLUMN_WIDTHS,
            selection_callback=None,  # add as needed
            multi_select=False,
            height=6,  # Show fewer lines by default for compact display
        )
        self.endorse_table.grid(row=1, column=0, sticky='nsew', padx=3, pady=(1, 10))

    def _on_generate_opposing_clicked(self):
        logger.info('Generate Opposing Tenancy Statements clicked')
        messagebox.showinfo('Info', 'Opposing tenancy statement generation not yet implemented.')

    def _on_consolidate_xt_clicked(self):
        logger.info('Consolidate Cross-Tenancy clicked')
        messagebox.showinfo('Info', 'Cross-tenancy consolidation not yet implemented.')

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
                logger.debug(f'Admit detected: {st}')
            elif statement_text.lower().startswith('endorse') or statement_text.lower().startswith('deny endorse'):
                endorses.append(st)
                logger.debug(f'Endorse detected: {st}')
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
