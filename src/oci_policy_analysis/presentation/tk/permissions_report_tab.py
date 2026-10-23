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

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.permissions_report_service import PermissionsReportService
from oci_policy_analysis.presentation.tk.base_tab import BaseUITab
from oci_policy_analysis.presentation.tk.data_table import DataTable

logger = get_logger(component='permissions_report_tab')


class PermissionsReportTab(BaseUITab):
    """Tab for displaying permissions by effective compartment and subject in a treeview, with context help."""

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text=(
                'This Permissions Analysis tab displays permissions by compartment and subject. '
                'Select any compartment or subject from the tree on the left to view their allow/deny permissions on the right. '
                'Use the filters above to find principals and permissions. '
                'The right tables show explicit and, optionally, inherited permissions.'
            ),
            page_help_link='/usage.html#permissions-report-tab',
        )
        self.app = app
        self.policy_repo = app.policy_compartment_analysis

        control_frame = ttk.LabelFrame(self, text='Permissions Report Controls')
        control_frame.pack(fill='x', padx=10, pady=10)
        self.principal_query_var = tk.StringVar()
        principal_label = ttk.Label(control_frame, text='Principal')
        principal_label.grid(row=0, column=0, padx=(6, 3), pady=5, sticky='w')
        self.principal_search = ttk.Entry(control_frame, textvariable=self.principal_query_var, width=22)
        self.principal_search.grid(row=0, column=1, padx=3, pady=5, sticky='w')
        principal_type_label = ttk.Label(control_frame, text='Principal type')
        principal_type_label.grid(row=0, column=2, padx=(10, 3), pady=5, sticky='w')
        self.principal_type_var = tk.StringVar(value='All types')
        self.principal_type_combo = ttk.Combobox(
            control_frame, textvariable=self.principal_type_var, values=['All types'], state='readonly', width=16
        )
        self.principal_type_combo.grid(row=0, column=3, padx=3, pady=5, sticky='w')
        self.path_query_var = tk.StringVar()
        path_label = ttk.Label(control_frame, text='Effective path')
        path_label.grid(row=0, column=4, padx=(10, 3), pady=5, sticky='w')
        self.path_search = ttk.Entry(control_frame, textvariable=self.path_query_var, width=24)
        self.path_search.grid(row=0, column=5, padx=3, pady=5, sticky='w')
        self.show_inherited_principals_var = tk.BooleanVar(value=False)
        self.chk_show_inherited = ttk.Checkbutton(
            control_frame,
            text='Include inherited principals and permissions',
            variable=self.show_inherited_principals_var,
            command=self.populate_tree,
        )
        self.chk_show_inherited.grid(row=1, column=0, columnspan=3, padx=5, pady=3, sticky='w')
        self.show_unmapped_var = tk.BooleanVar(value=False)
        self.chk_show_unmapped = ttk.Checkbutton(
            control_frame,
            text='Show unmapped statements',
            variable=self.show_unmapped_var,
            command=self._toggle_unmapped,
        )
        self.chk_show_unmapped.grid(row=1, column=3, padx=5, pady=3, sticky='w')
        self.include_prospective_var = tk.BooleanVar(value=False)
        self.chk_include_prospective = ttk.Checkbutton(
            control_frame,
            text='Include prospective statements',
            variable=self.include_prospective_var,
            command=self._toggle_prospective,
        )
        self.chk_include_prospective.grid(row=1, column=4, columnspan=2, padx=5, pady=3, sticky='w')

        # Attach context help to controls; messages tailored
        self.add_context_help(
            control_frame,
            (
                'Search principals by key and effective path, or choose a principal type. '
                'Use the checkboxes to include inherited access, prospective statements, or excluded statements.'
            ),
        )
        self.add_context_help(principal_label, 'Filter principals by words in the principal key.')
        self.add_context_help(self.principal_search, 'Filter principal keys by matching all entered words.')
        self.add_context_help(principal_type_label, 'Filter the tree to one principal type.')
        self.add_context_help(self.principal_type_combo, 'Choose a principal type, or show all types.')
        self.add_context_help(path_label, 'Filter the tree to effective paths that contain the entered text.')
        self.add_context_help(self.path_search, 'Match text against effective compartment paths.')
        self.add_context_help(
            self.chk_show_inherited,
            'When enabled, include principals and permission grants inherited from ancestor compartments. When off, show grants directly at the selected path.',
        )
        self.add_context_help(
            self.chk_show_unmapped,
            'Show policy statements that the corpus could not map to permission facts.',
        )
        self.add_context_help(
            self.chk_include_prospective,
            'Overlay current prospective statements on the compiled tenancy corpus for this report.',
        )

        # Frames for split view

        # Main bottom section: horizontally split frame
        bottom_section = ttk.Frame(self)
        bottom_section.pack(fill='both', expand=True, padx=0, pady=(0, 0))
        bottom_section.grid_columnconfigure(0, weight=1, uniform='report-columns')
        bottom_section.grid_columnconfigure(1, weight=1, uniform='report-columns')
        bottom_section.grid_rowconfigure(0, weight=5)

        left_frame = ttk.LabelFrame(bottom_section, text='Permissions Scope')
        left_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        right_frame = ttk.LabelFrame(bottom_section, text='Permissions')
        right_frame.grid(row=0, column=1, sticky='nsew', padx=(5, 0))
        self.add_context_help(
            left_frame, 'Filter effective paths and principals, then select a row to review its permissions.'
        )
        self.add_context_help(right_frame, 'Allow and deny permissions for the selected path and principal.')

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

        # Shared permission-name filter for the allow and deny detail tables.
        self.permission_query_var = tk.StringVar()
        permission_filter_frame = ttk.Frame(right_frame)
        permission_filter_frame.pack(fill='x', padx=5, pady=(5, 5))
        permission_label = ttk.Label(permission_filter_frame, text='Permission')
        permission_label.pack(side='left', padx=(0, 5))
        self.permission_search = ttk.Entry(permission_filter_frame, textvariable=self.permission_query_var)
        self.permission_search.configure(width=26)
        self.permission_search.pack(side='left')
        self.allow_count_label = ttk.Label(permission_filter_frame, text='Allow: 0 distinct')
        self.allow_count_label.pack(side='right', padx=(6, 0))
        self.deny_count_label = ttk.Label(permission_filter_frame, text='Deny: 0 distinct')
        self.deny_count_label.pack(side='right', padx=(6, 0))
        self.add_context_help(permission_label, 'Filter both Allow and Deny tables by permission name.')
        self.add_context_help(self.permission_search, 'Show permission rows whose permission name contains this text.')
        self.add_context_help(self.allow_count_label, 'Unique permission names currently displayed in the Allow table.')
        self.add_context_help(self.deny_count_label, 'Unique permission names currently displayed in the Deny table.')
        detail_pane = ttk.Frame(right_frame)
        detail_pane.pack(fill='both', expand=True, padx=5, pady=(0, 5))

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
            columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            display_columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            column_widths={'Permission': 300, 'Conditional': 90, 'Source': 90, 'Inherited': 85, 'Inherited From': 150},
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
            columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            display_columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            column_widths={'Permission': 300, 'Conditional': 90, 'Source': 90, 'Inherited': 85, 'Inherited From': 150},
            data=[],
        )
        self.deny_data_table.pack(fill='both', expand=True)
        self._selected_allow_rows: list[dict[str, Any]] = []
        self._selected_deny_rows: list[dict[str, Any]] = []
        self._visible_allow_rows: list[dict[str, Any]] = []
        self._visible_deny_rows: list[dict[str, Any]] = []
        self.unmapped_frame = ttk.LabelFrame(bottom_section, text='Unmapped / Excluded Statements')
        self.unmapped_frame.configure(height=170)
        self.unmapped_frame.grid_propagate(False)
        self.unmapped_frame.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=3, pady=(8, 0))
        self.unmapped_frame.grid_remove()
        bottom_section.grid_rowconfigure(1, weight=0)
        self.unmapped_table = None
        self.add_context_help(
            self.unmapped_frame,
            'Statements excluded from permission facts, with the reason and source policy details for review.',
        )
        self.permissions_tree.bind('<<TreeviewSelect>>', self.on_tree_selection)
        self.permissions_tree.bind('<Button-3>', self._on_principal_context_menu)
        self.permissions_tree.bind('<Button-2>', self._on_principal_context_menu)
        self.permissions_tree.tag_configure('compartment', font=('TkDefaultFont', 10, 'bold'))
        self.permissions_tree.tag_configure('subject', font=('TkDefaultFont', 9))
        self.principal_query_var.trace_add('write', lambda *_: self.populate_tree())
        self.path_query_var.trace_add('write', lambda *_: self.populate_tree())
        self.principal_type_combo.bind('<<ComboboxSelected>>', lambda _event: self.populate_tree())
        self.permission_query_var.trace_add('write', lambda *_: self._refresh_permission_tables())

    def _report_service(self) -> PermissionsReportService:
        context = getattr(self.app, 'app_context', None)
        if context is not None:
            context.intelligence = self.app.policy_intelligence
            return PermissionsReportService(context)
        return PermissionsReportService(SimpleNamespace(intelligence=self.app.policy_intelligence))

    def enable_widgets_after_load(self):
        # populate tree with updated report data
        self.populate_tree()

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Apply main settings for context help and font size.
        """
        super().apply_settings(context_help, font_size)

    def populate_tree(self):
        selected_path = selected_subject = None
        selection = self.permissions_tree.selection()
        if selection:
            selected_item = selection[0]
            selected_parent = self.permissions_tree.parent(selected_item)
            if selected_parent:
                selected_path = self.permissions_tree.item(selected_parent, 'text')
                selected_values = self.permissions_tree.item(selected_item, 'values')
                selected_subject = selected_values[1] if len(selected_values) > 1 else None
        for item in self.permissions_tree.get_children():
            self.permissions_tree.delete(item)
        tree_payload = self._report_service().get_tree(
            show_inherited_principals=self.show_inherited_principals_var.get(),
            principal_query=self.principal_query_var.get(),
            path_query=self.path_query_var.get(),
            principal_type=self.principal_type_var.get(),
            include_prospective=self.include_prospective_var.get(),
        )
        available_types = ['All types', *tree_payload.get('principal_types', [])]
        self.principal_type_combo.configure(values=available_types)
        if self.principal_type_var.get() not in available_types:
            self.principal_type_var.set('All types')
        paths = tree_payload.get('paths', [])
        if not paths:
            logger.info('No permissions report data available to populate tree')
            self._selected_allow_rows = []
            self._selected_deny_rows = []
            self._visible_allow_rows = []
            self._visible_deny_rows = []
            self.allow_data_table.update_data([])
            self.deny_data_table.update_data([])
            self._update_permission_counts()
            return
        restored_selection = None
        for path_row in paths:
            path = path_row.get('path', '')
            path_node = self.permissions_tree.insert(
                '', 'end', text=path, values=('Compartment',), tags=('compartment',)
            )
            for subject_row in path_row.get('subjects', []):
                subject_key = subject_row.get('subject_key', '')
                subject_type = subject_row.get('subject_type', 'unknown')
                inherited_from = subject_row.get('inherited_from') or ''
                subject_node = self.permissions_tree.insert(
                    path_node,
                    'end',
                    text=subject_row.get('display_name') or subject_key,
                    values=(subject_type, subject_key, inherited_from),
                    tags=('subject',),
                )
                if path == selected_path and subject_key == selected_subject:
                    restored_selection = subject_node
        if restored_selection:
            self.permissions_tree.selection_set(restored_selection)
            self.permissions_tree.see(restored_selection)
            self.on_tree_selection(None)
            return
        self._selected_allow_rows = []
        self._selected_deny_rows = []
        self._visible_allow_rows = []
        self._visible_deny_rows = []
        self.allow_data_table.update_data([])
        self.deny_data_table.update_data([])
        self._update_permission_counts()

    def _filter_permission_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query = self.permission_query_var.get().strip().casefold()
        if not query:
            return list(rows)
        return [row for row in rows if query in str(row.get('Permission') or '').casefold()]

    def _refresh_permission_tables(self):
        self._visible_allow_rows = self._filter_permission_rows(self._selected_allow_rows)
        self._visible_deny_rows = self._filter_permission_rows(self._selected_deny_rows)
        if hasattr(self, 'allow_data_table'):
            self.allow_data_table.update_data(self._visible_allow_rows)
        if hasattr(self, 'deny_data_table'):
            self.deny_data_table.update_data(self._visible_deny_rows)
        self._update_permission_counts()

    @staticmethod
    def _distinct_permission_count(rows: list[dict[str, Any]]) -> int:
        permissions = set()
        for row in rows:
            permission = str(row.get('permission_key') or row.get('Permission') or '')
            permission = permission.split(' (inherited from ', 1)[0].strip().casefold()
            if permission:
                permissions.add(permission)
        return len(permissions)

    def _update_permission_counts(self):
        allow_count = self._distinct_permission_count(self._visible_allow_rows)
        deny_count = self._distinct_permission_count(self._visible_deny_rows)
        self.allow_count_label.configure(text=f'Allow: {allow_count} distinct')
        self.deny_count_label.configure(text=f'Deny: {deny_count} distinct')

    def _toggle_unmapped(self):
        if not self.show_unmapped_var.get():
            self.unmapped_frame.grid_remove()
            self.unmapped_frame.master.grid_rowconfigure(1, weight=0)
            return
        rows = [
            {
                'Category': row.get('category', ''),
                'Reason': row.get('reason', ''),
                'Policy': row.get('policy_name', ''),
                'Effect': row.get('action', ''),
                'Verb': row.get('verb', ''),
                'Resource': row.get('resource', ''),
                'Statement': row.get('statement_text', ''),
            }
            for row in self._report_service().get_exclusions(include_prospective=self.include_prospective_var.get())
        ]
        if self.unmapped_table is not None:
            self.unmapped_table.destroy()
        self.unmapped_table = DataTable(
            self.unmapped_frame,
            columns=['Category', 'Reason', 'Policy', 'Effect', 'Verb', 'Resource', 'Statement'],
            display_columns=['Category', 'Reason', 'Policy', 'Effect', 'Verb', 'Resource', 'Statement'],
            column_widths={
                'Category': 150,
                'Reason': 230,
                'Policy': 150,
                'Effect': 80,
                'Verb': 80,
                'Resource': 130,
                'Statement': 360,
            },
            data=rows,
        )
        self.unmapped_table.pack(fill='both', expand=True)
        self.unmapped_frame.master.grid_rowconfigure(1, weight=2)
        self.unmapped_frame.grid()

    def _toggle_prospective(self):
        self.populate_tree()
        if self.show_unmapped_var.get():
            self._toggle_unmapped()

    def _on_principal_context_menu(self, event):
        row_id = self.permissions_tree.identify_row(event.y)
        if not row_id or not self.permissions_tree.parent(row_id):
            return
        self.permissions_tree.selection_set(row_id)
        principal_key = str(self.permissions_tree.item(row_id).get('values', ['', ''])[1] or '')
        principal_type = principal_key.partition(':')[0].casefold()
        menu = tk.Menu(self, tearoff=0)
        if principal_type in {'group', 'group-id'}:
            menu.add_command(label='Find in Groups / Users', command=lambda: self._navigate_to_group(principal_key))
        elif principal_type in {'dynamic-group', 'dynamic-group-id'}:
            menu.add_command(
                label='Find in Dynamic Groups', command=lambda: self._navigate_to_dynamic_group(principal_key)
            )
        elif principal_type in {'resource-principal', 'resource_principal', 'oke-workload-identity'}:
            menu.add_command(
                label='Find in Workload Principals',
                command=lambda: self._navigate_to_workload_principal(principal_key),
            )
        else:
            return
        menu.tk_popup(event.x_root, event.y_root)

    @staticmethod
    def _principal_key_parts(principal_key: str) -> tuple[str, str]:
        _principal_type, _separator, payload = principal_key.partition(':')
        domain, slash, name = payload.partition('/')
        return (domain, name) if slash else ('', payload)

    def _navigate_to_group(self, principal_key: str):
        tab = self.app.users_tab
        _domain, name = self._principal_key_parts(principal_key)
        self.app.notebook.select(tab)
        tab.groups_option_var.set('GROUPS')
        # The Groups / Users search is a name filter; domain-qualified corpus
        # keys carry a domain, but the tab's search field accepts group names.
        tab.user_group_search.set(name)

    def _navigate_to_dynamic_group(self, principal_key: str):
        tab = self.app.dynamic_groups_tab
        domain, name = self._principal_key_parts(principal_key)
        self.app.notebook.select(tab)
        tab.domain_filter_var.set('')
        tab.dg_name_var.set('')
        tab.dg_rule_var.set('')
        tab.dg_ocid_var.set('')
        if principal_key.casefold().startswith('dynamic-group-id:'):
            tab.dg_ocid_var.set(name or domain)
        else:
            tab.domain_filter_var.set(domain)
            tab.dg_name_var.set(name)

    def _navigate_to_workload_principal(self, principal_key: str):
        tab = self.app.resource_principals_tab
        principal_type, _separator, payload = principal_key.partition(':')
        self.app.notebook.select(tab)
        if principal_type.casefold() == 'oke-workload-identity':
            cluster, _, identity = payload.partition('/')
            namespace, _, service_account = identity.partition('/')
            tab.principals_style_var.set('OKE Workload Identity')
            tab.oke_cluster_id_var.set('' if cluster == 'unknown' else cluster)
            tab.oke_namespace_var.set('' if namespace == 'unknown' else namespace)
            tab.oke_service_account_var.set('' if service_account == 'unknown' else service_account)
            return

        resource_type, _, compartment_id = payload.partition('/')
        tab.principals_style_var.set('any-user / any-group')
        matching_type = next(
            (value for value in tab.resource_type_list if value.casefold() == resource_type.casefold()),
            'Any',
        )
        tab.resource_type_var.set(matching_type)
        tab.resource_compartment_ocid_var.set('' if compartment_id == 'unknown' else compartment_id)

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
        detail_payload = self._report_service().get_details(
            path_key=path_key,
            subject_key=subject_key,
            include_prospective=self.include_prospective_var.get(),
            include_inherited=self.show_inherited_principals_var.get(),
        )
        allow_rows = [
            {
                'Permission': row.get('permission') or '',
                'Conditional': str(row.get('conditional', False)),
                'Source': 'Prospective' if row.get('prospective') else 'Existing',
                'Inherited': 'Yes' if row.get('inherited') else 'No',
                'Inherited From': row.get('inherited_from') or '',
                'Statement Text': row.get('statement_text') or '',
            }
            for row in detail_payload.get('allow_rows', [])
        ]
        deny_rows = [
            {
                'Permission': row.get('permission') or '',
                'Conditional': str(row.get('conditional', False)),
                'Source': 'Prospective' if row.get('prospective') else 'Existing',
                'Inherited': 'Yes' if row.get('inherited') else 'No',
                'Inherited From': row.get('inherited_from') or '',
                'Statement Text': row.get('statement_text') or '',
            }
            for row in detail_payload.get('deny_rows', [])
        ]

        # Destroy existing tables to avoid duplication
        for widget in self.allow_dt_frame.winfo_children():
            widget.destroy()
        for widget in self.deny_dt_frame.winfo_children():
            widget.destroy()

        self._selected_allow_rows = allow_rows
        self._selected_deny_rows = deny_rows
        self._visible_allow_rows = self._filter_permission_rows(allow_rows)
        self._visible_deny_rows = self._filter_permission_rows(deny_rows)

        # Custom right-click: Show the source policy statement.
        def policy_right_click(rows, row_idx):
            if row_idx >= len(rows):
                return None
            data = rows[row_idx]
            menu = tk.Menu(self, tearoff=0)
            statement_text = data.get('Statement Text', '')
            menu.add_command(label='Show Policy Statement', command=lambda: self._show_policy_statement(statement_text))
            return menu

        self.allow_data_table = DataTable(
            self.allow_dt_frame,
            columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            display_columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            column_widths={'Permission': 300, 'Conditional': 90, 'Source': 90, 'Inherited': 85, 'Inherited From': 150},
            data=self._visible_allow_rows,
            row_context_menu_callback=lambda row_idx: policy_right_click(self._visible_allow_rows, row_idx),
        )
        self.allow_data_table.pack(fill='both', expand=True)
        self.deny_data_table = DataTable(
            self.deny_dt_frame,
            columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            display_columns=['Permission', 'Conditional', 'Source', 'Inherited', 'Inherited From'],
            column_widths={'Permission': 300, 'Conditional': 90, 'Source': 90, 'Inherited': 85, 'Inherited From': 150},
            data=self._visible_deny_rows,
            row_context_menu_callback=lambda row_idx: policy_right_click(self._visible_deny_rows, row_idx),
        )
        self.deny_data_table.pack(fill='both', expand=True)
        self._update_permission_counts()

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
