"""Desktop graphical search over the same direct grants used by the web UI."""

from __future__ import annotations

import tkinter as tk
from time import perf_counter
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.condition_tester_service import extract_condition_clause
from oci_policy_analysis.application.services.policy_graph_service import PolicyGraphService
from oci_policy_analysis.presentation.tk.base_tab import BaseUITab

logger = get_logger(component='policy_graph_tab')


class PolicyGraphTab(BaseUITab):
    """Filter direct policy grants through graph cards and inspect table results."""

    def __init__(self, parent, app):
        logger.info('Constructing desktop Policy Graph tab: search controls, graph lanes, and detailed-analysis table.')
        super().__init__(
            parent,
            default_help_text=(
                'Enter at least two search characters or choose a filter; graph cards narrow results.\n'
                'Right-click a table row → Show Detailed Analysis. '
                'Direct grants only.'
            ),
            page_help_link='/usage.html#policy-graph-desktop-tab',
        )
        self.app = app
        self.filters = {name: tk.StringVar(self) for name in ('principal', 'resource', 'path', 'query', 'effect')}
        self.result: dict = {}
        self._pending_search = None
        self._pending_draw = None
        self._detail = None
        self._rows: dict[str, dict] = {}
        self._principal_boxes: dict[str, tuple] = {}
        self._grant_boxes: list[tuple] = []
        self._path_boxes: dict[str, tuple] = {}
        self._build_ui()
        self.refresh_view()

    def _build_ui(self):
        heading = ttk.Frame(self)
        heading.pack(fill='x', padx=10, pady=6)
        ttk.Label(heading, text='Policy/Permission Graphical Search', font=('TkDefaultFont', 13, 'bold')).pack(
            side='left'
        )
        ttk.Button(heading, text='Refresh view', command=self.refresh_view).pack(side='right')
        self.byline = ttk.Label(
            self,
            text='Narrow search down by selecting one or more of principal (group, dynamic group, any-user, service), '
            'Resource or permission, or effective path.',
            wraplength=1000,
        )
        self.byline.pack(fill='x', padx=10, pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=10)
        for index, (name, label) in enumerate(
            (
                ('principal', 'Principal'),
                ('resource', 'Resource or permission'),
                ('path', 'Effective path'),
                ('query', 'Policy or statement'),
                ('effect', 'Effect'),
            )
        ):
            host = ttk.Frame(bar)
            host.grid(row=0, column=index, sticky='ew', padx=(0, 8))
            bar.columnconfigure(index, weight=1)
            ttk.Label(host, text=label).pack(anchor='w')
            if name == 'effect':
                widget = ttk.Combobox(
                    host, textvariable=self.filters[name], values=('', 'allow', 'deny'), state='readonly', width=10
                )
                widget.bind('<<ComboboxSelected>>', lambda _e: self._load(1))
            elif name in ('path', 'principal'):
                widget = ttk.Combobox(host, textvariable=self.filters[name], width=22)
                if name == 'path':
                    self.path_entry = widget
                else:
                    self.principal_entry = widget
            else:
                widget = ttk.Entry(host, textvariable=self.filters[name], width=22)
            widget.pack(fill='x')
            widget.bind('<Return>', lambda _e: self._load(1))
            self.add_context_help(
                widget,
                {
                    'principal': 'Search any part of a principal, such as ops. Matches include all result pages.',
                    'resource': 'Match a resource or direct permission, such as objects, OBJECT_CREATE, or object_.',
                    'path': 'Match any part of an effective path; all matching paths are available across pages.',
                    'query': 'Match a policy name, original statement text, or statement ID.',
                    'effect': 'Leave blank for allow and deny, or narrow to one effect.',
                }[name],
            )
            self.filters[name].trace_add('write', self._schedule_search)

        controls = ttk.Frame(self)
        controls.pack(fill='x', padx=10, pady=6)
        ttk.Button(controls, text='Clear filters', command=self._clear_filters).pack(side='left')
        self.summary = tk.StringVar(self)
        ttk.Label(controls, textvariable=self.summary).pack(side='left', padx=10)
        self.match_count = tk.StringVar(self)
        ttk.Label(controls, textvariable=self.match_count).pack(side='right')

        split = ttk.PanedWindow(self, orient='vertical')
        split.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        graph = ttk.Frame(split)
        split.add(graph, weight=3)
        lanes = ttk.Frame(graph)
        lanes.pack(fill='both', expand=True)
        lanes.columnconfigure(0, weight=2, uniform='graph')
        lanes.columnconfigure(1, weight=1, uniform='graph')
        lanes.rowconfigure(0, weight=1)
        left = ttk.Frame(lanes)
        left.grid(row=0, column=0, sticky='nsew')
        right = ttk.Frame(lanes)
        right.grid(row=0, column=1, sticky='nsew')
        titles = ttk.Frame(left)
        titles.pack(fill='x')
        for name in ('Principals', 'Resources & Permissions'):
            ttk.Label(titles, text=name, anchor='w').pack(side='left', fill='x', expand=True)
        self.path_title = ttk.Label(right, text='Effective Paths')
        self.path_title.pack(fill='x')
        self.canvas = self._scroll_canvas(left)
        self.path_canvas = self._scroll_canvas(right)
        for canvas in (self.canvas, self.path_canvas):
            canvas.bind('<Configure>', self._schedule_draw)
            self.add_context_help(
                canvas,
                'Search 2+ characters or choose a filter. Click result cards to narrow further; scroll with the mouse wheel.',
            )
        lower = ttk.Frame(split)
        split.add(lower, weight=2)
        table_host = ttk.Frame(lower)
        table_host.pack(fill='both', expand=True)
        columns = ('principal', 'effect', 'resource', 'path', 'policy', 'conditional', 'permissions')
        self.table = ttk.Treeview(table_host, columns=columns, show='headings', selectmode='browse', height=7)
        for name, label, width in zip(
            columns,
            ('Principal', 'Effect', 'Resource', 'Effective path', 'Policy', 'Conditional', 'Permissions'),
            (210, 65, 120, 280, 180, 95, 90),
            strict=True,
        ):
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=60)
        vertical = ttk.Scrollbar(table_host, command=self.table.yview)
        horizontal = ttk.Scrollbar(table_host, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        table_host.columnconfigure(0, weight=1)
        table_host.rowconfigure(0, weight=1)
        self.table.bind('<Button-3>', self._table_right_click)
        self.table.bind('<Button-2>', self._table_right_click)
        self.table.bind('<Control-Button-1>', self._table_right_click)
        self.table.bind('<Return>', self._open_selected)
        self.table.bind('<space>', self._open_selected)
        self.detail_menu = tk.Menu(self, tearoff=False)
        self.detail_menu.add_command(label='Show Detailed Analysis', command=self._open_selected)
        self.add_context_help(
            self.table,
            'Right-click for detailed analysis or to test a condition. Keyboard: select a row, then Enter for details.',
        )

    def _scroll_canvas(self, parent):
        host = ttk.Frame(parent)
        host.pack(fill='both', expand=True)
        canvas = tk.Canvas(host, background='#fafafa', highlightthickness=0, height=260)
        canvas.pack(side='left', fill='both', expand=True)
        canvas.bind('<MouseWheel>', lambda event: self._scroll(canvas, 'scroll', -1 if event.delta > 0 else 1, 'units'))
        canvas.bind('<Button-4>', lambda _e: self._scroll(canvas, 'scroll', -1, 'units'))
        canvas.bind('<Button-5>', lambda _e: self._scroll(canvas, 'scroll', 1, 'units'))
        return canvas

    def _scroll(self, canvas, *args):
        canvas.yview(*args)
        self._draw_connections()

    def _schedule_search(self, *_args):
        if self._pending_search:
            self.after_cancel(self._pending_search)
        self._pending_search = self.after(300, lambda: self._load(1))

    def _schedule_draw(self, _event=None):
        if self._pending_draw:
            self.after_cancel(self._pending_draw)
        self._pending_draw = self.after_idle(self._draw_graph)

    def _load(self, page=1):
        started = perf_counter()
        if self._pending_search:
            self.after_cancel(self._pending_search)
            self._pending_search = None
        self._close_detail(restore_focus=False)
        corpus = getattr(self.app.app_context, 'corpus', None)
        self.result = PolicyGraphService(corpus).get_page(
            **{name: value.get() for name, value in self.filters.items()},
            page=page,
            overview=True,
            all_results=True,
        )
        summary = self.result['summary']
        self.summary.set(
            f'{summary["source_statements"]} source statements · {summary["direct_facts"]} direct facts · '
            f'{summary["exclusions"]} excluded statements'
        )
        total, paths = self.result['total'], self.result['paths']
        overview = self.result['needs_filter']
        self.match_count.set(
            'Enter at least 2 characters or choose a filter'
            if overview
            else f'{total} matching grant{"s" if total != 1 else ""} · {len(paths)} effective paths'
        )
        self.path_entry['values'] = [item['path'] for item in paths]
        self.principal_entry['values'] = [
            item.get('principal_display') or item['principal'] for item in self.result['principals']
        ]
        self.path_title.configure(text=f'Effective Paths ({len(paths)})' if not overview else 'Effective Paths')
        self.table.delete(*self.table.get_children())
        self._rows.clear()
        for index, row in enumerate(self.result['grants']):
            iid = str(index)
            self._rows[iid] = row
            self.table.insert(
                '',
                'end',
                iid=iid,
                values=(
                    row.get('principal_display') or row['principal'],
                    row['effect'],
                    row['resource'],
                    row['path'],
                    row['policy_name'],
                    'Yes' if row['condition_clause'] else 'No',
                    len(row['permissions']),
                ),
            )
        self.canvas.yview_moveto(0)
        self.path_canvas.yview_moveto(0)
        self._draw_graph()
        logger.info(
            'Desktop Policy Graph view constructed: loaded=%s guidance=%s page=%d '
            'principal_cards=%d resource_cards=%d path_cards=%d table_rows=%d elapsed_ms=%.1f',
            self.result['loaded'],
            overview,
            self.result['page'],
            0 if overview else len(self.result['principals']),
            len(self.result['grants']),
            0 if overview else len(paths),
            len(self._rows),
            (perf_counter() - started) * 1000,
        )

    def refresh_view(self):
        """Read the current corpus without fetching OCI data, starting at page one."""
        self._load(1)

    def reset_for_data_load(self):
        """Clear filters and stale details when switching the loaded dataset."""
        self._clear_filters()

    def _clear_filters(self):
        for value in self.filters.values():
            value.set('')
        self._load(1)

    def _focus_node(self, changes):
        if self.result.get('needs_filter'):
            return
        for name, value in changes.items():
            self.filters[name].set(value)
        self._load(1)

    def _card(self, canvas, x, y, width, title, note, changes=None, effect=''):
        size = getattr(self, '_current_font_size', 11)
        tag = f'card:{len(canvas.find_all())}'
        label = canvas.create_text(
            x + 10,
            y + 8,
            text=title,
            width=max(30, width - 20),
            anchor='nw',
            font=('TkDefaultFont', size, 'bold'),
            fill='#242424',
            tags=(tag,),
        )
        label_box = canvas.bbox(label)
        note_item = canvas.create_text(
            x + 10,
            label_box[3] + 4,
            text=note,
            width=max(30, width - 20),
            anchor='nw',
            font=('TkDefaultFont', max(9, size - 1)),
            fill='#575757',
            tags=(tag,),
        )
        height = canvas.bbox(note_item)[3] - y + 10
        rectangle = canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill='#ffffff',
            outline='#b54232' if effect == 'deny' else '#c7d4cb',
            tags=(tag,),
        )
        canvas.tag_lower(rectangle, label)
        if changes:
            canvas.tag_bind(tag, '<Button-1>', lambda _e: self._focus_node(changes))
            canvas.tag_bind(tag, '<Enter>', lambda _e: canvas.configure(cursor='hand2'))
            canvas.tag_bind(tag, '<Leave>', lambda _e: canvas.configure(cursor=''))
        return (x, y, x + width, y + height)

    def _draw_graph(self):
        if self._pending_draw:
            self.after_cancel(self._pending_draw)
        self._pending_draw = None
        self.canvas.delete('all')
        self.path_canvas.delete('all')
        self._principal_boxes, self._path_boxes, self._grant_boxes = {}, {}, []
        width = max(360, self.canvas.winfo_width())
        lane = width / 2
        path_width = max(180, self.path_canvas.winfo_width())
        if self.result.get('needs_filter'):
            self._card(
                self.canvas,
                8,
                8,
                lane - 20,
                'Find a principal',
                'Search 2+ characters or choose a principal. Example: admins',
            )
            self._card(
                self.canvas,
                lane + 8,
                8,
                lane - 20,
                'Find resources and permissions',
                'Example: objects or OBJECT_CREATE',
            )
            self._card(
                self.path_canvas,
                12,
                8,
                path_width - 20,
                'Find an effective path',
                'Example: network or ROOT/Production',
            )
        else:
            rows = self.result.get('grants', [])
            y = 8
            for item in self.result.get('principals', []):
                principal, count = item['principal'], item['grant_count']
                box = self._card(
                    self.canvas,
                    8,
                    y,
                    lane - 20,
                    item.get('principal_display') or principal,
                    f'{count} matching grant(s) across all pages · click to filter',
                    {'principal': principal},
                )
                self._principal_boxes[principal] = box
                y = box[3] + 10
            y = 8
            for row in rows:
                box = self._card(
                    self.canvas,
                    lane + 8,
                    y,
                    lane - 20,
                    f'{row["effect"].upper()} · {row["resource"]}',
                    f'{row["policy_name"]} · {len(row["permissions"])} permission(s)'
                    f'{" · conditional" if row["condition"] else ""} · click to filter',
                    {'resource': row['resource'], 'effect': row['effect']},
                    row['effect'],
                )
                self._grant_boxes.append(box)
                y = box[3] + 10
            y = 8
            for item in self.result.get('paths', []):
                box = self._card(
                    self.path_canvas,
                    12,
                    y,
                    path_width - 20,
                    item['path'],
                    f'{item["grant_count"]} matching grant(s) across all pages · click to filter',
                    {'path': item['path']},
                )
                self._path_boxes[item['path'].casefold()] = box
                y = box[3] + 10
            if not rows:
                self._card(
                    self.canvas,
                    8,
                    8,
                    width - 20,
                    'No grants match these filters.'
                    if self.result.get('loaded')
                    else 'Load policy data to explore grants.',
                    'Load from the Settings tab.'
                    if not self.result.get('loaded')
                    else 'Try another resource, permission, principal, or path.',
                )
        for canvas in (self.canvas, self.path_canvas):
            bounds = canvas.bbox('all') or (0, 0, 1, 1)
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(canvas.winfo_height(), bounds[3] + 12)))
        self._draw_connections()

    def _draw_connections(self):
        def cy(box):
            return (box[1] + box[3]) / 2

        for canvas in (self.canvas, self.path_canvas):
            canvas.delete('connection')
        for row, middle in zip(self.result.get('grants', []), self._grant_boxes, strict=True):
            left = self._principal_boxes[row['principal']]
            right = self._path_boxes.get(row['path'].casefold())
            color = '#b54232' if row['effect'] == 'deny' else '#397358'
            self.canvas.create_line(left[2], cy(left), middle[0], cy(middle), fill=color, tags='connection')
            if right:
                right_screen_y = cy(right) - self.path_canvas.canvasy(0)
                middle_screen_y = cy(middle) - self.canvas.canvasy(0)
                if (
                    0 <= right_screen_y <= self.path_canvas.winfo_height()
                    and 0 <= middle_screen_y <= self.canvas.winfo_height()
                ):
                    self.canvas.create_line(
                        middle[2],
                        cy(middle),
                        self.canvas.winfo_width(),
                        right_screen_y + self.canvas.canvasy(0),
                        fill=color,
                        tags='connection',
                    )
                    self.path_canvas.create_line(0, cy(right), right[0], cy(right), fill=color, tags='connection')
        self.canvas.tag_lower('connection')
        self.path_canvas.tag_lower('connection')

    def _table_right_click(self, event):
        row = self.table.identify_row(event.y)
        if row and self.table.identify_region(event.x, event.y) in ('cell', 'tree'):
            self.table.selection_set(row)
            self.table.focus(row)
            self.detail_menu.delete(0, 'end')
            self.detail_menu.add_command(label='Show Detailed Analysis', command=self._open_selected)
            grant = self._rows.get(row)
            clause = (
                extract_condition_clause(grant.get('condition', ''), grant.get('statement_text', '')) if grant else ''
            )
            if clause:
                self.detail_menu.add_command(
                    label='Test Condition in Condition Tester Tab',
                    command=lambda: self.app.open_condition_tester_with_condition(clause),
                )
            try:
                self.detail_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.detail_menu.grab_release()
        return 'break'

    def _open_selected(self, _event=None):
        selection = self.table.selection()
        if not selection or selection[0] not in self._rows:
            return 'break'
        row = self._rows[selection[0]]
        self._close_detail(restore_focus=False)
        dialog = tk.Toplevel(self)
        self._detail = dialog
        dialog.title('Grant details')
        dialog.transient(self.winfo_toplevel())
        dialog.geometry('720x620')
        dialog.minsize(420, 300)
        text = ScrolledText(dialog, wrap='word', font=('TkDefaultFont', getattr(self, '_current_font_size', 11)))
        text.pack(fill='both', expand=True, padx=10, pady=10)
        fields = (
            ('Policy', row['policy_name']),
            ('Policy OCID', row['policy_ocid']),
            ('Statement', row['statement_text']),
            ('Statement ID', row['statement_id']),
            ('Principal', row.get('principal_display') or row['principal']),
            ('Effect', row['effect']),
            ('Resource', row['resource']),
            ('Effective path', row['path']),
            ('Condition', row['condition_clause'] or 'None'),
            (f'Permissions ({len(row["permissions"])})', '\n'.join(row['permissions'])),
        )
        for label, value in fields:
            text.insert('end', f'{label}\n', 'heading')
            text.insert('end', f'{value}\n\n')
        text.tag_configure('heading', font=('TkDefaultFont', getattr(self, '_current_font_size', 11), 'bold'))
        text.configure(state='disabled')
        close = ttk.Button(dialog, text='Close', command=self._close_detail)
        close.pack(pady=(0, 10))
        dialog.protocol('WM_DELETE_WINDOW', self._close_detail)
        dialog.bind('<Escape>', lambda _e: self._close_detail())
        dialog.grab_set()
        close.focus_set()
        return 'break'

    def _close_detail(self, restore_focus=True):
        if self._detail is not None:
            self._detail.destroy()
            self._detail = None
            if restore_focus:
                self.table.focus_set()

    def apply_settings(self, context_help: bool, font_size: str):
        """Apply standard help/font preferences and redraw wrapped graph cards."""
        super().apply_settings(context_help, font_size)
        if hasattr(self, 'canvas'):
            self._schedule_draw()

    def destroy(self):
        """Cancel queued redraws/searches and close any modal on tab destruction."""
        for pending in (self._pending_search, self._pending_draw):
            if pending:
                self.after_cancel(pending)
        self._close_detail(restore_focus=False)
        super().destroy()
