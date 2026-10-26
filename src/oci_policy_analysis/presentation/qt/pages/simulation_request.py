"""Configure an API request and condition inputs without evaluating access."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class SimulationRequestPage(QWidget):
    """Select a catalog operation and supply values for checked condition fields.

    Args:
        controller: Owner of the current snapshot, inclusion and request state.

    Attributes:
        input_widgets: Condition variable mapping to value and null controls.
        back_requested: Navigate to Statements without discarding request inputs.

    Notes:
        Metadata comes from ReferenceDataService; condition schemas are prepared
        by SimulationService in the owned worker. No policy is evaluated here.
    """

    back_requested = Signal()
    run_requested = Signal()
    inputs_changed = Signal()

    def __init__(self, controller):
        """Build guided operation selection, context fields and a request preview."""
        super().__init__()
        self.controller = controller
        self.context = None
        self.catalog = []
        self.input_widgets = {}
        self._updating = False
        self._conditions = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label('1. Choose the API request to test', 'eyebrow'))
        layout.addWidget(
            label(
                'Choose an API group and operation from the bundled reference catalog. Required permissions describe the primary operation; related checks are advisory.',
                wrap=True,
            )
        )
        selectors = QHBoxLayout()
        self.group = QComboBox()
        self.group.setAccessibleName('API catalog group')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find an API operation…')
        self.search.setClearButtonEnabled(True)
        selectors.addWidget(self.group, 1)
        selectors.addWidget(self.search, 2)
        layout.addLayout(selectors)
        self.operation = QComboBox()
        self.operation.setAccessibleName('API operation')
        self.operation.setMinimumContentsLength(30)
        layout.addWidget(self.operation)
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.metadata.setMaximumHeight(100)
        self.metadata.setPlaceholderText('Select an operation to see its primary permissions and reference notes.')
        layout.addWidget(self.metadata)
        layout.addWidget(label('2. Supply condition values for the checked statements', 'eyebrow'))
        layout.addWidget(
            label(
                'Blank or Null / not supplied leaves a value absent. This can be intentional, such as for a !variable condition. Values stay when you return to Statements and keep the same fields.',
                'muted',
                wrap=True,
            )
        )
        self.tabs = QTabWidget()
        self.inputs = QScrollArea()
        self.inputs.setWidgetResizable(True)
        self.tabs.addTab(self.inputs, 'Condition inputs')
        self.conditions = RecordTable(
            (
                ('Statement ID', 'internal_id'),
                ('Parse status', 'parse_status'),
                ('Warnings', 'warnings'),
                ('Condition', 'clause'),
            )
        )
        self.tabs.addTab(self.conditions, 'Condition evidence')
        related = QWidget()
        related_layout = QVBoxLayout(related)
        related_layout.addWidget(
            label(
                'Advisory dependencies only. They do not change the primary model outcome, and the snapshot may not establish whether a related resource is attached.',
                'notice',
                wrap=True,
            )
        )
        self.related = RecordTable(
            (
                ('Resource', 'resource'),
                ('Permissions', 'permissions'),
                ('Applies when', 'applies_when'),
                ('Hint', 'failure_hint'),
            )
        )
        related_layout.addWidget(self.related, 1)
        self.tabs.addTab(related, 'Related checks')
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.addWidget(
            label(
                'Read-only JSON input for the local simulation: principal, operation, target, context values and statement selections. Nothing is sent to OCI.',
                'muted',
                wrap=True,
            )
        )
        preview_layout.addWidget(self.preview, 1)
        self.tabs.addTab(preview_panel, 'Request JSON')
        layout.addWidget(self.tabs, 1)
        self.status = label('Prepare statements first.', 'muted', wrap=True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        back = QPushButton('Back: Statements')
        back.clicked.connect(self.back_requested.emit)
        actions.addWidget(back)
        actions.addStretch()
        self.copy = QPushButton('Copy request JSON')
        self.copy.setEnabled(False)
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.preview.toPlainText()))
        actions.addWidget(self.copy)
        self.run = QPushButton('Run simulation')
        self.run.setObjectName('primary')
        self.run.setEnabled(False)
        self.run.clicked.connect(self.run_requested.emit)
        actions.addWidget(self.run)
        layout.addLayout(actions)
        layout.addWidget(
            label(
                'Run evaluates the loaded model and records original inputs in this snapshot’s history.',
                'muted',
                wrap=True,
            )
        )
        self.group.currentIndexChanged.connect(self._filter_operations)
        self.search.textChanged.connect(self._filter_operations)
        self.operation.currentIndexChanged.connect(self._operation_changed)
        self._replace_inputs([])

    def set_context(self, context):
        """Replace the reference catalog and discard inputs from the prior snapshot.

        Args:
            context: Newly published AppContext, read only for reference lookups.
        """
        self.context = context
        self.catalog = context.reference_data_service.list_operations_with_permissions()
        self._updating = True
        self.group.clear()
        self.group.addItem('All API groups', '')
        for group in sorted({row['api_name'] for row in self.catalog}):
            self.group.addItem(group, group)
        self.search.clear()
        self._updating = False
        self._filter_operations()
        self.clear_request()

    def clear_request(self):
        """Clear operation, values and evidence after upstream invalidation."""
        self.controller.api_operation = ''
        self.controller.operation_name = ''
        self.controller.where_values = {}
        self.operation.setCurrentIndex(0)
        self.metadata.clear()
        self.related.model.replace([])
        self.conditions.model.replace([])
        self._conditions = []
        self._replace_inputs([])
        self._update_preview()

    def refresh_selection(self):
        """Project prepared schemas onto checked IDs, keeping surviving input values."""
        checked = set(self.controller.checked_ids)
        self._conditions = [
            row for row in self.controller.condition_schema['conditions'] if row['internal_id'] in checked
        ]
        fields = sorted({name for row in self._conditions for name in row['variables']} - {'request.operation'})
        self.conditions.model.replace(self._conditions)
        self._replace_inputs(fields)
        self._values_changed()

    def _filter_operations(self, *_args):
        if self._updating:
            return
        prior = self.controller.api_operation
        group = self.group.currentData()
        query = self.search.text().strip().casefold()
        self.operation.blockSignals(True)
        self.operation.clear()
        rows = [
            row for row in self.catalog if (not group or row['api_name'] == group) and query in row['label'].casefold()
        ]
        self.operation.addItem('Choose an API operation…' if rows else 'No matching API operations', None)
        for row in rows:
            self.operation.addItem(row['label'], row)
        for index in range(1, self.operation.count()):
            if self.operation.itemData(index)['label'] == prior:
                self.operation.setCurrentIndex(index)
                break
        self.operation.blockSignals(False)
        self._operation_changed()

    def _operation_changed(self, *_args):
        row = self.operation.currentData()
        self.controller.api_operation = row['label'] if row else ''
        self.controller.operation_name = (row.get('request_operation') or row['operation_name']) if row else ''
        self.related.model.replace(row['related_checks'] if row else [])
        self.metadata.setPlainText(
            'Primary permissions: '
            + (', '.join(row['permissions']) or 'No primary permission mapping listed; coverage is incomplete.')
            + '\nrequest.operation (automatic): '
            + (row.get('request_operation') or row['operation_name'])
            + ('\nReference notes: ' + row['notes'] if row['notes'] else '')
            if row
            else ''
        )
        self._update_preview()
        self.inputs_changed.emit()

    def _replace_inputs(self, names):
        prior = {name: (value.text(), null.isChecked()) for name, (value, null) in self.input_widgets.items()}
        content = QWidget()
        form = QFormLayout(content)
        form.setVerticalSpacing(12)
        self.input_widgets = {}
        if not names:
            form.addRow(
                label('No manual condition values are needed for the current checked statements.', 'muted', wrap=True)
            )
        for name in names:
            value = QLineEdit()
            value.setPlaceholderText(
                {'request.utc-timestamp': '2026-01-05T12:34:56Z', 'request.utc-timestamp.time-of-day': '13:27:00Z'}.get(
                    name, 'Blank = not supplied'
                )
            )
            null = QCheckBox('Null / not supplied')
            if name in prior:
                value.setText(prior[name][0])
                null.setChecked(prior[name][1])
            value.setEnabled(not null.isChecked())
            value.textChanged.connect(self._values_changed)
            null.toggled.connect(value.setDisabled)
            null.toggled.connect(self._values_changed)
            row = QHBoxLayout()
            row.addWidget(value, 1)
            row.addWidget(null)
            form.addRow(name, row)
            self.input_widgets[name] = (value, null)
        old = self.inputs.takeWidget()
        self.inputs.setWidget(content)
        if old:
            old.deleteLater()

    def _values_changed(self, *_args):
        self.controller.where_values = {
            name: None if null.isChecked() else value.text() for name, (value, null) in self.input_widgets.items()
        }
        self._update_preview()
        self.inputs_changed.emit()

    def _update_preview(self):
        self.preview.setPlainText(json.dumps(self.controller.request_payload(), indent=2, ensure_ascii=False))
        unsupported = sum(row['parse_status'] != 'parsed' for row in self._conditions)
        unsupplied = sum(null.isChecked() or value.text() == '' for value, null in self.input_widgets.values())
        self.status.setText(
            f'{len(self.controller.checked_ids)} checked statements · {len(self.input_widgets)} manual fields · {unsupplied} not supplied. '
            + ('Choose an API operation. ' if not self.controller.api_operation else '')
            + (
                f'{unsupported} unsupported conditions: review Condition evidence; input coverage is incomplete. '
                if unsupported
                else ''
            )
            + 'Review inputs, then run the model simulation.'
        )
        self.copy.setEnabled(self.controller.ready and bool(self.controller.api_operation))
        self.run.setEnabled(self.controller.ready and bool(self.controller.api_operation))
