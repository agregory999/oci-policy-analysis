"""Manual policy-limit entry with tenancy-specific Console and CLI guidance."""

import shlex

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService
from oci_policy_analysis.presentation.qt.widgets import label


class PolicyLimitsDialog(QDialog):
    """Collect verified limits for an offline snapshot without contacting OCI.

    Args:
        context: Current snapshot; its named cache is updated on explicit Apply.
        parent: Owning Qt page. Cancel never changes limits or files.
    """

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle('Enter tenancy policy limits')
        self.setModal(True)
        self.resize(820, 600)
        layout = QVBoxLayout(self)
        repo = context.policy_repo
        layout.addWidget(
            label(f'Tenancy: {getattr(repo, "tenancy_name", None) or repo.tenancy_ocid or "Not recorded"}', 'eyebrow')
        )
        layout.addWidget(
            label(
                'This snapshot was not live loaded. Enter the actual values for its tenancy if you know them; no default is assumed. '
                + (
                    'Values will be saved with the active cache.'
                    if getattr(repo, 'current_cache_name', '')
                    else 'Values apply to this session. The source file and global settings will not be changed.'
                ),
                'notice',
                wrap=True,
            )
        )
        form = QFormLayout()
        limits = getattr(repo, 'tenancy_policy_limits', {}) or {}
        self.policy_limit = QLineEdit(str(limits.get('policies_count') or ''))
        self.chain_limit = QLineEdit(str(limits.get('policy_statements_per_compartment_chain_count') or ''))
        form.addRow('Policies per tenancy', self.policy_limit)
        form.addRow('Statements per compartment hierarchy', self.chain_limit)
        layout.addLayout(form)
        layout.addWidget(label('Find the values in OCI', 'eyebrow'))
        layout.addWidget(
            label(
                'Console: Open Limits, Quotas and Usage, select the tenancy and Identity service, '
                'then locate policies-count and policy-statements-per-compartment-chain-count. '
                'Use that tenancy’s actual values rather than a published default.',
                wrap=True,
            )
        )
        layout.addWidget(
            label(
                'CLI: Run these commands using credentials and a region for the source tenancy. '
                'Replace TENANCY_OCID if the snapshot does not record it. Read the value field in each response.',
                wrap=True,
            )
        )
        tenancy_id = str(repo.tenancy_ocid or '')
        tenancy = shlex.quote(tenancy_id if tenancy_id.startswith('ocid1.tenancy.') else 'TENANCY_OCID')
        self.commands = QPlainTextEdit()
        self.commands.setReadOnly(True)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.commands.setFont(fixed_font)
        self.commands.setStyleSheet(f'QPlainTextEdit {{ font-family: "{fixed_font.family()}"; }}')
        self.commands.setPlainText(
            '\n\n'.join(
                f'oci limits value list --compartment-id {tenancy} --service-name identity --name {name} --all'
                for name in ('policies-count', 'policy-statements-per-compartment-chain-count')
            )
        )
        layout.addWidget(self.commands, 1)
        copy = QPushButton('Copy CLI commands')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.commands.toPlainText()))
        layout.addWidget(copy)
        documentation = label(
            '<a href="https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm">OCI service limits</a> · '
            '<a href="https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/limits/value/list.html">CLI reference</a>',
            wrap=True,
        )
        documentation.setTextFormat(Qt.TextFormat.RichText)
        documentation.setOpenExternalLinks(True)
        layout.addWidget(documentation)
        self.error = label('', 'notice', wrap=True)
        self.error.hide()
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.ensurePolished()
        if self.fontMetrics().height() > 20:
            self.resize(1060, 850)

    def _apply(self):
        try:
            PolicyLimitsService(self.context).apply_manual(self.policy_limit.text(), self.chain_limit.text())
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.accept()
