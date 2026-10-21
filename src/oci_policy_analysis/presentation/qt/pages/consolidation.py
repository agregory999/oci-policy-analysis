"""Guided native consolidation planning over shared protection and run history."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.consolidation_workbench_service import (
    LOCKED_POLICY_NAME,
    ConsolidationWorkbenchService,
)
from oci_policy_analysis.presentation.qt.json_view import JsonTree
from oci_policy_analysis.presentation.qt.selection_table import CheckableRecordModel
from oci_policy_analysis.presentation.qt.tables import STATEMENT_COLUMNS, BrowserStatementModel, RecordTable
from oci_policy_analysis.presentation.qt.widgets import label

logger = get_logger(component='qt.consolidation')

STAGES = (
    ('Protect / Lock', 'Keep essential statements out of future plans.'),
    ('Statements & Strategy', 'Choose candidates and how to consolidate them.'),
    ('Review plan', 'Inspect changes, skipped statements, and rollback.'),
    ('Execution / History', 'Copy instructions, apply externally, and check progress.'),
)


class ConsolidationSelectionModel(CheckableRecordModel, BrowserStatementModel):
    """Combine shared checkbox identity with shared statement formatting.

    Attributes:
        checked: Snapshot of selected source statement IDs.
        changed: Emitted after checkbox state or source inventory changes.

    Notes:
        CheckableRecordModel owns ID validation and filtering-independent selection.
        Its superclass display calls use BrowserStatementModel's policy labels and
        invalid-statement styles through the method resolution order.
    """

    changed = Signal()

    def __init__(self):
        columns = (*STATEMENT_COLUMNS[:-1], ('Occurrences', 'source_occurrences'), STATEMENT_COLUMNS[-1])
        super().__init__(columns, key=lambda row: row.get('internal_id', ''), eligible=lambda row: True)
        self.checked_changed.connect(lambda _ids: self.changed.emit())

    @property
    def checked(self):
        """Return selected IDs, including records currently hidden by filtering."""
        return set(self.checked_ids())

    def set_checked(self, ids):
        """Replace checkbox selection using the shared stable-ID eligibility checks.

        Args:
            ids: Statement IDs to include; unknown IDs are ignored.
        """
        self.set_checked_ids(ids)


class ConsolidationWorker(QThread):
    """Run plan generation or live progress checks while the shell owns the snapshot.

    Args:
        service: Service bound to the active context and shared local cache.
        operation: ``proposal`` or ``progress``.
        arguments: Positional service arguments captured before starting.
        parent: Page retaining the worker until its thread finishes.

    Attributes:
        result: Detached service result, available after thread completion.
        error: Failure message, empty on success.
        refreshed: Whether a live policy refresh may have replaced repository data.
    """

    def __init__(self, service, operation, arguments, parent):
        super().__init__(parent)
        self.service, self.operation, self.arguments = service, operation, arguments
        self.result, self.error, self.refreshed = None, '', False

    def run(self) -> None:
        """Plan locally or check OCI progress, rebuilding derived state after a live reload."""
        try:
            if self.operation == 'proposal':
                self.result = self.service.create_proposal(*self.arguments)
            else:
                self.refreshed = self.service.get_status()['can_check_progress']
                self.result = self.service.check_progress_with_refresh(*self.arguments)
        except Exception as exc:
            logger.exception('Consolidation %s failed', self.operation)
            self.error = str(exc)


class ConsolidationPage(QWidget):
    """Guide protection, candidate selection, plan review, and persisted history.

    Attributes:
        busy_changed: Shell gate for snapshot loads and competing workers.
        snapshot_changed: Rebind other pages after a live progress refresh.
        details_requested: Explicit statement inspection for the shared drawer.
        worker: Retained background task, or None while idle.
        service: Current context-bound consolidation facade, recreated after reload.

    Notes:
        Generates instructions only. OCI Console or CLI changes are performed by
        the operator outside the application; progress checking only reads OCI.
    """

    busy_changed = Signal(bool)
    snapshot_changed = Signal(object)
    details_requested = Signal(object, str)

    def __init__(self):
        super().__init__()
        self.context = self.service = self.worker = None
        self.plan = None
        self.effort_id = ''
        self.block_reason = ''
        self.saved_protection = set()
        self.can_check_progress = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('Plan → Review → Apply externally → Verify', 'eyebrow'))
        layout.addWidget(
            label(
                'Protect essential policies, select statements, and review an ordered consolidation plan. '
                'Console and CLI instructions include rollback; no OCI policy changes are executed here.',
                'muted',
                wrap=True,
            )
        )
        steps = QHBoxLayout()
        self.step_group = QButtonGroup(self)
        self.step_buttons = []
        self.stages = QStackedWidget()
        for index, (title, description) in enumerate(STAGES):
            button = QPushButton(f'{index + 1} · ' + title.replace('&', '&&'))
            button.setCheckable(True)
            button.setToolTip(description)
            button.clicked.connect(lambda checked=False, step=index: self.show_stage(step))
            self.step_group.addButton(button, index)
            self.step_buttons.append(button)
            steps.addWidget(button, 1)
            if index < len(STAGES) - 1:
                steps.addWidget(label('→', 'muted'))
        layout.addLayout(steps)
        self.stage_description = label('', 'notice', wrap=True)
        layout.addWidget(self.stage_description)
        self.status = label('Load a snapshot to start planning.', 'muted', wrap=True)
        layout.addWidget(self.status)
        self._build_protection()
        self._build_candidates()
        self._build_review()
        self._build_history()
        layout.addWidget(self.stages, 1)
        self.show_stage(0)
        self._update_controls()

    def _panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stages.addWidget(panel)
        return layout

    def _button(self, layout, title, callback, *, primary=False):
        button = QPushButton(title.replace('&', '&&'))
        button.clicked.connect(callback)
        if primary:
            button.setObjectName('primary')
        layout.addWidget(button)
        return button

    def _selection_table(self, layout):
        search = QLineEdit()
        search.setPlaceholderText('Filter by policy, compartment, effective path, or statement…')
        search.setClearButtonEnabled(True)
        layout.addWidget(search)
        model = ConsolidationSelectionModel()
        table = RecordTable(model.columns, source_model=model, multi_select=True)
        table.setColumnWidth(0, 80)
        table.setColumnWidth(1, 260)
        table.setColumnWidth(2, 220)
        table.setColumnWidth(3, 110)
        table.details_requested.connect(lambda record: self.details_requested.emit(record, 'Statement details'))
        search.textChanged.connect(table.proxy.setFilterFixedString)
        actions = QHBoxLayout()
        self._button(actions, 'Select displayed', lambda: self._check_displayed(table, True))
        self._button(actions, 'Clear displayed', lambda: self._check_displayed(table, False))
        actions.addStretch()
        count = label('', 'muted', wrap=True)
        actions.addWidget(count)
        layout.addLayout(actions)
        layout.addWidget(table, 1)
        search.textChanged.connect(lambda *_: self._selection_count(table, count))
        model.changed.connect(lambda: self._selection_count(table, count))
        return search, table, count

    def _build_protection(self):
        layout = self._panel()
        layout.addWidget(
            label(
                'Check statements that must stay in place. Save the protected set before choosing candidates. '
                f'The system policy “{LOCKED_POLICY_NAME}” is always excluded. Locks apply to consolidation planning.',
                wrap=True,
            )
        )
        self.protection_search, self.protection, self.protection_count = self._selection_table(layout)
        actions = QHBoxLayout()
        self.save_protection_button = self._button(actions, 'Save protection', self.save_protection)
        self._button(actions, 'Continue to statements →', lambda: self._continue_selection(), primary=True)
        actions.addStretch()
        layout.addLayout(actions)
        self.protection.model.changed.connect(self._update_controls)

    def _build_candidates(self):
        layout = self._panel()
        self.exclusions = label('', 'muted', wrap=True)
        layout.addWidget(self.exclusions)
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(label('Strategy'))
        self.strategy = QComboBox()
        self.strategy.setMaximumWidth(330)
        strategy_row.addWidget(self.strategy)
        self.strategy_description = label('', 'notice', wrap=True)
        strategy_row.addWidget(self.strategy_description, 1)
        layout.addLayout(strategy_row)
        self.strategy.currentIndexChanged.connect(self._strategy_changed)
        self.candidate_search, self.candidates, self.candidate_count = self._selection_table(layout)
        self.candidates.model.changed.connect(self._update_controls)
        actions = QHBoxLayout()
        self.generate_button = self._button(actions, 'Generate and save plan →', self.generate_proposal, primary=True)
        self._button(actions, '← Protect / Lock', lambda: self.show_stage(0))
        actions.addStretch()
        layout.addLayout(actions)

    def _build_review(self):
        layout = self._panel()
        self.plan_summary = label('Generate a plan or open one from history.', 'muted', wrap=True)
        layout.addWidget(self.plan_summary)
        split = QSplitter(Qt.Orientation.Vertical)
        self.plan_steps = RecordTable(
            (
                ('Step', 'index'),
                ('Action', 'action'),
                ('Compartment', 'policy_compartment'),
                ('Policy', 'policy_name'),
                ('Status', 'status'),
                ('Change', 'details'),
            )
        )
        self.plan_steps.setColumnWidth(0, 70)
        self.plan_steps.setColumnWidth(1, 100)
        self.plan_steps.setColumnWidth(4, 100)
        # Preserve the service's execution order, including plans with 10+ steps.
        self.plan_steps.setSortingEnabled(False)
        self.plan_steps.proxy.sort(-1)
        self.plan_steps.selectionModel().selectionChanged.connect(self._step_selected)
        self.plan_steps.details_requested.connect(lambda row: self._inspect_step(row))
        split.addWidget(self.plan_steps)
        self.review_tabs = QTabWidget()
        changes = QWidget()
        changes_layout = QVBoxLayout(changes)
        self.step_summary = label('Select a step to inspect original and proposed statements.', wrap=True)
        changes_layout.addWidget(self.step_summary)
        statement_split = QSplitter(Qt.Orientation.Horizontal)
        self.before = self._statement_panel(statement_split, 'Before · original statements')
        self.after = self._statement_panel(statement_split, 'After · proposed statements')
        changes_layout.addWidget(statement_split, 1)
        self.review_tabs.addTab(changes, 'Step changes')
        self.rollback = self._text()
        self.review_tabs.addTab(self.rollback, 'Rollback for selected step')
        self.skipped = RecordTable(
            (('Statement ID', 'internal_id'), ('Statement', 'statement_text'), ('Reason', 'reason'))
        )
        self.skipped.details_requested.connect(self._skipped_details)
        self.review_tabs.addTab(self.skipped, 'Skipped statements')
        note_panel = QWidget()
        notes_layout = QVBoxLayout(note_panel)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText('Decision context, approvals, execution observations…')
        notes_layout.addWidget(self.notes, 1)
        self.save_notes_button = self._button(notes_layout, 'Save plan notes', self.save_notes)
        self.review_tabs.addTab(note_panel, 'Plan notes')
        self.raw_step = JsonTree()
        self.review_tabs.addTab(self.raw_step, 'Raw step')
        split.addWidget(self.review_tabs)
        split.setSizes([240, 260])
        layout.addWidget(split, 1)
        actions = QHBoxLayout()
        self._button(actions, '← Statements & Strategy', lambda: self.show_stage(1))
        self.execution_button = self._button(
            actions, 'Review execution and rollback →', lambda: self.show_stage(3), primary=True
        )
        actions.addStretch()
        layout.addLayout(actions)

    def _statement_panel(self, split, title):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(label(title, 'eyebrow'))
        text = self._text()
        layout.addWidget(text)
        split.addWidget(panel)
        return text

    def _text(self):
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        return text

    def _build_history(self):
        layout = self._panel()
        split = QSplitter(Qt.Orientation.Vertical)
        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(label('Saved plans for this tenancy · shared with desktop and web', 'eyebrow'))
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText('Filter plan history…')
        self.history_search.setClearButtonEnabled(True)
        history_layout.addWidget(self.history_search)
        self.history = RecordTable(
            (
                ('Created', 'created_at'),
                ('Plan', 'effort_id'),
                ('Strategy', 'strategy'),
                ('Status', 'status'),
                ('Executed', 'execution_summary'),
                ('Validity', 'validity'),
            ),
            details_title='View plan in Review',
        )
        self.history.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.history_search.textChanged.connect(self.history.proxy.setFilterFixedString)
        self.history.selectionModel().selectionChanged.connect(self._history_selected)
        self.history.details_requested.connect(lambda row: self._open_history(row, review=True))
        self.history.doubleClicked.connect(lambda index: self._open_history(self.history.record_at(index), review=True))
        history_layout.addWidget(self.history, 1)
        actions = QHBoxLayout()
        self.refresh_history_button = self._button(actions, 'Refresh history', self.refresh_history)
        self.open_plan_button = self._button(actions, 'View in Review Plan', self._review_history)
        self.delete_plan_button = self._button(actions, 'Delete selected history…', self.delete_history)
        actions.addStretch()
        history_layout.addLayout(actions)
        split.addWidget(history_panel)
        output_panel = QWidget()
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.conflicts = label('Select a saved plan to see instructions.', 'notice', wrap=True)
        output_layout.addWidget(self.conflicts)
        controls = QHBoxLayout()
        controls.addWidget(label('Format'))
        self.output_format = QComboBox()
        self.output_format.addItem('OCI Console steps', 'ui')
        self.output_format.addItem('OCI CLI commands', 'cli')
        controls.addWidget(self.output_format)
        controls.addWidget(label('Show'))
        self.output_section = QComboBox()
        for title, value in (('Execution + rollback', 'both'), ('Execution', 'execution'), ('Rollback', 'rollback')):
            self.output_section.addItem(title, value)
        controls.addWidget(self.output_section)
        self.copy_button = self._button(controls, 'Copy', self.copy_output)
        self.export_button = self._button(controls, 'Export…', self.export_output)
        controls.addStretch()
        output_layout.addLayout(controls)
        self.output = self._text()
        output_layout.addWidget(self.output, 1)
        self.output_format.currentIndexChanged.connect(self._render_output)
        self.output_section.currentIndexChanged.connect(self._render_output)
        check_row = QHBoxLayout()
        self.check_progress_button = self._button(
            check_row, 'Refresh live policies & check progress', self.check_progress
        )
        self.progress_note = label(
            'Cached datasets show saved progress; live checking requires a tenancy load.', 'muted', wrap=True
        )
        check_row.addWidget(self.progress_note, 1)
        output_layout.addLayout(check_row)
        split.addWidget(output_panel)
        split.setSizes([200, 350])
        layout.addWidget(split, 1)

    def show_stage(self, index):
        """Navigate without discarding selections or generating a new plan."""
        self.stages.setCurrentIndex(index)
        self.step_buttons[index].setChecked(True)
        for number, button in enumerate(self.step_buttons):
            button.setObjectName('primary' if number == index else '')
            button.style().unpolish(button)
            button.style().polish(button)
        title, description = STAGES[index]
        self.stage_description.setText(f'{index + 1}. {title} — {description}')

    def set_context(self, context):
        """Rebind to the active snapshot; clear transient plans and restore saved protection.

        Args:
            context: Loaded AppContext, or None to clear the page. The shell must
                not replace it while this page owns an active worker.
        """
        if self.worker is not None:
            return
        self.context = context
        self.service = ConsolidationWorkbenchService(context) if context else None
        self.can_check_progress = bool(self.service and self.service.get_status()['can_check_progress'])
        self.plan, self.effort_id = None, ''
        self.protection.model.set_checked(set())
        self.candidates.model.set_checked(set())
        self.protection_search.clear()
        self.candidate_search.clear()
        self.strategy.clear()
        self.history.model.replace([])
        self._clear_plan()
        if self.service:
            self.saved_protection = {
                row.get('internal_id')
                for row in self.service.get_protected_set().get('protected', [])
                if row.get('internal_id')
            }
            originals = {row.get('internal_id'): row for row in context.policy_repo.regular_statements}
            rows = [{**originals.get(row.get('internal_id'), {}), **row} for row in self.service.get_protection_rows()]
            self.protection.model.replace(rows)
            self.protection.model.set_checked(self.saved_protection)
            for item in self.service.get_strategy_catalog():
                self.strategy.addItem(item['name'], item['description'])
            self._refresh_candidates()
            self.refresh_history()
            self.status.setText(
                f'{context.policy_repo.tenancy_name or "Loaded tenancy"} · protection and plans stored locally by tenancy.'
            )
        else:
            self.saved_protection = set()
            self.protection.model.replace([])
            self.candidates.model.replace([])
            self.status.setText('Load a snapshot to start planning.')
        self._selection_count(self.protection, self.protection_count)
        self._selection_count(self.candidates, self.candidate_count)
        self._update_controls()

    def set_block_reason(self, reason):
        """Gate persistence, planning, and checks while another task owns the snapshot."""
        self.block_reason = reason
        self._update_controls()

    def _selection_count(self, table, count):
        visible = {
            table.record_at(table.proxy.index(row, 0)).get('internal_id') for row in range(table.proxy.rowCount())
        }
        count.setText(
            f'{len(visible):,} displayed · {len(table.model.checked):,} selected ({len(table.model.checked - visible):,} hidden)'
            + (
                ' · Repeated source copies share one checkbox.'
                if any(row.get('source_occurrences', 1) > 1 for row in table.model.records)
                else ''
            )
        )

    def _check_displayed(self, table, checked):
        visible = {
            table.record_at(table.proxy.index(row, 0)).get('internal_id') for row in range(table.proxy.rowCount())
        }
        selected = table.model.checked | visible if checked else table.model.checked - visible
        table.model.set_checked(selected - {None, ''})

    def save_protection(self):
        """Save the full checkbox set, including checked statements hidden by a filter."""
        if not self._allowed():
            return False
        try:
            result = self.service.set_protected_set(sorted(self.protection.model.checked))
            self.saved_protection = {row['internal_id'] for row in result.get('protected', [])}
            self.protection.model.set_checked(self.saved_protection)
            self._refresh_candidates()
            self.status.setText(
                f'Saved {len(self.saved_protection):,} protected statements. Existing plans retain their original snapshot.'
            )
            self._update_controls()
            return True
        except Exception as exc:
            self.status.setText(f'Could not save protection: {exc}')
            return False

    def select_opportunity(self, opportunity: dict) -> bool:
        """Preselect eligible recommendation sources for explicit strategy review.

        Args:
            opportunity: Shared recommendation containing stable source IDs and
                an optional recommended strategy. No plan is saved here.

        Returns:
            bool: Whether the idle, snapshot-bound page accepted the handoff.
        """
        if not self._allowed() or opportunity.get('Handoff Mode') != 'supported':
            return False
        self._refresh_candidates()
        requested = set(opportunity.get('Statement Internal IDs') or [])
        available = {row['internal_id'] for row in self.candidates.model.records}
        selected = requested & available
        self.candidate_search.clear()
        self.candidates.model.set_checked(selected)
        strategy = self.strategy.findText(opportunity.get('Recommended Strategy') or '')
        if strategy >= 0:
            self.strategy.setCurrentIndex(strategy)
        self.show_stage(1)
        self.status.setText(
            f'{len(selected):,} recommended statements selected; {len(requested - selected):,} unavailable or excluded. Review strategy and selection before generating a plan.'
        )
        self._update_controls()
        return True

    def _continue_selection(self):
        if self.protection.model.checked != self.saved_protection and not self.save_protection():
            return
        self.show_stage(1)

    def _refresh_candidates(self):
        result = self.service.get_candidate_rows()
        originals = {row.get('internal_id'): row for row in self.context.policy_repo.regular_statements}
        rows = [{**originals.get(row.get('internal_id'), {}), **row} for row in result['rows']]
        available = {row.get('internal_id') for row in rows}
        checked = self.candidates.model.checked & available
        self.candidates.model.replace(rows)
        self.candidates.model.set_checked(checked)
        counts = result['counts']
        self.exclusions.setText(
            f'Excluded: {counts["protected"]:,} protected · {counts["invalid"]:,} invalid · {counts["system"]:,} system. Check candidates below; selections survive filtering.'
            + (
                f' {counts["ambiguous"]:,} conflicting source IDs also excluded; reload source data to resolve them.'
                if counts.get('ambiguous')
                else ''
            )
        )
        self._selection_count(self.candidates, self.candidate_count)

    def _strategy_changed(self, *_args):
        self.strategy_description.setText(
            str(self.strategy.currentData() or 'No strategy is available for this dataset.')
        )
        self._update_controls()

    def generate_proposal(self):
        """Persist a plan using the selected IDs and shared strategy, off the GUI thread."""
        if not self._allowed() or not self.candidates.model.checked:
            return
        if self.protection.model.checked != self.saved_protection:
            self.status.setText('Save or revert protection changes in step 1 before generating a plan.')
            self.show_stage(0)
            return
        self._start('proposal', (sorted(self.candidates.model.checked), self.strategy.currentText()))

    def _start(self, operation, arguments):
        self.worker = ConsolidationWorker(self.service, operation, arguments, self)
        self.worker.finished.connect(self._task_finished)
        self.status.setText(
            'Generating and saving plan…'
            if operation == 'proposal'
            else 'Refreshing live policies and checking progress…'
        )
        self._update_controls()
        self.busy_changed.emit(True)
        self.worker.start()

    def _task_finished(self):
        worker = self.worker
        self.worker = None
        self.busy_changed.emit(False)
        if worker.refreshed:
            self.snapshot_changed.emit(self.context)
        if worker.error:
            self.status.setText(f'Consolidation {worker.operation} failed: {worker.error}')
        elif worker.operation == 'proposal':
            self.refresh_history()
            plan = worker.result['plan']
            self._open_plan(plan['plan_id'])
            self.show_stage(2)
            self.status.setText(
                'Plan saved. Review every step, skipped statement, and rollback before applying changes.'
            )
        else:
            self.refresh_history()
            self._open_plan(worker.arguments[0])
            result = worker.result
            self.status.setText(
                f'{result.get("message", "Progress checked.")} {result["executed"]}/{result["total"]} steps executed.'
            )
        worker.deleteLater()
        self._update_controls()

    def refresh_history(self):
        """Read the current tenancy's shared history without checking OCI."""
        if not self.service or self.worker:
            return
        try:
            rows = self.service.get_history()
            for row in rows:
                row['execution_summary'] = f'{row["executed_steps"]}/{row["steps"]}'
            self.history.model.replace(rows)
        except Exception as exc:
            self.status.setText(f'Could not read history: {exc}')
        self._update_controls()

    def _history_selected(self, *_args):
        selected = self.history.selected_records()
        if selected:
            self._open_history(selected[0])
        self._update_controls()

    def _skipped_details(self, record):
        if not record or not self.context:
            return
        source = next(
            (
                row
                for row in self.context.policy_repo.regular_statements
                if row.get('internal_id') == record.get('internal_id')
            ),
            {},
        )
        self.details_requested.emit({**source, **record}, 'Skipped statement details')

    def _open_history(self, row, *, review=False):
        if row and self._allowed():
            self._open_plan(row['effort_id'])
            if review:
                self.show_stage(2)

    def _review_history(self):
        if self.effort_id:
            self.show_stage(2)

    def _open_plan(self, effort_id):
        detail = self.service.get_history_run_detail(effort_id)
        if not detail:
            self.status.setText('This plan is no longer in history. Refresh the history list.')
            self.plan, self.effort_id = None, ''
            self._clear_plan()
            self._update_controls()
            return
        run = detail['run']
        self.plan, self.effort_id = run.get('plan') or {}, effort_id
        self.plan_steps.model.replace(detail['proposal_rows'])
        self.skipped.model.replace(self.plan.get('skipped_statements') or [])
        self.review_tabs.setTabText(2, f'Skipped statements ({len(self.skipped.model.records)})')
        self.notes.setPlainText(self.plan.get('notes') or '')
        self.plan_summary.setText(
            f'{self.plan.get("plan_label") or "Consolidation plan"} · {effort_id} · {len(detail["proposal_rows"])} steps · {run.get("status", "in_progress")}'
        )
        conflict = detail['conflict_analysis']
        self.conflicts.setText(
            f'Plan {effort_id} · {conflict["status"]} · {conflict["rule"]}'
            + (
                '\n' + json.dumps(conflict['conflicts'], ensure_ascii=False, default=str)
                if conflict.get('conflicts')
                else ''
            )
        )
        self._render_output()
        if self.plan_steps.proxy.rowCount():
            self.plan_steps.selectRow(0)
        else:
            self._inspect_step(None)
        self._update_controls()

    def _step_selected(self, *_args):
        records = self.plan_steps.selected_records()
        self._inspect_step(records[0] if records else None)

    def _inspect_step(self, row):
        step = next(
            (
                step
                for step in (self.plan or {}).get('plan_steps', [])
                if row and step.get('step_id') == row.get('step_id')
            ),
            None,
        )
        self.before.setPlainText(
            '\n\n'.join(f'{i}. {text}' for i, text in enumerate((row or {}).get('before_statements', []), 1))
        )
        self.before.setPlaceholderText('New policy — no prior statements.' if row else 'No step selected.')
        self.after.setPlainText(
            '\n\n'.join(f'{i}. {text}' for i, text in enumerate((row or {}).get('after_statements', []), 1))
        )
        self.after.setPlaceholderText(
            'Policy will be deleted.' if row and row.get('action_key') == 'delete' else 'No proposed statements.'
        )
        self.step_summary.setText(
            f'Step {row["index"]} · {row["action"]} · {row["policy_name"]} · {row["details"]}'
            if row
            else 'Select a step to inspect original and proposed statements.'
        )
        self.raw_step.set_json(step)
        self.rollback.setPlainText(
            self.service.render_plan({**self.plan, 'plan_steps': [step]}, 'ui', 'rollback') if step else ''
        )

    def _clear_plan(self):
        self.plan_steps.model.replace([])
        self.skipped.model.replace([])
        self.notes.clear()
        self.output.clear()
        self.before.clear()
        self.after.clear()
        self.rollback.clear()
        self.raw_step.set_json(None)
        self.plan_summary.setText('Generate a plan or open one from history.')
        self.conflicts.setText('Select a saved plan to see instructions.')

    def save_notes(self):
        """Persist decision notes in the selected shared history record."""
        if not self._allowed() or not self.effort_id:
            return
        try:
            if self.service.save_plan_notes(self.effort_id, self.notes.toPlainText()):
                self.plan['notes'] = self.notes.toPlainText()
                self.status.setText('Plan notes saved.')
            else:
                self.status.setText('Plan notes could not be saved; the history record may have changed.')
        except Exception as exc:
            self.status.setText(f'Could not save notes: {exc}')

    def _render_output(self, *_args):
        if not self.service or not self.plan:
            self.output.clear()
            return
        try:
            self.output.setPlainText(
                self.service.render_plan(
                    self.plan, self.output_format.currentData(), self.output_section.currentData(), self.effort_id
                )
            )
        except Exception as exc:
            self.output.clear()
            self.status.setText(f'Could not render instructions: {exc}')

    def copy_output(self):
        """Copy the selected execution/rollback view without executing it."""
        QApplication.clipboard().setText(self.output.toPlainText())
        self.status.setText('Instructions copied. Review and apply them outside the application.')

    def export_output(self):
        """Save the currently displayed instructions to an operator-selected file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Export consolidation instructions',
            f'{self.effort_id}-{self.output_section.currentData()}.txt',
            'Text files (*.txt);;All files (*)',
        )
        if path:
            try:
                Path(path).write_text(self.output.toPlainText(), encoding='utf-8')
                self.status.setText(f'Instructions exported: {path}')
            except OSError as exc:
                self.status.setText(f'Export failed: {exc}')

    def check_progress(self):
        """Refresh live policies and persist observed progress for the selected plan."""
        if self._allowed() and self.effort_id and self.can_check_progress:
            self._start('progress', (self.effort_id,))

    def delete_history(self):
        """Delete one local history record after explicit confirmation; OCI is unchanged."""
        selected = self.history.selected_records()
        if not self._allowed() or not selected:
            return
        effort_id = selected[0]['effort_id']
        answer = QMessageBox.question(
            self,
            'Delete saved plan?',
            f'Delete local plan {effort_id}, including its rollback snapshot and notes? This does not undo OCI changes.',
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.service.delete_history_run(effort_id):
                if effort_id == self.effort_id:
                    self.plan, self.effort_id = None, ''
                    self._clear_plan()
                self.refresh_history()
                self.status.setText('Local history record deleted.')
        except Exception as exc:
            self.status.setText(f'Could not delete history: {exc}')
        self._update_controls()

    def _allowed(self):
        if self.service and not self.worker and not self.block_reason:
            return True
        self.status.setText(self.block_reason or 'Load a snapshot and wait for the current task to finish.')
        return False

    def _update_controls(self):
        if not hasattr(self, 'check_progress_button'):
            return
        available = self.service is not None and self.worker is None and not self.block_reason
        dirty = self.protection.model.checked != self.saved_protection
        self.save_protection_button.setEnabled(available and dirty)
        self.generate_button.setEnabled(
            available and not dirty and bool(self.candidates.model.checked) and self.strategy.count() > 0
        )
        self.generate_button.setToolTip(
            'Save pending protection changes first.'
            if dirty
            else 'Generate and persist a local proposal; no OCI policy changes are made.'
        )
        selected = bool(self.effort_id and self.plan)
        for button in (
            self.save_notes_button,
            self.execution_button,
            self.copy_button,
            self.export_button,
            self.open_plan_button,
        ):
            button.setEnabled(available and selected)
        self.delete_plan_button.setEnabled(available and bool(self.history.selected_records()))
        self.refresh_history_button.setEnabled(available)
        live = available and self.can_check_progress
        self.check_progress_button.setEnabled(bool(live and selected))
        self.progress_note.setText(
            self.block_reason
            or (
                'Live check refreshes policies and rebuilds snapshot analysis before checking this plan.'
                if live
                else 'Cached and compliance datasets show saved progress. Load from OCI to check current execution.'
            )
        )
        for widget in (self.protection, self.candidates, self.strategy, self.stages):
            widget.setEnabled(self.worker is None and not self.block_reason)
