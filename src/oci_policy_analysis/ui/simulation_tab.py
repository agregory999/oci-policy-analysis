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
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine
from oci_policy_analysis.ui.data_table import CheckboxTable

logger = get_logger(component='simulation_tab')


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
        """Initializes the SimulationTab UI component.

        Args:
            parent (tk.Widget): The parent Tkinter widget.
            app (object): Main application instance, expected to provide policy and simulation engine APIs.
            settings (object): Application settings object.

        """
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
        """Refreshes the dropdowns for compartment and principals.

        Populates members used by the compartment, principal type, and principal name comboboxes.
        Principal values are tuples (domain, name); 'any-user'/services will use (None, name).

        Returns:
            None
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
        # self.preview_frame.columnconfigure(0, weight=1)
        # self.preview_frame.rowconfigure(0, weight=1)

        self.statement_checkbox_table = None  # Will be created in load_statements
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
        """Loads and displays policy statements for the currently selected compartment and principal.

        Filters policy statements based on selection; populates the UI preview table and enables downstream simulation controls.

        Returns:
            None
        """
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

        # Remove old checklist/table if present
        if getattr(self, 'statement_checkbox_table', None) is not None:
            self.statement_checkbox_table.destroy()
            self.statement_checkbox_table = None
        all_stmts = allow_stmts + deny_stmts
        data = []
        for st in all_stmts:
            data.append(
                {
                    'Policy Path/Name': f"{st.get('compartment_path','Unknown Path')} / {st.get('policy_name','Unnamed Policy')}",
                    'Policy Statement': st.get('statement_text', ''),
                    'Conditional': 'Yes' if st.get('conditions') else 'No',
                    'obj': st,
                }
            )

        def on_action(checked_rows):
            checked_ids = [row['obj'].get('internal_id') for row in checked_rows if 'obj' in row]
            logger.info(f'Simulate Selected called for checked statement IDs: {checked_ids}')
            # Legacy: set checked_statements for the rest of code
            self.checked_statements = {}
            for row in data:
                obj = row.get('obj')
                idval = obj.get('internal_id') if obj else None
                if obj and idval is not None:
                    self.checked_statements[idval] = (tk.BooleanVar(value=row in checked_rows), obj)

        cols = ['Policy Path/Name', 'Policy Statement', 'Conditional']
        # Set table max height to about 30% typical default window (e.g. 260px), user can tune
        col_widths = {
            'Policy Path/Name': 220,
            'Policy Statement': 700,
            'Conditional': 90,
        }
        self.statement_checkbox_table = CheckboxTable(
            self.preview_frame,
            columns=cols,
            data=data,
            action_button_text='Load Where Clause Fields',
            action_callback=self.load_where_fields,
            enable_select_all=True,
            checked_by_default=True,
            max_height=260,  # px, approx 30% of default main window
            column_widths=col_widths,
            geometry_manager='pack',
        )
        self.statement_checkbox_table.pack(fill='both', expand=True, padx=4, pady=(8, 2))
        self._clear_where_inputs()
        self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
        self.simulate_button.config(state='disabled')
        # self.load_where_fields_button config/state logic removed—button now only exists in-table.

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

    def load_where_fields(self, checked_rows=None):  # noqa: C901
        """Extracts and displays dynamic where clause input fields based on the selected statements.

        Parses checked statements for required where-clause variables, then renders appropriate Tkinter fields for user input.

        Returns:
            None
        """

        # Get checked rows from the CheckboxTable widget
        if checked_rows is None:
            checked_rows = []
            if self.statement_checkbox_table is not None:
                checked_rows = self.statement_checkbox_table.get_checked_rows()
        logger.info(f'load_where_fields: Found {len(checked_rows)} checked row(s) from CheckboxTable.')

        # Update self.checked_statements for consistency (mapping from internal_id to row)
        self.checked_statements = {}
        for row in checked_rows:
            internal_id = (
                row.get('obj', {}).get('internal_id') if isinstance(row.get('obj'), dict) else row.get('internal_id')
            )
            obj = row.get('obj', row)
            if internal_id is not None:
                self.checked_statements[internal_id] = (tk.BooleanVar(value=True), obj)

        # Continue as before, but operate on these checked statement rows
        all_var_names = set()
        for row in checked_rows:
            # row may be a dict with key 'obj' (the statement), or the statement itself
            st = row.get('obj', row)
            logger.info(f'Load where fields: statement ID {st.get("internal_id")}')
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
        """Displays simulation results for the selected simulation trace entry.

        Args:
            event (tk.Event, optional): Optional Tkinter event object from dropdown selection.

        Returns:
            None
        """
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
        """Runs a policy simulation with the current selections (basic mode).

        Triggers the simulation engine and displays allow/deny result and final permission set.

        Returns:
            None
        """
        # Called on "Run Simulation" (basic, high-level details only)
        self._run_simulation_with_trace(trace_mode=False)

    def run_simulation_trace(self):
        """Runs a policy simulation with detailed tracing enabled.

        Shows statement-by-statement evaluation and trace debug output.

        Returns:
            None
        """
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

        logger.info(
            f'Calling simulate_and_record on simulation_engine (trace_mode={trace_mode}) with {len(checked_statement_ids)} statements'
        )
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
