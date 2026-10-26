"""Read-only tag-qualified grants and parsed predicates over the active snapshot."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.condition_tester_service import extract_condition_clause
from oci_policy_analysis.application.services.tag_based_policy_service import TagBasedPolicyService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import label

SCOPES = {
    'requestor_group_tag': 'Requestor Group',
    'requestor_compartment_tag': 'Requestor Compartment',
    'target_resource_tag': 'Target Resource',
    'target_compartment_tag': 'Target Compartment',
}


class TagConditionTable(StatementTable):
    """Retain full-condition testing alongside explicit single-predicate testing."""

    def context_menu(self, record):
        """Offer the selected atom without losing the full source qualification."""
        menu = super().context_menu(record)
        if record.get('tag_expression'):
            menu.addAction(
                'Test selected tag predicate…', lambda: self.test_condition_requested.emit(record['tag_expression'])
            )
        return menu


class TagBasedPoliciesPage(QWidget):
    """Inspect tag qualifiers without interpreting them as evaluated access.

    Attributes:
        context: Current snapshot, replaced on every load.
        details_requested: Requests original statement and predicate evidence.
        test_condition_requested: Opens the existing tester with selected text.
        focus_dynamic_group: Opens the referenced dynamic groups in their inventory.
    """

    details_requested = Signal(object, str)
    test_condition_requested = Signal(str)
    focus_dynamic_group = Signal(dict)

    def __init__(self):
        super().__init__()
        self.context = None
        self.inventory = {'statements': [], 'conditions': [], 'namespace_count': 0}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            label(
                'Tag predicates qualify a grant; they must be considered with the complete condition. '
                'This view shows snapshot evidence. The condition tester uses values you supply and does not establish OCI access.',
                'notice',
                wrap=True,
            )
        )
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search policy paths, principals, statements, or tag expressions…')
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        self.scope = QComboBox()
        self.scope.addItem('All tag scopes', '')
        for key, title in SCOPES.items():
            self.scope.addItem(title, key)
        self.scope.addItem('Unparsed references', 'Unparsed tag reference')
        controls.addWidget(self.scope)
        reset = QPushButton('Reset filters')
        reset.clicked.connect(self.reset_filters)
        controls.addWidget(reset)
        layout.addLayout(controls)
        tags = QHBoxLayout()
        self.filters = {}
        for key, title in [('tag_namespace', 'Tag namespace'), ('tag_key', 'Tag key'), ('tag_value', 'Tag value')]:
            field = QLineEdit()
            field.setPlaceholderText(title)
            field.setClearButtonEnabled(True)
            field.textChanged.connect(lambda *_: self.timer.start())
            self.filters[key] = field
            tags.addWidget(field, 1)
        layout.addLayout(tags)
        self.summary = label('Load a snapshot to inspect tag-qualified policies.', 'muted', wrap=True)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.statements = StatementTable()
        self.conditions = TagConditionTable(
            (
                ('Policy Path', 'policy_display'),
                ('Tag Applies To', 'tag_scope_display'),
                ('Namespace', 'tag_namespace'),
                ('Key', 'tag_key'),
                ('Operator', 'tag_operator'),
                ('Value / Variable', 'tag_value'),
                ('Parse Status', 'tag_parse_status'),
                ('Tag Predicate', 'tag_expression'),
            )
        )
        for index, width in enumerate((260, 155, 120, 100, 75, 150, 170, 420)):
            self.conditions.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
            self.conditions.setColumnWidth(index, width)
        self.tabs.addTab(self.statements, 'Statements')
        self.tabs.addTab(self.conditions, 'Tag Conditions')
        self.catalog = RecordTable(
            (('Namespace', 'namespace'), ('Key', 'key'), ('Allowed Values', 'values'), ('Compartment', 'path')),
            details_title='Tag catalog details',
        )
        self.tabs.addTab(self.catalog, 'Defined Tag Catalog')
        self.catalog.details_requested.connect(lambda row: self.details_requested.emit(row, 'Tag catalog details'))
        layout.addWidget(self.tabs, 1)
        actions = QHBoxLayout()
        self.test_full = QPushButton('Test full condition…')
        self.test_full.clicked.connect(lambda: self._test_selected(False))
        self.test_atom = QPushButton('Test tag predicate…')
        self.test_atom.clicked.connect(lambda: self._test_selected(True))
        actions.addWidget(self.test_full)
        actions.addWidget(self.test_atom)
        actions.addStretch()
        layout.addLayout(actions)
        self.coverage = label('', 'muted', wrap=True)
        layout.addWidget(self.coverage)
        for table in (self.statements, self.conditions):
            table.details_requested.connect(lambda row: self.details_requested.emit(row, 'Tag-based statement details'))
            table.test_condition_requested.connect(self.test_condition_requested.emit)
            table.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
            table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.tabs.currentChanged.connect(self._selection_changed)
        self.search.textChanged.connect(lambda *_: self.timer.start())
        self.scope.currentIndexChanged.connect(self.apply_filters)
        self._selection_changed()

    def set_context(self, context) -> None:
        """Rebuild detached evidence without changing source data or cache files."""
        self.timer.stop()
        self.context = context
        self.inventory = (
            TagBasedPolicyService.inventory(context.policy_repo.regular_statements)
            if context
            else {'statements': [], 'conditions': [], 'namespace_count': 0}
        )
        catalog = []
        for namespace, metadata in (
            (getattr(context.policy_repo, 'defined_tag_namespace_keys', {}) or {}) if context else {}
        ).items():
            for key, values in (metadata.get('keys') or {}).items():
                catalog.append(
                    {
                        'namespace': namespace,
                        'key': key,
                        'values': ', '.join(map(str, values)) if values else 'User supplied / no enumeration recorded',
                        'path': metadata.get('compartment_path') or '',
                    }
                )
        self.catalog.model.replace(catalog)
        self.apply_filters()

    def reset_filters(self) -> None:
        """Clear all display filters without loading or changing tenancy data."""
        self.search.clear()
        for field in self.filters.values():
            field.clear()
        self.scope.setCurrentIndex(0)
        self.apply_filters()

    def apply_filters(self, *_args) -> None:
        """Filter predicates together, then retain their complete source statements."""
        self.timer.stop()
        needle = self.search.text().strip().casefold()
        scope = self.scope.currentData()
        rows = []
        for row in self.inventory['conditions']:
            if scope and row.get('tag_scope') != scope:
                continue
            if any(
                field.text().strip().casefold() not in str(row.get(key) or '').casefold()
                for key, field in self.filters.items()
            ):
                continue
            if needle and needle not in ' '.join(str(value) for value in row.values()).casefold():
                continue
            rows.append({**row, 'tag_scope_display': SCOPES.get(row.get('tag_scope'), row.get('tag_scope'))})
        identities = {(row.get('policy_ocid'), row.get('internal_id'), row.get('statement_text')) for row in rows}
        statements = [
            row
            for row in self.inventory['statements']
            if (row.get('policy_ocid'), row.get('internal_id'), row.get('statement_text')) in identities
        ]
        self.conditions.model.replace(rows)
        self.statements.model.replace(statements)
        self.catalog.proxy.setFilterFixedString(self.search.text())
        self.summary.setText(
            f'{len(statements):,} / {len(self.inventory["statements"]):,} tag-qualified statements · {len(rows):,} tag predicates/references · {self.inventory["namespace_count"]:,} parsed namespaces. Right-click a row for details or condition testing.'
        )
        self._selection_changed()

    def _selected(self):
        table = self.tabs.currentWidget()
        rows = table.selected_records() if table in (self.statements, self.conditions) else []
        return rows[0] if rows else None

    def _selection_changed(self, *_args):
        row = self._selected()
        self.test_full.setEnabled(
            bool(row and extract_condition_clause(row.get('conditions') or '', row.get('statement_text') or ''))
        )
        self.test_atom.setEnabled(
            bool(row and self.tabs.currentWidget() is self.conditions and row.get('tag_expression'))
        )
        warnings = (row.get('tag_context_warnings') or []) if row else []
        self.coverage.setText(
            '\n'.join('• ' + str(warning) for warning in warnings)
            if warnings
            else 'Tag catalog coverage may be incomplete. Conditions containing any/all, exclusions, and non-tag predicates remain significant. Select a row to test it.'
        )

    def _test_selected(self, atom):
        row = self._selected()
        if not row:
            return
        clause = (
            row.get('tag_expression')
            if atom
            else extract_condition_clause(row.get('conditions') or '', row.get('statement_text') or '')
        )
        if clause:
            self.test_condition_requested.emit(clause)
