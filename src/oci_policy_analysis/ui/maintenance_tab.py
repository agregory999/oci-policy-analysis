##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# maintenance_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.common import config
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo

# Global logger for this module
logger = get_logger(component='maintenance')


class MaintenanceTab(ttk.Frame):
    # Document with multi-line google-style napoleon comments for the class with public methods
    """
    Maintenance Tab for OCI Policy Analysis UI.
    Provides cache management and permissions testing tools.
    Methods:
        __init__: Initializes the MaintenanceTab with UI components and callbacks.
        _refresh_maintenance_cache_list: (Internal) Refreshes the cache list display.
        _maintenance_remove_selected_cache: (Internal) Removes the selected cache entry.
        _maintenance_rename_selected_cache: (Internal) Renames the selected cache entry.
        _maintenance_preserve_selected_cache: (Internal) Toggles the preserve status of the selected cache entry.
        _maintenance_permissions_load_data: (Internal) Loads reference data for permissions testing.
        _maintenance_get_permission: (Internal) Retrieves permissions for the selected resource/family and verb.
        _maintenance_check_overlap: (Internal) Checks for overlap between two permission statements.
    """

    def __init__(self, parent, app, caching, settings):
        super().__init__(parent)
        self.app = app
        self.caching = caching
        self.settings = settings
        self.settings_tab = self.app.settings_tab  # Optional link for settings tab live refresh
        self.policies_tab = self.app.policies_tab  # Optional link to policies tab

        # -------- Maintenance UI Build (CACHE & SAVED SEARCHES, 50/50) ----------
        frm_top = ttk.LabelFrame(self, text='Cache & Saved Search Management')
        frm_top.pack(fill='x', padx=10, pady=10)

        frm_top_content = ttk.Frame(frm_top)
        frm_top_content.pack(fill='x', expand=True)

        # --- LEFT: Caches ---
        frm_cache = ttk.Frame(frm_top_content)
        frm_cache.pack(side='left', fill='both', expand=True, padx=(0, 8))

        cache_lbl = ttk.Label(frm_cache, text='Cache Entries', font=('TkDefaultFont', 10, 'bold'))
        cache_lbl.pack(anchor='nw', padx=3, pady=(2, 0))

        # Listbox of caches
        self.maintenance_cache_list = tk.Listbox(frm_cache, selectmode=tk.SINGLE, height=8, width=40)
        self.maintenance_cache_list.pack(side='left', padx=8, pady=6, fill='y')
        self._refresh_maintenance_cache_list()

        # Scrollbar for Listbox
        scroll = ttk.Scrollbar(frm_cache, orient='vertical', command=self.maintenance_cache_list.yview)
        self.maintenance_cache_list.config(yscrollcommand=scroll.set)
        scroll.pack(side='left', fill='y')

        # Buttons for cache ops
        btns_frm = ttk.Frame(frm_cache)
        btns_frm.pack(side='left', padx=5, fill='y')
        self.cache_remove_button = ttk.Button(
            btns_frm, text='Remove Selected', command=self._maintenance_remove_selected_cache
        )
        self.cache_remove_button.pack(pady=2)
        self.cache_rename_button = ttk.Button(
            btns_frm, text='Rename Selected', command=self._maintenance_rename_selected_cache
        )
        self.cache_rename_button.pack(pady=2)
        self.cache_preserve_button = ttk.Button(
            btns_frm, text='Toggle Preserve', command=self._maintenance_preserve_selected_cache
        )
        self.cache_preserve_button.pack(pady=2)

        # Feedback/status
        self.maintenance_status_var = tk.StringVar(value='')
        self.maintenance_status_label = ttk.Label(
            frm_cache, textvariable=self.maintenance_status_var, foreground='blue'
        )
        self.maintenance_status_label.pack(side='bottom', fill='x', pady=(4, 0))

        # --- RIGHT: Saved Searches ---
        frm_saved = ttk.Frame(frm_top_content)
        frm_saved.pack(side='left', fill='both', expand=True, padx=(8, 0))

        saved_lbl = ttk.Label(frm_saved, text='Saved Searches', font=('TkDefaultFont', 10, 'bold'))
        saved_lbl.pack(anchor='nw', padx=3, pady=(2, 0))

        self.saved_search_list = tk.Listbox(frm_saved, selectmode=tk.SINGLE, height=8, width=40)
        self.saved_search_list.pack(side='left', padx=8, pady=6, fill='y')
        # Example data for saved searches -- replace with real integration as needed
        self._refresh_saved_search_list()

        saved_scroll = ttk.Scrollbar(frm_saved, orient='vertical', command=self.saved_search_list.yview)
        self.saved_search_list.config(yscrollcommand=saved_scroll.set)
        saved_scroll.pack(side='left', fill='y')

        saved_btns_frm = ttk.Frame(frm_saved)
        saved_btns_frm.pack(side='left', padx=5, fill='y')
        self.saved_remove_button = ttk.Button(
            saved_btns_frm, text='Delete Selected', command=self._maintenance_remove_selected_search
        )
        self.saved_remove_button.pack(pady=2)
        self.saved_rename_button = ttk.Button(
            saved_btns_frm, text='Rename Selected', command=self._maintenance_rename_selected_search
        )
        self.saved_rename_button.pack(pady=2)
        # No preservation button for saved searches

        # Feedback label for saved search actions
        self.saved_search_status_var = tk.StringVar(value='')
        self.saved_search_status_label = ttk.Label(
            frm_saved, textvariable=self.saved_search_status_var, foreground='blue'
        )
        self.saved_search_status_label.pack(side='bottom', fill='x', pady=(4, 0))

        # -------- Maintenance UI Build (PERMISSIONS/OPERATIONS JSON VIEWERS) ----------
        frm_json_wrap = ttk.Frame(self)
        frm_json_wrap.pack(fill='x', padx=10, pady=(0, 5))

        # Permissions JSON (Raw/Debug)
        frm_json = ttk.LabelFrame(frm_json_wrap, text='Permissions JSON (Raw/Debug)')
        frm_json.pack(side='left', fill='both', expand=True, padx=(0, 4))

        self.json_text = ScrolledText(frm_json, height=10, width=70, wrap=tk.WORD)
        self.json_text.pack(pady=5, fill='both', expand=True)
        self._maintenance_display_json()
        # Removed Save JSON button

        # Operations JSON (Raw/Debug) to the right
        frm_ops_json = ttk.LabelFrame(frm_json_wrap, text='Operations JSON (Raw/Debug)')
        frm_ops_json.pack(side='left', fill='both', expand=True, padx=(4, 0))

        self.operations_json_text = ScrolledText(frm_ops_json, height=10, width=70, wrap=tk.WORD)
        self.operations_json_text.pack(pady=5, fill='both', expand=True)
        self._maintenance_display_operations_json()

        # -------- Main Maintenance UI Build (PERMISSIONS TESTER and API OPERATIONS TESTER side-by-side) ----------
        frm_testers_wrap = ttk.Frame(self)
        frm_testers_wrap.pack(fill='both', padx=10, pady=(0, 10), expand=True)

        # Permissions Viewer & Tests (LEFT)
        frm_permissions = ttk.LabelFrame(frm_testers_wrap, text='Permissions Viewer & Tests')
        frm_permissions.pack(side='left', fill='both', expand=True, padx=(0, 8))

        row0 = ttk.Frame(frm_permissions)
        row0.pack(fill='x', pady=2)
        ttk.Label(row0, text='Resource/Family:').pack(side='left', padx=2)
        self.permissions_resource_combo = ttk.Combobox(row0, width=30)
        self.permissions_resource_combo.pack(side='left')
        ttk.Label(row0, text='Verb:').pack(side='left', padx=2)
        self.permissions_verb_combo = ttk.Combobox(row0, values=['inspect', 'read', 'use', 'manage'], width=10)
        self.permissions_verb_combo.pack(side='left')
        ttk.Button(row0, text='Get Permissions', command=self._maintenance_get_permission).pack(side='left', padx=4)
        self.permissions_result_label = ttk.Label(frm_permissions, text='', wraplength=300, justify='left')
        self.permissions_result_label.pack(fill='x', pady=2, padx=2)

        sep = ttk.Separator(frm_permissions, orient='horizontal')
        sep.pack(fill='x', pady=4)
        overlap_stmt1 = ttk.Frame(frm_permissions)
        overlap_stmt1.pack(fill='x', pady=1)
        ttk.Label(overlap_stmt1, text='Stmt 1:').pack(side='left')
        self.permissions_res1_combo = ttk.Combobox(overlap_stmt1, width=20)
        self.permissions_res1_combo.pack(side='left')
        ttk.Label(overlap_stmt1, text='Verb:').pack(side='left')
        self.permissions_verb1_combo = ttk.Combobox(
            overlap_stmt1, values=['inspect', 'read', 'use', 'manage'], width=10
        )
        self.permissions_verb1_combo.pack(side='left')
        ttk.Label(overlap_stmt1, text='Action:').pack(side='left')
        self.permissions_action1_combo = ttk.Combobox(overlap_stmt1, values=['allow', 'deny'], width=8)
        self.permissions_action1_combo.set('allow')
        self.permissions_action1_combo.pack(side='left')

        overlap_stmt2 = ttk.Frame(frm_permissions)
        overlap_stmt2.pack(fill='x', pady=1)
        ttk.Label(overlap_stmt2, text='Stmt 2:').pack(side='left')
        self.permissions_res2_combo = ttk.Combobox(overlap_stmt2, width=20)
        self.permissions_res2_combo.pack(side='left')
        ttk.Label(overlap_stmt2, text='Verb:').pack(side='left')
        self.permissions_verb2_combo = ttk.Combobox(
            overlap_stmt2, values=['inspect', 'read', 'use', 'manage'], width=10
        )
        self.permissions_verb2_combo.pack(side='left')
        ttk.Label(overlap_stmt2, text='Action:').pack(side='left')
        self.permissions_action2_combo = ttk.Combobox(overlap_stmt2, values=['allow', 'deny'], width=8)
        self.permissions_action2_combo.set('allow')
        self.permissions_action2_combo.pack(side='left')

        ttk.Button(overlap_stmt2, text='Check Overlap', command=self._maintenance_check_overlap).pack(
            side='left', padx=12
        )

        self.permissions_overlap_text = tk.Text(frm_permissions, height=14, width=50, wrap=tk.WORD)
        self.permissions_overlap_text.pack(fill='both', padx=2, pady=2, expand=True)
        self._maintenance_permissions_load_data()

        # API Operations Tester (RIGHT)
        frm_ops_tester_lbl = ttk.LabelFrame(frm_testers_wrap, text='API Operations Tester')
        frm_ops_tester_lbl.pack(side='left', fill='both', expand=True, padx=(8, 0), ipadx=5)

        # --- API Operation Search/Filter ---
        ttk.Label(frm_ops_tester_lbl, text='API Operation:\n(Search and Select)').grid(
            row=0, column=0, sticky='w', padx=3, pady=2
        )

        self.apiop_filter_var = tk.StringVar()
        self.apiop_filter_entry = ttk.Entry(frm_ops_tester_lbl, textvariable=self.apiop_filter_var, width=42)
        self.apiop_filter_entry.grid(row=0, column=1, sticky='we', padx=3, pady=(2, 0))
        self.apiop_filter_entry.bind('<KeyRelease>', self._on_apiop_filter_change)

        self.apiop_combo = ttk.Combobox(frm_ops_tester_lbl, state='readonly', width=44)
        self.apiop_combo.grid(row=1, column=1, sticky='w', padx=3, pady=2)

        ttk.Label(frm_ops_tester_lbl, text='All Known Permissions:\n(Select multiple with Ctrl)').grid(
            row=2, column=0, sticky='nw', padx=3
        )
        self.apiop_perms_listbox = tk.Listbox(frm_ops_tester_lbl, selectmode='multiple', height=9, width=42)
        self.apiop_perms_listbox.grid(row=2, column=1, sticky='w', padx=3, pady=2)
        self.apiop_perms_listbox.bind('<<ListboxSelect>>', self._on_apiop_perm_select)

        # Permissions Selected (Preview)
        ttk.Label(frm_ops_tester_lbl, text='Selected Permissions:').grid(row=3, column=0, sticky='nw', padx=3)
        self.apiop_selectedperms_text = ScrolledText(
            frm_ops_tester_lbl, height=5, width=42, wrap=tk.WORD, state=tk.DISABLED, font=('Consolas', 10)
        )
        self.apiop_selectedperms_text.grid(row=3, column=1, padx=3, pady=(1, 3), sticky='we')

        self.apiop_check_btn = ttk.Button(frm_ops_tester_lbl, text='Check API', command=self._apiop_check)
        self.apiop_check_btn.grid(row=4, column=1, sticky='w', pady=(2, 2), padx=3)

        self.apiop_result_label = ttk.Label(frm_ops_tester_lbl, text='', width=20, font=('Consolas', 11, 'bold'))
        self.apiop_result_label.grid(row=4, column=0, sticky='e', padx=3)

        # Note label for operation-specific notes
        self.apiop_note_label = ttk.Label(
            frm_ops_tester_lbl,
            text='',
            wraplength=350,
            font=('TkDefaultFont', 9, 'italic'),
            foreground='slate gray',
            justify='left',
        )
        self.apiop_note_label.grid(row=5, column=0, columnspan=2, sticky='w', padx=3, pady=(6, 3))

        self._maintenance_ops_tester_load_data()

    def _refresh_saved_search_list(self):
        """Populate the saved searches Listbox using app settings (shared with policies tab)."""
        if 'saved_policy_searches' not in self.settings or not isinstance(self.settings['saved_policy_searches'], list):
            self.settings['saved_policy_searches'] = []
        self.saved_search_list.delete(0, tk.END)
        for search in self.settings['saved_policy_searches']:
            name = search.get('name', '')
            self.saved_search_list.insert(tk.END, name)

    def _maintenance_remove_selected_search(self):
        idx = self.saved_search_list.curselection()
        if not idx:
            self.saved_search_status_var.set('Select a saved search to delete.')
            return
        search_name = self.saved_search_list.get(idx[0])
        # Remove from settings
        found_index = next(
            (i for i, s in enumerate(self.settings['saved_policy_searches']) if s.get('name', '') == search_name), None
        )
        if found_index is not None:
            del self.settings['saved_policy_searches'][found_index]
            config.save_settings(self.settings)
            self._refresh_saved_search_list()
            self.saved_search_status_var.set(f'Removed "{search_name}"')
            # --- Update PoliciesTab saved search dropdown if present ---
            try:
                if getattr(self, 'app', None) and hasattr(self.app, 'policies_tab'):
                    self.app.policies_tab._refresh_saved_searches_dropdown()
            except Exception:
                pass
        else:
            self.saved_search_status_var.set('Name not found.')

    def _maintenance_rename_selected_search(self):
        idx = self.saved_search_list.curselection()
        if not idx:
            self.saved_search_status_var.set('Select a saved search to rename.')
            return
        search_name = self.saved_search_list.get(idx[0])
        new_name = simpledialog.askstring('Rename Saved Search', 'Enter new name:', initialvalue=search_name)
        if not new_name or new_name == search_name:
            self.saved_search_status_var.set('Rename cancelled or no change.')
            return
        # Check for duplicate name
        names = [s.get('name', '') for s in self.settings['saved_policy_searches']]
        if new_name in names:
            self.saved_search_status_var.set('Name already exists.')
            return
        # Find and update
        found = next((s for s in self.settings['saved_policy_searches'] if s.get('name', '') == search_name), None)
        if found:
            found['name'] = new_name
            config.save_settings(self.settings)
            self._refresh_saved_search_list()
            self.saved_search_status_var.set(f'Renamed to "{new_name}"')
        else:
            self.saved_search_status_var.set('Name not found.')

    def _maintenance_display_json(self):
        """Refresh the raw permissions JSON in the debug display."""
        import json

        if hasattr(self, '_ref_repo'):
            json_str = json.dumps(self._ref_repo.data, indent=2)
        else:
            try:
                # lazy-load repo if not loaded
                self._ref_repo = ReferenceDataRepo()
                json_str = json.dumps(self._ref_repo.data, indent=2)
            except Exception as ex:
                json_str = f'Error loading permissions data: {ex}'
        self.json_text.delete(1.0, tk.END)
        self.json_text.insert(tk.END, json_str)

    def _maintenance_display_operations_json(self):
        """Show operations_by_api JSON (API + Operations) in side panel."""
        import json

        if hasattr(self, '_ref_repo'):
            display_data = self._ref_repo.data.get('operations_by_api', {})
            json_str = json.dumps(display_data, indent=2)
        else:
            try:
                self._ref_repo = ReferenceDataRepo()
                json_str = json.dumps(self._ref_repo.data.get('operations_by_api', {}), indent=2)
            except Exception as ex:
                json_str = f'Error loading operations data: {ex}'
        self.operations_json_text.delete(1.0, tk.END)
        self.operations_json_text.insert(tk.END, json_str)

    def _maintenance_save_json(self):
        """Save not currently supported for reference data."""
        messagebox.showinfo('Not supported', 'Save operation is not supported for reference data in this UI.')

    def _refresh_maintenance_cache_list(self):
        """Populate the cache Listbox with available caches and their preserved status."""
        caches = self.caching.get_available_cache(None)
        self.maintenance_cache_list.delete(0, tk.END)
        # To show preserved/non-preserved, read cache_entries.json
        import json
        import os

        entries_path = os.path.join(str(self.caching.cache_dir), 'cache_entries.json')
        preserved_map = {}
        try:
            with open(entries_path, encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        key = f"{entry['tenancy_name']}_{entry['cache_date']}"
                        preserved_map[key] = entry.get('preserved', False)
                    except Exception:
                        continue
        except Exception:
            pass
        for cache in caches:
            preserved = preserved_map.get(cache, False)
            entry_str = f'🛡️ {cache}' if preserved else f'{cache}'
            self.maintenance_cache_list.insert(tk.END, entry_str)

    def _maintenance_remove_selected_cache(self):
        idx = self.maintenance_cache_list.curselection()
        if not idx:
            self.maintenance_status_var.set('Select cache to remove.')
            return
        entry_str = self.maintenance_cache_list.get(idx[0])
        cache_name = entry_str.replace('🛡️ ', '')  # Remove prefix if present
        if self.caching.remove_cache_entry(cache_name):
            self.maintenance_status_var.set(f'Removed {cache_name}')
            self._refresh_maintenance_cache_list()
        else:
            self.maintenance_status_var.set(f'Failed to remove {cache_name}')

    def _maintenance_rename_selected_cache(self):
        idx = self.maintenance_cache_list.curselection()
        if not idx:
            self.maintenance_status_var.set('Select cache to rename.')
            return
        entry_str = self.maintenance_cache_list.get(idx[0])
        cache_name = entry_str.replace('🛡️ ', '')
        new_name = simpledialog.askstring(
            'Rename Cache', 'Enter new name (format tenancy_cache-date):', initialvalue=cache_name
        )
        if new_name and new_name != cache_name:
            if self.caching.rename_cache_entry(cache_name, new_name):
                self.maintenance_status_var.set(f'Renamed {cache_name} to {new_name}')
                self._refresh_maintenance_cache_list()
                # Refresh the cache list in settings tab as well (live update)
                if getattr(self, 'settings_tab', None):
                    try:
                        self.settings_tab.refresh_cache_list()
                    except Exception:
                        pass
            else:
                self.maintenance_status_var.set(f'Failed to rename {cache_name}')

    def _maintenance_preserve_selected_cache(self):
        idx = self.maintenance_cache_list.curselection()
        if not idx:
            self.maintenance_status_var.set('Select cache to preserve/unpreserve.')
            return
        entry_str = self.maintenance_cache_list.get(idx[0])
        cache_name = entry_str.replace('🛡️ ', '')
        is_preserved = entry_str.startswith('🛡️ ')
        if self.caching.preserve_cache_entry(cache_name, preserve=not is_preserved):
            if not is_preserved:
                self.maintenance_status_var.set(f'Marked {cache_name} as preserved')
            else:
                self.maintenance_status_var.set(f'Unmarked {cache_name} as preserved')
            self._refresh_maintenance_cache_list()
            # Live update settings tab cache list if present
            if getattr(self, 'settings_tab', None):
                try:
                    self.settings_tab.refresh_cache_list()
                except Exception:
                    pass
        else:
            self.maintenance_status_var.set(f'Failed to update preserve state for {cache_name}')

    def _maintenance_permissions_load_data(self):
        # Load reference data
        try:
            self._ref_repo = ReferenceDataRepo()
            data = self._ref_repo.data
            all_items = sorted(data['resources'].keys()) + [f'Family: {f}' for f in sorted(data['families'].keys())]
            for widget_combo in [
                self.permissions_resource_combo,
                self.permissions_res1_combo,
                self.permissions_res2_combo,
            ]:
                widget_combo['values'] = all_items
                if all_items:
                    widget_combo.current(0)
            for vcombo in [self.permissions_verb_combo, self.permissions_verb1_combo, self.permissions_verb2_combo]:
                vcombo.set('read')
            for acombo in [self.permissions_action1_combo, self.permissions_action2_combo]:
                acombo.set('allow')
        except Exception as ex:
            self.permissions_result_label.config(text=f'Could not load permissions.json: {ex}')

    def _maintenance_get_permission(self):
        sel = self.permissions_resource_combo.get()
        verb = self.permissions_verb_combo.get()
        self.permissions_result_label.config(text='')
        if sel and verb and hasattr(self, '_ref_repo'):
            is_family = sel.startswith('Family: ')
            entity = sel.replace('Family: ', '') if is_family else sel
            perms = self._ref_repo.get_permissions(entity, verb)
            label = f'Family: {entity}' if is_family else entity
            if perms is None:
                self.permissions_result_label.config(text='Invalid selection.')
            else:
                source = self._ref_repo.get_source(entity)
                source_text = f'\nSource URL: {source}' if source else ''
                if perms:
                    upper_perms = [p.upper() for p in perms]
                    self.permissions_result_label.config(
                        text=f"{label} | {verb}: {', '.join(upper_perms)}{source_text}"
                    )
                else:
                    self.permissions_result_label.config(text=f'{label} | {verb}: (no permissions){source_text}')
        else:
            self.permissions_result_label.config(text='Select resource/family and verb.')

    def _on_apiop_perm_select(self, event=None):
        """Display selected permissions in the preview text box (non-editable)."""
        sel_indices = self.apiop_perms_listbox.curselection()
        perms = [self._apiop_perms[i] for i in sel_indices]
        display = ', '.join(perms)
        self.apiop_selectedperms_text.config(state=tk.NORMAL)
        self.apiop_selectedperms_text.delete(1.0, tk.END)
        self.apiop_selectedperms_text.insert(tk.END, display)
        self.apiop_selectedperms_text.config(state=tk.DISABLED)
        # No return (used as callback)

    def _maintenance_ops_tester_load_data(self):
        """Populate the operations tester controls with available APIs and permissions."""
        if not hasattr(self, '_ref_repo'):
            try:
                self._ref_repo = ReferenceDataRepo()
            except Exception:
                return

        data = self._ref_repo.data
        # API operations as "apiname:Operation"
        apiops = []
        op_to_api = {}
        for api, ops in data.get('operations_by_api', {}).items():
            for op in ops:
                label = f'{api}:{op}'
                apiops.append(label)
                op_to_api[label] = (api, op)
        self._apiop_all_labels = apiops  # save unfiltered for search/filter
        self._apiop_map = op_to_api  # cache for callback

        self._update_apiop_combo_filtered()

        # Permissions: union of all permissions in all resources/verbs
        permset = set()
        for resval in data.get('resources', {}).values():
            verbs = resval.get('verbs', {})
            for plist in verbs.values():
                permset.update(p.upper() for p in plist)
        perms = sorted(permset)
        self.apiop_perms_listbox.delete(0, tk.END)
        for p in perms:
            self.apiop_perms_listbox.insert(tk.END, p)
        self._apiop_perms = perms  # for quick lookup

        # Deselect all, clear selected preview box
        self.apiop_perms_listbox.selection_clear(0, tk.END)
        self._on_apiop_perm_select()
        self._update_apiop_note()

        # Bind combobox change to update note as well
        self.apiop_combo.bind('<<ComboboxSelected>>', self._on_apiop_combo_change)

    def _update_apiop_combo_filtered(self, event=None):
        """Update API operation combobox values based on current filter entry (case-insensitive substring match)."""
        filter_txt = self.apiop_filter_var.get().strip().lower()
        if not filter_txt:
            filtered = self._apiop_all_labels
        else:
            filtered = [label for label in self._apiop_all_labels if filter_txt in label.lower()]
        self.apiop_combo['values'] = filtered
        if filtered:
            self.apiop_combo.current(0)
        else:
            self.apiop_combo.set('')

    def _on_apiop_filter_change(self, event=None):
        self._update_apiop_combo_filtered()
        self._on_apiop_combo_change()

    def _apiop_check(self):
        """Check if selected permissions satisfy the selected API op."""
        if not hasattr(self, '_ref_repo'):
            messagebox.showerror('Error', 'Reference data not loaded')
            return
        op_label = self.apiop_combo.get()
        if not op_label or op_label not in self._apiop_map:
            self.apiop_result_label.config(text='(no op)')
            self.apiop_note_label.config(text='')
            return
        api_name, op_name = self._apiop_map[op_label]
        # Gather selected permissions from the listbox
        sel_indices = self.apiop_perms_listbox.curselection()
        perms = [self._apiop_perms[i] for i in sel_indices]
        res = self._ref_repo.has_api_operation_permissions(op_name, perms)
        self.apiop_result_label.config(text='True' if res else 'False', foreground='green' if res else 'red')
        # Also update selected permissions view in case selection changed via keyboard while focus on button
        self._on_apiop_perm_select()
        self._update_apiop_note()

    def _on_apiop_combo_change(self, event=None):
        """Update note field when changing operation combobox selection."""
        self._update_apiop_note()

    def _update_apiop_note(self):
        # Show the note for the selected operation (if present)
        op_label = self.apiop_combo.get()
        note = ''
        if hasattr(self, '_ref_repo') and hasattr(self, '_apiop_map') and op_label in self._apiop_map:
            api_name, op_name = self._apiop_map[op_label]
            opmeta = self._ref_repo.data.get('operations_by_api', {}).get(api_name, {}).get(op_name, {})
            note = opmeta.get('notes', '') or ''
        self.apiop_note_label.config(text=note if note else '')

    def _maintenance_check_overlap(self):
        sel1 = self.permissions_res1_combo.get()
        verb1 = self.permissions_verb1_combo.get()
        action1 = self.permissions_action1_combo.get()
        sel2 = self.permissions_res2_combo.get()
        verb2 = self.permissions_verb2_combo.get()
        action2 = self.permissions_action2_combo.get()
        self.permissions_overlap_text.delete(1.0, tk.END)
        logger.info(
            f'User action: Checking overlap between {sel1} ({verb1}, {action1}) and {sel2} ({verb2}, {action2})'
        )
        if not (sel1 and verb1 and action1 and sel2 and verb2 and action2 and hasattr(self, '_ref_repo')):
            logger.debug('Overlap: selection incomplete.')
            self.permissions_overlap_text.insert(tk.END, 'Select both statements.')
            return
        entity1 = sel1.replace('Family: ', '') if sel1.strip().startswith('Family:') else sel1
        entity2 = sel2.replace('Family: ', '') if sel2.strip().startswith('Family:') else sel2
        overlap = []
        try:
            # Direct API with logging support
            logger.debug(
                f'Calling ReferenceDataRepo.check_overlap_params({entity1}, {verb1}, {action1}, {entity2}, {verb2}, {action2})'
            )
            overlap = self._ref_repo.check_overlap_params(entity1, verb1, action1, entity2, verb2, action2)
        except Exception as ex:
            logger.error(f'Error in overlap check: {ex}')
            self.permissions_overlap_text.insert(tk.END, f'Error: {ex}')
            return
        output = f'Overlap between:\n  {sel1} | {verb1} | {action1}\n  {sel2} | {verb2} | {action2}\n\n'
        output += f"Common permissions: {', '.join(sorted(p.upper() for p in overlap)) if overlap else '(none)'}"
        logger.info(f'Overlap result = {output}')

        # Display result
        self.permissions_overlap_text.insert(tk.END, output)
