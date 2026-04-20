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
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

logger = get_logger(component='permissions_report_tab')
permission_reference_repo = ReferenceDataRepo()


class PermissionsReportTab(BaseUITab):
    """Tab for displaying permissions by effective compartment and subject in a treeview, with context help."""

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text=(
                'This tab displays permissions by compartment and subject. '
                'Select any compartment or subject from the tree on the left to view their allow/deny permissions on the right. '
                'Use controls above to expand/collapse the tree or export the report data. '
                'Tables on the right show explicit and inherited permissions.'
            ),
            page_help_link='/usage.html#permissions-report-tab',
        )
        self.app = app
        self.policy_repo = app.policy_compartment_analysis

        # 50/50 split left and right
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=4)

        control_frame = ttk.LabelFrame(self, text='Permissions Report Controls')
        control_frame.pack(fill='x', padx=10, pady=10)
        self.btn_expand_all = ttk.Button(control_frame, text='Expand All', state=tk.DISABLED, command=self.expand_all)
        self.btn_expand_all.grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.btn_collapse_all = ttk.Button(
            control_frame, text='Collapse All', state=tk.DISABLED, command=self.collapse_all
        )
        self.btn_collapse_all.grid(row=0, column=1, padx=5, pady=5, sticky='w')
        self.btn_export = ttk.Button(
            control_frame, text='Export to JSON', state=tk.DISABLED, command=self.export_to_json
        )
        self.btn_export.grid(row=0, column=2, padx=5, pady=5, sticky='w')
        self.show_inherited_principals_var = tk.BooleanVar(value=False)
        self.chk_show_inherited = ttk.Checkbutton(
            control_frame,
            text='Show inherited principals in tree',
            variable=self.show_inherited_principals_var,
            command=self.populate_tree,
        )
        self.chk_show_inherited.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        self.info_label = ttk.Label(control_frame, text='Load tenancy data to generate report')
        self.info_label.grid(row=0, column=4, padx=10, pady=5, sticky='w')

        # Attach context help to controls; messages tailored
        self.add_context_help(
            control_frame,
            (
                'Use these controls to manage the permissions report.\n'
                "'Expand All' shows the full permissions tree. "
                "'Collapse All' folds the tree. "
                "'Export to JSON' lets you save the report."
            ),
        )
        self.add_context_help(self.btn_expand_all, 'Expand all nodes in the permissions tree.')
        self.add_context_help(self.btn_collapse_all, 'Collapse all nodes in the permissions tree.')
        self.add_context_help(self.btn_export, 'Export the permissions report data to a JSON file.')
        self.add_context_help(
            self.chk_show_inherited,
            'When enabled, show principals inherited from parent compartments in each tree node.',
        )
        self.add_context_help(self.info_label, 'Status messages and steps for generating or exporting the report.')

        # Frames for split view

        # Main bottom section: horizontally split frame
        bottom_section = ttk.Frame(self)
        bottom_section.pack(fill='both', expand=True, padx=0, pady=(0, 0))

        left_frame = ttk.Frame(bottom_section)
        left_frame.pack(side='left', fill='both', expand=True)
        right_frame = ttk.Frame(bottom_section)
        right_frame.pack(side='left', fill='both', expand=True)

        vsb = ttk.Scrollbar(left_frame, orient='vertical')
        hsb = ttk.Scrollbar(left_frame, orient='horizontal')
        self.permissions_tree = ttk.Treeview(
            left_frame,
            columns=('Type', 'SubjectKey', 'InheritedFrom'),
            displaycolumns=('Type',),
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode='browse',
        )
        vsb.config(command=self.permissions_tree.yview)
        hsb.config(command=self.permissions_tree.xview)
        self.permissions_tree.heading('#0', text='Effective Path / Subject')
        self.permissions_tree.heading('Type', text='Type')
        self.permissions_tree.column('#0', width=350, minwidth=200, stretch=True)
        self.permissions_tree.column('Type', width=110, minwidth=70)
        self.permissions_tree.column('SubjectKey', width=0, stretch=False)
        self.permissions_tree.column('InheritedFrom', width=0, stretch=False)
        self.permissions_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)
        self.add_context_help(
            self.permissions_tree,
            'Select a compartment or subject in this tree to view detailed permissions. '
            'Tree nodes correspond to compartments and their effective subjects.',
        )

        # On right: output as a DataTable (Permission, Conditional), wrapped in LabelFrame
        detail_label = ttk.Label(right_frame, text='Selected Permissions', font=('TkDefaultFont', 10, 'bold'))
        detail_label.pack(anchor='nw', padx=5, pady=4)
        detail_pane = ttk.Frame(right_frame)
        detail_pane.pack(fill='both', expand=True, padx=5, pady=5)

        # DataTable for allow and deny
        self.allow_dt_frame = ttk.LabelFrame(detail_pane, text='Allow Permissions')
        self.allow_dt_frame.pack(fill='both', expand=True, padx=0, pady=(0, 10), side='top')
        self.add_context_help(
            self.allow_dt_frame,
            ('Table of permissions that are explicitly or inherited allowed for the selected subject.'),
        )

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
        self.add_context_help(
            self.deny_dt_frame,
            ('Table of permissions that are explicitly or inherited denied for the selected subject.'),
        )
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
        # Always enable expand/collapse/export, since permissions_report is always built after load
        self.btn_expand_all.configure(state='normal')
        self.btn_collapse_all.configure(state='normal')
        self.btn_export.configure(state='normal')
        self.info_label.config(text='Report loaded; ready to analyze permissions')
        # populate tree with updated report data
        self.populate_tree()

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Apply main settings for context help and font size.
        """
        super().apply_settings(context_help, font_size)

    def populate_tree(self):
        # Always use the centralized report data
        perm_engine = self.app.policy_intelligence.permissions_report
        report_data = perm_engine.get('report', {}) if perm_engine else {}
        for item in self.permissions_tree.get_children():
            self.permissions_tree.delete(item)
        if not report_data:
            logger.info('No permissions report data available to populate tree')
            return
        for path in sorted(report_data.keys()):
            path_node = self.permissions_tree.insert(
                '', 'end', text=path, values=('Compartment',), tags=('compartment',)
            )
            for subject_key, subject_type, inherited_from in self._get_subjects_for_path(path, report_data):
                display_name = subject_key
                if inherited_from:
                    display_name = f'{subject_key} (inherited from {inherited_from})'
                self.permissions_tree.insert(
                    path_node,
                    'end',
                    text=display_name,
                    values=(subject_type, subject_key, inherited_from or ''),
                    tags=('subject',),
                )

    def _get_subjects_for_path(self, path: str, report_data: dict) -> list[tuple[str, str, str | None]]:
        subjects = report_data.get(path, {})
        subject_map: dict[str, tuple[str, str | None]] = {}
        for subject_key, data in subjects.items():
            subject_type = (data or {}).get('subject_type') or 'unknown'
            subject_map[subject_key] = (subject_type, None)
        if self.show_inherited_principals_var.get():
            for ancestor in self._get_ancestor_paths(path):
                for subject_key, data in report_data.get(ancestor, {}).items():
                    if subject_key in subject_map:
                        continue
                    subject_type = (data or {}).get('subject_type') or 'unknown'
                    subject_map[subject_key] = (subject_type, ancestor)
        return sorted(
            [
                (subject_key, subject_type, inherited_from)
                for subject_key, (subject_type, inherited_from) in subject_map.items()
            ],
            key=lambda item: item[0],
        )

    @staticmethod
    def _get_ancestor_paths(path_key: str) -> list[str]:
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
        return parent_nodes

    @staticmethod
    def _build_permission_rows(
        permissions: list[str],
        parent_permissions: list[tuple[str, list[str]]],
        perm_conditionals: dict[tuple[str, str, str], bool],
        perm_statements: dict[tuple[str, str, str], str],
        path_key: str,
        subject_key: str,
    ) -> list[dict[str, str]]:
        rows = []
        for perm in sorted(permissions):
            rows.append(
                {
                    'Permission': perm,
                    'Conditional': str(perm_conditionals.get((path_key, subject_key, perm), False)),
                    'Statement Text': perm_statements.get((path_key, subject_key, perm), ''),
                }
            )
        for ancestor, ancestor_perms in parent_permissions:
            for perm in sorted(ancestor_perms):
                rows.append(
                    {
                        'Permission': f'{perm} (inherited from {ancestor})',
                        'Conditional': str(perm_conditionals.get((ancestor, subject_key, perm), False)),
                        'Statement Text': perm_statements.get((ancestor, subject_key, perm), ''),
                    }
                )
        return rows

    def on_tree_selection(self, event):  # noqa: C901
        sel = self.permissions_tree.selection()
        if not sel:
            return
        item = sel[0]
        node = self.permissions_tree.item(item)
        parent = self.permissions_tree.parent(item)
        if not parent:
            return
        subject_key = node.get('values', [None, None])[1] or node['text']
        path_key = self.permissions_tree.item(parent)['text']
        perm_engine = self.app.policy_intelligence.permissions_report
        report_data = perm_engine.get('report', {}) if perm_engine else {}
        perm_conditionals = perm_engine.get('perm_conditionals', {}) if perm_engine else {}
        perm_statements = perm_engine.get('perm_statements', {}) if perm_engine else {}
        subject_data = report_data.get(path_key, {}).get(subject_key, {})
        allow = list(subject_data.get('allow', []))
        deny = list(subject_data.get('deny', []))
        # Inheritance: collect from parent compartments as well
        parent_nodes = self._get_ancestor_paths(path_key)
        parent_perms = []
        parent_denies = []
        for ancestor in parent_nodes:
            ancestor_data = report_data.get(ancestor, {}).get(subject_key, {})
            ap_all = ancestor_data.get('allow', [])
            ap_deny = ancestor_data.get('deny', [])
            if ap_all:
                parent_perms.append((ancestor, ap_all))
            if ap_deny:
                parent_denies.append((ancestor, ap_deny))

        allow_rows = self._build_permission_rows(
            allow,
            parent_perms,
            perm_conditionals,
            perm_statements,
            path_key,
            subject_key,
        )
        deny_rows = self._build_permission_rows(
            deny,
            parent_denies,
            perm_conditionals,
            perm_statements,
            path_key,
            subject_key,
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
            if 'Policy\nAnalysis' in self.app.notebook.tab(tab, 'text'):
                self.app.notebook.select(tab)
                # Set search in policies_tab
                if hasattr(self.app, 'policies_tab'):
                    self.app.policies_tab.text_filter_var.set(statement_text)
                    self.app.policies_tab.chk_show_dynamic.set(True)
                    self.app.policies_tab.update_policy_output()
                break

    # generate_report is now obsolete: deleted.

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
        # For export, use the latest centralized report data again
        perm_engine = self.app.policy_intelligence.permissions_report
        report_data = perm_engine.get('report', {}) if perm_engine else {}
        if not report_data:
            return
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON Files', '*.json')])
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)
                self.info_label.config(text=f'Report exported to {filepath}')
            except Exception:
                pass
