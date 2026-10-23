"""Read-only Tk viewer for the process-local OCI API journal."""

import json
import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.application.core.support.api_calls import API_CALLS


class ApiCallsWindow(tk.Toplevel):
    """Inspect bounded API metadata; records are never persisted by this viewer.

    Args:
        parent: Owning console page.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title('API Calls · Current Application Session')
        self.geometry('1200x650')
        self.rows = {}
        self.signature = None
        self.poll_token = None
        controls = ttk.Frame(self)
        controls.pack(fill='x', padx=10, pady=10)
        self.search = tk.StringVar()
        ttk.Label(controls, text='Search').pack(side='left')
        ttk.Entry(controls, textvariable=self.search, width=40).pack(side='left', padx=5)
        self.errors = tk.BooleanVar()
        ttk.Checkbutton(controls, text='Errors only', variable=self.errors, command=self.refresh).pack(side='left')
        ttk.Button(controls, text='Clear API history', command=lambda: (API_CALLS.clear(), self.refresh())).pack(
            side='right'
        )
        self.count = ttk.Label(self, text='')
        self.count.pack(anchor='w', padx=10)
        pane = ttk.Panedwindow(self, orient='vertical')
        pane.pack(fill='both', expand=True, padx=10, pady=5)
        table_frame = ttk.Frame(pane)
        self.table = ttk.Treeview(
            table_frame,
            columns=('started_at', 'operation', 'duration_ms', 'http_status', 'code', 'outcome'),
            show='headings',
            height=12,
        )
        for key, title in [
            ('started_at', 'Started (UTC)'),
            ('operation', 'API Call'),
            ('duration_ms', 'Duration (ms)'),
            ('http_status', 'HTTP'),
            ('code', 'Service Code'),
            ('outcome', 'Outcome'),
        ]:
            self.table.heading(key, text=title, anchor='w')
            self.table.column(key, width=160, stretch=True)
        scroll = ttk.Scrollbar(table_frame, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        pane.add(table_frame, weight=3)
        self.detail = tk.Text(pane, height=10, wrap='word', state='disabled')
        pane.add(self.detail, weight=1)
        self.table.bind('<<TreeviewSelect>>', self.show_details)
        self.search.trace_add('write', lambda *_: self.refresh())
        self.refresh()
        self.bind('<Destroy>', self._on_destroy)
        self._poll()

    def _poll(self):
        if self.winfo_exists():
            self.refresh()
            self.poll_token = self.after(1500, self._poll)

    def refresh(self):
        """Refresh metadata while preserving a selected retained call."""
        revision, rows, dropped = API_CALLS.snapshot()
        signature = (revision, self.search.get(), self.errors.get())
        if signature == self.signature:
            return
        self.signature = signature
        selected = self.table.selection()
        needle = self.search.get().casefold().strip()
        rows = [
            row
            for row in rows
            if (not self.errors.get() or row.get('outcome') == 'Error')
            and (not needle or needle in json.dumps(row).casefold())
        ]
        self.rows = {str(row['sequence']): row for row in rows}
        self.table.delete(*self.table.get_children())
        for key, row in self.rows.items():
            self.table.insert('', 'end', iid=key, values=tuple(row.get(field, '') for field in self.table['columns']))
        if selected and selected[0] in self.rows:
            self.table.selection_set(selected[0])
        self.count.configure(
            text=f'{len(rows)} calls shown · {dropped} evicted · Current process only; restarting clears the journal.'
        )
        self.show_details()

    def _on_destroy(self, event):
        if event.widget is self and self.poll_token:
            self.after_cancel(self.poll_token)

    def show_details(self, _event=None):
        """Show status, reason, endpoint and interpretation for one call."""
        selection = self.table.selection()
        row = self.rows.get(selection[0]) if selection else None
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        if row:
            self.detail.insert('1.0', json.dumps(row, indent=2))
        self.detail.configure(state='disabled')
