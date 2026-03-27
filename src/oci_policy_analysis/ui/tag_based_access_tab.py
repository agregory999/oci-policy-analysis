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
from oci_policy_analysis.logic.policy_intelligence import (
    PolicyIntelligenceEngine,
)
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
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

        # Distinct values discovered from statements/conditions for
        # seeding the builder comboboxes.
        self._builder_principals: list[str] = []
        self._builder_principal_details: dict[str, tuple[str, str | None, str]] = {}
        self._builder_resources: list[str] = []
        self._builder_all_resources: list[str] = []
        self._builder_locations: list[str] = []
        self._builder_effective_paths: list[str] = []

        # Reference data repository from main app for "All Possible" resources/families.
        self._reference_repo: ReferenceDataRepo = app.reference_data_repo
        logger.info(
            'TagBasedAccessTab: ReferenceDataRepo loaded for All Possible resources (resources=%d, families=%d)',
            len(self._reference_repo.data.get('resources', {})),
            len(self._reference_repo.data.get('families', {})),
        )
        # Filter variables for the overview section (statement + detail views)
        self.tag_namespace_var = tk.StringVar()
        self.tag_key_var = tk.StringVar()
        self.access_type_var = tk.StringVar(value='Any')
        # Controls whether parsed-statement columns are visible in the
        # top-level statement table.
        self.show_parsed_statement_var = tk.BooleanVar(value=False)

        # Builder variables (bottom half – statement builder)
        # Left (statement specifics)
        self.builder_principal_var = tk.StringVar()
        self.builder_resource_var = tk.StringVar()
        self.builder_verb_var = tk.StringVar(value='use')
        self.builder_location_var = tk.StringVar()
        self.builder_effective_path_var = tk.StringVar()

        # Right (tag condition pieces)
        self.builder_access_type_var = tk.StringVar()
        self.builder_namespace_var = tk.StringVar()
        self.builder_key_var = tk.StringVar()
        self.builder_operator_var = tk.StringVar()
        self.builder_value_var = tk.StringVar()
        self.builder_variable_preview_var = tk.StringVar()
        self.builder_condition_preview_var = tk.StringVar()

        # Full statement preview (combines subject/verb/resource/location + where snippet)
        self.builder_statement_preview_var = tk.StringVar()

        # When enabled, the Resource dropdown will show **all known**
        # resources and families from ReferenceDataRepo instead of only
        # those discovered in the loaded tenancy policies.
        self.builder_all_possible_resources_var = tk.BooleanVar(value=False)

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

        logger.info('TagBasedAccessTab.populate_data: rebuilding tag condition view from repository')

        # Defensive guard: if repository is not yet loaded, just clear tables.
        repo = getattr(self, 'policy_repo', None)
        if not repo or not getattr(repo, 'regular_statements', None):
            logger.info('TagBasedAccessTab.populate_data: no policy data available; clearing tables')
            self._statement_rows = []
            self._condition_rows = []
            self._statement_to_conditions = {}
            self._update_statement_table([])
            self._update_condition_table([])
            return

        statement_rows: list[dict[str, str]] = []

        # ------------------------------------------------------------------
        # First pass: derive distinct values for the builder from **all**
        # regular statements in the tenancy, not just those with tag
        # conditions. This keeps the builder broadly useful even when
        # only a subset of policies use tag-based where-clauses.
        # ------------------------------------------------------------------

        principals_seen: set[str] = set()
        principal_details: dict[str, tuple[str, str | None, str]] = {}
        resources_seen: set[str] = set()
        effective_paths_seen: set[str] = set()

        for stmt in repo.regular_statements:
            try:
                display_row = for_display_tag_based_policy_row(stmt)  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - defensive
                logger.info(
                    'TagBasedAccessTab.populate_data: error normalizing statement for builder distincts',
                    exc_info=True,
                )
                continue

            # Derive canonical principal keys where possible so the
            # builder can emit realistic subjects (service, group,
            # dynamic-group, etc.). Fall back to simple strings when the
            # shape is not recognized.
            subj_type = (display_row.get('Subject Type') or '').strip() or None
            raw_subject = display_row.get('Subject')

            def _add_principal(ptype: str, domain: str | None, name: str) -> None:
                # For id-based subjects, prefer compact keys without a
                # domain placeholder, e.g. "group-id:ocid1...". These do
                # not participate in the canonical {type}:{domain}/{name}
                # pattern today.
                if ptype in {'group-id', 'dynamic-group-id'}:
                    key = f'{ptype}:{name}'
                    principals_seen.add(key)
                    principal_details[key] = (ptype, None, name)
                    return

                # For structured subjects (user/group/dynamic-group/service)
                # build the same principal_key shape used by simulation and
                # intelligence: {subject_type}:{domain}/{name} with
                # explicit Default/None rules.

                key = PolicyIntelligenceEngine.calculate_principal_key(ptype, domain, name)
                principals_seen.add(key)
                principal_details[key] = (ptype, domain, name)

            if (
                subj_type in {'user', 'group', 'dynamic-group', 'service', 'group-id', 'dynamic-group-id'}
                and raw_subject
            ):
                subjects = raw_subject if isinstance(raw_subject, list) else [raw_subject]
                for subj in subjects:
                    # Tuple/list form: (domain, name)
                    if isinstance(subj, (tuple | list)) and len(subj) == 2:
                        domain, name = subj
                        dom_str = None if (domain in (None, 'default')) else str(domain)
                        name_str = str(name).strip()
                        if name_str:
                            _add_principal(subj_type, dom_str, name_str)
                    elif isinstance(subj, str):
                        name_str = subj.strip()
                        if name_str:
                            _add_principal(subj_type, None, name_str)
            else:
                # Fallback: treat Subject as display-only strings if we
                # cannot infer a structured principal.
                if isinstance(raw_subject, list):
                    subject_pieces = [str(s).strip() for s in raw_subject if str(s).strip()]
                    for s in subject_pieces:
                        principals_seen.add(s)
                else:
                    subject_display = str(raw_subject or '').strip()
                    if subject_display:
                        principals_seen.add(subject_display)

            resource_display = str(display_row.get('Resource') or '').strip()
            if resource_display:
                resources_seen.add(resource_display)

            effective_path = str(display_row.get('Effective Path') or '').strip()
            if effective_path:
                effective_paths_seen.add(effective_path)

        # Persist sorted distinct values for builder comboboxes.
        self._builder_principals = sorted(principals_seen)
        self._builder_principal_details = principal_details
        self._builder_resources = sorted(resources_seen)
        # For now, treat Effective Path as the location / compartment
        # dimension until we have more granular location parsing.
        self._builder_locations = sorted(effective_paths_seen)
        self._builder_effective_paths = sorted(effective_paths_seen)

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
                    'TagBasedAccessTab.populate_data: TagConditionCollector failed; using raw condition as structure',
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
            'TagBasedAccessTab.populate_data: discovered %d candidate tag-based statements',
            len(statement_rows),
        )
        self._statement_rows = statement_rows

        # Initially show all discovered statements; the condition-detail
        # table is driven by selection and will be populated on-demand.
        self._condition_rows = []

        self._update_statement_table(self._statement_rows)
        self._update_condition_table(self._condition_rows)

        # Finally, refresh the builder dropdowns from the distinct
        # values we just derived.
        self._refresh_builder_values()

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

        # --- Bottom Half: Tag-based Condition Builder & Tester (sketch) ---
        builder_frame = ttk.LabelFrame(self, text='Tag-based Condition Builder & Tester')
        builder_frame.pack(fill='both', padx=8, pady=(0, 8), expand=True)
        self.add_context_help(
            builder_frame,
            (
                'Sketch for building tag-based where clauses. Configure access '
                'type, namespace, key, operator, and value to generate a '
                'syntactically correct snippet that can be copied or sent to '
                'the Condition Tester and Simulation tabs. (Bottom-half '
                'orchestration not fully implemented yet.)'
            ),
        )
        self._build_builder_section(builder_frame)

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
                'TagBasedAccessTab: selected statement for tag analysis: id=%s, policy=%s, path=%s',
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
                'TagBasedAccessTab: statement id=%s has %d tag conditions: %s',
                stmt_id,
                len(tag_conds),
                [c.condition_id for c in tag_conds],
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
                'TagBasedAccessTab: selected condition element id=%s, namespace=%s, key=%s',
                first.get('Condition ID'),
                first.get('Tag Namespace'),
                first.get('Tag Key'),
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

    def _build_builder_section(self, parent: ttk.LabelFrame) -> None:  # noqa: C901
        """Sketch the bottom-half tag condition builder UI.

        This section defines the layout and live preview labels, but does not
        yet wire clipboard operations or cross-tab navigation. Those
        behaviors will be added in a follow-on implementation once the
        TagConditionCollector and builder semantics are finalized.

        Args:
            parent: The parent label frame for the builder widgets.
        """

        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=3)
        parent.columnconfigure(2, weight=2)

        # --- Left: statement specifics ---
        form_frame = ttk.Frame(parent)
        form_frame.grid(row=0, column=0, sticky='nsew', padx=(6, 3), pady=6)
        # Three-column grid: [Label][Primary dropdown][Aux/toggle]
        form_frame.columnconfigure(0, weight=0)
        form_frame.columnconfigure(1, weight=1)
        form_frame.columnconfigure(2, weight=0)

        ttk.Label(form_frame, text='Principal:').grid(row=0, column=0, padx=3, pady=2, sticky='e')
        self._builder_principal_combo = ttk.Combobox(
            form_frame,
            textvariable=self.builder_principal_var,
            width=36,
            state='readonly',
            values=self._builder_principals,
        )
        self._builder_principal_combo.grid(row=0, column=1, columnspan=2, padx=3, pady=2, sticky='we')
        self.add_context_help(
            self._builder_principal_combo,
            'Choose the principal (user, group, dynamic group, service, or id-based) that the statement applies to. '
            'Keys like group-id:ocid... and dynamic-group-id:ocid... represent principals by OCID.',
        )

        ttk.Label(form_frame, text='Verb:').grid(row=1, column=0, padx=3, pady=2, sticky='e')
        self._builder_verb_combo = ttk.Combobox(
            form_frame,
            textvariable=self.builder_verb_var,
            width=36,
            state='readonly',
            values=['inspect', 'read', 'use', 'manage'],
        )
        self._builder_verb_combo.grid(row=1, column=1, columnspan=2, padx=3, pady=2, sticky='we')
        self.add_context_help(
            self._builder_verb_combo,
            'Select the high-level verb (inspect, read, use, manage) for the generated policy statement.',
        )

        ttk.Label(form_frame, text='Resource:').grid(row=2, column=0, padx=3, pady=2, sticky='e')
        self._builder_resource_combo = ttk.Combobox(
            form_frame,
            textvariable=self.builder_resource_var,
            width=36,
            state='readonly',
            values=self._builder_resources,
        )
        self._builder_resource_combo.grid(row=2, column=1, padx=3, pady=2, sticky='we')
        self.add_context_help(
            self._builder_resource_combo,
            "Pick the resource target (e.g., buckets, instances). By default this list is based on resources observed in existing policies; enable 'All Possible' to see every known resource/family from reference data.",
        )

        # Checkbox to toggle between in-use resources and full reference data domain
        all_possible_chk = ttk.Checkbutton(
            form_frame,
            text='All Possible',
            variable=self.builder_all_possible_resources_var,
            command=self._on_toggle_all_possible_resources,
        )
        all_possible_chk.grid(row=2, column=2, padx=(6, 0), pady=2, sticky='w')
        self.add_context_help(
            all_possible_chk,
            'When checked, the Resource dropdown is populated from the full domain of known resources and families in the reference data, not just those seen in the loaded tenancy.',
        )

        ttk.Label(form_frame, text='Location / Compartment:').grid(row=3, column=0, padx=3, pady=2, sticky='e')
        self._builder_location_combo = ttk.Combobox(
            form_frame,
            textvariable=self.builder_location_var,
            width=36,
            state='readonly',
            values=self._builder_locations,
        )
        self._builder_location_combo.grid(row=3, column=1, columnspan=2, padx=3, pady=2, sticky='we')
        self.add_context_help(
            self._builder_location_combo,
            'Select where in the compartment hierarchy this policy statement would live. '
            'This affects how Effective Path is interpreted but is not directly part of the policy text.',
        )

        ttk.Label(form_frame, text='Effective Path:').grid(row=4, column=0, padx=3, pady=2, sticky='e')
        self._builder_effective_path_combo = ttk.Combobox(
            form_frame,
            textvariable=self.builder_effective_path_var,
            width=36,
            state='readonly',
            values=self._builder_effective_paths,
        )
        self._builder_effective_path_combo.grid(row=4, column=1, columnspan=2, padx=3, pady=2, sticky='we')
        self.add_context_help(
            self._builder_effective_path_combo,
            'Choose the effective path (scope) that OCI uses when evaluating the statement. '
            "The builder subtracts Location from this path to form the 'in compartment ...' clause.",
        )

        # --- Right: tag condition pieces (as before) ---
        right_frame = ttk.Frame(parent)
        right_frame.grid(row=0, column=1, sticky='nsew', padx=3, pady=6)

        ttk.Label(right_frame, text='Access Type:').grid(row=0, column=0, padx=3, pady=2, sticky='e')
        access_combo = ttk.Combobox(
            right_frame,
            textvariable=self.builder_access_type_var,
            state='readonly',
            width=40,
            values=[
                'request.principal.group',
                'request.principal.compartment',
                'target.resource',
                'target.resource.compartment',
            ],
        )
        access_combo.grid(row=0, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            access_combo,
            'Select the left-hand side access variable for the tag condition, such as request.principal.group or '
            'target.resource.compartment.',
        )

        ttk.Label(right_frame, text='Tag Namespace:').grid(row=1, column=0, padx=3, pady=2, sticky='e')
        ttk.Entry(right_frame, textvariable=self.builder_namespace_var, width=42).grid(
            row=1, column=1, padx=3, pady=2, sticky='w'
        )
        self.add_context_help(
            right_frame,
            "Enter the tag namespace and key that the condition will reference. For example, a namespace of 'MyNs' "
            "and key 'CostCenter' would produce variables like request.principal.group.tag.MyNs.CostCenter.",
        )

        ttk.Label(right_frame, text='Tag Key:').grid(row=2, column=0, padx=3, pady=2, sticky='e')
        ttk.Entry(right_frame, textvariable=self.builder_key_var, width=42).grid(
            row=2, column=1, padx=3, pady=2, sticky='w'
        )

        ttk.Label(right_frame, text='Operator:').grid(row=3, column=0, padx=3, pady=2, sticky='e')
        op_combo = ttk.Combobox(
            right_frame,
            textvariable=self.builder_operator_var,
            state='readonly',
            width=20,
            values=['=', '!=', 'IN', 'NOT IN'],
        )
        op_combo.grid(row=3, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            op_combo,
            'Choose the comparison operator for the tag condition. Use IN / NOT IN when you want to compare against '
            'a list of allowed or disallowed values.',
        )

        ttk.Label(right_frame, text='Value(s):').grid(row=4, column=0, padx=3, pady=2, sticky='e')
        val_entry = ttk.Entry(right_frame, textvariable=self.builder_value_var, width=42)
        val_entry.grid(row=4, column=1, padx=3, pady=2, sticky='w')
        self.add_context_help(
            val_entry,
            'Enter the tag value or values to compare against. For IN and NOT IN operators, use a comma-separated '
            'list, for example: foo,bar,baz. To use pattern match, enter /*xx/ or /abc*/',
        )

        preview_frame = ttk.Frame(right_frame)
        preview_frame.grid(row=5, column=0, columnspan=2, padx=3, pady=(8, 2), sticky='w')

        ttk.Label(preview_frame, text='Generated variable:').grid(row=0, column=0, sticky='w')
        ttk.Label(preview_frame, textvariable=self.builder_variable_preview_var, foreground='#006699').grid(
            row=0, column=1, sticky='w', padx=(4, 0)
        )

        ttk.Label(preview_frame, text='Condition snippet:').grid(row=1, column=0, sticky='w')
        ttk.Label(preview_frame, textvariable=self.builder_condition_preview_var, foreground='#006699').grid(
            row=1, column=1, sticky='w', padx=(4, 0)
        )

        # --- Generated statement + actions (right-hand side) ---
        statement_frame = ttk.Frame(parent)
        statement_frame.grid(row=0, column=2, sticky='nsew', padx=(3, 6), pady=6)

        # Show where this statement would be placed in the hierarchy
        loc_label = ttk.Label(statement_frame, text='Location (Compartment): <none>')
        loc_label.pack(anchor='w', pady=(0, 4))
        self._builder_location_display_label = loc_label

        ttk.Label(statement_frame, text='Generated policy statement:').pack(anchor='w')
        ttk.Label(
            statement_frame,
            textvariable=self.builder_statement_preview_var,
            foreground='#003366',
            wraplength=380,
            justify='left',
        ).pack(fill='x', pady=(2, 6))

        btn_row = ttk.Frame(statement_frame)
        btn_row.pack(fill='x', pady=(0, 4))

        ttk.Button(btn_row, text='Copy Statement', command=self._on_copy_statement).pack(side='left', padx=(0, 4))
        ttk.Button(btn_row, text='Test Condition', command=self._on_test_condition).pack(side='left', padx=(0, 4))
        ttk.Button(btn_row, text='Add to Simulation Prospects', command=self._on_add_to_simulation).pack(side='left')

        # Hook up previews to builder variable changes
        def _update_previews(*_args) -> None:  # noqa: C901
            access = self.builder_access_type_var.get().strip()
            ns = self.builder_namespace_var.get().strip()
            key = self.builder_key_var.get().strip()
            op = self.builder_operator_var.get().strip() or '='
            val = self.builder_value_var.get().strip()

            # --- Variable + condition snippet ---
            if access and ns and key:
                var_name = f'{access}.tag.{ns}.{key}'
            else:
                var_name = ''
            self.builder_variable_preview_var.set(var_name)

            snippet = ''
            if var_name:
                # For IN / NOT IN, treat the Value(s) field as a comma-separated
                # list and emit a parenthesized, quoted list consistent with the
                # condition grammar, e.g. Value(s)="abc,123" -> ('abc','123').
                if op.upper() in {'IN', 'NOT IN'}:
                    values: list[str] = []
                    if val:
                        raw_parts = [p.strip() for p in val.split(',') if p.strip()]
                        values = [p if len(p) >= 2 and p[0] == '/' and p[-1] == '/' else f"'{p}'" for p in raw_parts]
                    list_part = f"({','.join(values)})" if values else '()'
                    snippet = f'all {{ {var_name} {op} {list_part} }}'
                else:
                    # Default to scalar comparison; quoting rules are owned by the
                    # condition parser, so we keep this as a simple string.
                    value_part = f"'{val}'" if val else "''"
                    snippet = f'all {{ {var_name} {op} {value_part} }}'
            self.builder_condition_preview_var.set(snippet)

            # --- Principal / subject phrase (SimulationTab-style keys) ---
            principal_key = self.builder_principal_var.get().strip()
            subject_phrase = '<principal>'
            if principal_key:
                details = self._builder_principal_details.get(principal_key)
                if details is not None:
                    ptype, domain, name = details
                    if ptype == 'service':
                        subject_phrase = f'service {name}'
                    elif ptype in {'group', 'dynamic-group', 'user'}:
                        if domain:
                            subject_phrase = f"{ptype} '{domain}'/'{name}'"
                        else:
                            subject_phrase = f"{ptype} '{name}'"
                    elif ptype == 'group-id':
                        subject_phrase = f'group id {name}'
                    elif ptype == 'dynamic-group-id':
                        subject_phrase = f'dynamic-group id {name}'
                    else:
                        subject_phrase = name or principal_key
                else:
                    # Fallback if key not in details map
                    subject_phrase = principal_key

            # --- Resource + verb phrase ---
            verb = self.builder_verb_var.get().strip() or 'use'
            resource = self.builder_resource_var.get().strip() or '<resource>'

            # --- Location / Effective Path -> location clause rules ---
            location_raw = self.builder_location_var.get().strip() or 'root'
            eff_raw = self.builder_effective_path_var.get().strip() or location_raw

            def _split_path(path: str) -> list[str]:
                parts = [p for p in path.split('/') if p]
                return parts or ['root']

            loc_parts = _split_path(location_raw)
            eff_parts = _split_path(eff_raw)

            # Validate that the effective path is within the chosen
            # location. If not, reset Effective Path to Location and
            # inform the user once.
            if eff_parts[: len(loc_parts)] != loc_parts:
                try:
                    messagebox.showwarning(
                        'Effective Path outside Location',
                        'The selected Effective Path is not within the chosen Location. '
                        'It has been reset to match the Location.',
                    )
                except Exception:
                    logger.info('TagBasedAccessTab: unable to show warning messagebox', exc_info=True)
                self.builder_effective_path_var.set('/'.join(loc_parts))
                eff_parts = list(loc_parts)

            location_clause = ''
            # Special case: both root -> "in tenancy"
            if loc_parts == ['root'] and eff_parts == ['root']:
                location_clause = ' in tenancy'
            else:
                # If effective path extends the location path, use the trailing
                # part as the compartment name, e.g. root/x/y vs root/x/y/z -> z.
                if len(eff_parts) > len(loc_parts) and eff_parts[: len(loc_parts)] == loc_parts:
                    remaining = eff_parts[len(loc_parts) :]
                    comp_name = '/'.join(remaining)
                    location_clause = f' in compartment {comp_name}'
                elif eff_parts:
                    # Fallback: use last segment of effective path
                    location_clause = f' in compartment {eff_parts[-1]}'

            # Update location display label for clarity
            try:
                if hasattr(self, '_builder_location_display_label'):
                    self._builder_location_display_label.config(text=f"Location (Compartment): {'/'.join(loc_parts)}")
            except Exception:
                logger.info('TagBasedAccessTab: unable to update location display label', exc_info=True)

            # --- Statement synthesis ---
            if snippet:
                statement = f'Allow {subject_phrase} to {verb} {resource}{location_clause} where {snippet}'
            else:
                statement = f'Allow {subject_phrase} to {verb} {resource}{location_clause}'

            self.builder_statement_preview_var.set(statement)

        for var in (
            self.builder_principal_var,
            self.builder_resource_var,
            self.builder_location_var,
            self.builder_effective_path_var,
            self.builder_access_type_var,
            self.builder_namespace_var,
            self.builder_key_var,
            self.builder_operator_var,
            self.builder_value_var,
            # Ensure verb changes immediately refresh the generated
            # statement preview, not just other builder fields.
            self.builder_verb_var,
        ):
            var.trace_add('write', _update_previews)

        # (Previously reserved for future integration; reclaimed space
        # so the generated statement and actions remain the primary
        # focus in the right-hand column.)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_builder_values(self) -> None:
        """Refresh the builder combobox value lists from cached distincts.

        This is invoked after :meth:`populate_data` runs so that the
        lower-half builder surfaces commonly-used principals, resources,
        and effective paths observed in the loaded policies.
        """

        try:
            # Principal / subject
            principal_widget: ttk.Combobox | None = None
            resource_widget: ttk.Combobox | None = None
            location_widget: ttk.Combobox | None = None
            effective_widget: ttk.Combobox | None = None

            # The builder widgets are created in _build_builder_section;
            # store them as attributes there so we can safely configure
            # their value lists here.
            principal_widget = getattr(self, '_builder_principal_combo', None)
            resource_widget = getattr(self, '_builder_resource_combo', None)
            location_widget = getattr(self, '_builder_location_combo', None)
            effective_widget = getattr(self, '_builder_effective_path_combo', None)

            if isinstance(principal_widget, ttk.Combobox):
                principal_widget['values'] = self._builder_principals or []
            if isinstance(resource_widget, ttk.Combobox):
                # Respect the "All Possible" toggle when choosing which
                # resource domain to expose in the builder dropdown.
                if self.builder_all_possible_resources_var.get() and self._builder_all_resources:
                    resource_widget['values'] = self._builder_all_resources
                else:
                    resource_widget['values'] = self._builder_resources or []
            if isinstance(location_widget, ttk.Combobox):
                location_widget['values'] = self._builder_locations or []
            if isinstance(effective_widget, ttk.Combobox):
                effective_widget['values'] = self._builder_effective_paths or []
        except Exception:
            # Failure to refresh builder values should never break the
            # rest of the tab; log and continue.
            logger.info('TagBasedAccessTab: unable to refresh builder combobox values', exc_info=True)

    def _on_toggle_all_possible_resources(self) -> None:
        """Handle the All Possible checkbox for the Resource dropdown.

        When enabled, populate the Resource combobox with every known
        resource and family from ReferenceDataRepo. When disabled,
        revert to the in-use resources discovered from the loaded
        tenancy policies.
        """

        use_all = self.builder_all_possible_resources_var.get()

        if use_all:
            # Here use self._reference_repo and assume it is loaded
            # repo = self._ensure_reference_repo()
            repo = self._reference_repo

            # Build a combined, sorted list of resources + families so
            # that users can choose from the full known domain.
            try:
                resource_names = list(repo.data.get('resources', {}).keys())
                family_names = list(repo.data.get('families', {}).keys())
                combined = sorted(set(resource_names + family_names), key=str.lower)
                self._builder_all_resources = combined
            except Exception:
                logger.info(
                    'TagBasedAccessTab: error while building All Possible resource list; falling back to in-use list',
                    exc_info=True,
                )
                self.builder_all_possible_resources_var.set(False)
                self._builder_all_resources = []

        # Refresh the combobox value list based on the new toggle state.
        self._refresh_builder_values()

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

        logger.info('TagBasedAccessTab: manual refresh requested from UI')
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
                'TagBasedAccessTab: unable to derive selected rows from statement_table during filter refresh',
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
            logger.info('TagBasedAccessTab: unable to apply parsed-statement column toggle', exc_info=True)

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
    # Builder button callbacks (initially conservative stubs)
    # ------------------------------------------------------------------

    def _on_copy_statement(self) -> None:
        """Copy the generated statement text to the clipboard.

        This keeps behavior local to the tab and avoids cross-tab
        orchestration for now. If there is no statement text, the
        method is a no-op.
        """

        text = self.builder_statement_preview_var.get().strip()
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            logger.info('TagBasedAccessTab: unable to access clipboard to copy statement', exc_info=True)

    def _on_test_condition(self) -> None:
        """Send the generated condition snippet to the Condition Tester tab.

        If the advanced tabs (and Condition Tester) are not available,
        this method simply returns without raising.
        """
        # Delegate to the generic helper so this behavior can be reused
        # from right-click context menus and other callers.
        snippet = self.builder_condition_preview_var.get().strip()
        self._send_condition_to_tester(snippet, show_empty_message=True)

    def _on_add_to_simulation(self) -> None:
        """Add the generated statement as a prospective simulation statement.

        This implementation appends a new inline prospective row in the
        Simulation tab, runs its Parse routine, and then switches focus
        to the Simulation tab so the user can review/save it.
        """

        statement = self.builder_statement_preview_var.get().strip()
        if not statement:
            return

        app = getattr(self, 'app', None)
        if not app:
            return

        sim_tab = getattr(app, 'simulation_tab', None)
        if sim_tab is None:
            return

        # Prefer Effective Path, then Location, then ROOT
        compartment_path = (
            self.builder_effective_path_var.get().strip() or self.builder_location_var.get().strip() or 'ROOT'
        )

        # Optional: derive a friendly description from tag namespace/key
        ns = self.builder_namespace_var.get().strip()
        key = self.builder_key_var.get().strip()
        if ns and key:
            desc = f'Tag builder: {ns}.{key}'
        else:
            desc = 'Tag-based builder statement'

        try:
            if hasattr(sim_tab, 'add_prospective_statement_from_builder'):
                sim_tab.add_prospective_statement_from_builder(
                    statement_text=statement,
                    compartment_path=compartment_path,
                    description=desc,
                )

            # Bring the Simulation tab to the foreground
            if hasattr(app, 'notebook'):
                app.notebook.select(sim_tab)
        except Exception:
            logger.info(
                'TagBasedAccessTab: error while adding statement to Simulation prospects',
                exc_info=True,
            )

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
                        'TagBasedAccessTab: unable to show info messagebox for empty condition snippet',
                        exc_info=True,
                    )
            return

        logger.info('TagBasedAccessTab: sending condition to tester: %r', snippet)

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
                        'TagBasedAccessTab: unable to select Condition Tester tab on notebook',
                        exc_info=True,
                    )
        except Exception:
            logger.info('TagBasedAccessTab: error while sending snippet to Condition Tester', exc_info=True)

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
