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


class PoliciesTab(ttk.Frame):
    """Tab for displaying and filtering policies.
    Args:
        parent: The parent tkinter widget.
        app: The main application instance.
        policy_repo (PolicyCompartmentAnalysis): The policy data repository.
        settings: The application settings dictionary.
    Attributes:
        app: The main application instance.
        settings: The application settings dictionary.
        policy_repo (PolicyCompartmentAnalysis): The policy data repository.
        subject_filter_var: Tkinter StringVar for subject filter.
        use_subject_any: Tkinter BooleanVar for 'any-user/group' checkbox.
        verb_filter_var: Tkinter StringVar for verb filter.
        location_filter_var: Tkinter StringVar for location filter.
        resource_filter_var: Tkinter StringVar for resource filter.
        hierarchy_filter_var: Tkinter StringVar for hierarchy filter.
        condition_filter_var: Tkinter StringVar for condition filter.
        text_filter_var: Tkinter StringVar for text filter.
        effective_path_var: Tkinter StringVar for effective path filter.
        policy_filter_var: Tkinter StringVar for policy name filter.
        hierarchy_filter_root: Tkinter BooleanVar for 'tenancy root only' checkbox.
        location_filter_tenancy: Tkinter BooleanVar for 'in tenancy' checkbox.
        chk_show_service: Tkinter BooleanVar for showing service statements.
        chk_show_dynamic: Tkinter BooleanVar for showing dynamic group statements.
        chk_show_resource: Tkinter BooleanVar for showing resource statements.
        chk_show_invalid: Tkinter BooleanVar for showing invalid statements.
        chk_show_regular: Tkinter BooleanVar for showing regular statements.
        chk_show_expanded: Tkinter BooleanVar for showing expanded columns.
        tenancy_name_var: Tkinter StringVar for displaying tenancy name.
        label_policy_count: Tkinter Label for displaying count of filtered and shown statements.
        policy_table: DataTable instance for displaying policy statements.
    Methods:
        update_policy_output: Updates the policy output based on current filters.
        enable_widgets_after_load: Enables widgets after data load is complete.
        clear_policy_filters: Clears all policy filters.
        export_policy_to_csv: Exports filtered policy statements to a CSV file.
    """

    def __init__(self, parent, app, settings):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = app.policy_compartment_analysis

        # --- Page Help setup ---
        self.page_help_text = (
            'Search for policy statements based on multiple criteria.  '
            'To use logical OR add a pipe (|) character inside of a field.  '
            'Save a search or load from an existing search as necessary.   '
            'Displayed policy statements will have right-click options for deeper analysis depending on enabled functionality.'
        )
        self.page_help_frame = ttk.LabelFrame(self, text='Page Help')
        self.page_help_label = tk.Label(self.page_help_frame, anchor='w', justify='left', wraplength=900)
        self.page_help_label.pack(fill='x', padx=14, pady=5)

        self._apply_page_help_style()
        self.update_page_help_visibility()
        # Set default help text on initial load
        self.set_page_help_text(self.page_help_text)

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
        def _show_filters_help(_event=None):
            filter_help = (
                'Use these filter boxes to select policy statements by subject, verb, resource, location, etc. '
                'Fields accept single or multiple (| pipe-separated) values. Checkbox controls and dropdowns provide quick toggles. '
                'You can save, load, or clear filters as needed for customized policy analysis.'
            )
            self.set_page_help_text(filter_help)

        def _restore_default_page_help_filters(_event=None):
            self.set_page_help_text(self.page_help_text)

        self.label_frm_filters.bind('<Enter>', _show_filters_help)
        self.label_frm_filters.bind('<Leave>', _restore_default_page_help_filters)
        # NOTE: Not binding to all children for robustness. See docs for generic GUI event handling and alternatives.

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

        # Saved Search Name entry/label
        ttk.Label(self.label_frm_actions, text='Saved Search Name:').grid(
            row=1, column=0, columnspan=2, padx=5, pady=5, sticky='w'
        )
        self.saved_search_name_var = tk.StringVar()
        self.entry_saved_search_name = ttk.Entry(
            self.label_frm_actions, textvariable=self.saved_search_name_var, width=22
        )
        self.entry_saved_search_name.grid(row=2, column=0, padx=5, pady=5, sticky='ew')

        # Save Search button - binds to custom method
        self.btn_save_search = ttk.Button(self.label_frm_actions, text='Save Search', command=self._handle_save_search)
        self.btn_save_search.grid(row=2, column=1, padx=5, pady=5, sticky='ew')

        # Saved Searches ComboBox
        ttk.Label(self.label_frm_actions, text='Saved Searches:').grid(row=3, column=0, padx=5, pady=5, sticky='w')
        self.saved_searches_var = tk.StringVar()
        self.cb_saved_searches = ttk.Combobox(
            self.label_frm_actions, textvariable=self.saved_searches_var, state='readonly', width=22, values=[]
        )
        self.cb_saved_searches.grid(row=3, column=1, padx=5, pady=5, sticky='ew')
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

        # Action dropdown
        ttk.Label(self.frm_policy_filter, text='Action (allow|deny)').grid(row=5, column=4, padx=5, pady=2, sticky='w')
        action_combo = ttk.Combobox(
            self.frm_policy_filter,
            textvariable=self.action_filter_var,
            values=['Both', 'Allow', 'Deny'],
            state='readonly',
            width=10,
        )
        action_combo.grid(row=5, column=5, padx=2, sticky='w')
        action_combo.bind('<<ComboboxSelected>>', self.update_policy_output)

        # Clear Filters button
        self.btn_clear = ttk.Button(
            self.frm_policy_filter, text='Clear Filters', state=tk.DISABLED, command=self.clear_policy_filters
        )
        self.btn_clear.grid(row=5, column=6, columnspan=2, padx=5, pady=5, sticky='ew')

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
            filters['policy_compartment'] = (
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
            '|'.join(filters.get('policy_compartment', []))
            if 'policy_compartment' in filters and filters.get('policy_compartment') != ['ROOTONLY']
            else ''
        )
        self.condition_filter_var.set('|'.join(filters.get('conditions', [])) if 'conditions' in filters else '')
        self.text_filter_var.set('|'.join(filters.get('statement_text', [])) if 'statement_text' in filters else '')
        self.policy_filter_var.set('|'.join(filters.get('policy_name', [])) if 'policy_name' in filters else '')
        self.effective_path_var.set('|'.join(filters.get('effective_path', [])) if 'effective_path' in filters else '')
        # Handle booleans
        self.hierarchy_filter_root.set(bool(filters.get('policy_compartment') == ['ROOTONLY']))
        self.location_filter_tenancy.set(bool(filters.get('location') == ['tenancy']))
        # "Action" field already handled above
        self.chk_show_invalid.set(bool(filters.get('valid') is False))
        self.update_policy_output()

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
                filters['policy_compartment'] = (
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
        label_frm_output = ttk.LabelFrame(self, text='Output Filters')
        label_frm_output.pack(fill='both', padx=10, pady=10)

        # Page Help: Output section mouseover
        def _show_output_help(_event=None):
            output_help = (
                'The Output Filters area lets you change how policy statements are displayed in the table. '
                'Use the checkboxes to select which statement types to include or exclude, and examine counts of '
                'filtered/shown/total statements. Quickly identify which policies meet your analysis goals.'
            )
            self.set_page_help_text(output_help)

        def _restore_output_help(_event=None):
            self.set_page_help_text(self.page_help_text)

        label_frm_output.bind('<Enter>', _show_output_help)
        label_frm_output.bind('<Leave>', _restore_output_help)

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
                self.update_policy_output()

        def policy_table_right_click(row_index: int) -> tk.Menu:
            effective_path_text = self.policy_table.data[row_index].get('Effective Path')
            policy_ocid_text = self.policy_table.data[row_index].get('Policy OCID')
            logger.debug(f'Right click on row {row_index}. Row data: {self.policy_table.data[row_index]}')
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label=f'Show all Policies with same Effective Path ({effective_path_text})',
                command=lambda: perform_effective_path_search(effective_path_text or ''),
            )
            # If the policy statement contains a condition (not null), add a way to send that to the Condition Tester tab
            condition_text = self.policy_table.data[row_index].get('Conditions')
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
        def _show_policy_table_help(_event=None):
            logger.info('Showing policy table specific help text')
            new_help = (
                'This table displays policy statements according to the current filters. '
                'You can sort, filter, and select policy rows. Right-click on a statement for more analysis options '
                '(such as showing by effective path, opening policy in browser, or sending to the Condition Tester tab, if enabled).'
            )
            self.set_page_help_text(new_help)

        def _restore_default_page_help(_event=None):
            self.set_page_help_text(self.page_help_text)

        label_frm_policy_table.bind('<Enter>', _show_policy_table_help)
        label_frm_policy_table.bind('<Leave>', _restore_default_page_help)

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
        self.verb_filter_var.trace_add('write', self.update_policy_output)
        self.subject_filter_var.trace_add('write', self.update_policy_output)
        self.resource_filter_var.trace_add('write', self.update_policy_output)
        self.location_filter_var.trace_add('write', self.update_policy_output)
        self.hierarchy_filter_var.trace_add('write', self.update_policy_output)
        self.condition_filter_var.trace_add('write', self.update_policy_output)
        self.text_filter_var.trace_add('write', self.update_policy_output)
        self.policy_filter_var.trace_add('write', self.update_policy_output)
        self.effective_path_var.trace_add('write', self.update_policy_output)

    def update_policy_output(self, *args):  # noqa: C901
        """Update the policy output based on current filters."""
        if self.policy_repo and hasattr(self.policy_repo, 'tenancy_name'):
            self.tenancy_name_var.set(f'Tenancy:\n{self.policy_repo.tenancy_name}')
        else:
            self.tenancy_name_var.set('Please Load a Tenancy')

        # Build filter dict for new call to filter
        filters: PolicySearch = {}
        if self.subject_filter_var.get():
            filters['subject'] = self.subject_filter_var.get().split('|')
        # Action filter
        action_value = self.action_filter_var.get().lower()
        if action_value == 'allow':
            filters['action'] = ['allow']
        elif action_value == 'deny':
            filters['action'] = ['deny']
        else:  # both
            filters['action'] = ['allow', 'deny', 'unknown']

        # Verb filter
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
            filters['policy_compartment'] = (
                ['ROOTONLY'] if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get().split('|')
            )
        # Do not assign 'condition' key—it is not valid in PolicySearch, skip!
        if self.text_filter_var.get():
            filters['statement_text'] = self.text_filter_var.get().split('|')
        if self.policy_filter_var.get():
            filters['policy_name'] = self.policy_filter_var.get().split('|')
        if self.effective_path_var.get():
            filters['effective_path'] = self.effective_path_var.get().split('|')
        if self.condition_filter_var.get():
            filters['conditions'] = self.condition_filter_var.get().split('|')
            pass
        if self.chk_show_invalid.get():
            filters['valid'] = False
            logger.debug('Filtering for invalid policies only')

        logger.info(f'Applying policy filters: {filters}')
        filtered_statements = self.policy_repo.filter_policy_statements(filters=filters)
        logger.info(f'Filtered statements via JSON filter: {len(filtered_statements)}')

        # Apply additional filters for output
        normalized_statements = [for_display_policy(st) for st in filtered_statements]
        filtered_statements = normalized_statements

        # Open up all policy types if invalid is checked
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

        # If expanded is checked, show all columns no matter what
        if self.chk_show_expanded.get():
            self.policy_table.set_display_columns(ALL_POLICY_COLUMNS)
            logger.debug('Setting policy table to expanded view with all columns')

        # Determine which rows to show based on checkboxes
        rows_to_show: list = [
            st
            for st in filtered_statements
            if (
                self.chk_show_service.get()
                and st.get('Subject Type') == 'service'
                or self.chk_show_dynamic.get()
                and st.get('Subject Type') == 'dynamic-group'
                or self.chk_show_resource.get()
                and st.get('Subject Type') == 'resource'
                or self.chk_show_regular.get()
                and st.get('Subject Type') in ['group', 'any-user', 'any-group']
                or self.chk_show_invalid.get()
                and (not st.get('Valid') or not st.get('Parsed'))
            )
        ]
        self.label_policy_count.config(
            text=f'Statements (Filtered): {len(filtered_statements)}\nStatements (Shown): {len(rows_to_show)}\nTotal Policies: {len(self.policy_repo.policies)}'
        )
        # Populate Data Table
        logger.debug(rows_to_show)
        self.policy_table.update_data(rows_to_show)
        logger.info(f'Populating policy data table with {len(rows_to_show)} statements')

    def set_page_help_text(self, text, temporary=False):
        """
        Updates the content of the page help label if visible.
        """
        if self.settings.get('context_help', False):
            self.page_help_label.configure(text=text)
            # Optionally re-apply style for temporary changes (font etc)
            self._apply_page_help_style()

    def update_page_help_visibility(self):
        """
        Show or hide Page Help frame based on context_help setting, always keeping it pinned at the top.
        Should be called after settings['context_help'] changes.
        """
        # Hide first, then decide whether/how to show
        self.page_help_frame.pack_forget()
        if self.settings.get('context_help', False):
            children = self.winfo_children()
            # Find the first child that is currently packed (winfo_manager == 'pack')
            packed_target = None
            for child in children:
                try:
                    if child.winfo_manager() == 'pack':
                        packed_target = child
                        break
                except Exception:
                    continue
            if packed_target:
                self.page_help_frame.pack(fill='x', padx=10, pady=(10, 0), before=packed_target)
            else:
                self.page_help_frame.pack(fill='x', padx=10, pady=(10, 0))

    def _apply_page_help_style(self):
        """
        Enforce consistent look for Page Help (background/font) per theme and font size setting.
        Only sets style/background/font, not the text itself!
        """
        bg = self._get_style_background()
        self.page_help_frame.configure(style='Custom.TLabelframe')
        self.page_help_label.configure(bg=bg, font=self._get_help_font())

    def _get_help_font(self):
        """
        Retrieve font tuple for help label from settings.
        """
        font_size_map = {
            'Small': 9,
            'Medium': 11,
            'Large': 13,
            'Extra Large': 16,
        }
        size = font_size_map.get(self.settings.get('font_size', 'Medium'), 11)
        return ('TkDefaultFont', size)

    def _get_style_background(self):
        """
        Try to get a background color consistent with ttk theme.
        """
        s = ttk.Style()
        try:
            bg = s.lookup('TFrame', 'background')
            if not bg:
                raise ValueError
            return bg
        except Exception:
            # fallback
            return self.winfo_toplevel().cget('bg') if hasattr(self, 'winfo_toplevel') else '#f0f0f0'

    def refresh_context_help(self):
        """
        Public API: Call from settings tab or theme handler when help/frame status should update.
        """
        self._apply_page_help_style()
        self.update_page_help_visibility()

    def enable_widgets_after_load(self):
        """Enable widgets after load."""

        # Clear/export button
        self.btn_clear.configure(state='normal')
        self.btn_export_policy.configure(state='normal')
