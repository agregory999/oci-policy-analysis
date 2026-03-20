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
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################
import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_dynamic_group, for_display_policy
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import DynamicGroup, PolicySearch, RegularPolicyStatement
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

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


class ResourcePrincipalsTab(BaseUITab):
    """
    Resource Principals Tab for OCI Policy Analysis UI.

    Allows viewing Dynamic Groups and associated policy statements, with contextual page help. Now inherits from BaseUITab.
    Methods:
        __init__: Initializes the ResourcePrincipalsTab with UI components and context help.
        _build_ui: (Internal) Builds the UI components for the tab.
        apply_settings: Updates tab appearance and page help when global UI settings change.
        update_principals_sheets: Updates sheets based on dropdown and DG selection (called from main app, or internally).
    """

    def __init__(self, parent, app):
        """
        Args:
            parent: parent notebook or frame (usually a Tkinter Notebook)
            app: Reference to main App instance.
        """
        super().__init__(
            parent,
            default_help_text='Analyze and view OCI Resource Principals, including Dynamic Groups and matching policy statements below.',
            page_help_link='/usage.html#resource-principals-tab',
        )
        self.app = app
        self.policy_repo: PolicyAnalysisRepository = app.policy_compartment_analysis

        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=10)
        self.grid_rowconfigure(1, weight=80)  # Separate Form
        self.grid_rowconfigure(2, weight=10)
        self.grid_columnconfigure(0, weight=1)

        # --- Filters Section ---
        filters_labelframe = ttk.LabelFrame(self, text='Output Filters')
        filters_labelframe.pack(fill='x', padx=5, pady=5)
        self.add_context_help(filters_labelframe, 'Set analysis filters for resource principals and policies.')

        # All controls left-aligned: no column weights
        for n in range(7):
            filters_labelframe.grid_columnconfigure(n, weight=0)
        # Optionally add spacing at the end
        filters_labelframe.grid_columnconfigure(7, weight=1)

        # Principals Style dropdown
        ttk.Label(filters_labelframe, text='Principals Style:').grid(row=0, column=0, padx=5, pady=2, sticky='w')
        self.principals_style_var = tk.StringVar(value='Dynamic Group')
        self.principals_style_list = ['Dynamic Group', 'any-user', 'any-group', 'any-user / any-group']
        self.principals_style_dropdown = ttk.OptionMenu(
            filters_labelframe, self.principals_style_var, self.principals_style_var.get(), *self.principals_style_list
        )
        self.principals_style_dropdown.grid(row=0, column=1, padx=5, pady=2, sticky='ew')
        self.add_context_help(
            self.principals_style_dropdown, 'Choose which OCI principal(s) to analyze. Filters both tables below.'
        )

        # Resource Type dropdown
        ttk.Label(filters_labelframe, text='Resource Type:').grid(row=0, column=2, padx=5, pady=2, sticky='w')
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
            filters_labelframe, self.resource_type_var, self.resource_type_var.get(), *self.resource_type_list
        )
        self.resource_type_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky='ew')
        self.add_context_help(self.resource_type_dropdown, 'Filter policies by major OCI resource type.')

        # Text Filter and Clear
        ttk.Label(filters_labelframe, text='Text Filter:').grid(row=0, column=4, padx=(14, 2), pady=2, sticky='w')
        self.text_filter_var = tk.StringVar()
        self.text_filter_entry = ttk.Entry(filters_labelframe, textvariable=self.text_filter_var, width=24)
        self.text_filter_entry.grid(row=0, column=5, padx=2, pady=2, sticky='w')
        self.add_context_help(
            self.text_filter_entry,
            'Narrow results: filter matching rule (DG) or policy statement by text. Case-insensitive.',
        )

        def clear_text_filter():
            self.text_filter_var.set('')

        self.clear_filter_btn = ttk.Button(filters_labelframe, text='Clear', width=5, command=clear_text_filter)
        self.clear_filter_btn.grid(row=0, column=6, padx=(2, 8), pady=2, sticky='w')
        self.add_context_help(self.clear_filter_btn, 'Clear text filter and show all results.')

        # Add "AI Assist" button inside Filters Label Frame (to the right of "Clear")
        def ai_assist_callback():
            self.app.policy_query_var.set('Analyze OCI Resource Principals and Dynamic Group policies.')
            self.app.ai_additional_instructions = (
                'Elaborate on how Resource Principals and Dynamic Groups are matched to resources and policies in OCI. '
                'Explain important factors, provide analysis of the policy context, and describe implications for access and security.'
            )
            self.app.policy_query_label_text.set('Resource Principals Analysis:')

        self.ai_assist_btn = ttk.Button(
            filters_labelframe,
            text='AI Assist',
            command=self.app.toggle_bottom,
            width=10,
            state=tk.DISABLED,  # Initially disabled until AI enablement is successful
        )
        self.ai_assist_btn.grid(row=0, column=7, padx=(8, 8), pady=2, sticky='w')
        self.add_context_help(
            self.ai_assist_btn, 'Use Generative AI to analyze Resource Principals context and matching policies.'
        )

        # refresh on text filter change
        self.text_filter_var.trace_add('write', self.update_principals_sheets)

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
                self.app.ai_additional_instructions = 'Analyze the selected OCI policy statement. Give additional details as to how OCI Resource principals work, and show how the statement breaks down into its components such as action, subject, verb, resource, conditions, and effective path. Explain its implications on permissions within the OCI environment.'
                self.app.policy_query_label_text.set('RP Policy Statement\nInsights:')

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

        # --- Main area: Labeled Frames for each table area ---
        frm_bottom_area = ttk.Frame(self)
        frm_bottom_area.pack(fill='both', expand=True, padx=5, pady=5)
        frm_bottom_area.grid_rowconfigure(0, weight=1)
        frm_bottom_area.grid_rowconfigure(1, weight=1)
        frm_bottom_area.grid_columnconfigure(0, weight=1)

        # LabelFrame: Dynamic Groups Table
        self.dg_labelframe = ttk.LabelFrame(frm_bottom_area, text='Dynamic Groups Table')
        self.dg_labelframe.grid(row=0, column=0, sticky='nsew', padx=2, pady=3)
        self.dg_labelframe.grid_columnconfigure(0, weight=1)
        self.dg_labelframe.grid_rowconfigure(0, weight=1)
        self.add_context_help(
            self.dg_labelframe,
            'Shows list of Dynamic Groups in tenancy. Select to view matching policy statements below.',
        )

        # Dynamic Groups DataTable
        self.rp_dg_table = DataTable(
            self.dg_labelframe,
            columns=ALL_DG_COLUMNS,
            display_columns=BASIC_DG_COLUMNS,
            column_widths=DG_COLUMN_WIDTHS,
            data=[],
            selection_callback=rp_dg_selection_callback,
            multi_select=True,
        )
        self.rp_dg_table.grid(row=0, column=0, sticky='nsew')

        # LabelFrame: Resource Principals Policy Table
        self.rp_labelframe = ttk.LabelFrame(frm_bottom_area, text='Matching Policies Table')
        self.rp_labelframe.grid(row=1, column=0, sticky='nsew', padx=2, pady=3)
        self.rp_labelframe.grid_columnconfigure(0, weight=1)
        self.rp_labelframe.grid_rowconfigure(0, weight=1)
        self.add_context_help(
            self.rp_labelframe,
            'List of policy statements for chosen resource principals or dynamic group(s). Right-click for full policy details.',
        )

        # Policy Statements DataTable
        self.rp_policy_table = DataTable(
            self.rp_labelframe,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            row_context_menu_callback=policy_more_details_menu,
            selection_callback=rp_policy_selection_callback,
            multi_select=False,
        )
        self.rp_policy_table.grid(row=0, column=0, sticky='nsew')

        # Update the sheet
        self.update_principals_sheets()

        # Bind dropdown updates to sheet update
        self.principals_style_var.trace_add('write', self.update_principals_sheets)
        self.resource_type_var.trace_add('write', self.update_principals_sheets)
        # (text filter wired above)

    def update_principals_sheets(self, *args):
        """
        Update view: show or hide tables depending on dropdown, update data in both tables.

        - In DG mode, show both tables; in other principal modes, show only matching policy table, hiding DG table.
        - Refresh table data for all cases.
        - Text filter field applies to Matching Rule (DG) or Policy Statement (any-user modes).
        """
        principals_style = self.principals_style_var.get()
        resource_type = self.resource_type_var.get()
        search_text = (self.text_filter_var.get() or '').strip().lower()

        # Enable/disable dropdowns as needed
        self.resource_type_dropdown.configure(state='normal')
        self.principals_style_dropdown.configure(state='normal')

        # Always hide both, then re-grid appropriately
        self.dg_labelframe.grid_remove()
        self.rp_labelframe.grid_remove()

        if principals_style in ('any-user', 'any-group', 'any-user / any-group'):
            self.resource_type_dropdown.configure(state='normal')
            self.rp_labelframe.grid(row=0, column=0, rowspan=2, sticky='nsew')
            logger.info(f'{principals_style} selected - only showing Policy table with resource dropdown')

            # Determine subjects to filter on
            if principals_style == 'any-user':
                subjects = ['any-user']
            elif principals_style == 'any-group':
                subjects = ['any-group']
            else:  # 'any-user / any-group'
                subjects = ['any-user', 'any-group']

            if resource_type == 'Any':
                filters: PolicySearch = PolicySearch(subject=subjects)
                policies: list[RegularPolicyStatement] = self.policy_repo.filter_policy_statements(filters=filters)
            else:
                filters: PolicySearch = PolicySearch(subject=subjects, statement_text=[resource_type])
                policies = self.policy_repo.filter_policy_statements(filters=filters)

            display_data = [for_display_policy(statement) for statement in policies]
            # Apply text filter to "Statement Text"
            if search_text:
                display_data = [row for row in display_data if search_text in (row.get('Statement Text') or '').lower()]
            self.rp_policy_table.update_data(display_data)
            logger.info(
                f'Filtered to {len(display_data)} policies with principals: {subjects} filtering by resource: {resource_type}'
            )

        elif principals_style == 'Dynamic Group':
            self.resource_type_dropdown.configure(state='disabled')
            self.dg_labelframe.grid(row=0, column=0, sticky='nsew')
            self.rp_labelframe.grid(row=1, column=0, sticky='nsew')
            logger.info('Showing Dynamic Groups and Policy tables')

            # Populate dynamic group table (apply text filter if set, to Matching Rule)
            filtered_dynamic_groups = self.policy_repo.filter_dynamic_groups(filters={})
            filtered_dynamic_groups = [for_display_dynamic_group(dg) for dg in filtered_dynamic_groups]
            if search_text:
                filtered_dynamic_groups = [
                    row for row in filtered_dynamic_groups if search_text in (row.get('Matching Rule') or '').lower()
                ]
            self.rp_dg_table.update_data(filtered_dynamic_groups)

        # In DG mode policy table is updated by DG selection; in other modes, filled above

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Update help area and style on global context help and font size change (from main.py).
        """
        BaseUITab.apply_settings(self, context_help=context_help, font_size=font_size)
