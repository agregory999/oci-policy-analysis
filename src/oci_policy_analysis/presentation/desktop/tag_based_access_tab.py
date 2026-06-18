##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It is not
# supported by Oracle Support.
#
# tag_based_access_tab.py
#
# Advanced tab for discovering and designing tag-based OCI IAM policies.
#
# Supports Python 3.12 and above
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

"""UI Tab for tag-based access analysis and condition authoring.

The :class:`TagBasedAccessTab` surfaces a normalized, per-tag-condition view
across all parsed policy statements and provides a sketched builder for
constructing new tag-based ``where`` clauses.

This first implementation focuses on:

* Wiring into the main application as an **advanced** tab (Settings toggle).
* Defining the public ``populate_data`` orchestration hook used after
  tenancy loads.
* Laying out the top-half discovery table and a placeholder bottom-half
  builder area, without implementing the full TagConditionCollector logic
  yet.

Core parsing/evaluation semantics intentionally remain in the existing
condition parser and simulation engine; this tab only orchestrates and
visualizes tag-focused data.
"""

from __future__ import annotations

import hashlib
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from oci_policy_analysis.application.core.parser import (
    TagCondition,
)
from oci_policy_analysis.application.core.support.helpers import for_display_tag_based_policy_row
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.tag_based_policy_service import TagBasedPolicyService
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import DataTable

logger = get_logger(component='tag_based_access_tab')


@dataclass
class TagConditionRow:
    """Lightweight representation of a tag-based condition for UI display.

    This is intentionally UI-focused and does **not** duplicate the eventual
    core ``TagCondition`` model described in
    ``CONTEXT_tag_based_access_tab.md``. Once the dedicated parser-side
    collector is implemented, this class can be replaced by or mapped from
    the shared model.
    """

    policy_name: str
    effective_path: str
    subject_type: str
    subject: str
    verb: str
    resource: str
    access_type: str
    tag_namespace: str
    tag_key: str
    operator: str
    value: str
    raw_condition: str


STATEMENT_COLUMNS: list[str] = [
    'Policy Name',
    'Effective Path',
    'Statement Text',
    'Raw Condition',
    'Parsed Condition Structure',
    # Optional parsed fields (toggled by UI checkbox)
    'Subject Type',
    'Subject',
    'Verb',
    'Resource',
]

STATEMENT_COLUMN_WIDTHS = {
    'Policy Name': 260,
    'Effective Path': 220,
    'Statement Text': 440,
    'Raw Condition': 380,
    'Parsed Condition Structure': 320,
    'Subject Type': 130,
    'Subject': 220,
    'Verb': 90,
    'Resource': 150,
}

CONDITION_DETAIL_COLUMNS: list[str] = [
    'Condition ID',
    'Policy Name',
    'Effective Path',
    'Access Type',
    'Tag Namespace',
    'Tag Key',
    'Operator',
    'Value',
    'Subexpression',
]

CONDITION_DETAIL_COLUMN_WIDTHS = {
    'Condition ID': 140,
    'Policy Name': 220,
    'Effective Path': 200,
    'Access Type': 170,
    'Tag Namespace': 140,
    'Tag Key': 140,
    'Operator': 90,
    'Value': 220,
    'Subexpression': 360,
}

TAG_OPERATOR_FILTER_VALUES = [
    'Any',
    '=',
    '!=',
    'in',
    'not in',
    '>',
    '<',
    '>=',
    '<=',
    'before',
    'after',
    'between',
]


class TagBasedAccessTab(BaseUITab):
    """Advanced UI tab for discovering and designing tag-based access.

    The tab is split into two main sections:

    * **Top Half – Tag-based Policies Overview**: a flat table of discovered
      tag-based conditions across all policy statements, with filters for
      tag namespace, key, and access type.
    * **Bottom Half – Tag-based Condition Builder & Tester**: a sketched
      layout for building new tag-based ``where`` clauses and sending them to
      existing tabs (Condition Tester, Simulation) for evaluation.

    Public methods follow the same conventions as other advanced tabs:

    * ``populate_data`` is orchestrated from ``App._post_load_update_ui`` to
      (re)build the internal cache and UI after a tenancy is loaded.
    * ``apply_settings`` is delegated to :class:`BaseUITab` for context help
      and font handling.
    """

    def __init__(self, parent: tk.Widget, app):
        """Initialize the Tag-based Access tab.

        The constructor should only create variables and build the static
        layout; it does **not** interrogate the repository or perform any
        heavy work. Data loading is coordinated explicitly via
        :meth:`populate_data` once a tenancy is available.

        Args:
            parent: The parent Tkinter widget, typically the main notebook.
            app:    Main application instance, providing access to the
                    policy repository and cross-tab helpers.
        """

        super().__init__(
            parent,
            default_help_text=(
                'Explore tag-based OCI IAM policies. Use this page to discover '
                'statements with tag conditions, filter by access type/namespace/'
                'key/value, and inspect parsed tag-condition details for each '
                'statement.'
            ),
            page_help_link='/context/project/CONTEXT_tag_based_access_tab.html',
        )
        self.app = app
        self.policy_repo = app.policy_compartment_analysis

        # Map from a stable statement identifier to the list of
        # TagCondition elements extracted from its where-clause. The
        # identifier is stored on each statement row so that selection
        # callbacks can look up the matching condition elements without
        # recomputing the parse.
        self._statement_to_conditions: dict[str, list[dict[str, object]]] = {}

        # --- Internal state ---
        # One row per policy statement that has a tag-based condition.
        self._statement_rows: list[dict[str, str]] = []
        # One row per tag condition element. Populated from
        # TagConditionCollector and filtered by statement selection.
        self._condition_rows: list[dict[str, str]] = []
        # Optional flat cache of all condition rows, used when no
        # statement is selected and filters are applied.
        self._all_condition_rows: list[dict[str, str]] = []

        # Filter variables for the overview section (statement + detail views)
        self.tag_namespace_var = tk.StringVar()
        self.tag_key_var = tk.StringVar()
        self.tag_value_var = tk.StringVar()
        self.tag_operator_var = tk.StringVar(value='Any')
        self.access_semantics_var = tk.StringVar(value='Any')
        self.condition_atom_terms_var = tk.StringVar()
        self.access_type_var = tk.StringVar(value='Any')
        # Controls whether parsed-statement columns are visible in the
        # top-level statement table.
        self.show_parsed_statement_var = tk.BooleanVar(value=False)
        # Toggle for including prospective statements in the overview tables.
        self.show_prospective_var = tk.BooleanVar(value=False)

        logger.info('Initializing TagBasedAccessTab UI layout')
        self._build_ui()

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def apply_settings(self, context_help: bool, font_size: str) -> None:
        """Apply context-help visibility and font size settings.

        Args:
            context_help: Whether to show the page help area.
            font_size:    Named font size (``"Small"``, ``"Medium"``, etc.).
        """

        super().apply_settings(context_help, font_size)

        # Ensure any dynamically added labels or controls in this tab
        # follow the same font sizing rules as other tabs. The
        # BaseUITab implementation already handles the main content
        # area; here we can add any TagBasedAccessTab-specific font
        # adjustments if needed in the future.

    def populate_data(self) -> None:  # noqa: C901, D401
        """Populate the Tag-based Access tab from the loaded policy data.

        This method is called from ``App._post_load_update_ui`` after a
        tenancy (or cache/compliance dataset) is loaded. It orchestrates:

        * Discovery of candidate tag-based policy statements using the
          repository's parsed statements.
        * Application of in-memory filters for namespace, key, value, and access
          type.
        * Refresh of the top-half :class:`DataTable` with normalized rows.

        The current implementation uses a conservative heuristic
        (``".tag."`` substring match in the raw conditions) as a stand-in for
        the planned TagConditionCollector visitor. Once the dedicated
        collector is available, this method can be updated to call into it
        without changing the tab wiring.
        """

        logger.info('In populate_data: rebuilding tag condition view from repository')

        # Defensive guard: if repository is not yet loaded, just clear tables.
        repo = getattr(self, 'policy_repo', None)
        if not repo or not getattr(repo, 'regular_statements', None):
            logger.info('In populate_data: no policy data available; clearing tables')
            self._statement_rows = []
            self._condition_rows = []
            self._statement_to_conditions = {}
            self._update_statement_table([])
            self._update_condition_table([])
            return

        statement_rows: list[dict[str, str]] = []

        # Optional prospective (what-if) statements. When enabled they are
        # shaped to look like regular statements so filters work the same way.
        prospective_statements = self._build_prospective_statement_like_list()

        # ------------------------------------------------------------------
        # Build the tag-focused overview tables using only statements whose
        # conditions contain ".tag.". This includes both real tenancy
        # statements and (optionally) prospective statements authored in the
        # Prospective Editor.
        # ------------------------------------------------------------------

        # Clear any prior mapping so we always reflect the latest snapshot.
        self._statement_to_conditions = {}
        self._all_condition_rows = []

        service_filters = self._current_service_filters()
        source_statements = (
            repo.filter_policy_statements(service_filters) if service_filters else repo.regular_statements
        )

        all_statements: list[tuple[str, dict]] = []
        for idx, stmt in enumerate(source_statements, start=1):
            all_statements.append((f's{idx}', stmt))
        for pidx, pst in enumerate(prospective_statements, start=1):
            all_statements.append((f'p{pidx}', pst))

        for stmt_id, stmt in all_statements:
            TagBasedPolicyService.enrich_statement(stmt)
            cond_text = str(stmt.get('conditions') or '').strip()
            tag_conds = [dict(cond) for cond in (stmt.get('tag_conditions') or []) if isinstance(cond, dict)]
            if not tag_conds:
                continue

            # Build a display-friendly row using the shared helper so the
            # column names remain consistent with other tabs.
            display_row = for_display_tag_based_policy_row(stmt)  # type: ignore[arg-type]

            base_name = display_row.get('Policy Name') or '(Unnamed Policy)'
            if stmt_id.startswith('p') and not str(base_name).startswith('[Prospective]'):
                policy_name = f'[Prospective] {base_name}'
            else:
                policy_name = base_name

            # Only one summary row per statement, enriched with parsed details.
            row = {
                'Policy Name': policy_name,
                'Effective Path': display_row.get('Effective Path') or 'ROOT',
                'Statement Text': display_row.get('Statement Text') or '',
                'Subject Type': display_row.get('Subject Type') or '',
                'Subject': str(display_row.get('Subject') or ''),
                'Verb': display_row.get('Verb') or '',
                'Resource': display_row.get('Resource') or '',
                'Raw Condition': cond_text,
                'Parsed Condition Structure': str(stmt.get('conditions_parsed_structure') or cond_text),
                '_Statement ID': stmt_id,
            }
            statement_rows.append(row)

            # Record the per-statement TagCondition list so selection of
            # this row can drive the detail table. Even if no tag
            # conditions were discovered we keep an entry (empty list) so
            # downstream code does not have to treat that as a special
            # case.
            self._statement_to_conditions[stmt_id] = tag_conds

            # Also project each TagCondition into a flat row for the
            # detail table so we have a convenient cache when no
            # statement is selected.
            for cond in tag_conds:
                self._all_condition_rows.append(self._project_condition_row(row, cond))

        logger.info(
            'In populate_data: discovered %d candidate tag-based statements',
            len(statement_rows),
        )
        self._statement_rows = statement_rows

        # Initially show all discovered statements; the condition-detail
        # table is driven by selection and will be populated on-demand.
        self._condition_rows = []

        self._update_statement_table(self._statement_rows)
        self._update_condition_table(self._condition_rows)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:  # noqa: D401
        """Construct the static layout for the Tag-based Access tab."""

        # --- Top Half: Tag-based Policies Overview (two tables) ---
        overview_frame = ttk.LabelFrame(self, text='Tag-based Policies Overview')
        overview_frame.pack(fill='both', padx=10, pady=(10, 5), expand=True)
        self.add_context_help(
            overview_frame,
            (
                'Discover policy statements that use tag-based conditions. '
                'Use the filters to narrow results by access type, tag '
                'namespace, tag key, or tag value, then review matching '
                'statements and their parsed condition elements.'
            ),
        )

        # Filters live at the top of the overview area and will eventually
        # drive both tables.
        self._build_overview_filters(overview_frame)

        # Tables are stacked vertically: statement-level first, then
        # condition-level details.
        self._build_statement_table(overview_frame)
        self._build_condition_detail_table(overview_frame)

    def _build_overview_filters(self, parent: ttk.LabelFrame) -> None:
        """Create the filter row for the overview table.

        Args:
            parent: The parent label frame that hosts the filter widgets.
        """

        filter_row_top = ttk.Frame(parent)
        filter_row_top.pack(fill='x', padx=6, pady=(6, 2))
        filter_row_top.columnconfigure(0, weight=1)
        filter_row_top.columnconfigure(1, weight=0)

        filter_left = ttk.Frame(filter_row_top)
        filter_left.grid(row=0, column=0, sticky='w')

        ttk.Label(filter_left, text='Access Type:').grid(row=0, column=0, padx=3, pady=2, sticky='w')
        access_combo = ttk.Combobox(
            filter_left,
            textvariable=self.access_type_var,
            state='readonly',
            width=24,
            values=[
                'Any',
                'request.principal.group',
                'request.principal.compartment',
                'target.resource',
                'target.resource.compartment',
            ],
        )
        access_combo.grid(row=0, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            access_combo,
            'Filter by access type (the left-hand side of a tag condition, '
            'such as request.principal.group or target.resource). Choose '
            "'Any' to include all access types.",
        )

        ttk.Label(filter_left, text='Tag Namespace:').grid(row=0, column=2, padx=3, pady=2, sticky='w')
        ns_entry = ttk.Entry(filter_left, textvariable=self.tag_namespace_var, width=20)
        ns_entry.grid(row=0, column=3, padx=3, pady=2, sticky='w')
        self.add_context_help(
            ns_entry,
            'Show only rows where the parsed tag namespace contains this '
            'text (case-insensitive). Example: entering "Operations" matches '
            'any namespace containing Operations.',
        )

        ttk.Label(filter_left, text='Tag Key:').grid(row=0, column=4, padx=3, pady=2, sticky='w')
        key_entry = ttk.Entry(filter_left, textvariable=self.tag_key_var, width=20)
        key_entry.grid(row=0, column=5, padx=3, pady=2, sticky='w')
        self.add_context_help(
            key_entry,
            'Show only rows where the parsed tag key contains this text ' '(case-insensitive). Example: "Environment".',
        )

        ttk.Label(filter_left, text='Tag Value:').grid(row=0, column=6, padx=3, pady=2, sticky='w')
        value_entry = ttk.Entry(filter_left, textvariable=self.tag_value_var, width=22)
        value_entry.grid(row=0, column=7, padx=3, pady=2, sticky='w')
        self.add_context_help(
            value_entry,
            'Show only rows where the parsed tag value contains this text ' '(case-insensitive). Example: "Prod".',
        )

        clear_btn = ttk.Button(filter_left, text='Clear Filters', command=self._clear_filters)
        clear_btn.grid(row=0, column=8, padx=(6, 0), pady=2, sticky='w')
        self.add_context_help(clear_btn, 'Clear tag namespace/key/value/access filters and re-show all rows.')

        filter_row_bottom = ttk.Frame(parent)
        filter_row_bottom.pack(fill='x', padx=6, pady=(0, 4))
        filter_row_bottom.columnconfigure(0, weight=1)
        filter_row_bottom.columnconfigure(1, weight=0)

        bottom_left = ttk.Frame(filter_row_bottom)
        bottom_left.grid(row=0, column=0, sticky='w')

        ttk.Label(bottom_left, text='Semantics:').grid(row=0, column=0, padx=3, pady=2, sticky='w')
        semantics_combo = ttk.Combobox(
            bottom_left,
            textvariable=self.access_semantics_var,
            state='readonly',
            width=26,
            values=[
                'Any',
                'requestor_group_tag',
                'requestor_compartment_tag',
                'target_resource_tag',
                'target_compartment_tag',
            ],
        )
        semantics_combo.grid(row=0, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            semantics_combo,
            'Semantic grouping for the parsed tag condition. Requestor values constrain the caller principal; '
            'target values constrain the resource or its compartment. Use this when you know the access pattern '
            'you want, but not the exact Oracle condition variable.',
        )

        ttk.Label(bottom_left, text='Operator:').grid(row=0, column=2, padx=3, pady=2, sticky='w')
        operator_combo = ttk.Combobox(
            bottom_left,
            textvariable=self.tag_operator_var,
            state='readonly',
            width=10,
            values=TAG_OPERATOR_FILTER_VALUES,
        )
        operator_combo.grid(row=0, column=3, padx=3, pady=2, sticky='w')
        self.add_context_help(
            operator_combo,
            'Filter by the parsed condition operator. Choose Any to ignore operator. Common tag policies use =, !=, in, or not in.',
        )

        ttk.Label(bottom_left, text='Atom Terms:').grid(row=0, column=4, padx=3, pady=2, sticky='w')
        atom_terms_entry = ttk.Entry(bottom_left, textvariable=self.condition_atom_terms_var, width=18)
        atom_terms_entry.grid(row=0, column=5, padx=3, pady=2, sticky='w')
        self.add_context_help(
            atom_terms_entry,
            'Broad parsed-condition search across atom left side, right side, operator, value type, evidence kind, and subexpression. '
            'Use this when you are not sure the condition is a tag condition.',
        )

        controls_row = ttk.Frame(parent)
        controls_row.pack(fill='x', padx=6, pady=(0, 4))
        controls_row.columnconfigure(0, weight=1)
        controls_left = ttk.Frame(controls_row)
        controls_left.grid(row=0, column=0, sticky='w')

        # Simple trace wiring: any change to namespace/key/access type will
        # re-apply filters to the in-memory tag rows without re-scanning
        # policies.
        self.tag_namespace_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        self.tag_key_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        self.tag_value_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        self.tag_operator_var.trace_add('write', lambda *_: self.populate_data())
        self.access_semantics_var.trace_add('write', lambda *_: self.populate_data())
        self.condition_atom_terms_var.trace_add('write', lambda *_: self.populate_data())
        self.access_type_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        operator_combo.bind('<<ComboboxSelected>>', lambda _event: self.populate_data())
        semantics_combo.bind('<<ComboboxSelected>>', lambda _event: self.populate_data())

        # Checkbox to toggle visibility of parsed-statement columns in the
        # statement overview table.
        parsed_chk = ttk.Checkbutton(
            controls_left,
            text='Show parsed statement',
            variable=self.show_parsed_statement_var,
            command=self._on_toggle_parsed_statement,
        )
        parsed_chk.grid(row=0, column=0, padx=(0, 8), pady=2, sticky='w')
        self.add_context_help(
            parsed_chk,
            'Show or hide parsed statement columns in the top table ' '(Subject Type, Subject, Verb, and Resource).',
        )

        # Prospective toggle mirrors the PoliciesTab experience so users can
        # include what-if statements authored in the Prospective editor.
        show_prospective_chk = ttk.Checkbutton(
            controls_left,
            text='Show Prospective',
            variable=self.show_prospective_var,
            command=self._on_toggle_prospective,
        )
        show_prospective_chk.grid(row=0, column=1, padx=(0, 8), pady=2, sticky='w')
        self.add_context_help(
            show_prospective_chk,
            'Include prospective (what-if) policy statements in this view. '
            'Only prospective statements with tag conditions are shown.',
        )

        open_prospective_btn = ttk.Button(
            controls_left,
            text='Prospective Editor…',
            command=self._open_prospective_editor_from_tag_tab,
        )
        open_prospective_btn.grid(row=0, column=2, padx=(0, 8), pady=2, sticky='w')
        self.add_context_help(
            open_prospective_btn,
            'Open the Prospective (what-if) Policy Editor to add or modify '
            'test statements. Those statements appear here when "Show '
            'Prospective" is enabled.',
        )

    def _clear_filters(self) -> None:
        """Clear all overview filters and refresh both tables."""
        self.tag_namespace_var.set('')
        self.tag_key_var.set('')
        self.tag_value_var.set('')
        self.tag_operator_var.set('Any')
        self.access_semantics_var.set('Any')
        self.condition_atom_terms_var.set('')
        self.access_type_var.set('Any')
        self._apply_filters_and_refresh()

    def _build_statement_table(self, parent: ttk.LabelFrame) -> None:
        """Create the statement-level :class:`DataTable` (Table 1).

        Each row corresponds to a policy statement that has a non-empty
        ``conditions`` field. The "Parsed Condition Structure" column is
        currently a stub (e.g. ``"(structure not yet parsed)"``), and will
        be populated once the TagConditionCollector is available.
        """

        table_frame = ttk.Frame(parent)
        table_frame.pack(fill='both', expand=True, padx=6, pady=(0, 4))

        def _on_select_statement(selected_rows: list[dict]) -> None:
            """Selection callback for the statement table.

            For the initial stub, this simply logs which statement was
            selected and clears the condition-detail table so you can see
            the wiring. Once TagConditionCollector is ready, this will be
            updated to filter condition rows for the selected statement.
            """

            if not selected_rows:
                self._update_condition_table([])
                return

            first = selected_rows[0]
            stmt_id = first.get('_Statement ID', '')
            logger.info(
                'Selected statement for tag analysis: id=%s, policy=%s, path=%s',
                stmt_id,
                first.get('Policy Name'),
                first.get('Effective Path'),
            )

            tag_conds = self._statement_to_conditions.get(stmt_id, [])

            # Project TagCondition elements into the flat row dicts
            # expected by the condition-detail DataTable.
            condition_rows: list[dict[str, str]] = []
            for cond in tag_conds:
                condition_rows.append(
                    {
                        'Condition ID': self._cond_value(cond, 'condition_id'),
                        'Policy Name': first.get('Policy Name', ''),
                        'Effective Path': first.get('Effective Path', ''),
                        'Access Type': self._cond_value(cond, 'access_type'),
                        'Tag Namespace': self._cond_value(cond, 'tag_namespace'),
                        'Tag Key': self._cond_value(cond, 'tag_key'),
                        'Operator': self._cond_value(cond, 'operator'),
                        'Value': self._cond_value(cond, 'value'),
                        'Subexpression': self._cond_value(cond, 'subexpression'),
                    }
                )

            logger.info(
                'Statement id=%s has %d tag conditions: %s',
                stmt_id,
                len(tag_conds),
                [self._cond_value(c, 'condition_id') for c in tag_conds],
            )

            self._condition_rows = condition_rows
            self._update_condition_table(self._condition_rows)

        self.statement_table = DataTable(
            parent=table_frame,
            columns=STATEMENT_COLUMNS,
            # Default to showing only the core discovery columns; the
            # parsed-statement details can be toggled on via the
            # "Show parsed statement" checkbox.
            display_columns=[
                'Policy Name',
                'Effective Path',
                'Statement Text',
                'Raw Condition',
                'Parsed Condition Structure',
            ],
            data=[],
            column_widths=STATEMENT_COLUMN_WIDTHS,
            selection_callback=_on_select_statement,
            multi_select=False,
        )
        self.statement_table.pack(fill='both', expand=True)

        # Attach a right-click context menu using DataTable's
        # row_context_menu_callback mechanism so we can reliably map
        # from the clicked row index back to the underlying dict in
        # self._statement_rows.
        def _statement_row_menu(row_index: int) -> tk.Menu:
            try:
                row = self._statement_rows[row_index]
            except Exception:
                return tk.Menu(self.statement_table, tearoff=0)

            menu = tk.Menu(self.statement_table, tearoff=0)
            menu.add_command(
                label='Show in condition tester',
                command=lambda r=row: self._on_statement_show_in_condition_tester(r),
            )
            return menu

        # Wire the callback onto the DataTable so its internal
        # _show_context_menu method invokes our menu provider.
        self.statement_table.row_context_menu_callback = _statement_row_menu

    def _build_condition_detail_table(self, parent: ttk.LabelFrame) -> None:
        """Create the condition-element :class:`DataTable` (Table 2).

        Each row represents a single named condition element inside a
        parsed where-clause. Until the TagConditionCollector is
        implemented, this table will remain empty or carry stubbed
        entries so you can confirm the layout.
        """

        table_frame = ttk.LabelFrame(parent, text='Tag Condition Elements (per parsed condition)')
        # Keep the detail table at a modest height (~5 visible rows)
        # by constraining the underlying DataTable height. This leaves
        # more vertical space for the Builder section below while still
        # allowing scrolling through additional rows.
        table_frame.pack(fill='x', expand=False, padx=6, pady=(0, 6), ipady=4)

        self.add_context_help(
            table_frame,
            (
                'Each row represents a single parsed tag condition. '
                'When you select a statement above, this table shows only '
                "that statement's tag conditions (respecting the filters). "
                'When no statement is selected, it shows all tag conditions '
                'that match the current Tag Namespace / Tag Key / Access Type '
                'filters across the visible statements.'
            ),
        )

        def _on_select_condition(selected_rows: list[dict]) -> None:
            if not selected_rows:
                return
            first = selected_rows[0]
            logger.info(
                f"Selected condition element id={first.get('Condition ID')}, "
                f"namespace={first.get('Tag Namespace')}, key={first.get('Tag Key')}"
            )

        self.condition_table = DataTable(
            parent=table_frame,
            columns=CONDITION_DETAIL_COLUMNS,
            display_columns=CONDITION_DETAIL_COLUMNS,
            data=[],
            column_widths=CONDITION_DETAIL_COLUMN_WIDTHS,
            selection_callback=_on_select_condition,
            multi_select=True,
            # Height is in approximate rows; 5 keeps the table compact
            # while retaining usability.
            height=5,
        )
        # Do not allow this table to consume extra vertical space; it
        # should remain at the fixed height defined above and allow
        # scrolling for additional rows.
        self.condition_table.pack(fill='x', expand=False)

        # Right-click context menu: allow testing an individual
        # condition subexpression directly in the Condition Tester.
        def _condition_row_menu(row_index: int) -> tk.Menu:
            try:
                row = self._condition_rows[row_index]
            except Exception:
                return tk.Menu(self.condition_table, tearoff=0)

            menu = tk.Menu(self.condition_table, tearoff=0)
            menu.add_command(
                label='Test individual condition',
                command=lambda r=row: self._on_condition_test_individual(r),
            )
            return menu

        self.condition_table.row_context_menu_callback = _condition_row_menu

    # ------------------------------------------------------------------
    # Prospective integration helpers
    # ------------------------------------------------------------------

    def _on_toggle_prospective(self) -> None:
        """Handle the Show Prospective checkbox toggle."""

        logger.info('TagBasedAccessTab: Show Prospective set to %s', self.show_prospective_var.get())
        self.populate_data()

    def _open_prospective_editor_from_tag_tab(self) -> None:
        """Open the Prospective Editor window from the Tag-based tab."""

        try:
            from oci_policy_analysis.presentation.desktop.prospective_editor_window import ProspectiveEditorWindow

            editor = ProspectiveEditorWindow(self, self.app)

            # Keep this tab in sync as the editor opens/closes so users
            # immediately see any prospective changes reflected here.
            self.populate_data()

            def _on_editor_destroy(event: tk.Event, *, window: tk.Toplevel = editor) -> None:
                if event.widget is window:
                    self.populate_data()

            editor.bind('<Destroy>', _on_editor_destroy)
        except Exception as exc:  # pragma: no cover - defensive UI guard
            logger.warning('TagBasedAccessTab: unable to open ProspectiveEditorWindow: %s', exc, exc_info=True)

    def _build_prospective_statement_like_list(self) -> list[dict]:  # noqa: C901
        """Return prospective statements shaped like regular policy statements."""

        if not getattr(self, 'show_prospective_var', None) or not self.show_prospective_var.get():
            return []

        service = getattr(self.app, 'prospective_service', None)
        engine = getattr(self.app, 'simulation_engine', None)

        raw_records: list[dict] = []
        try:
            if service is not None:
                for rec in service.list_all():
                    base = {
                        'compartment_path': getattr(rec, 'compartment_path', 'ROOT') or 'ROOT',
                        'description': getattr(rec, 'description', '') or '',
                        'statement_text': getattr(rec, 'statement_text', '') or '',
                        'parsed': getattr(rec, 'parsed', False),
                        'valid': getattr(rec, 'valid', False),
                        'invalid_reasons': list(getattr(rec, 'invalid_reasons', []) or []),
                    }
                    normalized = getattr(rec, 'normalized', None) or {}
                    if isinstance(normalized, dict):
                        base['normalized'] = normalized
                    raw_records.append(base)
            elif engine is not None and hasattr(engine, 'get_prospective_statements'):
                raw_records = list(engine.get_prospective_statements() or [])
        except Exception:  # pragma: no cover - defensive guard
            logger.info('TagBasedAccessTab: unable to build prospective list', exc_info=True)
            raw_records = []

        if not raw_records:
            logger.info('TagBasedAccessTab: no prospective statements available')
            return []

        tenancy_ocid = getattr(self.policy_repo, 'tenancy_ocid', None)
        prospective_like: list[dict] = []

        for pst in raw_records:
            stmt_text = str(pst.get('statement_text') or '').strip()
            if not stmt_text:
                continue

            comp_path = pst.get('compartment_path') or 'ROOT'
            desc = pst.get('description') or ''
            normalized = pst.get('normalized') or {}

            internal_id = hashlib.md5(
                (stmt_text + '::prospective::' + comp_path).encode('utf-8'),
            ).hexdigest()

            rec: dict = {
                'policy_name': desc or '[Prospective]',
                'policy_ocid': '(prospective)',
                'compartment_ocid': tenancy_ocid,
                'compartment_path': comp_path,
                'statement_text': stmt_text,
                'creation_time': '',
                'internal_id': internal_id,
                'parsed': bool(pst.get('parsed')),
                'valid': bool(pst.get('valid')),
                'invalid_reasons': list(pst.get('invalid_reasons') or []),
            }

            if isinstance(normalized, dict):
                for key in (
                    'subject_type',
                    'subject',
                    'verb',
                    'resource',
                    'permission',
                    'conditions',
                    'effective_path',
                    'action',
                    'location_type',
                    'location',
                ):
                    if key in normalized:
                        rec[key] = normalized[key]

            # Ensure a conditions string is present so .tag. detection works.
            conditions_value = rec.get('conditions') or pst.get('conditions') or ''
            if isinstance(conditions_value, list):
                conditions_value = ' '.join(str(part) for part in conditions_value if part)
            rec['conditions'] = str(conditions_value or '').strip()

            # Ensure an action is always present to keep filtering consistent.
            if 'action' not in rec:
                rec['action'] = 'allow'

            prospective_like.append(rec)

        logger.info(
            'TagBasedAccessTab: built %d prospective statements for tag overview',
            len(prospective_like),
        )

        return prospective_like

    def _current_service_filters(self) -> dict[str, list[str]]:
        filters: dict[str, list[str]] = {}
        if self.access_type_var.get().strip() and self.access_type_var.get().strip() != 'Any':
            filters['tag_access_type'] = [self.access_type_var.get().strip()]
        if self.tag_namespace_var.get().strip():
            filters['tag_namespace'] = [self.tag_namespace_var.get().strip()]
        if self.tag_key_var.get().strip():
            filters['tag_key'] = [self.tag_key_var.get().strip()]
        if self.tag_value_var.get().strip():
            filters['tag_value'] = [self.tag_value_var.get().strip()]
        if self.tag_operator_var.get().strip() and self.tag_operator_var.get().strip() != 'Any':
            filters['tag_operator'] = [self.tag_operator_var.get().strip()]
        if self.access_semantics_var.get().strip() and self.access_semantics_var.get().strip() != 'Any':
            filters['tag_access_semantics'] = [self.access_semantics_var.get().strip()]
        if self.condition_atom_terms_var.get().strip():
            filters['condition_atom_terms'] = [self.condition_atom_terms_var.get().strip()]
        return filters

    @staticmethod
    def _cond_value(cond: object, key: str) -> str:
        if isinstance(cond, dict):
            return str(cond.get(key) or '')
        return str(getattr(cond, key, '') or '')

    def _condition_matches_active_filters(self, cond: dict[str, object] | TagCondition) -> bool:
        """Return True if the TagCondition matches the current filters.

        Filters are applied against the parsed TagCondition fields:

        * Access Type: exact match on ``cond.access_type`` (unless "Any").
        * Tag Namespace: case-insensitive substring on ``cond.tag_namespace``.
        * Tag Key: case-insensitive substring on ``cond.tag_key``.
        * Tag Value: case-insensitive substring on ``cond.value``.
        """

        ns_filter = self.tag_namespace_var.get().strip().lower()
        key_filter = self.tag_key_var.get().strip().lower()
        value_filter = self.tag_value_var.get().strip().lower()
        operator_filter = self.tag_operator_var.get().strip().lower()
        if operator_filter == 'any':
            operator_filter = ''
        access_filter = self.access_type_var.get().strip()
        semantics_filter = self.access_semantics_var.get().strip()

        if access_filter and access_filter != 'Any':
            if self._cond_value(cond, 'access_type') != access_filter:
                return False
        if semantics_filter and semantics_filter != 'Any':
            if self._cond_value(cond, 'access_semantics') != semantics_filter:
                return False

        if ns_filter and ns_filter not in self._cond_value(cond, 'tag_namespace').lower():
            return False

        if key_filter and key_filter not in self._cond_value(cond, 'tag_key').lower():
            return False

        if value_filter and value_filter not in self._cond_value(cond, 'value').lower():
            return False
        if operator_filter and operator_filter not in self._cond_value(cond, 'operator').lower():
            return False

        return True

    def _project_condition_row(
        self, stmt_row: dict[str, str], cond: dict[str, object] | TagCondition
    ) -> dict[str, str]:
        """Project a TagCondition into a flat row for the detail table."""

        return {
            'Condition ID': self._cond_value(cond, 'condition_id'),
            'Policy Name': stmt_row.get('Policy Name', ''),
            'Effective Path': stmt_row.get('Effective Path', ''),
            'Access Type': self._cond_value(cond, 'access_type'),
            'Tag Namespace': self._cond_value(cond, 'tag_namespace'),
            'Tag Key': self._cond_value(cond, 'tag_key'),
            'Operator': self._cond_value(cond, 'operator'),
            'Value': self._cond_value(cond, 'value'),
            'Subexpression': self._cond_value(cond, 'subexpression'),
        }

    def _apply_filters_and_refresh(self) -> None:  # noqa: C901
        """Filter the in-memory rows and update both overview tables.

        Filters are applied using parsed :class:`TagCondition` metadata
        stored in :attr:`_statement_to_conditions`.

        * Statement table: a statement is included if **any** of its
          tag conditions matches the active filters.
        * Condition table:
          - If a statement is selected, shows only that statement's
            tag conditions that match the filters.
          - If no statement is selected, shows all matching tag
            conditions across the currently visible statements.
        """

        if not hasattr(self, 'statement_table'):
            return

        ns_filter = self.tag_namespace_var.get().strip()
        key_filter = self.tag_key_var.get().strip()
        value_filter = self.tag_value_var.get().strip()
        access_filter = self.access_type_var.get().strip()
        active_filters = bool(ns_filter or key_filter or value_filter or (access_filter and access_filter != 'Any'))

        # First, filter statements based on whether any of their
        # TagCondition elements match the active filters (or include all
        # when no filters are set).
        if not active_filters:
            filtered_statements = list(self._statement_rows)
        else:
            filtered_statements: list[dict[str, str]] = []
            for row in self._statement_rows:
                stmt_id = row.get('_Statement ID', '')
                conds = self._statement_to_conditions.get(stmt_id, [])
                if any(self._condition_matches_active_filters(c) for c in conds):
                    filtered_statements.append(row)

        self._update_statement_table(filtered_statements)

        # Next, build the condition-detail rows based on selection.
        selected_row_dicts: list[dict[str, str]] = []
        try:
            # DataTable in this project exposes a Treeview-like API:
            # selection() -> tuple of item IDs, and item(iid) -> dict with
            # "values" and "tags". We fall back gracefully if anything
            # changes in the widget implementation.
            if hasattr(self, 'statement_table') and hasattr(self.statement_table, 'tree'):
                tree = self.statement_table.tree  # type: ignore[attr-defined]
                selection = list(tree.selection())
                if selection:
                    iid = selection[0]
                    item = tree.item(iid)
                    # DataTable stores row dicts in "values" attribute
                    row_data = item.get('values')
                    if isinstance(row_data, dict):
                        selected_row_dicts = [row_data]
        except Exception:  # pragma: no cover - defensive
            logger.info(
                'Unable to derive selected rows from statement_table during filter refresh',
                exc_info=True,
            )

        condition_rows: list[dict[str, str]] = []
        if selected_row_dicts:
            # Only include conditions for the selected statement.
            stmt_row = selected_row_dicts[0]
            stmt_id = stmt_row.get('_Statement ID', '')
            tag_conds = self._statement_to_conditions.get(stmt_id, [])
            for cond in tag_conds:
                if not active_filters or self._condition_matches_active_filters(cond):
                    condition_rows.append(self._project_condition_row(stmt_row, cond))
        else:
            # No selection: show all matching conditions across
            # currently visible statements.
            for stmt_row in filtered_statements:
                stmt_id = stmt_row.get('_Statement ID', '')
                for cond in self._statement_to_conditions.get(stmt_id, []):
                    if not active_filters or self._condition_matches_active_filters(cond):
                        condition_rows.append(self._project_condition_row(stmt_row, cond))

        self._condition_rows = condition_rows
        self._update_condition_table(condition_rows)

    def _on_toggle_parsed_statement(self) -> None:
        """Toggle visibility of parsed-statement columns in the overview.

        When unchecked (default), only the primary discovery columns are
        shown: Policy Name, Effective Path, Statement Text (placeholder for
        the full statement), Raw Condition, and Parsed Condition Structure.

        When checked, additional parsed columns (Subject Type, Subject,
        Verb, Resource) are appended on the right-hand side of the table.
        """

        if not hasattr(self, 'statement_table'):
            return

        # TODO: Make these constants and reference them in this function
        base_columns = [
            'Policy Name',
            'Effective Path',
            'Statement Text',
            'Raw Condition',
            'Parsed Condition Structure',
        ]
        parsed_columns = ['Subject Type', 'Subject', 'Verb', 'Resource']

        if self.show_parsed_statement_var.get():
            display_columns = base_columns + parsed_columns
        else:
            display_columns = base_columns

        try:
            # DataTable exposes display_columns as a mutable attribute in
            # other tabs; update it here and ask the widget to refresh.
            self.statement_table.display_columns = display_columns
            self.statement_table.set_display_columns(display_columns)  # type: ignore[attr-defined]
        except Exception:
            # Fallback for older DataTable implementations that may not
            # expose a dedicated setter; updating the attribute alone is
            # still safe even if the table does not immediately re-pack
            # columns.
            logger.info('Unable to apply parsed-statement column toggle', exc_info=True)

    def _update_statement_table(self, rows: list[dict[str, str]]) -> None:
        """Update the statement-level :class:`DataTable`.

        Args:
            rows: Normalized row dictionaries matching
                  :data:`STATEMENT_COLUMNS`.
        """

        if not hasattr(self, 'statement_table'):
            return
        self.statement_table.update_data(new_data=rows)

    def _update_condition_table(self, rows: list[dict[str, str]]) -> None:
        """Update the condition-element :class:`DataTable`.

        Args:
            rows: Normalized row dictionaries matching
                  :data:`CONDITION_DETAIL_COLUMNS`.
        """

        if not hasattr(self, 'condition_table'):
            return
        self.condition_table.update_data(new_data=rows)

    # ------------------------------------------------------------------
    # Shared helper + context-menu actions for Condition Tester
    # ------------------------------------------------------------------

    def _send_condition_to_tester(self, snippet: str, show_empty_message: bool = False) -> None:
        """Send an arbitrary condition snippet to the Condition Tester tab.

        This central helper is used by:

        * The bottom "Test Condition" button (builder snippet).
        * Right-click actions on the top statement table
          ("Show in condition tester" full where-clause).
        * Right-click actions on the condition-detail table
          ("Test individual condition" subexpression-only).

        Args:
            snippet: The condition clause to inject into the
                :class:`ConditionTesterTab` text area.
            show_empty_message: When True, display an informational
                messagebox if ``snippet`` is empty. Callers that pass
                explicit text typically set this to False so they can
                remain silent on empty input.
        """

        snippet = (snippet or '').strip()
        if not snippet:
            if show_empty_message:
                try:
                    messagebox.showinfo(
                        'No Condition to Test',
                        'There is no generated condition snippet to test. '
                        'Please fill in the builder fields or choose a '
                        'statement/condition row, and then try again.',
                    )
                except Exception:
                    logger.info(
                        'Unable to show info messagebox for empty condition snippet',
                        exc_info=True,
                    )
            return

        logger.info('Sending condition to tester: %r', snippet)

        app = getattr(self, 'app', None)
        if not app:
            return

        # TODO: The condition_tester will exist if this tab does, so maybe no need for so much defense code
        tester_tab = getattr(app, 'condition_tester_tab', None)
        try:
            if tester_tab is not None and hasattr(tester_tab, 'set_clause_text'):
                tester_tab.set_clause_text(snippet)
            # Best-effort hook to bring the Condition Tester tab to front
            if hasattr(app, 'open_condition_tester_with_condition'):
                app.open_condition_tester_with_condition(snippet)
            elif hasattr(app, 'notebook') and tester_tab is not None:
                # Fallback: select the Condition Tester tab directly
                try:
                    app.notebook.select(tester_tab)
                except Exception:
                    logger.info(
                        'Unable to select Condition Tester tab on notebook',
                        exc_info=True,
                    )
        except Exception:
            logger.info('Error while sending snippet to Condition Tester', exc_info=True)

    def _on_statement_show_in_condition_tester(self, row: dict[str, str]) -> None:
        """Right-click action for the statement table.

        Uses the full *Raw Condition* / where-clause so the entire
        statement condition can be exercised in the Condition Tester.
        """

        if not row:
            return
        raw = (row.get('Raw Condition') or '').strip()
        self._send_condition_to_tester(raw, show_empty_message=True)

    def _on_condition_test_individual(self, row: dict[str, str]) -> None:
        """Right-click action for the condition-detail table.

        Uses the individual condition "Subexpression" so users can
        test a single tag condition element in isolation.
        """

        if not row:
            return
        subexpr = (row.get('Subexpression') or '').strip()
        self._send_condition_to_tester(subexpr, show_empty_message=True)
