"""Loaded identity inventory, membership evidence, and related source policies."""

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import label


class _IdentityView(QWidget):
    def __init__(self, *, users: bool):
        super().__init__()
        self.users = users
        self.context = None
        self.kind = 'user' if users else 'group'
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        controls = QGridLayout()
        self.filters = {}
        fields = [
            ('domain_name', 'Domain'),
            ('search' if users else 'group_name', 'Username or display name' if users else 'Group name'),
            (f'{self.kind}_ocid', f'{self.kind.title()} OCID'),
        ]
        for column, (key, title) in enumerate(fields):
            field = QLineEdit()
            field.setPlaceholderText(title)
            field.setClearButtonEnabled(True)
            field.setToolTip('AND between fields; | separates alternatives. Filters apply automatically.')
            field.textChanged.connect(lambda *_: self.timer.start())
            field.returnPressed.connect(self.apply_filters)
            self.filters[key] = field
            controls.addWidget(field, 0, column)
        reset = QPushButton('Reset filters')
        reset.clicked.connect(self.reset_filters)
        controls.addWidget(reset, 0, 3)
        layout.addLayout(controls)
        self.inventory_status = label('No identities loaded', 'muted')
        layout.addWidget(self.inventory_status)
        layout.addWidget(
            label('Select one or more rows · Ctrl/Cmd-click or Shift-click · Right-click for details', 'muted')
        )
        splitter = QSplitter(Qt.Orientation.Vertical)
        columns = (
            (('Domain', 'domain_name'), ('User', 'user_name'), ('Display name', 'display_name'), ('Email', 'email'))
            if users
            else (('Domain', 'domain_name'), ('Group', 'group_name'), ('Description', 'description'))
        )
        self.inventory = RecordTable(columns, multi_select=True, details_title=f'{self.kind.title()} details')
        self.inventory.selectionModel().selectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.inventory)
        membership_panel = QWidget()
        membership_panel.setMinimumHeight(170)
        membership_layout = QVBoxLayout(membership_panel)
        membership_layout.setContentsMargins(0, 8, 0, 0)
        self.membership_status = label(
            'Groups for each selected user' if users else 'Members of selected groups', 'muted'
        )
        membership_layout.addWidget(self.membership_status)
        member_columns = (
            (
                ('User domain', 'user_domain'),
                ('User', 'user_name'),
                ('Group domain', 'domain_name'),
                ('Group', 'group_name'),
                ('Group OCID', 'group_ocid'),
                ('Snapshot evidence', 'membership_status'),
            )
            if users
            else (
                ('Domain', 'domain_name'),
                ('User', 'user_name'),
                ('Display name', 'display_name'),
                ('Email', 'email'),
            )
        )
        self.memberships = RecordTable(member_columns, details_title='Membership details' if users else 'User details')
        membership_layout.addWidget(self.memberships)
        splitter.addWidget(membership_panel)
        evidence = QWidget()
        lower = QVBoxLayout(evidence)
        lower.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.statement_status = label('Select identities to see related policy statements', 'muted')
        row.addWidget(self.statement_status)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter related statements…')
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        lower.addLayout(row)
        self.statements = StatementTable()
        self.statements.details_title = 'Statement details'
        self.search.textChanged.connect(self.statements.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._counts)
        lower.addWidget(self.statements)
        splitter.addWidget(evidence)
        splitter.setSizes([240, 220, 300])
        layout.addWidget(splitter, 1)
        layout.addWidget(
            label(
                'Snapshot evidence only. Coverage may be incomplete; policy conditions and exclusions still apply.',
                'muted',
            )
        )

    def set_context(self, context):
        self.context = context
        self.search.clear()
        self.apply_filters(preserve_selection=False)

    def reset_filters(self):
        for field in self.filters.values():
            field.clear()
        self.apply_filters()

    def _identity(self, record):
        return (
            record.get(f'{self.kind}_ocid') or '',
            (record.get('domain_name') or 'Default').casefold(),
            (record.get(f'{self.kind}_name') or '').casefold(),
        )

    def apply_filters(self, *, preserve_selection=True):
        self.timer.stop()
        if self.context is None:
            return
        selected = (
            {self._identity(record) for record in self.inventory.selected_records()} if preserve_selection else set()
        )
        filters = {
            key: [part.strip() for part in field.text().split('|') if part.strip()]
            for key, field in self.filters.items()
            if field.text().strip()
        }
        repo = self.context.policy_repo
        records = repo.filter_users(filters) if self.users else repo.filter_groups(filters)
        selection = self.inventory.selectionModel()
        selection.blockSignals(True)
        try:
            self.inventory.model.replace(records)
            for row in range(self.inventory.proxy.rowCount()):
                index = self.inventory.proxy.index(row, 0)
                if self._identity(self.inventory.record_at(index)) in selected:
                    selection.select(
                        index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                    )
        finally:
            selection.blockSignals(False)
        total = len(repo.users if self.users else repo.groups)
        self.inventory_status.setText(f'{len(records):,} shown / {total:,} known {self.kind}s')
        self._selection_changed()

    def _selection_changed(self, *_args):
        if self.context is None:
            return
        selected = self.inventory.selected_records()
        service = PrincipalAnalysisService(self.context)
        if self.users:
            rows = service.user_group_rows(selected)
            result = service.by_groups_users(users=selected)
        else:
            rows = []
            seen = set()
            for group in selected:
                for user in self.context.policy_repo.get_users_for_group(group):
                    key = (user.get('user_ocid'), user.get('domain_name'), user.get('user_name'))
                    if key not in seen:
                        seen.add(key)
                        rows.append(user)
            result = service.by_groups_users(groups=selected)
        self.memberships.model.replace(rows)
        self.statements.model.replace(result.statements)
        title = 'Membership evidence rows' if self.users else 'Known members'
        self.membership_status.setText(f'{title}: {len(rows):,}')
        self._counts()

    def _counts(self, *_args):
        self.statement_status.setText(
            f'{len(self.inventory.selected_records()):,} selected · {self.statements.proxy.rowCount():,} shown / {self.statements.model.rowCount():,} related statements'
        )


class UsersGroupsPage(QWidget):
    """Browse loaded users and groups with read-only membership and policy evidence.

    Attributes:
        tabs: Group-based and user-based inventory views.
        group_view: Group filters, selected members, and matching statements.
        user_view: User filters, per-user memberships, and matching statements.
        details_requested: Explicit request to inspect retained source evidence.
    """

    details_requested = Signal(object, str)
    focus_dynamic_group = Signal(dict)

    def __init__(self) -> None:
        """Build both subtabs without loading or modifying tenancy data."""
        super().__init__()
        self.context = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.group_view = _IdentityView(users=False)
        self.user_view = _IdentityView(users=True)
        for title, view in [('Group-based View', self.group_view), ('User-based View', self.user_view)]:
            self.tabs.addTab(view, title)
            for table in (view.inventory, view.memberships, view.statements):
                table.details_requested.connect(
                    lambda record, table=table: self.details_requested.emit(record, table.details_title)
                )
            view.statements.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
        self.tabs.currentChanged.connect(lambda *_: self.details_requested.emit(None, ''))
        layout.addWidget(self.tabs)

    def set_context(self, context) -> None:
        """Replace the current snapshot and discard selections from the previous load.

        Args:
            context: Successfully loaded application context; queries remain local.
        """
        self.context = context
        self.group_view.set_context(context)
        self.user_view.set_context(context)
