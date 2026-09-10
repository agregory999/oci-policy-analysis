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

from oci_policy_analysis.application.core.engine import PolicySimulationEngine
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import CheckboxTable

# NOTE: ProspectiveEditorWindow is now the primary editor for prospective
# (what-if) policy statements. The inline editor embedded in this tab is
# deprecated and kept only as a non-interactive preview until it is fully
# removed.
from oci_policy_analysis.presentation.desktop.prospective_editor_window import ProspectiveEditorWindow

logger = get_logger(component='simulation_tab')


class SimulationTab(BaseUITab):
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
        super().__init__(
            parent,
            default_help_text=(
                'Simulate OCI policy enforcement in three stages: define the simulation environment, '
                'select applicable policy statements and where-clause variables, then run operations and review results.'
            ),
            page_help_link='/simulation.html',
        )
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

    # ------------------------------------------------------------------
    # Data population / tenancy-scoped initialization
    # ------------------------------------------------------------------

    def populate_data(self):
        """Populate Simulation tab data once a tenancy is loaded.

        This is invoked from App._post_load_update_ui, after
        policy_compartment_analysis has a concrete tenancy_ocid. At
        this point we can safely hydrate the simulation engine's
        prospective (what-if) statements from settings for the active
        tenancy.
        """

        # Ensure the simulation engine has the latest prospective
        # statements for the active tenancy via the shared
        # ProspectiveStatementsService, if available. This centralizes
        # prospective CRUD/persistence at the tenancy level instead of
        # having SimulationTab own it directly.
        prospective_service = getattr(self.app, 'prospective_service', None)
        if prospective_service is not None:
            try:
                engine = getattr(self, 'simulation_engine', None)
                if engine is not None and hasattr(engine, 'set_prospective_statements'):
                    engine.set_prospective_statements(prospective_service.to_simple_list())
            except Exception as ex:  # defensive; do not break UI if settings malformed
                logger.warning(
                    'SimulationTab.populate_data: failed to propagate prospective statements via service: %s',
                    ex,
                    exc_info=True,
                )

        # Refresh dropdowns after any prospective/tenancy changes
        self.refresh_dropdowns()

        # Rebuild the inline prospective preview contents using the
        # latest compartments list and hydrated prospective statements.
        # The outer LabelFrame (self.prospective_container) is created
        # once in _build_layout; here we only clear and repopulate its
        # children.
        try:
            for child in self.prospective_container.winfo_children():
                child.destroy()
        except Exception:
            logger.debug('SimulationTab.populate_data: unable to clear prospective_container children', exc_info=True)

        self._build_inline_prospective_preview(self.prospective_container)

    def refresh_dropdowns(self):  # noqa: C901
        """Refreshes the dropdowns for compartment and principals.

        - If users are not loaded, will hide/remove "user" as a principal type.
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
        # Only include "user" if users exist
        users_loaded = bool(getattr(self.policy_repo, 'users', []))
        if users_loaded:
            principal_types.add('user')
        else:
            if 'user' in principal_types:
                principal_types.discard('user')
        if not compartments:
            compartments = {'ROOT'}
        self._sim_index_compartments = sorted(compartments)
        # Build _sim_index_principals['user'] from repo.users if available and requested
        if hasattr(self.policy_repo, 'users') and users_loaded:
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
        try:
            self.compartment_combobox['values'] = self._sim_index_compartments
            self.principal_type_combobox['values'] = sorted(principal_types)
        except Exception as ex:
            logger.info(f'refresh_dropdowns: unable to update combos ({ex})')
        # If current type is "user" but no users, reset to "any-user" instead
        if not users_loaded and self.selected_principal_type.get() == 'user':
            self.selected_principal_type.set('any-user')
        if self.selected_compartment.get() not in self._sim_index_compartments:
            self.selected_compartment.set(next(iter(self._sim_index_compartments), 'ROOT'))
        if self.selected_principal_type.get() not in principal_types:
            self.selected_principal_type.set(next(iter(principal_types), 'any-user'))
        self._update_principal_list()
        if hasattr(self.app, 'sim_debugger_tab') and getattr(self.app, 'sim_debugger_tab', None):
            debug_index = {k: [f'{d}/{n}' if d else n for (d, n) in v] for k, v in self._sim_index_principals.items()}
            self.app.sim_debugger_tab.show_index(self._sim_index_compartments, debug_index)

        # Environment summary should reflect the latest dropdown values
        self._on_environment_changed(reason='refresh_dropdowns')

    def on_load_all_users_setting_changed(self, enabled: bool):
        """Called if settings change for Load All Users to refresh simulation principal types and UI."""
        self.refresh_dropdowns()

    def _update_principal_list(self, *_):  # noqa: C901
        pt = self.selected_principal_type.get()
        if pt in ('user', 'group', 'dynamic-group') and hasattr(self.policy_repo, f'{pt}s'):
            # Unified logic for user/group/dynamic-group to display as domain/name
            principals = []
            # Get attribute, e.g. self.policy_repo.groups for 'group', users for 'user'
            coll = getattr(self.policy_repo, f'{pt}s', [])
            domain_key = 'domain_name'
            name_key = (
                'user_name'
                if pt == 'user'
                else 'group_name'
                if pt == 'group'
                else 'dynamic_group_name'
                if pt == 'dynamic-group'
                else None
            )
            for entry in coll:
                domain = entry.get(domain_key)
                if domain == 'default':
                    domain = None
                name = entry.get(name_key)
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
            self.principal_combobox.config(state='readonly')
            # try:
            #     self.principal_combobox.configure(background='#f0f0f0')  # standard ttk disabled background
            # except Exception:
            #     pass
            self.selected_principal.set('')
        else:
            self.principal_combobox.config(state='normal')
            # try:
            #     self.principal_combobox.configure(background='white')
            # except Exception:
            #     pass
            if display_principals and self.selected_principal.get() not in display_principals:
                self.selected_principal.set(display_principals[0])
            elif not display_principals:
                self.selected_principal.set('')

    def _init_state(self):
        # Shared state across subtabs
        self.selected_compartment = tk.StringVar()
        self.selected_principal_type = tk.StringVar()
        self.selected_principal = tk.StringVar()
        self.selected_api_operation = tk.StringVar()
        self.show_trace_details_var = tk.BooleanVar(value=False)
        self.simulation_inputs: dict[str, tk.StringVar] = {}
        self.loaded_statements = []
        self.required_where_fields: set[str] = set()
        # Cache of the last simulation or history trace result dict so we can
        # re-render the results panel when the "Show trace details" checkbox
        # is toggled without having to recompute anything.
        self.simulation_results = None
        # Internal bookkeeping for subtab interactions
        self._statements_need_reload = True
        self.statement_checkbox_table = None
        self.checked_statements = {}

    def _get_simulation_engine(self):
        """Return the active simulation engine from the app when available.

        MainApp may replace ``app.simulation_engine`` during tenancy reload.
        This helper prevents SimulationTab from holding a stale engine
        instance captured at construction time.
        """

        app_engine = getattr(self.app, 'simulation_engine', None)
        current = getattr(self, 'simulation_engine', None)
        if app_engine is not None and app_engine is not current:
            self.simulation_engine = app_engine
            logger.info('SimulationTab: refreshed simulation_engine reference from app.')
            return app_engine
        return app_engine or current

    def _build_layout(self):
        """Build the 3-subtab layout for Simulation.

        Subtabs:
          1) Simulation Environment
          2) Statements and Context
          3) Simulation History
        """

        # Notebook containing the three logical subtabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)

        self.env_frame = ttk.Frame(self.notebook)
        self.statements_frame = ttk.Frame(self.notebook)
        self.history_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.env_frame, text='Simulation Environment')
        self.notebook.add(self.statements_frame, text='Statements and Context')
        self.notebook.add(self.history_frame, text='Simulation History')

        # Track tab changes so we can lazily load statements when the
        # user first navigates to the Statements and Context subtab.
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # --- Subtab 1: Simulation Environment ---
        select_frame = ttk.LabelFrame(self.env_frame, text='Principal and Effective Path Selection')
        select_frame.pack(fill='x', padx=8, pady=8)
        self.add_context_help(
            select_frame,
            (
                'Step 1: Select the compartment and principal (user, group, dynamic group, or service) for the simulation. '
                'Use the dropdowns for compartment, principal type, and principal name. '
                "Then click 'Load Simulation' to preview relevant policies."
            ),
        )
        # Row 0: Principal Type + Principal (give them more vertical space)
        ttk.Label(select_frame, text='Principal Type:').grid(row=0, column=0, sticky='w', pady=(2, 2))
        self.principal_type_combobox = ttk.Combobox(
            select_frame, textvariable=self.selected_principal_type, width=20, state='normal'
        )
        self.principal_type_combobox.grid(row=0, column=1, padx=2, pady=(2, 2), sticky='w')
        self.principal_type_combobox.bind('<<ComboboxSelected>>', self._on_principal_type_changed)
        self.add_context_help(self.principal_type_combobox, 'Select the type of principal (user, group, service, etc).')
        ttk.Label(select_frame, text='Principal:').grid(row=0, column=2, sticky='w', pady=(2, 2))
        self.principal_combobox = ttk.Combobox(
            select_frame, textvariable=self.selected_principal, width=40, state='normal'
        )
        self.principal_combobox.grid(row=0, column=3, padx=2, pady=(2, 2), sticky='w')
        self.add_context_help(self.principal_combobox, 'Select the identity (user/group name) for simulation.')
        # Any principal change should refresh the environment summary and
        # mark statements as needing reload.
        self.principal_combobox.bind('<<ComboboxSelected>>', lambda *_: self._on_environment_changed('principal'))

        # Row 1: Effective Path on its own line, with a note about sub-compartments
        ttk.Label(select_frame, text='Effective Path:').grid(row=1, column=0, sticky='w', pady=(2, 2))
        self.compartment_combobox = ttk.Combobox(select_frame, textvariable=self.selected_compartment, width=50)
        self.compartment_combobox.grid(row=1, column=1, padx=2, pady=(2, 2), sticky='w')
        self.add_context_help(
            self.compartment_combobox,
            'Choose the effective path (compartment scope) for the simulation context. '
            'Effective paths reflect how OCI actually applies the statement after resolving location.',
        )
        # Effective path changes also reset environment/summary.
        self.compartment_combobox.bind('<<ComboboxSelected>>', lambda *_: self._on_environment_changed('compartment'))
        ttk.Label(
            select_frame,
            text='Note: statements in sub-compartments of this path may also be in scope.',
            foreground='#555',
        ).grid(row=1, column=2, columnspan=2, sticky='w', padx=(4, 0), pady=(2, 2))
        # NOTE: we no longer have an explicit "Load Simulation" button.
        # Any change to the environment will mark statements/history as
        # needing reload via _on_environment_changed.

        self.prospective_container = ttk.LabelFrame(
            self.env_frame,
            text='Prospective (What-If) Policy Statements',
        )
        self.prospective_container.pack(fill='x', padx=8, pady=(4, 8))
        # Build an initial read-only prospective preview. This will be
        # refreshed on tenancy load and whenever the environment
        # changes, but all editing happens in ProspectiveEditorWindow.
        self._build_inline_prospective_preview(self.prospective_container)

        # Environment Summary + explicit navigation to Statements & Context
        summary_frame = ttk.LabelFrame(self.env_frame, text='Environment Summary')
        summary_frame.pack(fill='x', padx=8, pady=(0, 8))
        # Use a multi-line summary so we can show principal, path, and a
        # quick preview of which prospective statements are currently in
        # scope for the selected environment.
        self.environment_summary_label = ttk.Label(
            summary_frame,
            text='No environment selected yet.',
            foreground='#555',
            justify='left',
            wraplength=700,
        )
        self.environment_summary_label.pack(side='left', fill='x', expand=True, padx=(4, 4), pady=(4, 4))

        def _go_to_statements_and_load():
            # Ensure statements are loaded for the current environment
            self.load_statements()
            self._statements_need_reload = False
            # Switch to Statements & Context tab
            try:
                self.notebook.select(self.statements_frame)
            except Exception:
                logger.debug(
                    'SimulationTab: unable to switch to Statements tab from Environment Summary', exc_info=True
                )

        goto_btn = ttk.Button(
            summary_frame,
            text='Confirm and Select Statements for Simulation',
            command=_go_to_statements_and_load,
        )
        goto_btn.pack(side='right', padx=(4, 4), pady=(4, 4))

        # --- Subtab 2: Statements and Context ---
        self.preview_frame = ttk.LabelFrame(self.statements_frame, text='Applicable Policy Statements')
        self.preview_frame.pack(fill='both', padx=8, pady=8, expand=True)
        self.add_context_help(
            self.preview_frame,
            (
                'Step 2: See all policies that apply to the selected context. '
                'You may select (check/uncheck) those that should be used for the simulation. '
                'Load where-clause variables from checked policies.'
            ),
        )
        # self.preview_frame.columnconfigure(0, weight=1)
        # self.preview_frame.rowconfigure(0, weight=1)

        # Will be created lazily when statements are loaded for the current environment
        self.statement_checkbox_table = None

        # API Operation and where inputs, simulate button
        simulate_frame = ttk.LabelFrame(self.statements_frame, text='API Operation and Simulation Inputs')
        simulate_frame.pack(fill='x', padx=8, pady=8)
        self.add_context_help(
            simulate_frame,
            (
                'Step 3: Choose the API operation to simulate and enter values for any required variables. '
                'You may add/edit where-clause inputs below if needed. Click a simulation button to analyze.'
            ),
        )
        # Where-Clause Inputs label in section 3
        self.where_fields_label = ttk.Label(
            simulate_frame, text='Where-Clause Inputs: [None]', anchor='w', font=('TkDefaultFont', 9, 'bold')
        )
        self.where_fields_label.grid(row=0, column=0, columnspan=4, sticky='w', padx=(4, 0), pady=(0, 4))
        self.add_context_help(
            self.where_fields_label, 'Variables required by where clauses. Enter values before simulating.'
        )
        # Container for dynamic variable inputs
        self.where_inputs_frame = ttk.Frame(simulate_frame)
        self.where_inputs_frame.grid(row=1, column=0, columnspan=4, pady=(2, 8), sticky='ew')
        # API Operation selection
        ttk.Label(simulate_frame, text='API Operation:').grid(row=2, column=0, sticky='w')
        self.api_operation_combobox = ttk.Combobox(simulate_frame, textvariable=self.selected_api_operation, width=60)
        self.api_operation_combobox.grid(row=2, column=1, padx=2)
        self.add_context_help(self.api_operation_combobox, 'Pick the target OCI API call to simulate.')
        self.simulate_button = ttk.Button(simulate_frame, text='Run Simulation', command=self.run_simulation)
        self.simulate_button.grid(row=2, column=2, padx=8)
        self.simulate_button.config(state='disabled')  # Disabled at startup
        self.add_context_help(self.simulate_button, 'Run simulation using selected context, operation, and variables.')

        # (Show trace toggle has been moved to the Results section.)

        # Callback for strict activation of simulate buttons based on an actual valid selection
        def _maybe_enable_sim_buttons(event=None):
            """Enable simulation only if a valid API Operation is selected."""
            op = self.selected_api_operation.get()
            valid_ops = set(self._all_api_ops) if hasattr(self, '_all_api_ops') else set()
            if op in valid_ops:
                self.simulate_button.config(state='normal')
            else:
                self.simulate_button.config(state='disabled')

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

        # --- Subtab 3: Results and trace / Simulation History ---
        results_frame = ttk.LabelFrame(self.history_frame, text='Simulation Results')
        results_frame.pack(fill='both', expand=True, padx=8, pady=8)
        self.add_context_help(
            results_frame,
            (
                'Step 4: View simulation output and the full trace for policy evaluation. '
                'Choose from history, export results, or inspect full allow/deny rationale.'
            ),
        )

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
        self.add_context_help(
            self.trace_history_dropdown, 'Select a previous simulation run to view its results and trace.'
        )
        export_btn = ttk.Button(trace_row, text='Export All Simulations to JSON', command=_export_simulation_history)
        export_btn.pack(side='left', padx=(0, 0), pady=(0, 0))
        self.add_context_help(export_btn, 'Export all prior simulation results to a JSON file.')

        # Move "Show trace details" checkbox into the Results section so it
        # clearly controls how much detail is rendered in the results area,
        # independent of how simulations are triggered.
        trace_toggle_row = ttk.Frame(results_frame)
        trace_toggle_row.pack(fill='x', padx=2, pady=(3, 0))
        self.show_trace_checkbox = ttk.Checkbutton(
            trace_toggle_row,
            text='Show trace details (JSON and per-statement trace)',
            variable=self.show_trace_details_var,
            command=self._refresh_results_display_if_needed,
        )
        self.show_trace_checkbox.pack(side='left', padx=(0, 0))
        self.add_context_help(
            self.show_trace_checkbox,
            'When checked, include full JSON and per-statement trace details in the Simulation Results.',
        )
        self.results_text = tk.Text(results_frame, height=10, wrap='word')
        # Use standard y-scrollbar so long simulation traces can be scrolled.
        results_scroll = ttk.Scrollbar(results_frame, orient='vertical', command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.pack(side='left', fill='both', expand=True)
        results_scroll.pack(side='right', fill='y')
        self.add_context_help(
            self.results_text, 'Simulation summary and full policy trace details. See allow/deny and permissions here.'
        )

    def _refresh_results_display_if_needed(self):
        """Re-render the results panel when the Show Trace toggle changes.

        If we have a cached simulation result (either from the most recent
        run or from history), re-apply the same rendering logic used in
        _run_simulation_with_trace/on_trace_history_selected so the user can
        toggle trace details on/off without rerunning the simulation.
        """
        result = getattr(self, 'simulation_results', None)
        if not result:
            return

        # Detect whether this cached result came from a history entry (it
        # will have api_call_allowed at the top level) or directly from
        # simulate_and_record. In both cases we standardize on the same
        # rendering format used elsewhere.
        api_allowed = bool(result.get('api_call_allowed'))
        lines: list[str] = []
        lines.append(f"Result: {'ALLOWED' if api_allowed else 'DENIED'}")
        failure_reason = result.get('failure_reason') or ''
        if failure_reason:
            lines.append(f'Reason: {failure_reason}')

        required = result.get('required_permissions_for_api_operation') or []
        missing = result.get('missing_permissions') or []
        lines.append(f"Required permissions for API: {', '.join(required) if required else '[none]'}")
        if missing:
            lines.append(f"Missing permissions: {', '.join(missing)}")

        # Always show how many allow/deny statements were considered so
        # users can see inclusion at a glance, even without full trace.
        allow_ct = result.get('allow_statements_considered')
        deny_ct = result.get('deny_statements_considered')
        if allow_ct is not None or deny_ct is not None:
            lines.append(
                f'Statements considered: ALLOW={allow_ct if allow_ct is not None else 0}, '
                f'DENY={deny_ct if deny_ct is not None else 0}'
            )

        # Brief where-context echo for quick sanity checks.
        where_ctx = result.get('simulation_trace', {}).get('simulation_context', {}).get('where_context') or {}
        if where_ctx:
            pretty_where = json.dumps(where_ctx, indent=2, ensure_ascii=False)
            lines.append('Where context:')
            lines.append(pretty_where)

        sim_trace = result.get('simulation_trace') or {}
        final_permissions = sim_trace.get('final_permission_set') or []
        if self.show_trace_details_var.get():
            lines.append(f"Final permission set: {', '.join(final_permissions) or '[none granted]'}")
            lines.append('Simulation JSON detail below:\n')
            pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
            lines.append(pretty_json)

        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, '\n'.join(lines))

    def apply_settings(self, context_help: bool, font_size: str):
        """Apply main settings for context help and font size."""
        super().apply_settings(context_help, font_size)

    # ------------------------------------------------------------------
    # Environment / subtab helpers
    # ------------------------------------------------------------------

    def _on_tab_changed(self, event=None):
        """Handle notebook tab changes.

        When the user navigates to the Statements and Context subtab and
        the environment has been marked as changed, automatically load the
        applicable statements for the current environment.
        """

        try:
            current = self.notebook.select()
        except Exception:
            return

        if current == str(self.statements_frame) and self._statements_need_reload:
            logger.info('SimulationTab: tab changed to Statements; reloading applicable statements.')
            self.load_statements()
            self._statements_need_reload = False

    def _on_environment_changed(self, reason: str = '') -> None:
        """Called when effective path/principal/prospective list changes.

        Resets dependent UI state so that the Statements and Context tab
        will be reloaded on next visit. We intentionally do not wipe the
        underlying engine history, only the UI selection state.
        """

        logger.info('SimulationTab: environment changed (%s); resetting statements/context state', reason)

        # Clear statements table
        if self.statement_checkbox_table is not None:
            try:
                self.statement_checkbox_table.destroy()
            except Exception:
                logger.debug('SimulationTab: failed to destroy old statement_checkbox_table', exc_info=True)
            self.statement_checkbox_table = None

        # Clear selections and where-context inputs
        self.checked_statements = {}
        self._clear_where_inputs()
        self.where_fields_label.configure(text='Where-Clause Inputs: [None]')

        # Clear API op selection (but keep list of ops intact)
        self.selected_api_operation.set('')
        try:
            self.api_operation_combobox.set('')
        except Exception:
            pass

        # Clear current history dropdown selection (do not erase history list)
        if hasattr(self, 'trace_history_var'):
            self.trace_history_var.set('')
        if hasattr(self, 'trace_history_dropdown'):
            try:
                self.trace_history_dropdown.set('')
            except Exception:
                pass

        self._statements_need_reload = True

        # Update Environment Summary label with a richer, multi-line
        # description of the current selections, including a preview of
        # any prospective (what-if) statements that would apply to this
        # environment. This keeps the Environment subtab self-contained
        # without requiring a full statements reload.
        if hasattr(self, 'environment_summary_label'):
            self._refresh_environment_summary()

    def _refresh_environment_summary(self) -> None:  # noqa: C901
        """Render a multi-line environment summary in the Environment subtab.

        The summary shows:

          * Selected effective path
          * Principal type and name
          * A brief note about when statements are loaded
          * A list of any *prospective* policy statements that are in-scope
            for the current environment (same matching semantics as
            get_applicable_statements).

        We intentionally keep this lightweight by only scanning the
        simulation engine's in-memory prospective set and not querying
        the full tenancy repository here.
        """

        lbl = getattr(self, 'environment_summary_label', None)
        if lbl is None:
            return

        cpath = self.selected_compartment.get() or 'ROOT'
        ptype = self.selected_principal_type.get() or '[principal type]'
        pname = self.selected_principal.get() or '[principal]'

        # Base summary lines
        lines: list[str] = []
        lines.append(f'Effective path: {cpath}')
        lines.append(f'Principal: {ptype} → {pname}')
        lines.append('Statements will be (re)loaded when you confirm and move to the "Statements and Context" tab.')

        # Keep prospective service/engine in sync before rendering summary.
        service = getattr(self.app, 'prospective_service', None)
        if service is not None:
            try:
                engine = getattr(self, 'simulation_engine', None)
                if engine is not None and hasattr(engine, 'set_prospective_statements'):
                    engine.set_prospective_statements(service.to_simple_list())
                logger.info(
                    'Environment summary sync: prospective_service records=%d pulled into engine',
                    len(service.list_all()),
                )
            except Exception:
                logger.warning('Environment summary sync: service->engine pull failed', exc_info=True)

        # Append a short prospective statement preview, if available.
        engine = self._get_simulation_engine()
        prospective_lines: list[str] = []
        try:
            if engine and hasattr(engine, 'get_prospective_statements'):
                all_prospective = engine.get_prospective_statements() or []
                # Normalize principal the same way as statement loading so
                # preview matching stays consistent with the engine.
                pname_display = self.selected_principal.get() or ''
                effective_principal = self._build_engine_principal_value(ptype, pname_display)

                # Reuse engine helpers to keep matching semantics identical
                principal_key = engine._normalize_principal_key(ptype, effective_principal)  # type: ignore[attr-defined]
                subj_filter = engine._principal_key_to_policy_search_filter(principal_key)  # type: ignore[attr-defined]
                any_subjects = {str(s).lower() for s in subj_filter.get('subject', []) if s}
                logger.info(
                    'Environment summary prospective check: principal_key=%s effective_path=%s total_prospective=%d',
                    principal_key,
                    cpath,
                    len(all_prospective),
                )

                def _prospective_matches_env(pst: dict) -> bool:  # noqa: C901
                    # Scope by compartment path
                    pst_comp = str(pst.get('compartment_path', '')).strip()
                    if not pst_comp:
                        return False
                    if not (cpath == pst_comp or cpath.startswith(pst_comp + '/')):
                        return False

                    # Match by subject/principal using the same logic as
                    # simulation_engine.get_applicable_statements
                    ptype_local = (
                        pst.get('subject_type') or pst.get('normalized', {}).get('subject_type') or ''
                    ).lower()
                    subjects = pst.get('subject') or pst.get('normalized', {}).get('subject') or []
                    # String subjects (any-user/any-group/service)
                    if any_subjects:
                        for s in subjects:
                            if isinstance(s, str) and s.strip().lower() in any_subjects:
                                return True
                    # Exact object subjects (user/group/dynamic-group)
                    if ptype_local == 'user' and 'exact_users' in subj_filter:
                        targets = subj_filter['exact_users']
                    elif ptype_local == 'group' and 'exact_groups' in subj_filter:
                        targets = subj_filter['exact_groups']
                    elif ptype_local == 'dynamic-group' and 'exact_dynamic_groups' in subj_filter:
                        targets = subj_filter['exact_dynamic_groups']
                    else:
                        targets = []

                    if not targets:
                        return False

                    norm_subj: set[tuple[str | None, str]] = set()
                    for s in subjects:
                        if isinstance(s, (tuple | list)) and len(s) == 2:
                            domain, name = s
                            dom_norm = str(domain).lower() if domain else 'default'
                            norm_subj.add((dom_norm, str(name).lower()))

                    for t in targets:
                        dom = str(t.get('domain_name') or 'default').lower()
                        name = str(
                            t.get('user_name') or t.get('group_name') or t.get('dynamic_group_name') or ''
                        ).lower()
                        if (dom, name) in norm_subj:
                            return True
                    return False

                matching = [
                    pst
                    for pst in all_prospective
                    if pst.get('parsed') and pst.get('valid') and _prospective_matches_env(pst)
                ]

                logger.info(
                    'Environment summary prospective matches: %d matched (ids=%s)',
                    len(matching),
                    [pst.get('internal_id') for pst in matching],
                )

                if matching:
                    prospective_lines.append('Prospective statements in scope for this environment:')
                    # Keep this compact; show up to 5 entries with policy name and path
                    for pst in matching[:5]:
                        name = pst.get('policy_name') or pst.get('description') or pst.get('statement_text')
                        comp = pst.get('compartment_path', 'ROOT')
                        prefix = '[Prospective]'
                        prospective_lines.append(f'  • {prefix} {name} @ {comp}')
                    if len(matching) > 5:
                        prospective_lines.append(f'  … (+{len(matching) - 5} more prospective statements)')
                else:
                    prospective_lines.append('No prospective (what-if) statements currently match this environment.')
        except Exception:
            # Defensive: never break the UI if summary rendering fails.
            prospective_lines = []

        if prospective_lines:
            lines.append('')  # blank separator line
            lines.extend(prospective_lines)

        lbl.configure(text='\n'.join(lines))

    def _on_principal_type_changed(self, *_):
        """Handle changes to principal type from the Environment subtab."""

        self._update_principal_list()
        self._on_environment_changed(reason='principal_type')

    @staticmethod
    def _build_engine_principal_value(principal_type: str, principal_display: str) -> object:
        """Build the principal payload expected by PolicySimulationEngine helpers.

        For string-subject principal types (any-user/any-group/service), the
        engine expects a plain string value and **not** a (domain, name) tuple.
        For identity principals (user/group/dynamic-group), the engine expects
        a (domain, name) tuple when available.
        """

        ptype = (principal_type or '').strip()
        display = (principal_display or '').strip()

        if ptype in ('any-user', 'any-group', 'service'):
            return display or ptype

        if '/' in display:
            domain, name = display.split('/', 1)
            return (domain if domain != '' else None, name)

        if display:
            return (None, display)

        return ''

    def _build_inline_prospective_preview(self, parent: tk.Widget) -> None:
        """Read-only prospective statement preview in the Environment subtab.

        All editing is handled by ProspectiveEditorWindow/prospective_service.
        This helper only renders a summary list for the current tenancy and
        provides a button to open the dedicated editor.
        """

        # Intro / help text
        intro = (
            'Prospective (what-if) policy statements are evaluated alongside real '
            'tenancy policies during simulation. Use the Prospective Editor to add '
            'or modify these statements. This section shows the current saved set '
            'for the active tenancy.'
        )
        ttk.Label(parent, text=intro, wraplength=700, justify='left').grid(
            row=0, column=0, columnspan=2, sticky='w', padx=4, pady=(4, 4)
        )

        # Container for the read-only list
        list_frame = ttk.Frame(parent)
        list_frame.grid(row=1, column=0, sticky='nsew', padx=4, pady=(0, 4))
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        # Simple 3-column layout: Compartment, Description, Statement
        header = ttk.Frame(list_frame)
        header.pack(fill='x')
        ttk.Label(header, text='Compartment', width=30).grid(row=0, column=0, sticky='w', padx=2)
        ttk.Label(header, text='Description', width=35).grid(row=0, column=1, sticky='w', padx=2)
        ttk.Label(header, text='Statement', width=60).grid(row=0, column=2, sticky='w', padx=2)

        body = ttk.Frame(list_frame)
        body.pack(fill='both', expand=True, pady=(2, 0))

        # Fetch prospective statements from the tenancy-scoped service when
        # available; otherwise fall back to the engine's in-memory list.
        items: list[dict] = []
        service = getattr(self.app, 'prospective_service', None)
        engine = self._get_simulation_engine()
        try:
            if service is not None:
                items = [
                    {
                        'compartment_path': r.compartment_path,
                        'description': r.description,
                        'statement_text': r.statement_text,
                    }
                    for r in service.list_all()
                ]
            elif engine is not None and hasattr(engine, 'get_prospective_statements'):
                items = engine.get_prospective_statements() or []
        except Exception:
            logger.warning('SimulationTab: unable to load prospective statements for preview', exc_info=True)
            items = []

        if not items:
            ttk.Label(
                body,
                text='No prospective (what-if) policy statements are currently defined for this tenancy.',
                foreground='#555',
                justify='left',
                wraplength=700,
            ).grid(row=0, column=0, columnspan=3, sticky='w', padx=2, pady=(2, 4))
        else:
            for idx, pst in enumerate(items):
                comp = pst.get('compartment_path') or 'ROOT'
                desc = pst.get('description') or ''
                stmt = pst.get('statement_text') or ''

                ttk.Label(body, text=comp, width=30).grid(row=idx, column=0, sticky='w', padx=2, pady=1)
                ttk.Label(body, text=desc, width=35).grid(row=idx, column=1, sticky='w', padx=2, pady=1)
                ttk.Label(body, text=stmt, wraplength=600, justify='left').grid(
                    row=idx, column=2, sticky='w', padx=2, pady=1
                )

        # Footer with a single button to open the dedicated editor
        footer = ttk.Frame(parent)
        footer.grid(row=2, column=0, sticky='ew', padx=4, pady=(2, 6))
        footer.columnconfigure(0, weight=1)
        ttk.Button(
            footer,
            text='Manage Prospective Statements…',
            command=lambda: ProspectiveEditorWindow(self, self.app),
        ).grid(row=0, column=0, sticky='e')

    def load_statements(self):  # noqa: C901
        """Loads and displays policy statements for the currently selected compartment and principal.

        Filters policy statements based on selection; populates the UI preview table and enables downstream simulation controls.

        Returns:
            None
        """

        # CLEAN STATE for statements/context (results/history are left intact;
        # environment changes should call _on_environment_changed explicitly).
        self.selected_api_operation.set('')
        try:
            self.api_operation_combobox.set('')
        except Exception:
            pass

        self._clear_where_inputs()
        self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
        self.simulation_inputs = {}
        self.checked_statements = {}

        cpath = self.selected_compartment.get()
        ptype = self.selected_principal_type.get()
        pname_display = self.selected_principal.get()
        logger.info(f"Loading statements for Compartment '{cpath}', Principal '{pname_display}' ({ptype})")
        # Canonical principal normalization, for all types
        sim_engine = self._get_simulation_engine()
        all_stmts = []
        if sim_engine:
            # Ensure tenancy-scoped prospective statements are pushed into
            # the engine right before context matching.
            service = getattr(self.app, 'prospective_service', None)
            if service is not None:
                try:
                    engine = self._get_simulation_engine()
                    if engine is not None and hasattr(engine, 'set_prospective_statements'):
                        engine.set_prospective_statements(service.to_simple_list())
                    logger.info(
                        'load_statements sync: prospective_service records=%d pulled into engine',
                        len(service.list_all()),
                    )
                except Exception:
                    logger.warning('load_statements sync: service->engine pull failed', exc_info=True)

            # Normalize principal into the exact shape expected by the engine.
            effective_principal = self._build_engine_principal_value(ptype, pname_display)
            # principal is either string for any-user/service, or (domain, name) tuple/user/group
            _principal_key, stmts = sim_engine.get_statements_for_context(cpath, ptype, effective_principal)
            logger.info(f'Found {len(stmts)} applicable statements from simulation engine.')
            prospective_matched = [s for s in stmts if s.get('is_prospective')]
            logger.info(
                'load_statements: matched %d prospective statements (ids=%s names=%s)',
                len(prospective_matched),
                [s.get('internal_id') for s in prospective_matched],
                [s.get('policy_name') for s in prospective_matched],
            )
            all_stmts = stmts
        else:
            all_stmts = []
        # Remove old checklist/table if present
        table = getattr(self, 'statement_checkbox_table', None)
        if table is not None:
            table.destroy()
            self.statement_checkbox_table = None
        data = []
        for st in all_stmts:
            comp_path = st.get('compartment_path', 'Unknown Path')
            desc = st.get('description')
            base_name = desc or st.get('policy_name', 'Unnamed Policy')
            label = f'{base_name} ({comp_path})'
            if st.get('is_prospective'):
                label = f'[Prospective] {label}'
            data.append(
                {
                    'Policy Path/Name': label,
                    'Policy Statement': st.get('statement_text', ''),
                    'Conditional': 'Yes' if st.get('conditions') else 'No',
                    'obj': st,
                }
            )

        def on_action(checked_rows):  # called whenever checkbox selection changes
            checked_ids = [row.get('obj', {}).get('internal_id') for row in checked_rows if row.get('obj')]
            logger.info('Checkbox selection changed; %d statements checked: %s', len(checked_ids), checked_ids)

            # Rebuild checked_statements mapping, preserving existing where-input values
            self.checked_statements = {}
            for row in data:
                obj = row.get('obj')
                if not obj:
                    continue
                internal_id = obj.get('internal_id')
                if internal_id is None:
                    continue
                is_checked = any(cr.get('obj') is obj for cr in checked_rows)
                self.checked_statements[internal_id] = (tk.BooleanVar(value=is_checked), obj)

            # Auto-update where-clause inputs based on currently checked rows
            self._rebuild_where_inputs_from_checked_rows(checked_rows)

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
            action_buttons=[
                ('Load Available Where Clause Fields (Required)', self.load_where_fields),
            ],
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

    # ------------------------------------------------------------------
    # Prospective Statement Editor
    # ------------------------------------------------------------------

    def add_prospective_statement_from_builder(  # noqa: C901
        self,
        statement_text: str,
        compartment_path: str | None = None,
        description: str | None = None,
    ) -> None:
        """Add a new prospective statement generated by the Tag-based builder.

        This now delegates persistence to the tenancy-scoped
        ProspectiveStatementsService when available, or falls back to the
        simulation engine's in-memory list. The Simulation tab itself
        remains read-only and simply refreshes its prospective preview.
        """

        statement_text = (statement_text or '').strip()
        if not statement_text:
            return

        if not compartment_path:
            compartment_path = self.selected_compartment.get() or 'ROOT'
        if description is None:
            description = 'Tag-based builder statement'

        record = {
            'compartment_path': compartment_path,
            'description': description,
            'statement_text': statement_text,
        }

        service = getattr(self.app, 'prospective_service', None)
        engine = self._get_simulation_engine()

        try:
            if service is not None and hasattr(service, 'append_from_simple_dict'):
                service.append_from_simple_dict(record)  # type: ignore[attr-defined]
                service.persist_and_push_to_engine()
                if engine is not None and hasattr(engine, 'set_prospective_statements'):
                    engine.set_prospective_statements(service.to_simple_list())
        except Exception:
            logger.warning('SimulationTab: failed to add prospective statement from builder', exc_info=True)
            return

        # Refresh the read-only prospective preview
        try:
            if getattr(self, 'prospective_container', None) is not None:
                for child in self.prospective_container.winfo_children():
                    child.destroy()
                self._build_inline_prospective_preview(self.prospective_container)
        except Exception:
            logger.debug('SimulationTab: unable to refresh prospective preview after builder add', exc_info=True)

        # Mark environment changed so Statements & Context will be recomputed
        self._on_environment_changed(reason='prospective_added_from_builder')

    def open_prospective_editor(self, *_):  # noqa: C901
        """Open a simple CRUD dialog for managing prospective policy statements.

        Users can add/edit/delete "what-if" statements that will be evaluated
        alongside real tenancy policies during simulation. Only statements
        applicable to the current compartment/principal will appear in the
        Applicable Policy Statements table, but this editor allows defining
        prospective statements anywhere in the tenancy.
        """

        engine = getattr(self, 'simulation_engine', None)
        if not engine or not hasattr(engine, 'get_prospective_statements'):
            logger.warning('Prospective editor opened but simulation_engine has no prospective support.')
            return

        # Modal toplevel window
        win = tk.Toplevel(self)
        win.title('Manage Prospective Policy Statements')
        win.transient(self.winfo_toplevel())
        win.grab_set()

        # Match the main app/background theme (avoid stark white background)
        try:
            bg = ttk.Style().lookup('TFrame', 'background') or self.cget('background')
        except Exception:
            bg = '#f0f0f0'
        win.configure(background=bg)

        # Intro text about scope semantics
        intro = (
            'Define prospective (what-if) policy statements anywhere in the tenancy.\n'
            'During simulation, only statements applicable to the selected compartment '
            'and principal will appear in the "Applicable Policy Statements" table.'
        )
        ttk.Label(win, text=intro, wraplength=700, justify='left').pack(fill='x', padx=8, pady=(8, 4))

        # Container for rows
        rows_frame = ttk.Frame(win)
        rows_frame.pack(fill='both', expand=True, padx=8, pady=4)

        # Columns: Location (compartment), Description, Statement Text, Status, Actions
        header = ttk.Frame(rows_frame)
        header.pack(fill='x')
        ttk.Label(header, text='Location (Compartment)', width=35).grid(row=0, column=0, sticky='w', padx=2)
        ttk.Label(header, text='Description', width=25).grid(row=0, column=1, sticky='w', padx=2)
        ttk.Label(header, text='Statement Text', width=60).grid(row=0, column=2, sticky='w', padx=2)
        ttk.Label(header, text='Status', width=20).grid(row=0, column=3, sticky='w', padx=2)
        ttk.Label(header, text='Actions', width=12).grid(row=0, column=4, sticky='w', padx=2)

        body = ttk.Frame(rows_frame)
        body.pack(fill='both', expand=True, pady=(4, 0))

        # Keep simple: store row widgets/vars in a list
        row_models: list[dict[str, object]] = []

        # Available compartments for dropdown
        compartments = list(self._sim_index_compartments or ['ROOT'])

        def add_row(initial: dict | None = None):
            idx = len(row_models)
            row = {}

            loc_var = tk.StringVar(
                value=(initial or {}).get('compartment_path') or (self.selected_compartment.get() or 'ROOT')
            )
            desc_var = tk.StringVar(value=(initial or {}).get('description') or '')
            text_initial = (initial or {}).get('statement_text') or ''
            status_var = tk.StringVar(value='Not parsed')

            frame = ttk.Frame(body)
            frame.grid(row=idx, column=0, sticky='ew', pady=2)

            loc_cb = ttk.Combobox(frame, textvariable=loc_var, values=compartments, width=35)
            loc_cb.grid(row=0, column=0, padx=2, sticky='w')
            desc_entry = ttk.Entry(frame, textvariable=desc_var, width=25)
            desc_entry.grid(row=0, column=1, padx=2, sticky='w')
            # Use a scrollable, word-wrapped Text widget for long statements
            text_container = ttk.Frame(frame)
            text_container.grid(row=0, column=2, padx=2, sticky='w')
            text_widget = tk.Text(text_container, width=60, height=2, wrap='word')
            text_widget.insert('1.0', text_initial)
            text_widget.grid(row=0, column=0, sticky='w')
            text_scroll = ttk.Scrollbar(text_container, orient='vertical', command=text_widget.yview)
            text_scroll.grid(row=0, column=1, sticky='ns')
            text_widget.configure(yscrollcommand=text_scroll.set)
            status_lbl = ttk.Label(frame, textvariable=status_var, width=20, foreground='#555')
            status_lbl.grid(row=0, column=3, padx=2, sticky='w')

            def on_parse():
                stmt_text = text_widget.get('1.0', 'end-1c').strip()
                if not stmt_text:
                    status_var.set('Enter statement text')
                    return
                try:
                    result = self.simulation_engine.validate_prospective_statement(stmt_text)
                    logger.debug('Prospective parse debug result: %r', result)
                    if result.get('parsed') and result.get('valid'):
                        status_var.set('Ready')
                    else:
                        reasons = result.get('invalid_reasons') or []
                        status_var.set('Invalid')
                        logger.warning(
                            'Prospective statement parse failed or invalid. reasons=%s, text=%r',
                            reasons,
                            stmt_text,
                        )
                except Exception as ex:
                    status_var.set('Error')
                    logger.warning('Exception during prospective parse: %s', ex, exc_info=True)

            def on_delete():
                frame.destroy()
                row_models.remove(row)

            parse_btn = ttk.Button(frame, text='Parse', command=on_parse, width=6)
            parse_btn.grid(row=0, column=4, padx=(2, 0), sticky='w')
            del_btn = ttk.Button(frame, text='Delete', command=on_delete, width=6)
            del_btn.grid(row=0, column=5, padx=(2, 0), sticky='w')

            row.update(
                {
                    'frame': frame,
                    'loc_var': loc_var,
                    'desc_var': desc_var,
                    'text_widget': text_widget,
                    'status_var': status_var,
                }
            )
            row_models.append(row)

        # Seed from engine
        try:
            existing = engine.get_prospective_statements() or []
        except Exception as ex:  # defensive
            logger.warning(f'Unable to load prospective statements: {ex}')
            existing = []

        if existing:
            for stmt in existing:
                add_row(stmt)
        else:
            add_row({})

        # Bottom buttons
        btns = ttk.Frame(win)
        btns.pack(fill='x', padx=8, pady=(6, 8))

        def on_add():
            add_row({})

        def on_save():  # noqa: C901
            # Collect rows into simple dicts and hand off to engine
            new_list = []
            for rm in row_models:
                loc = rm['loc_var'].get().strip()  # type: ignore[union-attr]
                desc = rm['desc_var'].get().strip()  # type: ignore[union-attr]
                text_widget = rm['text_widget']  # type: ignore[index]
                if not isinstance(text_widget, tk.Text):
                    continue
                text = text_widget.get('1.0', 'end-1c').strip()
                if not text:
                    # Skip completely empty rows
                    continue
                if not loc:
                    loc = 'ROOT'
                new_list.append(
                    {
                        'compartment_path': loc,
                        'description': desc,
                        'statement_text': text,
                    }
                )

            try:
                service = getattr(self.app, 'prospective_service', None)
                if service is not None:
                    service.replace_all_from_simple_list(new_list)
                    service.persist_and_push_to_engine()
                    engine.set_prospective_statements(service.to_simple_list())
                else:
                    engine.set_prospective_statements(new_list)
                logger.info('Saved %d prospective statements via editor', len(new_list))
            except Exception as ex:  # defensive UI guard
                import tkinter.messagebox as mb

                mb.showerror('Error Saving Prospective Statements', str(ex))
                return

            # Refresh main table so new prospective statements appear
            self.load_statements()
            win.destroy()

        ttk.Button(btns, text='Add Statement', command=on_add).pack(side='left')
        ttk.Button(btns, text='Save', command=on_save).pack(side='right')
        ttk.Button(btns, text='Cancel', command=win.destroy).pack(side='right', padx=(0, 6))

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
            self.where_fields_label.configure(text=f'Where-Clause Inputs: {sorted_vars} (blank = null/not supplied)')
        else:
            self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
        # Once where fields are loaded, call button-enabling callback (respect API op selection logic)
        self._maybe_enable_sim_buttons()
        logger.info(f'Where fields loaded from checked statements: {sorted_vars}')

    def _rebuild_where_inputs_from_checked_rows(self, checked_rows):  # noqa: C901
        """Recompute where-clause input fields based on the currently checked rows.

        This is an auto-updating variant of load_where_fields that:
          * Regenerates the variable list whenever checkbox selection changes.
          * Preserves any existing values for variables that remain in scope.
        """

        logger.info('Rebuilding where inputs from %d checked row(s)', len(checked_rows or []))

        checked_rows = checked_rows or []

        # Collect variable names from all checked statements
        all_var_names: set[str] = set()
        for row in checked_rows:
            st = row.get('obj', row)
            cond_str = st.get('conditions') if isinstance(st, dict) else None
            if not cond_str:
                continue
            try:
                all_var_names.update(PolicySimulationEngine.extract_variable_names(cond_str))
            except Exception as exc:  # defensive
                logger.info('Extracting variables failed for stmt %r: %s', st, exc)

        sorted_vars = sorted(all_var_names)

        # Preserve old values where possible
        old_inputs = self.simulation_inputs or {}
        self._clear_where_inputs()

        if not sorted_vars:
            self.where_fields_label.configure(text='Where-Clause Inputs: [None]')
            self._maybe_enable_sim_buttons()
            return

        EXAMPLES = {
            'request.utc-timestamp': 'e.g. 2026-01-05T12:34:56Z',
            'request.utc-timestamp.time-of-day': 'e.g. 13:27:00Z',
        }

        for idx, var in enumerate(sorted_vars):
            ttk.Label(self.where_inputs_frame, text=var + ':', font=('TkDefaultFont', 10)).grid(
                row=idx, column=0, padx=2, pady=1, sticky='e'
            )
            # Reuse existing StringVar if present to preserve value
            strvar = old_inputs.get(var) or tk.StringVar()
            entry = ttk.Entry(self.where_inputs_frame, textvariable=strvar, width=35)
            entry.grid(row=idx, column=1, padx=2, pady=1, sticky='w')

            example_hint = ''
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

        self.where_fields_label.configure(text=f'Where-Clause Inputs: {sorted_vars} (blank = null/not supplied)')
        self._maybe_enable_sim_buttons()
        logger.info('Auto where fields rebuilt; variables=%s', sorted_vars)

    # API Operation search/filter
    def _on_api_op_search(self, event):
        val = self.api_operation_combobox.get()
        filtered = [op for op in getattr(self, '_all_api_ops', []) if val.lower() in op.lower()]
        self.api_operation_combobox['values'] = filtered if filtered else getattr(self, '_all_api_ops', [])

    def _on_api_op_selected(self, event=None):
        """
        When an API operation is selected, show the note below if one exists.

        This ensures that if the selected API operation has a "note" field (case-insensitive), it is displayed
        below the dropdown. If not, the note area is hidden.
        """
        op_name = self.selected_api_operation.get()
        note = ''
        # Check for possible sources of API operation notes:
        op_detail = None
        ref_repo = getattr(self, 'ref_data_repo', None)
        sim_engine = getattr(self, 'simulation_engine', None)
        # Try ref_data_repo first (most typical)
        if ref_repo and hasattr(ref_repo, 'data'):
            if 'operations' in ref_repo.data:
                op_detail = ref_repo.data['operations'].get(op_name)
        # If not found, and if sim_engine exposes operation detail, try there (edge case)
        if not op_detail and sim_engine and hasattr(sim_engine, 'get_api_operation_detail'):
            try:
                op_detail = sim_engine.get_api_operation_detail(op_name)
            except Exception:
                op_detail = None
        if op_detail and isinstance(op_detail, dict):
            # Accept 'note' regardless of capitalization
            note = op_detail.get('notes') or ''
            related_checks = op_detail.get('related_checks') or []
            if related_checks:
                related_lines = ['Related permission checks:']
                for check in related_checks:
                    permissions = ', '.join(check.get('permissions') or []) or '[none]'
                    related_lines.append(
                        f"- {check.get('resource') or '[resource unknown]'}: {permissions}; "
                        f"applies when: {check.get('applies_when') or 'conditional dependency'}"
                    )
                note = '\n'.join([line for line in [note, *related_lines] if line])
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
                # Cache for dynamic re-render on Show Trace toggle
                self.simulation_results = trace
                # Pretty print permissions/result (similar to after run_simulation).
                api_allowed = bool(trace.get('api_call_allowed'))
                lines: list[str] = []
                lines.append(f"Result: {'ALLOWED' if api_allowed else 'DENIED'}")
                failure_reason = trace.get('failure_reason') or ''
                if failure_reason:
                    lines.append(f'Reason: {failure_reason}')

                sim_trace = trace.get('simulation_trace') or {}
                final_permissions: list[str] = []
                if isinstance(sim_trace, dict):
                    final_permissions = sim_trace.get('final_permission_set') or []

                # Required and missing permissions summary
                required = trace.get('required_permissions_for_api_operation') or []
                missing = trace.get('missing_permissions') or []
                lines.append(f"Required permissions for API: {', '.join(required) if required else '[none]'}")
                if missing:
                    lines.append(f"Missing permissions: {', '.join(missing)}")

                # Only show full permission set and JSON when trace toggle is on
                if self.show_trace_details_var.get():
                    lines.append(
                        f"Final permission set: {', '.join(final_permissions) if final_permissions else '[none granted]'}"
                    )
                    lines.append('Simulation JSON detail below:\n')
                    pretty_json = json.dumps(trace, indent=2, ensure_ascii=False)
                    lines.append(pretty_json)

                self.results_text.delete(1.0, tk.END)
                self.results_text.insert(tk.END, '\n'.join(lines))

    def run_simulation(self):
        """Runs a policy simulation with the current selections (basic mode).

        Triggers the simulation engine and displays allow/deny result and final permission set.

        Returns:
            None
        """
        # Called on "Run Simulation". Engine always computes full trace;
        # UI decides how much to display based on show_trace_details_var.
        self._run_simulation_with_trace()
        # After a successful run, switch to the History subtab so the user
        # immediately sees the result and can browse prior traces.
        try:
            self.notebook.select(self.history_frame)
        except Exception:
            logger.debug('SimulationTab: unable to switch to history_frame after run', exc_info=True)

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

    def _run_simulation_with_trace(self):  # noqa: C901
        logger.info('Starting simulation with current selections')

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
        # Compose principal_key for engine using the same normalization
        # rules as PolicyIntelligenceEngine.calculate_principal_key and
        # PolicySimulationEngine._normalize_principal_key. Keep this
        # logic local to avoid importing engine classes into the UI
        # layer while still producing identical keys.
        if ptype in ('any-user', 'any-group', 'service'):
            # any-user:any-group/service always carry domain "None" in the key.
            pname = pname_display or ptype
            principal_key = f'{ptype}:None/{pname}'
        elif '/' in pname_display:
            domain, name = pname_display.split('/', 1)
            dom_norm = domain or 'Default'
            if dom_norm.lower() == 'default':
                dom_norm = 'Default'
            principal_key = f'{ptype}:{dom_norm}/{name}'
        else:
            # No explicit domain given; default identity domain is
            # represented explicitly as "Default".
            principal_key = f'{ptype}:Default/{pname_display}'
        # Normalize where-clause timestring entries
        where_context = {
            key: (self._normalize_timestring(value.get()) if value.get() != '' else None)
            for key, value in self.simulation_inputs.items()
        }

        # --- Improved: Include operation and principal for trace history name ---
        sim_trace_name = f'{api_operation} | {ptype}:{pname_display}' if api_operation and pname_display else None

        logger.info(f'Calling simulate_and_record on simulation_engine with {len(checked_statement_ids)} statements')
        result = self.simulation_engine.simulate_and_record(
            principal_key,
            cpath,
            api_operation,
            where_context,
            checked_statement_ids,
            trace_name=sim_trace_name,
            trace=True,
        )

        # Track this simulation as a high-level operation (batched per run).
        try:
            tracker = get_usage_tracker()
            if tracker is not None:
                sim_trace = result.get('simulation_trace') or {}
                final_perms = set(sim_trace.get('final_permission_set') or [])
                required = set(result.get('required_permissions_for_api_operation') or [])
                missing = set(result.get('missing_permissions') or [])

                # Compute basic allow/deny counts from statement trace without
                # recording any raw statement text.
                allow_count = 0
                deny_count = 0
                prospective_count = 0
                stmt_items = sim_trace.get('trace_statements') or []
                for st in stmt_items:
                    action = str(st.get('action', '')).lower()
                    if action == 'allow':
                        allow_count += 1
                    elif action == 'deny':
                        deny_count += 1

                # Count total vs prospective statements considered based on
                # internal ids present in checked_statements mapping.
                total_checked = 0
                for _var, st in self.checked_statements.values():
                    if not isinstance(st, dict):
                        continue
                    total_checked += 1
                    if st.get('is_prospective'):
                        prospective_count += 1

                tracker.track_operation(
                    'simulation_run',
                    api_operation=api_operation,
                    principal_type=ptype,
                    # redacted principal value; we only log whether one was selected
                    principal_selected=bool(pname_display),
                    effective_path=cpath,
                    total_statements=total_checked,
                    prospective_statements=prospective_count,
                    allow_statements_considered=int(result.get('allow_statements_considered') or 0),
                    deny_statements_considered=int(result.get('deny_statements_considered') or 0),
                    final_permission_count=len(final_perms),
                    required_permission_count=len(required),
                    missing_permission_count=len(missing),
                    # We track whether the operation would be allowed, but
                    # not the specific missing permissions.
                    api_call_allowed=bool(result.get('api_call_allowed')),
                )
        except Exception:
            # Never let usage tracking failures impact simulation UX.
            logger.debug('Failed to record simulation_run operation for usage tracking', exc_info=True)

        # Cache for dynamic re-render on Show Trace toggle
        self.simulation_results = result

        # Display outcome
        summary: list[str] = []
        api_allowed = bool(result.get('api_call_allowed'))
        summary.append(f"Result: {'ALLOWED' if api_allowed else 'DENIED'}")
        failure_reason = result.get('failure_reason') or ''
        if failure_reason:
            summary.append(f'Reason: {failure_reason}')

        # Required and missing permissions summary
        required = result.get('required_permissions_for_api_operation') or []
        missing = result.get('missing_permissions') or []
        summary.append(f"Required permissions for API: {', '.join(required) if required else '[none]'}")
        if missing:
            summary.append(f"Missing permissions: {', '.join(missing)}")
        related_checks = result.get('related_permission_checks') or []
        if related_checks:
            summary.append('Related permission checks:')
            for check in related_checks:
                permissions = ', '.join(check.get('permissions') or []) or '[none]'
                missing_related = ', '.join(check.get('missing_permissions') or [])
                applies_when = check.get('applies_when') or 'Conditional related resource dependency'
                status = 'satisfied' if check.get('satisfied') else 'missing'
                line = f"  - {check.get('resource') or '[resource unknown]'}: {permissions} ({status})"
                if missing_related:
                    line += f'; missing {missing_related}'
                line += f'; applies when: {applies_when}'
                summary.append(line)

        # Always surface a compact count of ALLOW/DENY statements
        # considered for this simulation run so users can quickly see
        # whether the expected policies participated.
        allow_ct = result.get('allow_statements_considered')
        deny_ct = result.get('deny_statements_considered')
        if allow_ct is not None or deny_ct is not None:
            summary.append(
                f'Statements considered: ALLOW={allow_ct if allow_ct is not None else 0}, '
                f'DENY={deny_ct if deny_ct is not None else 0}'
            )

        # Brief where-context echo for quick sanity checks.
        where_ctx = result.get('simulation_trace', {}).get('simulation_context', {}).get('where_context') or {}
        if where_ctx:
            pretty_where = json.dumps(where_ctx, indent=2, ensure_ascii=False)
            summary.append('Where context:')
            summary.append(pretty_where)

        # Pull the final permission set from the nested simulation_trace block,
        # but only display it when trace details are enabled.
        sim_trace = result.get('simulation_trace') or {}
        final_permissions = sim_trace.get('final_permission_set') or []
        if self.show_trace_details_var.get():
            summary.append(f"Final permission set: {', '.join(final_permissions) or '[none granted]'}")
            summary.append('Simulation JSON detail below:\n')
            pretty_json = json.dumps(result, indent=2, ensure_ascii=False)
            summary.append(pretty_json)

        self.results_text.insert(tk.END, '\n'.join(summary))
        logger.info(
            'Simulation result: %s',
            'ALLOWED' if api_allowed else 'DENIED',
        )
        # Update and select latest in trace history dropdown
        self._update_trace_history_dropdown()
        self.trace_history_dropdown.update_idletasks()
