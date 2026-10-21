"""Live, filterable OCI API metadata kept separately from component log text."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.api_calls import API_CALLS
from oci_policy_analysis.presentation.qt.tables import RecordModel, RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class ApiCallModel(RecordModel):
    """Sort numeric timing/status values and chronological UTC start times."""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Return scalar display data or typed sort values for completed calls."""
        if index.isValid() and role == Qt.ItemDataRole.UserRole:
            row = self.records[index.row()]
            field = self.columns[index.column()][1]
            value = row.get(field)
            return value if isinstance(value, (float, int)) else str(value or '').casefold()
        return super().data(index, role)


class ApiCallsView(QWidget):
    """Poll a bounded thread-safe journal independently of all logging levels.

    Args:
        journal: Optional isolated journal for embedded callers and tests.

    Notes:
        Default history lasts for this application process, across successful or
        failed loads. Clear forgets only API metadata. No snapshot/file is written.
        SDK pagination and retry attempts appear as separate completed calls.
    """

    def __init__(self, journal=None):
        super().__init__()
        self.journal = journal if journal is not None else API_CALLS
        self.revision = None
        self.records = []
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter calls, targets, status codes, reasons, or request IDs…')
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        self.errors_only = QCheckBox('Errors only')
        controls.addWidget(self.errors_only)
        self.show_details = QCheckBox('Show details')
        self.show_details.setToolTip(
            'Hide details to give the table more room. Drag the divider when details are shown.'
        )
        controls.addWidget(self.show_details)
        clear = QPushButton('Clear API history')
        clear.clicked.connect(self.clear_history)
        controls.addWidget(clear)
        layout.addLayout(controls)
        self.counts = label(
            'API calls are captured automatically, independent of log levels. In memory only.', 'muted', wrap=True
        )
        layout.addWidget(self.counts)
        columns = (
            ('Started (UTC)', 'started_at'),
            ('Call', 'operation'),
            ('Duration (ms)', 'duration_ms'),
            ('Result', 'outcome'),
            ('HTTP', 'http_status'),
            ('Code', 'code'),
            ('Reason', 'reason'),
        )
        self.table = RecordTable(columns, source_model=ApiCallModel(columns, None), details_title='API call details')
        self.table.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        for index, width in enumerate((200, 280, 115, 95, 75, 180)):
            self.table.setColumnWidth(index, width)
        self.table.details_requested.connect(self._show_details)
        self.table.selectionModel().selectionChanged.connect(self._selection)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.table.setMinimumHeight(100)
        self.splitter.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(60)
        self.details.setPlaceholderText('Select a call for target, endpoint, request ID, and error interpretation.')
        self.splitter.addWidget(self.details)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.details.hide()
        self.show_details.toggled.connect(self._toggle_details)
        layout.addWidget(self.splitter, 1)
        self.search.textChanged.connect(self._filter)
        self.errors_only.toggled.connect(self._filter)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        """Read completed calls on the GUI thread; retain selection while calls arrive."""
        revision, records, _dropped = self.journal.snapshot(self.revision)
        if records is None:
            return
        self.revision, self.records = revision, records
        self._filter()

    def _filter(self, *_args):
        selected = self.table.selected_records()
        sequence = selected[0]['sequence'] if selected else None
        needle = self.search.text().strip().casefold()
        records = [
            row
            for row in self.records
            if (not self.errors_only.isChecked() or row.get('outcome') == 'Error')
            and (not needle or any(needle in str(value).casefold() for value in row.values()))
        ]
        self.table.model.replace(records)
        if sequence is not None:
            for index, row in enumerate(records):
                if row['sequence'] == sequence:
                    shown = self.table.proxy.mapFromSource(self.table.model.index(index, 0))
                    self.table.selectRow(shown.row())
                    break
        _, _, dropped = self.journal.snapshot(self.revision)
        errors = sum(row.get('outcome') == 'Error' for row in self.records)
        self.counts.setText(
            f'{len(records):,} shown / {len(self.records):,} retained · {errors:,} errors · '
            f'{dropped:,} calls omitted/evicted · In memory only; errors retained ahead of successes.'
        )

    def _toggle_details(self, visible):
        self.details.setVisible(visible)
        if visible:
            self.splitter.setSizes([max(100, self.splitter.height() - 100), 100])

    def _show_details(self, row):
        if row:
            self.show_details.setChecked(True)
        self._inspect(row)

    def _selection(self, *_args):
        rows = self.table.selected_records()
        self._inspect(rows[0] if rows else None)

    def _inspect(self, row):
        if not row:
            self.details.clear()
            return
        fields = (
            ('Interpretation', 'interpretation'),
            ('Call', 'operation'),
            ('Tenancy', 'tenancy_ocid'),
            ('Target', 'target'),
            ('Started (UTC)', 'started_at'),
            ('Duration (ms)', 'duration_ms'),
            ('HTTP status', 'http_status'),
            ('Code', 'code'),
            ('Reason', 'reason'),
            ('Request ID', 'request_id'),
            ('Method', 'method'),
            ('Endpoint', 'endpoint'),
        )
        self.details.setPlainText(
            '\n'.join(f'{title}: {row[key]}' for title, key in fields if row.get(key) not in (None, ''))
        )

    def clear_history(self):
        """Clear retained diagnostic metadata while leaving log output unchanged."""
        self.journal.clear()
        self.refresh()

    def close(self):
        """Stop polling before the shell and its widgets are destroyed."""
        self.timer.stop()
        return super().close()
