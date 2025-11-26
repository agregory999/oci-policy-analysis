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
from tkinter import simpledialog, ttk

from oci_policy_analysis.common.logger import get_logger

# Global logger for this module
logger = get_logger(component='maintenance')


class MaintenanceTab(ttk.Frame):
    def __init__(self, parent, caching):
        super().__init__(parent)
        self.caching = caching

        # -------- Maintenance UI Build (CACHE) ----------
        frm_cache = ttk.LabelFrame(self, text='Cache Management')
        frm_cache.pack(fill='x', padx=10, pady=10)

        # Listbox of caches
        self.maintenance_cache_list = tk.Listbox(frm_cache, selectmode=tk.SINGLE, height=8, width=80)
        self.maintenance_cache_list.pack(side='left', padx=8, pady=6)
        self._refresh_maintenance_cache_list()

        # Scrollbar for Listbox
        scroll = ttk.Scrollbar(frm_cache, orient='vertical', command=self.maintenance_cache_list.yview)
        self.maintenance_cache_list.config(yscrollcommand=scroll.set)
        scroll.pack(side='left', fill='y')

        # Buttons for cache ops
        btns_frm = ttk.Frame(frm_cache)
        btns_frm.pack(side='left', padx=10, fill='y')
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

        # -------- Maintenance UI Build (PERMISSIONS) ----------
        frm_permissions = ttk.LabelFrame(self, text='Permissions Viewer & Tests')
        frm_permissions.pack(fill='x', padx=10, pady=(0, 10))

        # Resource/Verb/Result section
        row0 = ttk.Frame(frm_permissions)
        row0.pack(fill='x', pady=2)
        ttk.Label(row0, text='Resource/Family:').pack(side='left', padx=2)
        self.permissions_resource_combo = ttk.Combobox(row0, width=30)
        self.permissions_resource_combo.pack(side='left')
        ttk.Label(row0, text='Verb:').pack(side='left', padx=2)
        self.permissions_verb_combo = ttk.Combobox(row0, values=['inspect', 'read', 'use', 'manage'], width=10)
        self.permissions_verb_combo.pack(side='left')
        ttk.Button(row0, text='Get Permissions', command=self._maintenance_get_permission).pack(side='left', padx=4)
        self.permissions_result_label = ttk.Label(frm_permissions, text='', wraplength=600, justify='left')
        self.permissions_result_label.pack(fill='x', pady=2, padx=2)

        # Overlap section
        sep = ttk.Separator(frm_permissions, orient='horizontal')
        sep.pack(fill='x', pady=4)

        # NEW: Statement comparison on two lines for clarity and compactness
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

        # More space for output
        self.permissions_overlap_text = tk.Text(frm_permissions, height=14, width=110, wrap=tk.WORD)
        self.permissions_overlap_text.pack(fill='x', padx=2, pady=2)
        self._maintenance_permissions_load_data()

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
        else:
            self.maintenance_status_var.set(f'Failed to update preserve state for {cache_name}')

    def _maintenance_permissions_load_data(self):
        # Load reference data
        try:
            from reference_data.reference_data_repo import ReferenceDataRepo

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
