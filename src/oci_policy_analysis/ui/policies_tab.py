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

import csv
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tkinter.messagebox as tkmessagebox
from tkinter import ttk
from typing import Literal, cast  # <-- ADD for type handling

from oci_policy_analysis.common import config
from oci_policy_analysis.common.helpers import for_display_policy
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import PolicySearch
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

# Column data for Custom Data Table
ALL_POLICY_COLUMNS = [
    'Action',
    'Policy Name',
    'Policy OCID',
    'Compartment OCID',
    'Policy Compartment',
    'Effective Path',
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
    'Conditions',
    'Comments',
    'Parsing Notes',
    'Creation Time',
    'Parsed',
]
BASIC_POLICY_COLUMNS = ['Action', 'Policy Name', 'Policy Compartment', 'Effective Path', 'Statement Text', 'Valid']
BASIC_INVALID_POLICY_COLUMNS = [
    'Action',
    'Policy Name',
    'Policy Compartment',
    'Statement Text',
    'Valid',
    'Invalid Reasons',
]
POLICY_COLUMN_WIDTHS = {
    'Action': 75,
    'Policy Name': 250,
    'Policy OCID': 450,
    'Compartment OCID': 450,
    'Policy Compartment': 250,
    'Statement Text': 700,
    'Valid': 80,
    'Invalid Reasons': 400,
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

# Global logger for this module
logger = get_logger(component='policies_tab')


class PoliciesTab(BaseUITab):
    """
    Tab for displaying and filtering OCI policies.

    - Supports searching and filtering by multiple criteria (OR via | character in fields).
    - Includes saved search/load, policy export, and summary displays.
    - Context help is unified and appears at the top, per app setting.
    - Provides right-click analysis and integration with other app tabs.
    """

    # All context help logic is now inherited from BaseUITab.

    def __init__(self, parent, app, settings):
        super().__init__(
            parent,
            default_help_text='Filter and analyze policy statements. Use | for OR logic in fields. Right-click rows for options.',
            page_help_link='/usage.html#policy-tab',
        )
        # Ensure BaseUITab.timed_step uses the policies_tab logger instead of falling back to base_tab
        self.logger = logger
        self.app = app
        self.settings = settings
        self.policy_repo = app.policy_compartment_analysis
        self.page_help_text = self.default_help_text
        # Set initial help visibility for startup, matching context_help setting
        self.show_help = self.settings.get('context_help', True)
        self.update_page_help_visibility()
        # Configure tab
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Parent frame for filter/action label frames, new grid layout
        top_frm = ttk.Frame(self)
        top_frm.pack(fill='x', padx=10, pady=10)

        # Variables for policy and output filters
        self.subject_filter_var = tk.StringVar()
        self.use_subject_any = tk.BooleanVar()
        self.verb_filter_var = tk.StringVar()
        self.action_filter_var = tk.StringVar(value='Both')
        self.location_filter_var = tk.StringVar()
        self.resource_filter_var = tk.StringVar()
        self.hierarchy_filter_var = tk.StringVar()
        self.condition_filter_var = tk.StringVar()
        self.text_filter_var = tk.StringVar()
        self.effective_path_var = tk.StringVar()
        self.policy_filter_var = tk.StringVar()
        self.hierarchy_filter_root = tk.BooleanVar()
        self.location_filter_tenancy = tk.BooleanVar()
        self.chk_show_service = tk.BooleanVar()
        self.chk_show_dynamic = tk.BooleanVar()
        self.chk_show_resource = tk.BooleanVar()
        self.chk_show_invalid = tk.BooleanVar()
        self.chk_show_regular = tk.BooleanVar(value=True)
        self.chk_show_expanded = tk.BooleanVar()

        # Policy Filters LabelFrame (left)
        self.label_frm_filters = ttk.LabelFrame(top_frm, text='Policy Filters - use | in fields for logical OR')
        self.label_frm_filters.grid(row=0, column=0, sticky='nsew', padx=(0, 20))

        # Bind mouse events for Page Help context switching in filters
        self.add_context_help(
            self.label_frm_filters,
            'All policy statements are displayed here. Filter policies by subject, verb, resource, location, and more. Use | for OR within each field. Save and restore searches using the controls on the right.',
        )

        # Filter Actions LabelFrame (right)
        self.label_frm_actions = ttk.LabelFrame(top_frm, text='Filter Actions')
        self.label_frm_actions.grid(row=0, column=1, sticky='nsew')
        top_frm.grid_rowconfigure(0, weight=1)
        top_frm.grid_columnconfigure(0, weight=1)
        top_frm.grid_columnconfigure(1, weight=1)

        # --- Filter Actions widgets ---

        # Export to CSV button
        self.btn_export_policy = ttk.Button(
            self.label_frm_actions,
            text='Export Filtered\nStatements to CSV',
            state=tk.DISABLED,
            command=self.export_policy_to_csv,
        )
        self.btn_export_policy.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky='ew')

        # ---- Reload Policy Data button ----
        self.btn_reload_policies = ttk.Button(
            self.label_frm_actions,
            text='Reload Policy Data',
            state=tk.DISABLED,
            command=self._handle_reload_policies,
        )
        self.btn_reload_policies.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky='ew')
        self.add_context_help(
            self.btn_reload_policies,
            (
                'Reload policies and compartment data directly from tenancy (using original authentication and recursion settings).\n'
                'Enabled only if current data was loaded from tenancy, not cache/compliance. IAM group, Dynamic Group, and User data are NOT reloaded.'
            ),
        )

        # Saved Search Name entry/label
        ttk.Label(self.label_frm_actions, text='Saved Search Name:').grid(
            row=2, column=0, columnspan=2, padx=5, pady=5, sticky='w'
        )
        self.saved_search_name_var = tk.StringVar()
        self.entry_saved_search_name = ttk.Entry(
            self.label_frm_actions, textvariable=self.saved_search_name_var, width=22
        )
        self.entry_saved_search_name.grid(row=3, column=0, padx=5, pady=5, sticky='ew')

        # Save Search button - binds to custom method
        self.btn_save_search = ttk.Button(self.label_frm_actions, text='Save Search', command=self._handle_save_search)
        self.btn_save_search.grid(row=3, column=1, padx=5, pady=5, sticky='ew')

        # Saved Searches ComboBox
        ttk.Label(self.label_frm_actions, text='Saved Searches:').grid(row=4, column=0, padx=5, pady=5, sticky='w')
        self.saved_searches_var = tk.StringVar()
        self.cb_saved_searches = ttk.Combobox(
            self.label_frm_actions, textvariable=self.saved_searches_var, state='readonly', width=22, values=[]
        )
        self.cb_saved_searches.grid(row=4, column=1, padx=5, pady=5, sticky='ew')
        self.cb_saved_searches.bind('<<ComboboxSelected>>', self._handle_restore_search)

        # Helper to adjust expandability if needed:
        self.label_frm_actions.grid_rowconfigure(5, weight=1)
        self.label_frm_actions.grid_columnconfigure(0, weight=1)

        # Build the UI for policy filters
        self._build_ui_policy_filters()

        # Build the policy output table
        self._build_ui_policy_output()

        # --- Saved Searches: persistence and UI population  ---
        # Initialize if not present
        if 'saved_policy_searches' not in self.settings or not isinstance(self.settings['saved_policy_searches'], list):
            self.settings['saved_policy_searches'] = []
        self._refresh_saved_searches_dropdown()

        # -- After UI is built, check if Reload button should be enabled
        self._update_reload_policy_button_state()

    def _build_ui_policy_filters(self):
        # All logic to build the policy filter frame moved to separate method for clarity
        self.frm_policy_filter = ttk.Frame(self.label_frm_filters)
        self.frm_policy_filter.grid(row=0, column=0, sticky='w', padx=10, pady=10)
        self.frm_policy_filter.columnconfigure([0, 7], weight=1)

        # Subject
        ttk.Label(self.frm_policy_filter, text='Subject').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.subject_filter_var, width=25).grid(
            row=1, column=1, columnspan=2, padx=2, sticky='w'
        )
        btn_any_user = ttk.Checkbutton(
            self.frm_policy_filter, text='any-user / any-group', variable=self.use_subject_any
        )
        btn_any_user.grid(row=1, column=3, padx=2, sticky='e')
        btn_any_user.config(
            command=lambda: (
                self.subject_filter_var.set('any-user|any-group')
                if self.use_subject_any.get()
                else self.subject_filter_var.set(''),
                self.update_policy_output(),
            )
        )

        # Verb
        ttk.Label(self.frm_policy_filter, text='Verb').grid(row=1, column=4, padx=5, pady=2, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.verb_filter_var, width=30).grid(
            row=1, column=5, columnspan=3, padx=5, pady=2, sticky='w'
        )

        # Resource
        ttk.Label(self.frm_policy_filter, text='Resource').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.resource_filter_var, width=40).grid(
            row=2, column=1, columnspan=3, padx=5, pady=2, sticky='w'
        )

        # Location
        ttk.Label(self.frm_policy_filter, text='Location').grid(row=2, column=4, padx=5, pady=2, sticky='w')
        entry_loc = ttk.Entry(self.frm_policy_filter, width=20, textvariable=self.location_filter_var)
        entry_loc.grid(row=2, column=5, columnspan=2, padx=2, sticky='w')
        btn_in_tenancy = ttk.Checkbutton(
            self.frm_policy_filter, text='in tenancy?', variable=self.location_filter_tenancy
        )
        btn_in_tenancy.grid(row=2, column=7, padx=2)
        btn_in_tenancy.config(
            command=lambda: (
                self.location_filter_var.set('tenancy')
                if self.location_filter_tenancy.get()
                else self.location_filter_var.set(''),
                self.update_policy_output(),
            )
        )

        # Hierarchy
        ttk.Label(self.frm_policy_filter, text='Hierarchy').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        entry_hierarchy = ttk.Entry(self.frm_policy_filter, width=25, textvariable=self.hierarchy_filter_var)
        entry_hierarchy.grid(row=3, column=1, columnspan=2, padx=5, pady=2, sticky='w')
        btn_root_only = ttk.Checkbutton(
            self.frm_policy_filter, text='Tenancy Root Only', variable=self.hierarchy_filter_root
        )
        btn_root_only.grid(row=3, column=3, padx=5, pady=2, sticky='e')
        btn_root_only.config(
            command=lambda: (
                self.hierarchy_filter_var.set('ROOTONLY')
                if self.hierarchy_filter_root.get()
                else self.hierarchy_filter_var.set(''),
                self.update_policy_output(),
            )
        )

        # Condition
        ttk.Label(self.frm_policy_filter, text='Condition').grid(row=3, column=4, padx=5, pady=2, sticky='w')
        entry_condition = ttk.Entry(self.frm_policy_filter, width=30, textvariable=self.condition_filter_var)
        entry_condition.grid(row=3, column=5, columnspan=3, padx=5, pady=2, sticky='w')

        # Text
        ttk.Label(self.frm_policy_filter, text='Text').grid(row=4, column=0, padx=5, pady=2, sticky='w')
        entry_text = ttk.Entry(self.frm_policy_filter, width=40, textvariable=self.text_filter_var)
        entry_text.grid(row=4, column=1, columnspan=3, padx=5, pady=2, sticky='w')

        # Policy Name
        ttk.Label(self.frm_policy_filter, text='Policy Name').grid(row=4, column=4, padx=5, pady=2, sticky='w')
        entry_policy = ttk.Entry(self.frm_policy_filter, textvariable=self.policy_filter_var, width=30)
        entry_policy.grid(row=4, column=5, columnspan=3, padx=5, pady=2, sticky='w')

        # Effective Path
        ttk.Label(self.frm_policy_filter, text='Effective Path').grid(row=5, column=0, padx=5, pady=2, sticky='w')
        effective_path_text = ttk.Entry(self.frm_policy_filter, width=40, textvariable=self.effective_path_var)
        effective_path_text.grid(row=5, column=1, columnspan=3, padx=5, pady=2, sticky='w')

        # Action dropdown (labels/controls on main row)
        ttk.Label(self.frm_policy_filter, text='Action (allow|deny)').grid(row=5, column=4, padx=5, pady=2, sticky='w')
        action_combo = ttk.Combobox(
            self.frm_policy_filter,
            textvariable=self.action_filter_var,
            values=['Both', 'Allow', 'Deny'],
            state='readonly',
            width=10,
        )
        action_combo.grid(row=5, column=5, padx=2, sticky='w')
        self.add_context_help(
            action_combo, "Select which policy actions to show: Both,\nonly 'allow', or only 'deny' statements."
        )
        action_combo.bind('<<ComboboxSelected>>', self.update_policy_output)

        # Doc link row below the labels/controls (use standardized doc-link style)
        self.create_doc_link_label(
            self.frm_policy_filter,
            text='What is Effective Path?',
            url=self.DOCROOT + '/architecture.html#policy-parsing',
            row=6,
            column=0,
            columnspan=4,
            padx=5,
            pady=(0, 4),
            sticky='w',
        )

        self.create_doc_link_label(
            self.frm_policy_filter,
            text='OCI Deny Policies Documentation',
            url='https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/denypolicies.htm',
            row=6,
            column=4,
            columnspan=2,
            padx=5,
            pady=(0, 4),
            sticky='w',
        )

        # Clear Filters button
        self.btn_clear = ttk.Button(
            self.frm_policy_filter, text='Clear Filters', state=tk.DISABLED, command=self.clear_policy_filters
        )
        self.btn_clear.grid(row=6, column=6, columnspan=2, padx=5, pady=5, sticky='ew')

    def _on_ai_assist_clicked(self):
        """Callback for AI Assist button. Toggles the AI (bottom) pane."""
        if hasattr(self.app, 'toggle_bottom'):
            self.app.toggle_bottom()
            logger.info('Policies Tab: AI Assist button clicked, toggled bottom pane.')

    def _update_reload_policy_button_state(self):
        """Enable or disable the reload button depending on whether reload is allowed."""
        allowed = False
        if hasattr(self, 'policy_repo'):
            repo = self.policy_repo
            if getattr(repo, 'policies_loaded_from_tenancy', False) and not getattr(
                repo, 'loaded_from_compliance_output', False
            ):
                allowed = True
        if hasattr(self, 'btn_reload_policies'):
            if allowed:
                self.btn_reload_policies['state'] = tk.NORMAL
            else:
                self.btn_reload_policies['state'] = tk.DISABLED

    def _handle_reload_policies(self):
        """Handler for Reload Policy Data button. Delegates actual reload+cache+UI to App."""
        if not (
            hasattr(self.policy_repo, 'policies_loaded_from_tenancy') and self.policy_repo.policies_loaded_from_tenancy
        ) or getattr(self.policy_repo, 'loaded_from_compliance_output', False):
            tkmessagebox.showwarning(
                'Not allowed',
                'Policy data can only be reloaded from tenancy (not cache/compliance). Please load from tenancy first.',
            )
            self._update_reload_policy_button_state()
            return
        try:
            self.configure(cursor='watch')
            self.update_idletasks()
            # Let App coordinate the reload, cache update, and UI refresh
            ok = False
            if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache'):
                ok = self.app.reload_policies_and_compartments_and_update_cache()
            self.configure(cursor='')
            if ok:
                tkmessagebox.showinfo(
                    'Policy Data Reloaded', 'Policies and compartments have been reloaded from tenancy.'
                )
            else:
                self._update_reload_policy_button_state()
                tkmessagebox.showerror(
                    'Reload Failed',
                    'Policy data reload from tenancy failed. See application logs for details.',
                )
        except Exception as e:
            self.configure(cursor='')
            self._update_reload_policy_button_state()
            tkmessagebox.showerror('Reload Failed', f'Reload failed due to error: {str(e)}')

    def _get_current_search_dict(self):  # noqa: C901
        # Build filter dict using update_policy_output convention
        filters: PolicySearch = {}
        if self.subject_filter_var.get():
            filters['subject'] = self.subject_filter_var.get().split('|')
        action_value = self.action_filter_var.get().lower()
        if action_value == 'allow':
            filters['action'] = ['allow']
        elif action_value == 'deny':
            filters['action'] = ['deny']
        else:
            filters['action'] = ['allow', 'deny', 'unknown']
        if self.verb_filter_var.get():
            allowed_verbs = {'inspect', 'read', 'use', 'manage'}
            verbs = [v for v in self.verb_filter_var.get().split('|') if v in allowed_verbs]
            if verbs:
                filters['verb'] = cast(list[Literal['inspect', 'read', 'use', 'manage']], verbs)
        if self.resource_filter_var.get():
            filters['resource'] = self.resource_filter_var.get().split('|')
        if self.location_filter_var.get():
            filters['location'] = self.location_filter_var.get().split('|')
        if self.hierarchy_filter_var.get():
            filters['compartment_path'] = (
                ['ROOTONLY'] if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get().split('|')
            )
        if self.text_filter_var.get():
            filters['statement_text'] = self.text_filter_var.get().split('|')
        if self.policy_filter_var.get():
            filters['policy_name'] = self.policy_filter_var.get().split('|')
        if self.effective_path_var.get():
            filters['effective_path'] = self.effective_path_var.get().split('|')
        if self.condition_filter_var.get():
            filters['conditions'] = self.condition_filter_var.get().split('|')
        if self.chk_show_invalid.get():
            filters['valid'] = False
        return filters

    def _handle_save_search(self):
        search_name = self.saved_search_name_var.get().strip()
        if not search_name:
            tkmessagebox.showwarning('Save Search', 'Please enter a name for the saved search.')
            return
        filters = self._get_current_search_dict()
        # Check for duplicate name
        found = next((s for s in self.settings['saved_policy_searches'] if s['name'] == search_name), None)
        if found:
            # Ask for overwrite
            if not tkmessagebox.askyesno('Save Search', f'A saved search named "{search_name}" exists. Overwrite?'):
                return
            found['filters'] = filters
        else:
            self.settings['saved_policy_searches'].append({'name': search_name, 'filters': filters})
        config.save_settings(self.settings)
        self._refresh_saved_searches_dropdown(selected=search_name)
        tkmessagebox.showinfo('Save Search', f'Search saved as "{search_name}".')

    def _refresh_saved_searches_dropdown(self, selected=None):
        names = [s['name'] for s in self.settings.get('saved_policy_searches', [])]
        self.cb_saved_searches['values'] = names
        if selected and selected in names:
            self.saved_searches_var.set(selected)
        elif not names:
            self.saved_searches_var.set('')
        elif self.saved_searches_var.get() not in names:
            self.saved_searches_var.set('')

    def _handle_restore_search(self, event=None):
        selected = self.saved_searches_var.get()
        if not selected:
            return
        found = next((s for s in self.settings['saved_policy_searches'] if s['name'] == selected), None)
        if not found:
            tkmessagebox.showwarning('Saved Search', f'Could not find saved search "{selected}".')
            return
        filters = found.get('filters', {})
        # Only update variables; leave all widget layout as built in __init__
        self.subject_filter_var.set('|'.join(filters.get('subject', [])) if 'subject' in filters else '')
        self.verb_filter_var.set('|'.join(filters.get('verb', [])) if 'verb' in filters else '')
        self.resource_filter_var.set('|'.join(filters.get('resource', [])) if 'resource' in filters else '')
        self.location_filter_var.set('|'.join(filters.get('location', [])) if 'location' in filters else '')
        self.hierarchy_filter_var.set(
            '|'.join(filters.get('compartment_path', []))
            if 'compartment_path' in filters and filters.get('compartment_path') != ['ROOTONLY']
            else ''
        )
        self.condition_filter_var.set('|'.join(filters.get('conditions', [])) if 'conditions' in filters else '')
        self.text_filter_var.set('|'.join(filters.get('statement_text', [])) if 'statement_text' in filters else '')
        self.policy_filter_var.set('|'.join(filters.get('policy_name', [])) if 'policy_name' in filters else '')
        self.effective_path_var.set('|'.join(filters.get('effective_path', [])) if 'effective_path' in filters else '')
        # Handle booleans
        self.hierarchy_filter_root.set(bool(filters.get('compartment_path') == ['ROOTONLY']))
        self.location_filter_tenancy.set(bool(filters.get('location') == ['tenancy']))
        # "Action" field already handled above
        self.chk_show_invalid.set(bool(filters.get('valid') is False))
        self.populate_data()
        self.populate_data()
        self.populate_data()

        # --- Remove old label_frm_actions and its .place() ---
        # Create the policy filter frame and all fields/buttons (restoring the original layout)

    def clear_policy_filters(self):
        # Clear all filters
        for entry in [
            self.subject_filter_var,
            self.verb_filter_var,
            self.resource_filter_var,
            self.location_filter_var,
            self.hierarchy_filter_var,
            self.condition_filter_var,
            self.text_filter_var,
            self.policy_filter_var,
            self.effective_path_var,
        ]:
            entry.set('')
        self.use_subject_any.set(False)
        self.location_filter_tenancy.set(False)
        self.hierarchy_filter_root.set(False)

        # Change the Saved Search dropdown to blank
        self.saved_searches_var.set('')
        self.update_policy_output()

    def export_policy_to_csv(self):  # noqa: C901
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
        if filepath:
            # TODO: Get filtered data from the table instead of re-filtering (and this is broken)
            # Build filter dict for new call to filter (mirroring update_policy_output)
            filters: PolicySearch = {}
            if self.subject_filter_var.get():
                filters['subject'] = self.subject_filter_var.get().split('|')
            # Action filter for export
            action_value = self.action_filter_var.get().lower()
            if action_value == 'allow':
                filters['action'] = ['allow']
            elif action_value == 'deny':
                filters['action'] = ['deny']
            else:  # both
                filters['action'] = ['allow', 'deny']
            if self.verb_filter_var.get():
                # restrict to only allowed values for verb
                allowed_verbs = {'inspect', 'read', 'use', 'manage'}
                verbs = [v for v in self.verb_filter_var.get().split('|') if v in allowed_verbs]
                if verbs:
                    filters['verb'] = cast(list[Literal['inspect', 'read', 'use', 'manage']], verbs)
            if self.resource_filter_var.get():
                filters['resource'] = self.resource_filter_var.get().split('|')
            if self.location_filter_var.get():
                filters['location'] = self.location_filter_var.get().split('|')
            if self.hierarchy_filter_var.get():
                filters['compartment_path'] = (
                    ['ROOTONLY'] if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get().split('|')
                )
            # Do not assign 'condition' key—it is not valid in PolicySearch, skip!
            if self.text_filter_var.get():
                filters['statement_text'] = self.text_filter_var.get().split('|')
            if self.policy_filter_var.get():
                filters['policy_name'] = self.policy_filter_var.get().split('|')
            if self.effective_path_var.get():
                filters['effective_path'] = self.effective_path_var.get().split('|')
            if self.chk_show_invalid.get():
                filters['valid'] = False
                logger.debug('Filtering for invalid policies only')

            filtered = self.policy_repo.filter_policy_statements(filters=filters)
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # writer.writerow(self.sheet_policies.headers())
                # Write header row
                writer.writerow(ALL_POLICY_COLUMNS)
                # Write data rows
                for row in filtered:
                    writer.writerow(row.values())
            logger.info(f'Exported {len(filtered)} policy statements to {filepath}')
            tkmessagebox.showinfo('Export Complete', f'Exported {len(filtered)} policy statements to {filepath}')

    def _build_ui_policy_output(self):  # noqa: C901
        # Display Options label frame (with AI Assist button inside)
        label_frm_output = ttk.LabelFrame(self, text='Display Options')
        label_frm_output.pack(fill='x', padx=10, pady=(10, 0))

        # Page Help: Output section mouseover
        self.add_context_help(
            label_frm_output,
            'Customize which statement types to show and see result counts. Expand/collapse output as needed.',
        )

        # Ensure tenancy_name_var is always initialized before update_policy_output can ever be called
        if not hasattr(self, 'tenancy_name_var'):
            self.tenancy_name_var = tk.StringVar()
        ttk.Label(label_frm_output, textvariable=self.tenancy_name_var).grid(row=0, column=0, padx=5, pady=3)
        ttk.Separator(label_frm_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        self.label_policy_count = ttk.Label(label_frm_output, text='Statements (Filtered): 0')
        self.label_policy_count.grid(row=0, column=2, padx=5, pady=3, sticky='w')

        ttk.Separator(label_frm_output, orient=tk.VERTICAL).grid(row=0, column=3, padx=5, pady=3)
        # Display Output Selection
        ttk.Label(label_frm_output, text='Statement Type\nto display:').grid(row=0, column=4, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Service', variable=self.chk_show_service, command=self.update_policy_output
        ).grid(row=0, column=5, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Dynamic Group', variable=self.chk_show_dynamic, command=self.update_policy_output
        ).grid(row=0, column=6, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Resource', variable=self.chk_show_resource, command=self.update_policy_output
        ).grid(row=0, column=7, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Regular', variable=self.chk_show_regular, command=self.update_policy_output
        ).grid(row=0, column=8, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Invalid Only', variable=self.chk_show_invalid, command=self.update_policy_output
        ).grid(row=0, column=9, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm_output, text='Parsed Output', variable=self.chk_show_expanded, command=self.update_policy_output
        ).grid(row=0, column=10, padx=5, pady=3)

        # AI Assist button inside Output Filters, anchored east/right
        self.ai_assist_btn = ttk.Button(
            label_frm_output, text='AI Assist', command=self._on_ai_assist_clicked, state=tk.DISABLED
        )
        self.ai_assist_btn.grid(row=0, column=11, sticky='e', padx=(20, 8), pady=4)
        self.add_context_help(
            self.ai_assist_btn,
            'Show or hide the AI Assistant pane below to analyze policies.\nNOTE: AI must be enabled in Settings Tab.',
        )

        def selection_callback(selected_rows: list[dict]) -> None:
            for row in selected_rows:
                logger.info(f"Selected policy statement: {row.get('Statement Text')}")
                # Update the policy box
                self.app.ai_additional_instructions = 'Analyze the selected OCI policy statement. Show how the statement breaks down into its components such as action, subject, verb, resource, conditions, and effective path. Explain its implications on permissions within the OCI environment.'
                self.app.policy_query_label_text.set('Policy Statement\nInsights:')
                self.app.policy_query_var.set(row.get('Statement Text'))

        def perform_effective_path_search(effective_path: str):
            # Only allow non-None values to avoid type errors
            if isinstance(effective_path, str) and effective_path:
                self.effective_path_var.set(effective_path)
                # Update the output
                self.populate_data()
                self.populate_data()
                self.populate_data()

        def policy_table_right_click(row_index: int) -> tk.Menu:  # noqa: C901
            effective_path_text = self.policy_table.data[row_index].get('Effective Path')
            policy_ocid_text = self.policy_table.data[row_index].get('Policy OCID')
            logger.debug(f'Right click on row {row_index}. Row data: {self.policy_table.data[row_index]}')
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label=f'Show all Policies with same Effective Path ({effective_path_text})',
                command=lambda: perform_effective_path_search(effective_path_text or ''),
            )

            # --- Add Show Groups for subject_type group-id ---
            row = self.policy_table.data[row_index]
            subject_type = row.get('Subject Type', '')
            if subject_type == 'group-id':

                def show_groups_callback() -> None:  # noqa: C901
                    """Show related groups on the Groups/Users tab for group-id subjects."""

                    # Step 1: Switch to Groups/Users tab
                    self.app.notebook.select(self.app.users_tab)

                    # Step 2: Enable "Show all Data" via shared helper
                    users_tab = self.app.users_tab
                    users_tab.set_show_all_data(True)

                    # Step 3: Select groups by OCIDs
                    ocid_list: list[str] = []
                    subject_value = row.get('Subject', [])
                    # Subject is a list of tuples with (None, OCID) for group-id type, so extract OCIDs accordingly
                    if isinstance(subject_value, list):
                        ocid_list = [ocid for _, ocid in subject_value if ocid]
                    elif isinstance(subject_value, str):
                        # If separated by | or comma, split accordingly
                        if '|' in subject_value:
                            ocid_list = [v.strip() for v in subject_value.split('|')]
                        elif ',' in subject_value:
                            ocid_list = [v.strip() for v in subject_value.split(',')]
                        elif subject_value.strip():
                            ocid_list = [subject_value.strip()]
                    if not ocid_list:
                        # Fallback: nothing to select, return early
                        return

                    # Step 4: lookup group dicts {'domain_name':..., 'group_name':...} for each OCID.
                    # Let _update_user_analysis_policy_output fill selected_groups_for_table for display.
                    group_dicts: list[dict] = []
                    groups = getattr(users_tab.policy_compartment_analysis, 'groups', [])
                    for ocid in ocid_list:
                        match = next((g for g in groups if g.get('group_ocid', '') == ocid), None)
                        if match:
                            group_dicts.append(
                                {
                                    'domain_name': match.get('domain_name') or 'Default',
                                    'group_name': match.get('group_name', ''),
                                }
                            )
                    if not group_dicts:
                        return

                    # Step 5: Call _update_user_analysis_policy_output to update selected_groups_for_table and table.
                    users_tab._update_user_analysis_policy_output(groups_for_filter=group_dicts, users_for_filter=None)

                    # Step 6: Visually select the corresponding rows in users_groups_table if possible
                    try:
                        table = users_tab.users_groups_table
                        data = getattr(table, 'data', [])
                        ocid_set = set(ocid_list)
                        # Find rows whose 'Group OCID' is in our list
                        matching_indices = [i for i, r in enumerate(data) if r.get('Group OCID', '') in ocid_set]
                        # Map from row index to item_id via table.data_map
                        item_ids = [
                            item for item, idx in getattr(table, 'data_map', {}).items() if idx in matching_indices
                        ]
                        # Visually select the matching items, replacing any current selection
                        if item_ids:
                            table.tree.selection_set(item_ids)
                            # Optionally, trigger the associated selection callback
                            if table.selection_callback:
                                selected_rows = [data[idx] for idx in matching_indices]
                                table.selection_callback(selected_rows)
                    except Exception as e:  # pragma: no cover - defensive UI aid
                        # Non-critical, log but don't interrupt main logic
                        logger.debug(f'Unable to set users_groups_table selection programmatically: {e}')

                menu.add_command(
                    label='Show Groups on Groups/Users Tab',
                    command=show_groups_callback,
                )

            # --- Add Show Dynamic Groups for subject_type dynamic-group-id ---
            if subject_type == 'dynamic-group-id':

                def show_dynamic_groups_callback() -> None:
                    """Show related dynamic groups on the Dynamic Groups tab for dynamic-group-id subjects."""

                    # Step 1: Switch to Dynamic Groups tab
                    self.app.notebook.select(self.app.dynamic_groups_tab)

                    # Step 2: Build OCID list from Subject field
                    ocid_list: list[str] = []
                    subject_value = row.get('Subject', [])
                    # Subject is typically a list of tuples like (None, OCID) for dynamic-group-id
                    if isinstance(subject_value, list):
                        try:
                            ocid_list = [ocid for _, ocid in subject_value if ocid]
                        except Exception:
                            # Fallback: try to interpret as flat list of OCIDs
                            ocid_list = [v for v in subject_value if isinstance(v, str) and v]
                    elif isinstance(subject_value, str):
                        if '|' in subject_value:
                            ocid_list = [v.strip() for v in subject_value.split('|') if v.strip()]
                        elif ',' in subject_value:
                            ocid_list = [v.strip() for v in subject_value.split(',') if v.strip()]
                        elif subject_value.strip():
                            ocid_list = [subject_value.strip()]

                    if not ocid_list:
                        return

                    # Step 3: Ensure all DG columns visible, then apply OCID filter
                    dg_tab = self.app.dynamic_groups_tab
                    if hasattr(dg_tab, 'set_show_all_data'):
                        dg_tab.set_show_all_data(True)
                    if hasattr(dg_tab, 'set_ocid_filter_and_search'):
                        dg_tab.set_ocid_filter_and_search(ocid_list)

                menu.add_command(
                    label='Show Dynamic Groups on Dynamic Groups Tab',
                    command=show_dynamic_groups_callback,
                )

            # If the policy statement contains a condition (not null), add a way to send that to the Condition Tester tab
            condition_text = row.get('Conditions')
            # Only show if condition tester tab is currently visible and advanced_tabs_visible is True
            is_condition_tester_visible = hasattr(self.app, 'condition_tester_tab') and self.app.advanced_tabs_visible
            if condition_text and condition_text != 'None' and is_condition_tester_visible:
                menu.add_command(
                    label='Test Condition in Condition Tester Tab',
                    command=lambda: (
                        self.app.condition_tester_tab.set_clause_text(condition_text),
                        self.app.open_condition_tester_with_condition(condition_text),
                    ),
                )
            menu.add_command(
                label='Show Policy in logged-in Browser',
                command=lambda: self.app.open_link(
                    f'https://cloud.oracle.com/identity/domains/policies/{policy_ocid_text}'
                ),
            )
            return menu

        label_frm_policy_table = ttk.LabelFrame(self, text='Filtered Policy Statements')

        # Bind mouse events for Page Help context switching
        self.add_context_help(
            label_frm_policy_table,
            'This table shows filtered policy statements. Right-click any row for advanced analysis options.',
        )

        # Use the Data Table here with fields
        self.policy_table = DataTable(
            label_frm_policy_table,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            selection_callback=selection_callback,
            row_context_menu_callback=policy_table_right_click,
            multi_select=True,
        )
        # self.policy_table.grid(row=0, column=0, sticky="nsew")
        self.policy_table.pack(fill='both', expand=True, padx=0, pady=0)
        label_frm_policy_table.pack(fill='both', expand=True, padx=5, pady=5)

        # Trace to update the output when any filter changes
        self.verb_filter_var.trace_add('write', self.populate_data)
        self.subject_filter_var.trace_add('write', self.populate_data)
        self.resource_filter_var.trace_add('write', self.populate_data)
        self.location_filter_var.trace_add('write', self.populate_data)
        self.hierarchy_filter_var.trace_add('write', self.populate_data)
        self.condition_filter_var.trace_add('write', self.populate_data)
        self.text_filter_var.trace_add('write', self.populate_data)
        self.policy_filter_var.trace_add('write', self.populate_data)
        self.effective_path_var.trace_add('write', self.populate_data)

    def populate_data(self, *args):  # noqa: C901
        """Populate the policy output using per-step timing ala BaseUITab.timed_step (sub-timings)."""

        def _set_tenancy_label():
            if self.policy_repo and hasattr(self.policy_repo, 'tenancy_name'):
                self.tenancy_name_var.set(f'Tenancy:\n{self.policy_repo.tenancy_name}')
            else:
                self.tenancy_name_var.set('Please Load a Tenancy')

        def _build_filters():  # noqa: C901
            filters: PolicySearch = {}
            if self.subject_filter_var.get():
                filters['subject'] = self.subject_filter_var.get().split('|')
            action_value = self.action_filter_var.get().lower()
            if action_value == 'allow':
                filters['action'] = ['allow']
            elif action_value == 'deny':
                filters['action'] = ['deny']
            else:
                filters['action'] = ['allow', 'deny', 'unknown']
            if self.verb_filter_var.get():
                allowed_verbs = {'inspect', 'read', 'use', 'manage'}
                verbs = [v for v in self.verb_filter_var.get().split('|') if v in allowed_verbs]
                if verbs:
                    filters['verb'] = cast(list[Literal['inspect', 'read', 'use', 'manage']], verbs)
            if self.resource_filter_var.get():
                filters['resource'] = self.resource_filter_var.get().split('|')
            if self.location_filter_var.get():
                filters['location'] = self.location_filter_var.get().split('|')
            if self.hierarchy_filter_var.get():
                filters['compartment_path'] = (
                    ['ROOTONLY'] if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get().split('|')
                )
            if self.text_filter_var.get():
                filters['statement_text'] = self.text_filter_var.get().split('|')
            if self.policy_filter_var.get():
                filters['policy_name'] = self.policy_filter_var.get().split('|')
            if self.effective_path_var.get():
                filters['effective_path'] = self.effective_path_var.get().split('|')
            if self.condition_filter_var.get():
                filters['conditions'] = self.condition_filter_var.get().split('|')
            if self.chk_show_invalid.get():
                filters['valid'] = False
                logger.debug('Filtering for invalid policies only')
            return filters

        def _log_filter_info(filters):
            logger.info(f'Applying policy filters: {filters}')

        def _filter_policy_statements(filters):
            return self.policy_repo.filter_policy_statements(filters=filters)

        def _log_count_after_filter(filtered_statements):
            logger.info(f'Filtered statements via JSON filter: {len(filtered_statements)}')

        def _normalize_for_display(stmts):
            return [for_display_policy(st) for st in stmts]

        def _configure_view_columns():
            if self.chk_show_invalid.get():
                self.policy_table.set_display_columns(BASIC_INVALID_POLICY_COLUMNS)
                self.chk_show_service.set(True)
                self.chk_show_dynamic.set(True)
                self.chk_show_resource.set(True)
                self.chk_show_regular.set(True)
                logger.debug('Setting policy table to expanded view with invalid columns and undo other output filters')
            else:
                self.policy_table.set_display_columns(BASIC_POLICY_COLUMNS)
                logger.debug('Setting policy table to expanded view with basic columns')
            if self.chk_show_expanded.get():
                self.policy_table.set_display_columns(ALL_POLICY_COLUMNS)
                logger.debug('Setting policy table to expanded view with all columns')

        def _apply_row_toggles(filtered_statements):
            """
            Efficient filter for display toggles.
            - Caches all toggle values in local variables (no per-row .get calls)
            - Only fetches 'Subject Type' once per row
            - Uses 'set' for regular subject types for fast membership test
            """
            show_service = self.chk_show_service.get()
            show_dynamic = self.chk_show_dynamic.get()
            show_resource = self.chk_show_resource.get()
            show_regular = self.chk_show_regular.get()
            show_invalid = self.chk_show_invalid.get()
            regular_types = {'group', 'group-id', 'any-user', 'any-group'}

            result = []
            for st in filtered_statements:
                stype = st.get('Subject Type')
                if (
                    (show_service and stype == 'service')
                    or (show_dynamic and stype in ('dynamic-group', 'dynamic-group-id'))
                    or (show_resource and stype == 'resource')
                    or (show_regular and stype in regular_types)
                    or (show_invalid and (not st.get('Valid') or not st.get('Parsed')))
                ):
                    result.append(st)
            return result

        def _update_count_labels(filtered_statements, rows_to_show):
            self.label_policy_count.config(
                text=f'Statements (Filtered): {len(filtered_statements)}\nStatements (Shown): {len(rows_to_show)}\nTotal Policies: {len(self.policy_repo.policies)}'
            )

        def _update_policy_table(rows_to_show):
            self.policy_table.update_data(rows_to_show)

        # === Main sub-steps timed via base class ===
        self.timed_step('set_tenancy_label', _set_tenancy_label)
        filters = self.timed_step('build_filters', _build_filters)
        self.timed_step('log_filter_info', lambda: _log_filter_info(filters))
        filtered_statements = self.timed_step('filter_policy_statements', lambda: _filter_policy_statements(filters))
        self.timed_step('log_count_after_filter', lambda: _log_count_after_filter(filtered_statements))
        filtered_statements = self.timed_step(
            'normalize_for_display', lambda: _normalize_for_display(filtered_statements)
        )
        self.timed_step('output_column_view_config', _configure_view_columns)
        rows_to_show = self.timed_step('apply_row_toggles', lambda: _apply_row_toggles(filtered_statements))
        self.timed_step('update_count_labels', lambda: _update_count_labels(filtered_statements, rows_to_show))
        self.timed_step('update_policy_table', lambda: _update_policy_table(rows_to_show))
        self.timed_step(
            'log_final_info', lambda: logger.info(f'Populating policy data table with {len(rows_to_show)} statements')
        )

    # Backward compatibility: keep update_policy_output (deprecated) for now
    def update_policy_output(self, *args, **kwargs):
        """[DEPRECATED] Use populate_data instead for sub-timing and improved logging."""
        return self.populate_data(*args, **kwargs)

    def enable_widgets_after_load(self):
        """Enable widgets after load."""

        # Clear/export button
        self.btn_clear.configure(state='normal')
        self.btn_export_policy.configure(state='normal')
        self._update_reload_policy_button_state()
