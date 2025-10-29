##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# resource_principals_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################
import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.models import DynamicGroup, PolicySearch, PolicyStatement
from oci_policy_analysis.ui.data_table import DataTable
from oci_policy_analysis.ui.helpers import for_display_dynamic_group, for_display_policy

logger = get_logger(component='resource_principals_tab')

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


class ResourcePrincipalsTab(ttk.Frame):
    """
    Minimal Resource Principals Tab: Display filtering for RPs
    Uses the already-loaded data_repo from memory.
    """

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository):
        """
        Args:
            parent: parent notebook or frame
            config: dict from config.json (must include mcp settings)
            log_console: existing popup console (must have .write_line)
        """
        super().__init__(parent)
        self.app = app
        self.policy_repo = policy_repo

        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=10)
        self.grid_rowconfigure(1, weight=80)  # Separate Form
        self.grid_rowconfigure(2, weight=10)
        self.grid_columnconfigure(0, weight=1)

        # Frame for top
        frm_principals_top = ttk.Frame(self)
        frm_principals_top.grid(row=0, column=0, sticky='w', padx=5, pady=5)

        # Principals Style dropdown
        ttk.Label(frm_principals_top, text='Principals Style:').grid(row=0, column=0, padx=5, pady=2, sticky='w')
        self.principals_style_var = tk.StringVar(value='Dynamic Group')
        self.principals_style_list = ['Dynamic Group', 'any-user']
        self.principals_style_dropdown = ttk.OptionMenu(
            frm_principals_top, self.principals_style_var, self.principals_style_var.get(), *self.principals_style_list
        )
        self.principals_style_dropdown.grid(row=0, column=1, padx=5, pady=2, sticky='ew')

        # Resource Type dropdown
        ttk.Label(frm_principals_top, text='Resource Type:').grid(row=0, column=2, padx=5, pady=2, sticky='w')
        self.resource_type_var = tk.StringVar(value='Any')
        self.resource_type_list = [
            'Any',
            'autonomousdatabase',
            'function',
            'apigateway',
            'disworkspace',
            'dataflow',
            'dbmgmt',
            'serviceconnector',
            'stackmon',
            'cluster',
            'workloadprotectionagent',
            'aidataplatform',
        ]
        self.resource_type_dropdown = ttk.OptionMenu(
            frm_principals_top, self.resource_type_var, self.resource_type_var.get(), *self.resource_type_list
        )
        self.resource_type_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky='ew')

        def rp_dg_selection_callback(selected_rows: list[dict]) -> None:
            """When a Dynamic Group is selected, update the policy statements below"""
            dgs_for_filter: list[DynamicGroup] = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.info(f'Selected row: {row}')
                dgs_for_filter.append(
                    DynamicGroup(domain_name=row.get('Domain', ''), dynamic_group_name=row.get('DG Name', ''))
                )

                # dgs_for_filter.append((row.get('Domain'), row.get('DG Name')))
            logger.info(f'DGs for filter: {dgs_for_filter}')
            # Call the filter
            # TODO: fix this filter
            filters: PolicySearch = PolicySearch(exact_dynamic_groups=dgs_for_filter)
            filtered = self.policy_repo.filter_policy_statements(filters)

            logger.debug(f'type: {type(filtered)} len: {len(filtered)}')
            # SNormalize the data
            filtered = [for_display_policy(statement) for statement in filtered]
            self.rp_policy_table.update_data(filtered)
            logger.info(f'Policies added to RP policy table: {len(filtered)}')

        def rp_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.app.policy_query_var.set(selected_statement)

        def policy_more_details_menu(row_index: int) -> tk.Menu:
            menu = tk.Menu(self, tearoff=0)
            row_data = self.rp_policy_table.data[row_index]
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

        # Bottom frame (row 1) for sheets using grid (bottom 2 rows if DG, bottom 1 if any-user)
        frm_principals_bottom = ttk.Frame(self)
        frm_principals_bottom.grid_rowconfigure(0, weight=1)
        frm_principals_bottom.grid_rowconfigure(1, weight=1)
        frm_principals_bottom.grid_columnconfigure(0, weight=1)
        frm_principals_bottom.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Dynamic Groups Sheet (can be ungridded when not needed)
        self.rp_dg_table = DataTable(
            frm_principals_bottom,
            columns=ALL_DG_COLUMNS,
            display_columns=BASIC_DG_COLUMNS,
            column_widths=DG_COLUMN_WIDTHS,
            data=[],
            selection_callback=rp_dg_selection_callback,
            multi_select=True,
        )
        self.rp_dg_table.grid(row=0, column=0, sticky='nsew')

        # Add a label above table to show instructions
        ttk.Label(
            frm_principals_bottom, text='Matching Policies Table - right-click on a policy for more details'
        ).grid(row=4, column=0, padx=5, pady=5, sticky='w')
        # RP Policy Table
        self.rp_policy_table = DataTable(
            frm_principals_bottom,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            row_context_menu_callback=policy_more_details_menu,
            selection_callback=rp_policy_selection_callback,
            multi_select=False,
        )
        self.rp_policy_table.grid(row=2, column=0, sticky='nsew')

        # Update the sheet
        self.update_principals_sheets()

        # # Bind dropdowns to update function
        self.principals_style_var.trace_add('write', self.update_principals_sheets)
        self.resource_type_var.trace_add('write', self.update_principals_sheets)

    def update_principals_sheets(self, *args):
        """Update sheets based on dropdown selections and dynamic group selection."""
        principals_style = self.principals_style_var.get()
        resource_type = self.resource_type_var.get()

        # Enable/disable Resource Type dropdown
        self.resource_type_dropdown.configure(state='normal')

        # Enable/disable Principals Style
        self.principals_style_dropdown.configure(state='normal')

        # Un-grid both sheets (re-grid in a sec)
        self.rp_dg_table.grid_forget()
        self.rp_policy_table.grid_forget()

        if principals_style == 'any-user':
            # Enable Resource Type dropdown
            self.resource_type_dropdown.configure(state='normal')

            # Re-grid RP sheet
            self.rp_policy_table.grid(row=0, column=0, rowspan=2, sticky='nsew')
            logger.info('Any-User selected - only showing Policy table with resource dropdown')

            # Don't care about Dynamic groups
            if resource_type == 'Any':
                logger.info('Any-User with Any resource type selected')
                # TODO Fixme: this filter is not working as intended
                filters: PolicySearch = PolicySearch(conditions=['request.principal.type', 'any-user'])
                policies: list[PolicyStatement] = self.policy_repo.filter_policy_statements(filters=filters)
                # Normalize the data
                display_data = [for_display_policy(statement) for statement in policies]
                self.rp_policy_table.update_data(display_data)

                logger.info(f'Filtered to {len(policies)} policies with any principal type')
                # self.principals_sheet_policies_instance.set_sheet_data(policies)
            else:
                logger.info(f'Any-User with type {resource_type} specified')
                filters: PolicySearch = PolicySearch(
                    conditions=['request.principal.type'], statement_text=[resource_type]
                )
                policies = self.policy_repo.filter_policy_statements(filters=filters)
                # Normalize the data
                display_data = [for_display_policy(statement) for statement in policies]
                self.rp_policy_table.update_data(display_data)
                logger.info(f'Filtered to {len(policies)} policies with principal type {resource_type}')

        elif principals_style == 'Dynamic Group':
            # Disable Resource Type dropdown
            self.resource_type_dropdown.configure(state='disabled')

            logger.info('Showing Dynamic Groups and Policy tables')

            # Re-grid DG and RP sheet
            self.rp_dg_table.grid(row=0, column=0, sticky='nsew')
            self.rp_policy_table.grid(row=1, column=0, sticky='nsew')

            logger.info('Added both DG and Policy tables to grid')

            # Populate dynamic group sheet
            filtered_dynamic_groups = []
            # if type_principal == "Instance Principals":
            # filtered_dynamic_groups = identity_domain_analysis.filter_dynamic_groups(type_filter="instance.compartment.id")
            # elif type_principal == "Resource Principals":
            filtered_dynamic_groups = self.policy_repo.filter_dynamic_groups(filters={})
            # type_filter='resource.type|resource.principal|resource.id'
            # )

            # Normalize the data
            filtered_dynamic_groups = [for_display_dynamic_group(dg) for dg in filtered_dynamic_groups]
            self.rp_dg_table.update_data(filtered_dynamic_groups)
