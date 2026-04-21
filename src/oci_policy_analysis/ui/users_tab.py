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

from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import Group, GroupSearch, RegularPolicyStatement, User, UserSearch
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.presentation import for_display_policy
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

# Global logger for this module
logger = get_logger(component='users_tab')

GROUPS_ALL_COLUMNS = ['Domain Name', 'Group Name', 'User Count', 'Group ID', 'Group OCID']
GROUPS_DEFAULT_COLUMNS = ['Domain Name', 'Group Name', 'User Count']
GROUPS_COLUMNS_WIDTHS = {'Domain Name': 120, 'Group Name': 250, 'User Count': 80, 'Group ID': 220, 'Group OCID': 300}

USERS_ALL_COLUMNS = ['Domain Name', 'Username', 'Display Name', 'Primary Email', 'User ID', 'User OCID']
USERS_DEFAULT_COLUMNS = ['Domain Name', 'Username', 'Display Name', 'Primary Email']
USERS_COLUMNS_WIDTHS = {
    'Username': 160,
    'Display Name': 180,
    'Primary Email': 160,
    'User ID': 249,
    'User OCID': 300,
    'Domain Name': 100,
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


class UsersTab(BaseUITab):
    """
    Users Tab for OCI Policy Analysis UI.
    Allows selection of Groups or Users, and displays associated policy statements.
    Supports filtering and detailed policy statement views.
    """

    def __init__(self, parent, app):  # noqa: C901
        default_help_text = (
            'Select users and groups to view their effective policy statements. '
            'Use filters to narrow the results below. '
            'Mouse over each section for tips.'
        )
        super().__init__(parent, default_help_text=default_help_text, page_help_link='/usage.html#groups-users-tab')

        # Reference to main app and data repository
        self.app = app
        self.policy_compartment_analysis: PolicyAnalysisRepository = app.policy_compartment_analysis
        self.principal_analysis = PrincipalAnalysisService(app.app_context)

        # --- UI state variables and widget handles ---
        self.chk_show_expanded = tk.BooleanVar(value=False)
        self.chk_show_any_group_user = tk.BooleanVar(value=False)
        self.groups_option_var = tk.StringVar(value='GROUPS')
        self.groups_option_var.trace_add('write', lambda *_: self.update_user_analysis_output())
        self.user_group_search = tk.StringVar()
        self.users_groups_table = None
        self.users_users_table = None
        self.users_policy_table = None
        self.selected_groups_table = None
        self.user_label_count = None

        # Synchronize "load_all_users" state from repository to checkbox/UI as available
        self._load_all_users_state = tk.BooleanVar(
            value=getattr(self.policy_compartment_analysis, 'load_all_users', True)
        )

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
        # Internal state: are users loaded?
        self.users_available = lambda: len(self.policy_compartment_analysis.users) > 0
        # for UI toggling message when users are disabled
        self.disabled_users_label = None

        def _show_user_selection_help(_event=None):
            self.set_page_help_text(
                'Select one or more groups or users. Use the search and dropdown to filter. Selection drives statement display below.'
            )

        def _restore_user_selection_help(_event=None):
            self.set_page_help_text(self.default_help_text)

        self.lf_user_selection.bind('<Enter>', _show_user_selection_help)
        self.lf_user_selection.bind('<Leave>', _restore_user_selection_help)

        # Retain old frm_user_top as the organizer within the label frame
        self._build_ui_user_group_selection(self.lf_user_selection)

    # All context help methods now inherited from BaseUITab.

    # ------------------------------------------------------------------
    # Public lifecycle / data refresh API
    # ------------------------------------------------------------------

    def populate_data(self):
        """Populate / refresh Users tab data after a tenancy or cache load.

        This is the single entry point used by the main application after
        repository data is (re)loaded. It ensures that:

        * The GROUPS/USERS dropdown reflects the current repository state
          (including load_all_users and whether users were actually loaded).
        * The top tables (groups/users) and counts are refreshed using the
          current search text and selection.

        Behavior-wise this is equivalent to the previous sequence of calls
        from main:

        - update_user_analysis_output()
        - update_users_dropdown_options()
        """

        logger.info('Populating UsersTab data...')
        # NOTE: update_users_dropdown_options() will call
        # update_user_analysis_output() as its last step, so a single call
        # here fully refreshes the tab for the current state.
        self.update_users_dropdown_options()
        logger.info('Finished UsersTab.populate_data')

    def set_show_all_data(self, checked=None):
        """Sync table display columns with the *Show all Data* checkbox.

        If *checked* is provided, force the checkbox to that state. If
        *checked* is ``None``, rely on the current :class:`BooleanVar` value
        (used when invoked by the Checkbutton command, since Tkinter has
        already toggled it).
        """
        if checked is not None:
            self.show_all_data_var.set(checked)

        # At this point, show_all_data_var reflects the desired state
        if self.users_groups_table is not None:
            self.users_groups_table.set_display_columns(
                GROUPS_ALL_COLUMNS if self.show_all_data_var.get() else GROUPS_DEFAULT_COLUMNS
            )
        if self.users_users_table is not None:
            self.users_users_table.set_display_columns(
                USERS_ALL_COLUMNS if self.show_all_data_var.get() else USERS_DEFAULT_COLUMNS
            )

    def sync_load_all_users_checkbox(self):
        """
        Ensures the checkbox/UI for load_all_users matches the repository state.
        Should be called after loading data/cache if UI lags behind data model.
        """
        current_repo_val = getattr(self.policy_compartment_analysis, 'load_all_users', True)
        self._load_all_users_state.set(current_repo_val)

    def should_show_users_option(self):
        """
        Returns True if the USERS option should be available in the dropdown, i.e.,
        only if load_all_users is True AND there are users loaded.
        """
        repo = self.policy_compartment_analysis
        return getattr(repo, 'load_all_users', True) and len(getattr(repo, 'users', [])) > 0

    def update_users_dropdown_options(self):
        """Refresh the GROUPS/USERS dropdown based on current repo state.

        This should be called after any tenancy/repository load and is safe to
        invoke at other times. The method also **forces** a refresh of the
        table below by calling :meth:`update_user_analysis_output` at the end
        so that the current selection (GROUPS vs USERS) and search term are
        immediately reflected in the UI.
        """
        menu = self.groups_users_dropdown['menu']
        menu.delete(0, 'end')
        menu.add_command(label='GROUPS', command=lambda: self.groups_option_var.set('GROUPS'))
        if self.should_show_users_option():
            menu.add_command(label='USERS', command=lambda: self.groups_option_var.set('USERS'))
        # If the currently selected option is not available, reset to GROUPS
        if self.groups_option_var.get() == 'USERS' and not self.should_show_users_option():
            self.groups_option_var.set('GROUPS')
        # Always force the corresponding table to reload
        self.update_user_analysis_output()

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
        ttk.Label(frm_user_selection, text='Show Groups -or- Users').grid(
            row=0, column=0, columnspan=1, padx=5, pady=2, sticky='w'
        )
        # Dropdown: GROUPS/USERS
        # Patch: Only offer USERS if users are present, else just GROUPS
        self.groups_users_dropdown = ttk.OptionMenu(
            frm_user_selection,
            self.groups_option_var,
            self.groups_option_var.get(),
            *(['GROUPS', 'USERS'] if self.should_show_users_option() else ['GROUPS']),
        )
        self.groups_users_dropdown.grid(row=0, column=1, padx=5, pady=5, sticky='ew')

        # Show All Data Checkbutton (right of dropdown, col 3)
        self.show_all_data_var = tk.BooleanVar(value=False)

        self.show_all_data_chkbtn = ttk.Checkbutton(
            frm_user_selection, text='Show all Data', variable=self.show_all_data_var, command=self.set_show_all_data
        )
        self.show_all_data_chkbtn.grid(row=0, column=2, padx=6, pady=5, sticky='ew')
        self.add_context_help(
            self.show_all_data_chkbtn,
            'Toggle to show additional ID/OCID columns for Groups/Users.\n'
            'When unchecked, only the most important summary fields are shown for a more compact view.',
        )

        # Label: Search, Entry: user_group_search
        ttk.Label(frm_user_selection, text='Search').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        entry_search = ttk.Entry(frm_user_selection, textvariable=self.user_group_search, width=35)
        entry_search.grid(row=1, column=1, columnspan=2, padx=5, pady=2, sticky='ew')
        self.user_group_search.trace_add('write', lambda *_: self.update_user_analysis_output())

        # Disabled label for USERS mode disabled (add but keep hidden)
        self.disabled_users_label = ttk.Label(
            frm_user_selection,
            text='Loading of individual users is disabled.\nEnable "Load All Users" in Settings to use this feature.',
            foreground='red',
            wraplength=380,
            justify='left',
        )

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
        self.user_selected_groups.grid(row=3, column=0, columnspan=3, padx=5, pady=1, sticky='w')

        self.selected_groups_table = DataTable(
            frm_user_selection,
            columns=['Domain', 'Group'],
            display_columns=['Domain', 'Group'],
            data=[],
            column_widths={'Domain': 140, 'Group': 180},
            height=3,
        )
        self.selected_groups_table.grid(row=4, column=0, columnspan=3, padx=5, pady=1, sticky='w')
        # Reduce height for selected groups table row
        frm_user_selection.grid_rowconfigure(4, minsize=48, weight=0)

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
            columns=GROUPS_ALL_COLUMNS,
            display_columns=GROUPS_DEFAULT_COLUMNS,
            data=[],
            column_widths=GROUPS_COLUMNS_WIDTHS,
            selection_callback=users_group_selection_callback,
            multi_select=True,
            height=7,
        )
        self.users_users_table = DataTable(
            frm_user_top,
            columns=USERS_ALL_COLUMNS,
            display_columns=USERS_DEFAULT_COLUMNS,
            data=[],
            column_widths=USERS_COLUMNS_WIDTHS,
            selection_callback=users_user_selection_callback,
            multi_select=True,
            height=7,
        )

        # # Reduce groups/users table vertical space
        # frm_user_top.grid_rowconfigure(0, minsize=85, weight=0)
        # frm_user_top.grid_rowconfigure(1, minsize=85, weight=0)
        # frm_user_top.grid_rowconfigure(2, minsize=0, weight=0)
        # frm_user_top.grid_rowconfigure(3, minsize=0, weight=0)
        # frm_user_top.grid_rowconfigure(4, minsize=0, weight=0)

        # --- SECTION 2: Display Options with AI Assist Button in LabelFrame ---
        self.lf_display_options = ttk.LabelFrame(self, text='Display Options')
        self.lf_display_options.pack(fill='x', padx=12, pady=(12, 0))

        def _show_display_options_help(_event=None):
            self.set_page_help_text(
                'Adjust output display options, filters, and access AI assistance for user/group policies.'
            )

        def _restore_display_options_help(_event=None):
            self.set_page_help_text(self.default_help_text)

        self.lf_display_options.bind('<Enter>', _show_display_options_help)
        self.lf_display_options.bind('<Leave>', _restore_display_options_help)

        # Filter checkboxes section
        self._build_ui_statement_filters(self.lf_display_options)

        # AI Assist button inside Display Options frame, packed to the right
        self.ai_assist_btn = ttk.Button(
            self.lf_display_options, text='AI Assist', command=self._on_ai_assist_clicked, state=tk.DISABLED
        )
        self.ai_assist_btn.pack(side='right', anchor='e', padx=(16, 8), pady=8)
        self.add_context_help(
            self.ai_assist_btn,
            'Show or hide the AI Assistant pane below to analyze user/group policies.\nNOTE: AI must be enabled in Settings Tab and only policy statements are supported.',
        )

        # --- SECTION 3: Filtered Policy Statements ---
        self.lf_filtered_statements = ttk.LabelFrame(self, text='Filtered Policy Statements')
        self.lf_filtered_statements.pack(fill='both', expand=True, padx=10, pady=10)
        # Make main tab panel rows expand so the policy table area is prioritized
        self.grid_rowconfigure(2, weight=50)  # Give filtered statements lots of expand room
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=2)

        def _show_filtered_statements_help(_event=None):
            self.set_page_help_text(
                'Review the resulting policy statements for your selected users/groups. Adjust filters above as needed.'
            )

        def _restore_filtered_statements_help(_event=None):
            self.set_page_help_text(self.default_help_text)

        self.lf_filtered_statements.bind('<Enter>', _show_filtered_statements_help)
        self.lf_filtered_statements.bind('<Leave>', _restore_filtered_statements_help)

        def selection_callback(selected_rows: list[dict]) -> None:
            for row in selected_rows:
                logger.info(f"Selected policy statement: {row.get('Statement Text')}")
                # Update the policy box
                self.app.ai_additional_instructions = 'Analyze the selected OCI policy statement. Show how the statement breaks down into its components such as action, subject, verb, resource, conditions, and effective path. Explain its implications on permissions within the OCI environment.'
                self.app.policy_query_label_text.set('Policy Statement\nInsights:')
                self.app.policy_query_var.set(row.get('Statement Text'))

        # Data Table for filtered policy statements
        self.users_policy_table = DataTable(
            self.lf_filtered_statements,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            # font_size=10,
            selection_callback=selection_callback,
            multi_select=False,
        )
        self.users_policy_table.pack(expand=True, fill='both', padx=0, pady=0)

    def _build_ui_statement_filters(self, parent):
        # Everything packed horizontally, no grid.

        # Total Groups and Total Users labels
        total_groups = len(getattr(self.policy_compartment_analysis, 'groups', []))
        total_users = len(getattr(self.policy_compartment_analysis, 'users', []))
        self.total_groups_label = ttk.Label(parent, text=f'Total Groups: {total_groups}')
        self.total_groups_label.pack(side='left', padx=8, pady=(0, 3))
        self.total_users_label = ttk.Label(parent, text=f'Total Users: {total_users}')
        self.total_users_label.pack(side='left', padx=8, pady=(0, 3))

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

    def _on_ai_assist_clicked(self):
        """Callback for AI Assist button. Toggles the AI (bottom) pane."""
        if hasattr(self.app, 'toggle_bottom'):
            self.app.toggle_bottom()
            logger.info('Users Tab: AI Assist button clicked, toggled bottom pane.')

    def update_user_analysis_output(self):
        """Update the top user/group listing and associated counters.

        This method is responsible for:

        * Updating the *Total Groups* / *Total Users* labels from the
          underlying repository.
        * Displaying either the groups table or the users table, depending on
          the current value of ``self.groups_option_var`` (``'GROUPS'`` or
          ``'USERS'``).
        * Applying the search filter from ``self.user_group_search`` using
          ``GroupSearch`` / ``UserSearch``.

        It does **not** compute policy statements; those are handled by
        :meth:`_update_user_analysis_policy_output` and
        :meth:`update_user_policy_output`.
        """
        logger.info(f'Displaying: {self.groups_option_var.get()} with search of {self.user_group_search.get()}')

        # Update the total counts labels
        if hasattr(self, 'total_groups_label') and hasattr(self, 'total_users_label'):
            total_groups = len(getattr(self.policy_compartment_analysis, 'groups', []))
            total_users = len(getattr(self.policy_compartment_analysis, 'users', []))
            self.total_groups_label.configure(text=f'Total Groups: {total_groups}')
            self.total_users_label.configure(text=f'Total Users: {total_users}')

        # Defensive: Only try to display tables if they've been initialized
        if self.users_groups_table is None or self.users_users_table is None:
            logger.info('Table widgets not initialized yet; skipping analysis output update.')
            return

        # Grid the correct table
        # Patch: Hide USERS mode if unavailable, and display red warning instead
        if self.groups_option_var.get() == 'GROUPS':
            if self.disabled_users_label is not None and self.disabled_users_label.winfo_manager():
                self.disabled_users_label.grid_remove()
            self.users_users_table.grid_forget()
            self.users_groups_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            group_filter: GroupSearch = GroupSearch(
                group_name=self.user_group_search.get().split('|') if self.user_group_search.get() else [],
            )
            filtered_groups: list[Group] = self.policy_compartment_analysis.filter_groups(group_filter=group_filter)
            display_groups = []
            for g in filtered_groups:
                # Build display dict with all shown keys for full compatibility
                display_groups.append(
                    {
                        'Domain Name': g.get('domain_name', 'Default'),
                        'Group Name': g.get('group_name', ''),
                        'User Count': (
                            len(self.policy_compartment_analysis.get_users_for_group(g))
                            if hasattr(self.policy_compartment_analysis, 'get_users_for_group')
                            else 0
                        ),
                        'Group ID': g.get('group_id', ''),
                        'Group OCID': g.get('group_ocid', ''),
                    }
                )
            self.users_groups_table.update_data(display_groups)
            logger.info(f'Loaded {len(filtered_groups)} groups into table')
        elif self.groups_option_var.get() == 'USERS':
            if not self.users_available():
                self.users_users_table.grid_forget()
                if self.disabled_users_label is not None:
                    self.disabled_users_label.grid(row=3, column=0, columnspan=3, sticky='w', padx=5, pady=(8, 2))
                logger.info('User view disabled due to no users loaded')
                return
            if self.disabled_users_label is not None:
                self.disabled_users_label.grid_remove()
            self.users_groups_table.grid_forget()
            self.users_users_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            user_filter: UserSearch = UserSearch(
                search=self.user_group_search.get().split('|') if self.user_group_search.get() else [],
            )
            filtered_users: list[User] = self.policy_compartment_analysis.filter_users(user_filter=user_filter)
            display_users = []
            for u in filtered_users:
                display_users.append(
                    {
                        'Domain Name': u.get('domain_name', 'Default'),
                        'Username': u.get('user_name', ''),
                        'Display Name': u.get('display_name', ''),
                        'Primary Email': u.get('email', ''),
                        'User ID': u.get('user_id', ''),
                        'User OCID': u.get('user_ocid', ''),
                    }
                )
            self.users_users_table.update_data(display_users)
            logger.info(f'Loaded {len(filtered_users)} users into data')
        else:
            logger.warning('Should not get here')

    def update_user_policy_output(self):
        """Refresh the policy statements table and related labels.

        This uses the pre-computed ``self.filtered_policies`` and
        ``self.selected_groups_for_table`` that are maintained by
        :meth:`_update_user_analysis_policy_output` when the selection in the
        groups/users tables changes.

        Responsibilities:

        * Toggle between basic vs expanded policy columns based on the
          *Parsed Output* checkbox (``self.chk_show_expanded``).
        * Optionally include "any-user" / "any-group" statements when the
          corresponding checkbox is enabled.
        * Push the final policy list into ``self.users_policy_table`` and
          update the *Selected Groups* helper table and the
          *Policy Statements (Filtered)* count label.
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
            any_user_group_policies: list[RegularPolicyStatement] = self.principal_analysis.by_subject_types(
                subject_types=['any-user', 'any-group']
            ).statements
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
        """Recompute policy statements for the current group/user selection.

        This is the main worker that responds to selection changes in the
        groups/users tables. It:

        * Builds an appropriate :class:`PolicySearch` with exact groups and/or
          users.
        * Populates ``self.filtered_policies`` with the matching policy
          statements from the repository.
        * Builds ``self.selected_groups_for_table`` (used by the small
          *Selected Groups* table on the left).
        * Finally delegates to :meth:`update_user_policy_output` to refresh
          what is rendered on screen.
        """
        logger.info(f'Searching for policies for groups: {groups_for_filter} and users: {users_for_filter}')
        exact_groups_filter: list[Group] = groups_for_filter
        exact_users_filter: list[User] = users_for_filter
        policy_result = self.principal_analysis.by_exact_groups_users(
            groups=exact_groups_filter,
            users=exact_users_filter,
        )
        self.filtered_policies: list[RegularPolicyStatement] = policy_result.statements
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

    def on_load_all_users_setting_changed(self, enabled: bool):
        """
        Called if settings change for Load All Users to refresh user/group options and UI.
        Synchronizes between UI and model: both directions.
        """
        # Always update the model repository field so next cache save/load is accurate
        self.policy_compartment_analysis.load_all_users = enabled

        # If users are now NOT loaded, switch view to GROUPS forcibly and refresh dropdown/menu
        if not enabled:
            self.groups_option_var.set('GROUPS')
        menu = self.groups_users_dropdown['menu']
        menu.delete(0, 'end')
        menu.add_command(label='GROUPS', command=lambda: self.groups_option_var.set('GROUPS'))
        if enabled:
            menu.add_command(label='USERS', command=lambda: self.groups_option_var.set('USERS'))
        self.update_user_analysis_output()
