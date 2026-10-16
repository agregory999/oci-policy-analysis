"""Dynamic-group inventory and exact principal-focused policy evidence."""

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.common.grouping_helpers import named_principals
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import SegmentedControl, label

logger = get_logger(component='qt.pages.dynamic_groups')


def _identity(group: dict) -> tuple:
    return (
        (group.get('domain_name') or 'Default').casefold(),
        (group.get('dynamic_group_name') or '').casefold(),
        group.get('dynamic_group_ocid') or group.get('dynamic_group_id') or '',
    )


class DynamicGroupsPage(QWidget):
    """Browse known dynamic groups and the union of their source statements.

    Attributes:
        group_table: Sortable inventory with Ctrl/Cmd and Shift multi-selection.
        statements: Shared statement table with details and cross-page actions.
        context: Current loaded snapshot; replaced on each successful load.
    """

    details_requested = Signal(object, str)
    focus_dynamic_group = Signal(dict)

    def __init__(self) -> None:
        """Build live inventory filters and vertically split evidence tables."""
        super().__init__()
        self.context = None
        self._resetting = False
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(200)
        self.filter_timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QGridLayout()
        self.filters = {}
        for index, (key, title) in enumerate(
            (
                ('domain_name', 'Domain'),
                ('dynamic_group_name', 'Dynamic group name'),
                ('matching_rule', 'Matching rule'),
                ('dynamic_group_ocid', 'Dynamic group OCID'),
            )
        ):
            field = QLineEdit()
            field.setPlaceholderText(title)
            field.setClearButtonEnabled(True)
            field.setToolTip('AND between fields; | separates alternatives. Filters apply automatically.')
            field.textChanged.connect(self._schedule_filters)
            field.returnPressed.connect(self.apply_filters)
            self.filters[key] = field
            controls.addWidget(field, index // 2, index % 2)
        self.in_use = SegmentedControl(['All', 'In Use only', 'Not Used'])
        self.in_use.currentIndexChanged.connect(self._dropdown_changed)
        controls.addWidget(self.in_use, 2, 0)
        reset = QPushButton('Reset filters')
        reset.clicked.connect(self.reset_filters)
        controls.addWidget(reset, 2, 1)
        layout.addLayout(controls)
        self.inventory_status = label('No dynamic groups loaded', 'muted')
        layout.addWidget(self.inventory_status)
        layout.addWidget(label('Select groups to see related statements · Ctrl/Cmd-click selects several', 'muted'))
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.group_table = RecordTable(
            (
                ('Domain', 'domain_name'),
                ('Dynamic group', 'dynamic_group_name'),
                ('In use', 'in_use'),
                ('Matching rule', 'matching_rule'),
            ),
            multi_select=True,
            details_title='Dynamic group details',
        )
        self.group_table.setColumnWidth(2, 70)
        self.group_table.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Dynamic group details')
        )
        self.group_table.selectionModel().selectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.group_table)
        evidence = QWidget()
        lower = QVBoxLayout(evidence)
        lower.setContentsMargins(0, 12, 0, 0)
        row = QHBoxLayout()
        self.statement_status = label('Select a dynamic group', 'muted')
        row.addWidget(self.statement_status)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter related statements…')
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        lower.addLayout(row)
        self.statements = StatementTable()
        self.statements.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Statement details')
        )
        self.statements.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
        self.search.textChanged.connect(self.statements.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._counts)
        lower.addWidget(self.statements)
        splitter.addWidget(evidence)
        splitter.setSizes([300, 350])
        layout.addWidget(splitter, 1)

    def set_context(self, context) -> None:
        """Discard prior selections and bind inventory to the new loaded snapshot."""
        self.context = context
        self.group_table.clearSelection()
        self.statements.model.replace([])
        self.search.clear()
        self.apply_filters(preserve_selection=False)

    def _schedule_filters(self, *_args) -> None:
        if not self._resetting:
            self.filter_timer.start()

    def _dropdown_changed(self, *_args) -> None:
        if not self._resetting:
            self.apply_filters()

    def reset_filters(self) -> None:
        """Clear inventory filters and retain only explicitly visible selections."""
        self._resetting = True
        try:
            for field in self.filters.values():
                field.clear()
            self.in_use.setCurrentIndex(0)
        finally:
            self._resetting = False
        self.apply_filters()

    def apply_filters(self, *, preserve_selection: bool = True) -> None:
        """Apply repository inventory filters; hidden groups stop contributing evidence."""
        self.filter_timer.stop()
        if self.context is None:
            return
        selected = {_identity(group) for group in self.group_table.selected_records()} if preserve_selection else set()
        payload = {
            key: [part.strip() for part in field.text().split('|') if part.strip()]
            for key, field in self.filters.items()
            if field.text().strip()
        }
        if self.in_use.currentIndex():
            payload['in_use'] = self.in_use.currentIndex() == 1
        groups = self.context.policy_repo.filter_dynamic_groups(payload)
        selection = self.group_table.selectionModel()
        selection.blockSignals(True)
        try:
            self.group_table.model.replace(groups)
            for row in range(self.group_table.proxy.rowCount()):
                index = self.group_table.proxy.index(row, 0)
                if _identity(self.group_table.record_at(index)) in selected:
                    selection.select(
                        index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                    )
        finally:
            selection.blockSignals(False)
        self.details_requested.emit(None, '')
        self.inventory_status.setText(
            f'{len(groups):,} shown · {len(self.context.policy_repo.dynamic_groups):,} known dynamic groups · Snapshot coverage may be incomplete'
        )
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        if self.context is None:
            return
        groups = [
            {**group, 'dynamic_group_ocid': group.get('dynamic_group_ocid') or group.get('dynamic_group_id')}
            for group in self.group_table.selected_records()
        ]
        result = PrincipalAnalysisService(self.context).by_exact_dynamic_groups(groups)
        self.statements.model.replace(result.statements)
        self._counts()
        logger.info('Dynamic-group selection: groups=%d statements=%d', len(groups), len(result.statements))

    def _counts(self, *_args) -> None:
        self.statement_status.setText(
            f'{len(self.group_table.selected_records()):,} selected · {self.statements.proxy.rowCount():,} shown / {self.statements.model.rowCount():,} related statements'
        )

    def focus_statement(self, statement: dict) -> bool:
        """Select known groups referenced by a statement, using exact names or IDs.

        Args:
            statement: Retained source statement; names are matched with domain,
                and opaque IDs are compared without changing their values.

        Returns:
            bool: Whether at least one referenced group exists in the inventory.
        """
        self.reset_filters()
        self.search.clear()
        names = (
            {(domain.casefold(), name.casefold()) for domain, name in named_principals(statement) or []}
            if str(statement.get('subject_type') or '').casefold() == 'dynamic-group'
            else set()
        )
        ids = set()
        if str(statement.get('subject_type') or '').casefold() == 'dynamic-group-id':
            for subject in statement.get('subject') or []:
                if isinstance(subject, str):
                    ids.add(subject)
                elif isinstance(subject, list | tuple) and len(subject) >= 2:
                    ids.add(str(subject[1]))
        for principal in statement.get('principals') or []:
            if isinstance(principal, dict):
                if principal.get('ocid'):
                    ids.add(str(principal['ocid']))
                key = principal.get('principal_key')
                if isinstance(key, str) and key.startswith('dynamic-group-id:'):
                    ids.add(key.split(':', 1)[1])
        selection = self.group_table.selectionModel()
        selection.blockSignals(True)
        try:
            self.group_table.clearSelection()
            for row in range(self.group_table.proxy.rowCount()):
                index = self.group_table.proxy.index(row, 0)
                group = self.group_table.record_at(index)
                domain, name, ocid = _identity(group)
                if (domain, name) in names or (ocid and ocid in ids):
                    selection.select(
                        index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                    )
                    self.group_table.scrollTo(index)
        finally:
            selection.blockSignals(False)
        self.details_requested.emit(None, '')
        self._selection_changed()
        matched = bool(self.group_table.selected_records())
        if not matched:
            self.statement_status.setText(
                'No referenced dynamic group found in the loaded inventory. Coverage may be incomplete.'
            )
        return matched
