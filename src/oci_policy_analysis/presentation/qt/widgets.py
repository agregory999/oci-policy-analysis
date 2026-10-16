"""Shared visual primitives and theme for the Qt exploration."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

STYLE = """
QWidget { font-family: 'Avenir Next', 'Segoe UI', sans-serif; font-size: 13px; color: #243d39; }
QMainWindow, QStackedWidget { background: #f5f6f2; }
QWidget#settingsContent { background: #f5f6f2; }
QFrame#sidebar { background: #163e38; }
QFrame#sidebar QLabel { color: #c3d8d1; }
QLabel#brand { color: white; font-size: 23px; font-weight: 600; }
QListWidget#navigation { background: transparent; color: #d5e3de; border: none; outline: none; }
QListWidget#navigation::item { padding: 14px 16px; margin: 3px 0; border-radius: 6px; }
QListWidget#navigation::item:disabled { color: #85958c; background: transparent; }
QListWidget#navigation::item:selected:enabled { background: #2b554d; color: white; }
QLabel#title { font-size: 29px; font-weight: 600; }
QLabel#eyebrow { color: #53726a; font-size: 11px; font-weight: 600; }
QLabel#muted { color: #62766f; }
QLabel#notice { background: #eeeade; color: #63583b; padding: 12px; border-radius: 6px; }
QFrame#card { background: white; border: 1px solid #dde4dd; border-radius: 8px; }
QLabel#metric { font-size: 33px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #c9d4cd; border-radius: 5px; padding: 9px 14px; }
QPushButton:hover { background: #e9efea; }
QPushButton#primary { background: #1e6554; color: white; border-color: #1e6554; }
QPushButton#primary:hover { background: #287962; }
QPushButton:disabled { color: #85958c; background: #e9ede8; }
QComboBox, QLineEdit, QSpinBox { background: white; border: 1px solid #c9d4cd; border-radius: 4px; padding: 8px; }
QTableView, QPlainTextEdit { background: white; border: 1px solid #dde4dd; border-radius: 5px; selection-background-color: #d9eae0; selection-color: #163e38; }
QHeaderView::section { background: #edf1eb; padding: 10px; border: none; border-bottom: 1px solid #dde4dd; font-weight: 600; }
QProgressBar { border: none; background: #dfe8df; max-height: 3px; }
QProgressBar::chunk { background: #1e6554; }
QStatusBar { background: #eaf0e8; }
"""


def label(text: str, name: str = '', *, wrap: bool = False) -> QLabel:
    """Create a plain-text label, including for untrusted snapshot fields.

    Args:
        text: Literal label text, never interpreted as HTML.
        name: Optional theme object name.
        wrap: Whether to wrap long text within the available width.

    Returns:
        QLabel: Styled text widget with no parent until placed in a layout.
    """
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class CollapsibleSection(QWidget):
    """A reusable settings header whose content starts collapsed.

    Attributes:
        button: Checkable section header.
        content: Settings widget controlled by the header.
    """

    def __init__(self, title: str, content: QWidget) -> None:
        """Wrap a settings widget without changing its state or triggering work."""
        super().__init__()
        self.content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QToolButton()
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.setObjectName('sectionHeader')
        layout.addWidget(self.button)
        layout.addWidget(content)
        content.hide()
        self.button.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        self.button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class SegmentedControl(QWidget):
    """Exclusive, keyboard-accessible buttons for a small set of filter states."""

    currentIndexChanged = Signal(int)

    def __init__(self, titles: list[str]) -> None:
        """Create one checkable button per labeled state, selecting the first."""
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = []
        for index, title in enumerate(titles):
            button = QToolButton()
            button.setText(title)
            button.setObjectName('segment')
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.setAccessibleName(title)
            self.group.addButton(button, index)
            self.buttons.append(button)
            layout.addWidget(button)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.currentIndexChanged.emit)

    def currentIndex(self) -> int:
        """Return the checked state index."""
        return self.group.checkedId()

    def setCurrentIndex(self, index: int) -> None:
        """Select a state and emit only when its value changes."""
        if self.currentIndex() != index:
            self.buttons[index].setChecked(True)
            self.currentIndexChanged.emit(index)


class MultiSelectFilter(QToolButton):
    """Accessible checkbox menu for a union of inventory-derived filter values.

    Attributes:
        changed: Emitted after the checked values change; none means all values.
        checks: Checkbox widgets keyed by the retained source values.
    """

    changed = Signal()

    def __init__(self, title: str) -> None:
        """Create an empty filter whose unchecked state includes all values."""
        super().__init__()
        self.title = title
        self.setObjectName('multiSelectFilter')
        self.checks = {}
        self.menu = QMenu(self)
        self.setMenu(self.menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setAccessibleName(title)
        self._update_text()

    def set_values(self, values: list[str]) -> None:
        """Replace available source values while preserving surviving checks.

        Args:
            values: Available values from the current loaded snapshot.
        """
        selected = set(self.selected_values())
        self.menu.clear()
        self.checks = {}
        self.menu.addAction('All subject types', self.clear)
        self.menu.addSeparator()
        for value in sorted(set(values), key=str.casefold):
            check = QCheckBox(value)
            check.setContentsMargins(12, 6, 12, 6)
            check.setChecked(value in selected)
            action = QWidgetAction(self.menu)
            action.setDefaultWidget(check)
            self.menu.addAction(action)
            self.checks[value] = check
            check.toggled.connect(self._changed)
        self._update_text()

    def selected_values(self) -> list[str]:
        """Return the selected source values; an empty list means no restriction."""
        return [value for value, check in self.checks.items() if check.isChecked()]

    def clear(self) -> None:
        """Clear checked values and emit one filter change."""
        for check in self.checks.values():
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self._changed()

    def _changed(self, *_args) -> None:
        self._update_text()
        self.changed.emit()

    def _update_text(self) -> None:
        values = self.selected_values()
        self.setText(f'{self.title}: {len(values)} selected' if values else f'{self.title}: All')
        self.setToolTip(', '.join(values) if values else 'Select several values; none selected includes all.')
