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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

# from logic.models import CrossTenancyPolicy, DefinedAlias
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.logger import get_logger
from oci_policy_analysis.ui.data_table import DataTable
from oci_policy_analysis.ui.helpers import for_display_define, for_display_policy

# For cross-tenancy policies, just show all details we have
DEFINED_ALIAS_COLUMNS = ['Defined Name', 'Defined Type', 'OCID Alias']
CROSS_TENANCY_POLICY_COLUMNS = ['Policy Name', 'Policy OCID', 'Statement Text', 'Creation Time']
DEFINED_ALIAS_COLUMN_WIDTHS = {'Defined Name': 150, 'Defined Type': 150, 'OCID Alias': 500}
CROSS_TENANCY_POLICY_COLUMN_WIDTHS = {
    'Policy Name': 150,
    'Policy OCID': 300,
    'Statement Text': 600,
    'Creation Time': 150,
}

logger = get_logger(component='cross_tenancy_tab')


class CrossTenancyTab(ttk.Frame):
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
            """When a Defined Alias is selected, update the policy statements below"""
            defined_aliases_for_filter = []
            # Make the Defined Alias list for all selected rows
            for row in selected_rows:
                logger.info(f"Selected row: {row.get('Defined Name')}")
                defined_aliases_for_filter.append(row.get('Defined Name'))
            logger.info(f'Defined Aliases for filter: {defined_aliases_for_filter}')

            # Call the filter
            filtered = self.policy_compartment_analysis.filter_cross_tenancy_policy_statements(
                defined_aliases_for_filter
            )
            displayed_filtered = [for_display_policy(statement) for statement in filtered]
            filtered = displayed_filtered
            logger.info(f'Cross-tenancy: {len(filtered)}')
            # Set them into the next table
            self.cross_tenancy_table.update_data(filtered)
            logger.info(f'Policies added to cross-tenancy policy table: {len(filtered)}')

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

        # Cross Tenancy Policies Table
        self.cross_tenancy_table = DataTable(
            self,
            columns=CROSS_TENANCY_POLICY_COLUMNS,
            display_columns=CROSS_TENANCY_POLICY_COLUMNS,
            data=[],
            column_widths=CROSS_TENANCY_POLICY_COLUMN_WIDTHS,
            selection_callback=cross_tenancy_policy_selection_callback,
            multi_select=False,
        )
        self.cross_tenancy_table.grid(row=1, column=0, columnspan=2, sticky='nsew')

    def update_cross_tenancy_output(self):
        logger.info(f'Displaying: {len(self.policy_compartment_analysis.cross_tenancy_statements)} CT Statements')
        defined_aliases = self.policy_compartment_analysis.defined_aliases
        cross_tenancy_statements = self.policy_compartment_analysis.cross_tenancy_statements
        display_defined = [for_display_define(defined_alias) for defined_alias in defined_aliases]
        display_statements = [for_display_policy(statement) for statement in cross_tenancy_statements]
        logger.debug(f'Defined Aliases: {defined_aliases}')
        logger.debug(f'Cross-Tenancy Statements: {cross_tenancy_statements}')

        self.defined_aliases_table.update_data(display_defined)
        self.cross_tenancy_table.update_data(display_statements)
