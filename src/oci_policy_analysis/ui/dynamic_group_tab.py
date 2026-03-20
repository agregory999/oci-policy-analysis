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

from oci_policy_analysis.common.helpers import for_display_dynamic_group, for_display_policy
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import DynamicGroup, DynamicGroupSearch, PolicySearch
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

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


class DynamicGroupsTab(BaseUITab):
    """
    Dynamic Groups Tab for OCI Policy Analysis UI.

    Browse, filter, and analyze dynamic groups and related policies.
    Select dynamic groups to reveal matching policy statements below.
    """

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text='Browse, filter, and analyze dynamic groups and related policies.\nSelect dynamic groups to see matching policy statements below.',
            page_help_link='/docs/build/html/usage.html#dynamic-groups-tab',
        )
        self.app = app
        self.policy_compartment_analysis = app.policy_compartment_analysis
        self._build_ui()

    def _build_ui(self):
        # Top Filter Area (LabelFrame)
        label_frm_filters = ttk.LabelFrame(self, text='Dynamic Group Filters')
        label_frm_filters.pack(fill='x', padx=10, pady=6)
        self.add_context_help(
            label_frm_filters,
            'Filter the list of dynamic groups by domain, name, or rule. Use | for OR logic in fields.',
        )

        def clear_dg_filters():
            for entry in [self.domain_filter_var, self.dg_name_var, self.dg_rule_var, self.dg_ocid_var]:
                entry.set('')
            self._update_dg_output()

        self.chk_show_instance_principals = tk.BooleanVar()
        self.chk_show_not_in_use = tk.BooleanVar()
        # Show all Data toggle parallels UsersTab behavior
        self.show_all_data_var = tk.BooleanVar()
        self.domain_filter_var = tk.StringVar()
        self.dg_name_var = tk.StringVar()
        self.dg_rule_var = tk.StringVar()
        # Dynamic Group OCID filter supports multi-value via | separator
        self.dg_ocid_var = tk.StringVar()

        frm_dg_filter = ttk.Frame(label_frm_filters)
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

        self.dg_btn_clear = ttk.Button(frm_dg_filter, text='Clear Filters', state=tk.DISABLED, command=clear_dg_filters)
        self.dg_btn_clear.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        # Dynamic Group OCID filter (supports | for OR semantics)
        ttk.Label(frm_dg_filter, text='DG OCID').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_ocid = ttk.Entry(
            frm_dg_filter,
            textvariable=self.dg_ocid_var,
            state=tk.DISABLED,
            width=40,
        )
        self.dg_entry_ocid.grid(row=3, column=1, columnspan=3, padx=5, pady=2, sticky='ew')

        # Output Filter Area (LabelFrame)
        label_frm_output = ttk.LabelFrame(self, text='Dynamic Group Output Filters')
        label_frm_output.pack(fill='x', padx=10, pady=0)
        self.add_context_help(
            label_frm_output, 'Customize which dynamic groups to show and control column output below.'
        )

        self.dg_label_statement_count = ttk.Label(label_frm_output, text='Dynamic Groups (Filtered):')
        self.dg_label_statement_count.grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky='w')

        ttk.Checkbutton(
            label_frm_output,
            text='Show Only Instance Principals',
            variable=self.chk_show_instance_principals,
            command=self._update_dg_output,
        ).grid(row=0, column=2, padx=5, pady=2)
        ttk.Checkbutton(
            label_frm_output,
            text='Show Only Unused Dynamic Groups',
            variable=self.chk_show_not_in_use,
            command=self._update_dg_output,
        ).grid(row=0, column=3, padx=5, pady=2)
        self.dg_show_all_data_chkbtn = ttk.Checkbutton(
            label_frm_output,
            text='Show all Data',
            variable=self.show_all_data_var,
            command=self.set_show_all_data,
        )
        self.dg_show_all_data_chkbtn.grid(row=0, column=4, padx=5, pady=2)
        self.add_context_help(
            self.dg_show_all_data_chkbtn,
            'Toggle to show additional ID/OCID and metadata columns for Dynamic Groups.\n'
            'When unchecked, only the most important summary fields are shown for a more compact view.',
        )

        # --- AI Assist Button (parallels policies_tab.py) ---
        self.ai_assist_btn = ttk.Button(
            label_frm_output,
            text='AI Assist',
            command=self._on_ai_assist_clicked,
            state=tk.DISABLED,
        )
        self.ai_assist_btn.grid(row=0, column=7, sticky='e', padx=(20, 8), pady=4)
        self.add_context_help(
            self.ai_assist_btn,
            'Show or hide the AI Assistant pane below to analyze dynamic groups and related policies.\nNOTE: AI must be enabled in Settings Tab.',
        )

        ttk.Separator(label_frm_output, orient=tk.VERTICAL).grid(row=0, column=5, sticky='ns', pady=2)
        self.label_policy_count = ttk.Label(label_frm_output, text='Policy Statements\n(Shown Below): 0')
        self.label_policy_count.grid(row=0, column=6, padx=5, pady=2)

        # Trace to update on change
        self.domain_filter_var.trace_add('write', lambda *args: self._update_dg_output())
        self.dg_name_var.trace_add('write', lambda *args: self._update_dg_output())
        self.dg_rule_var.trace_add('write', lambda *args: self._update_dg_output())
        self.dg_ocid_var.trace_add('write', lambda *args: self._update_dg_output())

        # Dynamic Groups Table Area (LabelFrame)
        label_frm_dynamicgroups = ttk.LabelFrame(self, text='Dynamic Groups Table')
        label_frm_dynamicgroups.pack(fill='both', expand=False, padx=5, pady=(8, 2))
        self.add_context_help(
            label_frm_dynamicgroups,
            'This table lists all discovered dynamic groups matching your filters. Select rows to see their matching policies below.',
        )

        def dg_selection_callback(selected_rows: list[dict]) -> None:
            dgs_for_filter = []
            for row in selected_rows:
                logger.info(f"Selected DG: {row.get('Domain')}, {row.get('DG Name')}")
                dgs_for_filter.append((row.get('Domain'), row.get('DG Name')))
            logger.info(f'DGs for filter: {dgs_for_filter}')
            exact_dg_filter: list[DynamicGroup] = [
                DynamicGroup(domain_name=dg[0], dynamic_group_name=dg[1]) for dg in dgs_for_filter
            ]  # type: ignore
            policy_filter: PolicySearch = PolicySearch(exact_dynamic_groups=exact_dg_filter)
            filtered = self.policy_compartment_analysis.filter_policy_statements(filters=policy_filter)
            filtered = [for_display_policy(stmt) for stmt in filtered]
            self.dg_policy_table.update_data(filtered)
            logger.info(f'Policies added to policy table: {len(filtered)}')
            self.label_policy_count.config(text=f'Statements Shown: {len(self.dg_policy_table.data)}')

        def dg_table_right_click(row_index: int) -> tk.Menu:
            dg_domain_ocid_text = self.custom_data_dynamic_group.data[row_index].get('Domain OCID')
            dg_ocid_text = self.custom_data_dynamic_group.data[row_index].get('DG OCID')
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label='Show Dynamic Group in logged-in Browser',
                command=lambda: self.app.open_link(
                    f'https://cloud.oracle.com/identity/domains/{dg_domain_ocid_text}/dynamic-groups/{dg_ocid_text}'
                ),
            )
            return menu

        self.custom_data_dynamic_group = DataTable(
            label_frm_dynamicgroups,
            columns=ALL_DG_COLUMNS,
            display_columns=BASIC_DG_COLUMNS,
            column_widths=DG_COLUMN_WIDTHS,
            data=[],
            selection_callback=dg_selection_callback,
            row_context_menu_callback=dg_table_right_click,
            multi_select=True,
        )
        self.custom_data_dynamic_group.pack(fill='both', expand=True, padx=0, pady=0)

        # Dynamic Group Policy Table Area (LabelFrame)
        label_frm_policies = ttk.LabelFrame(self, text='Policies Matching Selected Dynamic Groups')
        label_frm_policies.pack(fill='both', expand=True, padx=5, pady=(2, 12))
        self.add_context_help(
            label_frm_policies,
            'Shows policies applying to the selected dynamic groups. Right-click rows for details or jump to the Policies tab to analyze.',
        )

        def dg_policy_selection_callback(selected_rows: list[dict]) -> None:
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.app.policy_query_var.set(selected_statement)
                self.app.ai_additional_instructions = (
                    'Analyze the selected OCI policy statement.',
                    'Explain how the dynamic group must exist in the specified identity domain.  Show how the statement ',
                    'breaks down into its components such as action (allow or deny), subject, verb (read, inspect, use, manage), resource, locations,',
                    'conditions, and effective path. Explain its implications on, permissions within the',
                    'OCI environment.',
                )
                self.app.policy_query_label_text.set('DG Policy Statement\nInsights:')
                self.app.policy_query_var.set(selected_statement)

        def policy_more_details_menu(row_index: int) -> tk.Menu:
            menu = tk.Menu(self, tearoff=0)
            row_data = self.dg_policy_table.data[row_index]

            def switch_tab_policy_analysis():
                self.app.notebook.select(tab_id=2)  # Policy Analysis tab
                logger.info(f'Switching to Policy Analysis tab for policy: {row_data.get("Policy Name", "")}')
                self.app.policies_tab.chk_show_dynamic.set(True)
                self.app.policies_tab.policy_filter_var.set(row_data.get('Policy Name', ''))

            menu.add_command(
                label=f'View Full Policy ({row_data.get("Policy Name", "")})', command=switch_tab_policy_analysis
            )
            return menu

        self.dg_policy_table = DataTable(
            label_frm_policies,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            row_context_menu_callback=policy_more_details_menu,
            selection_callback=dg_policy_selection_callback,
            multi_select=False,
        )
        self.dg_policy_table.pack(fill='both', expand=True, padx=0, pady=0)

        # Context note for policy table
        context_note_lbl = ttk.Label(
            label_frm_policies, text='Right-click a policy for more details or jump to Policy Analysis tab.'
        )
        context_note_lbl.pack(anchor='w', padx=10, pady=(3, 0))
        self.add_context_help(
            context_note_lbl,
            'Right-click a row for more advanced policy analysis. Click to open in the Policies tab for deeper review.',
        )

    def _on_ai_assist_clicked(self):
        """Callback for AI Assist button - toggles the AI assistant (bottom) pane."""
        if hasattr(self.app, 'toggle_bottom'):
            self.app.toggle_bottom()
            logger.info('Dynamic Group Tab: AI Assist button clicked, toggled bottom pane.')

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
            dynamic_group_ocid=self.dg_ocid_var.get().split('|') if self.dg_ocid_var.get() else None,  # type: ignore[arg-type]
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

        # Sync display columns with Show all Data toggle
        self.set_show_all_data()

        # Update label with counts
        self.dg_label_statement_count.config(
            text=f'Dynamic Groups (Total): {len(self.policy_compartment_analysis.dynamic_groups)}\nDynamic Groups (Filtered): {len(output_filtered)}'
        )

    def set_show_all_data(self, checked: bool | None = None) -> None:
        """Sync table display columns with the *Show all Data* checkbox.

        If *checked* is provided, force the checkbox to that state. If
        *checked* is ``None``, rely on the current :class:`BooleanVar` value
        (used when invoked by the Checkbutton command, since Tkinter has
        already toggled it).
        """
        if checked is not None:
            self.show_all_data_var.set(checked)

        if hasattr(self, 'custom_data_dynamic_group') and self.custom_data_dynamic_group is not None:
            if self.show_all_data_var.get():
                self.custom_data_dynamic_group.set_display_columns(ALL_DG_COLUMNS)
                logger.debug('Setting dynamic group table to expanded view with all columns')
            else:
                self.custom_data_dynamic_group.set_display_columns(BASIC_DG_COLUMNS)
                logger.debug('Setting dynamic group table to basic view with key columns')

    def set_ocid_filter_and_search(self, ocids: list[str] | None) -> None:
        """Set the DG OCID filter from a list of OCIDs and refresh the table.

        Intended for cross-tab integrations (e.g., Policies tab right-click
        actions) to programmatically focus on one or more dynamic groups by
        OCID. OCIDs are joined with ``|`` to leverage existing OR semantics.
        """

        ocid_list = ocids or []
        self.dg_ocid_var.set('|'.join(ocid_list))
        self._update_dg_output()

    def populate_data(self) -> None:
        """Populate / refresh Dynamic Groups tab data after a load.

        This is the single entry point used by the main application after
        repository data is (re)loaded. It enables filter controls and refreshes
        the dynamic groups table using the current filter state.
        """

        self.enable_controls()

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Update context help and font settings (called globally from main app).
        """
        super().apply_settings(context_help, font_size)
        # Optionally propagate font size to main DataTable widgets if required.

    def enable_controls(self):
        """
        Called from main app when data is loaded to enable the controls
        """
        for entry in [self.dg_entry_domain, self.dg_entry_name, self.dg_entry_type, self.dg_entry_ocid]:
            entry.config(state=tk.NORMAL)
        for btn in [self.dg_btn_clear]:
            btn.config(state=tk.NORMAL)
        self._update_dg_output()
