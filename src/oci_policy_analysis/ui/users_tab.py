##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# users_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.logger import get_logger
from oci_policy_analysis.logic.models import Group, GroupSearch, PolicySearch, User, UserSearch
from oci_policy_analysis.ui.data_table import DataTable
from oci_policy_analysis.ui.helpers import for_display_group, for_display_policy, for_display_user

# Global logger for this module
logger = get_logger(component='users_tab')

GROUPS_COLUMNS = ['Domain Name', 'Group Name', 'Group OCID']
GROUPS_COLUMNS_WIDTHS = {'Domain Name': 150, 'Group Name': 300, 'Group OCID': 450}

USERS_COLUMNS = ['Domain Name', 'Username', 'Display Name', 'Primary Email', 'User ID']
USERS_COLUMNS_WIDTHS = {
    'Username': 150,
    'Display Name': 200,
    'Primary Email': 200,
    'User ID': 300,
    'Domain Name': 150,
}

BASIC_POLICY_COLUMNS = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Effective Path', 'Valid']
ALL_POLICY_COLUMNS = [
    'Policy Name',
    'Policy OCID',
    'Compartment OCID',
    'Policy Compartment',
    'Statement Text',
    'Valid',
    'Invalid Reason',
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
POLICY_COLUMN_WIDTHS = {
    'Policy Name': 250,
    'Policy OCID': 450,
    'Compartment OCID': 450,
    'Policy Compartment': 250,
    'Statement Text': 700,
    'Valid': 80,
    'Invalid Reason': 200,
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


class UsersTab(ttk.Frame):
    """Example data-driven tab that can update the bottom entry."""

    def __init__(self, parent, app, policy_repo: PolicyAnalysisRepository):  # noqa: C901
        super().__init__(parent)
        self.app = app
        self.policy_compartment_analysis: PolicyAnalysisRepository = policy_repo

        self.grid_rowconfigure(0, weight=2)
        self.grid_rowconfigure(1, weight=7)
        # self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # For this tab, on the top left, include a table for all Groups with Domain/Group.  Allow Multi-Select
        # On the top right, include a table for all users, which is unfiltered, but if any group is selected on the left,
        # only show users in those groups.  This table is multi-select as well.
        # Depending on what is selected on the right, show all policies for those users in the bottom frame.
        # Bottom Frame is a policy table, similar to the other tabs, but only showing policies for the selected users/groups.
        # Similar AI analysis as well.

        # Frame for top (left form, right table)
        frm_user_top = ttk.Frame(self)
        frm_user_top.grid_rowconfigure(0, weight=1)
        frm_user_top.grid_rowconfigure(1, weight=1)
        frm_user_top.grid_columnconfigure(0, weight=4)  # Options
        frm_user_top.grid_columnconfigure(1, weight=6)  # Table
        # frm_user_top.grid_columnconfigure(2, weight=4)
        frm_user_top.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Frame for Policy Statements (row 1)
        frm_users_policies = ttk.Frame(self)
        frm_users_policies.grid_rowconfigure(0, weight=1)
        frm_users_policies.grid_rowconfigure(1, weight=9)
        frm_users_policies.grid_columnconfigure(0, weight=1)
        frm_users_policies.grid_columnconfigure(1, weight=1)
        frm_users_policies.grid_columnconfigure(2, weight=1)
        frm_users_policies.grid_columnconfigure(3, weight=7)
        frm_users_policies.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Variables
        self.chk_show_expanded = tk.BooleanVar(value=False)

        def users_group_selection_callback(selected_rows: list[dict]) -> None:
            """When a Group is selected, update the users/groups and policy statements below"""
            groups_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.debug(f"Selected Group: {row.get('Domain Name')} / {row.get('Group Name')}")
                if 'Group Name' in row:
                    groups_for_filter.append(
                        {'domain_name': row.get('Domain Name'), 'group_name': row.get('Group Name')}
                    )
            logger.info(f'Groups for filter: {groups_for_filter}')

            self._update_user_analysis_policy_output(groups_for_filter=groups_for_filter, users_for_filter=None)

        def users_user_selection_callback(selected_rows: list[dict]) -> None:
            """When a User is selected, update the users/groups and policy statements below"""
            users_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.debug(f"Selected User: {row.get('Domain Name')} / {row.get('Username')}")
                if 'Username' in row:
                    users_for_filter.append({'domain_name': row.get('Domain Name'), 'user_name': row.get('Username')})
            logger.info(f'Users for filter: {users_for_filter}')

            self._update_user_analysis_policy_output(groups_for_filter=None, users_for_filter=users_for_filter)

        def users_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.app.policy_query_var.set(selected_statement)
                # self.policy_analyze_statement_var.set(selected_statement)
            else:
                self.app.policy_query_var.set('')

        def switch_groups_users_selection(*args):
            """probably get rid of this"""
            logger.debug('Calling update for users')
            self._update_user_analysis_output()

        def update_search(*args):
            """probably get rid of this"""
            logger.debug(f'Updating search: {self.user_group_search.get()}')
            self._update_user_analysis_output()

        def clear_filter():
            self.user_group_search.set('')

        def update_user_policy_output():
            # Change to more output
            if self.chk_show_expanded.get():
                self.users_policy_table.set_display_columns(ALL_POLICY_COLUMNS)
            else:
                self.users_policy_table.set_display_columns(BASIC_POLICY_COLUMNS)
            logger.info(f'Updated display for expanded output: {self.chk_show_expanded.get()}')

        # Frame for selection and Search
        frm_user_selection = ttk.Frame(frm_user_top)
        frm_user_selection.grid_columnconfigure(0, weight=3)
        frm_user_selection.grid_columnconfigure(1, weight=5)
        frm_user_selection.grid_columnconfigure(2, weight=2)
        frm_user_selection.grid(row=0, column=0, padx=5, pady=2, sticky='w')

        # User / Group Selection
        ttk.Label(frm_user_selection, text='Select Groups / Users').grid(
            row=0, column=0, columnspan=2, padx=5, pady=2, sticky='w'
        )

        # Selection Dropdown (users or groups)
        self.groups_option_var = tk.StringVar(value='GROUPS')
        self.groups_users_dropdown = ttk.OptionMenu(
            frm_user_selection,
            self.groups_option_var,
            self.groups_option_var.get(),
            *['GROUPS', 'USERS'],
            # bootstyle='default',
            command=switch_groups_users_selection,
        )
        self.groups_users_dropdown.grid(row=0, column=2, padx=5, pady=5, sticky='ew')

        ttk.Label(frm_user_selection, text='Search').grid(row=1, column=0, padx=5, pady=2, sticky='w')

        # Search with trace
        self.user_group_search = tk.StringVar()
        ttk.Entry(frm_user_selection, textvariable=self.user_group_search, width=35).grid(
            row=1, column=1, columnspan=2, padx=5, pady=2, sticky='ew'
        )
        self.user_group_search.trace_add('write', update_search)
        ttk.Label(
            frm_user_selection, text='Search user/group name using | for logical OR\nExamples: user1|user2 grp1|grp2'
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky='w')
        self.btn_clear_groups_users = ttk.Button(frm_user_selection, text='Clear Filter', command=clear_filter)
        self.btn_clear_groups_users.grid(row=2, column=2, padx=5, pady=5, sticky='ew')

        self.user_selected_groups = ttk.Label(frm_user_selection, text='Selected Groups: ')
        self.user_selected_groups.grid(row=3, column=0, columnspan=3, padx=5, pady=2, sticky='w')

        self.selected_groups_table = DataTable(
            frm_user_selection,
            columns=['Domain', 'Group'],
            display_columns=['Domain', 'Group'],
            data=[],
            column_widths={'Domain': 200, 'Group': 300},
            # font_size=10,
            # selection_callback=users_group_selection_callback,
            # multi_select=True,
        )
        self.selected_groups_table.grid(row=4, column=0, columnspan=3, padx=5, pady=2, sticky='w')

        # Table for Groups on the left
        # Groups Table
        self.users_groups_table = DataTable(
            frm_user_top,
            columns=GROUPS_COLUMNS,
            display_columns=GROUPS_COLUMNS,
            data=[],
            column_widths=GROUPS_COLUMNS_WIDTHS,
            # font_size=10,
            selection_callback=users_group_selection_callback,
            multi_select=True,
        )

        # Users Table
        self.users_users_table = DataTable(
            frm_user_top,
            columns=USERS_COLUMNS,
            display_columns=USERS_COLUMNS,
            data=[],
            column_widths=USERS_COLUMNS_WIDTHS,
            # font_size=10,
            selection_callback=users_user_selection_callback,
            multi_select=True,
        )

        # Users Page Policy Table
        self.user_label_count = ttk.Label(frm_users_policies, text='Policy Statements (Filtered): 0')
        self.user_label_count.grid(row=0, column=0, padx=5, pady=3, sticky='w')

        ttk.Separator(frm_users_policies, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)

        ttk.Checkbutton(
            frm_users_policies, text='Parsed Output', variable=self.chk_show_expanded, command=update_user_policy_output
        ).grid(row=0, column=2, padx=5, pady=3)

        # Policy Table
        self.users_policy_table = DataTable(
            frm_users_policies,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            # font_size=10,
            selection_callback=users_policy_selection_callback,
            multi_select=False,
        )
        self.users_policy_table.grid(row=1, column=0, columnspan=4, sticky='nsew')

    def _update_user_analysis_output(self):
        # TODO: Compartment Analysis
        logger.info(f'Displaying: {self.groups_option_var.get()} with search of {self.user_group_search.get()}')

        # Grid the correct table
        if self.groups_option_var.get() == 'GROUPS':
            # Load the groups into grid and search
            self.users_users_table.grid_forget()
            self.users_groups_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Only filter on name for now
            group_filter: GroupSearch = GroupSearch(
                group_name=self.user_group_search.get().split('|') if self.user_group_search.get() else None,
            )
            # Filter and display
            filtered_groups: list[Group] = self.policy_compartment_analysis.filter_groups(group_filter=group_filter)
            display_groups = [for_display_group(g) for g in filtered_groups]
            self.users_groups_table.update_data(display_groups)
            logger.info(f'Loaded {len(filtered_groups)} groups into table')
        elif self.groups_option_var.get() == 'USERS':
            self.users_groups_table.grid_forget()
            self.users_users_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Only filter on username for now
            user_filter: UserSearch = UserSearch(
                search=self.user_group_search.get().split('|') if self.user_group_search.get() else None,
            )
            # Filter and display
            filtered_users: list[User] = self.policy_compartment_analysis.filter_users(user_filter=user_filter)
            display_users = [for_display_user(u) for u in filtered_users]
            self.users_users_table.update_data(display_users)
            logger.info(f'Loaded {len(filtered_users)} users into data')
        else:
            logger.warning('Should not get here')

    def _update_user_analysis_policy_output(self, groups_for_filter, users_for_filter):
        """Update the policy statements based on the selected groups and/or users"""
        # Take the list of groups, make a group filter, and update policy table
        logger.info(f'Searching for policies for groups: {groups_for_filter} and users: {users_for_filter}')
        # create an exact_groups filter for filter_policy_statements

        exact_groups_filter: list[Group] = groups_for_filter
        exact_users_filter: list[User] = users_for_filter
        exact_groups_users_filter = PolicySearch(exact_groups=exact_groups_filter, exact_users=exact_users_filter)
        filtered_policies = self.policy_compartment_analysis.filter_policy_statements(filters=exact_groups_users_filter)
        # Use helper to normalize for display
        display_policies = [for_display_policy(st) for st in filtered_policies]
        self.users_policy_table.update_data(display_policies)

        # Update the labels and table
        # Create a list of dict for the table
        # If all we have is users, grab the groups for them
        selected_groups_for_table = []
        if groups_for_filter:
            for group in groups_for_filter:
                dom = group.get('domain_name') or 'Default'
                gr = group.get('group_name')
                selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        elif users_for_filter:
            # If all we have is users, grab the groups for them
            for user in users_for_filter:
                groups_for_user = self.policy_compartment_analysis.get_groups_for_user(user)
                for group in groups_for_user:
                    dom = group.get('domain_name') or 'Default'
                    gr = group.get('group_name')
                    selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        # Update the group and policies table
        self.selected_groups_table.update_data(selected_groups_for_table)
        self.user_label_count.configure(text=f'Policy Statements (Filtered): {len(filtered_policies)}')
