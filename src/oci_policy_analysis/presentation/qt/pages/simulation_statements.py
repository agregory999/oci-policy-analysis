"""Guided checked-statement selection using shared source evidence tables."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from oci_policy_analysis.presentation.qt.selection_table import CheckedRecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class SimulationStatementsPage(QWidget):
    """Review candidate provenance and choose explicit statement inclusion.

    Attributes:
        selection: Native checked table; highlighting only inspects a record.
        back_requested: Navigate back without discarding current checks.
        next_requested: Continue with the complete explicit checked-ID list.
    """

    back_requested = Signal()
    next_requested = Signal()

    def __init__(self):
        """Build guidance, text filtering, evidence and scoped inclusion actions."""
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 22, 20, 18)
        layout.setSpacing(14)
        layout.addWidget(label('Choose the policy statements to test', 'eyebrow'))
        layout.addWidget(
            label(
                'Review the statements discovered for your environment. Eligible statements start checked. Uncheck a statement to model removing it; prospective rows represent local what-if policies.',
                wrap=True,
            )
        )
        self.environment = label('Confirm an environment to discover statements.', 'notice', wrap=True)
        layout.addWidget(self.environment)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter by statement, policy, source, compartment or eligibility…')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        layout.addWidget(
            label(
                'Check boxes to include statements. Clicking a row only highlights it; right-click for full details or to test its condition. Filtering keeps hidden checks.',
                'muted',
                wrap=True,
            )
        )
        self.selection = CheckedRecordTable(
            (
                ('Source', 'source_kind'),
                ('Effect', 'action'),
                ('Policy', 'policy_name'),
                ('Effective path', 'effective_path'),
                ('Eligibility / reason', 'selection_reason'),
                ('Original statement', 'statement_text'),
            ),
            key=lambda row: row.get('internal_id'),
            eligible=lambda row: row['checkable'],
        )
        for index, width in enumerate((70, 90, 55, 125, 135, 180)):
            self.selection.table.setColumnWidth(index, width)
        self.search.textChanged.connect(self.selection.table.proxy.setFilterFixedString)
        self.search.textChanged.connect(self.selection._counts)
        layout.addWidget(self.selection, 1)
        self.status = label('No statements loaded.', 'muted', wrap=True)
        layout.addWidget(self.status)
        navigation = QHBoxLayout()
        back = QPushButton('Back: Environment')
        back.clicked.connect(self.back_requested.emit)
        navigation.addWidget(back)
        navigation.addStretch()
        self.next = QPushButton('Next: Request context')
        self.next.setObjectName('primary')
        self.next.setEnabled(False)
        self.next.clicked.connect(self.next_requested.emit)
        navigation.addWidget(self.next)
        layout.addLayout(navigation)
