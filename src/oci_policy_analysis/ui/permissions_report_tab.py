##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# permissions_report_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import traceback
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.ui.data_table import DataTable

logger = get_logger(component='permissions_report')
permission_reference_repo = ReferenceDataRepo()


class PermissionsReportTab(ttk.Frame):
    """Tab for displaying permissions by effective compartment and subject in a treeview."""

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository, settings):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = policy_repo
        self.report_data = {}
        self.resource_map = {}

        # 50/50 split left and right
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=4)

        control_frame = ttk.LabelFrame(self, text='Permissions Report Controls')
        control_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=10)
        self.btn_generate = ttk.Button(
            control_frame, text='Generate Report', state=tk.DISABLED, command=self.generate_report
        )
        self.btn_generate.grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.btn_expand_all = ttk.Button(control_frame, text='Expand All', state=tk.DISABLED, command=self.expand_all)
        self.btn_expand_all.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        self.btn_collapse_all = ttk.Button(
            control_frame, text='Collapse All', state=tk.DISABLED, command=self.collapse_all
        )
        self.btn_collapse_all.grid(row=0, column=2, padx=5, pady=5, sticky='w')
        self.btn_export = ttk.Button(
            control_frame, text='Export to JSON', state=tk.DISABLED, command=self.export_to_json
        )
        self.btn_export.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        self.info_label = ttk.Label(control_frame, text='Load tenancy data to generate report')
        self.info_label.grid(row=0, column=4, padx=10, pady=5, sticky='w')

        left_frame = ttk.Frame(self)
        left_frame.grid(row=1, column=0, sticky='nsew')
        right_frame = ttk.Frame(self)
        right_frame.grid(row=1, column=1, sticky='nsew')
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        vsb = ttk.Scrollbar(left_frame, orient='vertical')
        hsb = ttk.Scrollbar(left_frame, orient='horizontal')
        self.permissions_tree = ttk.Treeview(
            left_frame, columns=('Type',), yscrollcommand=vsb.set, xscrollcommand=hsb.set, selectmode='browse'
        )
        vsb.config(command=self.permissions_tree.yview)
        hsb.config(command=self.permissions_tree.xview)
        self.permissions_tree.heading('#0', text='Effective Path / Subject')
        self.permissions_tree.heading('Type', text='Type')
        self.permissions_tree.column('#0', width=350, minwidth=200, stretch=True)
        self.permissions_tree.column('Type', width=110, minwidth=70)
        self.permissions_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # On right: output as a DataTable (Permission, Conditional), wrapped in LabelFrame
        detail_label = ttk.Label(right_frame, text='Selected Permissions', font=('TkDefaultFont', 10, 'bold'))
        detail_label.pack(anchor='nw', padx=5, pady=4)
        detail_pane = ttk.Frame(right_frame)
        detail_pane.pack(fill='both', expand=True, padx=5, pady=5)

        # DataTable for allow and deny
        self.allow_dt_frame = ttk.LabelFrame(detail_pane, text='Allow Permissions')
        self.allow_dt_frame.pack(fill='both', expand=True, padx=0, pady=(0, 10), side='top')
        # self.allow_data_table = None
        self.allow_data_table = DataTable(
            self.allow_dt_frame,
            columns=['Permission', 'Conditional'],
            display_columns=['Permission', 'Conditional'],
            column_widths={'Permission': 400, 'Conditional': 150},
            data=[],
        )
        self.allow_data_table.pack(fill='both', expand=True)

        self.deny_dt_frame = ttk.LabelFrame(detail_pane, text='Deny Permissions')
        self.deny_dt_frame.pack(fill='both', expand=True, padx=0, pady=(0, 10), side='top')
        self.deny_data_table = DataTable(
            self.deny_dt_frame,
            columns=['Permission', 'Conditional'],
            display_columns=['Permission', 'Conditional'],
            column_widths={'Permission': 400, 'Conditional': 150},
            data=[],
        )
        self.deny_data_table.pack(fill='both', expand=True)
        self.permissions_tree.bind('<<TreeviewSelect>>', self.on_tree_selection)
        self.permissions_tree.tag_configure('compartment', font=('TkDefaultFont', 10, 'bold'))
        self.permissions_tree.tag_configure('subject', font=('TkDefaultFont', 9))

    def enable_widgets_after_load(self):
        self.btn_generate.configure(state='normal')
        self.info_label.config(text='Ready to generate report')

    def build_report_data(self) -> dict:  # noqa: C901
        logger.info('Starting to build permissions report data')
        report = {}
        self.resource_map = {}
        self.perm_conditionals = {}  # (path,subject,perm) -> True/False
        self.perm_statements = {}  # (path,subject,perm) -> statement_text
        statements = self.policy_repo.regular_statements
        for _idx, stmt in enumerate(statements):
            try:
                effective_path = stmt.get('effective_path')
                if not effective_path or effective_path is None:
                    effective_path = 'UNKNOWN'
                action = stmt.get('action', 'allow').lower()
                subjects = stmt.get('subject', [])
                subject_type = stmt.get('subject_type', 'unknown')
                permissions = stmt.get('permission', [])
                resource_str = stmt.get('resource')
                statement_text = stmt.get('statement_text', '')
                is_conditional = bool(stmt.get('conditions'))
                if not permissions:
                    resource = stmt.get('resource', '')
                    verb = stmt.get('verb', '')
                    if resource and verb:
                        permissions = permission_reference_repo.get_permissions(
                            entity=resource, verb=verb, action=action
                        )
                        if not permissions:
                            permissions = [f'{verb.upper()}_{resource.upper()}']
                    else:
                        permissions = ['UNKNOWN_PERMISSION']
                if subjects is None:
                    subjects = [('Default', 'UNKNOWN')]
                for subject_domain, subject_name in subjects:
                    domain_str = str(subject_domain) if subject_domain else 'Default'
                    subject_key = f'{subject_type}:{domain_str}/{subject_name}'
                    if effective_path not in report:
                        report[effective_path] = {}
                    if subject_key not in report[effective_path]:
                        report[effective_path][subject_key] = {'allow': set(), 'deny': set()}
                    if action == 'deny':
                        report[effective_path][subject_key]['deny'].update(permissions)
                    else:
                        report[effective_path][subject_key]['allow'].update(permissions)
                    for perm in permissions:
                        self.perm_conditionals[(effective_path, subject_key, perm)] = is_conditional
                        self.perm_statements[(effective_path, subject_key, perm)] = statement_text
                    rsrc = resource_str if resource_str else ('Permissions (select row)' if permissions else '')
                    self.resource_map[(effective_path, subject_key)] = rsrc
            except Exception:
                pass
        for path in report:
            for subject in report[path]:
                report[path][subject]['allow'] = sorted(
                    [perm for perm in list(report[path][subject]['allow']) if perm is not None]
                )
                report[path][subject]['deny'] = sorted(
                    [perm for perm in list(report[path][subject]['deny']) if perm is not None]
                )
        return report

    def populate_tree(self):
        for item in self.permissions_tree.get_children():
            self.permissions_tree.delete(item)
        if not self.report_data:
            return
        sorted_paths = sorted(self.report_data.keys())
        for path in sorted_paths:
            path_node = self.permissions_tree.insert(
                '', 'end', text=path, values=('Compartment',), tags=('compartment',)
            )
            subjects = self.report_data[path]
            sorted_subjects = sorted(subjects.keys())
            for subject_key in sorted_subjects:
                subject_parts = subject_key.split(':', 1)
                subject_type = subject_parts[0] if len(subject_parts) > 1 else 'unknown'
                self.permissions_tree.insert(
                    path_node, 'end', text=subject_key, values=(subject_type,), tags=('subject',)
                )

    def on_tree_selection(self, event):  # noqa: C901
        sel = self.permissions_tree.selection()
        if not sel:
            return
        item = sel[0]
        node = self.permissions_tree.item(item)
        parent = self.permissions_tree.parent(item)
        if not parent:
            return
        subject_key = node['text']
        path_key = self.permissions_tree.item(parent)['text']
        subject_data = self.report_data.get(path_key, {}).get(subject_key, {})
        allow = list(subject_data.get('allow', []))
        deny = list(subject_data.get('deny', []))
        # Inheritance: collect from parent compartments as well
        parent_path = path_key
        parent_nodes = []
        while parent_path:
            if '/' in parent_path:
                parent_path = parent_path.rsplit('/', 1)[0]
            elif parent_path != 'ROOT':
                parent_path = 'ROOT'
            else:
                break
            parent_nodes.append(parent_path)
        parent_perms = []
        parent_denies = []
        for ancestor in parent_nodes:
            ancestor_data = self.report_data.get(ancestor, {}).get(subject_key, {})
            ap_all = ancestor_data.get('allow', [])
            ap_deny = ancestor_data.get('deny', [])
            if ap_all:
                parent_perms.append((ancestor, ap_all))
            if ap_deny:
                parent_denies.append((ancestor, ap_deny))

        # Build allow data for DataTable: list of dicts for DataTable
        allow_rows = []
        for perm in sorted(allow):
            allow_rows.append(
                {
                    'Permission': perm,
                    'Conditional': str(self.perm_conditionals.get((path_key, subject_key, perm), False)),
                    'Statement Text': self.perm_statements.get((path_key, subject_key, perm), ''),
                }
            )
        for ancestor, ancpermlist in parent_perms:
            for perm in sorted(ancpermlist):
                allow_rows.append(
                    {
                        'Permission': f'{perm} (inherited from {ancestor})',
                        'Conditional': str(self.perm_conditionals.get((ancestor, subject_key, perm), False)),
                        'Statement Text': self.perm_statements.get((ancestor, subject_key, perm), ''),
                    }
                )

        deny_rows = []
        for perm in sorted(deny):
            deny_rows.append(
                {
                    'Permission': perm,
                    'Conditional': str(self.perm_conditionals.get((path_key, subject_key, perm), False)),
                    'Statement Text': self.perm_statements.get((path_key, subject_key, perm), ''),
                }
            )
        for ancestor, ancdenylist in parent_denies:
            for perm in sorted(ancdenylist):
                deny_rows.append(
                    {
                        'Permission': f'{perm} (inherited from {ancestor})',
                        'Conditional': str(self.perm_conditionals.get((ancestor, subject_key, perm), False)),
                        'Statement Text': self.perm_statements.get((ancestor, subject_key, perm), ''),
                    }
                )

        # Destroy existing tables to avoid duplication
        for widget in self.allow_dt_frame.winfo_children():
            widget.destroy()
        for widget in self.deny_dt_frame.winfo_children():
            widget.destroy()

        # Custom right-click: Show Policy Statement
        def policy_right_click(row_idx):
            data = allow_rows[row_idx] if row_idx < len(allow_rows) else deny_rows[row_idx - len(allow_rows)]
            menu = tk.Menu(self, tearoff=0)
            statement_text = data.get('Statement Text', '')
            # Command to switch tab and set text
            menu.add_command(label='Show Policy Statement', command=lambda: self._show_policy_statement(statement_text))
            return menu

        def permission_ai_lookup(selected_rows: list[dict]):
            selected_rows[0]
            permission = selected_rows[0].get('Permission', '')
            # Here you could integrate with an AI lookup function
            logger.info(f'AI Lookup for permission: {permission}')
            self.app.policy_query_var.set(permission)
            self.app.ai_additional_instructions = 'Provide detailed information about this OCI permission.'
            self.app.policy_query_label_text.set('AI Permission Lookup:')

        self.allow_data_table = DataTable(
            self.allow_dt_frame,
            columns=['Permission', 'Conditional'],
            display_columns=['Permission', 'Conditional'],
            column_widths={'Permission': 400, 'Conditional': 100},
            data=allow_rows,
            row_context_menu_callback=policy_right_click,
            selection_callback=permission_ai_lookup,
        )
        self.allow_data_table.pack(fill='both', expand=True)
        self.deny_data_table = DataTable(
            self.deny_dt_frame,
            columns=['Permission', 'Conditional'],
            display_columns=['Permission', 'Conditional'],
            column_widths={'Permission': 400, 'Conditional': 100},
            data=deny_rows,
            row_context_menu_callback=policy_right_click,
        )
        self.deny_data_table.pack(fill='both', expand=True)

    def _show_policy_statement(self, statement_text):
        # Switch tab to policies_tab and filter to the statement_text
        for _i, tab in enumerate(self.app.notebook.tabs()):
            if 'Policy' in self.app.notebook.tab(tab, 'text'):
                self.app.notebook.select(tab)
                # Set search in policies_tab
                if hasattr(self.app, 'policies_tab'):
                    self.app.policies_tab.text_filter_var.set(statement_text)
                    self.app.policies_tab.chk_show_dynamic.set(True)
                    self.app.policies_tab.update_policy_output()
                break

    def generate_report(self):
        self.info_label.config(text='Generating report...')
        self.update_idletasks()
        try:
            self.report_data = self.build_report_data()
            self.populate_tree()
            self.btn_expand_all.configure(state='normal')
            self.btn_collapse_all.configure(state='normal')
            self.btn_export.configure(state='normal')
            num_paths = len(self.report_data)
            num_subjects = sum(len(subjects) for subjects in self.report_data.values())
            self.info_label.config(text=f'Report generated: {num_paths} compartments, {num_subjects} subjects')
        except Exception as e:
            self.info_label.config(text=f'Error generating report: {e}')
            error_msg = traceback.format_exc()
            logger.error(f'Error generating permissions report: {error_msg}')

    def expand_all(self):
        def expand_children(item):
            self.permissions_tree.item(item, open=True)
            for child in self.permissions_tree.get_children(item):
                expand_children(child)

        for item in self.permissions_tree.get_children():
            expand_children(item)

    def collapse_all(self):
        def collapse_children(item):
            self.permissions_tree.item(item, open=False)
            for child in self.permissions_tree.get_children(item):
                collapse_children(child)

        for item in self.permissions_tree.get_children():
            collapse_children(item)

    def export_to_json(self):
        if not self.report_data:
            return
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON Files', '*.json')])
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.report_data, f, indent=2, ensure_ascii=False)
                self.info_label.config(text=f'Report exported to {filepath}')
            except Exception:
                pass
