##########################################################################
# Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# simulation_tab.py
#
# Main Simulation UI Tab for OCI Policy Simulator. Guides user through:
#   1. Selection of Compartment & Principal
#   2. Loading of relevant policy statements and where-clause elements
#   3. Selection of API operation, entry of test values for where variables
#   4. Running simulation and displaying results
#
# Sections are arranged top-down; logger writes info at each phase for audit and debug.
#
# Supports Python 3.12 and above
#
# @author: Andrew Gregory & Cline
#
##########################################################################

import json
import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger

logger = get_logger(component='simulation_tab')


# SimulationDebuggerTab has been removed.


class SimulationTab(ttk.Frame):
    """
    UI Tab for Policy Simulation:
      - Section 1: Compartment and Principal chooser (dropdowns, load button)
      - Section 2: Applies policy statement preview & where-fields preview
      - Section 3: API Operation chooser, dynamic where inputs, simulate button
      - Section 4: Results/tracing output

    All major user actions log info/debug for workflow tracking.
    """

    def __init__(self, parent, app, settings):
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = app.policy_compartment_analysis
        self.ref_data_repo = app.reference_data_repo
        self._sim_index_compartments = []
        self._sim_index_principals = {}
        logger.info('SimulationTab: assigned app, settings, policy_repo, ref_data_repo.')
        self.simulation_engine = app.simulation_engine
        logger.info('SimulationTab initialized: building layout...')

        self._init_state()
        self._build_layout()
        # Populate dropdowns if the engine/data is present
        self.refresh_dropdowns()

    def refresh_dropdowns(self):  # noqa: C901
        """
        Populate compartment and principal type/name tuples for policy_repo.
        Each principal value is (domain, name), except for any-user/service which is (None, name).
        """
        logger.info('SimulationTab: refreshing dropdowns for compartment/principal types/names.')
        compartments = set()
        principals_by_type = {}
        principal_types = set()
        # Collect compartments
        if self.policy_repo and hasattr(self.policy_repo, 'compartments'):
            for comp in getattr(self.policy_repo, 'compartments', []):
                path = comp.get('hierarchy_path')
                if path:
                    compartments.add(path)
        # Build principal index as (domain, name) for each principal
        if self.policy_repo and hasattr(self.policy_repo, 'regular_statements'):
            for stmt in self.policy_repo.regular_statements:
                subject_type = stmt.get('subject_type')
                subjects = stmt.get('subject', [])
                if not subject_type or not subjects:
                    continue
                principal_types.add(subject_type)
                principals_by_type.setdefault(subject_type, set())
                for subj in subjects:
                    if isinstance(subj, tuple | list) and len(subj) == 2:
                        domain, name = subj
                        # Defensive: skip cases where domain or name is unhashable list/dict (multinested)
                        if isinstance(domain, list | dict) or isinstance(name, list | dict):
                            logger.debug(
                                f'Skipping nested subject value domain={domain!r} name={name!r} in {subject_type}'
                            )
                            continue
                        if domain == 'default':
                            domain = None
                        principals_by_type[subject_type].add((domain, name))
                    elif isinstance(subj, str):
                        principals_by_type[subject_type].add((None, subj))
                    else:
                        logger.info(f'Skipping unhashable subject value={subj} for subject_type={subject_type}')
        # Fallbacks
        # Always include 'user' in principal types and populate user principals from repo, not just statements
        principal_types.add('user')
        if not compartments:
            compartments = {'ROOT'}
        self._sim_index_compartments = sorted(compartments)
        # Build _sim_index_principals['user'] from repo.users if available
        if hasattr(self.policy_repo, 'users'):
            user_set = set()
            for entry in getattr(self.policy_repo, 'users', []):
                domain = entry.get('domain_name')
                if domain == 'default':
                    domain = None
                name = entry.get('user_name')
                if name:
                    user_set.add((domain, name))
            self._sim_index_principals['user'] = sorted(user_set, key=lambda tup: ((tup[0] or ''), tup[1]))
        self._sim_index_principals.update(
            {k: sorted(v, key=lambda tup: ((tup[0] or ''), tup[1])) for k, v in principals_by_type.items()}
        )
        # Update comboboxes
        self._sim_index_principals.update(
            {k: sorted(v, key=lambda tup: ((tup[0] or ''), tup[1])) for k, v in principals_by_type.items()}
        )
        # Update comboboxes
        try:
            self.compartment_combobox['values'] = self._sim_index_compartments
            self.principal_type_combobox['values'] = sorted(principal_types)
        except Exception as ex:
            logger.info(f'refresh_dropdowns: unable to update combos ({ex})')
        if self.selected_compartment.get() not in self._sim_index_compartments:
            self.selected_compartment.set(next(iter(self._sim_index_compartments), 'ROOT'))
        if self.selected_principal_type.get() not in principal_types:
            self.selected_principal_type.set(next(iter(principal_types), 'any-user'))
        # Populate principal combobox with names (show "domain/name" if domain present for UI)
        self._update_principal_list()
        # After dropdowns are updated, refresh the debug tab if it exists
        if hasattr(self.app, 'sim_debugger_tab') and getattr(self.app, 'sim_debugger_tab', None):
            # For debug: show (domain, name)
            debug_index = {k: [f'{d}/{n}' if d else n for (d, n) in v] for k, v in self._sim_index_principals.items()}
            self.app.sim_debugger_tab.show_index(self._sim_index_compartments, debug_index)

    def _update_principal_list(self, *_):  # noqa: C901
        pt = self.selected_principal_type.get()
        if pt == 'user' and hasattr(self.policy_repo, 'users'):
            principals = []
            for entry in getattr(self.policy_repo, 'users', []):
                domain = entry.get('domain_name')
                if domain == 'default':
                    domain = None
                name = entry.get('user_name')
                if name:
                    principals.append((domain, name))
            display_principals = [
                f'{d}/{n}' if d else n for (d, n) in sorted(principals, key=lambda tup: ((tup[0] or ''), tup[1]))
            ]
        elif pt == 'service':
            # Gather all service names used in any policy statement where domain is None, and name is the service name
            svc_names = set()
            debug_service_subjects = []
            try:
                for stmt in getattr(self.policy_repo, 'regular_statements', []):
                    if stmt.get('subject_type') == 'service':
                        for subj in stmt.get('subject', []):
                            debug_service_subjects.append(repr(subj))
                            if isinstance(subj, tuple | list) and len(subj) == 2 and (subj[0] is None):
                                name_val = subj[1]
                                # name_val can be a string or a list of strings
                                if isinstance(name_val, list | tuple):
                                    for single in name_val:
                                        if isinstance(single, str) and single.strip():
                                            svc_names.add(single.strip())
                                elif isinstance(name_val, str) and name_val.strip():
                                    svc_names.add(name_val.strip())
                            elif isinstance(subj, str) and subj.strip():
                                svc_names.add(subj.strip())
            except Exception:
                pass
            logger.debug(
                f'Service principal dropdown population: subjects={debug_service_subjects}, result={sorted(svc_names)}'
            )
            display_principals = sorted(svc_names)
        else:
            principals = self._sim_index_principals.get(pt, [])
            display_principals = [f'{d}/{n}' if d else n for (d, n) in principals]
        self.principal_combobox['values'] = display_principals
        if pt == 'any-user':
            self.principal_combobox.config(state='disabled')
            try:
                self.principal_combobox.configure(background='#f0f0f0')  # standard ttk disabled background
            except Exception:
                pass
            self.selected_principal.set('')
        else:
            self.principal_combobox.config(state='readonly')
            try:
                self.principal_combobox.configure(background='white')
            except Exception:
                pass
            if display_principals and self.selected_principal.get() not in display_principals:
                self.selected_principal.set(display_principals[0])
            elif not display_principals:
                self.selected_principal.set('')

    def _init_state(self):
        self.selected_compartment = tk.StringVar()
        self.selected_principal_type = tk.StringVar()
        self.selected_principal = tk.StringVar()
        self.selected_api_operation = tk.StringVar()
        self.simulation_inputs = {}
        self.loaded_statements = []
        self.required_where_fields = set()
        self.simulation_results = None

    def _build_layout(self):
        # Top: Section 1 — Compartment/Principal selection
        select_frame = ttk.LabelFrame(self, text='1. Principal and Compartment Selection')
        select_frame.pack(fill='x', padx=8, pady=8)
        ttk.Label(select_frame, text='Compartment:').grid(row=0, column=0, sticky='w')
        self.compartment_combobox = ttk.Combobox(select_frame, textvariable=self.selected_compartment, width=50)
        self.compartment_combobox.grid(row=0, column=1, padx=2)
        ttk.Label(select_frame, text='Principal Type:').grid(row=0, column=2, sticky='w')
        self.principal_type_combobox = ttk.Combobox(
            select_frame, textvariable=self.selected_principal_type, width=20, state='readonly'
        )
        self.principal_type_combobox.grid(row=0, column=3, padx=2)
        self.principal_type_combobox.bind('<<ComboboxSelected>>', self._update_principal_list)
        ttk.Label(select_frame, text='Principal:').grid(row=0, column=4, sticky='w')
        self.principal_combobox = ttk.Combobox(
            select_frame, textvariable=self.selected_principal, width=30, state='readonly'
        )
        self.principal_combobox.grid(row=0, column=5, padx=2)
        self.load_button = ttk.Button(select_frame, text='Load Simulation', command=self.load_statements)
        self.load_button.grid(row=0, column=6, padx=8)

        # Middle: Section 2 — Policy statement and where-clause preview
        self.preview_frame = ttk.LabelFrame(self, text='2. Applicable Policies')
        self.preview_frame.pack(fill='both', padx=8, pady=8, expand=True)
        self.preview_frame.columnconfigure(0, weight=1)
        self.preview_frame.rowconfigure(0, weight=1)

        # Scrollable checklist of policy statements (fill all vertical space)
        self.stmt_canvas = tk.Canvas(self.preview_frame, borderwidth=0)
        yscroll = ttk.Scrollbar(self.preview_frame, orient='vertical', command=self.stmt_canvas.yview)
        self.stmt_canvas.grid(row=0, column=0, sticky='nsew', padx=(2, 4), pady=(2, 6))
        yscroll.grid(row=0, column=1, sticky='ns', padx=(0, 0), pady=(2, 6))

        self.stmt_list_frame = ttk.Frame(self.stmt_canvas)
        self.stmt_list_frame_id = self.stmt_canvas.create_window((0, 0), window=self.stmt_list_frame, anchor='nw')

        self.stmt_canvas.configure(yscrollcommand=yscroll.set)

        # Scrolling: auto-resize inner frame and auto-expand area vertically
        def _on_frame_resize(event):
            self.stmt_canvas.configure(scrollregion=self.stmt_canvas.bbox('all'))

        self.stmt_list_frame.bind('<Configure>', _on_frame_resize)

        def _on_canvas_configure(event):
            # Make the inner frame's width the same as the visible canvas width
            canvas_width = event.width
            self.stmt_canvas.itemconfig(self.stmt_list_frame_id, width=canvas_width)

        self.stmt_canvas.bind('<Configure>', _on_canvas_configure)

        # Button row under the statement list
        btn_row_frame = ttk.Frame(self.preview_frame)
        btn_row_frame.grid(row=1, column=0, sticky='w', padx=4, pady=(2, 4))
        self.load_where_fields_button = ttk.Button(
            btn_row_frame, text='Load Where Clause Fields', command=self.load_where_fields
        )
        self.load_where_fields_button.pack(side='left', padx=(0, 4))
        self.load_where_fields_button.config(state='disabled')
        # New: Select All/None button right next to it
        self.select_all_btn = ttk.Button(btn_row_frame, text='Select All')
        self.select_all_btn.pack(side='left')
        # Section 3 — API Operation and where inputs, simulate button
        simulate_frame = ttk.LabelFrame(self, text='3. API Operation and Simulation Inputs')
        simulate_frame.pack(fill='x', padx=8, pady=8)
        # Where-Clause Inputs label in section 3
        self.where_fields_label = ttk.Label(
            simulate_frame, text='Where-Clause Inputs: [None]', anchor='w', font=('TkDefaultFont', 9, 'bold')
        )
        self.where_fields_label.grid(row=0, column=0, columnspan=4, sticky='w', padx=(4, 0), pady=(0, 4))
        # Container for dynamic variable inputs
        self.where_inputs_frame = ttk.Frame(simulate_frame)
        self.where_inputs_frame.grid(row=1, column=0, columnspan=4, pady=(2, 8), sticky='ew')
        # API Operation selection
        ttk.Label(simulate_frame, text='API Operation:').grid(row=2, column=0, sticky='w')
        self.api_operation_combobox = ttk.Combobox(simulate_frame, textvariable=self.selected_api_operation, width=60)
        self.api_operation_combobox.grid(row=2, column=1, padx=2)
        self.simulate_button = ttk.Button(simulate_frame, text='Run Simulation', command=self.run_simulation)
        self.simulate_button.grid(row=2, column=2, padx=8)
        self.simulate_button.config(state='disabled')  # Disabled at startup

        self.simulate_trace_button = ttk.Button(
            simulate_frame, text='Run Simulation (Trace)', command=self.run_simulation_trace
        )
        self.simulate_trace_button.grid(row=2, column=3, padx=(4, 0))
        self.simulate_trace_button.config(state='disabled')  # Disabled at startup

        # Callback for strict activation of simulate buttons based on an actual valid selection
        def _maybe_enable_sim_buttons(event=None):
            """Enable simulation only if a valid API Operation is selected."""
            op = self.selected_api_operation.get()
            valid_ops = set(self._all_api_ops) if hasattr(self, '_all_api_ops') else set()
            if op in valid_ops:
                self.simulate_button.config(state='normal')
                self.simulate_trace_button.config(state='normal')
            else:
                self.simulate_button.config(state='disabled')
                self.simulate_trace_button.config(state='disabled')

        # Bind both typing and select events
        self.api_operation_combobox.bind(
            '<KeyRelease>', lambda e: (self._on_api_op_search(e), _maybe_enable_sim_buttons())
        )
        self.api_operation_combobox.bind(
            '<<ComboboxSelected>>', lambda e: (self._on_api_op_selected(e), _maybe_enable_sim_buttons())
        )
        self.selected_api_operation.trace_add('write', lambda *a: _maybe_enable_sim_buttons())
        self._maybe_enable_sim_buttons = _maybe_enable_sim_buttons

        # Label for API operation note (shown/hidden below combobox as relevant)
        self.api_op_note_var = tk.StringVar()
        self.api_op_note_label = ttk.Label(
            simulate_frame,
            textvariable=self.api_op_note_var,
            foreground='dark orange',
            wraplength=630,
            font=('TkDefaultFont', 9, 'italic'),
        )
        self.api_op_note_label.grid(row=3, column=0, columnspan=4, sticky='w', padx=(4, 2), pady=(2, 0))
        self.api_op_note_label.grid_remove()  # Hide initially

        # Section 4 — Results and trace
        results_frame = ttk.LabelFrame(self, text='4. Simulation Results')
        results_frame.pack(fill='both', expand=True, padx=8, pady=8)

        # Export button for simulation history as JSON
        def _export_simulation_history():
            import tkinter.filedialog

            fname = tkinter.filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
            if fname:
                try:
                    # Use the unmodified simulation_history
                    with open(fname, 'w', encoding='utf-8') as f:
                        import json

                        json.dump(self.simulation_engine.simulation_history, f, indent=2, ensure_ascii=False)
                except Exception as ex:
                    import tkinter.messagebox as mb

                    mb.showerror('Export Failed', f'Failed to export simulation history: {ex}')

        # Horizontal row for dropdown and export button
        trace_row = ttk.Frame(results_frame)
        trace_row.pack(fill='x', padx=2, pady=(3, 0))
        ttk.Label(trace_row, text='Simulation Trace History:').pack(side='left', padx=(0, 6))
        self.trace_history_var = tk.StringVar()
        self.trace_history_dropdown = ttk.Combobox(
            trace_row, textvariable=self.trace_history_var, state='readonly', width=60
        )
        self.trace_history_dropdown.pack(side='left', padx=(0, 8))
        self.trace_history_dropdown.bind('<<ComboboxSelected>>', self.on_trace_history_selected)
        export_btn = ttk.Button(trace_row, text='Export All Simulations to JSON', command=_export_simulation_history)
        export_btn.pack(side='left', padx=(0, 0), pady=(0, 0))
        self.results_text = tk.Text(results_frame, height=10, wrap='word')
        self.results_text.pack(fill='both', expand=True)

    def load_statements(self):  # noqa: C901
        # Called on "Load Simulation"

        # --- CLEAN STATE: Reset simulation fields, result area, and selections ---
        # 1. Clear API operation selection and combo
        self.selected_api_operation.set('')
        self.api_operation_combobox.set('')

        # 2. Clear results text area
        self.results_text.delete(1.0, tk.END)

        # 3. Clear where inputs and where-fields label
        self._clear_where_inputs()
        self.where_fields_label.configure(text='Where-Clause Inputs: [None]')

        # 4. Clear variable input widgets
        self.simulation_inputs = {}

        # 5. Clear checked_statements (will be re-populated)
        self.checked_statements = {}

        # 6. Reset trace history UI (do not delete history itself, just reset dropdown selection)
        self._update_trace_history_dropdown()
        self.trace_history_var.set('')
        self.trace_history_dropdown.set('')

        cpath = self.selected_compartment.get()
        ptype = self.selected_principal_type.get()
        pname_display = self.selected_principal.get()
        logger.info(f"Loading statements for Compartment '{cpath}', Principal '{pname_display}' ({ptype})")
        allow_stmts = []
        deny_stmts = []
        filters = {}
        if self.policy_repo and hasattr(self.policy_repo, 'filter_policy_statements'):
            if cpath:
                filters['effective_path'] = [cpath]
            exact_key = None
            model_key = None
            collection = None
            if ptype == 'group':
                exact_key = 'exact_groups'
                model_key = 'group_name'
                collection = self.policy_repo.groups if hasattr(self.policy_repo, 'groups') else []
            elif ptype == 'dynamic-group':
                exact_key = 'exact_dynamic_groups'
                model_key = 'dynamic_group_name'
                collection = self.policy_repo.dynamic_groups if hasattr(self.policy_repo, 'dynamic_groups') else []
            elif ptype == 'user':
                exact_key = 'exact_users'
                model_key = 'user_name'
                collection = self.policy_repo.users if hasattr(self.policy_repo, 'users') else []
            # Parse (domain, name) from display value
            if ptype == 'any-user':
                filters['subject'] = ['any-user']
            elif pname_display:
                if '/' in pname_display:
                    domain, name = pname_display.split('/', 1)
                else:
                    domain, name = None, pname_display
                obj = None
                if exact_key and model_key and collection:
                    for entry in collection:
                        if model_key in entry and entry[model_key] == name:
                            # Always check domain match (including None/"default")
                            if (domain is None and entry.get('domain_name') in [None, 'default']) or (
                                domain is not None and entry.get('domain_name') == domain
                            ):
                                obj = entry
                                break
                    if obj:
                        filters[exact_key] = [obj]
                    else:
                        filters['subject'] = [name]
                elif ptype == 'service':
                    filters['subject'] = [name]
                else:
                    filters['subject'] = [name]
            logger.info(f'Applying simulation filters to load statements: {filters}')
            stmts = self.policy_repo.filter_policy_statements(filters)
            allow_stmts = [s for s in stmts if s.get('action', '').lower() == 'allow']
            deny_stmts = [s for s in stmts if s.get('action', '').lower() == 'deny']

        # Remove old checkboxes in scroll area
        for item in self.stmt_list_frame.winfo_children():
            item.destroy()
        self.checked_statements = {}
        all_stmts = allow_stmts + deny_stmts
        # Update label to include policy count
        try:
            if hasattr(self, 'preview_frame') and self.preview_frame:
                self.preview_frame.config(text=f'2. Applicable Policies ({len(all_stmts)})')
        except Exception:
            pass

        # -- TABLE HEADERS: checkbox, statement text, conditional, where clause column --
        tk.Label(self.stmt_list_frame, text='', width=2).grid(row=0, column=0, sticky='nw')
        tk.Label(
            self.stmt_list_frame, text='Policy Path/Name', anchor='w', width=40, font=('TkDefaultFont', 10, 'bold')
        ).grid(row=0, column=1, sticky='nw', padx=1)
        tk.Label(
            self.stmt_list_frame,
            text='Policy Statement',
            anchor='w',
            width=90,
            wraplength=800,
            font=('TkDefaultFont', 10, 'bold'),
        ).grid(row=0, column=2, sticky='nw', padx=1)
        tk.Label(
            self.stmt_list_frame, text='Conditional', anchor='w', width=10, font=('TkDefaultFont', 10, 'bold')
        ).grid(row=0, column=3, sticky='nw', padx=(0, 2))

        # Select All/None button logic (label and command updated later)
        def get_all_checked():
            return all(var.get() for var, _ in self.checked_statements.values()) if self.checked_statements else False

        def update_select_all_btn_label():
            if get_all_checked():
                self.select_all_btn.config(text='Select None')
            else:
                self.select_all_btn.config(text='Select All')

        def toggle_select_all():
            check = not get_all_checked()
            for var, _ in self.checked_statements.values():
                var.set(check)
            update_select_all_btn_label()

        self.select_all_btn.config(command=toggle_select_all)
        # Initial label update will happen below

        for idx, st in enumerate(all_stmts, start=1):
            internal_id = st.get('internal_id', str(idx))
            check_var = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(self.stmt_list_frame, variable=check_var)
            cb.grid(row=idx, column=0, sticky='nw', padx=2)
            # Show policy path/name, narrow column
            policy_path = st.get('compartment_path', 'Unknown Path')
            policy_name = st.get('policy_name', 'Unnamed Policy')
            tk.Label(
                self.stmt_list_frame, text=f'{policy_path} / {policy_name}', anchor='w', width=40, justify='left'
            ).grid(row=idx, column=1, sticky='nw', padx=1)

            # Show full policy statement, wide column; wrap at about 1000px, try to match the actual pixel width visually
            full_txt = st.get('statement_text', '')
            tk.Label(self.stmt_list_frame, text=full_txt, anchor='w', width=90, wraplength=800, justify='left').grid(
                row=idx, column=2, sticky='nw', padx=1
            )
            # is_conditional = bool(st.get("conditions"))
            # tk.Label(self.stmt_list_frame, text=str(is_conditional), anchor="center", width=12).grid(row=idx, column=3, sticky="nw", padx=(0,2))
            # New: show Yes/No for where clause presence
            is_conditional = bool(st.get('conditions'))
            has_where = 'Yes' if is_conditional else 'No'
            tk.Label(self.stmt_list_frame, text=has_where, anchor='center', width=10).grid(
                row=idx, column=3, sticky='nw', padx=(0, 2)
            )
            self.checked_statements[internal_id] = (check_var, st)
        self.stmt_list_frame.update_idletasks()
        update_select_all_btn_label()
        # Attach listener to update the Select All/None button when a checkbox is toggled
        for var, _ in self.checked_statements.values():
            var.trace_add('write', lambda *args: update_select_all_btn_label())

        # New flow: Where clause fields are loaded only when button is pressed; always present, just enable/disable
        self._clear_where_inputs()
        self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
        self.load_where_fields_button.config(state='normal')
        self.simulate_button.config(state='disabled')
        # self.load_where_fields_button.config(state="disabled")  # Never disable. User should always be able to start another simulation.

        # === API Operation ComboBox: populate and filter ===
        opnames = []
        # Always use app.simulation_engine if available
        sim_engine = getattr(self.app, 'simulation_engine', None)
        logger.info(f'API Operation population: simulation_engine={sim_engine}')
        if sim_engine:
            opnames = sim_engine.get_api_operations('')
            logger.info(
                f"Got {len(opnames)} API Operations from simulation_engine: {opnames[:10]}{'...' if len(opnames) > 10 else ''}"
            )
        elif self.ref_data_repo and hasattr(self.ref_data_repo, 'data') and 'operations' in self.ref_data_repo.data:
            opnames = sorted(self.ref_data_repo.data['operations'].keys())
            logger.info(f'Fallback API ops: loaded {len(opnames)}')
        else:
            logger.info('API operation population: No valid source for opnames')
        self._all_api_ops = opnames
        self.api_operation_combobox['values'] = opnames
        self.api_operation_combobox.bind('<KeyRelease>', self._on_api_op_search)
        self.api_operation_combobox.bind('<<ComboboxSelected>>', self._on_api_op_selected)
        if not opnames:
            logger.warning('No API operations available for dropdown!')

    def _clear_where_inputs(self):
        # Remove dynamic where field widgets and clear input map
        for widget in self.where_inputs_frame.winfo_children():
            widget.destroy()
        self.simulation_inputs = {}

    def load_where_fields(self):
        # Only call this after statements are loaded and checkboxes set
        from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine

        all_var_names = set()
        for _, (check_var, st) in self.checked_statements.items():
            if not check_var.get():
                continue
            cond_str = st.get('conditions')
            if cond_str:
                try:
                    all_var_names.update(PolicySimulationEngine.extract_variable_names(cond_str))
                except Exception as e:
                    logger.info(f"Extracting variables failed for stmt: {st.get('statement_text')} / {e}")
        self._clear_where_inputs()
        sorted_vars = sorted(all_var_names)
        if sorted_vars:
            # Map of variable patterns to example text
            EXAMPLES = {
                'request.utc-timestamp': 'e.g. 2026-01-05T12:34:56Z',
                'request.utc-timestamp.time-of-day': 'e.g. 13:27:00Z',
            }
            for idx, var in enumerate(sorted_vars):
                ttk.Label(self.where_inputs_frame, text=var + ':', font=('TkDefaultFont', 10)).grid(
                    row=idx, column=0, padx=2, pady=1, sticky='e'
                )
                strvar = tk.StringVar()
                entry = ttk.Entry(self.where_inputs_frame, textvariable=strvar, width=35)
                entry.grid(row=idx, column=1, padx=2, pady=1, sticky='w')
                # Add example/hint if this is a known time/timestamp variable
                example_hint = ''
                # Use substring so alternate forms like 'request.utc-timestamp.time-of-day' match
                if var == 'request.utc-timestamp':
                    example_hint = EXAMPLES['request.utc-timestamp']
                elif var == 'request.utc-timestamp.time-of-day':
                    example_hint = EXAMPLES['request.utc-timestamp.time-of-day']
                if example_hint:
                    ttk.Label(
                        self.where_inputs_frame,
                        text=example_hint,
                        foreground='#666',
                        font=('TkDefaultFont', 9, 'italic'),
                    ).grid(row=idx, column=2, padx=(3, 2), sticky='w')
                self.simulation_inputs[var] = strvar
            self.where_fields_label.configure(text=f'Where-Clause Inputs: {sorted_vars}')
        else:
            self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
        # Once where fields are loaded, call button-enabling callback (respect API op selection logic)
        self._maybe_enable_sim_buttons()
        # self.load_where_fields_button.config(state="disabled")  # Never disable. User should always be able to start another simulation.
        logger.info(f'Where fields loaded from checked statements: {sorted_vars}')

    # API Operation search/filter
    def _on_api_op_search(self, event):
        val = self.api_operation_combobox.get()
        filtered = [op for op in getattr(self, '_all_api_ops', []) if val.lower() in op.lower()]
        self.api_operation_combobox['values'] = filtered if filtered else getattr(self, '_all_api_ops', [])

    def _on_api_op_selected(self, event=None):
        """
        When an API operation is selected, show the note below if one exists.
        """
        op_name = self.selected_api_operation.get()
        note = ''
        # Prefer sim_engine reference if available
        ref_repo = getattr(self, 'ref_data_repo', None)
        op_detail = None
        if ref_repo and hasattr(ref_repo, 'data'):
            if 'operations' in ref_repo.data:
                op_detail = ref_repo.data['operations'].get(op_name)
        if op_detail and isinstance(op_detail, dict):
            note = op_detail.get('note') or op_detail.get('Note') or ''
        self.api_op_note_var.set(note or '')
        if note:
            self.api_op_note_label.grid()  # Show label
        else:
            self.api_op_note_label.grid_remove()  # Hide if no note

    def _update_trace_history_dropdown(self):
        # Refresh the dropdown contents from simulation_engine
        traces = self.simulation_engine.get_simulation_trace_list()
        display_names = []
        self._trace_history_map = {}  # display_name -> index
        for idx, entry in enumerate(traces):
            # display: name (date)
            dn = f"{entry['name']} ({entry['timestamp']})"
            display_names.append(dn)
            self._trace_history_map[dn] = idx
        self.trace_history_dropdown['values'] = display_names
        if display_names:
            self.trace_history_var.set(display_names[-1])  # Select most recent by default

    def on_trace_history_selected(self, event=None):
        # Load the selected trace into the results area
        selected = self.trace_history_var.get()
        idx = self._trace_history_map.get(selected)
        if idx is not None:
            trace = self.simulation_engine.get_simulation_trace_by_index(idx)
            if trace:
                # Pretty print permissions/result (similar to after run_simulation)
                summary = []
                summary.append(f"Result: {'ALLOWED' if trace['api_call_allowed'] else 'DENIED'}")
                if trace['failure_reason']:
                    summary.append(f"Reason: {trace['failure_reason']}")
                summary.append(f"Permissions: {', '.join(trace.get('final_permission_set', [])) or '[none granted]'}")
                summary.append('Simulation JSON detail below:\n')
                pretty_json = json.dumps(trace, indent=2, ensure_ascii=False)
                self.results_text.delete(1.0, tk.END)
                self.results_text.insert(tk.END, '\n'.join(summary) + '\n' + pretty_json)

    def run_simulation(self):
        # Called on "Run Simulation" (basic, high-level details only)
        self._run_simulation_with_trace(trace_mode=False)

    def run_simulation_trace(self):
        # Called on "Run Simulation (Trace)" — detailed per-statement trace
        self._run_simulation_with_trace(trace_mode=True)

    @staticmethod
    def _normalize_timestring(value: str) -> str:
        """
        Tries to convert lower-case 't' and 'z' in ISO format to upper-case, only if string matches time pattern.
        Leaves value unchanged if not ISO timestamp-like.
        """
        import re

        # Match patterns like 'YYYY-MM-DDtHH:MM:SSz' or 'YYYY-MM-DDTHH:MM:SSZ'
        iso_dt_pattern = r'^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.\d+)?([Zz]|[+\-]\d{2}:?\d{2})?$'
        m = re.match(iso_dt_pattern, value)
        if m:
            date, time, tz = m.group(1), m.group(2), m.group(3)
            new_v = f'{date}T{time}'
            if tz:
                new_v += tz.upper() if tz.lower() == 'z' else tz
            return new_v
        return value

    def _run_simulation_with_trace(self, trace_mode):
        mode_label = 'TRACE' if trace_mode else 'BASIC'
        logger.info(f'Starting simulation [{mode_label}] with current selections')

        # Summarize key selections at INFO, only detail (statements) at DEBUG
        logger.info(
            f'Compartment: {self.selected_compartment.get()}, Principal: {self.selected_principal.get()} ({self.selected_principal_type.get()}), API Operation: {self.selected_api_operation.get()}'
        )
        logger.debug(
            f"Where Clause Inputs: {{ {', '.join(f'{k}: {v.get()}' for k, v in self.simulation_inputs.items())} }}"
        )
        checked_statement_ids = []
        for var, st in self.checked_statements.values():
            if var.get():
                logger.debug(f"Checked Statement: {st.get('statement_text')} (Internal ID: {st.get('internal_id')})")
                checked_statement_ids.append(st.get('internal_id'))
        self.results_text.delete(1.0, tk.END)

        cpath = self.selected_compartment.get()
        ptype = self.selected_principal_type.get()
        pname_display = self.selected_principal.get()
        api_operation = self.selected_api_operation.get()
        # Compose principal_key for engine
        if ptype == 'any-user':
            principal_key = 'any-user:None/any-user'
        elif '/' in pname_display:
            domain, name = pname_display.split('/', 1)
            principal_key = f'{ptype}:{domain}/{name}'
        else:
            principal_key = f'{ptype}:None/{pname_display}'
        # Normalize where-clause timestring entries
        where_context = {k: self._normalize_timestring(v.get()) for k, v in self.simulation_inputs.items()}

        # --- Improved: Include operation and principal for trace history name ---
        sim_trace_name = f'{api_operation} | {ptype}:{pname_display}' if api_operation and pname_display else None

        logger.info(f'Calling simulate_and_record on simulation_engine (trace_mode={trace_mode})')
        result = self.simulation_engine.simulate_and_record(
            principal_key,
            cpath,
            api_operation,
            where_context,
            checked_statement_ids,
            trace_name=sim_trace_name,
            trace=trace_mode,
        )

        # Display outcome
        summary = []
        summary.append(f"Result: {'ALLOWED' if result['api_call_allowed'] else 'DENIED'}")
        if result['failure_reason']:
            summary.append(f"Reason: {result['failure_reason']}")
        summary.append(f"Permissions: {', '.join(result.get('final_permission_set', [])) or '[none granted]'}")
        summary.append('Simulation JSON detail below:\n')
        pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
        # For trace-mode, also pretty-print trace details if available
        if trace_mode and 'trace_statements' in result:
            summary.append('\n=== TRACE DETAILS ===\n')
            for stmt in result['trace_statements']:
                summary.append(json.dumps(stmt, indent=2, ensure_ascii=False))
        self.results_text.insert(tk.END, '\n'.join(summary) + '\n' + pretty_json)
        logger.info(f"Simulation [{mode_label}] result: {result.get('result')}")
        # Update and select latest in trace history dropdown
        self._update_trace_history_dropdown()
        self.trace_history_dropdown.update_idletasks()

    def _reload_index_debug(self):
        pass  # Button removed; cleanup for backward compatibility if called
