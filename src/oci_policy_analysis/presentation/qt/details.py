"""Reusable animated, read-only source-record drawer for Qt pages."""

import json

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, label

_GROUPS = [
    (
        'Source',
        (
            'statement_text',
            'policy_name',
            'policy_ocid',
            'compartment_path',
            'compartment_ocid',
            'internal_id',
            'creation_time',
            'policy_tags',
        ),
    ),
    (
        'Validity',
        (
            'valid',
            'invalid',
            'invalid_reasons',
            'invalid_reason',
            'parsed',
            'parse_errors',
            'parsing_notes',
            'confidence',
            'match_confidence',
            'match_confidence_reason',
        ),
    ),
    (
        'Parsed statement',
        (
            'action',
            'subject_type',
            'subject',
            'principals',
            'principal_keys',
            'verb',
            'resource',
            'permission',
            'location_type',
            'location',
            'effective_path',
            'effective_compartment_ocid',
            'comments',
        ),
    ),
    (
        'Permission facts',
        ('graph_selection', 'permission_facts'),
    ),
    (
        'Conditions',
        (
            'conditions',
            'conditions_where_clause',
            'conditions_parsed_structure',
            'condition_atoms',
            'where_clause',
            'where_clause_structure',
        ),
    ),
]


class DetailsDrawer(QFrame):
    """Slide a source record in from the right, keeping every supplied field.

    Attributes:
        record: Currently inspected source dictionary, or None after clear/reload.
        raw: Read-only original record serialization, including all optional fields.

    Notes:
        Never parses/reinterprets policy evidence or modifies the loaded snapshot.
        Nested values have their own scroll area; source values are plain text.
    """

    def __init__(self, parent: QWidget) -> None:
        """Install a right-edge overlay within the shell's central widget."""
        super().__init__(parent)
        self.setObjectName('detailsDrawer')
        self.record = None
        self._closing = False
        self.animation = QPropertyAnimation(self, b'pos', self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setOffset(-4, 2)
        shadow.setColor(QColor(0, 0, 0, 50))
        self.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        row = QHBoxLayout()
        self.title = label('Statement details', 'eyebrow')
        row.addWidget(self.title)
        row.addStretch()
        close = QPushButton('Close ×')
        close.clicked.connect(self.dismiss)
        row.addWidget(close)
        layout.addLayout(row)
        self.status = label('', wrap=True)
        layout.addWidget(self.status)
        tabs = QTabWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        tabs.addTab(self.scroll, 'Details')
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        tabs.addTab(self.raw, 'Raw record')
        layout.addWidget(tabs, 1)
        actions = QHBoxLayout()
        copy = QPushButton('Copy JSON')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.raw.toPlainText()))
        actions.addWidget(copy)
        self.copy_statement = QPushButton('Copy statement')
        self.copy_statement.clicked.connect(
            lambda: QApplication.clipboard().setText(str((self.record or {}).get('statement_text') or ''))
        )
        actions.addWidget(self.copy_statement)
        actions.addStretch()
        layout.addLayout(actions)
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.activated.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def show_record(self, record: dict | None, title: str = 'Statement details') -> None:
        """Render retained fields and animate the first opening of the drawer."""
        if record is None:
            self.clear()
            return
        if record is self.record and self.isVisible() and not self._closing:
            return
        opening = self.isHidden() or self._closing
        self.record = record
        self._closing = False
        self.animation.stop()
        self.title.setText(title)
        valid = record.get('valid')
        validity = 'Valid' if valid is True else 'Invalid' if valid is False else 'Validity not recorded'
        if 'statement_text' not in record:
            validity = str(record.get('dynamic_group_name') or 'Source record')
        parsed = record.get('parsed')
        parsed_status = 'Yes' if parsed is True else 'No' if parsed is False else 'Not recorded'
        self.status.setText(f'{validity} · Parsed: {parsed_status}' if 'statement_text' in record else validity)
        self.raw.setPlainText(json.dumps(record, indent=2, ensure_ascii=False, default=str))
        self.copy_statement.setVisible('statement_text' in record)
        content = QWidget()
        fields = QVBoxLayout(content)
        fields.setContentsMargins(0, 12, 8, 0)
        seen = set()
        groups = (
            _GROUPS
            if 'statement_text' in record
            else [
                (
                    'Identity',
                    (
                        'domain_name',
                        'domain_ocid',
                        'dynamic_group_name',
                        'dynamic_group_ocid',
                        'dynamic_group_id',
                        'description',
                        'in_use',
                        'creation_time',
                        'created_by_name',
                        'created_by_ocid',
                    ),
                ),
                (
                    'Matching rule',
                    (
                        'matching_rule',
                        'matching_rule_structure',
                        'matching_rule_parsed_structure',
                        'matching_rule_elements',
                    ),
                ),
            ]
        )
        for name, keys in [
            *groups,
            (
                'Additional fields',
                tuple(key for key in record if key not in {key for _, keys in groups for key in keys}),
            ),
        ]:
            selected = [key for key in keys if key in record and key not in seen]
            if not selected:
                continue
            group = QWidget()
            values = QVBoxLayout(group)
            for key in selected:
                seen.add(key)
                values.addWidget(label(key.replace('_', ' ').title(), 'eyebrow'))
                value = record[key]
                if isinstance(value, list | dict | tuple):
                    text = QPlainTextEdit()
                    text.setReadOnly(True)
                    text.setPlainText(json.dumps(value, indent=2, ensure_ascii=False, default=str))
                    text.setFixedHeight(115 if value else 55)
                else:
                    text = label(str(value) if value is not None else 'Not recorded', wrap=True)
                    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                values.addWidget(text)
            section = CollapsibleSection(name, group)
            section.button.setChecked(
                name in {'Source', 'Validity', 'Parsed statement', 'Permission facts', 'Identity', 'Matching rule'}
            )
            fields.addWidget(section)
        fields.addStretch()
        previous = self.scroll.takeWidget()
        if previous:
            previous.deleteLater()
        self.scroll.setWidget(content)
        self.scroll.verticalScrollBar().setValue(0)
        self.resize(
            min(720, max(480, int(self.parentWidget().width() * 0.54))), max(180, self.parentWidget().height() - 24)
        )
        target = self._target()
        self.move(QPoint(self.parentWidget().width(), 12) if opening else target)
        self.show()
        self.raise_()
        if opening:
            self.animation.setStartValue(self.pos())
            self.animation.setEndValue(target)
            self.animation.start()

    def dismiss(self) -> None:
        """Slide out; keep the source selection available for reopening by click."""
        if self.isHidden():
            return
        self._closing = True
        self.animation.stop()
        self.animation.setStartValue(self.pos())
        self.animation.setEndValue(QPoint(self.parentWidget().width(), 12))
        self.animation.start()

    def clear(self) -> None:
        """Immediately discard old snapshot evidence on reload, reset, or navigation."""
        self.animation.stop()
        self.record = None
        self._closing = False
        self.raw.clear()
        self.hide()

    def _target(self) -> QPoint:
        return QPoint(max(0, self.parentWidget().width() - self.width() - 12), 12)

    def _animation_finished(self) -> None:
        if self._closing:
            self.hide()
            self._closing = False

    def eventFilter(self, watched, event) -> bool:
        """Anchor to the shell's right edge after a resize, including dock changes."""
        if event.type() == QEvent.Type.Resize and self.isVisible():
            if self._closing:
                self.clear()
                return False
            self.animation.stop()
            self.resize(self.width(), max(180, self.parentWidget().height() - 24))
            self.move(self._target())
        return super().eventFilter(watched, event)
