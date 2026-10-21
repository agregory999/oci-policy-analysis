"""Tenancy-aware prospective CRUD and guided/ad-hoc modal statement editing."""

from copy import deepcopy
from dataclasses import asdict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.common.policy_helpers import principal_display_name
from oci_policy_analysis.application.services.prospective_builder_service import ProspectiveBuilderService
from oci_policy_analysis.application.services.prospective_workbench_service import ProspectiveWorkbenchService
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class ProspectiveEditorDialog(QDialog):
    """Edit one local draft using shared metadata, preview and validation services.

    Args:
        context: Loaded runtime supplying tenancy inventory and validation.
        record: Optional saved record to edit; left untouched until acceptance.
        parent: Owning workspace.

    Attributes:
        fields: Guided builder inputs keyed by the shared preview API.
        statement: Editable ad-hoc text passed verbatim to validation.

    Notes:
        Validation has no persistence side effects. Save returns draft fields to
        the workspace, which owns persistence and cross-page refresh.
    """

    def __init__(self, context, record=None, parent=None):
        """Build a modal editor with generated preview and an independent text draft."""
        super().__init__(parent)
        self.context = context
        self.builder = ProspectiveBuilderService(context.policy_repo, context.reference_data, context.simulation)
        self.metadata = self.builder.get_builder_metadata()
        self.setWindowTitle('Edit prospective statement' if record else 'Add prospective statement')
        available = self.screen().availableGeometry()
        minimum_width = min(1000, available.width() - 48)
        owner_width = parent.window().width() if parent else minimum_width
        self.setMinimumWidth(minimum_width)
        self.resize(
            min(max(minimum_width, round(owner_width * 0.88)), available.width() - 48),
            min(740, available.height() - 80),
        )
        layout = QVBoxLayout(self)
        layout.addWidget(
            label('What-if only · Saved locally for this tenancy; does not create an OCI policy.', 'notice', wrap=True)
        )
        common = QFormLayout()
        self.description = QLineEdit(record.description if record else '')
        common.addRow('Description', self.description)
        self.compartment = QComboBox()
        self.compartment.addItems(self.metadata['locations'])
        self.compartment.setCurrentText(record.compartment_path if record else 'ROOT')
        common.addRow('Policy compartment', self.compartment)
        layout.addLayout(common)
        self.tabs = QTabWidget()
        guided = QWidget()
        guided_layout = QVBoxLayout(guided)
        form = QFormLayout()
        self.builder_form = form
        self.fields = {}
        self.include_default = QCheckBox('Include Default identity domain')
        self.all_resources = QCheckBox('All reference resources and families')
        for key, title, choices in (
            ('action', 'Effect', 'actions'),
            ('principal_key', 'Existing principal', 'principals'),
            ('verb', 'Verb', 'verbs'),
            ('resource', 'Resource', 'resources_in_use'),
            ('effective_path', 'Effective path', 'effective_paths'),
            ('where_mode', 'Where clause', 'where_modes'),
            ('access_type', 'Tag access type', 'access_types'),
            ('operator', 'Tag operator', 'operators'),
        ):
            combo = QComboBox()
            for value in self.metadata[choices]:
                combo.addItem(principal_display_name(value) if key == 'principal_key' else value, value)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.fields[key] = combo
            if key in {'principal_key', 'resource'}:
                row = QHBoxLayout()
                row.setSpacing(12)
                row.addWidget(combo, 1)
                row.addWidget(self.include_default if key == 'principal_key' else self.all_resources)
                form.addRow(title, row)
            else:
                form.addRow(title, combo)
        for key, title in (('namespace', 'Tag namespace'), ('tag_key', 'Tag key'), ('value', 'Tag value(s)')):
            field = QLineEdit()
            self.fields[key] = field
            form.addRow(title, field)
        self.other_where = QPlainTextEdit()
        self.other_where.setPlaceholderText('Condition expression without the where keyword')
        self.other_where.setMaximumHeight(85)
        form.addRow('Custom condition', self.other_where)
        guided_layout.addLayout(form)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(90)
        guided_layout.addWidget(self.preview)
        self.warning = label('', 'muted', wrap=True)
        guided_layout.addWidget(self.warning)
        use = QPushButton('Use generated statement → Text and validation')
        use.clicked.connect(self._use_generated)
        guided_layout.addWidget(use)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(guided)
        self.tabs.addTab(scroll, 'Guided builder')
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.addWidget(
            label('Paste an ad-hoc statement or edit text copied from the builder.', 'muted', wrap=True)
        )
        self.statement = QPlainTextEdit(record.statement_text if record else '')
        self.statement.setPlaceholderText('Allow group … to read buckets in tenancy')
        text_layout.addWidget(self.statement)
        validate = QPushButton('Validate statement')
        validate.clicked.connect(self._validate)
        text_layout.addWidget(validate)
        self.validation = label('Not validated', 'muted', wrap=True)
        text_layout.addWidget(self.validation)
        self.tabs.addTab(text_page, 'Text and validation')
        layout.addWidget(self.tabs, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_draft)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for field in self.fields.values():
            if isinstance(field, QComboBox):
                field.currentTextChanged.connect(self._preview)
            else:
                field.textChanged.connect(self._preview)
        self.compartment.currentTextChanged.connect(self._preview)
        self.include_default.toggled.connect(self._preview)
        self.other_where.textChanged.connect(self._preview)
        self.all_resources.toggled.connect(self._resources_changed)
        self.statement.textChanged.connect(
            lambda: self.validation.setText('Text changed · Validate before reviewing results.')
        )
        self._preview()
        if record:
            self.tabs.setCurrentIndex(1)
            self._validate()

    def _resources_changed(self):
        combo = self.fields['resource']
        prior = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(
            self.metadata['resources_all_possible' if self.all_resources.isChecked() else 'resources_in_use']
        )
        if combo.findText(prior) >= 0:
            combo.setCurrentText(prior)
        combo.blockSignals(False)
        self._preview()

    def _preview(self):
        payload = {
            key: field.currentText() if isinstance(field, QComboBox) else field.text()
            for key, field in self.fields.items()
        }
        payload['principal_key'] = self.fields['principal_key'].currentData()
        payload.update(
            location=self.compartment.currentText(),
            include_default=self.include_default.isChecked(),
            other_where_text=self.other_where.toPlainText(),
        )
        result = self.builder.build_preview(payload)
        if result.effective_path != self.fields['effective_path'].currentText():
            self.fields['effective_path'].blockSignals(True)
            self.fields['effective_path'].setCurrentText(result.effective_path)
            self.fields['effective_path'].blockSignals(False)
        self.preview_result = result
        self.preview.setPlainText(result.statement_text)
        self.warning.setText('\n'.join(result.warnings))
        mode = self.fields['where_mode'].currentText()
        for key in ('access_type', 'operator', 'namespace', 'tag_key', 'value'):
            self.builder_form.setRowVisible(self.fields[key], mode == 'Tag-based Where Clause')
        self.builder_form.setRowVisible(self.other_where, mode == 'Other Where Clause')

    def _use_generated(self):
        self.statement.setPlainText(self.preview_result.statement_text)
        if not self.description.text().strip():
            self.description.setText(self.preview_result.description_suggestion)
        self.tabs.setCurrentIndex(1)
        self._validate()

    def _validate(self):
        result = self.context.simulation.validate_prospective_statement(self.statement.toPlainText().strip())
        valid = bool(result.get('parsed') and result.get('valid'))
        reasons = result.get('invalid_reasons') or []
        self.validation.setText(
            'Parsed and valid against the loaded reference data. Conditions and actual OCI access remain unevaluated.'
            if valid
            else 'Invalid / unresolved: ' + '; '.join(map(str, reasons))
        )

    def _accept_draft(self):
        if not self.statement.toPlainText().strip():
            self.tabs.setCurrentIndex(1)
            self.validation.setText('Enter a statement or use the generated preview first.')
            return
        self._validate()
        self.accept()


class ProspectiveStatementsPage(QWidget):
    """Manage saved prospective evidence for the active tenancy.

    Attributes:
        changed: Emitted after a successful persisted change for evidence refresh.
        table: Read-only saved records with validation and effective-path columns.

    Notes:
        Add/Edit uses a modal local draft. Invalid statements can be saved and
        inspected, while corpus admission and simulation eligibility stay in core.
    """

    changed = Signal()

    def __init__(self):
        """Create an empty workspace; bind it after a successful snapshot load."""
        super().__init__()
        self.context = None
        self.service = None
        layout = QVBoxLayout(self)
        self.tenancy = label('No tenancy loaded', 'muted', wrap=True)
        layout.addWidget(self.tenancy)
        layout.addWidget(
            label(
                'Prospective statements are local what-if evidence. They do not exist in the tenancy. Invalid drafts are retained; simulation uses eligible statements.',
                'notice',
                wrap=True,
            )
        )
        row = QHBoxLayout()
        for title, callback in (
            ('Add statement…', self._add),
            ('Edit selected…', self._edit),
            ('Delete selected', self._delete),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.table = RecordTable(
            (
                ('Description', 'description'),
                ('Compartment', 'compartment_path'),
                ('Effective path', 'effective_path'),
                ('Valid', 'valid'),
                ('Statement', 'statement_text'),
            )
        )
        self.table.doubleClicked.connect(self._edit)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(175)
        layout.addWidget(self.detail)
        self.status = label('', 'muted', wrap=True)
        layout.addWidget(self.status)

    def set_context(self, context):
        """Load the current tenancy's persisted records and reset selected evidence.

        Args:
            context: Newly loaded AppContext; no prior service is retained.
        """
        self.context = context
        if not str(context.policy_repo.tenancy_ocid or '').strip():
            self.service = None
            self.table.model.replace([])
            self.detail.clear()
            self.tenancy.setText('This snapshot has no tenancy identifier.')
            self.status.setText('Load a tenancy-scoped snapshot to manage prospective statements.')
            return
        self.service = ProspectiveWorkbenchService(context)
        self.tenancy.setText(f'Tenancy · {context.policy_repo.tenancy_ocid}')
        self.status.clear()
        self._refresh()

    def _refresh(self):
        self.table.model.replace([asdict(record) for record in self.service.records.list_all()])
        self.detail.clear()

    def _add(self):
        self._open_editor()

    def _edit(self, *_args):
        rows = self.table.selected_records()
        if rows:
            self._open_editor(self.service.records.get(rows[0]['id']))

    def review_draft(self, draft: dict) -> bool:
        """Review a generated draft in the existing editor and explicitly save it.

        Args:
            draft: Statement text, policy compartment and optional description.

        Returns:
            bool: Whether the user accepted and local persistence succeeded.
                Cancel leaves prospective state unchanged.
        """
        return self._open_editor(draft=draft)

    def _open_editor(self, record=None, draft=None):
        if not self.service:
            return False
        dialog = ProspectiveEditorDialog(self.context, record, self)
        if draft:
            dialog.compartment.setCurrentText(draft['compartment_path'])
            dialog.description.setText(draft.get('description', 'Simulation what-if'))
            dialog.statement.setPlainText(draft['statement_text'])
            dialog.tabs.setCurrentIndex(1)
            dialog._validate()
        succeeded = False
        if dialog.exec() == QDialog.DialogCode.Accepted:
            prior = deepcopy(self.service.records.list_all())
            try:
                saved = record or self.service.records.create(dialog.compartment.currentText(), '', '')
                saved.compartment_path = dialog.compartment.currentText()
                saved.description = dialog.description.text().strip()
                self.service.records.validate_and_update_text(saved.id, dialog.statement.toPlainText().strip())
                self.service.records.persist_and_push_to_engine(strict=True)
                self._refresh()
                self.status.setText('Saved for this tenancy · Browser, graph and simulation updated.')
                self.changed.emit()
                succeeded = True
            except Exception as exc:
                self._restore(prior)
                self.status.setText(f'Could not save: {exc}')
        dialog.deleteLater()
        return succeeded

    def _restore(self, records):
        for record in self.service.records.list_all():
            self.service.records.delete(record.id)
        for record in records:
            self.service.records.upsert(record)

    def _delete(self):
        rows = self.table.selected_records()
        if not rows:
            return
        prior = deepcopy(self.service.records.list_all())
        try:
            self.service.records.delete(rows[0]['id'])
            self.service.records.persist_and_push_to_engine(strict=True)
            self._refresh()
            self.status.setText('Deleted prospective statement for this tenancy.')
            self.changed.emit()
        except Exception as exc:
            self._restore(prior)
            self.status.setText(f'Could not delete: {exc}')

    def _selection_changed(self, *_args):
        rows = self.table.selected_records()
        if not rows:
            self.detail.clear()
            return
        record = self.service.records.get(rows[0]['id'])
        diagnostics = '; '.join(record.invalid_reasons) or ('Valid' if record.valid else 'Not validated')
        try:
            risk = self.service.potential_risk(record)
            text = (
                (f'Potential risk estimate: {risk["score"]}\n{risk["notes"]}\n' + '\n'.join(risk['recommendations']))
                if risk
                else 'Potential risk unavailable for invalid/unvalidated statements.'
            )
        except Exception:
            text = 'Potential risk unavailable with this snapshot.'
        self.detail.setPlainText(
            f'{diagnostics}\nEffective path: {record.effective_path or "Unresolved"}\n{text}\nHeuristic estimate; conditions and OCI access are not evaluated.'
        )
