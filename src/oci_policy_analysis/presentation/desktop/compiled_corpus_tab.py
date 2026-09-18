"""Experimental corpus build, exploration, and manual scenario workbench."""

from __future__ import annotations

import json
import logging
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.application.core.engine.compiled_corpus import (
    LOG_COMPONENT,
    BuildCancelled,
    missing_permission_mappings,
)
from oci_policy_analysis.application.core.support.logger import get_logger, set_component_level
from oci_policy_analysis.application.services.compiled_corpus_service import (
    FILTER_FIELDS,
    FILTER_OPERATORS,
    CompiledCorpusService,
    filter_corpus_grants,
    format_corpus_condition,
)
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab

logger = get_logger(LOG_COMPONENT)


class _CorpusLogHandler(logging.Handler):
    """Queue formatted records without calling Tk from worker threads."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = queue.Queue(maxsize=5000)
        self.dropped = 0
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record):
        try:
            self.records.put_nowait(self.format(record))
        except queue.Full:
            self.dropped += 1
        except Exception:
            self.handleError(record)


class CompiledCorpusTab(BaseUITab):
    """Keep Tk access on the main thread; workers publish progress through a queue."""

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text=(
                'Build an inspectable snapshot of loaded policy permissions and conditions. '
                'Each manual request uses shared context plus its own overrides. Policy changes require a rebuild.'
            ),
        )
        self.app = app
        self.service = CompiledCorpusService(app.app_context)
        self.corpus = None
        self.suite = {'schema_version': 1, 'shared_context': {}, 'scenarios': []}
        self.results = None
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self._checking = False
        self._grant_rows = {}
        self._context_entries = {}
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=8, pady=6)
        self.build_button = ttk.Button(bar, text='Build Compiled Corpus', command=self._build)
        self.build_button.pack(side='left')
        self.cancel_button = ttk.Button(bar, text='Cancel', state='disabled', command=self.cancel.set)
        self.cancel_button.pack(side='left', padx=5)
        ttk.Button(bar, text='Export Corpus…', command=self._export_corpus).pack(side='left', padx=5)
        ttk.Button(bar, text='Open Corpus…', command=self._open_corpus).pack(side='left')
        self.status = tk.StringVar(value='Load policy data, then build a corpus.')
        ttk.Label(self, textvariable=self.status, wraplength=1250).pack(fill='x', padx=8)
        self.progress = ttk.Progressbar(self, maximum=100)
        self.progress.pack(fill='x', padx=8, pady=5)
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=8, pady=5)
        explore, context, mappings, evaluate, results, logs = (ttk.Frame(notebook) for _ in range(6))
        for frame, title in (
            (explore, 'Explore Corpus'),
            (context, 'Context & Coverage'),
            (mappings, 'Missing Permission Mappings'),
            (evaluate, 'Manual Scenarios'),
            (results, 'Results & Contribution'),
            (logs, 'Build & Evaluation Logs'),
        ):
            notebook.add(frame, text=title)
        self._create_explorer(explore)
        self.catalog = self._text(context)
        self._create_mapping_gaps(mappings)
        self._create_scenarios(evaluate)
        self.result_text = self._text(results)
        ttk.Button(
            results, text='Export Results…', command=lambda: self._save(self.results, 'corpus-results.json')
        ).pack()
        self.log_text = self._text(logs)
        ttk.Label(
            logs,
            text='Component: compiled_corpus • INFO: stages and counts • DEBUG: fields, sources and scenario details',
        ).pack(anchor='w')
        ttk.Button(logs, text='Clear Log View', command=lambda: self._show(self.log_text, '')).pack(anchor='w')
        ttk.Button(bar, text='View Logs', command=lambda: notebook.select(logs)).pack(side='right', padx=5)
        configured = getattr(app, 'settings', {}).get('log_levels', {}).get(LOG_COMPONENT, 'INFO')
        self.log_level = tk.StringVar(value=configured)
        self.log_level_combo = ttk.Combobox(
            bar, textvariable=self.log_level, values=('DEBUG', 'INFO', 'WARNING', 'ERROR'), width=9, state='readonly'
        )
        self.log_level_combo.pack(side='right')
        self.log_level_combo.bind('<<ComboboxSelected>>', self._set_log_level)
        ttk.Label(bar, text='Corpus logging:').pack(side='right', padx=5)
        self._log_handler = _CorpusLogHandler()
        logger.addHandler(self._log_handler)
        self.bind('<Destroy>', self._detach_log_handler, add='+')
        self._set_log_level()
        self.after(100, self._poll)
        self.after(2000, self._watch)

    def _set_log_level(self, _event=None):
        set_component_level(LOG_COMPONENT, self.log_level.get())
        self.log_level.set(logging.getLevelName(logger.getEffectiveLevel()))
        settings = getattr(self.app, 'settings', None)
        if isinstance(settings, dict):
            settings.setdefault('log_levels', {})[LOG_COMPONENT] = self.log_level.get()
        logger.info('Corpus logging set to %s; component logs appear here and in app.log', self.log_level.get())

    def _detach_log_handler(self, event):
        if event.widget is self:
            logger.removeHandler(self._log_handler)
            self._log_handler.close()

    def _flush_logs(self):
        messages = []
        for _ in range(200):
            try:
                messages.append(self._log_handler.records.get_nowait())
            except queue.Empty:
                break
        if self._log_handler.dropped:
            messages.append(
                f'Log view skipped {self._log_handler.dropped} records while busy; full output remains in app.log.'
            )
            self._log_handler.dropped = 0
        if messages:
            self.log_text.configure(state='normal')
            self.log_text.insert('end', '\n'.join(messages) + '\n')
            lines = int(self.log_text.index('end-1c').split('.')[0])
            if lines > 5000:
                self.log_text.delete('1.0', f'{lines - 5000}.0')
            self.log_text.see('end')
            self.log_text.configure(state='disabled')

    @staticmethod
    def _text(parent, height=12):
        text = ScrolledText(parent, wrap='word', height=height, state='disabled')
        text.pack(fill='both', expand=True, padx=4, pady=4)
        return text

    @staticmethod
    def _show(widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False))
        widget.configure(state='disabled')

    @staticmethod
    def _tree(parent, columns, height=9):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=height, selectmode='browse')
        for column in columns:
            tree.heading(column, text=column.replace('_', ' ').title())
            tree.column(column, width=140, minwidth=70)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return tree

    def _create_explorer(self, parent):
        self.page = 0
        filter_area = ttk.LabelFrame(
            parent, text='All filters must match (AND); source filters must match the same supporting statement'
        )
        filter_area.pack(fill='x', pady=4)
        actions = ttk.Frame(filter_area)
        actions.pack(fill='x')
        ttk.Button(actions, text='Add Filter', command=self._add_filter).pack(side='left')
        ttk.Button(actions, text='Apply Filters', command=self._filter_grants).pack(side='left', padx=4)
        ttk.Button(actions, text='Clear Filters', command=self._clear_filters).pack(side='left')
        paging = ttk.Frame(actions)
        paging.pack(side='right')
        ttk.Button(paging, text='Previous', command=lambda: self._page(-1)).pack(side='left', padx=4)
        ttk.Button(paging, text='Next', command=lambda: self._page(1)).pack(side='left')
        self.page_label = ttk.Label(paging)
        self.page_label.pack(side='left', padx=5)
        self.filter_container = ttk.Frame(filter_area)
        self.filter_container.pack(fill='x')
        self.filter_rows = []
        self._add_filter('principal')
        self._add_filter('scope')
        self.grants = self._tree(parent, ('principal', 'scope', 'permission', 'effect', 'condition', 'sources'))
        self.grants.column('condition', width=380)
        self.grants.column('sources', width=70, stretch=False)
        self.grants.bind('<<TreeviewSelect>>', self._select_grant)
        self.detail = self._text(parent, 10)

    def _add_filter(self, field='permission'):
        row = ttk.Frame(self.filter_container)
        row.pack(fill='x', pady=2)
        field_var = tk.StringVar(value=field)
        operator_var = tk.StringVar(value='contains')
        value_var = tk.StringVar()
        ttk.Combobox(row, textvariable=field_var, values=FILTER_FIELDS, state='readonly', width=17).pack(side='left')
        ttk.Combobox(row, textvariable=operator_var, values=FILTER_OPERATORS, state='readonly', width=15).pack(
            side='left', padx=4
        )
        entry = ttk.Entry(row, textvariable=value_var, width=60)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda _: self._filter_grants())
        item = (row, field_var, operator_var, value_var)
        ttk.Button(row, text='Remove', command=lambda: self._remove_filter(item)).pack(side='left', padx=4)
        self.filter_rows.append(item)

    def _remove_filter(self, item):
        self.filter_rows.remove(item)
        item[0].destroy()
        self._filter_grants()

    def _clear_filters(self):
        for _, _, _, value in self.filter_rows:
            value.set('')
        self._filter_grants()

    def _page(self, delta):
        self.page = max(0, self.page + delta)
        self._filter_grants(reset=False)

    def _filter_grants(self, reset=True):
        if reset:
            self.page = 0
        filters = [
            {'field': field.get(), 'operator': operator.get(), 'value': value.get()}
            for _, field, operator, value in self.filter_rows
        ]
        rows = filter_corpus_grants(self.corpus or {}, filters=filters)
        self.page = min(self.page, max(0, (len(rows) - 1) // 250))
        self.grants.delete(*self.grants.get_children())
        self._grant_rows = {}
        for grant in rows[self.page * 250 : (self.page + 1) * 250]:
            self._grant_rows[grant['id']] = grant
            predicate = self.corpus['predicates'][grant['predicate_id']]
            self.grants.insert(
                '',
                'end',
                iid=grant['id'],
                values=(
                    grant['principal'],
                    grant['scope'],
                    grant['permission'],
                    grant['effect'],
                    format_corpus_condition(predicate),
                    len(grant['source_ids']),
                ),
            )
        total = len((self.corpus or {}).get('grants', []))
        self.page_label.configure(text=f'{len(rows):,} / {total:,} grants • page {self.page + 1}')
        if self.grants.get_children():
            self.grants.selection_set(self.grants.get_children()[0])
        else:
            self._show(
                self.detail,
                'No grants match these filters. Missing expansions are listed in Missing Permission Mappings.',
            )

    def _create_mapping_gaps(self, parent):
        self.mapping_summary = tk.StringVar(value='Build or open a corpus to list missing permission mappings.')
        ttk.Label(parent, textvariable=self.mapping_summary, wraplength=1200).pack(fill='x', padx=4, pady=4)
        ttk.Label(
            parent, text='Grouped by resource + verb + effect. Select a row for affected policies and statements.'
        ).pack(anchor='w', padx=4)
        ttk.Button(parent, text='Export Missing Mappings…', command=self._export_mapping_gaps).pack(
            anchor='w', padx=4, pady=4
        )
        self.mapping_tree = self._tree(parent, ('resource', 'verb', 'effect', 'statement_count', 'policy_count'))
        self.mapping_tree.bind('<<TreeviewSelect>>', self._select_mapping_gap)
        self.mapping_detail = self._text(parent, 10)
        self.mapping_rows = []

    def _display_mapping_gaps(self):
        self.mapping_rows = missing_permission_mappings(self.corpus or {})
        self.mapping_tree.delete(*self.mapping_tree.get_children())
        for index, row in enumerate(self.mapping_rows):
            self.mapping_tree.insert(
                '',
                'end',
                iid=str(index),
                values=(row['resource'], row['verb'], row['effect'], row['statement_count'], len(row['policy_names'])),
            )
        affected = sum(row['statement_count'] for row in self.mapping_rows)
        self.mapping_summary.set(
            f'{len(self.mapping_rows)} missing resource/verb/effect mappings affecting {affected} statements. '
            'Update the permission reference JSON, reload reference data, then rebuild.'
        )
        self._show(
            self.mapping_detail, 'No missing expansion diagnostics in this snapshot.' if not self.mapping_rows else ''
        )
        if self.mapping_rows:
            self.mapping_tree.selection_set('0')

    def _select_mapping_gap(self, _event=None):
        selection = self.mapping_tree.selection()
        if selection:
            row = self.mapping_rows[int(selection[0])]
            self._show(
                self.mapping_detail,
                {
                    'mapping': row,
                    'affected_statements': {sid: self.corpus['sources'].get(sid, {}) for sid in row['source_ids']},
                },
            )

    def _export_mapping_gaps(self):
        if not self.corpus:
            messagebox.showinfo('Missing mappings', 'Build or open a corpus first.')
            return
        self._save(
            {
                'snapshot_id': self.corpus['snapshot_id'],
                'missing_permission_mappings': self.mapping_rows,
                'sources': {
                    sid: self.corpus['sources'].get(sid, {}) for row in self.mapping_rows for sid in row['source_ids']
                },
            },
            'missing-permission-mappings.json',
        )

    def _select_grant(self, _event=None):
        selection = self.grants.selection()
        if selection:
            grant = self._grant_rows[selection[0]]
            self._show(
                self.detail,
                {
                    'grant': grant,
                    'condition': format_corpus_condition(self.corpus['predicates'][grant['predicate_id']]),
                    'parsed_condition': self.corpus['predicates'][grant['predicate_id']],
                    'provenance': {s: self.corpus['sources'][s] for s in grant['source_ids']},
                },
            )

    def _create_scenarios(self, parent):
        shared = ttk.LabelFrame(parent, text='Shared context — JSON object (scenario values override these)')
        shared.pack(fill='x', pady=3)
        self.shared_text = ScrolledText(shared, height=3, wrap='word')
        self.shared_text.pack(fill='x')
        self.shared_text.insert('1.0', '{}')
        ttk.Label(
            shared, text='Example: {"request.region": "iad", "request.utc-timestamp": "2026-09-11T12:00:00Z"}'
        ).pack(anchor='w')
        editor = ttk.LabelFrame(parent, text='Request')
        editor.pack(fill='x', pady=3)
        self.name = tk.StringVar()
        self.principal = tk.StringVar()
        self.operation = tk.StringVar()
        self.api_group = tk.StringVar()
        self.scope = tk.StringVar()
        self.expected = tk.StringVar()
        for row, (label, variable) in enumerate(
            (
                ('Name', self.name),
                ('Principal key', self.principal),
                ('OCI API / catalog group', self.api_group),
                ('API operation', self.operation),
                ('Target compartment', self.scope),
            )
        ):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky='w', padx=5)
            combo = ttk.Combobox(editor, textvariable=variable, width=70)
            combo.grid(row=row, column=1, sticky='ew', padx=5, pady=1)
            setattr(
                self,
                (
                    'api_group_combo'
                    if variable is self.api_group
                    else 'principal_combo'
                    if variable is self.principal
                    else 'operation_combo'
                    if variable is self.operation
                    else 'scope_combo'
                    if variable is self.scope
                    else 'name_combo'
                ),
                combo,
            )
        self.api_group_combo.configure(state='readonly')
        self.api_group_combo.bind('<<ComboboxSelected>>', self._select_api_group)
        editor.columnconfigure(1, weight=1)
        ttk.Label(editor, text='Expected result (optional)').grid(row=0, column=2, padx=5)
        ttk.Combobox(
            editor,
            textvariable=self.expected,
            values=('', 'allowed', 'denied', 'indeterminate'),
            state='readonly',
            width=16,
        ).grid(row=0, column=3, padx=5)
        ttk.Button(editor, text='Find Relevant Context', command=self._find_context).grid(row=1, column=2, columnspan=2)
        self.context_note = tk.StringVar(value='Select a request, then find its relevant context fields.')
        ttk.Label(parent, textvariable=self.context_note, wraplength=1250).pack(anchor='w')
        # A scrollable form keeps large condition catalogs usable.
        context_frame = ttk.Frame(parent, height=110)
        context_frame.pack(fill='both', expand=True)
        self.context_canvas = tk.Canvas(context_frame, height=100, highlightthickness=0)
        scrollbar = ttk.Scrollbar(context_frame, orient='vertical', command=self.context_canvas.yview)
        self.context_canvas.configure(yscrollcommand=scrollbar.set)
        self.context_canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.context_fields = ttk.Frame(self.context_canvas)
        self.context_canvas.create_window((0, 0), window=self.context_fields, anchor='nw')
        self.context_fields.bind(
            '<Configure>', lambda _: self.context_canvas.configure(scrollregion=self.context_canvas.bbox('all'))
        )
        actions = ttk.Frame(parent)
        actions.pack(fill='x', pady=3)
        for label, command in (
            ('Add Request', self._add),
            ('Update Selected', self._update),
            ('Remove Selected', self._remove),
            ('Save Suite…', self._save_suite),
            ('Open Suite…', self._open_suite),
        ):
            ttk.Button(actions, text=label, command=command).pack(side='left', padx=2)
        self.scenarios = self._tree(parent, ('name', 'principal', 'operation', 'scope', 'overrides', 'expected'), 4)
        self.scenarios.bind('<<TreeviewSelect>>', self._select_scenario)
        bar = ttk.Frame(parent)
        bar.pack(fill='x', pady=3)
        self.run_button = ttk.Button(bar, text='Run Scenarios', command=lambda: self._run(False), state='disabled')
        self.run_button.pack(side='left', padx=3)
        self.contribution_button = ttk.Button(
            bar, text='Analyze Statement Contribution', command=lambda: self._run(True), state='disabled'
        )
        self.contribution_button.pack(side='left')

    def _shared(self):
        data = json.loads(self.shared_text.get('1.0', 'end'))
        if not isinstance(data, dict):
            raise ValueError('Shared context must be a JSON object.')
        return data

    def _select_api_group(self, _event=None):
        operations = self.corpus['inputs']['reference_data'].get('operations', {}) if self.corpus else {}
        group = self.api_group.get()
        self.operation_combo['values'] = sorted(op for op in operations if op.startswith(group + ':'))
        self.operation.set('')

    def _scenario(self):
        overrides = {}
        for variable, (mode, value) in self._context_entries.items():
            if mode.get() == 'Value':
                overrides[variable] = value.get()
            elif mode.get() == 'Absent':
                overrides[variable] = None
        return {
            'name': self.name.get(),
            'principal_key': self.principal.get(),
            'api_operation': self.operation.get(),
            'compartment_path': self.scope.get(),
            'context': overrides,
            'expected': self.expected.get(),
        }

    def _render_context(self, fields, values=None):
        values = values or {}
        try:
            shared = self._shared()
        except ValueError:
            shared = {}
        for widget in self.context_fields.winfo_children():
            widget.destroy()
        self._context_entries = {}
        for row, variable in enumerate(sorted(set(fields) | set(values))):
            mode = tk.StringVar(
                value='Absent'
                if variable in values and values[variable] is None
                else 'Value'
                if variable in values
                else 'Shared / unknown'
            )
            value = tk.StringVar(value=str(values.get(variable) or ''))
            label = {
                'corpus.deny_enabled': 'Tenancy deny policies enabled (true / false)',
                'corpus.deny_exempt': 'Principal exempt from deny (true / false)',
            }.get(variable, variable)
            ttk.Label(self.context_fields, text=label, width=48).grid(row=row, column=0, sticky='w')
            ttk.Combobox(
                self.context_fields,
                textvariable=mode,
                values=('Shared / unknown', 'Value', 'Absent'),
                state='readonly',
                width=20,
            ).grid(row=row, column=1, padx=4)
            ttk.Entry(self.context_fields, textvariable=value, width=55).grid(row=row, column=2)
            inherited = json.dumps(shared[variable]) if variable in shared else 'unknown'
            ttk.Label(self.context_fields, text=f'Shared: {inherited}').grid(row=row, column=3, padx=5, sticky='w')
            self._context_entries[variable] = (mode, value)

    def _find_context(self):
        scenario = self._scenario()
        self._start('context', lambda: self.service.required_context(scenario))

    def _add(self):
        scenario = self._scenario()
        if not all(scenario[k] for k in ('principal_key', 'api_operation', 'compartment_path')):
            messagebox.showerror('Request', 'Supply principal, operation, and target compartment.')
            return
        self.suite['scenarios'].append(scenario)
        self._refresh_scenarios()

    def _update(self):
        selection = self.scenarios.selection()
        if selection:
            self.suite['scenarios'][int(selection[0])] = self._scenario()
            self._refresh_scenarios()

    def _remove(self):
        selection = self.scenarios.selection()
        if selection:
            del self.suite['scenarios'][int(selection[0])]
            self._refresh_scenarios()

    def _refresh_scenarios(self):
        self.scenarios.delete(*self.scenarios.get_children())
        for index, s in enumerate(self.suite['scenarios']):
            self.scenarios.insert(
                '',
                'end',
                iid=str(index),
                values=(
                    s.get('name'),
                    s['principal_key'],
                    s['api_operation'],
                    s['compartment_path'],
                    len(s.get('context', {})),
                    s.get('expected', ''),
                ),
            )

    def _select_scenario(self, _event=None):
        selection = self.scenarios.selection()
        if selection:
            s = self.suite['scenarios'][int(selection[0])]
            self.api_group.set(s.get('api_operation', '').partition(':')[0])
            self._select_api_group()
            for variable, key in (
                (self.name, 'name'),
                (self.principal, 'principal_key'),
                (self.operation, 'api_operation'),
                (self.scope, 'compartment_path'),
                (self.expected, 'expected'),
            ):
                variable.set(s.get(key, ''))
            self._render_context([], s.get('context', {}))

    def _run(self, contribution):
        try:
            self.suite['shared_context'] = self._shared()
            suite = json.loads(json.dumps(self.suite))
            self._start('results', lambda: self.service.run_suite(suite, contribution, self._progress, self.cancel))
        except (ValueError, TypeError) as exc:
            messagebox.showerror('Scenario suite', str(exc))

    def _build(self):
        if getattr(self.app, '_tenancy_load_in_progress', False) or getattr(
            self.app, '_policy_reload_in_progress', False
        ):
            messagebox.showinfo('Build corpus', 'Wait for the current data load to finish.')
            return
        self._start('build', lambda: self.service.build(self._progress, self.cancel))

    def _progress(self, done, total, message):
        self.events.put(('progress', (done, total, message)))

    def _start(self, kind, work):
        if self.busy:
            return
        self.busy = True
        self._set_log_level()
        logger.info('Tab action started: %s', kind)
        self.cancel.clear()
        self.build_button.configure(state='disabled')
        self.run_button.configure(state='disabled')
        self.contribution_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.status.set('Working…')

        def worker():
            try:
                self.events.put((kind, work()))
                logger.info('Tab action completed: %s', kind)
            except BuildCancelled:
                logger.info('Tab action cancelled: %s', kind)
                self.events.put(('cancelled', 'Cancelled; previous successful snapshot retained.'))
            except Exception as exc:
                logger.exception('Tab action failed: %s', kind)
                self.events.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        self._flush_logs()
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    done, total, message = value
                    self.progress['value'] = 100 * done / max(total, 1)
                    self.status.set(message)
                    continue
                if kind == 'watch':
                    self._checking = False
                    if not value and self.corpus and not self.busy:
                        self.status.set(
                            'Corpus out of date — rebuild required before evaluation. Previous snapshot remains inspectable.'
                        )
                        self._buttons()
                    continue
                self.busy = False
                if kind in ('build', 'open'):
                    self.corpus = value
                    self._display_corpus()
                elif kind == 'context':
                    self._render_context(value, self._scenario()['context'])
                    self.context_note.set(
                        f'{len(value)} relevant fields. Shared / unknown inherits shared values; Absent explicitly supplies null.'
                    )
                    self.status.set('Request context ready.')
                elif kind == 'results':
                    self.results = value
                    self._show_results(value)
                    self.status.set(f'Completed {len(value["results"])} scenarios. See Results & Contribution.')
                elif kind == 'error':
                    self.status.set(value)
                    messagebox.showerror(
                        'Compiled Corpus', f'{value}\n\nSee Build & Evaluation Logs for the traceback.'
                    )
                elif kind == 'cancelled':
                    self.status.set(value)
                self._buttons()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _buttons(self):
        self.build_button.configure(state='disabled' if self.busy else 'normal')
        state = 'normal' if self.corpus and not self.service.stale and not self.busy else 'disabled'
        self.run_button.configure(state=state)
        self.contribution_button.configure(state=state)
        self.cancel_button.configure(state='normal' if self.busy else 'disabled')

    def _watch(self):
        if self.corpus and not self.busy and not self._checking and not self.service.stale:
            self._checking = True

            def check():
                try:
                    current = self.service.check_current()
                except Exception:
                    logger.exception('Snapshot freshness check failed; corpus invalidated')
                    self.service.invalidate()
                    current = False
                self.events.put(('watch', current))

            threading.Thread(target=check, daemon=True).start()
        self.after(2000, self._watch)

    def populate_data(self):
        self.service.invalidate()
        self._buttons()
        if self.corpus:
            self.status.set('Loaded data changed — rebuild required before evaluation.')

    def _display_corpus(self):
        summary = self.corpus['summary']
        self.status.set(
            f'{summary["compiled_statements"]}/{summary["statements"]} statements compiled • '
            f'{summary["grants"]:,} grants • {summary["unresolved_statements"]} unresolved • '
            f'Snapshot {self.corpus["snapshot_id"][:12]}' + (' • Rebuild required' if self.service.stale else '')
        )
        self.progress['value'] = 100
        self._filter_grants()
        self._display_mapping_gaps()
        self._show(
            self.catalog, {k: self.corpus[k] for k in ('summary', 'context_catalog', 'diagnostics', 'limitations')}
        )
        self.principal_combo['values'] = sorted({g['principal'] for g in self.corpus['grants']})
        self.scope_combo['values'] = sorted(
            {g['scope'] for g in self.corpus['grants']}
            | {c.get('hierarchy_path', '') for c in self.corpus['inputs']['inventory'].get('compartments') or []}
        )
        self.api_group_combo['values'] = sorted(self.corpus['inputs']['reference_data'].get('operations_by_api', {}))
        self._select_api_group()

    def _show_results(self, result):
        lines = [f'Snapshot: {result["snapshot_id"]}', '', 'SCENARIO RESULTS']
        for r in result['results']:
            lines.append(f'{r["name"]}: {r["result"].upper()} (expected: {r["expected"] or "not specified"})')
        lines += ['', 'STATEMENT CONTRIBUTION']
        for sid, stats in result['statement_contribution'].items():
            source = self.corpus['sources'][sid]
            label = (
                'Decisive'
                if stats['decision_changes']
                else 'Permission-contributing'
                if stats['permission_changes']
                else 'Indeterminate'
                if stats['unknown'] or source['status'] != 'compiled'
                else 'Exercised; no measured change'
                if stats['exercised'] and result['contribution_analysis']
                else 'Exercised'
                if stats['exercised']
                else 'Not exercised'
            )
            lines.append(
                f'{source["statement_id"] or sid} • {source["policy_name"]}: {label} '
                f'({stats["exercised"]} exercised, {stats["decision_changes"]} decision changes)'
            )
        lines += ['', result['note'], '', 'FULL RESULTS / CONTEXT / WITNESSES', json.dumps(result, indent=2)]
        self._show(self.result_text, '\n'.join(lines))

    def _save(self, data, name):
        if data is None:
            messagebox.showinfo('Export', 'Nothing to export yet.')
            return
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile=name, filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(data, stream, indent=2, ensure_ascii=False)
            except OSError as exc:
                messagebox.showerror('Export', str(exc))

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path:
            return None
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)

    def _export_corpus(self):
        self._save(self.corpus, 'compiled-corpus.json')

    def _open_corpus(self):
        if self.busy:
            return
        try:
            data = self._load()
            if data is not None:
                self._start('open', lambda: self.service.open_corpus(data))
        except (ValueError, OSError) as exc:
            messagebox.showerror('Open corpus', str(exc))

    def _save_suite(self):
        try:
            self.suite['shared_context'] = self._shared()
            self._save(self.suite, 'corpus-scenarios.json')
        except ValueError as exc:
            messagebox.showerror('Save suite', str(exc))

    def _open_suite(self):
        try:
            data = self._load()
            if data is None:
                return
            if data.get('schema_version') != 1 or not isinstance(data.get('shared_context'), dict):
                raise ValueError('Expected a version 1 scenario suite with shared_context.')
            if not isinstance(data.get('scenarios'), list):
                raise ValueError('Expected a scenarios list.')
            for scenario in data['scenarios']:
                if not all(
                    isinstance(scenario.get(k), str) for k in ('principal_key', 'api_operation', 'compartment_path')
                ):
                    raise ValueError('Each scenario needs principal_key, api_operation and compartment_path strings.')
                if not isinstance(scenario.get('context', {}), dict):
                    raise ValueError('Scenario context must be an object.')
            self.suite = data
            self.shared_text.delete('1.0', 'end')
            self.shared_text.insert('1.0', json.dumps(data['shared_context'], indent=2))
            self._refresh_scenarios()
        except (ValueError, OSError, AttributeError) as exc:
            messagebox.showerror('Open suite', str(exc))
