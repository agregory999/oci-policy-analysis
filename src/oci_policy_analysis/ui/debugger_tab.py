##########################################################################
# Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# debugger_tab.py
#
# Generic Debugger Tab for OCI Policy Analysis.
# Shows dropdown to select data source and display mode (Text or Tree).
# Depending on mode, shows a scrollable text area (pretty-printed JSON) or TreeView for navigation.
#
# @author: Andrew Gregory & Cline
##########################################################################

import json
import tkinter as tk
from tkinter import scrolledtext, ttk

from oci_policy_analysis.ui.base_tab import BaseUITab


class DebuggerTab(BaseUITab):
    """
    Debugger Tab for viewing internal JSON/data from Policy Repo, Reference Data, or Simulation Engine.
    User selects Source and (Text or Tree) view.
    """

    def __init__(self, parent, app=None):
        super().__init__(
            parent,
            default_help_text=(
                'Debug and inspect internal data structures from various subsystems. '
                'Select a source and a display mode. Troubleshooting help available in documentation.'
            ),
            page_help_link='/logging_and_troubleshooting.html',
        )
        self.app = app  # expects: app has .policy_compartment_analysis and (optionally) .simulation_engine

        # Row for source and display mode
        control_row = ttk.Frame(self)
        control_row.pack(fill='x', pady=(8, 8), padx=8)

        self.source_var = tk.StringVar(value='Policy Repo Policies')
        self.view_mode_var = tk.StringVar(value='Text')

        ttk.Label(control_row, text='Source:').pack(side='left', padx=(2, 4))
        # Add all overlays as selectable options
        overlay_sources = [
            'Policy Intelligence: Cleanup Items',
            'Policy Intelligence: Recommendations',
            'Policy Intelligence: Overlaps',
            'Policy Intelligence: Risk Scores',
            'Policy Intelligence: Consolidations',
        ]
        self.source_options = [
            'Policy Repo Compartments',
            'Policy Repo Policies',
            'Reference Data',
            'Simulation History',
            # 'Consolidation (In-Flight Session)',  # NEW
        ] + overlay_sources

        self.source_combo = ttk.Combobox(
            control_row,
            textvariable=self.source_var,
            values=self.source_options,
            width=32,
            state='readonly',
        )
        self.source_combo.pack(side='left', padx=(0, 12))

        # Reference Data subset dropdown (initially empty, shown/hidden as needed)
        self.refdata_subset_var = tk.StringVar()
        self.refdata_subset_combo = ttk.Combobox(
            control_row, textvariable=self.refdata_subset_var, width=20, state='readonly', values=[]
        )
        self.refdata_subset_combo.pack_forget()  # Hide unless active

        ttk.Label(control_row, text='View:').pack(side='left', padx=(2, 4))
        self.view_mode_combo = ttk.Combobox(
            control_row, textvariable=self.view_mode_var, values=['Text', 'Tree'], width=9, state='readonly'
        )
        self.view_mode_combo.pack(side='left', padx=(0, 4))

        ttk.Button(control_row, text='Refresh', command=self._refresh_display).pack(side='left', padx=(12, 0))

        # Output widgets (start hidden, show active only)
        self.text_area = scrolledtext.ScrolledText(self, height=26, wrap='none', font=('Courier', 10))
        self.tree_area = ttk.Treeview(self, columns=('value',), show='tree headings', height=24)
        self.tree_area.heading('#0', text='Key/Index')
        self.tree_area.heading('value', text='Value')
        self._tree_node_to_path = {}  # Map: node_id -> JSON path tuple
        self.tree_area.bind('<<TreeviewOpen>>', self._on_treeview_open)

        self.source_combo.bind('<<ComboboxSelected>>', self._on_source_combo)
        self.view_mode_combo.bind('<<ComboboxSelected>>', lambda evt: self._refresh_display())
        self.refdata_subset_combo.bind('<<ComboboxSelected>>', lambda evt: self._refresh_display())

        self._init_reference_data_subsets()
        self._on_source_combo()

    def _get_source_data(self):  # noqa: C901
        if not self.app:
            return {}
        try:
            source = self.source_var.get()
            if source == 'Reference Data':
                # Get selected subset from Reference Data Repo
                return self.app.reference_data_repo.data

            elif source == 'Simulation History':
                return self.app.simulation_engine.simulation_history

            elif source == 'Policy Repo Policies':
                return self.app.policy_compartment_analysis.regular_statements
            elif source == 'Policy Repo Compartments':
                return self.app.policy_compartment_analysis.compartments

            # elif source == 'Consolidation (In-Flight Session)':
            #     try:
            #         from oci_policy_analysis.common.caching import CacheManager
            #     except ImportError:
            #         return {'error': 'CacheManager not available'}
            #     cache_mgr = CacheManager()
            #     tenancy_ocid = getattr(self.app, 'tenancy_ocid', 'unknown')
            #     # Try to load latest protected_set for this tenancy
            #     session = cache_mgr.load_consolidation_session(plan_id='protected_set', tenancy_ocid=tenancy_ocid)
            #     return session if session else {'note': 'No saved consolidation session/overlay found.'}

            # Overlay sources
            elif source.startswith('Policy Intelligence: '):
                overlay = getattr(self.app.policy_intelligence, 'overlay', {})
                mapping = {
                    'Policy Intelligence: Cleanup Items': 'cleanup_items',
                    'Policy Intelligence: Recommendations': 'recommendations',
                    'Policy Intelligence: Overlaps': 'overlaps',
                    'Policy Intelligence: Risk Scores': 'risk_scores',
                    'Policy Intelligence: Consolidations': 'consolidations',
                }
                overlay_key = mapping.get(source)
                if overlay_key:
                    return overlay.get(overlay_key, {})
                else:
                    return {'error': f'Unknown overlay source: {source}'}
            else:
                return {'error': f'Unknown source: {source}'}
        except Exception as ex:
            return {'error': str(ex)}
        return {}

    def _refresh_display(self):
        data = self._get_source_data()
        view_mode = self.view_mode_var.get()
        # Remove/hide both output widgets
        self.text_area.pack_forget()
        self.tree_area.pack_forget()
        if view_mode == 'Text':
            # Pretty-print JSON
            try:
                pretty = json.dumps(data, indent=2, ensure_ascii=False)
            except Exception as ex:
                pretty = f'(error serializing: {ex})'
            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(1.0, pretty)
            self.text_area.pack(fill='both', expand=True, padx=12, pady=4)
        else:
            # Clear and build tree
            self.tree_area.delete(*self.tree_area.get_children())
            self._tree_node_to_path.clear()
            self._insert_into_tree('', data, path=())
            self.tree_area.pack(fill='both', expand=True, padx=12, pady=4)

    def _insert_into_tree(self, parent, value, key='', path=()):
        """
        Populate just one level: for dicts and lists, create expandable items,
        for scalars, just the value. Supply `path` for tracking node position within data.
        """
        if isinstance(value, dict):
            for k, v in value.items():
                next_path = path + (k,)
                node_id = self.tree_area.insert(parent, 'end', text=str(k), values=(self._short_repr(v),))
                self._tree_node_to_path[node_id] = next_path
                if isinstance(v, dict | list):
                    # Add a single dummy child so the node is expandable; real children on expand
                    dummy_id = self.tree_area.insert(node_id, 'end', text='...', values=('...',))
                    self._tree_node_to_path[dummy_id] = next_path + ('...',)
        elif isinstance(value, list):
            for idx, v in enumerate(value):
                next_path = path + (idx,)
                node_id = self.tree_area.insert(parent, 'end', text=f'[{idx}]', values=(self._short_repr(v),))
                self._tree_node_to_path[node_id] = next_path
                if isinstance(v, dict | list):
                    dummy_id = self.tree_area.insert(node_id, 'end', text='...', values=('...',))
                    self._tree_node_to_path[dummy_id] = next_path + ('...',)
        else:
            # Scalar
            node_id = self.tree_area.insert(parent, 'end', text=str(key), values=(self._short_repr(value),))
            self._tree_node_to_path[node_id] = path

    def _on_treeview_open(self, event):
        """
        On expanding a tree node: if children are just a dummy "...", remove it and load actual children.
        """
        selected = self.tree_area.focus()
        path = self._tree_node_to_path.get(selected)
        if not path:  # Root may be empty path
            return
        # Fetch data at this path in the JSON source
        data = self._get_source_data()
        current = data
        try:
            for p in path:
                current = current[p]
        except Exception:
            return  # Path invalid or missing
        # If children already loaded (i.e. not just one child named "..."), do nothing
        kids = self.tree_area.get_children(selected)
        if len(kids) == 1:
            kid_text = self.tree_area.item(kids[0], 'text')
            if kid_text == '...':
                self.tree_area.delete(kids[0])
                self._insert_into_tree(selected, current, path=path)
                # No need to store new mappings here: _insert_into_tree takes care of it

    def _short_repr(self, v):
        # Show a short string for tree value column
        if isinstance(v, dict):
            return '{...}'
        elif isinstance(v, list):
            return f'[... {len(v)} items]'
        elif v is None:
            return 'null'
        elif isinstance(v, str) and len(v) > 80:
            return v[:77] + '...'
        else:
            return str(v)

    def _init_reference_data_subsets(self):
        # Probe for available subsets if Reference Data available
        refdata_repo = None
        self.refdata_subsets_list = []
        refdata = getattr(self.app, 'policy_compartment_analysis', None)
        if refdata and hasattr(refdata, 'reference_data_repo'):
            refdata_repo = getattr(refdata, 'reference_data_repo', None)
        if refdata_repo and hasattr(refdata_repo, 'data'):
            data = getattr(refdata_repo, 'data', {})
            if isinstance(data, dict):
                self.refdata_subsets_list = list(data.keys())
        # Default to first subset if empty value
        if self.refdata_subsets_list:
            self.refdata_subset_var.set(self.refdata_subsets_list[0])
            self.refdata_subset_combo['values'] = self.refdata_subsets_list
        else:
            self.refdata_subset_var.set('')
            self.refdata_subset_combo['values'] = []

    def _on_source_combo(self, evt=None):
        src = self.source_var.get()
        if src == 'Reference Data' and self.refdata_subsets_list:
            self.refdata_subset_combo.pack(side='left', padx=(0, 10))
        else:
            self.refdata_subset_combo.pack_forget()
        if src == 'Reference Data':
            # Ensure valid value always set
            if not self.refdata_subset_var.get() and self.refdata_subsets_list:
                self.refdata_subset_var.set(self.refdata_subsets_list[0])
        self._refresh_display()
