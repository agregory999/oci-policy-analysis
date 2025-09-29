from tkinter import ttk

from logic.data_repo import IdentityDomainsAnalysis
from logic.logger import get_logger
from ui.data_table import DataTable

logger = get_logger()

GROUPS_COLUMNS = ['Domain Name', 'Group Name', 'Group OCID']
GROUPS_COLUMNS_WIDTHS = {'Domain Name': 150, 'Group Name': 300, 'Group OCID': 450}


class UsersTab(ttk.Frame):
    """Example data-driven tab that can update the bottom entry."""

    def __init__(self, parent, app, identity_repo):
        super().__init__(parent)
        self.app = app
        self.identity_repo: IdentityDomainsAnalysis = identity_repo

        ttk.Label(self, text='Users').pack(anchor='w', padx=8, pady=(10, 6))

        self.tree = ttk.Treeview(self, columns=('id', 'name', 'role'), show='headings')
        self.tree.heading('id', text='ID')
        self.tree.heading('name', text='Name')
        self.tree.heading('role', text='Role')
        self.tree.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        cmdbar = ttk.Frame(self)
        cmdbar.pack(fill='x', padx=8, pady=(0, 10))
        ttk.Button(cmdbar, text='Send Selected to Bottom Entry', command=self.send_selected).pack(side='left')

        self.users_groups_table = DataTable(
            self,
            columns=GROUPS_COLUMNS,
            display_columns=GROUPS_COLUMNS,
            data=[],
            column_widths=GROUPS_COLUMNS_WIDTHS,
            # font_size=10,
            # selection_callback=users_group_selection_callback,
            multi_select=True,
        )
        self.users_groups_table.pack(fill='both', expand=True)

        # Prob not nec
        # self.reload_data()

    def reload_data(self):
        # Load the data or filter it as needed
        self.users_groups_table.update_data(self.identity_repo.groups)
        logger.info(f'Loaded data for Groups: {len(self.identity_repo.groups)}')

    def send_selected(self):
        sel = self.tree.selection()
        if not sel:
            logger.info('No user selected')
            return
        vals = self.tree.item(sel[0], 'values')
        # Example payload to the bottom entry
        text = f'{vals[0]} | {vals[1]} | {vals[2]}'
        self.app.update_bottom_entry(text)
        logger.info('Sent selection to bottom entry')
