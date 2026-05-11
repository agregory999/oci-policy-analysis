##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# prospective_editor_window.py
#
# Toplevel editor for tenancy-scoped prospective (what-if) policy
# statements. Provides a CRUD UI over ProspectiveStatementsService and a
# flexible statement builder area (including tag-based where-clause
# support) for synthesizing new statements.
#
# Supports Python 3.12 and above
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from oci_policy_analysis.application.core.common.builder_helpers import (
    build_full_statement,
    build_location_clause,
    build_subject_phrase,
    build_tag_variable_and_snippet,
)
from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.services.prospective_statements_service import (
    ProspectiveStatementsService,
)
from oci_policy_analysis.common.logger import get_logger

logger = get_logger(component='prospective_editor_window')


class ProspectiveEditorWindow(tk.Toplevel):  # noqa: D401
    """Toplevel editor for tenancy-scoped prospective statements.

    Layout (first iteration):

    * Top: table-style rows showing existing prospective statements for
      the active tenancy (Location / Description / Statement Text) with
      per-row Delete buttons.
    * Bottom: Save & Close button row to persist via
      :class:`ProspectiveStatementsService`.
    * Right now, the Tag-based builder is not yet integrated; the
      initial goal is to stand up a simple CRUD editor on top of the
      new service. The builder section will be added in a follow-on
      patch, reusing logic from TagBasedAccessTab.
    """

    def __init__(self, parent: tk.Widget, app) -> None:  # noqa: D401
        """Create the top-level prospective statement editor window.

        The heavy UI construction work is delegated to helper methods so
        that ``__init__`` remains a high-level orchestration entrypoint
        and is easier to read/maintain. This window is only created on
        demand (when the user opens the Prospective editor), so a small
        amount of upfront work here is acceptable.
        """

        super().__init__(parent)
        self.app = app
        self.service: ProspectiveStatementsService | None = getattr(app, 'prospective_service', None)
        self.policy_repo = getattr(app, 'policy_compartment_analysis', None)
        self.reference_repo = getattr(app, 'reference_data_repo', None)

        logger.info('Opening for current tenancy')

        # Basic window chrome + pre-flight service check
        self._configure_window_chrome()
        if self.service is None:
            # _configure_window_chrome() may still succeed even when the
            # service is missing; in that case we show a warning and
            # close immediately.
            logger.info('Prospective service missing on app; editor will not open.')
            messagebox.showwarning(
                'Prospective Service Unavailable',
                'The ProspectiveStatementsService is not available for this tenancy. '
                'Prospective editor cannot be opened.',
            )
            self.destroy()
            return

        # Build the intro text + CRUD rows + builder + bottom buttons.
        # The add_row callback and row models are wired up by the CRUD
        # section and reused by the builder and Save/Close handlers.
        self._build_intro_section()
        self._build_crud_section()
        self._build_builder_section()
        self._build_bottom_buttons()

        # Seed builder dropdowns (resources, locations, principals) now
        # that the UI widgets exist.
        self._initialize_builder_locations_and_effective_paths()
        self._refresh_builder_resource_values()
        self._initialize_builder_principals_from_repo()

    # ------------------------------------------------------------------
    # Top-level window + intro
    # ------------------------------------------------------------------

    def _configure_window_chrome(self) -> None:
        """Configure basic window properties (title, modality, background)."""

        self.title('Manage Prospective Policy Statements')
        try:
            self.transient(self.winfo_toplevel())
        except Exception:
            # Best-effort only; not critical.
            pass
        self.grab_set()

        # Match main app background if possible to avoid stark white
        # on themed environments.
        try:
            bg = ttk.Style().lookup('TFrame', 'background') or self.cget('background')
        except Exception:
            bg = '#f0f0f0'
        self.configure(background=bg)

    def _build_intro_section(self) -> None:
        """Create the static intro text at the top of the window."""

        intro = (
            'Manage prospective (what-if) policy statements for the active tenancy.\n'
            'These statements are evaluated alongside real tenancy policies '
            'during simulation when they are in scope for the selected environment.'
        )
        intro_lbl = ttk.Label(self, text=intro, wraplength=760, justify='left')
        intro_lbl.pack(fill='x', padx=8, pady=(8, 4))

    # ------------------------------------------------------------------
    # CRUD editor section
    # ------------------------------------------------------------------

    def _build_crud_section(self) -> None:  # noqa: C901
        """Build the top CRUD editor section for existing statements."""

        # --- Top: CRUD editor over prospective statements ---
        rows_frame = ttk.LabelFrame(self, text='Prospective Policy Statements (CRUD)')
        rows_frame.pack(fill='both', expand=True, padx=8, pady=(0, 4))

        # Header + body share a single grid so columns align with rows
        rows_frame.columnconfigure(0, weight=1)

        header = ttk.Frame(rows_frame)
        header.grid(row=0, column=0, sticky='ew', padx=2, pady=(2, 0))
        header.columnconfigure(0, weight=2)
        header.columnconfigure(1, weight=2)
        header.columnconfigure(2, weight=5)
        header.columnconfigure(3, weight=0)
        header.columnconfigure(4, weight=0)

        ttk.Label(header, text='Location (Compartment)').grid(row=0, column=0, sticky='w', padx=2)
        ttk.Label(header, text='Description').grid(row=0, column=1, sticky='w', padx=2)
        ttk.Label(header, text='Statement Text').grid(row=0, column=2, sticky='w', padx=2)
        ttk.Label(header, text='Status').grid(row=0, column=3, sticky='w', padx=2)
        ttk.Label(header, text='Actions').grid(row=0, column=4, sticky='w', padx=2)

        body = ttk.Frame(rows_frame)
        body.grid(row=1, column=0, sticky='nsew', padx=2, pady=(2, 2))
        rows_frame.rowconfigure(1, weight=1)

        self._row_models: list[dict[str, object]] = []
        self._rows_body = body

        # Cache compartments for dropdown (same list SimulationTab uses)
        try:
            sim_tab = getattr(self.app, 'simulation_tab', None)
            compartments = list(getattr(sim_tab, '_sim_index_compartments', []) or ['ROOT']) if sim_tab else ['ROOT']
        except Exception:
            compartments = ['ROOT']

        def add_row(initial: dict | None = None) -> dict[str, object]:  # noqa: C901
            """Create a single editable row bound to an existing or new record."""

            idx = len(self._row_models)
            row: dict[str, object] = {}

            loc_var = tk.StringVar(
                value=(initial or {}).get('compartment_path') or (compartments[0] if compartments else 'ROOT')
            )
            desc_var = tk.StringVar(value=(initial or {}).get('description') or '')
            text_var = tk.StringVar(value=(initial or {}).get('statement_text') or '')

            frame = ttk.Frame(body)
            frame.grid(row=idx * 2, column=0, sticky='ew', pady=(1, 0))
            frame.columnconfigure(0, weight=2)
            frame.columnconfigure(1, weight=2)
            frame.columnconfigure(2, weight=5)
            frame.columnconfigure(3, weight=0)

            # Second row for parse notes spans full width
            notes_var = tk.StringVar(value='')
            notes_lbl = ttk.Label(
                body,
                textvariable=notes_var,
                foreground='dark orange',
                font=('TkDefaultFont', 9, 'italic'),
                wraplength=720,
                justify='left',
            )
            # Use grid_remove so the widget exists (and can be updated)
            # but is only made visible when we actually have a message.
            notes_lbl.grid(row=idx * 2 + 1, column=0, sticky='w', padx=6, pady=(0, 4))
            notes_lbl.grid_remove()

            loc_cb = ttk.Combobox(frame, textvariable=loc_var, values=compartments, width=28, state='readonly')
            loc_cb.grid(row=0, column=0, padx=2, sticky='ew')

            desc_container = ttk.Frame(frame)
            desc_container.grid(row=0, column=1, padx=2, sticky='nsew')
            frame.columnconfigure(1, weight=2)

            desc_widget = tk.Text(
                desc_container,
                height=2,
                wrap='word',
                width=30,
            )
            desc_widget.pack(side='left', fill='both', expand=True)

            if desc_var.get():
                desc_widget.insert('1.0', desc_var.get())

            def _sync_desc_var(_event: object | None = None) -> None:
                try:
                    current = desc_widget.get('1.0', 'end-1c')
                except Exception:
                    current = ''
                desc_var.set(current)

            desc_widget.bind('<FocusOut>', _sync_desc_var)
            desc_widget.bind('<KeyRelease>', _sync_desc_var)

            desc_scroll_y = ttk.Scrollbar(desc_container, orient='vertical', command=desc_widget.yview)
            desc_scroll_y.pack(side='right', fill='y')
            desc_widget.configure(yscrollcommand=desc_scroll_y.set)

            # Use a small multi-line, scrollable text widget for the
            # statement text so longer policies are easier to read
            # while still keeping each row compact. We keep a
            # StringVar in the row model so the rest of the logic can
            # continue to treat statement_text as a simple string.
            text_container = ttk.Frame(frame)
            text_container.grid(row=0, column=2, padx=2, sticky='nsew')
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(2, weight=5)

            text_widget = tk.Text(
                text_container,
                height=2,  # roughly two lines high
                wrap='word',  # wrap on word boundaries for readability
            )
            text_widget.pack(side='left', fill='both', expand=True)

            # Seed initial value
            if text_var.get():
                text_widget.insert('1.0', text_var.get())

            # Keep the StringVar and Text widget in sync. We only
            # need to push Text -> StringVar before consumers read it.
            def _sync_text_var(event: object | None = None) -> None:
                try:
                    current = text_widget.get('1.0', 'end-1c')
                except Exception:
                    current = ''
                text_var.set(current)

            # Update the bound StringVar whenever focus leaves the
            # widget or the user types. This keeps things in sync for
            # validation and save operations.
            text_widget.bind('<FocusOut>', _sync_text_var)
            text_widget.bind('<KeyRelease>', _sync_text_var)

            # Add a vertical scrollbar so very long statements remain
            # navigable without making the row excessively tall.
            scroll_y = ttk.Scrollbar(text_container, orient='vertical', command=text_widget.yview)
            scroll_y.pack(side='right', fill='y')
            text_widget.configure(yscrollcommand=scroll_y.set)

            status_var = tk.StringVar(value='Not parsed')
            status_lbl = ttk.Label(frame, textvariable=status_var, width=12, foreground='#555')
            status_lbl.grid(row=0, column=3, padx=2, sticky='w')

            # We keep a reference to the service record id (if known)
            record_id: str | None = (initial or {}).get('id')  # type: ignore[assignment]
            if record_id is None and self.service is not None:
                try:
                    rec = self.service.create(
                        loc_var.get().strip() or 'ROOT',
                        desc_var.get().strip(),
                        text_var.get().strip(),
                    )
                    record_id = rec.id
                except Exception:
                    logger.warning('Unable to create prospective record during row initialization', exc_info=True)

            # Initialize status/notes based on any persisted validation state
            initial_data = initial or {}
            status_initialized = False

            def _initialize_status_from_initial_data(data: dict[str, object], show_notes: bool = True) -> None:
                nonlocal status_initialized

                if not isinstance(data, dict):
                    return

                reasons_raw = data.get('invalid_reasons')
                reasons: list[str] = []
                if isinstance(reasons_raw, str) and reasons_raw.strip():
                    reasons = [reasons_raw.strip()]
                elif isinstance(reasons_raw, (list | tuple | set)):
                    reasons = [str(reason).strip() for reason in reasons_raw if str(reason).strip()]

                parsed_flag = bool(data.get('parsed'))
                valid_flag = bool(data.get('valid'))

                if show_notes:
                    notes_lbl.grid()
                else:
                    notes_lbl.grid_remove()

                if reasons:
                    notes_var.set('; '.join(reasons))
                    status_var.set('Invalid')
                    status_initialized = True
                    return

                if parsed_flag and valid_flag:
                    status_var.set('Parsed')
                    notes_var.set('')
                    if show_notes:
                        notes_lbl.grid_remove()
                    status_initialized = True
                    return

                if parsed_flag and not valid_flag:
                    status_var.set('Invalid')
                    notes_var.set('')
                    if show_notes:
                        notes_lbl.grid_remove()
                    status_initialized = True

            _initialize_status_from_initial_data(initial_data, show_notes=True)

            if not status_initialized:
                if text_var.get().strip():
                    status_var.set('Not parsed')
                else:
                    status_var.set('Not parsed')
                notes_var.set('')
                notes_lbl.grid_remove()

            def on_parse() -> None:  # noqa: C901
                """Validate this row's statement using the simulation engine/service."""

                stmt_text = text_var.get().strip()
                if not stmt_text:
                    status_var.set('Enter statement text')
                    notes_var.set('')
                    notes_lbl.grid_remove()
                    return

                # Prefer the service's validate helper when available so
                # parsed/normalized state is recorded centrally.
                rid_obj = row.get('record_id')

                def _ensure_principals(normalized: dict[str, object]) -> None:
                    subject_type = str(normalized.get('subject_type') or '').strip()
                    subjects = normalized.get('subject')
                    if not subject_type:
                        return

                    subj_list = subjects if isinstance(subjects, list) else [subjects]
                    principals: list[dict[str, object]] = []

                    if subject_type in ('any-user', 'any-group', 'service'):
                        for subj in subj_list:
                            name = str(subj or subject_type).strip()
                            if not name:
                                continue
                            key = calculate_principal_key(subject_type, None, name)
                            principals.append(
                                {
                                    'principal_type': subject_type,
                                    'principal_key': key,
                                    'display_name': name,
                                    'name': name,
                                }
                            )
                    elif subject_type in ('group-id', 'dynamic-group-id'):
                        for subj in subj_list:
                            ocid = str(subj or '').strip()
                            if not ocid:
                                continue
                            key = f'{subject_type}:{ocid}'
                            principals.append(
                                {
                                    'principal_type': subject_type,
                                    'principal_key': key,
                                    'ocid': ocid,
                                    'display_name': ocid,
                                    'name': ocid,
                                }
                            )
                    else:
                        for subj in subj_list:
                            if isinstance(subj, (tuple | list)) and len(subj) == 2:
                                domain, name = subj
                            elif isinstance(subj, str):
                                domain, name = None, subj
                            else:
                                continue
                            name_str = str(name or '').strip()
                            if not name_str:
                                continue
                            domain_val = str(domain).strip() if isinstance(domain, str) and domain.strip() else None
                            key = calculate_principal_key(subject_type, domain_val, name_str)
                            display = f'{domain_val}/{name_str}' if domain_val else name_str
                            principals.append(
                                {
                                    'principal_type': subject_type,
                                    'principal_key': key,
                                    'domain_name': domain_val,
                                    'display_name': display,
                                    'name': name_str,
                                }
                            )

                    if principals:
                        normalized['principals'] = principals
                        if len(principals) == 1:
                            normalized['principal_key'] = principals[0]['principal_key']

                if self.service is not None and isinstance(rid_obj, str):
                    rid: str = rid_obj
                    try:
                        logger.info(f'Validating statement: {stmt_text}')
                        logger.info(
                            'Requesting effective path calculation for record %s via ProspectiveStatementsService', rid
                        )
                        rec = self.service.get(rid)
                        if rec is None:
                            rec = self.service.create(
                                loc_var.get().strip() or 'ROOT',
                                desc_var.get().strip(),
                                stmt_text,
                            )
                            row['record_id'] = rec.id
                            rid = rec.id
                        else:
                            rec.compartment_path = loc_var.get().strip() or 'ROOT'
                            rec.description = desc_var.get().strip()
                        updated = self.service.validate_and_update_text(rid, stmt_text)
                        if isinstance(updated.normalized, dict):
                            _ensure_principals(updated.normalized)
                            try:
                                # Ensure the updated normalized principals are retained in the service cache
                                # so downstream tabs (Policies, Simulation) can see them immediately.
                                self.service.upsert(updated)
                            except Exception:
                                logger.info(
                                    'ProspectiveEditorWindow: unable to upsert updated record after principal calc',
                                    exc_info=True,
                                )
                        logger.info(f'Validation result for {rid} -> parsed={updated.parsed}, valid={updated.valid}')
                        logger.info(
                            'Effective path for record %s resolved to %s',
                            rid,
                            getattr(updated, 'effective_path', '<none>'),
                        )
                        if updated.parsed and updated.valid:
                            status_var.set('Parsed')
                            notes_var.set('')
                            notes_lbl.grid_remove()
                        elif updated.invalid_reasons:
                            # Treat any non-empty invalid_reasons list as a
                            # hard validation failure, even when parsed is
                            # False. This ensures ANTLR parse errors are
                            # captured and surfaced while still allowing the
                            # user to save the statement for later fixing.
                            status_var.set('Invalid')
                            reasons = updated.invalid_reasons or []
                            message = '; '.join(reasons)
                            notes_var.set(message)
                            notes_lbl.grid()
                            try:
                                messagebox.showwarning(
                                    'Prospective Statement Parse Error',
                                    (
                                        message + '\n\nYou can still save this prospective statement, '
                                        "but it will be marked invalid and searchable via 'Invalid Only' in the Policies tab."
                                    ),
                                )
                            except Exception:
                                logger.info('Unable to show parse-error messagebox (service path)', exc_info=True)
                        else:
                            status_var.set('Not parsed')
                    except Exception:
                        logger.warning(f'Error during validate_and_update_text for {rid}', exc_info=True)
                        status_var.set('Error')
                        notes_var.set('Error while validating prospective statement; see logs for details.')
                        notes_lbl.grid()
                    return

                # Fallback: use simulation_engine directly if service/id
                # are not available.
                engine = getattr(self.app, 'simulation_engine', None)
                if engine is None or not hasattr(engine, 'validate_prospective_statement'):
                    status_var.set('Engine N/A')
                    notes_var.set('Simulation engine does not expose prospective validation.')
                    notes_lbl.grid()
                    return
                try:
                    logger.info(f'Validating via engine only (no service id); length={len(stmt_text)}')
                    result = engine.validate_prospective_statement(stmt_text)
                    normalized = result.get('normalized')
                    if isinstance(normalized, dict):
                        _ensure_principals(normalized)
                    parsed = bool(result.get('parsed'))
                    valid = bool(result.get('valid'))
                    reasons = result.get('invalid_reasons') or []
                    message = '; '.join(reasons)

                    if parsed and valid:
                        status_var.set('Parsed')
                        notes_var.set('')
                        notes_lbl.grid_remove()
                    elif reasons:
                        # Same semantics as the service-backed path: any
                        # diagnostics mean the statement is considered
                        # invalid, but the user is allowed to keep and save
                        # it. This supports editing and later repair while
                        # still making invalid prospective rows visible to
                        # Policies tab filters.
                        status_var.set('Invalid')
                        notes_var.set(message)
                        notes_lbl.grid()
                        try:
                            messagebox.showwarning(
                                'Prospective Statement Parse Error',
                                (
                                    message + '\n\nYou can still save this prospective statement, '
                                    "but it will be marked invalid and searchable via 'Invalid Only' in the Policies tab."
                                ),
                            )
                        except Exception:
                            logger.info('Unable to show parse-error messagebox (engine path)', exc_info=True)
                    else:
                        status_var.set('Not parsed')
                except Exception:
                    logger.warning('Error during validate_prospective_statement', exc_info=True)
                    status_var.set('Error')
                    notes_var.set('Error while validating prospective statement; see logs for details.')
                    notes_lbl.grid()

            def on_delete() -> None:
                # If this row corresponds to an existing record, delete it
                rid = row.get('record_id')
                if isinstance(rid, str) and self.service is not None:
                    try:
                        logger.info(f'Deleting record_id={rid}')
                        self.service.delete(rid)
                    except Exception:
                        logger.warning(f'Error deleting record {rid} from service', exc_info=True)

                frame.destroy()
                notes_lbl.destroy()
                if row in self._row_models:
                    self._row_models.remove(row)

            # Parse and Delete side by side
            ttk.Button(frame, text='Parse', command=on_parse, width=7).grid(
                row=0, column=4, padx=(2, 1), pady=0, sticky='w'
            )
            ttk.Button(frame, text='Delete', command=on_delete, width=7).grid(
                row=0, column=5, padx=(1, 2), pady=0, sticky='w'
            )

            row.update(
                {
                    'frame': frame,
                    'loc_var': loc_var,
                    'desc_var': desc_var,
                    'text_var': text_var,
                    'status_var': status_var,
                    'notes_var': notes_var,
                    'record_id': record_id,
                    'on_parse': on_parse,
                    'initialize_status': lambda data, show_notes=True: _initialize_status_from_initial_data(
                        data, show_notes
                    ),
                }
            )
            self._row_models.append(row)
            return row

        self._add_row = add_row

        # Seed from existing service records
        service = self.service
        try:
            existing_records = list(service.list_all()) if service is not None else []
            logger.info(f'Loaded {len(existing_records)} existing prospective statements for editor')
        except Exception:
            logger.warning('Error while listing prospective records from service', exc_info=True)
            existing_records = []

        if existing_records:
            for rec in existing_records:
                add_row(
                    {
                        'id': rec.id,
                        'compartment_path': rec.compartment_path,
                        'description': rec.description,
                        'statement_text': rec.statement_text,
                        'parsed': rec.parsed,
                        'valid': rec.valid,
                        'invalid_reasons': list(rec.invalid_reasons or []),
                    }
                )
        else:
            logger.info('No existing records; seeding with single empty row')
            add_row({})

        # Add Free-Form Statement button below the current rows
        add_free_btn = ttk.Button(rows_frame, text='Add Free-Form Statement', command=lambda: add_row({}))
        add_free_btn.grid(row=2, column=0, sticky='w', padx=6, pady=(2, 4))

    # ------------------------------------------------------------------
    # Builder section
    # ------------------------------------------------------------------

    def _build_builder_section(self) -> None:  # noqa: C901
        """Build the bottom prospective statement builder area."""

        # --- Bottom: Prospective statement builder (full-width) ---
        builder_frame = ttk.LabelFrame(self, text='Prospective Statement Builder')
        builder_frame.pack(fill='x', expand=False, padx=8, pady=(0, 6))

        # Simple builder variables (mirroring TagBasedAccessTab, but
        # generalized so that the builder can be used for both
        # tag-based and non-tag-based statements.
        self.builder_action_var = tk.StringVar(value='Allow')
        self.builder_principal_var = tk.StringVar()
        self.builder_include_default_var = tk.BooleanVar(value=False)
        self.builder_verb_var = tk.StringVar(value='use')
        self.builder_resource_var = tk.StringVar()
        self.builder_location_var = tk.StringVar()
        self.builder_effective_path_var = tk.StringVar()
        self.builder_where_mode_var = tk.StringVar(value='No Where Clause')
        # Shared helper text for the right-hand WHERE-clause area
        self.where_help_text = tk.StringVar(value='')
        self.builder_access_type_var = tk.StringVar()
        self.builder_namespace_var = tk.StringVar()
        self.builder_key_var = tk.StringVar()
        self.builder_operator_var = tk.StringVar()
        self.builder_value_var = tk.StringVar()
        self.builder_variable_preview_var = tk.StringVar()
        self.builder_condition_preview_var = tk.StringVar()
        self.builder_statement_preview_var = tk.StringVar()

        # When enabled, Resource dropdown in the builder will show all
        # known resources/families from reference data, not just those
        # seen in existing policies. This allows building statements
        # even for resources not yet present in existing policies.
        self.builder_all_possible_resources_var = tk.BooleanVar(value=False)
        self._builder_resources: list[str] = []
        self._builder_all_resources: list[str] = []

        # Location/effective-path choices (compartment paths) seeded
        # from SimulationTab's index when available. To keep behavior
        # consistent with TagBasedAccessTab, we default both Location
        # and Effective Path lists to the simulation tab's
        # _sim_index_compartments (effective paths) when present.
        self._builder_locations: list[str] = []
        # Principal choices (normalized keys) and detail map mirroring
        # TagBasedAccessTab so subject phrases are consistent.
        self._builder_principals: list[str] = []
        self._builder_principal_details: dict[str, tuple[str, str | None, str]] = {}
        self._builder_effective_paths: list[str] = []

        builder_frame.columnconfigure(0, weight=1)

        # Content row: two-column builder area (left/right)
        content_row = ttk.Frame(builder_frame)
        content_row.grid(row=0, column=0, sticky='nsew', padx=0, pady=0)
        content_row.columnconfigure(0, weight=1)
        content_row.columnconfigure(1, weight=1)

        # Left column: action/subject/verb/resource/location/where-mode selector
        left = ttk.Frame(content_row)
        left.grid(row=0, column=0, sticky='nsew', padx=(6, 3), pady=6)

        ttk.Label(left, text='Action').grid(row=0, column=0, sticky='w')
        ttk.Combobox(
            left,
            textvariable=self.builder_action_var,
            values=['Allow', 'Deny'],
            width=10,
            state='readonly',
        ).grid(row=0, column=1, padx=3, pady=2, sticky='w')

        ttk.Label(left, text='Principal').grid(row=1, column=0, sticky='w')
        self.builder_principal_combo = ttk.Combobox(
            left,
            textvariable=self.builder_principal_var,
            width=28,
            state='readonly',
            values=self._builder_principals,
        )
        self.builder_principal_combo.grid(row=1, column=1, padx=3, pady=2, sticky='we')

        # When enabled, keep the Default domain in the generated principal
        ttk.Checkbutton(
            left,
            text='Include Default',
            variable=self.builder_include_default_var,
        ).grid(row=1, column=2, padx=(6, 0), pady=2, sticky='w')

        ttk.Label(left, text='Verb').grid(row=2, column=0, sticky='w')
        ttk.Combobox(
            left,
            textvariable=self.builder_verb_var,
            values=['inspect', 'read', 'use', 'manage'],
            width=28,
            state='readonly',
        ).grid(row=2, column=1, padx=3, pady=2, sticky='we')

        ttk.Label(left, text='Resource').grid(row=3, column=0, sticky='w')
        self.builder_resource_combo = ttk.Combobox(
            left,
            textvariable=self.builder_resource_var,
            width=18,
            state='readonly',
            values=self._builder_resources,
        )
        self.builder_resource_combo.grid(row=3, column=1, padx=3, pady=2, sticky='we')

        # All Resources checkbox similar to TagBasedAccessTab
        self.builder_all_resources_chk = ttk.Checkbutton(
            left,
            text='All Possible Resources',
            variable=self.builder_all_possible_resources_var,
            command=self._on_toggle_all_possible_resources,
        )
        self.builder_all_resources_chk.grid(row=3, column=2, padx=(6, 0), pady=2, sticky='w')

        ttk.Label(left, text='Location / Compartment').grid(row=4, column=0, sticky='w')
        self.builder_location_combo = ttk.Combobox(
            left,
            textvariable=self.builder_location_var,
            width=28,
            state='readonly',
            values=self._builder_locations,
        )
        self.builder_location_combo.grid(row=4, column=1, padx=3, pady=2, sticky='we')

        ttk.Label(left, text='Effective Path').grid(row=5, column=0, sticky='w')
        self.builder_effective_path_combo = ttk.Combobox(
            left,
            textvariable=self.builder_effective_path_var,
            width=28,
            state='readonly',
            values=self._builder_effective_paths,
        )
        self.builder_effective_path_combo.grid(row=5, column=1, padx=3, pady=2, sticky='we')

        # Where Clause mode selector under Effective Path
        ttk.Label(left, text='Where Clause').grid(row=6, column=0, sticky='w')
        self.builder_where_mode_combo = ttk.Combobox(
            left,
            textvariable=self.builder_where_mode_var,
            values=['No Where Clause', 'Tag-based Where Clause', 'Other Where Clause'],
            width=28,
            state='readonly',
        )
        self.builder_where_mode_combo.grid(row=6, column=1, padx=3, pady=2, sticky='we')

        # Compact helper text explaining how Location and Effective Path
        # interact. We keep it visually subtle to avoid overwhelming the
        # builder, but explicit enough that users understand that
        # Location controls where the statement lives in the hierarchy
        # while Effective Path controls the "in compartment ..." portion
        # of the generated policy text. When Effective Path is left
        # blank, it defaults to the Location/Compartment value.
        ttk.Label(
            left,
            text=(
                'Location / Compartment is where in the hierarchy this  prospective statement will live. '
                'Effective Path controls the location part of the generated policy text (for example:'
                " 'in compartment ...'). If Effective Path is not set, it will default to the Location / Compartment."
            ),
            wraplength=500,
            justify='left',
            foreground='#555555',
        ).grid(row=7, column=0, columnspan=3, sticky='w', padx=3, pady=(4, 2))

        # Right column container (for different where-clause modes)
        right_container = ttk.Frame(content_row)
        right_container.grid(row=0, column=1, sticky='nsew', padx=(3, 6), pady=6)
        right_container.columnconfigure(0, weight=1)

        # Shared help label for all where-clause modes
        self.builder_verb_var = tk.StringVar(value='use')
        where_help_lbl = ttk.Label(right_container, textvariable=self.where_help_text, wraplength=500, justify='left')
        where_help_lbl.grid(row=0, column=0, sticky='w', pady=(0, 6))

        # Tag-based where-clause frame (existing form)
        self.tag_where_frame = ttk.Frame(right_container)
        self.tag_where_frame.grid(row=1, column=0, sticky='nsew')
        self.tag_where_frame.columnconfigure(1, weight=1)

        # Free-form where-clause frame (for "Other Where Clause")
        self.other_where_frame = ttk.Frame(right_container)
        self.other_where_frame.grid(row=1, column=0, sticky='nsew')
        self.other_where_frame.columnconfigure(0, weight=1)
        self.other_where_frame.grid_remove()

        # Simple info-only frame for "No Where Clause" mode
        self.no_where_frame = ttk.Frame(right_container)
        self.no_where_frame.grid(row=1, column=0, sticky='nsew')
        self.no_where_frame.columnconfigure(0, weight=1)
        self.no_where_frame.grid_remove()

        # Tag-based where clause controls (existing UI)
        right = self.tag_where_frame

        ttk.Label(right, text='Access Type').grid(row=0, column=0, sticky='w')
        ttk.Combobox(
            right,
            textvariable=self.builder_access_type_var,
            values=[
                'request.principal.group',
                'request.principal.compartment',
                'target.resource',
                'target.resource.compartment',
            ],
            width=38,
            state='readonly',
        ).grid(row=0, column=1, padx=3, pady=2, sticky='w')

        ttk.Label(right, text='Tag Namespace').grid(row=1, column=0, sticky='w')
        ttk.Entry(right, textvariable=self.builder_namespace_var, width=40).grid(
            row=1, column=1, padx=3, pady=2, sticky='w'
        )

        ttk.Label(right, text='Tag Key').grid(row=2, column=0, sticky='w')
        ttk.Entry(right, textvariable=self.builder_key_var, width=40).grid(row=2, column=1, padx=3, pady=2, sticky='w')

        ttk.Label(right, text='Operator').grid(row=3, column=0, sticky='w')
        ttk.Combobox(
            right,
            textvariable=self.builder_operator_var,
            values=['=', '!=', 'IN', 'NOT IN'],
            width=12,
            state='readonly',
        ).grid(row=3, column=1, padx=3, pady=2, sticky='w')

        ttk.Label(right, text='Value(s)').grid(row=4, column=0, sticky='w')
        ttk.Entry(right, textvariable=self.builder_value_var, width=40).grid(
            row=4, column=1, padx=3, pady=2, sticky='w'
        )

        preview = ttk.Frame(right)
        preview.grid(row=5, column=0, columnspan=2, sticky='w', pady=(6, 2))
        ttk.Label(preview, text='Generated variable:').grid(row=0, column=0, sticky='w')
        ttk.Label(preview, textvariable=self.builder_variable_preview_var, foreground='#006699').grid(
            row=0, column=1, sticky='w', padx=(4, 0)
        )
        ttk.Label(preview, text='Condition snippet:').grid(row=1, column=0, sticky='w')
        ttk.Label(preview, textvariable=self.builder_condition_preview_var, foreground='#006699').grid(
            row=1, column=1, sticky='w', padx=(4, 0)
        )

        # Free-form WHERE clause editor (for "Other Where Clause")
        self.builder_other_where_text = tk.Text(
            self.other_where_frame,
            height=4,
            wrap='word',
        )
        self.builder_other_where_text.grid(row=0, column=0, sticky='nsew', pady=(0, 2))
        other_scroll = ttk.Scrollbar(
            self.other_where_frame, orient='vertical', command=self.builder_other_where_text.yview
        )
        other_scroll.grid(row=0, column=1, sticky='ns')
        self.builder_other_where_text.configure(yscrollcommand=other_scroll.set)

        def _open_condition_docs(_event: object | None = None) -> None:
            url = 'https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/conditions.htm'
            try:
                opened = webbrowser.open_new_tab(url)
                if not opened:
                    raise RuntimeError('Unable to open link')
            except Exception:
                messagebox.showinfo('Open Link', f'Open this link in your browser:\n{url}')

        def _safe_bg(widget: tk.Widget | None, fallback: str | None = None) -> str | None:
            try:
                return widget.cget('background')  # type: ignore[call-arg]
            except Exception:
                return fallback

        link_bg = (
            _safe_bg(
                self.other_where_frame,
                _safe_bg(builder_frame, _safe_bg(self if isinstance(self, tk.Widget) else None, '#f0f0f0')),
            )
            or '#f0f0f0'
        )
        condition_link = tk.Label(
            self.other_where_frame,
            text='Condition Reference Documentation',
            fg='#0645AD',
            cursor='hand2',
            font=('TkDefaultFont', 10, 'underline'),
            bg=link_bg,
            activebackground=link_bg,
        )
        condition_link.grid(row=1, column=0, sticky='w', pady=(0, 4))
        condition_link.bind('<Button-1>', _open_condition_docs)
        condition_link.bind('<Return>', _open_condition_docs)

        # Keep custom WHERE editor in sync with previews as the user types
        def _on_other_where_key(_event: object | None = None) -> None:
            try:
                # Trigger a full preview refresh so the generated
                # statement reflects the latest WHERE text.
                _update_builder_previews()
            except Exception:
                logger.info('Error while updating previews from custom WHERE editor', exc_info=True)

        self.builder_other_where_text.bind('<KeyRelease>', _on_other_where_key)

        # Info-only content for "No Where Clause" mode
        ttk.Label(
            self.no_where_frame,
            text='',
            justify='left',
        ).grid(row=0, column=0, sticky='w')

        # Horizontal separator before the full-width location/statement/controls
        sep = ttk.Separator(builder_frame, orient='horizontal')
        sep.grid(row=1, column=0, sticky='ew', padx=6, pady=(4, 4))

        # Full-width area for Location / Compartment, generated statement, and Add button
        bottom_builder = ttk.Frame(builder_frame)
        bottom_builder.grid(row=2, column=0, sticky='ew', padx=6, pady=(0, 4))
        bottom_builder.columnconfigure(0, weight=0)
        bottom_builder.columnconfigure(1, weight=1)
        bottom_builder.columnconfigure(2, weight=0)

        # Mirror Location / Compartment next to generated statement
        ttk.Label(bottom_builder, text='Location / Compartment (of prospective statement):').grid(
            row=0, column=0, sticky='nw'
        )
        ttk.Label(
            bottom_builder,
            textvariable=self.builder_location_var,
            foreground='#003366',
            font=('TkFixedFont', 9),
            wraplength=260,
            justify='left',
        ).grid(row=0, column=1, sticky='nw', padx=(4, 8))

        ttk.Label(bottom_builder, text='Generated policy statement:').grid(row=1, column=0, sticky='nw', pady=(4, 0))
        ttk.Label(
            bottom_builder,
            textvariable=self.builder_statement_preview_var,
            foreground='#003366',
            font=('TkFixedFont', 9),
            wraplength=640,
            justify='left',
        ).grid(row=1, column=1, sticky='nw', padx=(4, 8), pady=(4, 0))

        # Builder-level action row (inside the LabelFrame) for adding
        # the generated statement into the CRUD list. Button is placed
        # to the right of the Location/Generated statement display.
        builder_actions = ttk.Frame(bottom_builder)
        builder_actions.grid(row=0, column=2, rowspan=2, sticky='ne', padx=(6, 0), pady=(0, 0))

        def on_add_from_builder() -> None:
            """Append a new row based on the current builder statement."""

            stmt = (self.builder_statement_preview_var.get() or '').strip()
            if not stmt:
                messagebox.showinfo(
                    'No Statement',
                    'There is no generated statement to add. Please fill in the builder fields first.',
                )
                return

            # The row's compartment_path represents where the prospective
            # policy statement *lives* (policy location), not the statement's
            # effective scope. Effective scope is encoded in statement text
            # (e.g. "in compartment ...") and resolved later by parser/
            # intelligence logic.
            loc = (self.builder_location_var.get() or 'ROOT').strip()
            ns = (self.builder_namespace_var.get() or '').strip()
            key = (self.builder_key_var.get() or '').strip()

            # Build a human-friendly description using the same subject phrase
            # that appears in the generated statement, plus the selected
            # resource and where-clause mode.
            principal_key = self.builder_principal_var.get().strip()
            subject_phrase = build_subject_phrase(principal_key, self._builder_principal_details)
            if not subject_phrase:
                subject_phrase = '<principal>'

            resource = self.builder_resource_var.get().strip() or '<resource>'
            action = self.builder_action_var.get().strip() or 'Allow'
            mode = (self.builder_where_mode_var.get() or '').strip()

            if mode == 'No Where Clause':
                where_desc = 'without where clause'
            elif mode == 'Other Where Clause':
                where_desc = 'with custom where clause'
            else:  # Tag-based Where Clause (default)
                where_desc = 'with tag-based where clause'

            desc = f'{action} {subject_phrase} / {resource} {where_desc}'.strip()

            # Preserve tag context hint when using the tag-based builder.
            if mode == 'Tag-based Where Clause' and ns and key:
                desc = f'{desc} (tag {ns}.{key})'

            logger.info(f"Adding new row from builder (loc={loc or 'ROOT'}, len={len(stmt)})")

            # Use the shared CRUD helper to append a new row for this
            # builder-generated statement.
            row = self._add_row(
                {
                    'compartment_path': loc or 'ROOT',
                    'description': desc,
                    'statement_text': stmt,
                }
            )

            # Immediately validate the new row if possible
            on_parse = row.get('on_parse') if isinstance(row, dict) else None
            if callable(on_parse):
                try:
                    on_parse()
                except Exception:
                    logger.warning('Error while parsing builder-added row', exc_info=True)

        ttk.Button(builder_actions, text='Add to Statements', command=on_add_from_builder).pack(side='left')

        def _update_builder_previews(*_args: object) -> None:  # noqa: C901
            # Handle where-clause mode visibility
            mode = (self.builder_where_mode_var.get() or 'Tag-based Where Clause').strip()
            if mode == 'No Where Clause':
                self.tag_where_frame.grid_remove()
                self.other_where_frame.grid_remove()
                self.no_where_frame.grid()
                self.where_help_text.set('No where clause will be added to this statement.')
            elif mode == 'Other Where Clause':
                self.tag_where_frame.grid_remove()
                self.no_where_frame.grid_remove()
                self.other_where_frame.grid()
                self.where_help_text.set(
                    "Construct or paste a WHERE clause, but do not include the 'where' keyword. "
                    "Example: any { request.permission = 'OBJECT_CREATE', request.operation = 'PutObject' }."
                )
            else:  # Tag-based Where Clause
                self.other_where_frame.grid_remove()
                self.no_where_frame.grid_remove()
                self.tag_where_frame.grid()
                self.where_help_text.set(
                    'Create a tag-based where clause based on choosing criteria below. After adding the '
                    'statement, it is possible to manually edit it above, for example to add additional conditions.'
                )

            access = self.builder_access_type_var.get().strip()
            ns = self.builder_namespace_var.get().strip()
            key = self.builder_key_var.get().strip()
            op = self.builder_operator_var.get().strip() or '='
            val = self.builder_value_var.get().strip()

            # Compute where-clause snippet based on mode
            if mode == 'No Where Clause':
                var_name = ''
                snippet = ''
            elif mode == 'Other Where Clause':
                try:
                    other_text = self.builder_other_where_text.get('1.0', 'end-1c').strip()
                except Exception:
                    other_text = ''
                var_name = '(custom where)' if other_text else ''
                snippet = other_text
            else:  # Tag-based Where Clause
                var_name, snippet = build_tag_variable_and_snippet(access, ns, key, op, val)

            self.builder_variable_preview_var.set(var_name)
            self.builder_condition_preview_var.set(snippet)

            principal_key = self.builder_principal_var.get().strip()
            # Use the same principal-details map shape as TagBasedAccessTab
            # so subject phrases are consistent across tabs.
            details = self._builder_principal_details.get(principal_key)
            include_default = bool(self.builder_include_default_var.get())

            if details is not None:
                ptype, domain, name = details

                # SERVICE PRINCIPALS
                # ------------------
                # Internal keys for services may use a Default prefix
                # (e.g. "service:Default/objectstorage"), but for both
                # the dropdown and the generated statement we always want
                # the succinct "service <name>" form. We therefore
                # normalize the key and ensure the details map entry
                # uses a domain-less tuple so build_subject_phrase
                # renders "service <name>".
                if ptype == 'service':
                    simple_key, svc_name = self._simplify_service_principal(principal_key, name)
                    principal_key = simple_key
                    self._builder_principal_details[simple_key] = ('service', None, svc_name or (name or ''))
                    details = ('service', None, svc_name or (name or ''))
                    ptype, domain, name = details

                # GROUP / DYNAMIC-GROUP PRINCIPALS
                # ---------------------------------
                # For group and dynamic-group, the Include Default
                # checkbox controls whether the literal Default domain
                # appears in the statement text:
                #   * When unchecked and the principal's domain is the
                #     tenancy-default, emit just "group 'name'" or
                #     "dynamic-group 'name'" (no domain).
                #   * When checked or when the domain is non-default,
                #     emit "group 'Domain'/'name'" or
                #     "dynamic-group 'Domain'/'name'".
                #
                # build_subject_phrase implements the rendering rules
                # above based on whether the stored domain is None or
                # a concrete value. We therefore rewrite the details map
                # to toggle domain between None and the original
                # domain value depending on Include Default, and ensure
                # the principal_key we pass in matches that entry.
                if ptype in {'group', 'dynamic-group'}:
                    dom = domain or 'Default'
                    is_default_domain = isinstance(dom, str) and dom.lower() == 'default'

                    # Base key without any explicit domain for
                    # default-domain principals, and with explicit
                    # domain for others.
                    if include_default or not is_default_domain:
                        # Keep explicit domain in the statement text.
                        canonical_key = f'{ptype}:{dom}/{name}'
                        principal_key = canonical_key
                        # Ensure domain is recorded so helper renders
                        # "group 'Dom'/'name'" form.
                        self._builder_principal_details[canonical_key] = (ptype, dom, name)
                    else:
                        # Suppress Default in the statement text by
                        # clearing the domain from details; this causes
                        # build_subject_phrase to emit just
                        # "group 'name'" or "dynamic-group 'name'".
                        simple_key = f'{ptype}:{name}'
                        principal_key = simple_key
                        self._builder_principal_details[simple_key] = (ptype, None, name)

                # ID-based principals (group-id/dynamic-group-id) and
                # users already render correctly based on the details
                # tuple, so no further adjustment is required here.

            subject_phrase = build_subject_phrase(principal_key, self._builder_principal_details)

            verb = self.builder_verb_var.get().strip() or 'use'
            resource = self.builder_resource_var.get().strip() or '<resource>'

            loc_raw = self.builder_location_var.get().strip() or 'root'
            eff_raw = self.builder_effective_path_var.get().strip() or loc_raw
            location_clause, loc_parts, eff_parts = build_location_clause(loc_raw, eff_raw)

            # Special case: when the effective path is the root of the
            # tenancy, emit "in tenancy" for readability and to match
            # how root-scoped policies are typically expressed.
            if not eff_parts or eff_parts == ['ROOT']:
                location_clause = ' in tenancy'

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
                    logger.info('Unable to show warning messagebox for effective path', exc_info=True)
                self.builder_effective_path_var.set('/'.join(loc_parts))

            # TODO: Additional semantic validation could be added here,
            # e.g. ensuring that the compartment referenced by the
            # statement is inside/under the chosen Location. Any
            # warnings would be surfaced next to the builder rather than
            # blocking statement generation.

            effect = self.builder_action_var.get().strip() or 'Allow'
            statement = build_full_statement(
                effect=effect,
                subject_phrase=subject_phrase,
                verb=verb,
                resource=resource,
                location_clause=location_clause,
                where_snippet=snippet,
            )
            self.builder_statement_preview_var.set(statement)

        for var in (
            self.builder_action_var,
            self.builder_principal_var,
            self.builder_include_default_var,
            self.builder_verb_var,
            self.builder_resource_var,
            self.builder_location_var,
            self.builder_effective_path_var,
            self.builder_where_mode_var,
            self.builder_access_type_var,
            self.builder_namespace_var,
            self.builder_key_var,
            self.builder_operator_var,
            self.builder_value_var,
        ):
            var.trace_add('write', _update_builder_previews)

        _update_builder_previews()

    # ------------------------------------------------------------------
    # Bottom Save/Close buttons
    # ------------------------------------------------------------------

    def _build_bottom_buttons(self) -> None:  # noqa: C901
        """Create the bottom Save and Close button row."""

        btns = ttk.Frame(self)
        btns.pack(fill='x', padx=8, pady=(4, 8))

        def on_save_and_close() -> None:  # noqa: C901
            """Persist all rows to the service and close the window.

            On successful save, this method also triggers a refresh of
            any open UI tabs that surface prospective statements so that
            changes are immediately visible after the editor is closed.

            Today this includes:

            * PoliciesTab – which merges prospective statements into the
              main policy table when "Show Prospective" is enabled.
            * SimulationTab – which previews applicable prospective
              statements and uses them during simulation.
            """

            if self.service is None:
                self.destroy()
                return

            # Build a simple list from the current rows; skip empty text.
            # Wherever possible, preserve existing record ids so that
            # previously-validated parsed/normalized details are kept in
            # the ProspectiveStatementsService and reused when saving.
            simple_list: list[dict[str, str]] = []
            for rm in list(self._row_models):
                loc = rm['loc_var'].get().strip()  # type: ignore[union-attr]
                desc = rm['desc_var'].get().strip()  # type: ignore[union-attr]
                text = rm['text_var'].get().strip()  # type: ignore[union-attr]
                if not text:
                    continue
                if not loc:
                    loc = 'ROOT'
                entry: dict[str, str] = {
                    'compartment_path': loc,
                    'description': desc,
                    'statement_text': text,
                }
                rid = rm.get('record_id')
                if isinstance(rid, str):
                    entry['id'] = rid
                simple_list.append(entry)

            logger.info(f'Preparing to save {len(simple_list)} prospective statements (non-empty rows)')

            try:
                self.service.replace_all_from_simple_list(simple_list)
                logger.info(f'Replace_all_from_simple_list applied; records in service={len(self.service.list_all())}')
                # Persist to settings and push into the simulation
                # engine. The engine will normalize and calculate
                # effective paths for each statement so downstream tabs
                # (Policies, Simulation) see a fully-prepared
                # prospective set on their next refresh.
                self.service.persist_and_push_to_engine()
                logger.info(f'Saved {len(simple_list)} prospective statements via ProspectiveStatementsService')
            except Exception as ex:
                logger.warning(f'Error saving prospective statements: {ex}', exc_info=True)
                messagebox.showerror('Error Saving Prospective Statements', str(ex))
                return

            # --- Refresh dependent tabs so new prospective data is visible
            app = getattr(self, 'app', None)
            try:
                refreshed_tabs: list[str] = []

                # Policies tab: rebuild combined real+prospective table.
                policies_tab = getattr(app, 'policies_tab', None)
                if policies_tab is not None and hasattr(policies_tab, 'populate_data'):
                    policies_tab.populate_data()
                    refreshed_tabs.append('PoliciesTab')

                # Tag-based Access tab: ensure prospective rows appear in the
                # tag-focused overview when the toggle is enabled.
                tag_tab = getattr(app, 'tag_based_access_tab', None)
                if tag_tab is not None and hasattr(tag_tab, 'populate_data'):
                    tag_tab.populate_data()
                    refreshed_tabs.append('TagBasedAccessTab')

                # Simulation tab: re-hydrate its data/model from the
                # updated service/engine and refresh any inline
                # prospective previews.
                sim_tab = getattr(app, 'simulation_tab', None)
                if sim_tab is not None and hasattr(sim_tab, 'populate_data'):
                    sim_tab.populate_data()
                    refreshed_tabs.append('SimulationTab')

                if refreshed_tabs:
                    logger.info('Refreshed tabs after prospective save: %s', ', '.join(refreshed_tabs))
            except Exception:
                # Never let a refresh failure block closing the dialog;
                # individual tabs will log their own issues as needed.
                logger.warning('ProspectiveEditorWindow: error while refreshing tabs after save', exc_info=True)

            self.destroy()

        ttk.Button(btns, text='Save and Close', command=on_save_and_close).pack(side='right', padx=(6, 0))

    # ------------------------------------------------------------------
    # Builder principal initialization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_service_name(raw: str) -> str:
        """Return the service name without prefixes like service:, Default/, etc."""

        if not raw:
            return ''

        name = raw.strip()
        if not name:
            return ''

        # Drop a leading "service:" prefix (case-insensitive)
        if ':' in name:
            prefix, rest = name.split(':', 1)
            if prefix.lower() == 'service':
                name = rest

        # Remove tenancy-default prefixes such as "Default/"
        if '/' in name:
            parts = [p for p in name.split('/') if p]
            if parts and parts[0].lower() == 'default':
                parts = parts[1:]
            name = parts[-1] if parts else name

        # Drop any remaining "service" prefix without delimiters (e.g. "servicecloudguard")
        if name.lower().startswith('service'):
            name = name[7:]

        return name.strip(' :/_-\t')

    @staticmethod
    def _simplify_service_principal(raw_key: str, fallback_name: str | None = None) -> tuple[str, str]:
        """Return a canonical (key, name) pair for a service principal."""

        name_from_key = ProspectiveEditorWindow._normalize_service_name(raw_key or '')
        name_from_fallback = ProspectiveEditorWindow._normalize_service_name(fallback_name or '')

        service_name = name_from_key or name_from_fallback or (fallback_name or '').strip()
        simple_key = f'service:{service_name}' if service_name else 'service'

        return simple_key, service_name

    def _initialize_builder_principals_from_repo(self) -> None:  # noqa: C901
        """Populate principal choices/details for the builder from the policy repo."""

        # Build principal choices from policy_repo similar to
        # TagBasedAccessTab so subject phrases are realistic.
        try:
            principals_seen: set[str] = set()
            principal_details: dict[str, tuple[str, str | None, str]] = {}

            repo = getattr(self, 'policy_repo', None)
            for stmt in getattr(repo, 'regular_statements', []) or []:
                subj_type = (stmt.get('subject_type') or '').strip() or None
                subjects = stmt.get('subject') or []

                def _add_principal(ptype: str, domain: str | None, name: str) -> None:
                    # Basic key shape mirrors PolicyIntelligenceEngine
                    # but we keep it simple here to avoid a hard
                    # dependency; display formatting is handled by
                    # build_subject_phrase.
                    if ptype in {'group-id', 'dynamic-group-id'}:
                        key = f'{ptype}:{name}'
                        principals_seen.add(key)
                        principal_details[key] = (ptype, None, name)
                        return

                    # Service principals: always expose as "service:<name>" in
                    # the dropdown so users never see an internal
                    # "service:Default/<name>" form. We still record the
                    # structured details as ("service", None, name) so
                    # build_subject_phrase renders "service <name>".
                    if ptype == 'service':
                        raw_key = f'service:{domain}/{name}' if domain else f'service:{name}'
                        simple_key, svc_name = self._simplify_service_principal(raw_key, name)
                        principals_seen.add(simple_key)
                        principal_details[simple_key] = ('service', None, svc_name or name.strip())
                        return

                    dom = domain
                    if dom in (None, 'default', 'Default'):
                        dom = None
                    key = f"{ptype}:{dom or 'Default'}/{name}"
                    principals_seen.add(key)
                    principal_details[key] = (ptype, dom, name)

                if subj_type in {'user', 'group', 'dynamic-group', 'service', 'group-id', 'dynamic-group-id'}:
                    if not isinstance(subjects, (list | tuple)):
                        subjects_iter = [subjects]
                    else:
                        subjects_iter = subjects
                    for subj in subjects_iter:
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
                    # Fallback: treat Subject as display-only strings if
                    # we cannot infer a structured principal.
                    if isinstance(subjects, (list | tuple)):
                        for s in subjects:
                            s_str = str(s).strip()
                            if s_str:
                                principals_seen.add(s_str)
                    else:
                        s_str = str(subjects or '').strip()
                        if s_str:
                            principals_seen.add(s_str)

            self._builder_principals = sorted(principals_seen)
            self._builder_principal_details = principal_details

            if hasattr(self, 'builder_principal_combo'):
                self.builder_principal_combo['values'] = self._builder_principals
        except Exception:
            logger.info('Unable to derive principal choices for builder', exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers for builder dropdowns
    # ------------------------------------------------------------------

    def _initialize_builder_locations_and_effective_paths(self) -> None:
        """Populate builder Location and Effective Path choices.

        Mirrors the SimulationTab/TagBasedAccessTab behavior by using
        the simulation tab's indexed compartments (effective paths)
        when available. Both Location and Effective Path combos are
        seeded from the same list so statements can be placed anywhere
        in the hierarchy.
        """

        try:
            sim_tab = getattr(self.app, 'simulation_tab', None)
            comp_paths = list(getattr(sim_tab, '_sim_index_compartments', []) or []) if sim_tab else []
        except Exception:
            comp_paths = []

        if not comp_paths:
            comp_paths = ['ROOT']

        self._builder_locations = sorted(comp_paths)
        self._builder_effective_paths = sorted(comp_paths)

        try:
            if hasattr(self, 'builder_location_combo'):
                self.builder_location_combo['values'] = self._builder_locations
            if hasattr(self, 'builder_effective_path_combo'):
                self.builder_effective_path_combo['values'] = self._builder_effective_paths
        except Exception:
            logger.info('Unable to seed location/effective path combos from simulation index', exc_info=True)

    def _refresh_builder_resource_values(self) -> None:
        """Populate the builder Resource combobox from in-use or all-known resources.

        When ``builder_all_possible_resources_var`` is true and reference
        data is available, we expose the union of resources+families from
        ``reference_repo``. Otherwise we use a simple in-use list derived
        from the policy repository if present.
        """

        # Derive in-use resources from policy_repo once per window
        try:
            if not self._builder_resources and self.policy_repo is not None:
                seen: set[str] = set()
                for stmt in getattr(self.policy_repo, 'regular_statements', []) or []:
                    res = (stmt.get('resource') or '').strip()
                    if res:
                        seen.add(res)
                self._builder_resources = sorted(seen)
        except Exception:
            logger.info('Unable to derive in-use resources', exc_info=True)

        values: list[str] = []
        use_all = bool(self.builder_all_possible_resources_var.get())

        if use_all and self.reference_repo is not None:
            try:
                data = getattr(self.reference_repo, 'data', {}) or {}
                resource_names = list((data.get('resources') or {}).keys())
                family_names = list((data.get('families') or {}).keys())
                combined = sorted(set(resource_names + family_names), key=str.lower)
                self._builder_all_resources = combined
                values = combined
            except Exception:
                logger.info('Error building All Resources list; falling back to in-use list', exc_info=True)
                self.builder_all_possible_resources_var.set(False)

        if not values:
            values = list(self._builder_resources)

        try:
            if hasattr(self, 'builder_resource_combo'):
                self.builder_resource_combo['values'] = values
        except Exception:
            logger.info('Unable to refresh builder_resource_combo values', exc_info=True)

    def _on_toggle_all_possible_resources(self) -> None:
        """Handle the All Possible Resources checkbox for the builder Resource dropdown.

        Mirrors the behavior of TagBasedAccessTab: when enabled, use the
        full reference-data domain for resources/families; when disabled,
        fall back to resources seen in the loaded policies.
        """

        self._refresh_builder_resource_values()
