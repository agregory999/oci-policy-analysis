"""Read-only lazy JSON trees and structured field-change inspection."""

import json

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFontDatabase, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QHeaderView, QMenu, QTreeView

_ROOT = QModelIndex()


def json_text(value, present=True) -> str:
    """Render JSON types literally, keeping absent values distinct from null.

    Args:
        value: JSON-compatible scalar or container.
        present: False for a missing field rather than an explicit null value.

    Returns:
        str: Literal JSON or the explicit missing-value label.
    """
    return json.dumps(value, ensure_ascii=False, default=str) if present else '<missing>'


class _Node:
    def __init__(self, value, key='', parent=None, row=0):
        self.value, self.key, self.parent, self.row = value, key, parent, row
        self.keys = (
            list(value) if isinstance(value, dict) else list(range(len(value))) if isinstance(value, list) else []
        )
        self.children = {}

    def child(self, row):
        if row not in self.children:
            key = self.keys[row]
            self.children[row] = _Node(self.value[key], key, self, row)
        return self.children[row]


class JsonModel(QAbstractItemModel):
    """Expose original JSON lazily without one widget or item per source field.

    Args:
        value: JSON-compatible source value retained read-only by the owner.
        parent: Owning tree view.
        present: Whether the root item exists; False produces an empty tree.
    """

    def __init__(self, value=None, parent=None, *, present=True):
        super().__init__(parent)
        self.root = _Node({'$': value} if present else {})

    def rowCount(self, parent=_ROOT):
        """Return children for containers only; scalar leaves never expand."""
        if parent.isValid() and parent.column() != 0:
            return 0
        return len((parent.internalPointer() if parent.isValid() else self.root).keys)

    def columnCount(self, parent=_ROOT):
        """Return JSON key, value and type columns."""
        return 3

    def index(self, row, column, parent=_ROOT):
        """Materialize only the requested child of an expanded JSON container."""
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        node = parent.internalPointer() if parent.isValid() else self.root
        return self.createIndex(row, column, node.child(row))

    def parent(self, index):
        """Return the owning container index independently of the selected column."""
        if not index.isValid():
            return QModelIndex()
        parent = index.internalPointer().parent
        return QModelIndex() if parent is self.root else self.createIndex(parent.row, 0, parent)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """Provide literal JSON scalar values, container summaries and type names."""
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        node = index.internalPointer()
        value = node.value
        if index.column() == 0:
            return f'[{node.key}]' if isinstance(node.key, int) else str(node.key)
        if index.column() == 2:
            return (
                'null'
                if value is None
                else {
                    dict: 'object',
                    list: 'array',
                    str: 'string',
                    bool: 'boolean',
                    int: 'number',
                    float: 'number',
                }.get(type(value), type(value).__name__)
            )
        return (
            f'{{{len(value)} keys}}'
            if isinstance(value, dict)
            else f'[{len(value)} items]'
            if isinstance(value, list)
            else json_text(value)
        )

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        """Label the three original-JSON columns."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ('JSON key', 'Value', 'Type')[section]
        return None


class JsonTree(QTreeView):
    """Inspect original JSON with expansion and explicit copy actions."""

    def __init__(self):
        super().__init__()
        self.setObjectName('jsonTree')
        family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.setStyleSheet(f'QTreeView#jsonTree {{ font-family: "{family}"; }}')
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.set_json(None)

    def set_json(self, value, *, present=True) -> None:
        """Replace source JSON and discard every prior node and selection.

        Args:
            value: Original JSON retained read-only for the current selection.
            present: False when an entire baseline or target item is absent.
        """
        previous = self.model()
        self.setModel(JsonModel(value, self, present=present))
        if previous:
            previous.deleteLater()
        self.setColumnWidth(0, 250)
        self.setColumnWidth(1, 460)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.expandToDepth(0)

    def _menu(self, position):
        index = self.indexAt(position)
        if not index.isValid():
            return
        node = index.internalPointer()
        self.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction(
            'Copy JSON value',
            lambda: QApplication.clipboard().setText(json.dumps(node.value, indent=2, ensure_ascii=False, default=str)),
        )
        tokens = []
        current = node
        while current.parent is not self.model().root:
            tokens.append(str(current.key).replace('~', '~0').replace('/', '~1'))
            current = current.parent
        pointer = '/' + '/'.join(reversed(tokens)) if tokens else ''
        menu.addAction('Copy JSON pointer', lambda: QApplication.clipboard().setText(pointer))
        menu.exec(self.viewport().mapToGlobal(position))
        menu.deleteLater()


class FieldChanges(QTreeView):
    """Group changed fields into expandable paths with typed before/after values."""

    field_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.set_changes([])

    def set_changes(self, changes) -> None:
        """Display service-generated field deltas; path tokens retain literal keys."""
        previous = self.model()
        model = QStandardItemModel(self)
        model.setHorizontalHeaderLabels(['JSON path', 'Change', 'Baseline', 'Target'])
        nodes = {(): model.invisibleRootItem()}
        for change in changes:
            tokens = change.get('path') or [change['field']]
            prefix = ()
            for index, token in enumerate(tokens):
                parent = nodes[prefix]
                prefix = (*prefix, token)
                if prefix not in nodes:
                    key = f'[{token}]' if isinstance(token, int) else str(token)
                    cells = [QStandardItem(key), QStandardItem(), QStandardItem(), QStandardItem()]
                    for cell in cells:
                        cell.setEditable(False)
                    parent.appendRow(cells)
                    nodes[prefix] = cells[0]
                if index == len(tokens) - 1:
                    item = nodes[prefix]
                    item.setData(change, Qt.ItemDataRole.UserRole)
                    row = item.row()
                    owner = item.parent() or model.invisibleRootItem()
                    values = [
                        change.get('action', 'Modified'),
                        json_text(change.get('old'), change.get('old_present', True)),
                        json_text(change.get('new'), change.get('new_present', True)),
                    ]
                    for column, text in enumerate(values, 1):
                        owner.child(row, column).setText(text)
                        owner.child(row, column).setToolTip(text)
        self.setModel(model)
        if previous:
            previous.deleteLater()
        for column, width in enumerate((240, 100, 300, 300)):
            self.setColumnWidth(column, width)
        self.expandToDepth(1)
        self.selectionModel().currentChanged.connect(self._selected)
        self.field_selected.emit(None)
        if changes:
            first_path = tuple(changes[0].get('path') or [changes[0]['field']])
            self.setCurrentIndex(model.indexFromItem(nodes[first_path]))

    def _selected(self, index, previous):
        item = self.model().itemFromIndex(index.siblingAtColumn(0)) if index.isValid() else None
        self.field_selected.emit(item.data(Qt.ItemDataRole.UserRole) if item else None)
