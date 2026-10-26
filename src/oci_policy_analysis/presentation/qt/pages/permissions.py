"""Interactive permission contributions over the shared snapshot report."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.permissions_report_service import PermissionsReportService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import label


class PermissionsAnalysisPage(QWidget):
    """Explore allow/deny contributions, original grants and corpus exclusions.

    Attributes:
        details_requested: Open the shared evidence inspector.
        test_condition_requested: Populate the existing condition tester.
        analysis_requested: Ask the shell for explicit Full intelligence enrichment.
    """

    details_requested = Signal(object, str)
    test_condition_requested = Signal(str)
    analysis_requested = Signal()

    def __init__(self):
        super().__init__()
        self.context = None
        self.service = None
        self.selection = None
        self.payload = {}
        self.block_reason = ''
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(
            label(
                'Permission contributions from the loaded snapshot. Conditions, deny statements, inheritance and exclusions remain relevant; this is not an OCI authorization decision.',
                'notice',
                wrap=True,
            )
        )
        controls = QHBoxLayout()
        self.principal = QLineEdit()
        self.principal.setPlaceholderText('Principal key search (all terms)')
        self.path = QLineEdit()
        self.path.setPlaceholderText('Effective path (all terms)')
        self.kind = QComboBox()
        self.kind.addItem('All principal types', '')
        for widget in (self.principal, self.path, self.kind):
            controls.addWidget(widget)
        layout.addLayout(controls)
        options = QGridLayout()
        self.inherited = QCheckBox('Include inherited grants')
        self.prospective = QCheckBox('Include prospective statements')
        self.analysis_button = QPushButton('Run Full intelligence')
        self.analysis_button.clicked.connect(self.analysis_requested.emit)
        self.export_button = QPushButton('Export JSON…')
        self.export_button.clicked.connect(self.export_json)
        self.inherited.setToolTip('Include principals and permissions inherited from ancestor grant paths.')
        for index, widget in enumerate((self.inherited, self.prospective, self.analysis_button, self.export_button)):
            options.addWidget(widget, index // 2, index % 2)
        layout.addLayout(options)
        self.status = label('Load data to inspect permission contributions.', 'muted', wrap=True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        explorer = QWidget()
        explorer_layout = QVBoxLayout(explorer)
        explorer_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Effective Path / Principal', 'Type'])
        self.tree.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnHidden(1, True)
        splitter.addWidget(self.tree)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        self.permission_search = QLineEdit()
        self.permission_search.setPlaceholderText('Permission search (all terms)')
        panel_layout.addWidget(self.permission_search)
        self.permission_tabs = QTabWidget()
        self.tables = {}
        for effect, title in [('allow', 'Allow contributions'), ('deny', 'Deny contributions')]:
            table = RecordTable(
                (
                    ('Permission', 'permission'),
                    ('Conditional', 'conditional'),
                    ('Inherited From', 'inherited_from'),
                    ('Prospective', 'prospective'),
                    ('Original Statements', 'statement_text'),
                )
            )
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.details_requested.connect(
                lambda row: self.details_requested.emit(row, 'Permission contribution details')
            )
            table.selectionModel().selectionChanged.connect(lambda *_, effect=effect: self._permission_selected(effect))
            self.permission_tabs.addTab(table, title)
            self.tables[effect] = table
        panel_layout.addWidget(self.permission_tabs, 1)
        panel_layout.addWidget(label('Source Grants · Right-click for details or condition testing', 'muted'))
        self.sources = StatementTable()
        self.sources.details_requested.connect(
            lambda row: self.details_requested.emit(row, 'Permission source statement')
        )
        self.sources.test_condition_requested.connect(self.test_condition_requested.emit)
        panel_layout.addWidget(self.sources, 1)
        splitter.addWidget(panel)
        splitter.setSizes([400, 800])
        explorer_layout.addWidget(splitter, 1)
        self.tabs.addTab(explorer, 'Permissions')
        self.exclusions = StatementTable(
            (
                ('Policy Path', 'policy_display'),
                ('Category', 'category'),
                ('Reason', 'reason'),
                ('Original Statement', 'statement_text'),
            )
        )
        self.exclusions.details_requested.connect(
            lambda row: self.details_requested.emit(row, 'Excluded source evidence')
        )
        self.exclusions.test_condition_requested.connect(self.test_condition_requested.emit)
        self.tabs.addTab(self.exclusions, 'Exclusions')
        layout.addWidget(self.tabs, 1)
        for field in (self.principal, self.path):
            field.textChanged.connect(lambda *_: self.timer.start())
        for signal in (self.kind.currentIndexChanged, self.inherited.toggled, self.prospective.toggled):
            signal.connect(self.refresh)
        self.tree.itemSelectionChanged.connect(self._scope_selected)
        self.permission_search.textChanged.connect(self._details)
        self.permission_tabs.currentChanged.connect(self._details)

    def set_context(self, context):
        """Discard old evidence and bind services to the replacement snapshot."""
        self.timer.stop()
        self.context = context
        self.service = PermissionsReportService(context) if context else None
        self.selection = None
        self.refresh()

    def set_block_reason(self, reason):
        """Prevent query/export work while the shell owns a snapshot mutation."""
        previous = self.block_reason
        self.block_reason = reason
        for widget in (
            self.tabs,
            self.principal,
            self.path,
            self.kind,
            self.inherited,
            self.prospective,
            self.export_button,
            self.analysis_button,
        ):
            widget.setEnabled(not reason)
        self.analysis_button.setEnabled(bool(self.context and not reason))
        if previous and not reason:
            self.refresh()

    def refresh(self, *_args):
        """Project the shared report tree; never run enrichment implicitly."""
        self.timer.stop()
        if self.block_reason:
            return
        prior = self.selection
        self.selection = None
        self.tree.clear()
        for table in (*self.tables.values(), self.sources, self.exclusions):
            table.model.replace([])
        ready = bool(self.context and getattr(self.context.intelligence, 'permissions_report', {}))
        self.analysis_button.setEnabled(bool(self.context))
        self.export_button.setEnabled(ready)
        if not ready:
            self.payload = {}
            self.status.setText(
                'Run Full intelligence to populate Permissions Analysis. Empty evidence here does not establish absence of grants.'
            )
            return
        kwargs = {'include_prospective': self.prospective.isChecked()}
        self.payload = self.service.get_export_payload(**kwargs)
        result = self.service.get_tree(
            principal_query=self.principal.text(),
            path_query=self.path.text(),
            principal_type=self.kind.currentData(),
            show_inherited_principals=self.inherited.isChecked(),
            **kwargs,
        )
        kind = self.kind.currentData()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItem('All principal types', '')
        for value in result['principal_types']:
            self.kind.addItem(value, value)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.kind.blockSignals(False)
        count = 0
        restore = None
        for scope in result['paths']:
            if not scope['subjects']:
                continue
            node = QTreeWidgetItem(self.tree, [scope['path'], ''])
            for subject in scope['subjects']:
                child = QTreeWidgetItem(node, [subject['display_name'], subject['subject_type']])
                selection = (scope['path'], subject['subject_key'])
                child.setData(0, Qt.ItemDataRole.UserRole, selection)
                if selection == prior:
                    restore = child
                count += 1
            node.setExpanded(True)
        originals = {
            (str(row.get('internal_id')), row.get('statement_text')): row
            for row in self.context.policy_repo.regular_statements
        }
        self.exclusions.model.replace(
            [
                {**originals.get((str(row.get('statement_id')), row.get('statement_text')), {}), **row}
                for row in self.service.get_exclusions(**kwargs)
            ]
        )
        self.status.setText(
            f'{count:,} path/principal pairs · {len(self.exclusions.model.records):,} excluded statements. Select a principal, then a permission for source grants.'
        )
        if restore:
            self.tree.setCurrentItem(restore)

    def _scope_selected(self):
        item = self.tree.currentItem()
        self.selection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self._details()

    def _details(self, *_args):
        for table in self.tables.values():
            table.model.replace([])
        self.sources.model.replace([])
        if not self.selection or not self.service or self.block_reason:
            return
        path, principal = self.selection
        result = self.service.get_details(
            path_key=path,
            subject_key=principal,
            permission_query=self.permission_search.text(),
            include_inherited=self.inherited.isChecked(),
            include_prospective=self.prospective.isChecked(),
        )
        for effect, table in self.tables.items():
            table.model.replace(result[effect + '_rows'])

    def _permission_selected(self, effect):
        self.sources.model.replace([])
        rows = self.tables[effect].selected_records()
        if not rows or not self.selection:
            return
        permission = rows[0]['permission']
        path, principal = self.selection
        originals = {
            (str(row.get('internal_id')), row.get('statement_text')): row
            for row in self.context.policy_repo.regular_statements
        }
        evidence = []
        seen = set()
        for grant in self.payload.get('grant_rows', []):
            if (
                str(grant.get('effective_path', '')).strip('/').casefold() != path.strip('/').casefold()
                or str(grant.get('principal_key', '')).casefold() != principal.casefold()
                or grant.get('permission') != permission
                or grant.get('action') != effect
            ):
                continue
            if grant.get('inherited_from') and not self.inherited.isChecked():
                continue
            identity = (
                grant.get('statement_id'),
                grant.get('statement_text'),
                bool(grant.get('prospective')),
                str(grant.get('inherited_from') or '').casefold(),
            )
            if identity not in seen:
                seen.add(identity)
                evidence.append(
                    {
                        **originals.get((str(grant.get('statement_id')), grant.get('statement_text')), {}),
                        **grant,
                        'effective_path': path,
                    }
                )
        self.sources.model.replace(evidence)

    def export_json(self):
        """Export the current report only after an explicit destination choice."""
        if not self.payload or self.block_reason:
            return
        import json
        from pathlib import Path

        path, _ = QFileDialog.getSaveFileName(self, 'Export permission evidence', 'permissions.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(
                    json.dumps(self.payload, indent=2, ensure_ascii=False, default=str), encoding='utf-8'
                )
                self.status.setText(f'Exported permission evidence: {path}')
            except OSError as exc:
                self.status.setText(f'Could not export: {exc}')
