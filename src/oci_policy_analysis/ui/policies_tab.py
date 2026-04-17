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
        self.verb_filter_var = tk.StringVar()
        self.action_filter_var = tk.StringVar(value='Both')
        self.location_filter_var = tk.StringVar()
        self.resource_filter_var = tk.StringVar()
        self.permission_filter_var = tk.StringVar()
        self.hierarchy_filter_var = tk.StringVar()
        self.condition_filter_var = tk.StringVar()
        self.text_filter_var = tk.StringVar()
        self.effective_path_var = tk.StringVar()
        self.policy_filter_var = tk.StringVar()
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
        self.label_frm_actions.grid(row=0, column=1, sticky='ne')
        top_frm.grid_rowconfigure(0, weight=1)
        top_frm.grid_columnconfigure(0, weight=1)
        top_frm.grid_columnconfigure(1, weight=0)

        # --- Filter Actions widgets ---

        # Export to CSV button
        self.btn_export_policy = ttk.Button(
            self.label_frm_actions,
            text='Export Filtered Statements to CSV',
            state=tk.DISABLED,
            command=self.export_policy_to_csv,
        )
        self.btn_export_policy.grid(row=0, column=0, padx=5, pady=(5, 3), sticky='ew')

        # ---- Reload Policy Data button ----
        self.btn_reload_policies = ttk.Button(
            self.label_frm_actions,
            text='Reload Policy Data',
            state=tk.DISABLED,
            command=self._handle_reload_policies,
        )
        self.btn_reload_policies.grid(row=1, column=0, padx=5, pady=3, sticky='ew')
        self.add_context_help(
            self.btn_reload_policies,
            (
                'Reload policies and compartment data directly from tenancy (using original authentication and recursion settings).\n'
                'Enabled only if current data was loaded from tenancy, not cache/compliance. IAM group, Dynamic Group, and User data are NOT reloaded.'
            ),
        )

        # Saved Search Name entry/label
        ttk.Label(self.label_frm_actions, text='Saved Search Name:').grid(
            row=2, column=0, padx=5, pady=(6, 2), sticky='w'
        )
        self.saved_search_name_var = tk.StringVar()
        self.entry_saved_search_name = ttk.Entry(
            self.label_frm_actions, textvariable=self.saved_search_name_var, width=22
        )
        self.entry_saved_search_name.grid(row=3, column=0, padx=5, pady=2, sticky='ew')

        # Save Search button - binds to custom method
        self.btn_save_search = ttk.Button(self.label_frm_actions, text='Save Search', command=self._handle_save_search)
        self.btn_save_search.grid(row=4, column=0, padx=5, pady=(2, 6), sticky='ew')

        # Saved Searches ComboBox
        ttk.Label(self.label_frm_actions, text='Saved Searches:').grid(row=5, column=0, padx=5, pady=(2, 2), sticky='w')
        self.saved_searches_var = tk.StringVar()
        self.cb_saved_searches = ttk.Combobox(
            self.label_frm_actions, textvariable=self.saved_searches_var, state='readonly', width=22, values=[]
        )
        self.cb_saved_searches.grid(row=6, column=0, padx=5, pady=(2, 6), sticky='ew')
        self.cb_saved_searches.bind('<<ComboboxSelected>>', self._handle_restore_search)

        # Helper to adjust expandability if needed:
        self.label_frm_actions.grid_rowconfigure(7, weight=1)
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
        self.frm_policy_filter.grid(row=0, column=0, sticky='w', padx=2, pady=1)
        self.frm_policy_filter.columnconfigure([0, 7], weight=1)

        # Subject
        ttk.Label(self.frm_policy_filter, text='Subject').grid(row=1, column=0, padx=2, pady=1, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.subject_filter_var, width=30).grid(
            row=1, column=1, columnspan=2, padx=2, pady=1, sticky='w'
        )
        btn_any_user = ttk.Button(
            self.frm_policy_filter,
            text='Add any-user/group',
            width=16,
            command=lambda: self._append_filter_tokens(self.subject_filter_var, ['any-user', 'any-group']),
        )
        btn_any_user.grid(row=1, column=3, padx=2, pady=1, sticky='e')
        self.add_context_help(btn_any_user, 'Append any-user|any-group to Subject filter.')

        # Verb
        ttk.Label(self.frm_policy_filter, text='Verb').grid(row=1, column=4, padx=5, pady=1, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.verb_filter_var, width=24).grid(
            row=1, column=5, columnspan=2, padx=2, pady=1, sticky='w'
        )
        btn_add_lower_verbs = ttk.Button(
            self.frm_policy_filter,
            text='Add lower verbs',
            width=16,
            command=self._handle_add_lower_verbs,
        )
        btn_add_lower_verbs.grid(row=1, column=7, padx=2, pady=1, sticky='w')
        self.add_context_help(
            btn_add_lower_verbs,
            'Expand Verb to include lower verbs: use→inspect|read|use, read→inspect|read, manage→inspect|read|use|manage.',
        )

        # Permission (moved up under Verb)
        ttk.Label(self.frm_policy_filter, text='Permission').grid(row=2, column=4, padx=5, pady=1, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.permission_filter_var, width=24).grid(
            row=2, column=5, columnspan=2, padx=2, pady=1, sticky='w'
        )
        btn_lookup_permissions = ttk.Button(
            self.frm_policy_filter,
            text='Lookup Permissions',
            width=16,
            command=self._open_permission_lookup_popup,
        )
        btn_lookup_permissions.grid(row=2, column=7, padx=2, pady=1, sticky='w')
        self.add_context_help(
            btn_lookup_permissions,
            'Open a lookup popup to build Permission filter values from API operation '
            'or resource/family + verb mappings.',
        )

        # Resource
        ttk.Label(self.frm_policy_filter, text='Resource').grid(row=2, column=0, padx=2, pady=1, sticky='w')
        ttk.Entry(self.frm_policy_filter, textvariable=self.resource_filter_var, width=30).grid(
            row=2, column=1, columnspan=2, padx=2, pady=1, sticky='w'
        )
        btn_add_hierarchy = ttk.Button(
            self.frm_policy_filter,
            text='Add Hierarchy',
            width=16,
            command=self._handle_add_hierarchy_to_resource_filter,
        )
        btn_add_hierarchy.grid(row=2, column=3, padx=2, pady=1, sticky='e')
        self.add_context_help(
            btn_add_hierarchy,
            'Loads containing family (if any) and all-resources',
        )

        # Location
        ttk.Label(self.frm_policy_filter, text='Location').grid(row=3, column=4, padx=5, pady=1, sticky='w')
        entry_loc = ttk.Entry(self.frm_policy_filter, width=24, textvariable=self.location_filter_var)
        entry_loc.grid(row=3, column=5, columnspan=2, padx=2, pady=1, sticky='w')
        btn_in_tenancy = ttk.Button(
            self.frm_policy_filter,
            text='"in tenancy" only',
            width=16,
            command=lambda: self._set_filter_value(
                self.location_filter_var, f'tenancy|{getattr(self.app.policy_compartment_analysis, "tenancy_ocid", "")}'
            ),
        )
        btn_in_tenancy.grid(row=3, column=7, padx=2, pady=1, sticky='w')
        self.add_context_help(btn_in_tenancy, "Set Location filter to 'tenancy'.")

        # Hierarchy
        ttk.Label(self.frm_policy_filter, text='Hierarchy').grid(row=3, column=0, padx=2, pady=1, sticky='w')
        entry_hierarchy = ttk.Entry(self.frm_policy_filter, width=30, textvariable=self.hierarchy_filter_var)
        entry_hierarchy.grid(row=3, column=1, columnspan=2, padx=2, pady=1, sticky='w')
        btn_root_only = ttk.Button(
            self.frm_policy_filter,
            text='Add ROOTONLY',
            width=16,
            command=lambda: self._insert_filter_tokens(self.hierarchy_filter_var, ['ROOTONLY']),
        )
        btn_root_only.grid(row=3, column=3, padx=2, pady=1, sticky='e')
        self.add_context_help(btn_root_only, 'Insert ROOTONLY into Hierarchy filter.')

        # Condition
        ttk.Label(self.frm_policy_filter, text='Condition').grid(row=4, column=4, padx=5, pady=1, sticky='w')
        entry_condition = ttk.Entry(self.frm_policy_filter, width=24, textvariable=self.condition_filter_var)
        # Use columnspan=2 so we can place the Tag-based checkbox in column 7
        entry_condition.grid(row=4, column=5, columnspan=2, padx=2, pady=1, sticky='w')

        # Tag-based condition helper button
        btn_tag_based = ttk.Button(
            self.frm_policy_filter,
            text='Add .tag.',
            width=16,
            command=lambda: self._insert_filter_tokens(self.condition_filter_var, ['.tag.']),
        )
        btn_tag_based.grid(row=4, column=7, padx=2, pady=1, sticky='w')
        self.add_context_help(btn_tag_based, 'Insert .tag. into Condition filter.')

        # Text
        ttk.Label(self.frm_policy_filter, text='Text').grid(row=4, column=0, padx=2, pady=1, sticky='w')
        entry_text = ttk.Entry(self.frm_policy_filter, width=45, textvariable=self.text_filter_var)
        entry_text.grid(row=4, column=1, columnspan=3, padx=2, pady=1, sticky='w')

        # Policy Name
        ttk.Label(self.frm_policy_filter, text='Policy Name').grid(row=5, column=4, padx=5, pady=1, sticky='w')
        entry_policy = ttk.Entry(self.frm_policy_filter, textvariable=self.policy_filter_var, width=40)
        entry_policy.grid(row=5, column=5, columnspan=3, padx=2, pady=1, sticky='w')

        # Effective Path
        ttk.Label(self.frm_policy_filter, text='Effective Path').grid(row=5, column=0, padx=2, pady=1, sticky='w')
        effective_path_text = ttk.Entry(self.frm_policy_filter, width=30, textvariable=self.effective_path_var)
        effective_path_text.grid(row=5, column=1, columnspan=2, padx=2, pady=1, sticky='w')

        # Effective Path doc link (moved to right of field)
        self.create_doc_link_label(
            self.frm_policy_filter,
            text='What is Effective Path?',
            url=self.DOCROOT + '/architecture.html#policy-parsing',
            row=5,
            column=3,
            columnspan=1,
            padx=2,
            pady=1,
            sticky='w',
        )

        # Action dropdown (moved to a new left-side row)
        ttk.Label(self.frm_policy_filter, text='Action (allow|deny)').grid(row=6, column=0, padx=2, pady=1, sticky='w')
        action_combo = ttk.Combobox(
            self.frm_policy_filter,
            textvariable=self.action_filter_var,
            values=['Both', 'Allow', 'Deny'],
            state='readonly',
            width=10,
        )
        action_combo.grid(row=6, column=1, padx=2, pady=1, sticky='w')
        self.add_context_help(
            action_combo, "Select which policy actions to show: Both,\nonly 'allow', or only 'deny' statements."
        )
        action_combo.bind('<<ComboboxSelected>>', self.update_policy_output)

        # Doc link row (deny policy docs) to the right of Action controls
        self.create_doc_link_label(
            self.frm_policy_filter,
            text='OCI Deny Policies Docs',
            url='https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/denypolicies.htm',
            row=6,
            column=3,
            columnspan=3,
            padx=2,
            pady=1,
            sticky='w',
        )

        # Clear Filters button
        self.btn_clear = ttk.Button(
            self.frm_policy_filter, text='Clear Filters', state=tk.DISABLED, command=self.clear_policy_filters
        )
        self.btn_clear.grid(row=6, column=5, columnspan=3, padx=5, pady=1, sticky='ew')
        self.add_context_help(self.btn_clear, 'Clear all policy filter fields.')

    def _insert_filter_tokens(self, variable: tk.StringVar, tokens: list[str]) -> None:
        """Insert one or more `|`-separated tokens into a filter field.

        Preserves existing values and de-duplicates while keeping order.
        """

        existing = [t.strip() for t in variable.get().split('|') if t.strip()]
        updated = list(dict.fromkeys(existing + [t.strip() for t in tokens if t.strip()]))
        variable.set('|'.join(updated))
        self.update_policy_output()

    def _append_filter_tokens(self, variable: tk.StringVar, tokens: list[str]) -> None:
        """Append one or more tokens to a filter, preserving existing text.

        If existing value is present, appends as `|token1|token2`; otherwise
        sets `token1|token2`.
        """

        to_add = '|'.join([t.strip() for t in tokens if t.strip()])
        if not to_add:
            return
        current = variable.get().strip()
        variable.set(f'{current}|{to_add}' if current else to_add)
        self.update_policy_output()

    def _set_filter_value(self, variable: tk.StringVar, value: str) -> None:
        """Set a filter field to a specific value and refresh output."""

        variable.set(value)
        self.update_policy_output()

    def _handle_add_lower_verbs(self) -> None:
        """Expand Verb filter to include lower verbs for common OCI verb ladders."""

        current = self.verb_filter_var.get().strip().lower()
        mapping = {
            'read': 'inspect|read',
            'use': 'inspect|read|use',
            'manage': 'inspect|read|use|manage',
        }
        new_value = mapping.get(current)
        if new_value:
            self.verb_filter_var.set(new_value)
            self.update_policy_output()

    def _handle_add_hierarchy_to_resource_filter(self) -> None:
        """Expand the Resource filter with hierarchy tokens.

        Always includes `all-resources` and, for each resource token, attempts to
        include the containing family from reference data.
        """

        current = self.resource_filter_var.get().strip()
        raw_tokens = [t.strip() for t in current.split('|') if t.strip()]

        # Always include all-resources at the beginning per UX requirement.
        ordered_tokens: list[str] = ['all-resources']
        missing_family_for: list[str] = []

        ref_repo = getattr(self.app, 'reference_data_repo', None)
        family_map = getattr(ref_repo, 'family_name_map', {}) if ref_repo is not None else {}

        # If no input resource token exists, still apply all-resources.
        if not raw_tokens:
            self.resource_filter_var.set('all-resources')
            self.update_policy_output()
            return

        for token in raw_tokens:
            token_lc = token.lower()

            # Skip duplicates of all-resources from input.
            if token_lc == 'all-resources':
                continue

            # If user already entered a family token, preserve it as canonical.
            if token_lc in family_map:
                ordered_tokens.append(family_map[token_lc])
                continue

            family_name = None
            if ref_repo is not None and hasattr(ref_repo, 'get_containing_family'):
                family_name = ref_repo.get_containing_family(token)

            if family_name:
                ordered_tokens.append(family_name)
            else:
                missing_family_for.append(token)

            ordered_tokens.append(token)

        # De-duplicate while preserving order.
        deduped_tokens = list(dict.fromkeys(ordered_tokens))
        self.resource_filter_var.set('|'.join(deduped_tokens))
        self.update_policy_output()

        if missing_family_for:
            tkmessagebox.showwarning(
                'No Family Type Found',
                'No family types found for: '
                + ', '.join(missing_family_for)
                + '. Added all-resources and kept the provided resource values.',
            )

    def _merge_permissions_into_filter(self, permissions: list[str], *, refresh: bool = True) -> None:
        """Merge permissions into Permission filter using `|` delimiters.

        Existing values are preserved, new values are appended, and duplicates
        are removed while retaining the original order.
        """

        normalized_new = [str(p).strip().upper() for p in permissions if str(p).strip()]
        if not normalized_new:
            return
        existing = [t.strip() for t in self.permission_filter_var.get().split('|') if t.strip()]
        merged = list(dict.fromkeys(existing + normalized_new))
        self.permission_filter_var.set('|'.join(merged))
        if refresh:
            self.populate_data()

    def _open_permission_lookup_popup(self) -> None:
        """Open a popup that helps build the Permission filter value list."""

        existing = getattr(self, '_perm_lookup_popup', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        ref_repo = getattr(self.app, 'reference_data_repo', None)
        if ref_repo is None or not getattr(ref_repo, 'data', None):
            tkmessagebox.showwarning('Permissions Lookup', 'Reference permissions data is not loaded yet.')
            return

        popup = tk.Toplevel(self.winfo_toplevel())
        popup.title('Lookup Permissions')
        popup.transient(self.winfo_toplevel())
        popup.resizable(True, True)
        popup.geometry('880x616')
        try:
            popup_bg = ttk.Style().lookup('TFrame', 'background') or self.cget('background')
            if popup_bg:
                popup.configure(background=popup_bg)
        except Exception:
            pass
        self._perm_lookup_popup = popup

        self._perm_lookup_pending_perms: list[str] = []
        self._perm_lookup_api_filter_var = tk.StringVar()

        outer = ttk.Frame(popup)
        outer.pack(fill='both', expand=True, padx=10, pady=10)

        # --- API Operation lookup -------------------------------------------------
        frm_api = ttk.LabelFrame(outer, text='Lookup by API Operation')
        frm_api.pack(fill='x', pady=(0, 8))

        ttk.Label(frm_api, text='Search API Operation:').grid(row=0, column=0, padx=4, pady=4, sticky='w')
        self._perm_lookup_api_filter_entry = ttk.Entry(
            frm_api,
            textvariable=self._perm_lookup_api_filter_var,
            width=44,
        )
        self._perm_lookup_api_filter_entry.grid(row=0, column=1, padx=4, pady=4, sticky='we')

        ttk.Label(frm_api, text='API:Operation:').grid(row=1, column=0, padx=4, pady=4, sticky='w')
        self._perm_lookup_api_combo = ttk.Combobox(frm_api, state='readonly', width=70)
        self._perm_lookup_api_combo.grid(row=1, column=1, padx=4, pady=4, sticky='we')

        self._perm_lookup_add_api_btn = ttk.Button(
            frm_api,
            text='Add from API Operation',
            command=self._permission_lookup_add_from_api_operation,
        )
        self._perm_lookup_add_api_btn.grid(row=1, column=2, padx=4, pady=4, sticky='e')
        frm_api.grid_columnconfigure(1, weight=1)

        # --- Resource/family + verb lookup ---------------------------------------
        frm_res = ttk.LabelFrame(outer, text='Lookup by Resource or Family + Verb')
        frm_res.pack(fill='x', pady=(0, 8))

        ttk.Label(frm_res, text='Resource/Family:').grid(row=0, column=0, padx=4, pady=4, sticky='w')
        self._perm_lookup_resource_combo = ttk.Combobox(frm_res, width=44)
        self._perm_lookup_resource_combo.grid(row=0, column=1, padx=4, pady=4, sticky='we')

        ttk.Label(frm_res, text='Verb:').grid(row=0, column=2, padx=4, pady=4, sticky='w')
        self._perm_lookup_verb_combo = ttk.Combobox(
            frm_res,
            values=['inspect', 'read', 'use', 'manage'],
            state='readonly',
            width=10,
        )
        self._perm_lookup_verb_combo.grid(row=0, column=3, padx=4, pady=4, sticky='w')
        self._perm_lookup_verb_combo.set('read')

        self._perm_lookup_add_res_btn = ttk.Button(
            frm_res,
            text='Add from Resource/Family',
            command=self._permission_lookup_add_from_resource_or_family,
        )
        self._perm_lookup_add_res_btn.grid(row=0, column=4, padx=4, pady=4, sticky='e')
        frm_res.grid_columnconfigure(1, weight=1)

        # --- Lookup output and pending list --------------------------------------
        split = ttk.Frame(outer)
        split.pack(fill='both', expand=True)

        frm_result = ttk.LabelFrame(split, text='Lookup Result')
        frm_result.pack(side='left', fill='both', expand=True, padx=(0, 4))
        self._perm_lookup_result_text = tk.Text(frm_result, wrap=tk.WORD, height=14)
        self._perm_lookup_result_text.pack(fill='both', expand=True, padx=4, pady=4)

        frm_pending = ttk.LabelFrame(split, text='Permissions to Insert')
        frm_pending.pack(side='left', fill='both', expand=True, padx=(4, 0))
        self._perm_lookup_pending_listbox = tk.Listbox(frm_pending, selectmode=tk.EXTENDED, height=14)
        self._perm_lookup_pending_listbox.pack(fill='both', expand=True, padx=4, pady=4)

        pending_btns = ttk.Frame(frm_pending)
        pending_btns.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(pending_btns, text='Remove Selected', command=self._permission_lookup_remove_selected).pack(
            side='left', padx=(0, 6)
        )
        ttk.Button(pending_btns, text='Clear', command=self._permission_lookup_clear_pending).pack(side='left')

        # --- Footer actions -------------------------------------------------------
        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=(8, 0))

        ttk.Button(footer, text='Insert and Close', command=self._permission_lookup_commit_and_close).pack(
            side='right', padx=(6, 0)
        )
        ttk.Button(footer, text='Cancel', command=self._permission_lookup_cancel).pack(side='right')

        # Build API operation map
        self._perm_lookup_op_map: dict[str, tuple[str, dict]] = {}
        for api_name, ops in sorted(ref_repo.data.get('operations_by_api', {}).items()):
            if not isinstance(ops, dict):
                continue
            for op_name, meta in sorted(ops.items()):
                label = f'{api_name}:{op_name}'
                self._perm_lookup_op_map[label] = (op_name, meta if isinstance(meta, dict) else {})
        self._permission_lookup_update_api_combo()

        # Build resources/families list
        all_items = sorted(ref_repo.data.get('resources', {}).keys()) + [
            f'Family: {f}' for f in sorted(ref_repo.data.get('families', {}).keys())
        ]
        self._perm_lookup_resource_combo['values'] = all_items
        if all_items:
            self._perm_lookup_resource_combo.current(0)

        self._perm_lookup_api_filter_var.trace_add('write', self._permission_lookup_update_api_combo)
        popup.protocol('WM_DELETE_WINDOW', self._permission_lookup_commit_and_close)

    def _permission_lookup_update_api_combo(self, *_args) -> None:
        """Update API operation combobox from search text (case-insensitive)."""

        if not hasattr(self, '_perm_lookup_api_combo'):
            return
        filter_txt = (
            self._perm_lookup_api_filter_var.get() if hasattr(self, '_perm_lookup_api_filter_var') else ''
        ).strip()
        if not filter_txt:
            labels = sorted(self._perm_lookup_op_map.keys())
        else:
            needle = filter_txt.lower()
            labels = [label for label in sorted(self._perm_lookup_op_map.keys()) if needle in label.lower()]
        self._perm_lookup_api_combo['values'] = labels
        if labels:
            self._perm_lookup_api_combo.current(0)
        else:
            self._perm_lookup_api_combo.set('')

    def _permission_lookup_set_result_text(self, lines: list[str]) -> None:
        if not hasattr(self, '_perm_lookup_result_text'):
            return
        self._perm_lookup_result_text.delete(1.0, tk.END)
        self._perm_lookup_result_text.insert(tk.END, '\n'.join(lines))

    def _permission_lookup_add_permissions(self, perms: list[str], source_label: str) -> None:
        """Add permissions to pending list, de-duplicated, and update result details."""

        clean = [str(p).strip().upper() for p in perms if str(p).strip()]
        clean_sorted = sorted(set(clean))
        if not clean_sorted:
            self._permission_lookup_set_result_text(
                [
                    f'--- {source_label} ---',
                    '',
                    'Permissions (0):',
                    '  (none)',
                ]
            )
            return

        self._perm_lookup_pending_perms = list(dict.fromkeys(self._perm_lookup_pending_perms + clean_sorted))
        self._permission_lookup_refresh_pending_listbox()

        lines = [f'--- {source_label} ---', '', f'Permissions ({len(clean_sorted)}):']
        lines.extend([f'  {p}' for p in clean_sorted])
        self._permission_lookup_set_result_text(lines)

    def _permission_lookup_add_from_api_operation(self) -> None:
        """Lookup operation permissions and add them to pending list."""

        selected = self._perm_lookup_api_combo.get() if hasattr(self, '_perm_lookup_api_combo') else ''
        if not selected or selected not in self._perm_lookup_op_map:
            tkmessagebox.showwarning('Permissions Lookup', 'Select an API operation first.')
            return

        op_name, meta = self._perm_lookup_op_map[selected]
        perms = [str(p).upper() for p in meta.get('permissions', [])] if isinstance(meta, dict) else []
        self._permission_lookup_add_permissions(perms, f'API Operation: {op_name}')

    def _permission_lookup_add_from_resource_or_family(self) -> None:
        """Lookup resource/family + verb permissions and add to pending list."""

        ref_repo = getattr(self.app, 'reference_data_repo', None)
        if ref_repo is None:
            tkmessagebox.showwarning('Permissions Lookup', 'Reference permissions data is not loaded yet.')
            return

        sel = self._perm_lookup_resource_combo.get() if hasattr(self, '_perm_lookup_resource_combo') else ''
        verb = self._perm_lookup_verb_combo.get() if hasattr(self, '_perm_lookup_verb_combo') else ''
        if not sel or not verb:
            tkmessagebox.showwarning('Permissions Lookup', 'Select Resource/Family and Verb first.')
            return

        entity = sel.replace('Family: ', '') if sel.startswith('Family: ') else sel
        perms = ref_repo.get_permissions(entity, verb)
        self._permission_lookup_add_permissions(perms or [], f'{sel} | verb: {verb}')

    def _permission_lookup_refresh_pending_listbox(self) -> None:
        if not hasattr(self, '_perm_lookup_pending_listbox'):
            return
        self._perm_lookup_pending_listbox.delete(0, tk.END)
        for perm in self._perm_lookup_pending_perms:
            self._perm_lookup_pending_listbox.insert(tk.END, perm)

    def _permission_lookup_remove_selected(self) -> None:
        """Remove selected permissions from pending list."""

        if not hasattr(self, '_perm_lookup_pending_listbox'):
            return
        indices = list(self._perm_lookup_pending_listbox.curselection())
        if not indices:
            return
        to_remove = {self._perm_lookup_pending_listbox.get(i) for i in indices}
        self._perm_lookup_pending_perms = [p for p in self._perm_lookup_pending_perms if p not in to_remove]
        self._permission_lookup_refresh_pending_listbox()

    def _permission_lookup_clear_pending(self) -> None:
        self._perm_lookup_pending_perms = []
        self._permission_lookup_refresh_pending_listbox()

    def _permission_lookup_commit_and_close(self) -> None:
        """Insert pending permissions into filter and close popup."""

        if getattr(self, '_perm_lookup_pending_perms', []):
            self._merge_permissions_into_filter(self._perm_lookup_pending_perms, refresh=True)
        popup = getattr(self, '_perm_lookup_popup', None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        self._perm_lookup_popup = None

    def _permission_lookup_cancel(self) -> None:
        """Close popup without inserting pending permissions."""

        popup = getattr(self, '_perm_lookup_popup', None)
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        self._perm_lookup_popup = None

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
        if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache_async'):
            self.app.reload_policies_and_compartments_and_update_cache_async(
                callback={
                    'complete': lambda success, message, is_error: (
                        self._update_reload_policy_button_state(),
                        logger.info('Policy reload completion: success=%s message=%s', success, message),
                    )
                },
                show_popup=True,
            )
            return

        # Fallback to legacy synchronous path if async API is unavailable.
        try:
            self.configure(cursor='watch')
            self.update_idletasks()
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
        if self.permission_filter_var.get():
            filters['permission'] = self.permission_filter_var.get().split('|')
        if self.location_filter_var.get():
            filters['location'] = self.location_filter_var.get().split('|')
        if self.hierarchy_filter_var.get():
            filters['compartment_path'] = self.hierarchy_filter_var.get().split('|')
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
        self.permission_filter_var.set('|'.join(filters.get('permission', [])) if 'permission' in filters else '')
        self.location_filter_var.set('|'.join(filters.get('location', [])) if 'location' in filters else '')
        self.hierarchy_filter_var.set(
            '|'.join(filters.get('compartment_path', [])) if 'compartment_path' in filters else ''
        )
        self.condition_filter_var.set('|'.join(filters.get('conditions', [])) if 'conditions' in filters else '')
        self.text_filter_var.set('|'.join(filters.get('statement_text', [])) if 'statement_text' in filters else '')
        self.policy_filter_var.set('|'.join(filters.get('policy_name', [])) if 'policy_name' in filters else '')
        self.effective_path_var.set('|'.join(filters.get('effective_path', [])) if 'effective_path' in filters else '')
        # "Action" field already handled above

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
            self.permission_filter_var,
            self.location_filter_var,
            self.hierarchy_filter_var,
            self.condition_filter_var,
            self.text_filter_var,
            self.policy_filter_var,
            self.effective_path_var,
        ]:
            entry.set('')

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
            if self.permission_filter_var.get():
                filters['permission'] = self.permission_filter_var.get().split('|')
            if self.location_filter_var.get():
                filters['location'] = self.location_filter_var.get().split('|')
            if self.hierarchy_filter_var.get():
                filters['compartment_path'] = self.hierarchy_filter_var.get().split('|')
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

        # Optional prospective statements toggle and editor button. These
        # are enabled only when the application exposes a
        # ProspectiveStatementsService for the active tenancy.
        self.show_prospective_var = tk.BooleanVar(value=False)

        def _on_toggle_prospective() -> None:
            """Callback when the Show Prospective checkbox is toggled.

            We simply re-populate the data table so that the latest
            prospective statements from the shared service are merged in
            (or removed) using the current filters.
            """

            logger.info('PoliciesTab: Show prospective toggle set to %s', self.show_prospective_var.get())
            # populate_data already pulls fresh data from the
            # ProspectiveStatementsService each time, so calling it here
            # ensures any newly-saved/parsed statements from the editor
            # window are immediately visible in the Policies tab.
            self.populate_data()

        show_prospective_chk = ttk.Checkbutton(
            label_frm_output,
            text='Show Prospective',
            variable=self.show_prospective_var,
            command=_on_toggle_prospective,
        )
        show_prospective_chk.grid(row=0, column=11, padx=(10, 2), pady=3)
        self.add_context_help(
            show_prospective_chk,
            'Toggle to include prospective (what-if) policy statements in the table, '
            'in addition to real tenancy policies. Prospective rows are prefixed with '
            '[Prospective] and may not participate fully in subject-based filters '
            '(they are not backed by separate prospective users/groups/dynamic groups).',
        )

        def _open_prospective_editor_from_policies() -> None:
            """Open the tenancy-scoped Prospective Editor window.

            We delegate to the main application, which owns the
            ProspectiveStatementsService and simulation engine. If the
            service is not available, a warning dialog is shown from the
            editor window itself.
            """

            from oci_policy_analysis.ui.prospective_editor_window import ProspectiveEditorWindow

            try:
                ProspectiveEditorWindow(self, self.app)
            except Exception as exc:  # pragma: no cover - defensive UI guard
                logger.warning('PoliciesTab: unable to open ProspectiveEditorWindow: %s', exc, exc_info=True)

        self.btn_open_prospective = ttk.Button(
            label_frm_output,
            text='Prospective Editor…',
            command=_open_prospective_editor_from_policies,
            state=tk.NORMAL,
        )
        self.btn_open_prospective.grid(row=0, column=12, sticky='e', padx=(12, 4), pady=4)
        self.add_context_help(
            self.btn_open_prospective,
            'Open the tenancy-scoped Prospective (what-if) Policy Editor. '
            'Prospective statements defined there will be evaluated alongside '
            'real tenancy policies during simulation.',
        )

        # AI Assist button inside Output Filters, anchored east/right
        self.ai_assist_btn = ttk.Button(
            label_frm_output, text='AI Assist', command=self._on_ai_assist_clicked, state=tk.DISABLED
        )
        self.ai_assist_btn.grid(row=0, column=13, sticky='e', padx=(20, 8), pady=4)
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
            policy_name_text = self.policy_table.data[row_index].get('Policy Name')
            logger.debug(f'Right click on row {row_index}. Row data: {self.policy_table.data[row_index]}')
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label='Show only this Policy',
                command=lambda: (
                    self.clear_policy_filters(),
                    self.policy_filter_var.set(str(policy_name_text or '')),
                    self.update_policy_output(),
                ),
            )
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
        self.permission_filter_var.trace_add('write', self.populate_data)
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
            if self.permission_filter_var.get():
                filters['permission'] = self.permission_filter_var.get().split('|')
            if self.location_filter_var.get():
                filters['location'] = self.location_filter_var.get().split('|')
            if self.hierarchy_filter_var.get():
                filters['compartment_path'] = self.hierarchy_filter_var.get().split('|')
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
            """Filter real tenancy policy statements using the repository helper."""

            return self.policy_repo.filter_policy_statements(filters=filters)

        def _build_prospective_statement_like_list() -> list[dict]:  # noqa: C901
            """Build a RegularPolicyStatement-like list from prospective records.

            This uses the shared ProspectiveStatementsService (if available) or,
            as a fallback, the simulation engine's get_prospective_statements().
            Each entry is shaped so that filter_policy_statements and
            for_display_policy can treat it like a regular statement.
            """

            prospective_like: list[dict] = []

            # Quick exit if the toggle is off
            if not getattr(self, 'show_prospective_var', None) or not self.show_prospective_var.get():
                return prospective_like

            service = getattr(self.app, 'prospective_service', None)
            engine = getattr(self.app, 'simulation_engine', None)

            raw_records: list[dict] = []
            try:
                if service is not None:
                    # ProspectiveStatementsService.list_all() returns
                    # ProspectiveStatementRecord objects; project them to
                    # simple dicts we can reshape.
                    for rec in service.list_all():
                        base = {
                            'compartment_path': getattr(rec, 'compartment_path', 'ROOT') or 'ROOT',
                            'description': getattr(rec, 'description', '') or '',
                            'statement_text': getattr(rec, 'statement_text', '') or '',
                            'parsed': getattr(rec, 'parsed', False),
                            'valid': getattr(rec, 'valid', False),
                            'invalid_reasons': list(getattr(rec, 'invalid_reasons', []) or []),
                        }
                        normalized = getattr(rec, 'normalized', None) or {}
                        if isinstance(normalized, dict):
                            base['normalized'] = normalized
                        raw_records.append(base)
                elif engine is not None and hasattr(engine, 'get_prospective_statements'):
                    raw_records = list(engine.get_prospective_statements() or [])
            except Exception:  # pragma: no cover - defensive guard
                logger.info('PoliciesTab: unable to build prospective list for Policies tab view', exc_info=True)
                raw_records = []

            if not raw_records:
                logger.info('PoliciesTab: no prospective records returned from service/engine')
                return prospective_like

            import hashlib

            tenancy_ocid = getattr(self.policy_repo, 'tenancy_ocid', None)

            logger.info(
                'PoliciesTab: building %d prospective records for Policies view (tenancy_ocid=%s)',
                len(raw_records),
                tenancy_ocid,
            )

            for pst in raw_records:
                stmt_text = (pst.get('statement_text') or '').strip()
                if not stmt_text:
                    continue

                comp_path = pst.get('compartment_path') or 'ROOT'
                desc = pst.get('description') or ''
                normalized = pst.get('normalized') or {}

                # Build a synthetic internal_id so that sorting and any
                # downstream debug logs have something stable to use.
                internal_id = hashlib.md5(
                    (stmt_text + '::prospective::' + comp_path).encode('utf-8'),
                ).hexdigest()

                # Seed a minimal RegularPolicyStatement-shaped dict. Any
                # normalized values present are overlaid below.
                rec: dict = {
                    'policy_name': desc or '[Prospective]',
                    'policy_ocid': '(prospective)',
                    'compartment_ocid': tenancy_ocid,
                    'compartment_path': comp_path,
                    'statement_text': stmt_text,
                    'creation_time': '',
                    'internal_id': internal_id,
                    'parsed': bool(pst.get('parsed')),
                    'valid': bool(pst.get('valid')),
                    'invalid_reasons': list(pst.get('invalid_reasons') or []),
                }

                if isinstance(normalized, dict):
                    # Only copy keys that are meaningful for filtering or
                    # display, leaving others untouched.
                    for key in (
                        'subject_type',
                        'subject',
                        'verb',
                        'resource',
                        'permission',
                        'conditions',
                        'effective_path',
                        'action',
                        'location_type',
                        'location',
                    ):
                        if key in normalized:
                            rec[key] = normalized[key]

                # Ensure an action is always present so the default
                # action filter (['allow', 'deny', 'unknown']) in
                # filter_policy_statements does not drop all
                # prospective statements when no explicit action was
                # parsed yet.
                if 'action' not in rec:
                    rec['action'] = 'allow'

                prospective_like.append(rec)

            logger.info(
                'PoliciesTab: built %d prospective RegularPolicyStatement-like records',
                len(prospective_like),
            )

            return prospective_like

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

            # If no type filters are enabled, hide all real statements but
            # still allow prospective rows (which have no Subject Type set)
            # to flow through. This supports the "Show Prospective only"
            # use case where Service/DG/Resource/Regular are all unchecked.
            if not any((show_service, show_dynamic, show_resource, show_regular, show_invalid)):
                result = [st for st in filtered_statements if not st.get('Subject Type')]
                logger.info(
                    'PoliciesTab: apply_row_toggles with all real-type toggles off; %d -> %d (prospective-only view)',
                    len(filtered_statements),
                    len(result),
                )
                return result

            result = []
            for st in filtered_statements:
                stype = st.get('Subject Type')

                if (
                    (show_service and stype == 'service')
                    or (show_dynamic and stype in ('dynamic-group', 'dynamic-group-id'))
                    or (show_resource and stype == 'resource')
                    or (show_regular and (stype in regular_types or not stype))
                    or (show_invalid and (not st.get('Valid') or not st.get('Parsed')))
                ):
                    result.append(st)
            logger.info(
                'PoliciesTab: apply_row_toggles reduced %d -> %d rows (service=%s, dynamic=%s, resource=%s, regular=%s, invalid=%s)',
                len(filtered_statements),
                len(result),
                show_service,
                show_dynamic,
                show_resource,
                show_regular,
                show_invalid,
            )
            return result

        def _update_count_labels(filtered_statements, rows_to_show, prospective_count: int = 0):
            """Update the summary label with counts.

            When prospective rows are included, show a separate line so users
            can see how many what-if statements are in the current filtered
            view.
            """

            base = [
                f'Statements (Filtered): {len(filtered_statements)}',
                f'Statements (Shown): {len(rows_to_show)}',
                f'Total Policies: {len(self.policy_repo.policies)}',
            ]
            if getattr(self, 'show_prospective_var', None) and self.show_prospective_var.get():
                base.insert(2, f'Prospective Statements (Shown): {prospective_count}')
            self.label_policy_count.config(text='\n'.join(base))

        def _update_policy_table(rows_to_show):
            self.policy_table.update_data(rows_to_show)

        # === Main sub-steps timed via base class ===
        self.timed_step('set_tenancy_label', _set_tenancy_label)
        filters = self.timed_step('build_filters', _build_filters)
        self.timed_step('log_filter_info', lambda: _log_filter_info(filters))

        # Real tenancy statements
        real_filtered = self.timed_step('filter_policy_statements', lambda: _filter_policy_statements(filters))
        self.timed_step('log_count_after_filter', lambda: _log_count_after_filter(real_filtered))

        # Optional prospective/what-if statements, filtered with the same JSON
        # criteria when the toggle is enabled.
        prospective_like = self.timed_step('build_prospective_like', _build_prospective_statement_like_list)
        prospective_filtered: list[dict] = []
        if prospective_like:
            logger.info(
                'PoliciesTab: filtering %d prospective statements with filters=%s',
                len(prospective_like),
                filters,
            )
            prospective_filtered = self.timed_step(
                'filter_prospective_statements',
                lambda: self.policy_repo.filter_policy_statements(filters=filters, statements=prospective_like),
            )
            logger.info(
                'PoliciesTab: %d prospective statements matched after filter',
                len(prospective_filtered),
            )

        # Normalize both sets for display and prefix prospective policy names
        real_display = self.timed_step('normalize_real', lambda: _normalize_for_display(real_filtered))
        prospective_display = self.timed_step(
            'normalize_prospective', lambda: _normalize_for_display(prospective_filtered)
        )

        for row in prospective_display:
            base_name = row.get('Policy Name') or '(unnamed prospective)'
            if not str(base_name).startswith('[Prospective]'):
                row['Policy Name'] = f'[Prospective] {base_name}'

        # Real rows first, then prospective rows so they appear at the end
        combined_display = real_display + prospective_display
        logger.info(
            'PoliciesTab: combined_display has %d rows (%d real, %d prospective). Sample prospective rows: %s',
            len(combined_display),
            len(real_display),
            len(prospective_display),
            [
                {
                    'Policy Name': r.get('Policy Name'),
                    'Subject Type': r.get('Subject Type'),
                    'Valid': r.get('Valid'),
                    'Parsed': r.get('Parsed'),
                }
                for r in prospective_display[:3]
            ],
        )

        self.timed_step('output_column_view_config', _configure_view_columns)
        rows_to_show = self.timed_step('apply_row_toggles', lambda: _apply_row_toggles(combined_display))
        self.timed_step(
            'update_count_labels',
            lambda: _update_count_labels(combined_display, rows_to_show, len(prospective_display)),
        )
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
