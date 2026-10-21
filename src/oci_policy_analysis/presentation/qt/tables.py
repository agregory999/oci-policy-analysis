"""Reusable source-record tables and statement context actions."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QItemSelectionModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QMenu, QTableView, QWidget

from oci_policy_analysis.application.services.condition_tester_service import extract_condition_clause
from oci_policy_analysis.presentation import format_compartment_policy_name

_ROOT_INDEX = QModelIndex()


class RecordModel(QAbstractTableModel):
    """Expose original statement evidence without creating one widget per cell."""

    headers = ()

    def __init__(self, columns: tuple, parent: QWidget | None) -> None:
        """Retain column labels and field names without copying source records."""
        super().__init__(parent)
        self.columns = columns
        self.headers = tuple(column[0] for column in columns)
        self.records: list[dict] = []

    def rowCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:
        """Return the number of source statements at the root."""
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:
        """Return the fixed policy evidence column count."""
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return display/tooltip values without interpreting authorization."""
        if index.isValid() and role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            record = self.records[index.row()]
            value = record.get(self.columns[index.column()][1])
            if isinstance(value, bool):
                return 'Yes' if value else 'No'
            return str(value) if value is not None else ''
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        """Return horizontal column labels."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def replace(self, records: list[dict]) -> None:
        """Replace evidence after the owning context has finished loading."""
        self.beginResetModel()
        self.records = records
        self.endResetModel()


class BrowserStatementModel(RecordModel):
    """Format browser policy paths and mark explicitly invalid source evidence.

    Args:
        columns: Display headings and source-field names.
        parent: Owning table, which supplies the current theme and font.

    Notes:
        Formatting and styles never modify the original statement dictionary.
        Unknown validity retains normal styling. Red plus italics distinguishes
        invalid statements in both themes and without relying only on color.
    """

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Return combined policy labels or invalid-state roles for browser cells."""
        if not index.isValid():
            return None
        record = self.records[index.row()]
        invalid = record.get('valid') is False
        if role == Qt.ItemDataRole.FontRole and invalid:
            font = QFont(self.parent().font())
            font.setItalic(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole and invalid:
            dark = self.parent().palette().color(QPalette.ColorRole.Base).lightness() < 128
            return QColor('#ff9a9a' if dark else '#a12632')
        if self.columns[index.column()][1] == 'policy_display' and role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            value = format_compartment_policy_name(record.get('compartment_path'), record.get('policy_name'))
        else:
            value = super().data(index, role)
        if invalid and role == Qt.ItemDataRole.ToolTipRole:
            return f'Invalid statement. Right-click for details.\n{value or ""}'
        return value


STATEMENT_COLUMNS = (
    ('Policy Path', 'policy_display'),
    ('Effective path', 'effective_path'),
    ('Original statement', 'statement_text'),
)


class RecordTable(QTableView):
    """Sort source records without losing the identity behind a selected row.

    Attributes:
        details_requested: Explicit inspection request, or None when the source model resets.
        model: Source model, independent from table sort/filter order.
        proxy: Case-insensitive display filter over all columns.
    """

    details_requested = Signal(object)
    test_condition_requested = Signal(str)

    def __init__(
        self,
        columns: tuple,
        *,
        multi_select: bool = False,
        details_title: str = 'Record details',
        source_model: RecordModel | None = None,
    ) -> None:
        """Build a read-only table; Ctrl/Cmd-click extends multi-selection."""
        super().__init__()
        self.model = source_model if source_model is not None else RecordModel(columns, self)
        self.model.setParent(self)
        columns = self.model.columns
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setModel(self.proxy)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multi_select
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(42)
        self.horizontalHeader().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
        for index in range(len(columns) - 1):
            self.setColumnWidth(index, 150)
        self.details_title = details_title
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.model.modelAboutToBeReset.connect(lambda: self.details_requested.emit(None))

    def context_menu(self, record: dict) -> QMenu:
        """Offer explicit inspection without opening a drawer on ordinary selection."""
        menu = QMenu(self)
        menu.addAction(self.details_title, lambda: self.details_requested.emit(record))
        self._add_condition_action(menu, record)
        return menu

    def _add_condition_action(self, menu, record):
        clause = extract_condition_clause(
            record.get('conditions') or record.get('condition_clause') or record.get('matching_rule') or '',
            record.get('statement_text') or '',
        )
        if clause:
            menu.addAction('Test condition…', lambda: self.test_condition_requested.emit(clause))

    def _show_context_menu(self, position) -> None:
        index = self.indexAt(position)
        record = self.record_at(index)
        if record is None:
            return
        if self.selectionModel().isSelected(index):
            self.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.setCurrentIndex(index)
        menu = self.context_menu(record)
        menu.exec(self.viewport().mapToGlobal(position))
        menu.deleteLater()

    def record_at(self, index: QModelIndex) -> dict | None:
        """Return the source dictionary for an index in the displayed sort order."""
        if not index.isValid():
            return None
        source = self.proxy.mapToSource(index)
        return self.model.records[source.row()]

    def selected_records(self) -> list[dict]:
        """Return only explicitly selected rows, preserving full source evidence."""
        return [self.record_at(index) for index in self.selectionModel().selectedRows()]


class StatementTable(RecordTable):
    """Shared statement table with details, copy, and dynamic-group focus actions."""

    focus_dynamic_group = Signal(dict)

    def __init__(self, columns: tuple = STATEMENT_COLUMNS, *, source_model: RecordModel | None = None) -> None:
        """Expose context actions on rows while retaining the original statement text."""
        super().__init__(columns, source_model=source_model or BrowserStatementModel(columns, None))
        if columns == STATEMENT_COLUMNS:
            self.setColumnWidth(0, 260)
            self.setColumnWidth(1, 220)

    def context_menu(self, record: dict) -> QMenu:
        """Build actions for one source record; identity resolution belongs to its page."""
        menu = QMenu(self)
        menu.addAction('Statement details', lambda: self.details_requested.emit(record))
        if str(record.get('subject_type') or '').casefold() in {'dynamic-group', 'dynamic-group-id'}:
            menu.addAction('Focus on Dynamic Group', lambda: self.focus_dynamic_group.emit(record))
        menu.addSeparator()
        menu.addAction(
            'Copy statement', lambda: QApplication.clipboard().setText(str(record.get('statement_text') or ''))
        )
        self._add_condition_action(menu, record)
        return menu
