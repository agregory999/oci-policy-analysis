"""Desktop cross-tenancy graph and statement explorer using the shared projection."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.cross_tenancy_analysis_service import CrossTenancyAnalysisService
from oci_policy_analysis.presentation.tk.base_tab import BaseUITab

LOGGER = get_logger(component='cross_tenancy')


def selected_rows(payload: dict, source_ids: set[str] | None = None, query: str = '') -> list[dict]:
    """Apply the same source-ID and statement-text filters used by the web page."""
    rows = [
        *(payload.get('defines') or []),
        *(payload.get('admit_statements') or []),
        *(payload.get('endorse_statements') or []),
        *(payload.get('unknown_statements') or []),
    ]
    query = query.strip().casefold()
    return [
        row
        for row in rows
        if (source_ids is None or row.get('stable_key') in source_ids)
        and (not query or query in str(row.get('statement_text') or '').casefold())
    ]


class CrossTenancyTab(BaseUITab):
    """Draw relationship lanes and inspect their source statements and findings."""

    def __init__(self, parent, main_app):
        super().__init__(
            parent,
            default_help_text='Select a tenancy, link, or entity to filter cross-tenancy source statements.',
            page_help_link='/usage.html#cross-tenancy-tab',
        )
        self.main_app = main_app
        self.payload: dict = {}
        self._selection_id = ''
        self._selection_keys: set[str] | None = None
        self._graph_items: dict[str, tuple[str, set[str]]] = {}
        self._row_by_id: dict[str, dict] = {}
        self._finding_by_id: dict[str, dict] = {}
        self._redraw_after: str | None = None
        self._build_ui()
        self.update_cross_tenancy_output()

    def _build_ui(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=10, pady=6)
        ttk.Label(bar, text='Cross-Tenancy Planner', font=('TkDefaultFont', 13, 'bold')).pack(side='left')
        self.count_var = tk.StringVar(value='No statements loaded')
        ttk.Label(bar, textvariable=self.count_var).pack(side='left', padx=12)
        ttk.Button(bar, text='Generate single Cross-Tenancy Policy', command=self._generate_single_policy).pack(
            side='right', padx=(6, 0)
        )
        ttk.Button(bar, text='Refresh view', command=self.update_cross_tenancy_output).pack(side='right')

        split = ttk.PanedWindow(self, orient='vertical')
        split.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        graph_frame = ttk.LabelFrame(split, text='Relationships')
        split.add(graph_frame, weight=2)
        lower = ttk.PanedWindow(split, orient='horizontal')
        split.add(lower, weight=3)

        canvas_host = ttk.Frame(graph_frame)
        canvas_host.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(canvas_host, background='#f7f9fc', highlightthickness=0, height=300)
        scroll_y = ttk.Scrollbar(canvas_host, orient='vertical', command=self.canvas.yview)
        scroll_x = ttk.Scrollbar(canvas_host, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll_y.grid(row=0, column=1, sticky='ns')
        scroll_x.grid(row=1, column=0, sticky='ew')
        canvas_host.rowconfigure(0, weight=1)
        canvas_host.columnconfigure(0, weight=1)
        self.canvas.bind('<Configure>', self._schedule_redraw)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        self.canvas.bind('<Button-4>', lambda _e: self.canvas.yview_scroll(-1, 'units'))
        self.canvas.bind('<Button-5>', lambda _e: self.canvas.yview_scroll(1, 'units'))

        relation_bar = ttk.Frame(graph_frame)
        relation_bar.pack(fill='x', padx=6, pady=4)
        ttk.Label(relation_bar, text='Relationship / entity:').pack(side='left')
        self.relationship_var = tk.StringVar(value='All relationships')
        self.relationship_combo = ttk.Combobox(
            relation_bar, textvariable=self.relationship_var, state='readonly', width=52
        )
        self.relationship_combo.pack(side='left', padx=6, fill='x', expand=True)
        self.relationship_combo.bind('<<ComboboxSelected>>', self._on_relationship_selected)

        explorer = ttk.Frame(lower)
        lower.add(explorer, weight=3)
        inspector = ttk.LabelFrame(lower, text='Details')
        lower.add(inspector, weight=2)
        self.inspector = ScrolledText(inspector, wrap='word', font=('TkFixedFont', 10), state='disabled')
        self.inspector.pack(fill='both', expand=True, padx=5, pady=5)
        self._show_detail('Select a statement or finding to inspect its source and parsed fields.')

        controls = ttk.Frame(explorer)
        controls.pack(fill='x', pady=(0, 5))
        ttk.Label(controls, text='Statement text:').pack(side='left')
        self.filter_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.filter_var, width=28).pack(side='left', padx=4)
        self.filter_var.trace_add('write', lambda *_: self._render_rows())
        ttk.Label(controls, text='Defined entity:').pack(side='left', padx=(8, 2))
        self.entity_var = tk.StringVar(value='All')
        self.entity_combo = ttk.Combobox(controls, textvariable=self.entity_var, state='readonly', width=22)
        self.entity_combo.pack(side='left', padx=3)
        self.entity_combo.bind('<<ComboboxSelected>>', lambda _e: self._render_rows())
        ttk.Button(controls, text='Clear', command=self._clear_filters).pack(side='left', padx=6)
        self.statement_count_var = tk.StringVar(value='0 statements')
        ttk.Label(explorer, textvariable=self.statement_count_var).pack(anchor='w')

        notebook = ttk.Notebook(explorer)
        notebook.pack(fill='both', expand=True)
        statements_frame, findings_frame = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(statements_frame, text='Statements')
        notebook.add(findings_frame, text='Findings')
        self.statement_tree = self._tree(
            statements_frame,
            ('Type', 'Policy', 'Statement', 'Associated tenancy'),
            (85, 145, 510, 190),
            self._on_statement_selected,
        )
        self.finding_tree = self._tree(
            findings_frame,
            ('Finding', 'Severity', 'Policy', 'Alias', 'Issue'),
            (180, 85, 140, 110, 350),
            self._on_finding_selected,
        )

    @staticmethod
    def _tree(parent, columns, widths, callback) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        for name, width in zip(columns, widths, strict=True):
            tree.heading(name, text=name)
            tree.column(name, width=width, minwidth=75, stretch=name == 'Statement')
        yscroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.bind('<<TreeviewSelect>>', callback)
        return tree

    def _show_detail(self, value: str | dict) -> None:
        self.inspector.configure(state='normal')
        self.inspector.delete('1.0', 'end')
        if isinstance(value, dict) and 'principal_identity' in value:
            value = {'principal_identity': value['principal_identity'], **value}
        self.inspector.insert('1.0', json.dumps(value, indent=2, default=str) if isinstance(value, dict) else value)
        self.inspector.configure(state='disabled')

    def _on_statement_selected(self, _event=None) -> None:
        selection = self.statement_tree.selection()
        if selection:
            self._show_detail(self._row_by_id[selection[0]])

    def _on_finding_selected(self, _event=None) -> None:
        selection = self.finding_tree.selection()
        if selection:
            finding = self._finding_by_id[selection[0]]
            source_ids = set(finding.get('source_ids') or [])
            related = [row for row in selected_rows(self.payload) if row.get('stable_key') in source_ids]
            self._show_detail({**finding, 'source_statements': related})

    def _generate_single_policy(self) -> None:
        """Show the combined, ordered policy with source comments and copy action."""
        generated = CrossTenancyAnalysisService.generate_single_policy(self.payload)
        window = tk.Toplevel(self.winfo_toplevel())
        window.title('Single Cross-Tenancy Policy')
        window.geometry('900x650')
        window.transient(self.winfo_toplevel())
        window.grab_set()
        summary = (
            f'Included: {generated["included"]} valid, resolved Define / Admit / Endorse statements from all loaded policies. '
            f'Not included: {generated["invalid_or_unparsed"]} invalid or unparsed, '
            f'{generated["unresolved_or_ambiguous"]} unresolved or ambiguous, and '
            f'{generated["unclassified"]} unclassified statements.'
        )
        ttk.Label(window, text=summary, wraplength=850, justify='left').pack(fill='x', padx=12, pady=12)
        policies = generated.get('policies') or [{'name': 'CrossTenancy-01', 'text': generated.get('text', '')}]
        selected = tk.StringVar(value=policies[0]['name'])
        selector = ttk.Combobox(
            window, textvariable=selected, values=[item['name'] for item in policies], state='readonly'
        )
        selector.pack(fill='x', padx=12, pady=(0, 8))
        editor = ScrolledText(window, wrap='none', font=('TkFixedFont', 10))
        editor.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        editor.insert('1.0', policies[0]['text'] or 'No valid, resolved cross-tenancy statements are available.')
        editor.configure(state='disabled')

        def show_policy(_event=None):
            editor.configure(state='normal')
            editor.delete('1.0', 'end')
            editor.insert('1.0', policies[selector.current()]['text'])
            editor.configure(state='disabled')

        selector.bind('<<ComboboxSelected>>', show_policy)
        buttons = ttk.Frame(window)
        buttons.pack(fill='x', padx=12, pady=(0, 12))

        def copy_policy():
            window.clipboard_clear()
            window.clipboard_append(policies[selector.current()]['text'])
            window.update_idletasks()

        ttk.Button(buttons, text='Copy policy', command=copy_policy).pack(side='left')
        ttk.Button(buttons, text='Close', command=window.destroy).pack(side='right')

    def _schedule_redraw(self, _event=None) -> None:
        if self._redraw_after:
            self.after_cancel(self._redraw_after)
        self._redraw_after = self.after(100, self._draw_graph)

    def apply_settings(self, context_help: bool, font_size: str) -> None:
        super().apply_settings(context_help, font_size)
        if hasattr(self, 'canvas'):
            self._draw_graph()

    def _add_card(
        self,
        x: int,
        y: int,
        label: str,
        key: str,
        keys: set[str],
        *,
        color: str = '#ffffff',
        width: int = 220,
        height: int = 48,
    ) -> int:
        active = key == self._selection_id
        tag = f'item{len(self._graph_items)}'
        self._graph_items[tag] = (key, keys)
        text_id = self.canvas.create_text(
            x + 10,
            y + 8,
            text=label,
            anchor='nw',
            width=width - 20,
            font=('TkDefaultFont', getattr(self, '_current_font_size', 11)),
            fill='#152b3b',
            tags=(tag,),
        )
        bounds = self.canvas.bbox(text_id)
        height = max(height, (bounds[3] - bounds[1] if bounds else 0) + 16)
        rectangle = self.canvas.create_rectangle(
            x,
            y,
            x + width,
            y + height,
            fill='#d8ebf8' if active else color,
            outline='#245979' if active else '#9aafc2',
            width=2 if active else 1,
            tags=(tag,),
        )
        self.canvas.tag_lower(rectangle, text_id)
        self.canvas.tag_bind(tag, '<Button-1>', lambda _e, item=tag: self._select_graph_item(item))
        self.canvas.tag_bind(tag, '<Enter>', lambda _e: self.canvas.configure(cursor='hand2'))
        self.canvas.tag_bind(tag, '<Leave>', lambda _e: self.canvas.configure(cursor=''))
        return height

    def _select_graph_item(self, tag: str) -> None:
        key, keys = self._graph_items[tag]
        if self._selection_id == key:
            self._selection_id, self._selection_keys = '', None
        else:
            self._selection_id, self._selection_keys = key, keys
        self.relationship_var.set(
            next(
                (label for label, item_key, _ in self._relationships if item_key == self._selection_id),
                'All relationships',
            )
        )
        self._draw_graph()
        self._render_rows()

    def _on_relationship_selected(self, _event=None) -> None:
        label = self.relationship_var.get()
        selected = next(((key, keys) for name, key, keys in self._relationships if name == label), None)
        self._selection_id, self._selection_keys = selected if selected else ('', None)
        self._draw_graph()
        self._render_rows()

    def _draw_graph(self) -> None:
        self._redraw_after = None
        self.canvas.delete('all')
        self._graph_items.clear()
        graph = self.payload.get('relationship_graph') or {}
        local = self.payload.get('local_tenancy') or {}
        links = graph.get('links') or []
        children = graph.get('subnodes') or []
        width = max(self.canvas.winfo_width(), 800)
        centers = (25, max(290, width // 2 - 110), max(565, width - 245))
        for x, title in zip(centers, ('Admitted · controls us', 'Our tenancy', 'Endorsed · we control'), strict=True):
            self.canvas.create_text(x, 17, text=title, anchor='nw', fill='#34546b', font=('TkDefaultFont', 10, 'bold'))
        local_keys = {
            key for node in children if node.get('tenancy_alias') == 'local' for key in node.get('statement_keys', [])
        }
        local_height = self._add_card(
            centers[1], 48, local.get('name') or 'This tenancy', 'local', local_keys, color='#e0f2e9'
        )
        max_y = 110
        for lane, direction in ((0, 'incoming'), (2, 'outgoing')):
            y = 55
            grouped: dict[str, list[dict]] = {}
            for link in links:
                if link.get('direction') == direction:
                    grouped.setdefault(str(link.get('alias') or '').casefold(), []).append(link)
            for alias_key, matched in grouped.items():
                alias = matched[0].get('alias') or alias_key
                keys = {key for link in matched for key in link.get('statement_keys', [])}
                keys.update(
                    row['stable_key']
                    for row in self.payload.get('defines', [])
                    if str(row.get('defined_type') or '').casefold() == 'tenancy'
                    and str(row.get('defined_name') or '').casefold() == alias_key
                )
                tenancy = next(
                    (node for node in graph.get('tenancies', []) if str(node.get('alias')).casefold() == alias_key), {}
                )
                label = f'{alias}  ·  {len(keys)} source(s)' + ('  ·  any tenancy' if tenancy.get('special') else '')
                node_key = f'tenancy:{alias_key}:{direction}'
                tenancy_height = self._add_card(
                    centers[lane], y, label, node_key, keys, color='#fff5e9' if lane == 0 else '#eaf4fb'
                )
                line_y = y + tenancy_height / 2
                center_y = 48 + local_height / 2
                x1, x2 = (centers[0] + 220, centers[1]) if lane == 0 else (centers[1] + 220, centers[2])
                for link in matched:
                    line_key = str(link.get('id') or f'link:{alias_key}:{direction}:{link.get("association")}')
                    tag = f'item{len(self._graph_items)}'
                    self._graph_items[tag] = (line_key, set(link.get('statement_keys') or []))
                    y1, y2 = (line_y, center_y) if lane == 0 else (center_y, line_y)
                    self.canvas.create_line(
                        x1,
                        y1,
                        x2,
                        y2,
                        fill='#865ba6' if link.get('association') else '#49738b',
                        width=2,
                        dash=(5, 4) if link.get('association') else (),
                        tags=(tag,),
                    )
                    self.canvas.tag_bind(tag, '<Button-1>', lambda _e, item=tag: self._select_graph_item(item))
                    line_y += 5
                y += tenancy_height + 6
                for child in children:
                    if str(child.get('tenancy_alias') or '').casefold() != alias_key:
                        continue
                    if not keys.intersection(child.get('statement_keys') or []):
                        continue
                    child_keys = set(child.get('statement_keys') or [])
                    child_height = self._add_card(
                        centers[lane] + 14,
                        y,
                        f'{child.get("kind")} · {child.get("name")}',
                        child.get('id') or '',
                        child_keys,
                        width=206,
                        height=38,
                    )
                    y += child_height + 5
                y += 15
            max_y = max(max_y, y)
        local_y = 48 + local_height + 10
        for child in children:
            if child.get('tenancy_alias') == 'local':
                child_height = self._add_card(
                    centers[1] + 14,
                    local_y,
                    f'{child.get("kind")} · {child.get("name")}',
                    child.get('id') or '',
                    set(child.get('statement_keys') or []),
                    width=206,
                    height=38,
                )
                local_y += child_height + 5
        max_y = max(max_y, local_y)
        unplaced = [node for node in children if not node.get('tenancy_alias')]
        orphans = [node for node in graph.get('defined_entities', []) or [] if node.get('orphan')]
        if unplaced or orphans:
            max_y += 20
            self.canvas.create_text(
                25,
                max_y,
                text='Unplaced and orphan definitions',
                anchor='nw',
                font=('TkDefaultFont', 10, 'bold'),
                fill='#34546b',
            )
            max_y += 26
            for node in unplaced:
                card_height = self._add_card(
                    25,
                    max_y,
                    f'Unplaced · {node.get("kind")} {node.get("name")}',
                    node.get('id') or '',
                    set(node.get('statement_keys') or []),
                    width=300,
                    height=38,
                )
                max_y += card_height + 5
            for node in orphans:
                card_height = self._add_card(
                    25,
                    max_y,
                    f'Orphan · {node.get("defined_type")} {node.get("defined_name")}',
                    node.get('id') or '',
                    set(node.get('statement_keys') or []),
                    width=300,
                    height=38,
                )
                max_y += card_height + 5
        self.canvas.configure(scrollregion=(0, 0, max(width, centers[2] + 245), max_y + 30))

    def _clear_filters(self) -> None:
        self._selection_id, self._selection_keys = '', None
        self.relationship_var.set('All relationships')
        self.entity_var.set('All')
        self.filter_var.set('')
        self._draw_graph()
        self._render_rows()

    def _render_rows(self) -> None:
        if not hasattr(self, 'statement_tree'):
            return
        entity = getattr(self, '_entity_by_label', {}).get(self.entity_var.get())
        keys = self._selection_keys
        if entity:
            entity_keys = set(entity.get('statement_keys') or [])
            keys = entity_keys if keys is None else keys & entity_keys
        visible = selected_rows(self.payload, keys, self.filter_var.get())
        self.statement_tree.delete(*self.statement_tree.get_children())
        self._row_by_id.clear()
        for index, row in enumerate(visible):
            associated = (
                row.get('tenancy_associations') if row.get('kind') == 'Define' else row.get('external_tenancies')
            )
            names = ', '.join(item.get('name') or item.get('alias') or '' for item in associated or [])
            if row.get('kind') == 'Define':
                names = (
                    f'{names}{"" if str(row.get("defined_type") or "").casefold() == "tenancy" else " (deduced)"}'
                    if names
                    else '<not associated>'
                )
            iid = f'row:{index}'
            self.statement_tree.insert(
                '',
                'end',
                iid=iid,
                values=(
                    row.get('kind') or '',
                    row.get('policy_name') or '',
                    row.get('statement_text') or '',
                    names or '—',
                ),
            )
            self._row_by_id[iid] = row
        total = len(selected_rows(self.payload))
        self.statement_count_var.set(f'{len(visible)} of {total} statements')

    def update_cross_tenancy_output(self) -> None:
        """Redraw the current in-memory snapshot; OCI reload is a separate action."""
        repo = self.main_app.policy_compartment_analysis
        intelligence = getattr(self.main_app, 'policy_intelligence', None)
        findings = (getattr(intelligence, 'overlay', {}) or {}).get('cross_tenancy_findings', [])
        corpus = getattr(getattr(self.main_app, 'app_context', None), 'cross_tenancy_corpus', None)
        self.payload = CrossTenancyAnalysisService(repo, findings, corpus).get_analysis_payload()
        graph = self.payload.get('relationship_graph') or {}
        self._selection_id, self._selection_keys = '', None
        self._relationships = [('All relationships', '', set())]
        for direction in ('incoming', 'outgoing'):
            aliases = {
                str(link.get('alias') or '').casefold()
                for link in graph.get('links', [])
                if link.get('direction') == direction
            }
            for alias in sorted(aliases):
                keys = {
                    key
                    for link in graph.get('links', [])
                    if str(link.get('alias') or '').casefold() == alias and link.get('direction') == direction
                    for key in link.get('statement_keys', [])
                }
                keys.update(
                    row['stable_key']
                    for row in self.payload.get('defines', [])
                    if str(row.get('defined_type') or '').casefold() == 'tenancy'
                    and str(row.get('defined_name') or '').casefold() == alias
                )
                self._relationships.append((f'{alias} · {direction}', f'tenancy:{alias}:{direction}', keys))
        for link in graph.get('links', []):
            description = 'Associate' if link.get('association') else 'Trust'
            self._relationships.append(
                (
                    f'{description} · {link.get("alias")} · {link.get("direction")}',
                    link.get('id') or '',
                    set(link.get('statement_keys') or []),
                )
            )
        for node in graph.get('subnodes', []):
            self._relationships.append(
                (
                    f'{node.get("kind")} · {node.get("name")} · {node.get("tenancy_alias") or "unplaced"}',
                    node.get('id') or '',
                    set(node.get('statement_keys') or []),
                )
            )
        for node in graph.get('defined_entities', []):
            if node.get('orphan'):
                self._relationships.append(
                    (
                        f'Orphan · {node.get("defined_name")}',
                        node.get('id') or '',
                        set(node.get('statement_keys') or []),
                    )
                )
        self.relationship_combo['values'] = [label for label, _, _ in self._relationships]
        self.relationship_var.set('All relationships')
        entities = graph.get('defined_entities', [])
        self._entity_by_label = {
            f'{node.get("defined_type")} · {node.get("defined_name")} · {index + 1}': node
            for index, node in enumerate(entities)
        }
        self.entity_combo['values'] = ['All', *self._entity_by_label]
        self.entity_var.set('All')
        self.finding_tree.delete(*self.finding_tree.get_children())
        self._finding_by_id.clear()
        for index, finding in enumerate(self.payload.get('findings', [])):
            iid = f'finding:{index}'
            self.finding_tree.insert(
                '',
                'end',
                iid=iid,
                values=(
                    finding.get('Type') or '',
                    finding.get('Severity') or '',
                    finding.get('Policy Name') or '',
                    finding.get('Alias') or '',
                    finding.get('Issue') or '',
                ),
            )
            self._finding_by_id[iid] = finding
        counts = self.payload.get('counts') or {}
        LOGGER.info(
            'Cross-tenancy view refreshed: defines=%d admits=%d endorses=%d unknown=%d findings=%d '
            'tenancies=%d links=%d entities=%d',
            counts.get('defines', 0),
            counts.get('admit', 0),
            counts.get('endorse', 0),
            counts.get('unknown', 0),
            counts.get('findings', 0),
            len(graph.get('tenancies', [])),
            len(graph.get('links', [])),
            len(graph.get('subnodes', [])),
        )
        self.count_var.set(
            f'{counts.get("defines", 0)} defines · {counts.get("admit", 0)} admits · '
            f'{counts.get("endorse", 0)} endorses · {counts.get("findings", 0)} findings'
        )
        self._render_rows()
        self._draw_graph()
