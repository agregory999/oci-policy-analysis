##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_workbench_tab.py
#
# UI tab for advanced policy consolidation ("Consolidation Workbench").
#
# Multi-subtab prototype: Protection, Candidate Selection, Proposal.
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import time
import tkinter as tk
import tkinter.messagebox as tkmessagebox
from tkinter import ttk

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker
from oci_policy_analysis.application.services.consolidation_workbench_service import ConsolidationWorkbenchService
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import CheckboxTable, DataTable


# Each instance will have self.logger for timing and info
def get_module_logger():
    """Return the logger used by the consolidation workbench module."""
    return get_logger(component='consolidation_workbench_tab')


# Locked/system policies whose statements are omitted from consolidation (by policy name)
LOCKED_POLICY_NAME = 'Tenant Admin Policy'

# =========================
# ConsolidationWorkbenchTab
# =========================


class ConsolidationWorkbenchTab(BaseUITab):
    """
    UI tab for the advanced policy consolidation workbench.

    This tab features:
    1. Policy/Statement Protection (browser w/ checkboxes)
    2. Candidate Selection & Strategy (checkboxes, search, protected list, strategy)
    3. Proposal/Batch tab (proposal result and multi-step plan history)

    Note:
      - After policy data is reloaded (e.g. in main), call `reload_and_validate_protection_set()` to
        ensure protected statements still exist; missing ones are flagged and removed.
      - All state (protection, plans/history) are persisted/loaded as per-tenancy session overlay in the canonical cache.
    """

    # ====== Public API ======

    def __init__(self, parent, app):
        """
        Initialize the consolidation workbench tab UI.

        Args:
            parent (Widget): The parent tkinter/tkk widget.
            app (Any): Application-wide context; required for policy repo, tenancy OCID, and event hooks.
        """
        self.logger = get_module_logger()
        self.logger.debug('Initializing ConsolidationWorkbenchTab')
        super().__init__(
            parent,
            default_help_text=(
                'The Consolidation Workbench provides advanced controls for protecting, selecting, '
                'and consolidating statements and policies in a repeatable/batch-driven workflow.'
            ),
        )
        self.app = app
        # Keep all consolidation behavior behind the application service used by
        # the web workbench.
        self.service = getattr(self.app, 'consolidation_workbench_service', None)
        if self.service is None:
            self.service = ConsolidationWorkbenchService(self.app.app_context)
        self.protected_statement_ids = set()
        self.candidate_statement_ids = set()
        self.protect_table_selected_ids = set()  # Persist selection as Internal IDs

        self.protection_full_data = []  # stores unfiltered data for search
        self._build_notebook_ui()

    # No data loading here; populate_data will be called after data context is loaded

    def populate_data(self):
        """
        Public entry point called after UI construction and tenancy/policy data load.
        Calls all necessary data loaders for this tab, each timed and logged using self.timed_step.
        """
        self.logger.info('Populating ConsolidationWorkbenchTab data...')
        self.timed_step('load_policies_and_statements', self.load_policies_and_statements)
        self.timed_step('reload_and_validate_protection_set', self.reload_and_validate_protection_set)
        self.timed_step('refresh_plan_history_for_tenancy', self.refresh_plan_history_for_tenancy)
        self.logger.info('Finished ConsolidationWorkbenchTab.populate_data')

    # ====== Main UI Construction ======
    # ====== Public Methods ======

    def reload_and_validate_protection_set(self):
        """
        Validate the current protected statements after policy data reload.
        When called after tenancy data/policy reload, checks that all internal_ids in the
        protected set are still present in policy data. Any missing statements are logged
        (warning) and removed from protection/candidate sets. UI is automatically refreshed.

        Returns:
            None
        """

        timings = []
        start = time.perf_counter()
        show_all_timings = False
        # Defensive: check if the app has a settings dict with our flag
        if hasattr(self, 'app') and hasattr(self.app, 'settings'):
            show_all_timings = bool(self.app.settings.get('always_log_timings', False))

        def _log_ui_timing(step_name, elapsed):
            if show_all_timings:
                self.logger.critical(
                    f'[UI Timing] ConsolidationWorkbenchTab.reload_and_validate_protection_set.{step_name}: {elapsed:.2f}s'
                )

        def step(label, fn):
            t0 = time.perf_counter()
            fn()
            t1 = time.perf_counter()
            elapsed = t1 - t0
            timings.append((label, elapsed))
            _log_ui_timing(label, elapsed)

        self.logger.info('Validating protected set after policy data reload.')
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if not repo or not hasattr(repo, 'regular_statements'):
            self.logger.warning('No policy_compartment_analysis or regular_statements found for validation.')
            return

        # Build set of current valid internal_ids
        t0 = time.perf_counter()
        current_ids = {st.get('internal_id', '') for st in repo.regular_statements if st.get('internal_id', '')}
        before_count = len(self.protected_statement_ids)
        missing_ids = {iid for iid in self.protected_statement_ids if iid not in current_ids}
        t1 = time.perf_counter()
        build_ids_elapsed = t1 - t0
        timings.append(('Build valid current_ids + find missing', build_ids_elapsed))
        if 'show_all_timings' in locals() and show_all_timings:
            self.logger.critical(
                f'[UI Timing] ConsolidationWorkbenchTab.reload_and_validate_protection_set.Build valid current_ids + find missing: {build_ids_elapsed:.2f}s'
            )

        for iid in sorted(missing_ids):
            self.logger.warning(
                f"Protected statement with internal_id '{iid}' no longer exists in current policy data (was removed or updated). It will be unprotected."
            )

        changed = False
        if missing_ids:
            self.protected_statement_ids.difference_update(missing_ids)
            self.protect_table_selected_ids.difference_update(missing_ids)
            changed = True

        if changed:
            self.logger.info('Updating UI after removed protected statements: %s', missing_ids)

        step('_refresh_filter_protect_table', self._refresh_filter_protect_table)
        step('_update_selected_statements_table', self._update_selected_statements_table)
        step('_update_protected_display', self._update_protected_display)
        step('_load_candidate_statements', self._load_candidate_statements)

        after_count = len(self.protected_statement_ids)
        self.logger.info(
            f'Protection set validated after reload. {before_count - after_count} missing internal_id(s) removed; {after_count} protected remain.'
        )
        self.logger.info(
            'consolidation_tab.reload_and_validate_protection_set timing (seconds): '
            + ' | '.join([f'{label}: {elapsed:.2f}' for label, elapsed in timings])
            + f' | TOTAL: {time.perf_counter()-start:.2f}s'
        )

    def refresh_plan_history_for_tenancy(self):
        """
        Refresh the plan list for the current tenancy in the Proposal dropdown and Plan History tab.

        Call after any load (tenancy, cache, or compliance) so all plans tied to this tenancy_ocid
        are visible. Reload and Check Progress is enabled only when data is from OCI (current).

        Returns:
            None
        """
        self._refresh_plan_history_dropdown()

    # ====== UI Construction: Subtabs ======
    def _build_notebook_ui(self):
        """Build the notebook and protection/candidate/proposal subtabs.

        Returns:
            None
        """
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Top-level Notebook (subtabs INSIDE the workbench tab)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=0, pady=0)
        self.add_context_help(
            self.notebook,
            (
                'Switch between protection, selection/strategy, and consolidation proposal for staged refactoring. '
                'Selections/submissions in one tab feed into actions in the next.'
            ),
        )

        # --- Subtab 1: Protection ---
        frame_protect = ttk.Frame(self.notebook)
        self._build_protection_tab(frame_protect)
        self.notebook.add(frame_protect, text='Policy/Statement Protection')

        # --- Subtab 2: Candidate Selection & Strategy ---
        frame_candidate = ttk.Frame(self.notebook)
        self._build_candidate_tab(frame_candidate)
        self.notebook.add(frame_candidate, text='Candidate Selection & Strategy')

        # --- Subtab 3: Proposal/Batch ---
        frame_proposal = ttk.Frame(self.notebook)
        self._build_proposal_tab(frame_proposal)
        self.notebook.add(frame_proposal, text='Consolidation Proposal')

        # --- Subtab 4: Plan History (read-only) ---
        frame_history = ttk.Frame(self.notebook)
        self._build_plan_history_tab(frame_history)
        self.notebook.add(frame_history, text='Plan History')

    # === Subtab 1: Protection ===

    def _build_protection_tab(self, parent):
        """Build the protection subtab (search, checkbox table, selected-statements table).

        Args:
            parent: Parent ttk.Frame for the subtab.

        Returns:
            None
        """
        label = ttk.Label(
            parent,
            text='Mark policies/statements as protected; these are excluded from proposed consolidations. Changes here are instantly reflected in candidate tabs.',
            wraplength=1100,
            justify='left',
        )
        label.pack(fill='x', padx=12, pady=(12, 2))

        # --- Search/Filter Row ---
        filter_frame = ttk.Frame(parent)
        filter_frame.pack(fill='x', padx=12, pady=(2, 5))

        ttk.Label(filter_frame, text='Search Policy Name:').pack(side='left', padx=(0, 3))
        self.policy_search_var = tk.StringVar()
        policy_search_entry = ttk.Entry(filter_frame, textvariable=self.policy_search_var, width=24)
        policy_search_entry.pack(side='left', padx=(0, 8))
        clear_policy_btn = ttk.Button(filter_frame, text='Clear', command=lambda: self.policy_search_var.set(''))
        clear_policy_btn.pack(side='left', padx=(0, 10))

        ttk.Label(filter_frame, text='Search Statement Text:').pack(side='left', padx=(8, 3))
        self.statement_search_var = tk.StringVar()
        statement_search_entry = ttk.Entry(filter_frame, textvariable=self.statement_search_var, width=24)
        statement_search_entry.pack(side='left', padx=(0, 8))
        clear_stmt_btn = ttk.Button(filter_frame, text='Clear', command=lambda: self.statement_search_var.set(''))
        clear_stmt_btn.pack(side='left', padx=(0, 10))

        self.policy_search_var.trace_add('write', lambda *_: self._refresh_filter_protect_table())
        self.statement_search_var.trace_add('write', lambda *_: self._refresh_filter_protect_table())

        protect_table_frame = ttk.Frame(parent)
        protect_table_frame.pack(fill='both', expand=True, padx=10, pady=(2, 8))

        # Table keeps Internal ID in data but hides it from display via display_columns.
        self.protect_table = CheckboxTable(
            protect_table_frame,
            columns=['Policy Name', 'Statement Text', 'Location', 'Compartment', 'Principal', 'Internal ID'],
            data=[],
            display_columns=['☑', 'Policy Name', 'Statement Text', 'Location', 'Compartment', 'Principal'],
            sortable=True,
            column_widths={
                'Policy Name': 180,
                'Statement Text': 320,
                'Location': 120,
                'Compartment': 120,
                'Principal': 120,
                'Internal ID': 90,
            },
            action_buttons=[
                ('Save Protected', self._on_mark_as_protected),
                ('Save and Select Consolidation Statements', self._on_save_and_go_to_candidates),
            ],
            enable_select_all=True,
            checked_by_default=False,
            check_changed_callback=self._on_protect_check_changed,
            select_all_callback=self._on_protect_select_all,
        )
        self.protect_table.pack(fill='both', expand=True, padx=2, pady=(2, 0))
        self.add_context_help(
            self.protect_table, 'Check policies and/or statements to mark as protected from consolidation jobs.'
        )

        # Table at the bottom showing protected/selected statements (Internal ID kept in data, hidden from display).
        self.selected_statements_table = DataTable(
            protect_table_frame,
            columns=['Policy Name', 'Statement Text', 'Internal ID'],
            display_columns=['Policy Name', 'Statement Text'],
            data=[],
            sortable=True,
            row_colors=('#FAFFF8', '#F3F3FF'),
            column_widths={
                'Policy Name': 180,
                'Statement Text': 500,
                'Internal ID': 90,
            },
            height=5,
        )
        self.selected_statements_table.pack(fill='x', expand=False, padx=2, pady=(12, 3))
        self.add_context_help(
            self.selected_statements_table, 'Current set of protected statements (always visible, display-only).'
        )

    # === Subtab 2: Candidate Selection & Strategy ===

    def _build_candidate_tab(self, parent):
        """Build the candidate selection subtab (search, strategy, checkbox table, proposal button).

        Args:
            parent: Parent ttk.Frame for the subtab.

        Returns:
            None
        """
        outer = ttk.Frame(parent)
        outer.pack(fill='both', expand=True)

        top_label = ttk.Label(
            outer,
            text=(
                'Select policies and statements for consolidation. Use the search box to find by name, compartment, or resource. '
                'Protected and invalid statements are excluded from the list and from consolidation.'
            ),
            wraplength=1100,
            justify='left',
        )
        top_label.pack(fill='x', padx=12, pady=(12, 2))

        # Strategy + Search/filter + Protected count on a single row (pluggable: from engine)
        strat_row = ttk.Frame(outer)
        strat_row.pack(fill='x', padx=12, pady=(3, 2))
        ttk.Label(strat_row, text='Strategy:').pack(side='left', padx=(2, 2))
        strategy_names = self.service.get_status().get('strategy_names', [])
        default_strategy = strategy_names[0] if strategy_names else ''
        self.candidate_strategy_var = tk.StringVar(value=default_strategy)
        strat_combo = ttk.Combobox(
            strat_row,
            textvariable=self.candidate_strategy_var,
            state='readonly',
            values=strategy_names,
            width=32,
        )
        strat_combo.pack(side='left', padx=(2, 16))
        self.add_context_help(strat_combo, 'Choose the algorithm for consolidation (pluggable strategies).')

        # Search/filter box (to right of strategy)
        ttk.Label(strat_row, text='Search/Filter:').pack(side='left', padx=(8, 2))
        self.candidate_search_var = tk.StringVar()
        self.candidate_search_entry = ttk.Entry(strat_row, textvariable=self.candidate_search_var, width=38)
        self.candidate_search_entry.pack(side='left', padx=(2, 16))
        self.candidate_search_var.trace_add('write', lambda *_: self._load_candidate_statements())

        # Protected and Invalid counts (excluded from consolidation)
        self.candidate_protected_count = ttk.Label(strat_row, text='Protected: 0')
        self.candidate_protected_count.pack(side='left', padx=(10, 1))
        self.add_context_help(
            self.candidate_protected_count,
            'Protected statements are not shown as candidates. To edit them, use the Statement/Protection tab.',
        )
        self.candidate_invalid_count = ttk.Label(strat_row, text='Invalid: 0')
        self.candidate_invalid_count.pack(side='left', padx=(8, 1))
        self.add_context_help(
            self.candidate_invalid_count,
            'Invalid statements (parse/validation failures) are omitted from consolidation entirely.',
        )
        self.candidate_system_count = ttk.Label(strat_row, text='System: 0')
        self.candidate_system_count.pack(side='left', padx=(8, 1))
        self.add_context_help(
            self.candidate_system_count,
            f'Statements in locked/system policies (e.g. "{LOCKED_POLICY_NAME}") are omitted from consolidation.',
        )

        # Candidate table (with checkboxes); excluded IDs set in _load_candidate_statements
        self.candidate_table_selected_ids = set()  # persistent selection
        self.invalid_statement_ids = set()
        self.system_statement_ids = set()  # statements in locked policy (e.g. Tenant Admin Policy)
        self.candidate_table = CheckboxTable(
            outer,
            columns=[
                'Policy Name',
                'Statement Text',
                'Statement Compartment Path',
                'Statement Location',
                'Statement Effective Path',
                'Principal',
                'Resource',
                'Internal ID',
            ],
            data=[],
            column_widths={
                'Policy Name': 180,
                'Statement Text': 320,
                'Statement Compartment Path': 160,
                'Statement Location': 160,
                'Statement Effective Path': 160,
                'Principal': 140,
                'Resource': 160,
                'Internal ID': 90,
            },
            action_buttons=[('Create Consolidation Proposal', self._on_create_consolidation_proposal)],
            enable_select_all=True,
            checked_by_default=False,
            check_changed_callback=self._on_candidate_check_changed,
            select_all_callback=self._on_candidate_select_all,
        )
        self.candidate_table.pack(fill='both', expand=True, padx=8, pady=6)
        self.add_context_help(
            self.candidate_table, 'Select candidate policies/statements for consolidation (excluding protected).'
        )

        # Selected candidates table below
        self.selected_candidates_table = DataTable(
            outer,
            columns=[
                'Policy Name',
                'Statement Text',
                'Statement Compartment Path',
                'Statement Location',
                'Statement Effective Path',
                'Principal',
                'Resource',
                'Internal ID',
            ],
            display_columns=[
                'Policy Name',
                'Statement Text',
                'Statement Compartment Path',
                'Statement Location',
                'Statement Effective Path',
                'Principal',
                'Resource',
            ],
            data=[],
            sortable=False,
            row_colors=('#FAFFF8', '#F3F3FF'),
            column_widths={
                'Policy Name': 180,
                'Statement Text': 320,
                'Statement Compartment Path': 160,
                'Statement Location': 160,
                'Statement Effective Path': 160,
                'Principal': 140,
                'Resource': 160,
                'Internal ID': 90,
            },
            height=5,
        )
        # "Statement Compartment Path": st.get("compartment_path", ""),
        # "Statement Location": st.get("location", ""),
        # "Statement Effective Path": st.get("effective_path", ""),
        self.selected_candidates_table.pack(fill='x', expand=False, padx=8, pady=(10, 3))
        self.add_context_help(
            self.selected_candidates_table, 'Current candidate selection (always visible, display-only).'
        )

        # Load initial candidates and counts
        self._load_candidate_statements()
        self._update_selected_candidates_table()

    # === Subtab 3: Proposal ===

    def _build_proposal_tab(self, parent):
        """Build the proposal subtab (plan dropdown, status, proposal table, script area).

        Args:
            parent: Parent ttk.Frame for the subtab.

        Returns:
            None
        """
        lbl = ttk.Label(
            parent,
            text='All consolidation plans for this tenancy are listed below. You can view any plan and its script; '
            "'Reload and Check Progress' is only available when data is loaded from OCI (not cache/compliance).",
            wraplength=1100,
            justify='left',
        )
        lbl.pack(fill='x', padx=12, pady=(12, 5))

        # --- Plan/run history dropdown + Reload button (one row) ---
        dropdown_frame = ttk.Frame(parent)
        dropdown_frame.pack(fill='x', padx=10, pady=(2, 2))
        ttk.Label(dropdown_frame, text='Select Consolidation Plan:').pack(side='left', padx=(4, 3))
        self.plan_history_var = tk.StringVar()
        self.plan_history_dropdown = ttk.Combobox(
            dropdown_frame,
            textvariable=self.plan_history_var,
            state='readonly',
            width=44,
            values=[],
        )
        self.plan_history_dropdown.pack(side='left', padx=(0, 12))
        self.plan_history_dropdown.bind('<<ComboboxSelected>>', self._on_select_plan_history)
        self.plan_history_id_lookup = {}  # id -> run_record

        # Reload + Check Progress button (live-tenancy only)
        self.btn_check_progress = ttk.Button(
            dropdown_frame,
            text='Reload and Check Progress',
            command=self._on_reload_and_check_progress,
        )
        self.btn_check_progress.pack(side='left', padx=(4, 2))
        self.add_context_help(
            self.btn_check_progress,
            (
                'Reload policies/compartments from OCI and check the selected plan against current state. '
                'Enabled only when data was loaded from tenancy (not cache/compliance).'
            ),
        )

        # --- Status in its own section (blue text, full width so reload button stays left) ---
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill='x', padx=10, pady=(2, 6))
        self.plan_status_label = ttk.Label(status_frame, text='', foreground='blue', wraplength=1000, justify='left')
        self.plan_status_label.pack(anchor='w', fill='x')

        # The proposal workspace deliberately uses two stable rows instead of
        # letting the plan table consume all vertical space. This keeps the
        # generated CLI/Console output visible at normal window sizes.
        workspace = ttk.Frame(parent)
        workspace.pack(fill='both', expand=True, padx=10, pady=(2, 10))
        workspace.grid_columnconfigure(0, weight=3, uniform='proposal-top')
        workspace.grid_columnconfigure(1, weight=1, uniform='proposal-top')
        workspace.grid_rowconfigure(0, weight=3, uniform='proposal-rows')
        workspace.grid_rowconfigure(1, weight=2, uniform='proposal-rows')

        # Top row: plan elements (75%) and notes (25%).
        plan_elements_lf = ttk.LabelFrame(workspace, text='Plan Elements')
        plan_elements_lf.grid(row=0, column=0, sticky='nsew', padx=(0, 6), pady=(0, 6))
        self.proposal_table = DataTable(
            plan_elements_lf,
            columns=['#', 'Action', 'Policy Compartment', 'Policy Name', 'Effective Path', 'Details', 'Status'],
            display_columns=['#', 'Action', 'Policy Compartment', 'Policy Name', 'Details', 'Status'],
            data=[],
            sortable=False,
            column_widths={
                '#': 36,
                'Action': 90,
                'Policy Compartment': 280,
                'Policy Name': 280,
                'Details': 280,
                'Status': 90,
            },
            selection_callback=self._on_proposal_row_selected,
        )
        self.proposal_table.pack(fill='both', expand=True, padx=4, pady=4)
        self.add_context_help(
            self.proposal_table, 'Review the ordered consolidation actions before copying the generated output below.'
        )

        notes_lf = ttk.LabelFrame(workspace, text='Plan Notes')
        notes_lf.grid(row=0, column=1, sticky='nsew', padx=(6, 0), pady=(0, 6))
        self.plan_notes_text = tk.Text(notes_lf, height=6, wrap='word', state='normal', width=45)
        self.plan_notes_text.pack(fill='both', expand=True, padx=4, pady=4)
        notes_btn_row = ttk.Frame(notes_lf)
        notes_btn_row.pack(fill='x', padx=4, pady=(0, 4))
        ttk.Button(notes_btn_row, text='Save notes to plan', command=self._on_save_plan_notes).pack(
            side='left', padx=(0, 8)
        )
        self.add_context_help(
            notes_lf,
            'Optional notes for this plan (strategy or your own). Save to persist to plan history.',
        )

        # Bottom row: executable output (50%) and excluded statements (50%).
        script_frame = ttk.LabelFrame(workspace, text='Proposed Script / Batch Output')
        script_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 6), pady=(6, 0))
        self.skipped_statements_lf = ttk.LabelFrame(workspace, text='Skipped Statements (0)')
        self.skipped_statements_lf.grid(row=1, column=1, sticky='nsew', padx=(6, 0), pady=(6, 0))
        self.skipped_statements_tree = ttk.Treeview(
            self.skipped_statements_lf,
            columns=('reason', 'statement_snippet'),
            show='headings',
            height=8,
        )
        self.skipped_statements_tree.heading('reason', text='Reason')
        self.skipped_statements_tree.heading('statement_snippet', text='Statement (snippet)')
        self.skipped_statements_tree.column('reason', width=150)
        self.skipped_statements_tree.column('statement_snippet', width=260)
        skipped_scroll = ttk.Scrollbar(
            self.skipped_statements_lf, orient='vertical', command=self.skipped_statements_tree.yview
        )
        self.skipped_statements_tree.configure(yscrollcommand=skipped_scroll.set)
        self.skipped_statements_tree.pack(side='left', fill='both', expand=True, padx=4, pady=4)
        skipped_scroll.pack(side='right', fill='y', pady=4)
        self.add_context_help(
            self.skipped_statements_lf,
            'Statements that this strategy did not include (e.g. do not match strategy rules).',
        )

        format_row = ttk.Frame(script_frame)
        format_row.pack(fill='x', padx=(6, 6), pady=(4, 2))
        ttk.Label(format_row, text='Format:').pack(side='left', padx=(0, 4))
        self.script_format_var = tk.StringVar(value='OCI CLI')
        self.script_format_combo = ttk.Combobox(
            format_row,
            textvariable=self.script_format_var,
            state='readonly',
            values=['OCI CLI', 'UI-based Steps'],
            width=18,
        )
        self.script_format_combo.pack(side='left', padx=(0, 8))
        self.script_format_combo.bind('<<ComboboxSelected>>', self._on_script_format_changed)
        self.add_context_help(
            self.script_format_combo, 'OCI CLI: shell commands. UI-based Steps: instructions for OCI Console.'
        )
        ttk.Label(format_row, text='Show:').pack(side='left', padx=(12, 4))
        self.script_section_var = tk.StringVar(value='Execution')
        self.script_section_combo = ttk.Combobox(
            format_row,
            textvariable=self.script_section_var,
            state='readonly',
            values=['Execution', 'Rollback', 'Both'],
            width=12,
        )
        self.script_section_combo.pack(side='left', padx=(0, 8))
        self.script_section_combo.bind('<<ComboboxSelected>>', self._on_script_format_changed)
        self.add_context_help(
            self.script_section_combo, 'Show execution plan, rollback plan, or both in the script area.'
        )

        self.script_text = tk.Text(script_frame, height=14, width=120, wrap='word', state='disabled')
        self.script_text.tag_configure('proposal_highlight', background='#e6f0ff')
        self.script_text.pack(fill='both', expand=True, padx=(6, 6), pady=(2, 6))
        self.add_context_help(
            self.script_text, 'CLI commands or UI instructions for the selected plan. Switch format above to toggle.'
        )

        # Keep reference to last plan so format switch can re-render
        self._last_plan_for_script = None

        # --- Load plan history into dropdown on tab build ---
        self._refresh_plan_history_dropdown()

    # === Subtab 4: Plan History ===

    def _build_plan_history_tab(self, parent):
        """Build the read-only Plan History subtab (all plans for tenancy with status).

        Args:
            parent: Parent ttk.Frame for the subtab.

        Returns:
            None
        """
        lbl = ttk.Label(
            parent,
            text='All consolidation plans for this tenancy. On load or reload we check non-completed plans: if any policy in a plan has an opa_consolidation tag from a different plan, Validity shows Conflicted. Cache and compliance data are static (no reload); plans can still be generated and viewed. Select a row and click View in Proposal to open it in the Consolidation Proposal tab.',
            wraplength=1000,
            justify='left',
        )
        lbl.pack(fill='x', padx=12, pady=(12, 5))
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill='x', padx=12, pady=(2, 4))
        refresh_btn = ttk.Button(btn_frame, text='Refresh', command=self._refresh_plan_history_table)
        refresh_btn.pack(side='left', padx=(0, 8))
        self.view_plan_btn = ttk.Button(
            btn_frame,
            text='View in Proposal',
            command=self._on_plan_history_view_in_proposal,
        )
        self.view_plan_btn.pack(side='left', padx=(0, 4))
        self.add_context_help(
            self.view_plan_btn,
            'Load the selected plan in the Consolidation Proposal tab (dropdown and details).',
        )

        def plan_history_context_menu(row_index: int) -> tk.Menu | None:
            """Provide the same per-plan delete action available in the web UI."""
            if row_index < 0 or row_index >= len(self.plan_history_table.data):
                return None
            row = self.plan_history_table.data[row_index]
            effort_id = row.get('consolidation_effort_id') or row.get('Effort ID', '')
            if not effort_id:
                return None
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(
                label='Delete plan from history',
                command=lambda plan_id=effort_id: self._delete_history_plan(plan_id),
            )
            return menu

        self.plan_history_table = DataTable(
            parent,
            columns=['Effort ID', 'Created', 'Strategy', 'Status', 'Steps', 'Validity', 'consolidation_effort_id'],
            display_columns=['Effort ID', 'Created', 'Strategy', 'Status', 'Steps', 'Validity'],
            data=[],
            sortable=True,
            column_widths={
                'Effort ID': 200,
                'Created': 160,
                'Strategy': 220,
                'Status': 100,
                'Steps': 80,
                'Validity': 100,
            },
            selection_callback=self._on_plan_history_row_selected,
            row_context_menu_callback=plan_history_context_menu,
        )
        self.plan_history_table.pack(fill='both', expand=True, padx=8, pady=(0, 4))
        self.add_context_help(
            self.plan_history_table,
            'Read-only list of all consolidation runs. Validity: OK / Conflicted (policies tagged by another plan).',
        )
        # Detail pane below table: plan details, conflicts, and OCI Audit placeholder
        detail_frame = ttk.LabelFrame(parent, text='Plan details')
        detail_frame.pack(fill='both', expand=True, padx=8, pady=(4, 10))
        self.plan_history_detail_text = tk.Text(
            detail_frame, height=10, wrap='word', state='disabled', font=('TkDefaultFont', 9)
        )
        self.plan_history_detail_text.pack(fill='both', expand=True, padx=4, pady=4)
        self.add_context_help(
            detail_frame,
            'Details for the selected plan: summary, tag conflicts (if any), and OCI Audit placeholder.',
        )
        self._plan_history_selected_rows = []
        self._refresh_plan_history_table()

    def _delete_history_plan(self, effort_id: str) -> None:
        """Confirm and delete one persisted plan-history record."""
        if not effort_id:
            return
        try:
            confirmed = tkmessagebox.askyesno(
                'Delete plan from history',
                f'Delete consolidation plan {effort_id} from history?\n\nThis does not change OCI policies.',
            )
        except Exception:
            confirmed = False
        if not confirmed:
            return

        if not self.service.delete_history_run(effort_id):
            try:
                tkmessagebox.showerror('Delete failed', 'The plan could not be found or deleted from history.')
            except Exception:
                pass
            return

        self._plan_history_selected_rows = []
        self._refresh_plan_history_dropdown()
        self._refresh_plan_history_table()
        try:
            tkmessagebox.showinfo('Plan deleted', f'Deleted consolidation plan {effort_id} from history.')
        except Exception:
            pass

    def _refresh_plan_history_table(self):
        """Populate the Plan History table from canonical state and check validity of non-completed plans.

        For each non-completed plan, checks whether any policy in the plan has an opa_consolidation
        tag from a different plan (conflict). Works with any data source (live, cache, compliance).

        Returns:
            None
        """
        if not getattr(self, 'plan_history_table', None):
            return
        tenancy_ocid = self._get_tenancy_ocid()
        if not tenancy_ocid:
            self.plan_history_table.update_data([])
            return
        history = self.service.get_history()
        rows = []
        for run in history:
            rows.append(
                {
                    'Effort ID': run.get('effort_id', '—'),
                    'Created': (run.get('created_at') or '')[:19].replace('T', ' '),
                    'Strategy': run.get('strategy', '—'),
                    'Status': run.get('status', 'in_progress'),
                    'Steps': f"{run.get('executed_steps', 0)}/{run.get('steps', 0)}" if run.get('steps') else '—',
                    'Validity': run.get('validity', '—'),
                    'consolidation_effort_id': run.get('effort_id', ''),
                }
            )
        self.plan_history_table.update_data(rows)

    def _on_plan_history_row_selected(self, selected_rows):
        """Store selection, enable View in Proposal, and update the detail pane."""
        self._plan_history_selected_rows = selected_rows or []
        if hasattr(self, 'view_plan_btn'):
            self.view_plan_btn['state'] = tk.NORMAL if self._plan_history_selected_rows else tk.DISABLED
        self._update_plan_history_detail_pane()

    def _update_plan_history_detail_pane(self):
        """Refresh the Plan details pane with the selected plan's summary, conflicts, and OCI Audit placeholder."""
        detail = getattr(self, 'plan_history_detail_text', None)
        if not detail:
            return
        detail.config(state='normal')
        detail.delete('1.0', 'end')
        selected = getattr(self, '_plan_history_selected_rows', [])
        if not selected:
            detail.insert('end', 'Select a plan above to see details.')
            detail.config(state='disabled')
            return
        row = selected[0]
        effort_id = row.get('consolidation_effort_id') or row.get('Effort ID', '')
        tenancy_ocid = self._get_tenancy_ocid()
        if not tenancy_ocid:
            detail.insert('end', 'No tenancy loaded.')
            detail.config(state='disabled')
            return
        detail_data = self.service.get_history_run_detail(effort_id)
        if not detail_data:
            detail.insert('end', f'Plan {effort_id} not found in history.')
            detail.config(state='disabled')
            return
        run = detail_data['run']
        lines = []
        lines.append('Plan summary')
        lines.append('-' * 40)
        lines.append(f"Effort ID: {run.get('consolidation_effort_id', '—')}")
        lines.append(f"Created:   {(run.get('created_at') or '')[:19]}")
        lines.append(f"Strategy:  {run.get('strategy', '—')}")
        lines.append(f"Status:    {run.get('status', 'in_progress')}")
        plan = run.get('plan') or {}
        steps = plan.get('plan_steps') or []
        step_status = run.get('step_status') or {}
        progress = step_status.get('progress') if isinstance(step_status.get('progress'), dict) else {}
        executed = sum(1 for p in progress.values() if p.get('executed')) if progress else 0
        lines.append(f'Steps:     {executed}/{len(steps)}')
        lines.append('')
        # Conflicts
        lines.append('Conflicts (policies tagged by another plan)')
        lines.append('-' * 40)
        if plan and steps:
            conflicts = detail_data['conflict_analysis']['conflicts']
            if conflicts:
                for c in conflicts:
                    lines.append(f"  Policy OCID: {c.get('policy_ocid', '')}")
                    lines.append(f"    Current tag: {c.get('current_tag_value', '')}")
                    lines.append(f"    Conflicting plan: {c.get('conflicting_plan_id', '')}")
            else:
                lines.append('  None.')
        else:
            lines.append('  (No plan or engine to check.)')
        lines.append('')
        lines.append('OCI Audit Data (selected policy)')
        lines.append('-' * 40)
        lines.append('  (Not implemented yet.)')
        detail.insert('end', '\n'.join(lines))
        detail.config(state='disabled')

    def _on_plan_history_view_in_proposal(self):
        """Load the selected plan from Plan History into the Proposal tab and switch to it."""
        selected = getattr(self, '_plan_history_selected_rows', [])
        if not selected:
            try:
                tkmessagebox.showinfo('No selection', 'Select a plan row first, then click View in Proposal.')
            except Exception:
                pass
            return
        row = selected[0]
        effort_id = row.get('consolidation_effort_id') or row.get('Effort ID', '')
        if not effort_id:
            return
        # Find dropdown label that matches this run (same as in plan_history_id_lookup)
        tenancy_ocid = self._get_tenancy_ocid()
        if not tenancy_ocid:
            return
        run = self.service.get_history_run(effort_id)
        if not run:
            return
        created = (run.get('created_at') or '')[:19].replace('T', ' ')
        label = f'{effort_id} ({created})'
        strat = run.get('strategy', '')
        if strat:
            label += f' [{strat}]'
        if label not in getattr(self, 'plan_history_id_lookup', {}):
            self._refresh_plan_history_dropdown()
        if label in self.plan_history_id_lookup:
            self.plan_history_var.set(label)
            self._on_select_plan_history()
            self.notebook.select(2)  # Proposal tab index
        return

    # ====== Private (Helper/UI) Methods ======

    def _get_tenancy_ocid(self):
        """Resolve tenancy OCID for consolidation state from app or repo.

        Returns:
            str | None: Tenancy OCID if available, else None.
        """
        tenancy_ocid = getattr(self.app, 'tenancy_ocid', None)
        if not tenancy_ocid:
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            if repo and hasattr(repo, 'tenancy_ocid'):
                tenancy_ocid = getattr(repo, 'tenancy_ocid', None)
        return tenancy_ocid

    def _refresh_plan_history_dropdown(self):
        """Load plan history from state and populate the history dropdown.

        Uses tenancy_ocid from app or policy_compartment_analysis so history is found for
        cache-loaded tenancies. Most recent run is selected by default.

        Returns:
            None
        """
        history = []
        for item in self.service.get_history():
            run = self.service.get_history_run(item.get('effort_id', ''))
            if run:
                history.append(run)
        # Show most recent first (by created_at)
        sorted_hist = sorted(history, key=lambda r: r.get('created_at', ''), reverse=True)
        items = []
        self.plan_history_id_lookup = {}
        for run in sorted_hist:
            eid = run.get('consolidation_effort_id', '<unknown>')
            ts = run.get('created_at', '')[:19].replace('T', ' ')
            label = f'{eid} ({ts})'
            strat = run.get('strategy', '')
            if strat:
                label += f' [{strat}]'
            items.append(label)
            self.plan_history_id_lookup[label] = run
        self.plan_history_dropdown['values'] = items
        if items:
            self.plan_history_var.set(items[0])
            self._on_select_plan_history()
        else:
            self.plan_history_var.set('')
            self.plan_status_label.config(text='No prior consolidation runs found.')
            self.proposal_table.update_data([])
            self._set_plan_notes_and_skipped_from_plan(None)
            self._last_plan_for_script = None
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            self.script_text.insert('end', '(no plan selected)')
            self.script_text.config(state='disabled')
        if getattr(self, 'plan_history_table', None):
            self._refresh_plan_history_table()
        # Enable Reload and Check Progress only when data is from OCI (current)
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        can_check = bool(
            repo
            and getattr(repo, 'policies_loaded_from_tenancy', False)
            and not getattr(repo, 'loaded_from_compliance_output', False)
        )
        if hasattr(self, 'btn_check_progress'):
            self.btn_check_progress['state'] = tk.NORMAL if can_check else tk.DISABLED

    def _set_plan_notes_and_skipped_from_plan(self, plan):
        """Populate Plan notes and Skipped statements widgets from plan.

        Args:
            plan: ConsolidationPlan dict or None; if None, clear notes and skipped.
        """
        notes = (plan.get('notes') or '').strip() if plan else ''
        self.plan_notes_text.config(state='normal')
        self.plan_notes_text.delete('1.0', 'end')
        self.plan_notes_text.insert('1.0', notes)
        self.plan_notes_text.config(state='normal')

        skipped = (plan.get('skipped_statements') or []) if plan else []
        for item in self.skipped_statements_tree.get_children():
            self.skipped_statements_tree.delete(item)
        for s in skipped:
            reason = (s.get('reason') or '').strip()
            snippet = (s.get('statement_text') or s.get('internal_id', ''))[:120]
            if len(s.get('statement_text') or '') > 120:
                snippet += '…'
            self.skipped_statements_tree.insert('', 'end', values=(reason, snippet))
        self.skipped_statements_lf.config(text=f'Skipped statements ({len(skipped)})')

    def _on_save_plan_notes(self):
        """Save current plan notes text to the selected plan in history."""
        label = getattr(self, 'plan_history_var', None) and self.plan_history_var.get()
        if not label or not getattr(self, 'plan_history_id_lookup', None) or label not in self.plan_history_id_lookup:
            try:
                tkmessagebox.showinfo('No plan selected', 'Select a consolidation plan from the dropdown first.')
            except Exception:
                pass
            return
        run = self.plan_history_id_lookup[label]
        plan = run.get('plan')
        if not plan:
            try:
                tkmessagebox.showinfo('No plan', 'This run has no plan to attach notes to.')
            except Exception:
                pass
            return
        new_notes = self.plan_notes_text.get('1.0', 'end').strip()
        tenancy_ocid = self._get_tenancy_ocid()
        if not tenancy_ocid:
            try:
                tkmessagebox.showwarning('Cannot save', 'No tenancy OCID; notes not persisted.')
            except Exception:
                pass
            return
        effort_id = run.get('consolidation_effort_id')
        updated_plan = {**plan, 'notes': new_notes}
        if self.service.save_plan_notes(effort_id, new_notes):
            self.plan_history_id_lookup[label] = {**run, 'plan': updated_plan}
            self.logger.info('Saved plan notes for %s', effort_id)
            try:
                tkmessagebox.showinfo('Saved', 'Plan notes saved to history.')
            except Exception:
                pass
        else:
            try:
                tkmessagebox.showerror('Save failed', 'Could not update plan in history.')
            except Exception:
                pass

    def _set_script_content_from_plan(self, plan):
        """Set script text from plan using current format (OCI CLI or UI-based Steps).

        Stores plan in _last_plan_for_script so format/section dropdown can re-render.

        Args:
            plan: ConsolidationPlan dict or None; if None, script shows placeholder.

        Returns:
            None
        """
        self._last_plan_for_script = plan
        self.script_text.config(state='normal')
        self.script_text.delete(1.0, 'end')
        if not plan:
            self.script_text.insert('end', '(no plan selected)')
            self.script_text.config(state='disabled')
            return
        fmt = (self.script_format_var.get() or 'OCI CLI').strip()
        show = (self.script_section_var.get() or 'Execution').strip()
        try:
            effort_id = str(plan.get('plan_id') or '')
            fmt_key = 'ui' if fmt == 'UI-based Steps' else 'cli'
            section_key = 'execution' if show == 'Execution' else ('rollback' if show == 'Rollback' else 'both')
            self.script_text.insert(
                'end', self.service.render_plan(plan, fmt=fmt_key, section=section_key, effort_id=effort_id)
            )
        except Exception as e:
            self.logger.warning('Failed to render script for plan: %s', e)
            self.script_text.insert('end', f'(failed to render: {e})')
        self.script_text.config(state='disabled')

    def _on_script_format_changed(self, event=None):
        """Re-render script area when user changes format or section (OCI CLI / UI-based Steps).

        Args:
            event: Optional tkinter event (unused).

        Returns:
            None
        """
        if getattr(self, '_last_plan_for_script', None):
            self._set_script_content_from_plan(self._last_plan_for_script)

    def _on_proposal_row_selected(self, selected_rows):
        """Highlight the script line that corresponds to the selected proposal step.

        Args:
            selected_rows: List of selected row dicts (first row's step_id is used).

        Returns:
            None
        """
        if not selected_rows:
            self.script_text.config(state='normal')
            self.script_text.tag_remove('proposal_highlight', '1.0', 'end')
            self.script_text.config(state='disabled')
            return
        row = selected_rows[0]
        step_id = row.get('step_id', '').strip()
        if not step_id:
            self.script_text.config(state='normal')
            self.script_text.tag_remove('proposal_highlight', '1.0', 'end')
            self.script_text.config(state='disabled')
            return
        self.script_text.config(state='normal')
        self.script_text.tag_remove('proposal_highlight', '1.0', 'end')
        pos = self.script_text.search(step_id, '1.0', 'end')
        if pos:
            line_start = self.script_text.index(f'{pos} linestart')
            line_end = self.script_text.index(f'{pos} lineend')
            self.script_text.tag_add('proposal_highlight', line_start, line_end)
            self.script_text.see(line_start)
        self.script_text.config(state='disabled')

    def _on_select_plan_history(self, event=None):
        """Handle plan history dropdown selection; update proposal table and script from selected run.

        Args:
            event: Optional tkinter event (unused).

        Returns:
            None
        """
        sel = self.plan_history_var.get()
        if not sel or sel not in self.plan_history_id_lookup:
            self.plan_status_label.config(text='(None selected)')
            self.proposal_table.update_data([])
            self._last_plan_for_script = None
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            self.script_text.insert('end', '(no plan selected)')
            self.script_text.config(state='disabled')
            return
        run = self.plan_history_id_lookup[sel]
        # Show major info in status section
        txt = []
        txt.append(f"Strategy: {run.get('strategy', '')} | Created: {run.get('created_at', '')}")
        step_status = run.get('step_status') or {}
        progress = step_status.get('progress') if isinstance(step_status.get('progress'), dict) else {}
        # Find the latest real executed step (not 'proposal') or fallback
        real_steps = [k for k in step_status.keys() if k != 'proposal']
        if real_steps:
            last_key = real_steps[-1]
            step_info = step_status[last_key]
            txt.append(f"Latest step: {last_key} [{step_info.get('status')}] at {step_info.get('generated_at', '')}")
        elif progress:
            # Fallback if using progress step_id keys
            executed = [k for k, v in progress.items() if v.get('executed')]
            if executed:
                last_key = executed[-1]
                txt.append(f"Latest executed step: {last_key} at {progress[last_key].get('executed_at', '')}")
        else:
            txt.append('Latest step: (not started)')
        self.plan_status_label.config(text=' | '.join(txt))
        plan = run.get('plan')
        if plan:
            # Prefer stored progress from last Reload and Check Progress (so executed steps show correctly when loading old plans)
            step_status = run.get('step_status') or {}
            stored_progress = step_status.get('progress') if isinstance(step_status.get('progress'), dict) else None
            progress = stored_progress
            if progress is None:
                try:
                    progress = self.service.evaluate_progress(plan)
                except Exception as e:
                    self.logger.debug('Could not check plan progress: %s', e)
            data = self.service.get_proposal_rows(plan=plan, progress=progress)
            self._set_plan_notes_and_skipped_from_plan(plan)
        else:
            data = self.service.get_proposal_rows(plan=None, results_fallback=run.get('results', []))
            self._set_plan_notes_and_skipped_from_plan(None)
        self.proposal_table.update_data(data)
        # Render script from plan (CLI or UI per format dropdown)
        if plan:
            self._set_script_content_from_plan(plan)
        else:
            self._last_plan_for_script = None
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            script_out = '\n'.join([f"-- Plan step: {r.get('Policy Name', r.get('policy_name', '?'))}" for r in data])
            self.script_text.insert('end', script_out if script_out else '(no statements)')
            self.script_text.config(state='disabled')

    # Data Loaders and Action Handlers

    def _on_protect_check_changed(self, checked_rows):
        """Handle single-row checkbox change; add/remove only the affected ID for robust selection.

        Args:
            checked_rows: List of row dicts currently checked in the protection table.

        Returns:
            None
        """
        # Figure out which row changed. Compute set of checked.
        checked_ids = {
            row.get('Internal ID') for row in checked_rows if 'Internal ID' in row and row.get('Internal ID')
        }
        # Determine set of visible IDs (only filter once)
        pfilter = self.policy_search_var.get().strip().lower()
        sfilter = self.statement_search_var.get().strip().lower()
        visible_ids = {
            d['Internal ID']
            for d in self.protection_full_data
            if (not pfilter or (d['Policy Name'] and pfilter in d['Policy Name'].lower()))
            and (not sfilter or (d['Statement Text'] and sfilter in d['Statement Text'].lower()))
            and d.get('Internal ID', '')
        }
        checked_previously = {iid for iid in visible_ids if iid in self.protect_table_selected_ids}
        # Find IDs newly checked/unchecked
        newly_checked = checked_ids - checked_previously
        newly_unchecked = checked_previously - checked_ids
        changed = False
        if newly_checked:
            self.protect_table_selected_ids.update(newly_checked)
            changed = True
        if newly_unchecked:
            self.protect_table_selected_ids.difference_update(newly_unchecked)
            changed = True
        # Only update UI if something changed
        if changed:
            self._refresh_filter_protect_table(skip_update_selected=False)
        else:
            self.logger.debug('No protection selection state changed; skipped redundant UI update.')

    def _on_protect_select_all(self, visible_internal_ids, check_state):
        """Apply select-all or clear-all for visible rows; update persistent set and table.

        Args:
            visible_internal_ids: Set or list of internal_ids currently visible (after filter).
            check_state: True to select all, False to clear all visible.

        Returns:
            None
        """
        before = set(self.protect_table_selected_ids)
        if check_state:
            self.protect_table_selected_ids.update(visible_internal_ids)
        else:
            self.protect_table_selected_ids.difference_update(visible_internal_ids)
        if set(self.protect_table_selected_ids) != before:
            self._refresh_filter_protect_table(skip_update_selected=False)
        else:
            self.logger.debug('Select-all/unselect-all: No state change, skipping redundant update.')

    def load_policies_and_statements(self):
        """
        Load all policies and statements for the protection tab and restore protected set.

        Populates the protection table from the bound policy repository (app.policy_compartment_analysis).
        Loads the current protected statement set from the canonical consolidation state file for
        this tenancy and restores checkboxes and protected display. Call after tenancy or
        cache load so the workbench reflects current data.

        Returns:
            None
        """
        self.logger.info('Loading protection rows through ConsolidationWorkbenchService.')
        self.protection_full_data = [
            {
                'Policy Name': row.get('policy_name', ''),
                'Statement Text': row.get('statement_text', ''),
                'Location': row.get('location', ''),
                'Compartment': row.get('effective_path', ''),
                'Principal': row.get('principal', ''),
                'Internal ID': row.get('internal_id', ''),
                'Policy OCID': row.get('policy_ocid', ''),
            }
            for row in self.service.get_protection_rows()
        ]
        protected_set = self.service.get_protected_set()
        ids = {
            ref.get('internal_id')
            for ref in (protected_set.get('protected') or [])
            if isinstance(ref, dict) and ref.get('internal_id')
        }
        self.protected_statement_ids = set(ids)
        self.protect_table_selected_ids = set(ids)
        self.logger.info(
            'Protection browser loaded with %d statements and %d protected.', len(self.protection_full_data), len(ids)
        )
        self._refresh_filter_protect_table()
        self._update_selected_statements_table()

    def _refresh_filter_protect_table(self, *, skip_update_selected=False):
        """Apply policy/statement search filters and refresh protection table; keep checkbox state.
        Optionally skip updating the selected statements table if already handled.

        Returns:
            None
        """
        # Cache last filter
        pfilter = self.policy_search_var.get().strip().lower()
        sfilter = self.statement_search_var.get().strip().lower()
        current_filters = (pfilter, sfilter, frozenset(self.protect_table_selected_ids))
        if hasattr(self, '_last_protect_filter') and self._last_protect_filter == current_filters:
            self.logger.debug('Skipping redundant protection filter/update.')
            return
        self._last_protect_filter = current_filters
        timings = []
        start = time.perf_counter()
        self.logger.debug(
            "Refreshing filter for protection table with policy filter '%s', statement filter '%s'.", pfilter, sfilter
        )
        t0 = time.perf_counter()
        filtered = []
        for d in self.protection_full_data:
            pname = d['Policy Name'].lower() if d['Policy Name'] else ''
            stxt = d['Statement Text'].lower() if d['Statement Text'] else ''
            if (not pfilter or pfilter in pname) and (not sfilter or sfilter in stxt):
                d_checked = dict(d)
                iid = d_checked.get('Internal ID', '')
                # Use persistent set to drive checkbox state for ALL visible rows
                d_checked['checked'] = iid in self.protect_table_selected_ids
                filtered.append(d_checked)
        t1 = time.perf_counter()
        timings.append(('Loop/data filter', t1 - t0))
        t2 = time.perf_counter()
        self.protect_table.update_data(filtered)
        t3 = time.perf_counter()
        timings.append(('update_data (CheckboxTable)', t3 - t2))
        if not skip_update_selected:
            t4 = time.perf_counter()
            self._update_selected_statements_table()
            t5 = time.perf_counter()
            timings.append(('_update_selected_statements_table', t5 - t4))
        self.logger.debug('Protection table filtered: now shows %d statements.', len(filtered))
        self.logger.info(
            '_refresh_filter_protect_table timing (seconds): '
            + ' | '.join([f'{label}: {elapsed:.2f}' for label, elapsed in timings])
            + f' | TOTAL: {time.perf_counter()-start:.2f}s'
        )

    def _on_mark_as_protected(self, selected_rows):
        """Set protected statements from current selection; persist to cache and refresh UI.

        Args:
            selected_rows: List of selected row dicts (must include "Internal ID").

        Returns:
            None
        """
        self.logger.info(
            'Marking selected statements as protected from protection tab. Row count: %d', len(selected_rows)
        )
        selected_ids = set()
        for row in selected_rows:
            if 'Internal ID' in row and row['Internal ID']:
                selected_ids.add(row['Internal ID'])
                self.logger.debug('Protecting statement with Internal ID: %s', row['Internal ID'])
            else:
                self.logger.warning("Row missing 'Internal ID', skipped: %s", row)
        self.protected_statement_ids = selected_ids
        self.protect_table_selected_ids = set(selected_ids)  # Persist current checked Internal IDs
        self.logger.debug('Protected statement IDs set to: %s', self.protected_statement_ids)

        try:
            self.service.set_protected_set(sorted(selected_ids))
        except ValueError as exc:
            self.logger.warning('Protected set was not persisted: %s', exc)

        self._update_protected_display()
        self.logger.debug('Protected display updated after protecting statements.')
        self._load_candidate_statements()
        self.logger.debug('Candidate statements reloaded after protecting statements.')
        self._update_selected_statements_table()

    def _on_save_and_go_to_candidates(self, selected_rows):
        """Save protected statements from the protection table and switch to the Candidate Selection subtab."""
        self._on_mark_as_protected(selected_rows)
        if hasattr(self, 'notebook'):
            self.notebook.select(1)  # Candidate Selection & Strategy

    def _load_candidate_statements(self):
        """Load candidate table: all non-protected, non-invalid statements, optionally filtered by search text.

        Invalid statements (those with invalid_reasons) are omitted from consolidation entirely.
        Returns:
            None
        """
        result = self.service.get_candidate_rows(search=self.candidate_search_var.get())
        counts = result.get('counts', {})
        self.invalid_statement_ids = set()
        self.system_statement_ids = set()
        data = [
            {
                'Policy Name': row.get('policy_name', ''),
                'Statement Text': row.get('statement_text', ''),
                'Statement Compartment Path': row.get('statement_compartment_path', ''),
                'Statement Location': row.get('statement_location', ''),
                'Statement Effective Path': row.get('statement_effective_path', ''),
                'Principal': row.get('principal', ''),
                'Resource': row.get('resource', ''),
                'Internal ID': row.get('internal_id', ''),
                'checked': row.get('internal_id', '') in self.candidate_table_selected_ids,
            }
            for row in result.get('rows', [])
        ]
        self._service_candidate_counts = counts
        self.candidate_table.update_data(data)
        self.logger.info('Candidate table loaded through service: %d rows.', len(data))
        self._update_candidate_counts()
        self._update_selected_candidates_table()

    def _on_candidate_check_changed(self, checked_rows):
        """Sync persistent candidate selection from checkboxes; update selected-candidates table.

        Args:
            checked_rows: List of row dicts currently checked in the candidate table.

        Returns:
            None
        """
        # Add all newly checked; remove all newly unchecked (within this filter)
        for row in checked_rows:
            if 'Internal ID' in row and row.get('Internal ID'):
                self.candidate_table_selected_ids.add(row['Internal ID'])
        # Prune any unchecked IDs visible in current filter
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if repo and hasattr(repo, 'regular_statements'):
            cfilter = self.candidate_search_var.get().strip().lower()
            visible_ids = set()
            invalid_ids = getattr(self, 'invalid_statement_ids', set())
            system_ids = getattr(self, 'system_statement_ids', set())
            for st in repo.regular_statements:
                internal_id = st.get('internal_id', '')
                if (
                    internal_id in self.protected_statement_ids
                    or internal_id in invalid_ids
                    or internal_id in system_ids
                ):
                    continue
                pname = st.get('policy_name', '').lower()
                stxt = st.get('statement_text', '').lower()
                if not cfilter or (cfilter in pname or cfilter in stxt):
                    visible_ids.add(internal_id)
            checked_ids = {
                row.get('Internal ID') for row in checked_rows if 'Internal ID' in row and row.get('Internal ID')
            }
            self.candidate_table_selected_ids.difference_update(visible_ids - checked_ids)
        self._update_selected_candidates_table()

    def _on_candidate_select_all(self, visible_internal_ids, check_state):
        """Select all or clear all visible candidates; update persistent set and tables.

        Args:
            visible_internal_ids: Set or list of internal_ids currently visible (after filter).
            check_state: True to select all, False to clear all visible.

        Returns:
            None
        """
        if check_state:
            self.candidate_table_selected_ids.update(visible_internal_ids)
        else:
            self.candidate_table_selected_ids.difference_update(visible_internal_ids)
        self._load_candidate_statements()
        self._update_selected_candidates_table()

    def _update_selected_candidates_table(self):
        """Refresh the selected-candidates summary table from persistent candidate selection.

        Returns:
            None
        """
        candidate_ids = self.candidate_table_selected_ids
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        records = []
        system_ids = getattr(self, 'system_statement_ids', set())
        if repo and hasattr(repo, 'regular_statements'):
            for st in repo.regular_statements:
                iid = st.get('internal_id', '')
                if iid in candidate_ids and iid not in self.protected_statement_ids and iid not in system_ids:
                    records.append(
                        {
                            'Policy Name': st.get('policy_name', ''),
                            'Statement Text': st.get('statement_text', ''),
                            'Statement Compartment Path': st.get('compartment_path', ''),
                            'Statement Location': st.get('location', ''),
                            'Statement Effective Path': st.get('effective_path', ''),
                            'Principal': st.get('subject_type', ''),
                            'Resource': st.get('resource', ''),
                            'Status': '',
                            'Internal ID': st.get('internal_id', ''),
                        }
                    )
        if hasattr(self, 'selected_candidates_table'):
            self.selected_candidates_table.update_data(records)

    def _update_candidate_counts(self):
        """Update the Protected, Invalid, and System count labels in the candidate tab.

        Returns:
            tuple[int, int, int]: (protected_count, invalid_count, system_count).
        """
        n_prot = len(self.protected_statement_ids) if hasattr(self, 'protected_statement_ids') else 0
        counts = getattr(self, '_service_candidate_counts', {})
        n_inv = int(
            counts.get('invalid', len(self.invalid_statement_ids) if hasattr(self, 'invalid_statement_ids') else 0)
        )
        n_sys = int(
            counts.get('system', len(self.system_statement_ids) if hasattr(self, 'system_statement_ids') else 0)
        )
        if hasattr(self, 'candidate_protected_count'):
            self.candidate_protected_count.config(text=f'Protected: {n_prot}')
        if hasattr(self, 'candidate_invalid_count'):
            self.candidate_invalid_count.config(text=f'Invalid: {n_inv}')
        if hasattr(self, 'candidate_system_count'):
            self.candidate_system_count.config(text=f'System: {n_sys}')
        return n_prot, n_inv, n_sys

    def _on_create_consolidation_proposal(self, selected_rows):
        """Handle Create Consolidation Proposal: use persistent candidate selection, generate plan, show proposal tab.

        Args:
            selected_rows: Unused; selection comes from candidate_table_selected_ids.

        Returns:
            None
        """
        self.logger.info(
            'User triggered: Create Consolidation Proposal. Selected: %d', len(self.candidate_table_selected_ids)
        )
        # Exclude invalid and system (locked policy) statements from consolidation
        invalid_ids = getattr(self, 'invalid_statement_ids', set())
        system_ids = getattr(self, 'system_statement_ids', set())
        self.candidate_statement_ids = set(self.candidate_table_selected_ids) - invalid_ids - system_ids
        # Fire anonymous usage tracking event for consolidation proposal generation.
        try:
            tracker = get_usage_tracker()
            if tracker is not None:
                tracker.track_operation(
                    'consolidation_proposal',
                    selected=len(self.candidate_table_selected_ids),
                    protected=len(self.protected_statement_ids),
                )
        except Exception:
            self.logger.debug('Usage tracking for consolidation_proposal failed', exc_info=True)

        self._on_generate_proposal()
        # Switch to proposal subtab (3rd tab, index 2)
        if hasattr(self, 'notebook'):
            self.notebook.select(2)

    def _update_protected_display(self):
        """No-op: protected statements display box was removed from Candidate Selection subtab."""
        pass

    def _update_selected_statements_table(self):
        """Refresh the selected-statements table in the protection tab from current selection.

        Returns:
            None
        """
        # Compose list from persistent set and full_data
        selected_set = self.protect_table_selected_ids
        id2entry = {row.get('Internal ID', ''): row for row in self.protection_full_data}
        records = []
        for iid in sorted(selected_set):
            entry = id2entry.get(iid)
            if entry:
                records.append(
                    {
                        'Policy Name': entry.get('Policy Name', ''),
                        'Statement Text': entry.get('Statement Text', ''),
                        'Internal ID': iid,
                    }
                )
        if hasattr(self, 'selected_statements_table'):
            self.selected_statements_table.update_data(records)

    def _on_generate_proposal(self):
        """Generate consolidation plan from candidates; save to history and show proposal table/script.

        Uses current strategy and candidate_statement_ids. Plan is stored in canonical history
        with unique effort_id and timestamps. Proposal tab table and script area are updated.

        Returns:
            None
        """
        strategy_name = self.candidate_strategy_var.get() if hasattr(self, 'candidate_strategy_var') else ''
        self.logger.info(
            'User triggered: Generate consolidation proposal from %d candidates (strategy=%s, protected=%d)',
            len(self.candidate_statement_ids),
            strategy_name or '<none>',
            len(self.protected_statement_ids),
        )
        if strategy_name not in (self.service.get_status().get('strategy_names', []) or []):
            self.logger.warning("Strategy '%s' is not registered; aborting proposal generation.", strategy_name)
            try:
                tkmessagebox.showwarning(
                    'Strategy Not Available',
                    f"'{strategy_name}' is not a registered consolidation strategy. "
                    'Choose a strategy from the dropdown and try again.',
                )
            except Exception:
                pass
            return
        try:
            result = self.service.create_proposal(
                candidate_internal_ids=sorted(self.candidate_statement_ids),
                strategy_display_name=strategy_name,
            )
            plan = result['plan']
        except ValueError as e:
            self.logger.warning('Consolidation plan was rejected: %s', e)
            self.plan_status_label.config(text=str(e))
            try:
                tkmessagebox.showerror('Plan cannot be created', str(e))
            except Exception:
                pass
            return
        except Exception as e:
            self.logger.warning('Failed to generate consolidation plan: %s', e)
            self.proposal_table.update_data([])
            self._set_plan_notes_and_skipped_from_plan(None)
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            self.script_text.insert('end', f'(failed to generate plan: {e})')
            self.script_text.config(state='disabled')
            return

        rows = result['rows']
        self.proposal_table.update_data(rows)
        self._set_plan_notes_and_skipped_from_plan(plan)

        # Render script using current format (OCI CLI or UI-based Steps)
        self._set_script_content_from_plan(plan)

        # Visible success feedback so user sees the plan was generated
        num_steps = len(plan.get('plan_steps', []))
        self.plan_status_label.config(
            text=f"Plan generated: {plan.get('plan_id', '?')} — {num_steps} step(s). Select from dropdown to re-open."
        )
        self.logger.info('Consolidation plan generated: %s steps, plan_id=%s', num_steps, plan.get('plan_id'))

        self._refresh_plan_history_dropdown()

    def _on_reload_and_check_progress(self):  # noqa: C901
        """Reload policy/compartment data from tenancy, then re-evaluate selected plan execution progress.

        Only allowed when repo is loaded from tenancy (not cache/compliance). Updates proposal
        table Status column and status label with executed step counts.

        Returns:
            None
        """
        # Ensure we have a selected run in the dropdown
        sel = self.plan_history_var.get()
        if not sel or sel not in getattr(self, 'plan_history_id_lookup', {}):
            tkmessagebox.showwarning(
                'No Plan Selected',
                'Please select a consolidation plan from the dropdown before checking progress.',
            )
            return
        run = self.plan_history_id_lookup[sel]
        plan = run.get('plan')
        if not plan:
            tkmessagebox.showwarning(
                'No Plan Data',
                'The selected history entry does not contain a full plan definition, '
                'so execution progress cannot be checked.',
            )
            return

        # Visible running state to indicate synchronous/long-running work.
        if hasattr(self, 'btn_check_progress'):
            self.btn_check_progress.config(state=tk.DISABLED, text='Reload and Check Progress (Running...)')

        # Guard: only allow reload for live-tenancy policy loads (same constraints as Policies tab)
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if (
            not repo
            or not getattr(repo, 'policies_loaded_from_tenancy', False)
            or getattr(repo, 'loaded_from_compliance_output', False)
        ):
            self.plan_status_label.config(text='Reload skipped (no-op): dataset not loaded live from tenancy.')
            tkmessagebox.showwarning(
                'Not allowed',
                'Execution progress can only be checked for tenancies loaded directly from OCI (not cache/compliance). '
                'Please load from tenancy first.',
            )
            if hasattr(self, 'btn_check_progress'):
                self.btn_check_progress.config(text='Reload and Check Progress')
                self.btn_check_progress['state'] = tk.NORMAL
            return

        # Reload policies/compartments (App coordinates cache update and UI refresh)
        if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache_async'):

            def _after_reload_complete(success: bool, message: str, is_error: bool):
                try:
                    if not success:
                        tkmessagebox.showerror('Reload Failed', message)
                        return
                    self._continue_check_progress_after_reload(run=run, plan=plan)
                finally:
                    if hasattr(self, 'btn_check_progress'):
                        self.btn_check_progress.config(text='Reload and Check Progress')
                        self.btn_check_progress['state'] = tk.NORMAL

            self.app.reload_policies_and_compartments_and_update_cache_async(
                callback={'complete': _after_reload_complete},
                show_popup=True,
            )
            return

        try:
            self.logger.info('Reloading policies/compartments before checking consolidation plan progress.')
            self.configure(cursor='watch')
            self.update_idletasks()
            ok = False
            if hasattr(self.app, 'reload_policies_and_compartments_and_update_cache'):
                ok = self.app.reload_policies_and_compartments_and_update_cache()
            self.configure(cursor='')
            if not ok:
                tkmessagebox.showerror(
                    'Reload Failed',
                    'Policy data reload from tenancy failed. See application logs for details.',
                )
                return
        except Exception as e:
            self.configure(cursor='')
            self.logger.warning('Exception during reload before progress check: %s', e)
            tkmessagebox.showerror('Reload Failed', f'Reload failed due to error: {str(e)}')
            if hasattr(self, 'btn_check_progress'):
                self.btn_check_progress.config(text='Reload and Check Progress')
                self.btn_check_progress['state'] = tk.NORMAL
            return

        try:
            self._continue_check_progress_after_reload(run=run, plan=plan)
        finally:
            if hasattr(self, 'btn_check_progress'):
                self.btn_check_progress.config(text='Reload and Check Progress')
                self.btn_check_progress['state'] = tk.NORMAL

    def _continue_check_progress_after_reload(self, run, plan):
        """Continue plan progress checks once policy reload has completed."""

        # At this point the repo and tags have been refreshed; ask engine to evaluate progress.
        try:
            progress = self.service.evaluate_progress(plan)
        except Exception as e:
            self.logger.warning('Failed to evaluate plan progress: %s', e)
            tkmessagebox.showerror('Check Progress Failed', f'Could not evaluate plan progress: {e}')
            return

        total = len(progress)
        executed = sum(1 for p in progress.values() if p.get('executed'))
        self.logger.info(
            'Consolidation plan progress after reload: executed=%d/%d steps (%s)',
            executed,
            total,
            run.get('consolidation_effort_id', '<unknown>'),
        )

        # If all steps executed, persist plan as completed
        effort_id = run.get('consolidation_effort_id', '')
        if effort_id:
            tenancy_ocid = self._get_tenancy_ocid()
            if tenancy_ocid:
                try:
                    self.service.save_progress(effort_id, progress)
                    self._refresh_plan_history_dropdown()
                    if hasattr(self, 'plan_history_table') and self.plan_history_table:
                        self._refresh_plan_history_table()
                    if total > 0 and executed >= total:
                        self.logger.info('Plan marked as completed: %s', effort_id)
                except Exception as e:
                    self.logger.warning('Failed to mark plan as completed: %s', e)

        # Update status label with execution summary
        base_txt = self.plan_status_label.cget('text') or ''
        suffix = f' | Executed: {executed}/{total} step(s)'
        if total > 0 and executed >= total:
            suffix += ' [Completed]'
        self.plan_status_label.config(text=(base_txt + suffix) if base_txt else suffix)

        # Refresh proposal table so Status column shows Executed/Pending per step
        data = self.service.get_proposal_rows(plan=plan, progress=progress)
        self.proposal_table.update_data(data)

        for step_id, info in progress.items():
            self.logger.debug('Plan step %s progress: %s', step_id, info)
