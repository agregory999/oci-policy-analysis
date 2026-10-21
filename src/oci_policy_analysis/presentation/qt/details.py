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

from oci_policy_analysis.presentation.qt.json_view import JsonTree
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, label

_GROUPS = [
    (
        'Basic Details',
        (
            'statement_text',
            'policy_name',
            'policy_ocid',
            'compartment_path',
            'compartment_ocid',
            'creation_time',
            'effective_path',
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
            'effective_compartment_ocid',
            'comments',
        ),
    ),
    (
        'Cross-tenancy',
        (
            'kind',
            'direction',
            'tenancy_aliases',
            'resolved_aliases',
            'aliases_resolved',
            'principal_identity',
            'external_tenancies',
            'participants',
            'association',
            'tenancy_associations',
            'reciprocal_guidance',
        ),
    ),
    (
        'Define details',
        ('defined_type', 'defined_name', 'ocid_alias', 'definition_status', 'reference_status', 'reference_count'),
    ),
    (
        'Admit details',
        (
            'admitted_principal_type',
            'admitted_principal',
            'admitted_tenancy',
            'admitted_principal_tenancy',
            'admit_action',
            'admit_resource',
            'admit_permissions_original',
            'admit_permissions',
            'admit_location_type',
            'admit_location',
            'admit_associate_resource',
            'admit_associate_tenancy',
            'admit_associate_with_resource',
            'admit_associate_with_tenancy',
            'associate_clause_raw',
        ),
    ),
    (
        'Endorse details',
        (
            'endorsed_principal_type',
            'endorsed_principal',
            'endorsed_principal_tenancy',
            'endorse_action',
            'endorse_resource',
            'endorse_permissions_original',
            'endorse_permissions',
            'endorse_tenancy',
            'endorse_location_type',
            'endorse_location',
            'endorse_associate_resource',
            'endorse_associate_tenancy',
            'endorse_associate_with_resource',
            'endorse_associate_with_tenancy',
            'associate_clause_raw',
        ),
    ),
    ('Statement comment and condition', ('comment', 'where_clause')),
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
        self.invalid_notice = QPlainTextEdit()
        self.invalid_notice.setReadOnly(True)
        self.invalid_notice.setAccessibleName('Invalid statement reason')
        self.invalid_notice.setMaximumHeight(120)
        self.invalid_notice.setMinimumHeight(80)
        self.invalid_notice.setStyleSheet('border-left: 3px solid #c3424b;')
        self.invalid_notice.hide()
        layout.addWidget(self.invalid_notice)
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
        self.invalid_notice.setVisible(valid is False)
        if valid is False:
            reasons = [record[key] for key in ('invalid_reasons', 'invalid_reason', 'parse_errors') if record.get(key)]
            if not reasons and record.get('parsing_notes'):
                reasons = [record['parsing_notes']]
            summary = (
                '\n'.join(
                    '• '
                    + (
                        json.dumps(reason, ensure_ascii=False, default=str)
                        if isinstance(reason, (list, dict, tuple))
                        else str(reason)
                    )
                    for value in reasons
                    for reason in (value if isinstance(value, (list, tuple)) else [value])
                )
                or 'No invalid reason was recorded. Review Validity and Raw record.'
            )
            self.invalid_notice.setPlainText('Invalid statement\n' + summary)
        else:
            self.invalid_notice.clear()
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
        if record.get('user_name'):
            identity_name, identity_keys = groups[0]
            identity_keys = tuple(identity_keys) + tuple(
                key for key in record if key not in {item for _, keys in groups for item in keys}
            )
            groups[0] = (identity_name, identity_keys)
        if valid is False and 'statement_text' in record:
            groups = [group for group in groups if group[0] == 'Validity'] + [
                group for group in groups if group[0] != 'Validity'
            ]
        cross_tenancy_finding = title == 'Cross-tenancy finding details'
        if cross_tenancy_finding:
            groups = [
                (
                    'Finding',
                    ('Type', 'Severity', 'Policy Name', 'Issue', 'Statement Text', 'source_ids', 'related_statements'),
                )
            ]
        consolidation_finding = 'Opportunity ID' in record and 'Evidence' in record
        if consolidation_finding:
            groups = [('Recommendation', tuple(record))]
        display_groups = list(groups)
        if not cross_tenancy_finding and not consolidation_finding:
            display_groups.append(
                (
                    'Additional Details',
                    tuple(
                        key
                        for key in record
                        if key != 'parsed_fields' and key not in {key for _, keys in groups for key in keys}
                    ),
                )
            )
        for name, keys in display_groups:
            selected = [
                key
                for key in keys
                if key in record
                and key not in seen
                and record[key] is not None
                and record[key] != ''
                and record[key] != []
                and record[key] != {}
                and record[key] != ()
            ]
            if not selected:
                continue
            group = QWidget()
            values = QVBoxLayout(group)
            for key in selected:
                seen.add(key)
                values.addWidget(label(key.replace('_', ' ').title(), 'eyebrow'))
                value = record[key]
                if consolidation_finding and key == 'Evidence':
                    text = JsonTree()
                    text.set_json(value)
                    text.expandToDepth(2)
                    text.setMinimumHeight(340)
                elif key in {'invalid_reasons', 'invalid_reason', 'parse_errors'}:
                    reasons = value if isinstance(value, (list, tuple)) else [value]
                    text = label(
                        '\n'.join(
                            '• '
                            + (
                                json.dumps(reason, ensure_ascii=False, default=str)
                                if isinstance(reason, (dict, list, tuple))
                                else str(reason)
                            )
                            for reason in reasons
                        ),
                        wrap=True,
                    )
                    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                elif isinstance(value, list | tuple):
                    text = label(
                        '\n'.join(
                            '• '
                            + (
                                json.dumps(item, ensure_ascii=False, default=str)
                                if isinstance(item, dict | list | tuple)
                                else str(item)
                            )
                            for item in value
                        )
                        or 'None recorded',
                        wrap=True,
                    )
                    text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                elif isinstance(value, dict):
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
                name
                in {
                    'Recommendation',
                    'Basic Details',
                    'Parsed statement',
                    'Cross-tenancy',
                    'Permission facts',
                    'Identity',
                    'Matching rule',
                }
                or (name == 'Validity' and valid is False)
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
