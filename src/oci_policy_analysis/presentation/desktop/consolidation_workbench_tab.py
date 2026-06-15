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
from datetime import UTC, datetime
from tkinter import ttk
from typing import Any, cast

from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine
from oci_policy_analysis.application.core.models.models_consolidation import (
    ConsolidationPlan,
    ProtectedStatementReference,
    ProtectedStatementSet,
)
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import CheckboxTable, DataTable


# Each instance will have self.logger for timing and info
def get_module_logger():
    return get_logger('ui.consolidation_workbench_tab')


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
        # Engine is instantiated by App; fallback to create one if missing (defensive)
        engine = getattr(self.app, 'consolidation_engine', None)
        if engine and isinstance(engine, ConsolidationEngine):
            self.engine: ConsolidationEngine = engine
        else:
            self.engine = ConsolidationEngine(
                cache_mgr=CacheManager(),
                reference_data_repo=cast(Any, getattr(self.app, 'reference_data_repo', None)),
                policy_repo=cast(Any, getattr(self.app, 'policy_compartment_analysis', None)),
            )
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
        strategy_names = self.engine.get_strategy_display_names() if self.engine else []
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

        # --- Plan notes (editable, left) and Skipped statements (read-only, right) ---
        notes_skipped_frame = ttk.Frame(parent)
        notes_skipped_frame.pack(fill='x', padx=10, pady=(2, 4))

        h_container = ttk.Frame(notes_skipped_frame)
        h_container.pack(fill='both', expand=True)

        # Left: Plan Notes
        notes_lf = ttk.LabelFrame(h_container, text='Plan notes')
        notes_lf.pack(side='left', fill='both', expand=True, padx=(0, 6), pady=(0, 4))
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

        # Right: Skipped Statements
        self.skipped_statements_lf = ttk.LabelFrame(h_container, text='Skipped statements (0)')
        self.skipped_statements_lf.pack(side='left', fill='both', expand=True, padx=(8, 0), pady=(0, 4))
        self.skipped_statements_tree = ttk.Treeview(
            self.skipped_statements_lf,
            columns=('reason', 'statement_snippet'),
            show='headings',
            height=8,
        )
        self.skipped_statements_tree.heading('reason', text='Reason')
        self.skipped_statements_tree.heading('statement_snippet', text='Statement (snippet)')
        self.skipped_statements_tree.column('reason', width=260)
        self.skipped_statements_tree.column('statement_snippet', width=360)
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

        # Plan table: numbered steps, no column sort, row click highlights script; Policy Compartment before Policy Name
        self.proposal_table = DataTable(
            parent,
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
        self.proposal_table.pack(fill='both', expand=True, padx=8, pady=(0, 10))
        self.add_context_help(
            self.proposal_table, 'Proposed consolidation actions, merges, or deletions (history-aware).'
        )

        # Batch/script text + format and section dropdowns
        script_frame = ttk.LabelFrame(parent, text='Proposed Script / Batch Output')
        script_frame.pack(fill='both', expand=True, padx=12, pady=(2, 12))
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
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(tenancy_ocid)
        sorted_hist = sorted(history, key=lambda r: r.get('created_at', ''), reverse=True)
        rows = []
        for run in sorted_hist:
            plan = run.get('plan') or {}
            steps_list = plan.get('plan_steps') or []
            total_steps = len(steps_list)
            step_status = run.get('step_status') or {}
            progress = step_status.get('progress') if isinstance(step_status.get('progress'), dict) else {}
            executed = sum(1 for p in progress.values() if p.get('executed')) if progress else 0
            steps_str = f'{executed}/{total_steps}' if total_steps else '—'
            created = (run.get('created_at') or '')[:19].replace('T', ' ')
            status = run.get('status') or 'in_progress'
            # Validity: for non-completed plans with steps, check if policies are tagged by another plan
            validity = '—'
            if status != 'completed' and plan and steps_list and hasattr(self, 'engine') and self.engine:
                try:
                    conflicts = self.engine.get_plan_tag_conflicts(cast(ConsolidationPlan, plan))
                    validity = f'Conflicted ({len(conflicts)})' if conflicts else 'OK'
                except Exception:
                    validity = '—'
            elif status == 'completed':
                validity = '—'
            rows.append(
                {
                    'Effort ID': run.get('consolidation_effort_id', '—'),
                    'Created': created,
                    'Strategy': run.get('strategy', '—'),
                    'Status': status,
                    'Steps': steps_str,
                    'Validity': validity,
                    'consolidation_effort_id': run.get('consolidation_effort_id', ''),
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
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(tenancy_ocid)
        run = next((r for r in history if r.get('consolidation_effort_id') == effort_id), None)
        if not run:
            detail.insert('end', f'Plan {effort_id} not found in history.')
            detail.config(state='disabled')
            return
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
        if plan and steps and hasattr(self, 'engine') and self.engine:
            try:
                conflicts = self.engine.get_plan_tag_conflicts(cast(ConsolidationPlan, plan))
                if conflicts:
                    for c in conflicts:
                        lines.append(f"  Policy OCID: {c.get('policy_ocid', '')}")
                        lines.append(f"    Current tag: {c.get('current_tag_value', '')}")
                        lines.append(f"    Conflicting plan: {c.get('conflicting_plan_id', '')}")
                else:
                    lines.append('  None.')
            except Exception as e:
                lines.append(f'  (Error: {e})')
                self.logger.debug('Error in conflict analysis: %s', e)
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
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(tenancy_ocid)
        run = next((r for r in history if r.get('consolidation_effort_id') == effort_id), None)
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
        cache_mgr = CacheManager()
        tenancy_ocid = self._get_tenancy_ocid()
        history = cache_mgr.get_history(tenancy_ocid)
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
        if CacheManager().update_run_record(tenancy_ocid, effort_id, {'plan': updated_plan}):
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
        if not plan or not hasattr(self, 'engine'):
            self.script_text.insert('end', '(no plan selected)')
            self.script_text.config(state='disabled')
            return
        fmt = (self.script_format_var.get() or 'OCI CLI').strip()
        show = (self.script_section_var.get() or 'Execution').strip()
        try:
            if fmt == 'UI-based Steps':
                section = 'execution' if show == 'Execution' else ('rollback' if show == 'Rollback' else 'all')
                self.script_text.insert('end', self.engine.render_plan_ui_instructions(plan, section=section))
            else:
                cmd_txt = self.engine.render_plan_commands(plan)
                rollback_txt = self.engine.render_plan_rollback_commands(plan)
                if show == 'Execution':
                    self.script_text.insert('end', cmd_txt)
                elif show == 'Rollback':
                    self.script_text.insert('end', rollback_txt)
                else:
                    self.script_text.insert('end', cmd_txt + '\n\n' + rollback_txt)
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

    def _build_proposal_rows(self, plan=None, progress=None, results_fallback=None):  # noqa: C901
        """Build proposal table rows from plan steps or legacy results.

        Each row has #, Action, Policy Compartment, Policy Name, Effective Path, Details, Status,
        and step_id (for script highlight on selection). If plan is set, Status comes from
        progress dict; if results_fallback is set (no plan), Status is "—".

        Args:
            plan: Optional ConsolidationPlan; if present, rows built from plan_steps.
            progress: Optional dict step_id -> {executed}; used to set Status (Executed/Pending).
            results_fallback: Optional list of legacy result rows when plan is missing.

        Returns:
            list[dict]: List of row dicts for the proposal DataTable.
        """
        if plan and plan.get('plan_steps'):
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            policies_by_ocid = {p.get('policy_ocid'): p for p in getattr(repo, 'policies', []) or []} if repo else {}
            compartments = getattr(repo, 'compartments', []) or [] if repo else []
            comp_by_id = {c.get('id'): c for c in compartments if c.get('id')}

            def _policy_compartment_path(policy):
                path = (policy.get('compartment_path') or '').strip()
                if path:
                    return path
                coid = policy.get('compartment_ocid')
                if coid and coid in comp_by_id:
                    return (comp_by_id[coid].get('hierarchy_path') or '').strip()
                return ''

            rows = []
            for i, step in enumerate(plan['plan_steps'], 1):
                action_key = step.get('action') or ''
                if action_key == 'add':
                    # Use correct compartment path if available, otherwise fallback to compartment OCID, otherwise ROOT
                    comp_obj = (
                        comp_by_id.get(step.get('compartment_ocid', ''), {}) if step.get('compartment_ocid', '') else {}
                    )
                    policy_compartment = (
                        comp_obj.get('hierarchy_path')
                        or comp_obj.get('name')
                        or step.get('compartment_ocid', '')
                        or 'ROOT'
                    )
                    pol_name = (step.get('create_policy_name') or 'Consolidated-Root') + ' (suggested)'
                    effective_path = policy_compartment
                    n_stmts = len(step.get('after_statements', []))
                    details = f'New Policy with {n_stmts} statements and updated location'
                else:
                    pol = policies_by_ocid.get(step.get('policy_ocid', ''), {}) or {}
                    # For delete steps, retain compartment/name from plan when policy is gone (already deleted)
                    if action_key == 'delete' and not pol:
                        policy_compartment = (
                            (
                                (comp_by_id.get(step.get('compartment_ocid'), {}) or {}).get('hierarchy_path') or ''
                            ).strip()
                            or step.get('compartment_ocid')
                            or ''
                        )
                        pol_name = (step.get('create_policy_name') or '(unknown policy)') + ' (deleted)'
                        effective_path = policy_compartment
                    else:
                        pol_name = pol.get('policy_name', '(unknown policy)')
                        policy_compartment = _policy_compartment_path(pol)
                        effective_path = policy_compartment
                    details = ''
                    if action_key == 'modify':
                        details = f"Statements: {len(step.get('before_statements', []))} -> {len(step.get('after_statements', []))}"
                    elif action_key == 'delete':
                        details = f"Delete policy (rollback recreates with {len(step.get('before_statements', []))} statements)"
                action = (action_key or '').upper()
                status = 'Pending'
                if progress and isinstance(progress, dict):
                    pi = progress.get(step.get('step_id'), {})
                    status = 'Executed' if pi.get('executed') else 'Pending'
                rows.append(
                    {
                        '#': i,
                        'Action': action,
                        'Policy Compartment': policy_compartment,
                        'Policy Name': pol_name,
                        'Effective Path': effective_path,
                        'Details': details,
                        'Status': status,
                        'step_id': step.get('step_id', ''),
                    }
                )
            return rows
        if results_fallback:
            rows = []
            for i, r in enumerate(results_fallback, 1):
                rows.append(
                    {
                        '#': r.get('index', r.get('#', i)),
                        'Action': r.get('action', r.get('Action', '')),
                        'Policy Compartment': r.get('policy_compartment', r.get('Policy Compartment', '')),
                        'Policy Name': r.get('policy_name', r.get('Policy Name', '')),
                        'Effective Path': r.get('Effective Path', ''),
                        'Details': r.get('details', r.get('Details', '')),
                        'Status': r.get('status', r.get('Status', '—')),
                        'step_id': r.get('step_id', ''),
                    }
                )
            return rows
        return []

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
            if progress is None and hasattr(self, 'engine') and self.engine:
                try:
                    progress = self.engine.check_plan_progress(plan)
                except Exception as e:
                    self.logger.debug('Could not check plan progress: %s', e)
            data = self._build_proposal_rows(plan=plan, progress=progress)
            self._set_plan_notes_and_skipped_from_plan(plan)
        else:
            data = self._build_proposal_rows(results_fallback=run.get('results', []))
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
        self.logger.info('Loading all policies and statements for the protection tab.')
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        tenancy_ocid = getattr(self.app, 'tenancy_ocid', None)
        # Robustness: If not present, try to get from repo (after cache load this is set)
        if not tenancy_ocid:
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            if repo and hasattr(repo, 'tenancy_ocid'):
                tenancy_ocid = getattr(repo, 'tenancy_ocid', None)
        cache_mgr = CacheManager()
        data = []
        # Load available statements for display/search
        if repo and hasattr(repo, 'regular_statements'):
            for st in repo.regular_statements:
                entry = {
                    'Policy Name': st.get('policy_name', ''),
                    'Statement Text': st.get('statement_text', ''),
                    'Location': st.get('location', ''),
                    'Compartment': st.get('effective_path', ''),
                    'Principal': st.get('subject_type', ''),
                    'Internal ID': st.get('internal_id', ''),
                    'Policy OCID': st.get('policy_ocid', ''),
                }
                self.logger.debug('Loaded statement: %s', entry)
                data.append(entry)
        self.protection_full_data = data
        self.logger.info('Protection browser data loaded with %d statements.', len(data))

        # Load protected_set (if any) and restore protection UI state from canonical cache
        try:
            protected_set = cache_mgr.get_protected_set(tenancy_ocid)
            if protected_set and 'protected' in protected_set:
                ids = {ref.get('internal_id') for ref in protected_set['protected'] if ref.get('internal_id')}
                self.protected_statement_ids = set(ids)
                self.protect_table_selected_ids = set(ids)
                # Info log with tenancy, debug with IDs
                self.logger.info(f'Restored protected set from state for tenancy ${tenancy_ocid}')
                self.logger.debug('Restored protected internal_ids: %s', ids)
                self.logger.debug(
                    'Policy statements available at load: %s',
                    [entry.get('Internal ID', '') for entry in self.protection_full_data],
                )
            else:
                self.protected_statement_ids = set()
                self.protect_table_selected_ids = set()
                self.logger.info('No existing protected set found for tenancy %s; started fresh.', tenancy_ocid)
        except Exception as e:
            self.logger.warning('Failed to load protected set for tenancy %s: %s', tenancy_ocid, e)
            self.protected_statement_ids = set()
            self.protect_table_selected_ids = set()
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

        # --- Store protected_set in canonical per-tenancy consolidation state file ---
        protected_list = []
        seen_ids = set()
        for entry in self.protection_full_data:
            iid = entry.get('Internal ID')
            if iid in self.protect_table_selected_ids and iid not in seen_ids:
                ref: ProtectedStatementReference = {
                    'internal_id': iid,
                    'policy_ocid': entry.get('Policy OCID', ''),
                    'policy_name': entry.get('Policy Name', ''),
                    'statement_text': entry.get('Statement Text', ''),
                }
                protected_list.append(ref)
                seen_ids.add(iid)
            elif iid in self.protect_table_selected_ids:
                self.logger.debug('Duplicate internal_id in protection set, skipping: %s', iid)
        # At this point, tenancy_ocid may have been resolved below
        cache_mgr = CacheManager()
        tenancy_ocid = getattr(self.app, 'tenancy_ocid', None)
        # Defensive: Try to resolve tenancy_ocid from loaded repo if missing
        if not tenancy_ocid:
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            if repo and hasattr(repo, 'tenancy_ocid'):
                tenancy_ocid = getattr(repo, 'tenancy_ocid', None)

        if not tenancy_ocid:
            self.logger.warning('No valid tenancy_ocid available; cannot persist protected set. Action skipped.')
        else:
            protected_set: ProtectedStatementSet = {
                'tenancy_ocid': tenancy_ocid,
                'protected': protected_list,
            }
            cache_mgr.set_protected_set(tenancy_ocid, cast(dict[str, Any], protected_set))
            self.logger.info('Saved ProtectedStatementSet to canonical state file for tenancy %s.', tenancy_ocid)

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
        self.logger.info('Loading candidate statement data (excluding protected and invalid).')
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if not repo or not hasattr(repo, 'regular_statements'):
            self.invalid_statement_ids = set()
            self.system_statement_ids = set()
            self.candidate_table.update_data([])
            if hasattr(self, 'selected_candidates_table'):
                self.selected_candidates_table.update_data([])
            self._update_candidate_counts()
            return
        # Statements with invalid_reasons are omitted from consolidation entirely
        self.invalid_statement_ids = {
            st.get('internal_id')
            for st in repo.regular_statements
            if st.get('internal_id') and st.get('invalid_reasons')
        }
        # Statements in locked/system policy (e.g. Tenant Admin Policy) are omitted
        self.system_statement_ids = {
            st.get('internal_id')
            for st in repo.regular_statements
            if st.get('internal_id') and (st.get('policy_name') or '').strip() == LOCKED_POLICY_NAME
        }
        # Log the invalid and system statement IDs for debugging
        self.logger.info(
            'Identified %d invalid statements and %d system statements to exclude from candidates.',
            len(self.invalid_statement_ids),
            len(self.system_statement_ids),
        )
        self.logger.debug('Invalid statement internal_ids: %s', self.invalid_statement_ids)
        self.logger.debug('System statement internal_ids: %s', self.system_statement_ids)
        cfilter = self.candidate_search_var.get().strip().lower()
        self.logger.info("Candidate search filter applied: '%s'", cfilter)

        # STEP 1: build filtered data
        t0 = time.perf_counter()
        data = []
        for st in repo.regular_statements:
            internal_id = st.get('internal_id', '')
            if internal_id in self.protected_statement_ids:
                continue
            if internal_id in self.invalid_statement_ids:
                continue
            if internal_id in self.system_statement_ids:
                continue
            pname = st.get('policy_name', '').lower()
            stxt = st.get('statement_text', '').lower()
            if not cfilter or (cfilter in pname or cfilter in stxt):
                entry = {
                    'Policy Name': st.get('policy_name', ''),
                    'Statement Text': st.get('statement_text', ''),
                    'Statement Compartment Path': st.get('compartment_path', ''),
                    'Statement Location': st.get('location', ''),
                    'Statement Effective Path': st.get('effective_path', ''),
                    'Principal': st.get('subject_type', ''),
                    'Resource': st.get('resource', ''),
                    'Internal ID': internal_id,
                }
                data.append(entry)
        t1 = time.perf_counter()
        self.logger.info('Candidate statements loaded: %d after filtering. [Build loop took %.4fs]', len(data), t1 - t0)

        # STEP 2: checked assignment for UI
        t2 = time.perf_counter()
        for row in data:
            row['checked'] = row.get('Internal ID', '') in self.candidate_table_selected_ids
        t3 = time.perf_counter()
        self.logger.info('Checked flag assignment for %d rows took %.4fs', len(data), t3 - t2)

        # STEP 3: UI update
        t4 = time.perf_counter()
        self.candidate_table.update_data(data)
        t5 = time.perf_counter()
        self.logger.info('candidate_table.update_data() took %.4fs for %d rows', t5 - t4, len(data))
        self.logger.info(
            'Candidate table loaded: %d candidates (excluding %d protected, %d invalid, %d system).',
            len(data),
            len(self.protected_statement_ids),
            len(self.invalid_statement_ids),
            len(self.system_statement_ids),
        )
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
        n_inv = len(self.invalid_statement_ids) if hasattr(self, 'invalid_statement_ids') else 0
        n_sys = len(self.system_statement_ids) if hasattr(self, 'system_statement_ids') else 0
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
        if strategy_name not in (self.engine.get_strategy_display_names() or []):
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
        # Move to Root Compartment: OCI allows max 50 statements per policy
        if strategy_name == 'Move to Root Compartment' and len(self.candidate_statement_ids) > 50:
            try:
                tkmessagebox.showerror(
                    'Too Many Statements',
                    'Move to Root Compartment allows at most 50 policy statements. '
                    f'You have selected {len(self.candidate_statement_ids)}. Please reduce the selection.',
                )
            except Exception:
                pass
            return
        try:
            plan = self.engine.generate_plan(
                candidate_internal_ids=set(self.candidate_statement_ids),
                protected_internal_ids=set(self.protected_statement_ids),
                strategy_display_name=strategy_name,
                params={'marker_tag_key': 'opa_consolidation'},
            )
        except Exception as e:
            self.logger.warning('Failed to generate consolidation plan: %s', e)
            self.proposal_table.update_data([])
            self._set_plan_notes_and_skipped_from_plan(None)
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            self.script_text.insert('end', f'(failed to generate plan: {e})')
            self.script_text.config(state='disabled')
            return

        rows = self._build_proposal_rows(plan=plan, progress=None)
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

        # Persist plan/run to canonical plan history; only refresh dropdown if save succeeded (otherwise we would wipe the UI)
        tenancy_ocid = self._get_tenancy_ocid()
        if not tenancy_ocid:
            self.logger.warning(
                'No tenancy_ocid available; plan not saved to history. Plan is still shown in table and script.'
            )
            try:
                tkmessagebox.showwarning(
                    'Plan not saved to history',
                    'Tenancy OCID is missing, so this plan could not be added to the dropdown. '
                    'The plan and script are shown below. Reload from tenancy or load a cache that sets tenancy to save plans.',
                )
            except Exception:
                pass
            return
        try:
            dt_now = datetime.now(UTC)
            run_record = {
                'consolidation_effort_id': plan.get('plan_id', '<unknown>'),
                'created_at': dt_now.isoformat(),
                'status': 'in_progress',  # updated to "completed" when all steps executed
                'candidate_statements': list(self.candidate_statement_ids),
                'strategy': plan.get('plan_tags', {}).get('strategy_id', ''),
                'step_status': {
                    'proposal': {
                        'status': 'completed',
                        'generated_at': dt_now.isoformat(),
                    }
                },
                'results': rows,
                'plan': plan,  # full plan for re-display and progress check
            }
            cache_mgr = CacheManager()
            cache_mgr.add_run_record(tenancy_ocid, run_record)
            self._refresh_plan_history_dropdown()
            self.logger.info('Consolidation run saved to history for tenancy_ocid=%s', tenancy_ocid)
        except Exception as e:
            self.logger.warning('Failed to persist consolidation proposal/run: %s', e)
            try:
                tkmessagebox.showwarning(
                    'Plan not saved to history',
                    f'Plan was generated ({num_steps} steps) but could not be saved to the history list: {e}. '
                    'The plan and script below are still valid; use Reload and Check Progress only after loading from tenancy.',
                )
            except Exception:
                pass

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
            progress = self.engine.check_plan_progress(plan)
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
                    cache_mgr = CacheManager()
                    updated_rows = self._build_proposal_rows(plan=plan, progress=progress)
                    updates = {
                        'step_status': {**run.get('step_status', {}), 'progress': progress},
                        'results': updated_rows,
                    }
                    if total > 0 and executed >= total:
                        updates['status'] = 'completed'
                        updates['completed_at'] = datetime.now(UTC).isoformat()
                    cache_mgr.update_run_record(
                        tenancy_ocid,
                        effort_id,
                        updates,
                    )
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
        data = self._build_proposal_rows(plan=plan, progress=progress)
        self.proposal_table.update_data(data)

        for step_id, info in progress.items():
            self.logger.debug('Plan step %s progress: %s', step_id, info)
