"""Native result evidence, related requests and reviewed what-if grant candidates."""

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, label


class SimulationResultsPage(QWidget):
    """Present original run evidence and explicit follow-up actions.

    Args:
        controller: Snapshot-bound simulation lifecycle and history owner.

    Attributes:
        report: Original displayed run, kept separate from edited request inputs.
        related_requested: A reviewed operation/path request requiring new preparation.
        prospective_requested: Draft candidates requiring review before persistence.
        details_requested: Native evidence-row inspection for the shared drawer.

    Notes:
        No action applies OCI changes. History JSON export uses an explicit file
        picker; generated candidates require a separate review/save action.
    """

    related_requested = Signal(dict)
    prospective_requested = Signal(object)
    details_requested = Signal(object, str)
    back_requested = Signal()

    def __init__(self, controller):
        """Build outcome, evidence, next-step and history controls."""
        super().__init__()
        self.controller = controller
        self.context = None
        self.report = None
        self.saved_history = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setSpacing(12)
        history_row = QHBoxLayout()
        history_row.addWidget(label('Run history'))
        self.history = QComboBox()
        self.history.currentIndexChanged.connect(self._select_history)
        history_row.addWidget(self.history, 1)
        refresh = QPushButton('Refresh history')
        refresh.clicked.connect(self.refresh_history)
        history_row.addWidget(refresh)
        export = QPushButton('Export history JSON…')
        export.clicked.connect(self._export)
        history_row.addWidget(export)
        layout.addLayout(history_row)
        self.outcome = label('No simulation run yet.', 'title', wrap=True)
        self.summary = label('Run a request to see its permission evidence.', wrap=True)
        headline = QHBoxLayout()
        headline.addWidget(self.outcome)
        headline.addSpacing(16)
        headline.addWidget(self.summary, 1)
        layout.addLayout(headline)
        self.current_status = label('', 'muted', wrap=True)
        layout.addWidget(self.current_status)
        layout.addWidget(
            label(
                'Snapshot model only; this is not an OCI authorization decision. Conditions and inventory may be incomplete.',
                'notice',
                wrap=True,
            )
        )
        self.tabs = QTabWidget()
        why = QWidget()
        why_layout = QVBoxLayout(why)
        self.findings = label('', wrap=True)
        why_layout.addWidget(self.findings)
        self.permissions = RecordTable((('Required permission', 'permission'), ('Model status', 'status')))
        why_layout.addWidget(self.permissions, 1)
        next_actions = QHBoxLayout()
        self.explore_policies = QPushButton('Explore policies for missing permissions')
        self.explore_policies.setEnabled(False)
        self.explore_policies.clicked.connect(lambda: self.tabs.setCurrentIndex(4))
        next_actions.addWidget(self.explore_policies)
        self.explore_related = QPushButton('Review related simulations')
        self.explore_related.setEnabled(False)
        self.explore_related.clicked.connect(lambda: self.tabs.setCurrentIndex(3))
        next_actions.addWidget(self.explore_related)
        why_layout.addLayout(next_actions)
        self.tabs.addTab(why, 'Why this outcome')
        self.evidence = QTreeWidget()
        self.evidence.setHeaderLabels(['Statement / evidence', 'Outcome / details'])
        self.evidence.setColumnWidth(0, 420)
        self.evidence.setWordWrap(True)
        self.tabs.addTab(self.evidence, 'Statement evidence')
        self.comparisons = RecordTable(
            (
                ('Statement ID', 'internal_id'),
                ('Variable', 'variable'),
                ('Input', 'sim_value'),
                ('Expected', 'expected'),
                ('Result', 'result'),
                ('Details', 'info'),
            )
        )
        self.tabs.addTab(self.comparisons, 'Condition comparisons')
        self._build_related()
        self._build_candidates()
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.tabs.addTab(self.raw, 'Full run JSON')
        layout.addWidget(self.tabs, 1)
        self.status = label('', 'muted', wrap=True)
        layout.addWidget(self.status)
        back = QPushButton('Back: Request context')
        back.clicked.connect(self.back_requested.emit)
        layout.addWidget(back)
        for table, title in (
            (self.permissions, 'Permission result'),
            (self.comparisons, 'Condition comparison'),
            (self.related, 'Related scenario'),
            (self.candidates, 'Policy candidate'),
            (self.corpus_examples, 'Corpus source example'),
        ):
            table.details_requested.connect(lambda record, title=title: self.details_requested.emit(record, title))
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)

    def _build_related(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            label(
                'Run a separate scenario for a dependency resource. Choose its compartment, which may differ from the primary request. Existing advisory results only considered the primary permission set.',
                wrap=True,
            )
        )
        self.related = RecordTable(
            (
                ('Operation', 'api_operation'),
                ('Resource', 'resource'),
                ('Applies when', 'applies_when'),
                ('Reason', 'reason'),
            )
        )
        self.related.selectionModel().selectionChanged.connect(self._related_selected)
        layout.addWidget(self.related, 1)
        form = QFormLayout()
        self.related_operation = QComboBox()
        self.related_operation.setEditable(True)
        self.related_operation.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.related_path = QComboBox()
        form.addRow('Follow-up operation', self.related_operation)
        form.addRow('Related resource compartment', self.related_path)
        layout.addLayout(form)
        self.related_button = QPushButton('Prepare related simulation')
        self.related_button.clicked.connect(self._start_related)
        layout.addWidget(self.related_button)
        self.tabs.addTab(page, 'Related simulations')

    def _build_candidates(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.addWidget(
            label(
                'Review failed conditions and denies first. Candidate allows cannot override denies. Choose the grant principal, scope and restrictions; broader resource/family grants list their extra permissions.',
                wrap=True,
            )
        )
        form = QFormLayout()
        self.grant_principal = QComboBox()
        form.addRow('Grant to principal', self.grant_principal)
        row = QHBoxLayout()
        self.granularity = QComboBox()
        for text, key in [
            ('Explicit missing permissions', 'permission'),
            ('Resource + verb', 'resource'),
            ('Family + verb', 'family'),
        ]:
            self.granularity.addItem(text, key)
        self.policy_path = QComboBox()
        self.target_path = QComboBox()
        row.addWidget(self.granularity, 1)
        row.addWidget(label('Store policy in'))
        row.addWidget(self.policy_path, 1)
        row.addWidget(label('Target'))
        row.addWidget(self.target_path, 1)
        form.addRow('Grant shape & scope', row)
        restriction = QHBoxLayout()
        self.restriction = QComboBox()
        self.restriction.addItems(['No additional condition', 'Only this API operation', 'Custom where clause'])
        self.where_clause = QLineEdit()
        self.where_clause.setPlaceholderText('Custom condition expression without where')
        self.where_clause.setEnabled(False)
        self.restriction.currentIndexChanged.connect(lambda index: self.where_clause.setEnabled(index == 2))
        restriction.addWidget(self.restriction)
        restriction.addWidget(self.where_clause, 1)
        form.addRow('Restrictions', restriction)
        options_layout.addLayout(form)
        self.generate = QPushButton('Build policy candidates')
        self.generate.clicked.connect(self._generate)
        options_layout.addWidget(self.generate)
        self.candidate_options = CollapsibleSection('Choose grant scope and restrictions', options)
        self.candidate_options.button.setChecked(True)
        layout.addWidget(self.candidate_options)
        result_tabs = QTabWidget()
        draft_page = QWidget()
        draft_layout = QVBoxLayout(draft_page)
        draft_layout.setContentsMargins(0, 0, 0, 0)
        self.candidates = RecordTable(
            (
                ('Mapping', 'mapping'),
                ('Covers', 'covered_permissions'),
                ('Extra permissions', 'additional_permissions'),
                ('Candidate statement', 'statement_text'),
            ),
            multi_select=True,
        )
        draft_layout.addWidget(self.candidates, 1)
        self.add_prospects = QPushButton('Review / add selected drafts to prospects…')
        self.add_prospects.clicked.connect(self._add_selected)
        self.add_prospects.setEnabled(False)
        self.candidates.selectionModel().selectionChanged.connect(
            lambda *_: self.add_prospects.setEnabled(bool(self.candidates.selected_records()))
        )
        draft_layout.addWidget(self.add_prospects)
        result_tabs.addTab(draft_page, 'Candidate drafts')
        self.corpus_examples = RecordTable(
            (
                ('Permission', 'permission'),
                ('Effect', 'effect'),
                ('Principal', 'principal_key'),
                ('Path', 'effective_path'),
                ('Source statement', 'statement_text'),
            )
        )
        result_tabs.addTab(self.corpus_examples, 'Corpus examples (may have other scope)')
        layout.addWidget(result_tabs, 1)
        self.candidate_notes = label('', 'muted', wrap=True)
        layout.addWidget(self.candidate_notes)
        self.tabs.addTab(page, 'Policy candidates')
        for control in (self.grant_principal, self.granularity, self.policy_path, self.target_path, self.restriction):
            control.currentIndexChanged.connect(self._clear_candidates)
        self.where_clause.textChanged.connect(self._clear_candidates)

    def set_context(self, context):
        """Replace the snapshot, clear displayed results and bind known choice lists."""
        self.context = context
        self.report = None
        service = SimulationWorkbenchService(context)
        metadata = service.suggestion_metadata()
        self.grant_principal.clear()
        self.grant_principal.addItem('Choose a grant principal…', '')
        self.grant_principal.addItems(metadata['principals'])
        for combo in (self.related_path, self.policy_path, self.target_path):
            combo.clear()
            combo.addItem('Choose compartment…', '')
            for path in metadata['locations']:
                combo.addItem(path, path)
        self.policy_path.setCurrentText('ROOT')
        self.related_operation.clear()
        self.related_operation.addItem('Choose a catalog operation…', '')
        for row in context.reference_data_service.list_operations_with_permissions():
            self.related_operation.addItem(row['label'], row['label'])
        self.show_history(self.controller.history)
        self.outcome.setText('No simulation run yet.')
        self.summary.setText('Run a request to see its permission evidence.')
        self.current_status.clear()
        self.status.clear()
        self.permissions.model.replace([])
        self.comparisons.model.replace([])
        self.related.model.replace([])
        self.evidence.clear()
        self.raw.clear()
        self.findings.clear()
        self._clear_candidates()
        self.generate.setEnabled(False)
        self.related_button.setEnabled(False)
        self.explore_policies.setEnabled(False)
        self.explore_related.setEnabled(False)

    def show_history(self, history):
        """List every run by timestamp, operation and target path without re-executing."""
        self.saved_history = history
        self.history.blockSignals(True)
        self.history.clear()
        for index, entry in enumerate(history):
            report = entry.get('workbench_report')
            path = (
                report['request']['compartment_path']
                if report
                else (entry['trace'].get('simulation_trace') or {})
                .get('simulation_context', {})
                .get('effective_path', '')
            )
            self.history.addItem(
                f'{index + 1} · {report["timestamp"] if report else entry["timestamp"]} · {"ALLOW" if entry["api_call_allowed"] else "DENY"} · {entry["api_operation"]} · {path}',
                index,
            )
        self.history.setCurrentIndex(len(history) - 1)
        self.history.blockSignals(False)

    def refresh_history(self):
        """Read current engine history, including runs from other active consumers."""
        if self.context is None or self.controller.worker is not None:
            return
        self.controller.history = SimulationWorkbenchService(self.context).history()
        self.show_history(self.controller.history)
        if self.saved_history:
            self._select_history(len(self.saved_history) - 1)

    def show_report(self, report):
        """Render an original report with expandable native statement evidence."""
        self.report = report
        result, request = report['result'], report['request']
        self.outcome.setText(
            ('Model ALLOW' if result['api_call_allowed'] else 'Model DENY')
            + (' · incomplete operation mapping' if not result['required_permissions_for_api_operation'] else '')
        )
        self.summary.setText(
            f'{request["api_operation"]} · {request["compartment_path"]}\nPrincipal: {request["principal_key"]} · {len(request.get("checked_statement_ids", []))} included statements · {report.get("timestamp", "")}'
        )
        self.current_status.setText('Saved run: the current request has different inputs.')
        self.current_status.setVisible(self.controller.request_payload() != request)
        self.findings.setText(
            '\n\n'.join(report['findings'])
            or 'All primary permissions are present in this model run. Review conditions and related-resource scenarios before drawing conclusions about OCI access.'
        )
        self.permissions.model.replace(report['permissions'])
        self.comparisons.model.replace(report['comparisons'])
        self.related.model.replace(report['related_scenarios'])
        self.related_operation.setCurrentIndex(0)
        self.related_path.setCurrentIndex(0)
        self.grant_principal.setCurrentIndex(max(0, self.grant_principal.findText(request['principal_key'])))
        self.target_path.setCurrentText(request['compartment_path'])
        self._clear_candidates()
        self.candidate_options.button.setChecked(True)
        self.generate.setEnabled(bool(result['missing_permissions']))
        self.explore_policies.setEnabled(bool(result['missing_permissions']))
        self.explore_related.setEnabled(bool(report['related_scenarios']))
        self.related_button.setEnabled(bool(request.get('principal_type')))
        self.evidence.clear()
        for row in result['simulation_trace']['trace_statements']:
            status = (
                'Condition failed'
                if not row['passed']
                else ('Deny matched' if row['action'] == 'deny' else 'Grant matched')
            )
            item = QTreeWidgetItem(
                self.evidence, [row.get('policy_name') or row.get('internal_id') or row['action'].upper(), status]
            )
            QTreeWidgetItem(item, ['Original statement', row['statement_text']])
            QTreeWidgetItem(
                item,
                [
                    'Source / scope',
                    f'{"Prospective" if row.get("prospective") else "Loaded"} · {row.get("internal_id", "")} · {row.get("effective_path", "")}',
                ],
            )
            QTreeWidgetItem(
                item,
                [
                    'Reason',
                    row['fail_reason']
                    or (
                        'Matching deny subtracts these permissions.'
                        if row['action'] == 'deny'
                        else 'Passing statement contributes these permissions.'
                    ),
                ],
            )
            QTreeWidgetItem(item, ['Permissions', ', '.join(row['permissions']) or 'No permissions contributed'])
            if row.get('permissions_revoked'):
                QTreeWidgetItem(item, ['Actually revoked', ', '.join(row['permissions_revoked'])])
            if not row['passed'] or row['action'] == 'deny':
                item.setExpanded(True)
        self.raw.setPlainText(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        self.tabs.setCurrentIndex(0)
        self.status.clear()

    def mark_stale(self):
        """Keep saved evidence visible but distinguish it from edited request inputs."""
        if self.report:
            self.current_status.setText(
                'Request inputs changed. This is a saved run; run again to evaluate the current request.'
            )
            self.current_status.show()

    def show_candidates(self, result):
        """Display validated draft alternatives and their additional permissions."""
        self.candidates.model.replace(result['candidates'])
        self.candidate_options.button.setChecked(False)
        self.corpus_examples.model.replace(result['evidence'])
        self.candidate_notes.setText(
            result['limitations']
            + (
                ' Unmapped permissions: ' + ', '.join(result['unmapped_permissions'])
                if result['unmapped_permissions']
                else ''
            )
        )
        self.status.setText(
            f'{len(result["candidates"])} candidate statements prepared. Select drafts to review and save locally, then rerun.'
        )

    def _clear_candidates(self, *_args):
        self.candidates.model.replace([])
        self.corpus_examples.model.replace([])
        self.candidate_notes.clear()
        self.add_prospects.setEnabled(False)

    def _generate(self):
        if not self.report:
            return
        where = self.where_clause.text().strip() if self.restriction.currentIndex() == 2 else ''
        if self.restriction.currentIndex() == 2 and not where:
            self.status.setText('Enter the custom where restriction before generating candidates.')
            return
        if self.restriction.currentIndex() == 1:
            operation = self.report['request']['where_context'].get('request.operation', '')
            where = f"request.operation = '{operation}'"
        self.controller.suggest(
            self.report,
            {
                'principal_key': self.grant_principal.currentText(),
                'granularity': self.granularity.currentData(),
                'effective_path': self.target_path.currentData(),
                'policy_path': self.policy_path.currentData(),
                'where_clause': where,
            },
        )

    def _add_selected(self):
        rows = self.candidates.selected_records()
        if rows:
            self.prospective_requested.emit(rows)

    def _related_selected(self, *_args):
        rows = self.related.selected_records()
        if rows:
            self.related_operation.setCurrentText(rows[0]['api_operation'])

    def _start_related(self):
        if not self.report:
            return
        operation = self.related_operation.currentText()
        index = self.related_operation.findText(operation, Qt.MatchFlag.MatchExactly)
        if index < 1 or self.related_operation.itemData(index) != operation or not self.related_path.currentData():
            self.status.setText('Choose a valid catalog operation and the related resource compartment first.')
            return
        self.related_requested.emit(
            {
                **self.report['request'],
                'api_operation': operation,
                'compartment_path': self.related_path.currentData(),
                'checked_statement_ids': None,
                'where_context': {},
            }
        )

    def _select_history(self, index):
        if index < 0 or not self.saved_history:
            return
        entry = self.saved_history[index]
        report = entry.get('workbench_report')
        if report:
            self.show_report(report)
        else:
            # Legacy engine history is retained verbatim even without prepared inputs.
            self.report = None
            self.outcome.setText('Saved engine run · ' + ('ALLOW' if entry['api_call_allowed'] else 'DENY'))
            self.summary.setText(entry['api_operation'] + ' · ' + entry['timestamp'])
            self.current_status.setText(
                'Legacy run: full evidence is available in Full run JSON. Request inputs were not captured by this workbench.'
            )
            self.raw.setPlainText(json.dumps(entry, indent=2, default=str))
            self.permissions.model.replace([])
            self.comparisons.model.replace([])
            self.related.model.replace([])
            self.evidence.clear()
            self.findings.clear()
            self._clear_candidates()
            self.generate.setEnabled(False)
            self.related_button.setEnabled(False)
            self.explore_policies.setEnabled(False)
            self.explore_related.setEnabled(False)
            self.tabs.setCurrentWidget(self.raw)

    def _export(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, 'Export simulation history', 'simulation-history.json', 'JSON (*.json)'
        )
        if path:
            from pathlib import Path

            try:
                Path(path).write_text(
                    json.dumps(self.saved_history, indent=2, ensure_ascii=False, default=str), encoding='utf-8'
                )
                self.status.setText('History exported: ' + path)
            except OSError as exc:
                self.status.setText('Could not export history: ' + str(exc))
