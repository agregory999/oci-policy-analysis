"""Native recommendations dashboard over shared snapshot intelligence."""

import json
from copy import deepcopy

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
from oci_policy_analysis.presentation.qt.tables import RecordModel, RecordTable
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, label

logger = get_logger(component='qt.recommendations')

SECTIONS = (
    ('summary', 'Summary', ('Priority', 'Category', 'Recommendation', 'Notes', 'Action', 'Action Detail')),
    (
        'risk_policy',
        'Policy risk',
        ('Policy Path', 'Max Statement Risk (Global %)', 'Total Statements', 'Total Raw Risk', 'Example Statement'),
    ),
    ('risk_statement', 'Statement risk', ('Policy Path', 'Relative Risk', 'Score', 'Effective Path', 'Statement Text')),
    ('supersession', 'Superseded', ('Policy Name', 'Effective Path', 'Classification', 'Superseded By')),
    ('cross_tenancy', 'Cross-tenancy', ('Type', 'Severity', 'Policy Name', 'Issue', 'Statement Text')),
    ('consolidation', 'Consolidation', ('Type', 'Policies', 'Statements', 'Scope', 'Summary', 'Recommended Action')),
    ('cleanup', 'Cleanup / Fix', ('Type', 'Name', 'Reason', 'Action')),
    (
        'limits',
        'Limits',
        ('Compartment Hierarchy Path', 'Direct Statements', 'Cumulative Statements', 'Status', 'Recommendation'),
    ),
)


class FindingModel(RecordModel):
    """Sort numeric risk/count fields numerically and priorities by urgency."""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Return typed sort values while preserving original display evidence."""
        if index.isValid() and role == Qt.ItemDataRole.UserRole:
            field = self.columns[index.column()][1]
            value = self.records[index.row()].get(field)
            if field == 'Priority':
                return {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}.get(str(value).casefold(), 4)
            return value if isinstance(value, (int, float)) else str(value or '').casefold()
        return super().data(index, role)


class RecommendationWorker(QThread):
    """Own the serialized snapshot while rebuilding full derived analysis.

    Args:
        context: Active loaded snapshot; retained until thread completion.
        settings: Detached strategy and risk preferences for the explicit run.
        parent: Owning page which keeps the worker alive.
    """

    completed = Signal(object, object)
    failed = Signal(object, str)
    stage = Signal(str)

    def __init__(self, context, settings: dict, parent) -> None:
        super().__init__(parent)
        self.context, self.settings = context, deepcopy(settings)

    def run(self) -> None:
        """Run shared enrichment off the GUI thread and return detached evidence."""
        try:
            result = RecommendationsService(self.context).refresh_analysis(
                settings=self.settings,
                on_stage=lambda stage, detail, state: self.stage.emit(f'{stage} · {detail}'),
            )
            self.completed.emit(self.context, deepcopy(result))
        except Exception as exc:
            logger.exception('Recommendation analysis failed')
            self.failed.emit(self.context, str(exc))


class SupersessionDialog(QDialog):
    """Present full candidate, evidence and qualified permission coverage.

    Args:
        details: Detached shared-service supersession detail payload.
        parent: Owning Recommendations page.
    """

    def __init__(self, details: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Supersession details')
        self.resize(1080, 760)
        self.setMinimumSize(720, 480)
        self.details = details
        layout = QVBoxLayout(self)
        finding = details['finding']
        layout.addWidget(label(finding['Classification'] or 'Supersession', 'eyebrow'))
        layout.addWidget(label('Review all qualifications before removing a statement in OCI.', 'notice', wrap=True))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        sections = QVBoxLayout(content)
        candidate = details['candidate'] or {}
        self._section(
            sections,
            'Candidate statement',
            [
                ('Policy', candidate.get('policy_name')),
                ('Policy compartment', candidate.get('compartment_path')),
                ('Effective scope', candidate.get('effective_path')),
                ('Original statement', candidate.get('statement_text')),
                (
                    'Conditions',
                    candidate.get('conditions') or candidate.get('conditions_where_clause') or 'None recorded',
                ),
            ],
        )
        self._section(
            sections,
            'Coverage notes',
            [
                ('Analysis', finding['Notes']),
                (
                    'Meaning',
                    'One unconditional statement must cover the full candidate permission set. Conditional evidence is review-only and is excluded from proof of complete coverage.',
                ),
            ],
        )
        for index, evidence in enumerate(finding['Evidence'], 1):
            status = 'Conditional · review only' if evidence.get('conditional') else 'Unconditional coverage'
            self._section(
                sections,
                f'{index}. {status}',
                [
                    ('Policy', evidence.get('policy_name')),
                    ('Effective scope', evidence.get('effective_path')),
                    ('Scope relationship', evidence.get('relationship')),
                    ('Original statement', evidence.get('statement_text')),
                    ('Covered permissions', ', '.join(evidence.get('covered_permissions') or [])),
                ],
            )
        sections.addStretch()
        scroll.setWidget(content)
        self.tabs.addTab(scroll, 'Candidate & evidence')
        columns = tuple(
            (key, key) for key in ('Permission', 'Unconditional coverage', 'Conditional evidence (review only)')
        )
        self.coverage = RecordTable(columns, details_title='Coverage details')
        self.coverage.setWordWrap(True)
        self.coverage.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.coverage.setColumnWidth(0, 240)
        self.coverage.setColumnWidth(1, 360)
        self.coverage.model.replace(details['coverage'])
        self.coverage.resizeRowsToContents()
        self.coverage.details_requested.connect(self._coverage_details)
        coverage_page = QWidget()
        coverage_layout = QVBoxLayout(coverage_page)
        coverage_layout.addWidget(self.coverage, 2)
        self.coverage_text = QPlainTextEdit()
        self.coverage_text.setReadOnly(True)
        self.coverage_text.setPlaceholderText('Right-click a permission for complete coverage text.')
        coverage_layout.addWidget(self.coverage_text, 1)
        self.tabs.addTab(coverage_page, 'Permission coverage')
        self.coverage.horizontalHeader().sectionResized.connect(lambda *_: self.coverage.resizeRowsToContents())
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlainText(json.dumps(details, indent=2, ensure_ascii=False, default=str))
        self.tabs.addTab(self.raw, 'Raw evidence')
        buttons = QHBoxLayout()
        copy = QPushButton('Copy candidate')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(str(candidate.get('statement_text') or '')))
        buttons.addWidget(copy)
        copy_all = QPushButton('Copy all evidence')
        copy_all.clicked.connect(lambda: QApplication.clipboard().setText(self.raw.toPlainText()))
        buttons.addWidget(copy_all)
        buttons.addStretch()
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        """Fit wrapped coverage rows after inherited font/theme styles are applied."""
        super().showEvent(event)
        QTimer.singleShot(0, self.coverage.resizeRowsToContents)

    def _section(self, layout, title, fields) -> None:
        layout.addWidget(label(title, 'eyebrow'))
        for key, value in fields:
            layout.addWidget(label(key, 'muted'))
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            text = label(str(value) if value not in (None, '') else 'Not recorded', wrap=True)
            text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            text.setContentsMargins(8, 0, 8, 10)
            layout.addWidget(text)

    def _coverage_details(self, record) -> None:
        if record:
            self.coverage_text.setPlainText('\n\n'.join(f'{key}\n{value}' for key, value in record.items()))


class RecommendationsPage(QWidget):
    """Browse shared findings and explicitly rebuild missing report material.

    Attributes:
        busy_changed: Shell serialization gate while analysis mutates derived state.
        analysis_finished: Context needing consumer rebinding after success/failure.
        details_requested: Read-only general finding inspection request.
        worker: Retained background worker or None while idle.
    """

    busy_changed = Signal(bool)
    analysis_finished = Signal(object)
    details_requested = Signal(object)

    def __init__(self, settings: dict) -> None:
        super().__init__()
        self.settings = settings
        self.context, self.worker = None, None
        self.payload = {}
        self.block_reason = ''
        self.dialog = None
        self._error = ''
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.run_button = QPushButton('Run analysis')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_analysis)
        controls.addWidget(self.run_button)
        controls.addStretch()
        layout.addLayout(controls)
        risk_panel = QWidget()
        risk_form = QFormLayout(risk_panel)
        self.where_reduction, self.service_reduction = QComboBox(), QComboBox()
        for combo, key, title in (
            (self.where_reduction, 'risk_where_clause_reduction_pct', 'WHERE risk reduction'),
            (self.service_reduction, 'risk_service_principal_reduction_pct', 'Service principal risk reduction'),
        ):
            for value in (0, 25, 50, 75, 90):
                combo.addItem(f'{value}%', value)
            combo.setCurrentIndex(max(0, combo.findData(settings.get(key, 50))))
            risk_form.addRow(title, combo)
        self.summary = label('', 'muted', wrap=True)
        risk_form.addRow(self.summary)
        risk_form.addRow(
            label(
                'Findings reflect loaded snapshot evidence. Conditions and exclusions remain relevant. Disabled checks and missing source data can leave sections empty.',
                'muted',
                wrap=True,
            )
        )
        layout.addWidget(CollapsibleSection('Analysis settings and coverage', risk_panel))
        self.status = label('Load a snapshot to review recommendations.', 'notice', wrap=True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.tables, self.searches, self.counts = {}, {}, {}
        self.severity, self.category, self.compartment, self.limit_status = (QComboBox() for _ in range(4))
        for key, title, fields in SECTIONS:
            page = QWidget()
            rows = QVBoxLayout(page)
            filters = QHBoxLayout()
            search = QLineEdit()
            search.setPlaceholderText(f'Search {title.lower()}…')
            search.setClearButtonEnabled(True)
            filters.addWidget(search, 1)
            if key == 'summary':
                filters.addWidget(self.severity)
                filters.addWidget(self.category)
            elif key == 'supersession':
                filters.addWidget(self.compartment)
            elif key == 'limits':
                filters.addWidget(self.limit_status)
            rows.addLayout(filters)
            columns = tuple((field, field) for field in fields)
            table = RecordTable(
                columns,
                source_model=FindingModel(columns, None),
                details_title='Supersession details' if key == 'supersession' else 'Finding details',
            )
            table.horizontalHeader().setSectionResizeMode(len(fields) - 1, QHeaderView.ResizeMode.Interactive)
            table.setColumnWidth(len(fields) - 1, 320)
            table.proxy.setSortRole(Qt.ItemDataRole.UserRole)
            if key in {'risk_policy', 'risk_statement'}:
                table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
            table.details_requested.connect(lambda record, section=key: self._details(section, record))
            table.doubleClicked.connect(
                lambda index, section=key, view=table: self._details(section, view.record_at(index))
            )
            rows.addWidget(table, 1)
            count = label('', 'muted')
            rows.addWidget(count)
            self.tables[key], self.searches[key], self.counts[key] = table, search, count
            search.textChanged.connect(lambda text, section=key: self._filter(section))
            self.tabs.addTab(page, title)
        for combo, key in (
            (self.severity, 'summary'),
            (self.category, 'summary'),
            (self.compartment, 'supersession'),
            (self.limit_status, 'limits'),
        ):
            combo.currentIndexChanged.connect(lambda index, section=key: self._filter(section))
        layout.addWidget(self.tabs, 1)
        self._controls()

    def set_context(self, context) -> None:
        """Replace snapshot findings without running analytics or fetching OCI data."""
        self.context = context
        self._clear_dialog()
        self.details_requested.emit(None)
        self.payload = RecommendationsService(context).get_dashboard_payload(fetch_limits=False) if context else {}
        self._publish_payload()
        self._controls()

    def set_block_reason(self, reason: str) -> None:
        """Prevent analysis while loading, simulation, reports or MCP own the data."""
        self.block_reason = reason
        self._controls()

    def run_analysis(self) -> None:
        """Run configured checks and rebuild report prerequisites on explicit request."""
        if not self.run_button.isEnabled() or self.worker is not None:
            return
        settings = deepcopy(self.settings)
        settings.update(
            {
                'risk_where_clause_reduction_pct': self.where_reduction.currentData(),
                'risk_service_principal_reduction_pct': self.service_reduction.currentData(),
            }
        )
        self._error = ''
        self._clear_dialog()
        self.details_requested.emit(None)
        self.worker = RecommendationWorker(self.context, settings, self)
        self.worker.stage.connect(self.status.setText)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self._controls()
        self.status.setText('Running configured checks and rebuilding reports…')
        self.worker.start()

    def _controls(self) -> None:
        busy = self.worker is not None
        self.run_button.setEnabled(self.context is not None and not busy and not self.block_reason)
        self.tabs.setEnabled(not busy)
        self.where_reduction.setEnabled(not busy)
        self.service_reduction.setEnabled(not busy)
        self.run_button.setToolTip(
            self.block_reason
            or 'Uses enabled checks from Overview settings; rebuilds permissions reports and resets simulation results.'
        )

    def _publish_payload(self) -> None:
        for combo, title, values in (
            (
                self.severity,
                'All priorities',
                {str(row.get('Priority') or '') for row in self.payload.get('summary', [])},
            ),
            (
                self.category,
                'All categories',
                {str(row.get('Category') or '') for row in self.payload.get('summary', [])},
            ),
            (
                self.compartment,
                'All compartments',
                {str(row.get('hierarchy_path') or '') for row in getattr(self.context.policy_repo, 'compartments', [])}
                if self.context
                else set(),
            ),
            (
                self.limit_status,
                'All statuses',
                {str(row.get('Status') or '') for row in self.payload.get('limits', [])},
            ),
        ):
            selected = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(title, '')
            for value in sorted(values - {''}):
                combo.addItem(value, value)
            combo.setCurrentIndex(max(0, combo.findText(selected)))
            combo.blockSignals(False)
        for key in self.tables:
            self._filter(key)
        if not self.context:
            self.status.setText('Load a snapshot to review recommendations.')
            self.summary.clear()
            return
        permissions_ready = bool(getattr(self.context.intelligence, 'permissions_report', {}))
        self.status.setText(
            'Full analysis available. Review findings and coverage notes before making changes.'
            if permissions_ready
            else 'Query foundations are loaded. Run analysis to build recommendations and the Effective Permissions report.'
        )
        meta = self.payload.get('meta', {})
        enabled = self.context.settings.get('enabled_intelligence_checks') or ['All default checks']
        limits = self.payload.get('tenancy_policy_limits') or {}
        self.summary.setText(
            f'{meta.get("tenancy_name") or "Snapshot"} · Data as of {meta.get("data_as_of") or "not recorded"} · Configured checks: {", ".join(enabled)}\n'
            f'Policy chain statement limit: {limits.get("policy_statements_per_compartment_chain_count") or "not supplied"}. Counts reflect loaded inventory. Full analysis resets simulation results; no policies are changed.'
        )

    def _filter(self, key) -> None:
        rows = self.payload.get(key, [])
        selected = []
        for row in rows:
            if key == 'summary' and any(
                combo.currentData() and row.get(field) != combo.currentData()
                for combo, field in ((self.severity, 'Priority'), (self.category, 'Category'))
            ):
                continue
            path = str(row.get('Effective Path') or '').rstrip('/')
            scope = str(self.compartment.currentData() or '').rstrip('/')
            if key == 'supersession' and scope and path != scope and not path.startswith(scope + '/'):
                continue
            if (
                key == 'limits'
                and self.limit_status.currentData()
                and row.get('Status') != self.limit_status.currentData()
            ):
                continue
            selected.append(row)
        table = self.tables[key]
        table.model.replace(selected)
        table.proxy.setFilterFixedString(self.searches[key].text())
        self.counts[key].setText(
            f'Showing {table.proxy.rowCount()} of {len(rows)} · Right-click or double-click for details'
        )

    def _details(self, key, record) -> None:
        if record is None:
            self.details_requested.emit(None)
            return
        if key == 'supersession':
            details = RecommendationsService(self.context).supersession_details(str(record['Internal ID']))
            if details:
                self._clear_dialog()
                self.dialog = SupersessionDialog(details, self)
                self.dialog.show()
        else:
            self.details_requested.emit(record)

    def _clear_dialog(self) -> None:
        if self.dialog:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def _completed(self, context, payload) -> None:
        if context is self.context:
            self.payload = payload

    def _failed(self, context, message) -> None:
        if context is self.context:
            self._error = f'Analysis failed: {message}. Derived results may be incomplete; rerun analysis or reload.'

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker:
            context = worker.context
            worker.deleteLater()
            if context is self.context:
                # Rebind all consumers even on failure: enrichment replaces engines incrementally.
                self.analysis_finished.emit(context)
                self._publish_payload()
                if self._error:
                    self.status.setText(self._error)
        self._controls()
        self.busy_changed.emit(False)
