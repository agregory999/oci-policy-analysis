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
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.helpers import for_display_group, for_display_policy, for_display_user
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import Group, GroupSearch, PolicySearch, User, UserSearch
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.ui.data_table import DataTable

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
    'Invalid Reasons',
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
    'Invalid Reasons': 200,
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
    """
    Users Tab for OCI Policy Analysis UI.
    Allows selection of Groups or Users, and displays associated policy statements.
    Supports filtering and detailed policy statement views.

    """

    def __init__(self, parent, app):  # noqa: C901
        super().__init__(parent)

        # Reference to main app and data repository
        self.app = app
        self.policy_compartment_analysis: PolicyAnalysisRepository = app.policy_compartment_analysis

        # --- UI state variables and widget handles ---
        self.chk_show_expanded = tk.BooleanVar(value=False)
        self.chk_show_any_group_user = tk.BooleanVar(value=False)
        self.groups_option_var = tk.StringVar(value='GROUPS')
        self.user_group_search = tk.StringVar()
        self.users_groups_table = None
        self.users_users_table = None
        self.users_policy_table = None
        self.selected_groups_table = None
        self.user_label_count = None

        # --- Page Help setup (adapted from policies_tab.py) ---
        self.page_help_text = (
            'Select users and groups to view their effective policy statements. '
            'Use filters to narrow the results below. '
            'Mouse over each section for tips.'
        )
        self.page_help_frame = ttk.LabelFrame(self, text='Page Help')
        self.page_help_label = tk.Label(self.page_help_frame, anchor='w', justify='left', wraplength=900)
        self.page_help_label.pack(fill='x', padx=14, pady=5)
        self._apply_page_help_style()
        self.update_page_help_visibility()
        self.set_page_help_text(self.page_help_text)

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

        # --- SECTION 1: User/Group Selection ---
        self.lf_user_selection = ttk.LabelFrame(self, text='User/Group Selection')
        self.lf_user_selection.pack(fill='x', padx=12, pady=(8, 0))

        def _show_user_selection_help(_event=None):
            self.set_page_help_text(
                'Select one or more groups or users. Use the search and dropdown to filter. Selection drives statement display below.'
            )

        def _restore_user_selection_help(_event=None):
            self.set_page_help_text(self.page_help_text)

        self.lf_user_selection.bind('<Enter>', _show_user_selection_help)
        self.lf_user_selection.bind('<Leave>', _restore_user_selection_help)

        # Retain old frm_user_top as the organizer within the label frame
        self._build_ui_user_group_selection(self.lf_user_selection)

    def _build_ui_user_group_selection(self, parent):  # noqa: C901
        frm_user_top = ttk.Frame(parent)
        frm_user_top.grid_rowconfigure(0, weight=1)
        frm_user_top.grid_rowconfigure(1, weight=1)
        frm_user_top.grid_columnconfigure(0, weight=4)
        frm_user_top.grid_columnconfigure(1, weight=6)
        frm_user_top.grid(row=0, column=0, sticky='nsew', padx=2, pady=2)

        # --- Selection/Search Frame (left) ---
        frm_user_selection = ttk.Frame(frm_user_top)
        frm_user_selection.grid_columnconfigure(0, weight=3)
        frm_user_selection.grid_columnconfigure(1, weight=5)
        frm_user_selection.grid_columnconfigure(2, weight=2)
        frm_user_selection.grid(row=0, column=0, padx=5, pady=2, sticky='w')

        # Label: Select Groups / Users
        ttk.Label(frm_user_selection, text='Select Groups / Users').grid(
            row=0, column=0, columnspan=2, padx=5, pady=2, sticky='w'
        )
        # Dropdown: GROUPS/USERS
        self.groups_users_dropdown = ttk.OptionMenu(
            frm_user_selection,
            self.groups_option_var,
            self.groups_option_var.get(),
            *['GROUPS', 'USERS'],
            command=lambda *_: self.update_user_analysis_output(),
        )
        self.groups_users_dropdown.grid(row=0, column=2, padx=5, pady=5, sticky='ew')

        # Label: Search, Entry: user_group_search
        ttk.Label(frm_user_selection, text='Search').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        entry_search = ttk.Entry(frm_user_selection, textvariable=self.user_group_search, width=35)
        entry_search.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky='ew')
        self.user_group_search.trace_add('write', lambda *_: self.update_user_analysis_output())

        # Search instructions
        ttk.Label(
            frm_user_selection, text='Search user/group name using | for logical OR\nExamples: user1|user2 grp1|grp2'
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky='w')

        # Button: Clear Filter
        self.btn_clear_groups_users = ttk.Button(
            frm_user_selection, text='Clear Filter', command=lambda: self.user_group_search.set('')
        )
        self.btn_clear_groups_users.grid(row=2, column=2, padx=5, pady=5, sticky='ew')

        # Selected Groups label & table
        self.user_selected_groups = ttk.Label(frm_user_selection, text='Selected Groups: ')
        self.user_selected_groups.grid(row=3, column=0, columnspan=3, padx=5, pady=2, sticky='w')

        self.selected_groups_table = DataTable(
            frm_user_selection,
            columns=['Domain', 'Group'],
            display_columns=['Domain', 'Group'],
            data=[],
            column_widths={'Domain': 200, 'Group': 300},
        )
        self.selected_groups_table.grid(row=4, column=0, columnspan=3, padx=5, pady=2, sticky='w')

        # --- Table area: groups/users table (right) ---
        # --- Callbacks for table selection ---
        def users_group_selection_callback(selected_rows: list[dict]) -> None:
            logger.info('>>> users_group_selection_callback was called')
            """When a Group is selected, update the selected groups and filtered policy statements."""
            groups_for_filter = []
            for row in selected_rows:
                logger.debug(f"Selected Group: {row.get('Domain Name')} / {row.get('Group Name')}")
                if 'Group Name' in row:
                    groups_for_filter.append(
                        {'domain_name': row.get('Domain Name'), 'group_name': row.get('Group Name')}
                    )
            logger.info(f'Groups for filter: {groups_for_filter}')
            self._update_user_analysis_policy_output(groups_for_filter=groups_for_filter, users_for_filter=None)

        def users_user_selection_callback(selected_rows: list[dict]) -> None:
            logger.info('>>> users_user_selection_callback was called')
            """When a User is selected, update the selected groups (from user) and filtered policy statements."""
            users_for_filter = []
            for row in selected_rows:
                logger.debug(f"Selected User: {row.get('Domain Name')} / {row.get('Username')}")
                if 'Username' in row:
                    users_for_filter.append({'domain_name': row.get('Domain Name'), 'user_name': row.get('Username')})
            logger.info(f'Users for filter: {users_for_filter}')
            self._update_user_analysis_policy_output(groups_for_filter=None, users_for_filter=users_for_filter)

        self.users_groups_table = DataTable(
            frm_user_top,
            columns=GROUPS_COLUMNS,
            display_columns=GROUPS_COLUMNS,
            data=[],
            column_widths=GROUPS_COLUMNS_WIDTHS,
            selection_callback=users_group_selection_callback,
            multi_select=True,
        )
        self.users_users_table = DataTable(
            frm_user_top,
            columns=USERS_COLUMNS,
            display_columns=USERS_COLUMNS,
            data=[],
            column_widths=USERS_COLUMNS_WIDTHS,
            selection_callback=users_user_selection_callback,
            multi_select=True,
        )

        # --- SECTION 2: Statement Filters ---
        self.lf_statement_filters = ttk.LabelFrame(self, text='Statement Filters')
        self.lf_statement_filters.pack(fill='x', padx=12, pady=(12, 0))

        def _show_statement_filters_help(_event=None):
            self.set_page_help_text(
                'Configure filtering options for statements, such as parsed/expanded output or user/group scope.'
            )

        def _restore_statement_filters_help(_event=None):
            self.set_page_help_text(self.page_help_text)

        self.lf_statement_filters.bind('<Enter>', _show_statement_filters_help)
        self.lf_statement_filters.bind('<Leave>', _restore_statement_filters_help)

        # A frame for filter checkboxes (will be filled in in later step)
        self._build_ui_statement_filters(self.lf_statement_filters)

        # --- SECTION 3: Filtered Policy Statements ---
        self.lf_filtered_statements = ttk.LabelFrame(self, text='Filtered Policy Statements')
        self.lf_filtered_statements.pack(fill='both', expand=True, padx=10, pady=10)

        def _show_filtered_statements_help(_event=None):
            self.set_page_help_text(
                'Review the resulting policy statements for your selected users/groups. Adjust filters above as needed.'
            )

        def _restore_filtered_statements_help(_event=None):
            self.set_page_help_text(self.page_help_text)

        self.lf_filtered_statements.bind('<Enter>', _show_filtered_statements_help)
        self.lf_filtered_statements.bind('<Leave>', _restore_filtered_statements_help)

        # Data Table for filtered policy statements
        self.users_policy_table = DataTable(
            self.lf_filtered_statements,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            # font_size=10,
            selection_callback=None,  # Will be set/rewired as needed,
            multi_select=False,
        )
        self.users_policy_table.pack(expand=True, fill='both', padx=0, pady=0)

    def _build_ui_statement_filters(self, parent):
        # Everything packed horizontally, no grid.
        self.user_label_count = ttk.Label(parent, text='Policy Statements (Filtered): 0')
        self.user_label_count.pack(side='left', padx=8, pady=(0, 3))

        ttk.Checkbutton(
            parent,
            text='Parsed Output',
            variable=self.chk_show_expanded,
            command=lambda: self.update_user_policy_output(),
        ).pack(side='left', padx=10)

        ttk.Checkbutton(
            parent,
            text='Show any-group / any-user',
            variable=self.chk_show_any_group_user,
            command=lambda: self.update_user_policy_output(),
        ).pack(side='left', padx=10)

    def update_user_analysis_output(self):
        """
        Update the user/group table based on selection and search.
        Called initially after load from main class and when search or selection changes.
        """
        logger.info(f'Displaying: {self.groups_option_var.get()} with search of {self.user_group_search.get()}')

        # Defensive: Only try to display tables if they've been initialized
        if self.users_groups_table is None or self.users_users_table is None:
            logger.warning('Table widgets not initialized yet; skipping analysis output update.')
            return

        # Grid the correct table
        if self.groups_option_var.get() == 'GROUPS':
            # Load the groups into grid and search
            self.users_users_table.grid_forget()
            self.users_groups_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Only filter on name for now
            group_filter: GroupSearch = GroupSearch(
                group_name=self.user_group_search.get().split('|') if self.user_group_search.get() else [],
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
                search=self.user_group_search.get().split('|') if self.user_group_search.get() else [],
            )
            # Filter and display
            filtered_users: list[User] = self.policy_compartment_analysis.filter_users(user_filter=user_filter)
            display_users = [for_display_user(u) for u in filtered_users]
            self.users_users_table.update_data(display_users)
            logger.info(f'Loaded {len(filtered_users)} users into data')
        else:
            logger.warning('Should not get here')

    def update_user_policy_output(self):
        """
        Update the display elements for the user analysis policy statements.
        Called when the selection of groups/users changes, or when the checkboxes change.

        Args:
            groups_for_filter (list[Group], optional): List of groups to filter policies for. Defaults to None.
            users_for_filter (list[User], optional): List of users to filter policies for. Defaults to None.
        """
        # Defensive: Exit if the tables/labels are not built yet
        if self.users_policy_table is None or self.selected_groups_table is None or self.user_label_count is None:
            logger.warning('Policy/output table widgets not initialized yet; skipping policy output update.')
            return

        if self.chk_show_expanded.get():
            self.users_policy_table.set_display_columns(ALL_POLICY_COLUMNS)
        else:
            self.users_policy_table.set_display_columns(BASIC_POLICY_COLUMNS)
        logger.info(f'Updated display for expanded output: {self.chk_show_expanded.get()}')

        # If the show all checkbox is selected, run additional query to get any-user/any-group policies
        if self.chk_show_any_group_user.get():
            logger.info('Including any-user and any-group policies in output')
            # Create filter for any-user/any-group
            any_user_group_policies = self.policy_compartment_analysis.filter_policy_statements(
                PolicySearch(subject=['any-user', 'any-group'])
            )
            logger.info(f'Found {len(any_user_group_policies)} any-user/any-group policies')
            # Add to existing data table data in self.filtered_policies
            seen_ids = {
                getattr(st, 'internal_id', None) or st.get('statement_text', None) for st in self.filtered_policies
            }
            additional_policies = []
            for st in any_user_group_policies:
                key = getattr(st, 'internal_id', None) or st.get('statement_text', None)
                if key not in seen_ids:
                    additional_policies.append(st)
                    seen_ids.add(key)
            if len(additional_policies) > 0:
                logger.info(f'Added {len(additional_policies)} any-user/any-group policies to output')
            all_policies = list(self.filtered_policies) + additional_policies
        else:
            logger.info('Not including any-user and any-group policies in output')
            # Display only filtered policies
            all_policies = list(self.filtered_policies)
        # Update the display elements
        self.users_policy_table.update_data([for_display_policy(st) for st in all_policies])
        self.selected_groups_table.update_data(self.selected_groups_for_table)
        self.user_label_count.configure(text=f'Policy Statements (Filtered): {len(all_policies)}')

    def _update_user_analysis_policy_output(self, groups_for_filter, users_for_filter):  # noqa: C901
        """Update the policy statements based on the selected groups and/or users"""
        logger.info(f'Searching for policies for groups: {groups_for_filter} and users: {users_for_filter}')
        exact_groups_filter: list[Group] = groups_for_filter
        exact_users_filter: list[User] = users_for_filter
        exact_groups_users_filter = PolicySearch(exact_groups=exact_groups_filter, exact_users=exact_users_filter)
        self.filtered_policies = self.policy_compartment_analysis.filter_policy_statements(
            filters=exact_groups_users_filter
        )
        logger.info(f'Found {len(self.filtered_policies)} policies for selected users/groups')
        self.selected_groups_for_table = []
        if groups_for_filter:
            for group in groups_for_filter:
                dom = group.get('domain_name') or 'Default'
                gr = group.get('group_name')
                self.selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        elif users_for_filter:
            # If all we have is users, grab the groups for them
            for user in users_for_filter:
                groups_for_user = self.policy_compartment_analysis.get_groups_for_user(user)
                logger.info(f'User {user.get("user_name")} is in groups: {groups_for_user}')
                for group in groups_for_user:
                    dom = group.get('domain_name') or 'Default'
                    gr = group.get('group_name')
                    self.selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        # Call the main update_user_policy_output to refresh display
        self.update_user_policy_output()
        # self.selected_groups_table.update_data(selected_groups_for_table)
        # self.user_label_count.configure(text=f'Policy Statements (Filtered): {len(all_policies)}')

    # ----------- Page Help Methods (adapted from policies_tab.py) ----------------

    def set_page_help_text(self, text, temporary=False):
        """
        Updates the content of the page help label if visible.
        """
        # If context help setting is available in app.settings; otherwise always show it
        settings = getattr(self.app, 'settings', None)
        show_help = True if not settings else settings.get('context_help', True)
        if show_help:
            self.page_help_label.configure(text=text)
            self._apply_page_help_style()

    def update_page_help_visibility(self):
        """
        Show or hide Page Help frame based on context_help setting, always pinned at the top.
        Should be called after settings['context_help'] changes.
        """
        # Hide first, then decide whether/how to show
        self.page_help_frame.pack_forget()
        settings = getattr(self.app, 'settings', None)
        show_help = True if not settings else settings.get('context_help', True)
        if show_help:
            children = self.winfo_children()
            packed_target = None
            for child in children:
                try:
                    if getattr(child, 'winfo_manager', lambda: None)() == 'pack':
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
        Enforce consistent look for Page Help according to theme/font.
        """
        bg = self._get_style_background()
        self.page_help_frame.configure(style='Custom.TLabelframe')
        self.page_help_label.configure(bg=bg, font=self._get_help_font())

    def _get_help_font(self):
        """
        Retrieve font tuple for help label from settings.
        """
        settings = getattr(self.app, 'settings', None)
        font_size_map = {
            'Small': 9,
            'Medium': 11,
            'Large': 13,
            'Extra Large': 16,
        }
        size = 11  # default
        if settings:
            size = font_size_map.get(settings.get('font_size', 'Medium'), 11)
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
            return self.winfo_toplevel().cget('bg') if hasattr(self, 'winfo_toplevel') else '#f0f0f0'

    def refresh_context_help(self):
        """
        Public API: Call from settings tab or theme handler when help/frame status should update.
        """
        self._apply_page_help_style()
        self.update_page_help_visibility()
