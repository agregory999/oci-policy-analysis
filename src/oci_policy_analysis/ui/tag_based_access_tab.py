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

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from oci_policy_analysis.common.helpers import for_display_tag_based_policy_row
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.parsers.condition_parser.TagConditionCollector import (
    TagCondition,
    collect_tag_conditions,
)
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

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
                'Explore tag-based OCI IAM policies. The top section discovers '
                'and filters statements with tag conditions; the bottom section '
                'sketches a builder for new tag-based where clauses, which are '
                'evaluated using the existing Condition Tester and Simulation '
                'tabs.'
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
        self._statement_to_conditions: dict[str, list[TagCondition]] = {}

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
        self.access_type_var = tk.StringVar(value='Any')
        # Controls whether parsed-statement columns are visible in the
        # top-level statement table.
        self.show_parsed_statement_var = tk.BooleanVar(value=False)

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
        * Application of in-memory filters for namespace, key, and access
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

        # ------------------------------------------------------------------
        # Second pass: build the tag-focused overview tables using only
        # statements whose conditions contain ".tag.".
        # ------------------------------------------------------------------

        # Clear any prior mapping so we always reflect the latest
        # repository snapshot.
        self._statement_to_conditions = {}
        self._all_condition_rows = []

        for idx, stmt in enumerate(repo.regular_statements, start=1):
            cond_text = (stmt.get('conditions') or '').strip()
            if not cond_text or '.tag.' not in cond_text:
                continue

            # Build a stable identifier for this statement within the
            # current tab population run. This avoids depending on the
            # repository's internal IDs while still giving us a key to
            # map back from UI selection to parsed conditions.
            stmt_id = f's{idx}'

            # Use the dedicated TagConditionCollector helper to parse
            # the where-clause. Any syntax errors are handled inside the
            # helper; we only log a brief message here for context.
            try:
                structure, tag_conds = collect_tag_conditions(cond_text)
            except Exception:  # pragma: no cover - defensive, helper already logs
                logger.info(
                    'In populate_data: TagConditionCollector failed; using raw condition as structure',
                    exc_info=True,
                )
                structure, tag_conds = cond_text, []

            # Build a display-friendly row using the shared helper so the
            # column names remain consistent with other tabs.
            display_row = for_display_tag_based_policy_row(stmt)  # type: ignore[arg-type]

            # For now we only populate a single summary row per statement.
            row = {
                'Policy Name': display_row.get('Policy Name') or '(Unnamed Policy)',
                'Effective Path': display_row.get('Effective Path') or 'ROOT',
                'Statement Text': display_row.get('Statement Text') or '',
                'Subject Type': display_row.get('Subject Type') or '',
                'Subject': str(display_row.get('Subject') or ''),
                'Verb': display_row.get('Verb') or '',
                'Resource': display_row.get('Resource') or '',
                'Raw Condition': cond_text,
                # Always show the parsed structure if available; if the
                # collector returned an empty string, fall back to the
                # original condition text so users still see the shape
                # of the where-clause instead of a placeholder.
                'Parsed Condition Structure': structure or cond_text,
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
                'Use the filters to narrow by tag namespace, key, or access '
                'type, then inspect the flattened per-condition view.'
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

        filter_row = ttk.Frame(parent)
        filter_row.pack(fill='x', padx=6, pady=(6, 4))

        ttk.Label(filter_row, text='Tag Namespace:').grid(row=0, column=0, padx=3, pady=2, sticky='w')
        ns_entry = ttk.Entry(filter_row, textvariable=self.tag_namespace_var, width=24)
        ns_entry.grid(row=0, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            ns_entry,
            'Filter rows where the discovered tag namespace contains this '
            'string (case-insensitive). Multiple namespaces can be provided '
            'using | separators in a future enhancement.',
        )

        ttk.Label(filter_row, text='Tag Key:').grid(row=0, column=2, padx=3, pady=2, sticky='w')
        key_entry = ttk.Entry(filter_row, textvariable=self.tag_key_var, width=24)
        key_entry.grid(row=0, column=3, padx=3, pady=2, sticky='w')
        self.add_context_help(
            key_entry,
            'Filter rows where the discovered tag key contains this string ' '(case-insensitive).',
        )

        ttk.Label(filter_row, text='Access Type:').grid(row=0, column=4, padx=3, pady=2, sticky='w')
        access_combo = ttk.Combobox(
            filter_row,
            textvariable=self.access_type_var,
            state='readonly',
            width=26,
            values=[
                'Any',
                'request.principal.group',
                'request.principal.compartment',
                'target.resource',
                'target.resource.compartment',
            ],
        )
        access_combo.grid(row=0, column=5, padx=3, pady=2, sticky='w')
        self.add_context_help(
            access_combo,
            'Restrict results to a specific access type (left-hand side of '
            "the tag condition), or choose 'Any' to see all.",
        )

        refresh_btn = ttk.Button(filter_row, text='Refresh from Loaded Policies', command=self._on_refresh_clicked)
        refresh_btn.grid(row=0, column=6, padx=(12, 2), pady=2, sticky='w')
        self.add_context_help(
            refresh_btn,
            'Re-scan the loaded policies for tag-based conditions and '
            'rebuild the overview table. This is safe to use after reloads '
            'or cache imports.',
        )

        # Simple trace wiring: any change to namespace/key/access type will
        # re-apply filters to the in-memory tag rows without re-scanning
        # policies.
        self.tag_namespace_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        self.tag_key_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())
        self.access_type_var.trace_add('write', lambda *_: self._apply_filters_and_refresh())

        # Checkbox to toggle visibility of parsed-statement columns in the
        # statement overview table.
        parsed_chk = ttk.Checkbutton(
            filter_row,
            text='Show parsed statement',
            variable=self.show_parsed_statement_var,
            command=self._on_toggle_parsed_statement,
        )
        parsed_chk.grid(row=0, column=7, padx=(12, 2), pady=2, sticky='w')

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
                        'Condition ID': cond.condition_id,
                        'Policy Name': first.get('Policy Name', ''),
                        'Effective Path': first.get('Effective Path', ''),
                        'Access Type': cond.access_type,
                        'Tag Namespace': cond.tag_namespace,
                        'Tag Key': cond.tag_key,
                        'Operator': cond.operator,
                        'Value': cond.value,
                        'Subexpression': cond.subexpression,
                    }
                )

            logger.info(
                f'Statement id={stmt_id} has {len(tag_conds)} tag conditions: {[c.condition_id for c in tag_conds]}'
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

    def _condition_matches_active_filters(self, cond: TagCondition) -> bool:
        """Return True if the TagCondition matches the current filters.

        Filters are applied against the parsed TagCondition fields:

        * Access Type: exact match on ``cond.access_type`` (unless "Any").
        * Tag Namespace: case-insensitive substring on ``cond.tag_namespace``.
        * Tag Key: case-insensitive substring on ``cond.tag_key``.
        """

        ns_filter = self.tag_namespace_var.get().strip().lower()
        key_filter = self.tag_key_var.get().strip().lower()
        access_filter = self.access_type_var.get().strip()

        if access_filter and access_filter != 'Any':
            if (cond.access_type or '') != access_filter:
                return False

        if ns_filter and ns_filter not in (cond.tag_namespace or '').lower():
            return False

        if key_filter and key_filter not in (cond.tag_key or '').lower():
            return False

        return True

    def _project_condition_row(self, stmt_row: dict[str, str], cond: TagCondition) -> dict[str, str]:
        """Project a TagCondition into a flat row for the detail table."""

        return {
            'Condition ID': cond.condition_id,
            'Policy Name': stmt_row.get('Policy Name', ''),
            'Effective Path': stmt_row.get('Effective Path', ''),
            'Access Type': cond.access_type,
            'Tag Namespace': cond.tag_namespace,
            'Tag Key': cond.tag_key,
            'Operator': cond.operator,
            'Value': cond.value,
            'Subexpression': cond.subexpression,
        }

    def _on_refresh_clicked(self) -> None:
        """Handle the *Refresh from Loaded Policies* button click.

        This simply re-runs :meth:`populate_data`, which re-scans the
        repository and applies any active filters.
        """

        logger.info('Manual refresh requested from UI')
        self.populate_data()

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
        access_filter = self.access_type_var.get().strip()
        active_filters = bool(ns_filter or key_filter or (access_filter and access_filter != 'Any'))

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
