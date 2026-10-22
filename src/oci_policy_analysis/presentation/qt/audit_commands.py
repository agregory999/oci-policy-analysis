"""Native, editable OCI Audit command helper for historical evidence."""

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from oci_policy_analysis.application.services.audit_command_service import AuditCommandService
from oci_policy_analysis.presentation.qt.widgets import label


class AuditCommandsDialog(QDialog):
    """Generate commands for manual use, without querying Audit or changing OCI.

    Args:
        change: Original historical change evidence.
        metadata: Metadata from the compared snapshots, not the active context.
        parent: Owning historical page.
    """

    def __init__(self, change, metadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Find OCI Audit Records')
        self.resize(1000, 690)
        layout = QVBoxLayout(self)
        layout.addWidget(label(AuditCommandService.NOTE, 'notice', wrap=True))
        form = QFormLayout()
        defaults = AuditCommandService.defaults(change, metadata)
        self.fields = {}
        for key, title in [
            ('compartment_id', 'Compartment OCID'),
            ('resource_id', 'Resource OCID (optional)'),
            ('start_time', 'Start (inclusive, UTC/offset)'),
            ('end_time', 'End (exclusive, UTC/offset)'),
            ('region', 'Region (blank uses CLI configuration)'),
            ('profile', 'Profile (blank uses CLI configuration)'),
        ]:
            field = QLineEdit(defaults[key])
            form.addRow(title, field)
            self.fields[key] = field
        self.shell = QComboBox()
        self.shell.addItem('POSIX shell', 'posix')
        self.shell.addItem('PowerShell', 'powershell')
        form.addRow('Command shell', self.shell)
        self.fetch_all = QCheckBox('Fetch every page (--all; may be slow)')
        form.addRow('Result pages', self.fetch_all)
        layout.addLayout(form)
        self.status = label(
            'Generate contiguous windows of at most 14 days. Times expand to minute boundaries.', 'muted', wrap=True
        )
        layout.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        buttons = QHBoxLayout()
        generate = QPushButton('Generate commands')
        generate.clicked.connect(self.generate)
        self.copy = QPushButton('Copy commands')
        self.copy.clicked.connect(lambda: QApplication.clipboard().setText(self.output.toPlainText()))
        self.copy.setEnabled(False)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        for button in (generate, self.copy, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        for field in self.fields.values():
            field.textChanged.connect(self._invalidate)
        self.shell.currentIndexChanged.connect(self._invalidate)
        self.fetch_all.toggled.connect(self._invalidate)

    def _invalidate(self, *_):
        self.output.clear()
        self.copy.setEnabled(False)

    def generate(self):
        """Render validated commands only after the operator requests them."""
        try:
            result = AuditCommandService.generate(
                {
                    **{key: field.text() for key, field in self.fields.items()},
                    'shell': self.shell.currentData(),
                    'fetch_all': self.fetch_all.isChecked(),
                }
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            self._invalidate()
            return
        self.output.setPlainText('\n\n'.join(result['commands']))
        self.copy.setEnabled(True)
        paging = 'All result pages; may be slow.' if result['fetch_all'] else 'First page per window.'
        self.status.setText(
            f'{len(result["commands"])} commands · {paging} · Start inclusive, end exclusive · No OCI calls performed.'
        )
