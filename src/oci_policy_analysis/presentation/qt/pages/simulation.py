"""Guided simulation environment setup and statement inclusion."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget

from oci_policy_analysis.application.services.simulation_service import SimulationService
from oci_policy_analysis.presentation.qt.pages.simulation_request import SimulationRequestPage
from oci_policy_analysis.presentation.qt.pages.simulation_results import SimulationResultsPage
from oci_policy_analysis.presentation.qt.pages.simulation_statements import SimulationStatementsPage
from oci_policy_analysis.presentation.qt.simulation_controller import SimulationController
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class SimulationPage(QTabWidget):
    """Select a snapshot-bound environment without running a simulation.

    Attributes:
        context: Current snapshot, replaced after each successful load.
        scenario: Current principal/key/path inputs, or None until complete.
        manage_prospective: Request navigation to the existing what-if editor.

    Notes:
        Preparation does not evaluate requests or record history. Explicit Run
        actions evaluate the model in an owned worker and retain original inputs.
    """

    manage_prospective = Signal()
    details_requested = Signal(object, str)
    prospective_requested = Signal(object)

    def __init__(self):
        """Build environment controls and clearly labeled remaining steps."""
        super().__init__()
        self.context = None
        self.scenario = None
        self.options = {}
        self._pending_request = None
        self.controller = SimulationController(self)
        self.controller.prepared.connect(self._prepared)
        self.controller.invalidated.connect(self._invalidate_statements)
        self.controller.failed.connect(self._preparation_failed)
        self.controller.busy_changed.connect(self._preparation_busy)
        self.controller.executed.connect(self._executed)
        environment = QWidget()
        layout = QVBoxLayout(environment)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(label('Set up the request environment', 'eyebrow'))
        layout.addWidget(label('Choose who is making the request and where it occurs.', wrap=True))
        layout.addWidget(
            label(
                'Simulation models the loaded snapshot. Identity and policy coverage may be incomplete; results do not establish an OCI authorization decision.',
                'notice',
                wrap=True,
            )
        )
        layout.addSpacing(4)
        layout.addWidget(label('1. Choose an identity and target compartment', 'eyebrow'))
        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.principal_type = QComboBox()
        self.principal = QComboBox()
        self.compartment = QComboBox()
        self.principal_type.setMinimumWidth(160)
        self.principal.setMinimumWidth(280)
        identity = QHBoxLayout()
        identity.setSpacing(12)
        identity.addWidget(self.principal_type, 1)
        identity.addWidget(label('Principal'))
        identity.addWidget(self.principal, 3)
        form.addRow('Principal type', identity)
        form.addRow('Effective compartment', self.compartment)
        layout.addLayout(form)
        self.identity_note = label('', 'muted', wrap=True)
        layout.addWidget(self.identity_note)
        layout.addSpacing(8)
        layout.addWidget(label('Environment summary', 'eyebrow'))
        self.summary = label('Load a snapshot to select an environment.', wrap=True)
        layout.addWidget(self.summary)
        layout.addSpacing(8)
        layout.addWidget(label('2. Review optional what-if policies', 'eyebrow'))
        layout.addWidget(
            label(
                'All saved what-if statements for this snapshot are shown below. Scope and eligibility will be reviewed in the Statements step.',
                'muted',
                wrap=True,
            )
        )
        self.prospects = RecordTable(
            (
                ('Policy', 'policy_name'),
                ('Compartment', 'compartment_path'),
                ('Valid', 'valid'),
                ('Statement', 'statement_text'),
            )
        )
        layout.addWidget(self.prospects, 1)
        self.manage = QPushButton('Manage prospective statements…')
        self.manage.clicked.connect(self.manage_prospective.emit)
        navigation = QHBoxLayout()
        navigation.addWidget(self.manage)
        navigation.addStretch()
        self.continue_button = QPushButton('Next: Select statements')
        self.continue_button.setObjectName('primary')
        self.continue_button.clicked.connect(self._open_statements)
        navigation.addWidget(self.continue_button)
        layout.addLayout(navigation)
        self.preparation_status = label(
            'Confirm the environment, then continue to review applicable statements.', 'muted', wrap=True
        )
        layout.addWidget(self.preparation_status)
        self.addTab(environment, '1. Environment')
        self.statements = SimulationStatementsPage()
        self.statements.back_requested.connect(lambda: self.setCurrentIndex(0))
        self.statements.next_requested.connect(lambda: self.setCurrentIndex(2))
        self.statements.selection.checked_changed.connect(self._checked_changed)
        self.statements.selection.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Simulation statement details')
        )
        self.addTab(self.statements, '2. Statements')
        self.request_context = SimulationRequestPage(self.controller)
        self.request_context.run_requested.connect(self.controller.execute)
        self.request_context.back_requested.connect(lambda: self.setCurrentIndex(1))
        self.request_context.conditions.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Simulation condition details')
        )
        self.request_context.related.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Related permission check')
        )
        self.addTab(self.request_context, '3. Request context')
        self.results = SimulationResultsPage(self.controller)
        self.results.back_requested.connect(lambda: self.setCurrentIndex(2 if self.controller.ready else 0))
        self.results.details_requested.connect(self.details_requested.emit)
        self.results.related_requested.connect(self.prepare_followup)
        self.results.prospective_requested.connect(self.prospective_requested.emit)
        self.request_context.inputs_changed.connect(self.results.mark_stale)
        self.controller.suggestions_ready.connect(self.results.show_candidates)
        self.addTab(self.results, '4. Results && history')
        self.principal_type.currentTextChanged.connect(self._type_changed)
        self.principal.currentIndexChanged.connect(self._update_summary)
        self.compartment.currentTextChanged.connect(self._update_summary)
        self.currentChanged.connect(self._tab_changed)
        self.setEnabled(False)

    def set_context(self, context):
        """Replace the snapshot and discard all previous environment selections.

        Args:
            context: Newly published AppContext. No source files are written.
        """
        self.context = context
        self._pending_request = None
        self.controller.set_context(context)
        self.request_context.set_context(context)
        self.results.set_context(context)
        self.scenario = None
        self.options = SimulationService(context).environment_options()
        self.principal_type.blockSignals(True)
        self.compartment.blockSignals(True)
        self.principal_type.clear()
        self.compartment.clear()
        self.principal_type.addItems(list(self.options['principals']))
        self.compartment.addItems(self.options['compartment_paths'])
        self.principal_type.blockSignals(False)
        self.compartment.blockSignals(False)
        # Prefer a specific identity to a wildcard when inventory is available.
        index = self.principal_type.findText('group')
        if index >= 0:
            self.principal_type.setCurrentIndex(index)
        self._type_changed()
        self.prospects.model.replace(context.simulation.get_prospective_statements())
        self.manage.setEnabled(bool(context.policy_repo.tenancy_ocid))
        self.setCurrentIndex(0)
        self.setEnabled(True)

    def refresh_prospective(self):
        """Refresh saved what-if evidence without changing the selected environment."""
        if self.context is not None:
            records = self.context.simulation.get_prospective_statements()
            if records == self.prospects.model.records:
                return
            self.controller.set_environment(self.scenario, force=True)
            kind = self.principal_type.currentText()
            choice = self.principal.currentData()
            self.options = SimulationService(self.context).environment_options()
            self.principal_type.blockSignals(True)
            self.principal_type.clear()
            self.principal_type.addItems(list(self.options['principals']))
            self.principal_type.setCurrentText(kind)
            self.principal_type.blockSignals(False)
            self._type_changed()
            if choice:
                for index in range(self.principal.count()):
                    if self.principal.itemData(index)['principal_key'] == choice['principal_key']:
                        self.principal.setCurrentIndex(index)
                        break
            self.prospects.model.replace(self.context.simulation.get_prospective_statements())

    def _type_changed(self, *_args):
        self.principal.blockSignals(True)
        self.principal.clear()
        kind = self.principal_type.currentText()
        for choice in self.options.get('principals', {}).get(kind, []):
            self.principal.addItem(choice['label'], choice)
        self.principal.blockSignals(False)
        wildcard = kind in {'any-user', 'any-group'}
        self.principal.setEnabled(not wildcard)
        self.identity_note.setText(
            'Wildcard principal: supply resource identity conditions in Request context when applicable.'
            if wildcard
            else 'Choices combine loaded inventory and policy references. Users appear only when user inventory is loaded.'
        )
        self._update_summary()

    def _update_summary(self, *_args):
        choice = self.principal.currentData()
        path = self.compartment.currentText()
        self.scenario = None
        if not choice or not path:
            self.controller.set_environment(None)
            self.continue_button.setEnabled(False)
            self.summary.setText(
                'Select a known identity and compartment. Missing inventory may require reloading data.'
            )
            return
        self.scenario = {
            'principal_type': self.principal_type.currentText(),
            'principal': choice['principal'],
            'principal_key': choice['principal_key'],
            'compartment_path': path,
        }
        self.controller.set_environment(self.scenario)
        self.continue_button.setEnabled(self.controller.worker is None)
        self.summary.setText(
            f'Principal: {self.principal_type.currentText()} · {choice["label"]}\n'
            f'Canonical identity: {choice["principal_key"]}\nEffective compartment: {path}'
        )

    def _checked_changed(self, ids):
        self.controller.checked_ids = list(ids)
        if self.controller.ready:
            self.results.mark_stale()
            self.request_context.refresh_selection()
            self.statements.status.setText(
                f'{len(ids):,} statements included. '
                + (
                    'No statements are included; this is an explicit empty selection.'
                    if not ids
                    else 'Conditions will be supplied in Request context. No request has been evaluated.'
                )
            )

    def _invalidate_statements(self):
        self.results.mark_stale()
        self.request_context.clear_request()
        self.statements.selection.model.replace([])
        self.statements.search.clear()
        self.statements.next.setEnabled(False)
        self.statements.status.setText(
            'Environment or what-if policies changed. Return to Environment and select statements again.'
        )
        self.statements.environment.setText('No current statement selection.')
        self.preparation_status.setText('Confirm the environment, then continue to review applicable statements.')
        self.setTabEnabled(2, False)
        self.setTabEnabled(3, True)
        if self.currentIndex() > 0:
            self.setCurrentIndex(0)

    def _open_statements(self):
        self.controller.prepare()

    def _tab_changed(self, index):
        if index == 1 and not self.controller.ready:
            self.controller.prepare()

    def _prepared(self, result):
        if result is not None:
            self.statements.selection.model.replace(result['statements'])
            self.statements.selection.model.set_checked_ids(
                [str(row['internal_id']) for row in result['statements'] if row['checkable']]
            )
            self.statements.environment.setText(self.summary.text())
        self._checked_changed(self.statements.selection.model.checked_ids())
        self.statements.next.setEnabled(True)
        self.setTabEnabled(2, True)
        self.setCurrentIndex(1)
        self.preparation_status.setText('Statements prepared. Return here to change the environment.')
        if self._pending_request is not None:
            pending = self._pending_request
            self._pending_request = None
            request = pending['request']
            if request['checked_statement_ids'] is not None:
                ids = set(request['checked_statement_ids'])
                ids.update(
                    str(row['internal_id'])
                    for row in self.statements.selection.model.records
                    if row.get('is_prospective') and str(row['internal_id']) not in pending['before_prospective_ids']
                )
                self.statements.selection.model.set_checked_ids(ids)
            self.request_context.group.setCurrentIndex(0)
            self.request_context.search.clear()
            self.request_context.operation.setCurrentText(request['api_operation'])
            for name, (value, null) in self.request_context.input_widgets.items():
                if name in request['where_context']:
                    supplied = request['where_context'][name]
                    null.setChecked(supplied is None)
                    value.setText('' if supplied is None else str(supplied))
            self.setCurrentIndex(2)
            self.request_context.status.setText(
                'Follow-up prepared. Review the target compartment, included statements and condition values, then Run simulation.'
            )

    def _preparation_failed(self, message):
        self.preparation_status.setText(f'Could not prepare statements: {message}')
        self.statements.status.setText(f'Could not prepare statements: {message}')
        self.results.status.setText(f'Simulation action failed: {message}')
        self.request_context.status.setText(f'Simulation action failed: {message}')

    def _preparation_busy(self, busy):
        for index in range(self.count()):
            self.widget(index).setEnabled(not busy)
        for control in (self.principal_type, self.principal, self.compartment, self.manage, self.continue_button):
            control.setEnabled(not busy)
        if busy:
            self.preparation_status.setText('Finding applicable statements…')
            self.statements.status.setText('Finding applicable statements…')
            self.results.status.setText('Simulation work in progress…')
        else:
            self.principal.setEnabled(self.principal_type.currentText() not in {'any-user', 'any-group'})
            self.manage.setEnabled(bool(self.context and self.context.policy_repo.tenancy_ocid))
            self.continue_button.setEnabled(self.scenario is not None)

    def _executed(self, report, history):
        self.results.show_history(history)
        self.results.show_report(report)
        self.setTabEnabled(3, True)
        self.setCurrentIndex(3)

    def prepare_followup(self, request, before_prospective_ids=None):
        """Stage a related request or reviewed what-if rerun without executing it.

        Args:
            request: Original environment and request values; None checked IDs
                explicitly request fresh default inclusion at a new related scope.
            before_prospective_ids: Existing prospect IDs before reviewed additions,
                used to include new prospects while retaining intentional exclusions.
        """
        if self.controller.worker is not None or self.controller.block_reason:
            self.results.status.setText(self.controller.block_reason or 'Wait for the current simulation task.')
            return
        self._pending_request = {'request': request, 'before_prospective_ids': set(before_prospective_ids or [])}
        self.principal_type.setCurrentText(request['principal_type'])
        for index in range(self.principal.count()):
            if self.principal.itemData(index)['principal_key'] == request['principal_key']:
                self.principal.setCurrentIndex(index)
                break
        else:
            self._pending_request = None
            self.results.status.setText('The original principal is no longer available. Choose a new environment.')
            return
        for index in range(self.compartment.count()):
            if self.compartment.itemText(index).casefold() == request['compartment_path'].casefold():
                self.compartment.setCurrentIndex(index)
                break
        else:
            self._pending_request = None
            self.results.status.setText('The target compartment is not available in this snapshot.')
            return
        self.controller.set_environment(self.scenario, force=True)
        self.controller.prepare()
