import tkinter as tk
from tkinter import ttk

from logic.data_repo import IdentityDomainsAnalysis, PolicyCompartmentAnalysis
from logic.logger import get_logger
from ui.data_table import DataTable

logger = get_logger()

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

    def __init__(self, parent, app, identity_repo: IdentityDomainsAnalysis, policy_repo: PolicyCompartmentAnalysis):  # noqa: C901
        super().__init__(parent)
        self.app = app
        self.identity_repo: IdentityDomainsAnalysis = identity_repo
        self.policy_compartment_analysis: PolicyCompartmentAnalysis = policy_repo

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
                    groups_for_filter.append({'domain': row.get('Domain Name'), 'name': row.get('Group Name')})
            logger.info(f'Groups for filter: {groups_for_filter}')

            self._update_user_analysis_policy_output(groups_for_filter=groups_for_filter, users_for_filter=None)

        def users_user_selection_callback(selected_rows: list[dict]) -> None:
            """When a User is selected, update the users/groups and policy statements below"""
            users_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.debug(f"Selected User: {row.get('Domain Name')} / {row.get('Username')}")
                if 'Username' in row:
                    users_for_filter.append({'domain': row.get('Domain Name'), 'name': row.get('Username')})
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
        frm_user_selection.grid_columnconfigure(1, weight=7)
        frm_user_selection.grid(row=0, column=0, padx=5, pady=2, sticky='w')

        # User / Group Selection
        ttk.Label(frm_user_selection, text='Select Groups or Users').grid(row=0, column=0, padx=5, pady=2, sticky='w')

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
        self.groups_users_dropdown.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frm_user_selection, text='Search').grid(row=1, column=0, padx=5, pady=2, sticky='w')

        # Search with trace
        self.user_group_search = tk.StringVar()
        ttk.Entry(frm_user_selection, textvariable=self.user_group_search, width=30).grid(
            row=1, column=1, padx=5, pady=2, sticky='w'
        )
        self.user_group_search.trace_add('write', update_search)
        self.btn_clear_groups_users = ttk.Button(frm_user_selection, text='Clear Filter', command=clear_filter)
        self.btn_clear_groups_users.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='w')

        self.user_selected_groups = ttk.Label(frm_user_selection, text='Selected Groups: ')
        self.user_selected_groups.grid(row=3, column=0, columnspan=2, padx=5, pady=2, sticky='w')

        self.selected_groups_table = DataTable(
            frm_user_selection,
            columns=['Domain', 'Group'],
            display_columns=['Domain', 'Group'],
            data=[],
            column_widths={'Domain': 150, 'Group': 200},
            # font_size=10,
            # selection_callback=users_group_selection_callback,
            # multi_select=True,
        )
        self.selected_groups_table.grid(row=4, column=0, columnspan=2, padx=5, pady=2, sticky='w')

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

            # Filter and display
            filtered_groups = self.identity_repo.filter_groups(name_filter=self.user_group_search.get())
            self.users_groups_table.update_data(filtered_groups)
            logger.info(f'Loaded {len(filtered_groups)} groups into table')
        elif self.groups_option_var.get() == 'USERS':
            self.users_groups_table.grid_forget()
            self.users_users_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Filter and display
            filtered_users = self.identity_repo.filter_users(name_filter=self.user_group_search.get())
            self.users_users_table.update_data(filtered_users)
            logger.info(f'Loaded {len(filtered_users)} users into data')
        else:
            logger.warning('Should not get here')

    def _update_user_analysis_policy_output(self, groups_for_filter, users_for_filter):
        logger.info('Getting policies for groups and users')

        if users_for_filter and len(users_for_filter) > 0:
            groups_for_filter = []
            # If we only have users, populate the groups for those users
            for user in users_for_filter:
                logger.info(f'Getting groups for user: {user}')
                groups_for_user = self.identity_repo.get_groups_for_user(user)
                groups_for_filter.extend(groups_for_user)

        # Take the list of groups, make a group filter, and update policy table
        logger.info(f'Searching for policies for groups: {groups_for_filter}')
        filtered_policies = self.policy_compartment_analysis.filter_policy_statements_by_groups(
            groups_filter=groups_for_filter
        )
        self.users_policy_table.update_data(filtered_policies)

        # Update the labels and table
        # Create a list of dict for the table
        selected_groups_for_table = []
        for group in groups_for_filter:
            dom = group.get('domain') or 'Default'
            gr = group.get('name')
            selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        # Update the group and policies table
        self.selected_groups_table.update_data(selected_groups_for_table)
        self.user_label_count.configure(text=f'Policy Statements (Filtered): {len(filtered_policies)}')

    #     ttk.Label(self, text='Users').pack(anchor='w', padx=8, pady=(10, 6))

    #     self.tree = ttk.Treeview(self, columns=('id', 'name', 'role'), show='headings')
    #     self.tree.heading('id', text='ID')
    #     self.tree.heading('name', text='Name')
    #     self.tree.heading('role', text='Role')
    #     self.tree.pack(fill='both', expand=True, padx=8, pady=(0, 8))

    #     cmdbar = ttk.Frame(self)
    #     cmdbar.pack(fill='x', padx=8, pady=(0, 10))
    #     ttk.Button(cmdbar, text='Send Selected to Bottom Entry', command=self.send_selected).pack(side='left')

    #     self.users_groups_table = DataTable(
    #         self,
    #         columns=GROUPS_COLUMNS,
    #         display_columns=GROUPS_COLUMNS,
    #         data=[],
    #         column_widths=GROUPS_COLUMNS_WIDTHS,
    #         # font_size=10,
    #         # selection_callback=users_group_selection_callback,
    #         multi_select=True,
    #     )
    #     self.users_groups_table.pack(fill='both', expand=True)

    #     # Prob not nec
    #     # self.reload_data()

    # def reload_data(self):
    #     # Load the data or filter it as needed
    #     self.users_groups_table.update_data(self.identity_repo.groups)
    #     logger.info(f'Loaded data for Groups: {len(self.identity_repo.groups)}')

    # def send_selected(self):
    #     sel = self.tree.selection()
    #     if not sel:
    #         logger.info('No user selected')
    #         return
    #     vals = self.tree.item(sel[0], 'values')
    #     # Example payload to the bottom entry
    #     text = f'{vals[0]} | {vals[1]} | {vals[2]}'
    #     self.app.update_bottom_entry(text)
    #     logger.info('Sent selection to bottom entry')
