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

import tkinter as tk
import tkinter.messagebox as tkmessagebox
from datetime import UTC, datetime
from tkinter import ttk

from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models_consolidation import ProtectedStatementReference, ProtectedStatementSet
from oci_policy_analysis.logic.consolidation_engine import ConsolidationEngine
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import CheckboxTable, DataTable

logger = get_logger('consolidation_workbench_tab')

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
        logger.info('Initializing ConsolidationWorkbenchTab')
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
                reference_data_repo=getattr(self.app, 'reference_data_repo', None),
                policy_repo=getattr(self.app, 'policy_compartment_analysis', None),
            )
        self.protected_statement_ids = set()
        self.candidate_statement_ids = set()
        self.protect_table_selected_ids = set()  # Persist selection as Internal IDs

        self.protection_full_data = []  # stores unfiltered data for search
        self._build_notebook_ui()

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
        logger.info('Validating protected set after policy data reload.')
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if not repo or not hasattr(repo, 'regular_statements'):
            logger.warning('No policy_compartment_analysis or regular_statements found for validation.')
            return

        # Build set of current valid internal_ids
        current_ids = {st.get('internal_id', '') for st in repo.regular_statements if st.get('internal_id', '')}
        before_count = len(self.protected_statement_ids)
        missing_ids = {iid for iid in self.protected_statement_ids if iid not in current_ids}

        for iid in sorted(missing_ids):
            logger.warning(
                f"Protected statement with internal_id '{iid}' no longer exists in current policy data (was removed or updated). It will be unprotected."
            )

        changed = False
        if missing_ids:
            self.protected_statement_ids.difference_update(missing_ids)
            self.protect_table_selected_ids.difference_update(missing_ids)
            changed = True

        if changed:
            logger.info('Updating UI after removed protected statements: %s', missing_ids)

        # Always refresh both subtabs so data reflects current repo after any reload
        self._refresh_filter_protect_table()
        self._update_selected_statements_table()
        self._update_protected_display()
        self._load_candidate_statements()

        after_count = len(self.protected_statement_ids)
        logger.info(
            f'Protection set validated after reload. {before_count - after_count} missing internal_id(s) removed; {after_count} protected remain.'
        )

    def refresh_plan_history_for_corpus(self):
        """
        Refresh the plan list for the current tenancy/corpus in the Proposal dropdown and Plan History tab.

        Call after any load (tenancy, cache, or compliance) so all plans tied to this corpus_id
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
                'Statement Text': 320,
                'Internal ID': 90,
            },
            height=5,
        )
        self.selected_statements_table.pack(fill='x', expand=False, padx=2, pady=(12, 3))
        self.add_context_help(
            self.selected_statements_table, 'Current set of protected statements (always visible, display-only).'
        )

        # Load initial data
        self.load_policies_and_statements()

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
                'Protected policies/statements are listed below, and cannot be selected for consolidation.'
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

        # Protected count label + help
        self.candidate_protected_count = ttk.Label(strat_row, text='Protected: 0')
        self.candidate_protected_count.pack(side='left', padx=(10, 1))
        self.add_context_help(
            self.candidate_protected_count,
            'Protected statements are not shown as candidates. To edit them, use the Statement/Protection tab.',
        )

        # Candidate table (with checkboxes)
        self.candidate_table_selected_ids = set()  # persistent selection
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

        # Protected statements/IDs (readonly, current state)
        ttk.Label(outer, text='Protected Statements (currently excluded):').pack(anchor='w', padx=16, pady=(8, 0))
        self.protected_display_list = tk.Text(outer, height=4, width=150, wrap='word', state='disabled')
        self.protected_display_list.pack(fill='x', padx=16, pady=(0, 8))
        self.add_context_help(
            self.protected_display_list, 'List of internal_ids (or names/text) of currently protected statements.'
        )

        # Load initial candidates and protected display
        self._load_candidate_statements()
        self._update_selected_candidates_table()
        self._update_protected_display()

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
        corpus_id = self._get_corpus_id()
        if not corpus_id:
            self.plan_history_table.update_data([])
            return
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(corpus_id)
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
                    conflicts = self.engine.get_plan_tag_conflicts(plan)
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
        corpus_id = self._get_corpus_id()
        if not corpus_id:
            detail.insert('end', 'No corpus/tenancy loaded.')
            detail.config(state='disabled')
            return
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(corpus_id)
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
                conflicts = self.engine.get_plan_tag_conflicts(plan)
                if conflicts:
                    for c in conflicts:
                        lines.append(f"  Policy OCID: {c.get('policy_ocid', '')}")
                        lines.append(f"    Current tag: {c.get('current_tag_value', '')}")
                        lines.append(f"    Conflicting plan: {c.get('conflicting_plan_id', '')}")
                else:
                    lines.append('  None.')
            except Exception as e:
                lines.append(f'  (Error: {e})')
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
        corpus_id = self._get_corpus_id()
        if not corpus_id:
            return
        cache_mgr = CacheManager()
        history = cache_mgr.get_history(corpus_id)
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

    def _get_corpus_id(self):
        """Resolve corpus/tenancy id for consolidation state from app or repo.

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

        Uses corpus_id from app or policy_compartment_analysis so history is found for
        cache-loaded tenancies. Most recent run is selected by default.

        Returns:
            None
        """
        cache_mgr = CacheManager()
        tenancy_ocid = self._get_corpus_id()
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
            logger.warning('Failed to render script for plan: %s', e)
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
                    policy_compartment = 'ROOT'
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
                        '#': i,
                        'Action': r.get('Action', ''),
                        'Policy Compartment': r.get('Policy Compartment', ''),
                        'Policy Name': r.get('Policy Name', ''),
                        'Effective Path': r.get('Effective Path', ''),
                        'Details': r.get('Details', ''),
                        'Status': r.get('Status', '—'),
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
        if run.get('step_status'):
            latest_step = list(run['step_status'].items())[-1]
            txt.append(
                f"Latest step: {latest_step[0]} [{latest_step[1].get('status')}] at {latest_step[1].get('generated_at', '')}"
            )
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
                    logger.debug('Could not check plan progress: %s', e)
            data = self._build_proposal_rows(plan=plan, progress=progress)
        else:
            data = self._build_proposal_rows(results_fallback=run.get('results', []))
        self.proposal_table.update_data(data)
        # Render script from plan (CLI or UI per format dropdown)
        if plan:
            self._set_script_content_from_plan(plan)
        else:
            self._last_plan_for_script = None
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            script_out = '\n'.join([f"-- Plan step: {r.get('Policy Name','?')}" for r in data])
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
        # Determine set of visible IDs
        pfilter = self.policy_search_var.get().strip().lower()
        sfilter = self.statement_search_var.get().strip().lower()
        visible_ids = []
        for d in self.protection_full_data:
            pname = d['Policy Name'].lower() if d['Policy Name'] else ''
            stxt = d['Statement Text'].lower() if d['Statement Text'] else ''
            if (not pfilter or pfilter in pname) and (not sfilter or sfilter in stxt):
                if d.get('Internal ID', ''):
                    visible_ids.append(d['Internal ID'])
        # If the count of checked in current filter increased, it was a check; otherwise an uncheck.
        checked_previously = [iid for iid in visible_ids if iid in self.protect_table_selected_ids]
        # Find IDs newly checked
        newly_checked = set(checked_ids) - set(checked_previously)
        newly_unchecked = set(checked_previously) - set(checked_ids)
        # Only change single affected row
        for iid in newly_checked:
            self.protect_table_selected_ids.add(iid)
        for iid in newly_unchecked:
            self.protect_table_selected_ids.discard(iid)
        self._update_selected_statements_table()

    def _on_protect_select_all(self, visible_internal_ids, check_state):
        """Apply select-all or clear-all for visible rows; update persistent set and table.

        Args:
            visible_internal_ids: Set or list of internal_ids currently visible (after filter).
            check_state: True to select all, False to clear all visible.

        Returns:
            None
        """
        if check_state:
            self.protect_table_selected_ids.update(visible_internal_ids)
        else:
            self.protect_table_selected_ids.difference_update(visible_internal_ids)
        self._refresh_filter_protect_table()
        self._update_selected_statements_table()

    def load_policies_and_statements(self):
        """
        Load all policies and statements for the protection tab and restore protected set.

        Populates the protection table from the bound policy repository (app.policy_compartment_analysis).
        Loads the current protected statement set from the canonical consolidation state file for
        this tenancy/corpus and restores checkboxes and protected display. Call after tenancy or
        cache load so the workbench reflects current data.

        Returns:
            None
        """
        logger.info('Loading all policies and statements for the protection tab.')
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
                logger.debug('Loaded statement: %s', entry)
                data.append(entry)
        self.protection_full_data = data
        logger.info('Protection browser data loaded with %d statements.', len(data))

        # Load protected_set (if any) and restore protection UI state from canonical cache
        try:
            protected_set = cache_mgr.get_protected_set(tenancy_ocid)
            if protected_set and 'protected' in protected_set:
                ids = {ref.get('internal_id') for ref in protected_set['protected'] if ref.get('internal_id')}
                self.protected_statement_ids = set(ids)
                self.protect_table_selected_ids = set(ids)
                # Info log with tenancy, debug with IDs
                logger.info(f'Restored protected set from state for tenancy ${tenancy_ocid}')
                logger.debug('Restored protected internal_ids: %s', ids)
                logger.debug(
                    'Policy statements available at load: %s',
                    [entry.get('Internal ID', '') for entry in self.protection_full_data],
                )
            else:
                self.protected_statement_ids = set()
                self.protect_table_selected_ids = set()
                logger.info('No existing protected set found for tenancy %s; started fresh.', tenancy_ocid)
        except Exception as e:
            logger.warning('Failed to load protected set for tenancy %s: %s', tenancy_ocid, e)
            self.protected_statement_ids = set()
            self.protect_table_selected_ids = set()
        self._refresh_filter_protect_table()
        self._update_selected_statements_table()

    def _refresh_filter_protect_table(self):
        """Apply policy/statement search filters and refresh protection table; keep checkbox state.

        Returns:
            None
        """
        pfilter = self.policy_search_var.get().strip().lower()
        sfilter = self.statement_search_var.get().strip().lower()
        logger.debug(
            "Refreshing filter for protection table with policy filter '%s', statement filter '%s'.", pfilter, sfilter
        )
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
                logger.debug('Filtering result: %s', d_checked)
        self.protect_table.update_data(filtered)
        self._update_selected_statements_table()
        logger.debug('Protection table filtered: now shows %d statements.', len(filtered))

    def _on_mark_as_protected(self, selected_rows):
        """Set protected statements from current selection; persist to cache and refresh UI.

        Args:
            selected_rows: List of selected row dicts (must include "Internal ID").

        Returns:
            None
        """
        logger.info('Marking selected statements as protected from protection tab. Row count: %d', len(selected_rows))
        selected_ids = set()
        for row in selected_rows:
            if 'Internal ID' in row and row['Internal ID']:
                selected_ids.add(row['Internal ID'])
                logger.debug('Protecting statement with Internal ID: %s', row['Internal ID'])
            else:
                logger.warning("Row missing 'Internal ID', skipped: %s", row)
        self.protected_statement_ids = selected_ids
        self.protect_table_selected_ids = set(selected_ids)  # Persist current checked Internal IDs
        logger.debug('Protected statement IDs set to: %s', self.protected_statement_ids)

        # --- NEW: Store protected_set in canonical per-corpus consolidation state file ---
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
                logger.debug('Duplicate internal_id in protection set, skipping: %s', iid)
        # At this point, tenancy_ocid may have been resolved below
        cache_mgr = CacheManager()
        tenancy_ocid = getattr(self.app, 'tenancy_ocid', None)
        # Defensive: Try to resolve tenancy_ocid from loaded repo if missing
        if not tenancy_ocid:
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            if repo and hasattr(repo, 'tenancy_ocid'):
                tenancy_ocid = getattr(repo, 'tenancy_ocid', None)

        if not tenancy_ocid:
            logger.warning('No valid tenancy_ocid/corpus_id available; cannot persist protected set. Action skipped.')
        else:
            protected_set: ProtectedStatementSet = {
                'corpus_id': tenancy_ocid,
                'protected': protected_list,
            }
            cache_mgr.set_protected_set(tenancy_ocid, protected_set)
            logger.info('Saved ProtectedStatementSet to canonical state file for tenancy %s.', tenancy_ocid)

        self._update_protected_display()
        logger.debug('Protected display updated after protecting statements.')
        self._load_candidate_statements()
        logger.debug('Candidate statements reloaded after protecting statements.')
        self._update_selected_statements_table()

    def _on_save_and_go_to_candidates(self, selected_rows):
        """Save protected statements from the protection table and switch to the Candidate Selection subtab."""
        self._on_mark_as_protected(selected_rows)
        if hasattr(self, 'notebook'):
            self.notebook.select(1)  # Candidate Selection & Strategy

    def _load_candidate_statements(self):
        """Load candidate table: all non-protected statements, optionally filtered by search text.

        Returns:
            None
        """
        logger.debug('Loading candidate statement data (excluding protected).')
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if not repo or not hasattr(repo, 'regular_statements'):
            self.candidate_table.update_data([])
            if hasattr(self, 'selected_candidates_table'):
                self.selected_candidates_table.update_data([])
            return
        cfilter = self.candidate_search_var.get().strip().lower()
        logger.debug("Candidate search filter applied: '%s'", cfilter)
        data = []
        for st in repo.regular_statements:
            internal_id = st.get('internal_id', '')
            # Skip protected
            if internal_id in self.protected_statement_ids:
                logger.debug('Skipping candidate (protected): %s', internal_id)
                continue
            # Apply filter
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
                logger.debug('Candidate statement loaded: %s', entry)
                data.append(entry)
        # Mark as checked if in persistent candidate selection set
        for row in data:
            row['checked'] = row.get('Internal ID', '') in self.candidate_table_selected_ids
        self.candidate_table.update_data(data)
        excluded = len(self.protected_statement_ids)
        logger.info(
            'Candidate table loaded: %d candidates (excluding %d protected).',
            len(data),
            excluded,
        )
        self._update_candidate_protected_count()
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
            for st in repo.regular_statements:
                internal_id = st.get('internal_id', '')
                if internal_id in self.protected_statement_ids:
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
        if repo and hasattr(repo, 'regular_statements'):
            for st in repo.regular_statements:
                if (
                    st.get('internal_id', '') in candidate_ids
                    and st.get('internal_id', '') not in self.protected_statement_ids
                ):
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

    def _update_candidate_protected_count(self):
        """Update the protected-count label in the candidate tab.

        Returns:
            int: Number of protected statements.
        """
        n = len(self.protected_statement_ids) if hasattr(self, 'protected_statement_ids') else 0
        if hasattr(self, 'candidate_protected_count'):
            self.candidate_protected_count.config(text=f'Protected: {n}')
        return n

    def _on_create_consolidation_proposal(self, selected_rows):
        """Handle Create Consolidation Proposal: use persistent candidate selection, generate plan, show proposal tab.

        Args:
            selected_rows: Unused; selection comes from candidate_table_selected_ids.

        Returns:
            None
        """
        logger.info(
            'User triggered: Create Consolidation Proposal. Selected: %d', len(self.candidate_table_selected_ids)
        )
        self.candidate_statement_ids = set(self.candidate_table_selected_ids)
        self._on_generate_proposal()
        # Switch to proposal subtab (3rd tab, index 2)
        if hasattr(self, 'notebook'):
            self.notebook.select(2)

    def _update_protected_display(self):
        """Refresh the readonly protected-statements list (IDs and text) in the candidate tab.

        Returns:
            None
        """
        try:
            self.protected_display_list.config(state='normal')
            self.protected_display_list.delete(1.0, 'end')
            if not self.protected_statement_ids:
                self.protected_display_list.insert('end', '(none)')
            else:
                # Build a mapping Internal ID -> statement_text
                id2text = {}
                for entry in self.protection_full_data:
                    internal_id = entry.get('Internal ID')
                    text = entry.get('Statement Text', '')
                    if internal_id:
                        id2text[internal_id] = text
                items = []
                for pid in sorted(self.protected_statement_ids):
                    txt = id2text.get(pid, '(not found)')
                    items.append(f'{pid}: "{txt}"')
                self.protected_display_list.insert('end', '\n'.join(items))
            self.protected_display_list.config(state='disabled')
        except Exception as e:
            logger.warning(f'Protected display update failed: {e}')

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
        logger.info(
            'User triggered: Generate consolidation proposal from %d candidates (strategy=%s, protected=%d)',
            len(self.candidate_statement_ids),
            self.candidate_strategy_var.get() if hasattr(self, 'candidate_strategy_var') else '<none>',
            len(self.protected_statement_ids),
        )
        strategy_name = self.candidate_strategy_var.get() if hasattr(self, 'candidate_strategy_var') else ''
        if strategy_name not in (self.engine.get_strategy_display_names() or []):
            logger.warning("Strategy '%s' is not registered; aborting proposal generation.", strategy_name)
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
            logger.warning('Failed to generate consolidation plan: %s', e)
            self.proposal_table.update_data([])
            self.script_text.config(state='normal')
            self.script_text.delete(1.0, 'end')
            self.script_text.insert('end', f'(failed to generate plan: {e})')
            self.script_text.config(state='disabled')
            return

        rows = self._build_proposal_rows(plan=plan, progress=None)
        self.proposal_table.update_data(rows)

        # Render script using current format (OCI CLI or UI-based Steps)
        self._set_script_content_from_plan(plan)

        # Visible success feedback so user sees the plan was generated
        num_steps = len(plan.get('plan_steps', []))
        self.plan_status_label.config(
            text=f"Plan generated: {plan.get('plan_id', '?')} — {num_steps} step(s). Select from dropdown to re-open."
        )
        logger.info('Consolidation plan generated: %s steps, plan_id=%s', num_steps, plan.get('plan_id'))

        # Persist plan/run to canonical plan history; only refresh dropdown if save succeeded (otherwise we would wipe the UI)
        corpus_id = self._get_corpus_id()
        if not corpus_id:
            logger.warning(
                'No corpus_id (tenancy_ocid) available; plan not saved to history. Plan is still shown in table and script.'
            )
            try:
                tkmessagebox.showwarning(
                    'Plan not saved to history',
                    'Tenancy/corpus id is missing, so this plan could not be added to the dropdown. '
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
            cache_mgr.add_run_record(corpus_id, run_record)
            self._refresh_plan_history_dropdown()
            logger.info('Consolidation run saved to history for corpus_id=%s', corpus_id)
        except Exception as e:
            logger.warning('Failed to persist consolidation proposal/run: %s', e)
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

        # Guard: only allow reload for live-tenancy policy loads (same constraints as Policies tab)
        repo = getattr(self.app, 'policy_compartment_analysis', None)
        if (
            not repo
            or not getattr(repo, 'policies_loaded_from_tenancy', False)
            or getattr(repo, 'loaded_from_compliance_output', False)
        ):
            tkmessagebox.showwarning(
                'Not allowed',
                'Execution progress can only be checked for tenancies loaded directly from OCI (not cache/compliance). '
                'Please load from tenancy first.',
            )
            return

        # Reload policies/compartments (App coordinates cache update and UI refresh)
        try:
            logger.info('Reloading policies/compartments before checking consolidation plan progress.')
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
            logger.warning('Exception during reload before progress check: %s', e)
            tkmessagebox.showerror('Reload Failed', f'Reload failed due to error: {str(e)}')
            return

        # At this point the repo and tags have been refreshed; ask engine to evaluate progress.
        try:
            progress = self.engine.check_plan_progress(plan)
        except Exception as e:
            logger.warning('Failed to evaluate plan progress: %s', e)
            tkmessagebox.showerror('Check Progress Failed', f'Could not evaluate plan progress: {e}')
            return

        total = len(progress)
        executed = sum(1 for p in progress.values() if p.get('executed'))
        logger.info(
            'Consolidation plan progress after reload: executed=%d/%d steps (%s)',
            executed,
            total,
            run.get('consolidation_effort_id', '<unknown>'),
        )

        # If all steps executed, persist plan as completed
        effort_id = run.get('consolidation_effort_id', '')
        if total > 0 and executed >= total and effort_id:
            corpus_id = self._get_corpus_id()
            if corpus_id:
                try:
                    cache_mgr = CacheManager()
                    cache_mgr.update_run_record(
                        corpus_id,
                        effort_id,
                        {
                            'status': 'completed',
                            'step_status': {**run.get('step_status', {}), 'progress': progress},
                            'completed_at': datetime.now(UTC).isoformat(),
                        },
                    )
                    self._refresh_plan_history_dropdown()
                    if hasattr(self, 'plan_history_table') and self.plan_history_table:
                        self._refresh_plan_history_table()
                    logger.info('Plan marked as completed: %s', effort_id)
                except Exception as e:
                    logger.warning('Failed to mark plan as completed: %s', e)

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
            logger.debug('Plan step %s progress: %s', step_id, info)
