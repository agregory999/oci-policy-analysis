"""Native checked-row inclusion shared by downstream analysis workflows."""

from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from oci_policy_analysis.presentation.qt.tables import RecordModel, RecordTable
from oci_policy_analysis.presentation.qt.widgets import label

_ROOT = QModelIndex()


class CheckableRecordModel(RecordModel):
    """Keep process inclusion separate from row highlighting and source records.

    Args:
        columns: Display labels and dictionary field names; Include is prepended.
        key: Adapter-supplied stable, unique ID, e.g. internal_id or plan-step ID.
        eligible: Adapter-supplied checkability rule; no domain rule is inferred.

    Attributes:
        checked_changed: Complete checked-ID list, emitted after each change.

    Notes:
        Source records are never modified. Missing IDs are uncheckable; duplicate
        IDs reject replacement before changing the model. Replacement clears
        inclusion unless preserve_checks is explicitly requested for the same
        snapshot/workflow. Proxy filtering does not replace the source model.
    """

    checked_changed = Signal(object)

    def __init__(self, columns: tuple, *, key: Callable[[dict], str], eligible: Callable[[dict], bool]) -> None:
        super().__init__((('Include', '_include'), *columns), None)
        self.key = key
        self.eligible = eligible
        self._ids = []
        self._eligible = set()
        self._checked = set()

    def replace(self, records: list[dict], *, preserve_checks: bool = False) -> None:
        """Publish new records atomically; preserve checks only on explicit request."""
        ids = [str(self.key(record) or '') for record in records]
        duplicates = [key for key, count in Counter(ids).items() if key and count > 1]
        if duplicates:
            raise ValueError('Checked rows require unique stable IDs')
        eligible = {key for key, record in zip(ids, records, strict=True) if key and self.eligible(record)}
        checked = self._checked & eligible if preserve_checks else set()
        self.beginResetModel()
        self.records = records
        self._ids, self._eligible, self._checked = ids, eligible, checked
        self.endResetModel()
        self.checked_changed.emit(self.checked_ids())

    def flags(self, index: QModelIndex):
        """Expose Qt's native checkbox interaction only for eligible source rows."""
        flags = super().flags(index)
        if index.isValid() and index.column() == 0 and self._ids[index.row()] in self._eligible:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Provide standard check-state roles, leaving display evidence unchanged."""
        if index.isValid() and index.column() == 0:
            key = self._ids[index.row()]
            if role == Qt.ItemDataRole.CheckStateRole and key in self._eligible:
                return Qt.CheckState.Checked if key in self._checked else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.ToolTipRole:
                return (
                    'Include in the next operation'
                    if key in self._eligible
                    else str(
                        self.records[index.row()].get('selection_reason')
                        or 'This row is not eligible for selection or has no stable ID.'
                    )
                )
            return None
        return super().data(index, role)

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Toggle one native checkbox without resetting the table or its sorting."""
        if not index.isValid() or index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        key = self._ids[index.row()]
        if key not in self._eligible or value not in (Qt.CheckState.Checked, Qt.CheckState.Unchecked, 0, 2):
            return False
        checked = value in (Qt.CheckState.Checked, 2)
        if (key in self._checked) != checked:
            if checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            self.checked_changed.emit(self.checked_ids())
        return True

    def checked_ids(self) -> list[str]:
        """Return included IDs in source order, including filtered-out rows."""
        return [key for key in self._ids if key in self._checked]

    def checked_records(self) -> list[dict]:
        """Return included source records without adding presentation state."""
        return [row for key, row in zip(self._ids, self.records, strict=True) if key in self._checked]

    def set_checked_ids(self, ids) -> None:
        """Apply explicit inclusion, ignoring unknown and ineligible IDs."""
        checked = set(ids) & self._eligible
        if checked == self._checked:
            return
        self._checked = checked
        if self.records:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.records) - 1, 0), [Qt.ItemDataRole.CheckStateRole]
            )
        self.checked_changed.emit(self.checked_ids())


class CheckedRecordTable(QWidget):
    """Compose a native record table with explicitly scoped inclusion actions.

    Args:
        columns: Display labels and source dictionary field names.
        key: Stable ID extractor for the downstream service's row type.
        eligible: Eligibility predicate; defaults to the row's checkable field.

    Attributes:
        table: Shared sortable/filterable RecordTable with explicit detail menu.
        model: Inclusion model; emits complete checked IDs independent of filters.
        checked_changed: Complete checked-ID list, suitable for workflow state.
        details_requested: Original source row for the shared detail drawer.
    """

    checked_changed = Signal(object)
    details_requested = Signal(object)

    def __init__(
        self, columns: tuple, *, key: Callable[[dict], str], eligible: Callable[[dict], bool] | None = None
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.model = CheckableRecordModel(
            columns, key=key, eligible=eligible or (lambda row: row.get('checkable', True))
        )
        self.table = RecordTable((), source_model=self.model)
        self.table.setColumnWidth(0, 70)
        self.table.details_requested.connect(self.details_requested.emit)
        layout.addWidget(self.table, 1)
        self.actions = QHBoxLayout()
        for title, callback in [
            ('Check visible', lambda: self._visible(True)),
            ('Clear visible', lambda: self._visible(False)),
            ('Clear all checks', lambda: self.model.set_checked_ids([])),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            self.actions.addWidget(button)
        layout.addLayout(self.actions)
        self.counts = label('0 rows · 0 checked', 'muted', wrap=True)
        layout.addWidget(self.counts)
        self.model.checked_changed.connect(self.checked_changed.emit)
        self.model.checked_changed.connect(self._counts)
        self.table.proxy.rowsInserted.connect(self._counts)
        self.table.proxy.rowsRemoved.connect(self._counts)
        self.table.proxy.modelReset.connect(self._counts)
        self.table.proxy.layoutChanged.connect(self._counts)

    def _visible_ids(self) -> set[str]:
        return {
            str(self.model.key(self.table.record_at(self.table.proxy.index(row, 0))) or '')
            for row in range(self.table.proxy.rowCount())
        }

    def _visible(self, checked: bool) -> None:
        ids = set(self.model.checked_ids())
        self.model.set_checked_ids(ids | self._visible_ids() if checked else ids - self._visible_ids())

    def _counts(self, *_args) -> None:
        checked = set(self.model.checked_ids())
        self.counts.setText(
            f'{self.table.proxy.rowCount():,} / {self.model.rowCount():,} rows shown · {len(checked):,} checked · {len(checked - self._visible_ids()):,} checked outside filter'
        )

    def add_checked_action(self, title: str, callback: Callable[[list[str]], None]) -> QPushButton:
        """Add an explicit operation receiving the current IDs only when clicked."""
        button = QPushButton(title)
        button.setEnabled(bool(self.model.checked_ids()))
        self.checked_changed.connect(lambda ids: button.setEnabled(bool(ids)))
        button.clicked.connect(lambda: callback(self.model.checked_ids()))
        self.actions.addWidget(button)
        return button
