"""Compartment, policy, tag, and tenancy-limit inventory for Qt."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService
from oci_policy_analysis.presentation import format_compartment_policy_name
from oci_policy_analysis.presentation.qt.policy_limits import PolicyLimitsDialog
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class _InventoryProxy(QSortFilterProxyModel):
    """Combine text search with the selected compartment and policy rows."""

    def __init__(self, table, kind, parent):
        super().__init__(parent)
        self.kind = kind
        self.query = ''
        self.compartment_ocid = ''
        self.policy_ocid = ''
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(-1)
        self.setSourceModel(table.model)
        table.proxy = self
        table.setModel(self)

    def filterAcceptsRow(self, source_row, source_parent):
        record = self.sourceModel().records[source_row]
        if (
            self.kind == 'policy'
            and self.compartment_ocid
            and str(record.get('compartment_ocid') or '') != self.compartment_ocid
        ):
            return False
        if self.kind == 'statement' and self.policy_ocid and str(record.get('policy_ocid') or '') != self.policy_ocid:
            return False
        if not self.query:
            return True
        return self.query.casefold() in ' '.join(str(value) for value in record.values()).casefold()


class _LimitFetchWorker(QThread):
    """Fetch live tenancy limits away from the UI thread."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context

    def run(self) -> None:
        """Fetch through the active repository OCI client and return its result."""
        try:
            repo = self.context.policy_repo
            repo.fetch_tenancy_policy_statement_limits()
            self.completed.emit(dict(getattr(repo, 'tenancy_policy_limits', {}) or {}))
        except Exception as exc:
            self.failed.emit(str(exc))


class PolicyInventoryPage(QWidget):
    """Browse the loaded compartment hierarchy, policies, statements and tags.

    Attributes:
        busy_changed: Signals explicit live-limit fetches so the shell can serialize loads.
        details_requested: Requests source-record inspection in the shared drawer.
        limits_changed: Indicates the active snapshot's validated policy limits changed.

    Notes:
        Inventory is rebuilt from the active snapshot. Cached/CIS limit overrides
        update that cache when one is active; live limits require an explicit fetch.
    """

    busy_changed = Signal(bool)
    details_requested = Signal(object, str)
    focus_policy_requested = Signal(object)
    limits_changed = Signal()
    limits_status_changed = Signal(str)

    def __init__(self, cache) -> None:
        """Build inventory views and retain the existing cache store.

        Args:
            cache: Existing cache manager used only when applying explicit limits
                to an active named snapshot.
        """
        super().__init__()
        self.cache = cache
        self.context = None
        self.worker = None
        self._limit_message = ''
        self.limit_dialog = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        limits_panel = QWidget()
        limit_layout = QVBoxLayout(limits_panel)
        limit_layout.setContentsMargins(0, 0, 0, 0)
        self.limits_summary = label('Load a snapshot to view policy limits.', 'notice', wrap=True)
        limit_layout.addWidget(self.limits_summary)
        controls = QHBoxLayout()
        self.fetch_limits = QPushButton('Fetch limits from OCI')
        self.fetch_limits.clicked.connect(lambda: self.manage_limits())
        controls.addWidget(self.fetch_limits)
        controls.addStretch()
        limit_layout.addLayout(controls)
        layout.addWidget(limits_panel)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter compartments, policies, statements, or tags…')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.tabs = QTabWidget()
        self.hierarchy = QTreeWidget()
        self.hierarchy.setHeaderLabel('Compartments → Policies → Tags and Statements')
        self.hierarchy.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hierarchy.customContextMenuRequested.connect(self._show_hierarchy_menu)
        self.tabs.addTab(self.hierarchy, 'Hierarchy')
        self.compartments = RecordTable(
            (
                ('Compartment', 'name'),
                ('Hierarchy path', 'path'),
                ('Direct statements', 'statement_count_direct'),
                ('Cumulative statements', 'statement_count_cumulative'),
                ('Description', 'description'),
            ),
            details_title='Compartment details',
        )
        self.policies = RecordTable(
            (
                ('Compartment + policy', 'policy_display'),
                ('Statements', 'statement_count'),
                ('OCID', 'policy_ocid'),
            ),
            details_title='Policy details',
        )
        self.statements = RecordTable(
            (
                ('Policy', 'policy_display'),
                ('Effective path', 'effective_path'),
                ('Original statement', 'statement_text'),
            ),
            details_title='Policy statement details',
        )
        self.tags = RecordTable(
            (
                ('Scope', 'scope'),
                ('Path', 'path'),
                ('Policy', 'policy_name'),
                ('Namespace', 'namespace'),
                ('Key', 'key'),
                ('Value', 'value'),
            ),
            details_title='Tag details',
        )
        self._proxies = {
            'compartments': _InventoryProxy(self.compartments, 'compartment', self),
            'policies': _InventoryProxy(self.policies, 'policy', self),
            'statements': _InventoryProxy(self.statements, 'statement', self),
            'tags': _InventoryProxy(self.tags, 'tag', self),
        }
        for table, title in (
            (self.compartments, 'Compartments'),
            (self.policies, 'Policies'),
            (self.statements, 'Statements'),
            (self.tags, 'Tags'),
        ):
            table.details_requested.connect(
                lambda record, title=title: self.details_requested.emit(record, f'{title} details')
            )
            self.tabs.addTab(table, title)
        self.compartments.selectionModel().selectionChanged.connect(self._compartment_selected)
        self.policies.selectionModel().selectionChanged.connect(self._policy_selected)
        layout.addWidget(self.tabs, 1)
        self.search.textChanged.connect(self._filters_changed)
        self.status = label(
            'Counts describe the loaded snapshot. Conditions and exclusions remain relevant.', 'muted', wrap=True
        )
        layout.addWidget(self.status)

    def set_context(self, context) -> None:
        """Replace the inventory with data from the active snapshot.

        Args:
            context: Loaded application context, or None to clear the view.
        """
        if self.limit_dialog:
            self.limit_dialog.reject()
            self.limit_dialog.deleteLater()
            self.limit_dialog = None
        self.context = context
        self._limit_message = ''
        self.search.clear()
        for proxy in self._proxies.values():
            proxy.compartment_ocid = ''
            proxy.policy_ocid = ''
            proxy.query = ''
            proxy.invalidateFilter()
        for table in (self.compartments, self.policies, self.statements, self.tags):
            table.model.replace([])
        if context is None:
            self.limits_summary.setText('Load a snapshot to view policy limits.')
            self.fetch_limits.hide()
            return
        repo = context.policy_repo
        statements = list(getattr(repo, 'regular_statements', []) or [])
        statement_counts = Counter(str(row.get('policy_ocid') or '') for row in statements)
        compartments = []
        for row in getattr(repo, 'compartments', []) or []:
            compartments.append(
                {
                    **row,
                    'path': row.get('hierarchy_path') or row.get('path') or row.get('name') or '',
                    'statement_count_direct': int(row.get('statement_count_direct') or 0),
                    'statement_count_cumulative': int(row.get('statement_count_cumulative') or 0),
                }
            )
        policies = []
        for row in getattr(repo, 'policies', []) or []:
            comp_path = (
                row.get('compartment_path') or repo.get_compartment_path_for_ocid(row.get('compartment_ocid')) or ''
            )
            policies.append(
                {
                    **row,
                    'compartment_path': comp_path,
                    'policy_display': format_compartment_policy_name(
                        comp_path, row.get('policy_name') or '(Unnamed Policy)'
                    ),
                    'statement_count': statement_counts.get(str(row.get('policy_ocid') or ''), 0),
                }
            )
        self.compartments.model.replace(compartments)
        self.policies.model.replace(policies)
        self._build_hierarchy(repo, compartments, policies, statements)
        self.statements.model.replace(
            [
                {
                    **row,
                    'policy_display': format_compartment_policy_name(
                        row.get('compartment_path')
                        or (
                            repo.get_compartment_path_for_ocid(row.get('compartment_ocid'))
                            if row.get('compartment_ocid')
                            else ''
                        ),
                        row.get('policy_name'),
                    ),
                }
                for row in statements
            ]
        )
        self.tags.model.replace(self._tag_rows(compartments, policies))
        self._update_limits_ui()
        self._update_status()

    def _build_hierarchy(self, repo, compartments, policies, statements):
        """Render tenancy limits and inventory as an expandable source hierarchy."""
        self.hierarchy.clear()
        limits = getattr(repo, 'tenancy_policy_limits', {}) or {}
        chain_limit = limits.get('policy_statements_per_compartment_chain_count')
        policies_limit = limits.get('policies_count')
        max_chain = max((int(row.get('statement_count_cumulative') or 0) for row in compartments), default=0)
        root = QTreeWidgetItem(
            [
                f'Tenancy limits · policies {len(policies):,} / {self._number(policies_limit)} · '
                f'maximum statement chain {max_chain:,} / {self._number(chain_limit)}'
            ]
        )
        self.hierarchy.addTopLevelItem(root)
        root.setExpanded(True)
        policies_by_compartment = {}
        for policy in policies:
            policies_by_compartment.setdefault(str(policy.get('compartment_ocid') or ''), []).append(policy)
        statements_by_policy = {}
        for statement in statements:
            statements_by_policy.setdefault(str(statement.get('policy_ocid') or ''), []).append(statement)
        children_by_parent = {}
        for compartment in compartments:
            children_by_parent.setdefault(str(compartment.get('parent_id') or ''), []).append(compartment)

        def add_tags(parent, record):
            for namespace, key, value in self._tag_entries(record):
                QTreeWidgetItem(parent, [f'Tag · {namespace}: {key} = {value}'])

        def add_compartments(parent_item, parent_id=''):
            for compartment in children_by_parent.get(parent_id, []):
                compartment_id = str(compartment.get('id') or '')
                count = (
                    f'Statements · direct {compartment.get("statement_count_direct", 0):,} · '
                    f'cumulative {compartment.get("statement_count_cumulative", 0):,} / '
                    f'{self._number(chain_limit)} limit'
                )
                item = QTreeWidgetItem(
                    parent_item,
                    [f'Compartment: {compartment.get("name") or "(Unnamed)"} · {compartment.get("path", "")}'],
                )
                item.setData(0, Qt.ItemDataRole.UserRole, ('compartment', compartment))
                QTreeWidgetItem(item, [count])
                description = str(compartment.get('description') or '').strip()
                if description:
                    QTreeWidgetItem(item, [f'Description: {description}'])
                add_tags(item, compartment)
                compartment_policies = policies_by_compartment.get(compartment_id, [])
                policy_parent = QTreeWidgetItem(item, ['Policies']) if compartment_policies else None
                for policy in compartment_policies:
                    policy_item = QTreeWidgetItem(
                        policy_parent, [f'Policy: {policy.get("policy_name") or "(Unnamed Policy)"}']
                    )
                    policy_item.setData(0, Qt.ItemDataRole.UserRole, ('policy', policy))
                    add_tags(policy_item, policy)
                    for statement in statements_by_policy.get(str(policy.get('policy_ocid') or ''), []):
                        statement_item = QTreeWidgetItem(
                            policy_item, [str(statement.get('statement_text') or '(No statement text)')]
                        )
                        statement_item.setData(0, Qt.ItemDataRole.UserRole, ('statement', statement))
                add_compartments(item, compartment_id)

        tenancy_id = str(getattr(repo, 'tenancy_ocid', None) or getattr(repo, 'tenancy_id', None) or '')
        add_compartments(root, tenancy_id)
        self.hierarchy.expandToDepth(1)
        self._filter_hierarchy(self.search.text())

    @staticmethod
    def _tag_entries(record):
        entries = []
        defined = record.get('defined_tags') or record.get('policy_defined_tags') or {}
        freeform = record.get('freeform_tags') or record.get('policy_freeform_tags') or {}
        for namespace, values in defined.items() if isinstance(defined, dict) else ():
            if isinstance(values, dict):
                entries.extend((str(namespace), str(key), str(value)) for key, value in values.items())
        if isinstance(freeform, dict):
            entries.extend(('Freeform', str(key), str(value)) for key, value in freeform.items())
        if not entries and isinstance(record.get('tags'), dict):
            for key, value in record['tags'].items():
                namespace, separator, tag_key = str(key).partition(':')
                entries.append(
                    (namespace if separator else 'Freeform', tag_key if separator else namespace, str(value))
                )
        return entries

    def _show_hierarchy_menu(self, position):
        item = self.hierarchy.itemAt(position)
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        kind, record = data
        menu = QMenu(self.hierarchy)
        if kind == 'statement':
            menu.addAction('Statement details', lambda: self.details_requested.emit(record, 'Policy statement details'))
        elif kind == 'policy':
            menu.addAction('Policy details', lambda: self.details_requested.emit(record, 'Policy details'))
            menu.addAction('Focus on Policy', lambda: self.focus_policy_requested.emit(record))
        elif kind == 'compartment':
            menu.addAction('Compartment details', lambda: self.details_requested.emit(record, 'Compartment details'))
        menu.exec(self.hierarchy.viewport().mapToGlobal(position))

    @staticmethod
    def _tag_rows(compartments, policies):
        rows = []
        for scope, items in (('Compartment', compartments), ('Policy', policies)):
            for item in items:
                path = item.get('path') or item.get('compartment_path') or item.get('policy_name') or ''
                freeform = item.get('freeform_tags') or item.get('policy_freeform_tags') or {}
                defined = item.get('defined_tags') or item.get('policy_defined_tags') or {}
                combined = item.get('tags') or {}
                if isinstance(combined, dict) and not (isinstance(freeform, dict) or isinstance(defined, dict)):
                    for key, value in combined.items():
                        rows.append(
                            {
                                'scope': scope,
                                'path': path,
                                'policy_name': item.get('policy_name') or '',
                                'namespace': '',
                                'key': str(key),
                                'value': str(value),
                            }
                        )
                if isinstance(freeform, dict):
                    for key, value in freeform.items():
                        rows.append(
                            {
                                'scope': scope,
                                'path': path,
                                'policy_name': item.get('policy_name') or '',
                                'namespace': 'Freeform',
                                'key': str(key),
                                'value': str(value),
                            }
                        )
                if isinstance(defined, dict):
                    for namespace, values in defined.items():
                        if isinstance(values, dict):
                            for key, value in values.items():
                                rows.append(
                                    {
                                        'scope': scope,
                                        'path': path,
                                        'policy_name': item.get('policy_name') or '',
                                        'namespace': str(namespace),
                                        'key': str(key),
                                        'value': str(value),
                                    }
                                )
        unique = {
            (row['scope'], row['path'], row['policy_name'], row['namespace'], row['key'], row['value']): row
            for row in rows
        }
        return [unique[key] for key in sorted(unique, key=lambda item: tuple(str(value).casefold() for value in item))]

    @staticmethod
    def _number(value):
        try:
            return f'{int(value):,}'
        except (TypeError, ValueError):
            return str(value) if value not in (None, '') else 'not recorded'

    def _offline_editable(self):
        return bool(self.context and not PolicyLimitsService(self.context).is_live_loaded)

    def manage_limits(self, parent=None) -> None:
        """Fetch live limits or open manual entry for a non-live snapshot.

        Args:
            parent: Optional owning page for the modal entry dialog.
        """
        if self.context is None or self.worker is not None or not self.isEnabled():
            return
        if PolicyLimitsService(self.context).is_live_loaded:
            self._fetch_limits()
            return
        if self.limit_dialog:
            self.limit_dialog.reject()
            self.limit_dialog.deleteLater()
        self.limit_dialog = PolicyLimitsDialog(self.context, parent if parent is not None else self)
        self.limit_dialog.accepted.connect(self._manual_limits_saved)
        self.limit_dialog.show()

    def _manual_limits_saved(self):
        self._refresh_limit_views()
        self.limits_changed.emit()
        self.limits_status_changed.emit('')

    def _refresh_limit_views(self):
        if self.context is not None:
            self._update_limits_ui()
            self._build_hierarchy(
                self.context.policy_repo,
                self.compartments.model.records,
                self.policies.model.records,
                self.statements.model.records,
            )

    def _update_limits_ui(self):
        if self.context is None:
            return
        repo = self.context.policy_repo
        limits = getattr(repo, 'tenancy_policy_limits', {}) or {}
        offline = self._offline_editable()
        policy_limit = limits.get('policies_count')
        chain_limit = limits.get('policy_statements_per_compartment_chain_count')
        max_chain = max((int(row.get('statement_count_cumulative') or 0) for row in repo.compartments or []), default=0)
        policy_limit_text = self._number(policy_limit) if policy_limit else 'not recorded'
        chain_limit_text = self._number(chain_limit) if chain_limit else 'not recorded'
        self.limits_summary.setText(
            f'Policies: {len(repo.policies):,} loaded / {policy_limit_text} limit'
            f' · Maximum compartment statement chain: {max_chain:,} / {chain_limit_text} limit'
            f' · Source: {limits.get("source") or "not supplied"}'
        )
        service = PolicyLimitsService(self.context)
        self.fetch_limits.setText('Enter known limits…' if offline else 'Fetch limits from OCI')
        self.fetch_limits.show()
        self.fetch_limits.setEnabled(self.worker is None and (offline or service.can_fetch_live))
        self.fetch_limits.setToolTip(
            'Enter verified limits for this snapshot, with Console and CLI guidance.'
            if offline
            else 'Fetches the two Identity policy limits from the active OCI tenancy.'
        )

    def _fetch_limits(self):
        if not self.context or self.worker is not None:
            return
        if not PolicyLimitsService(self.context).is_live_loaded:
            self.limits_summary.setText(
                'OCI limit retrieval requires a live-loaded tenancy. Enter known limits for this snapshot instead.'
            )
            return
        if not PolicyLimitsService(self.context).can_fetch_live:
            self.limits_summary.setText(
                'OCI limits client is unavailable for this session. Check load credentials and retry.'
            )
            return
        self._limit_message = ''
        self.worker = _LimitFetchWorker(self.context, self)
        self.worker.completed.connect(self._limits_fetched)
        self.worker.failed.connect(self._limits_failed)
        self.worker.finished.connect(self._worker_finished)
        self.fetch_limits.setEnabled(False)
        self.limits_summary.setText('Fetching policy limits from OCI…')
        self.limits_status_changed.emit(self.limits_summary.text())
        self.busy_changed.emit(True)
        self.worker.start()

    def _limits_fetched(self, limits):
        if self.context is None:
            return
        self._limit_message = ''
        if not limits.get('policies_count') or not limits.get('policy_statements_per_compartment_chain_count'):
            self._limit_message = 'OCI did not return both policy limits. Verify limit access and refresh again.'
        self._refresh_limit_views()
        self.limits_changed.emit()

    def _limits_failed(self, message):
        self._limit_message = f'Could not fetch OCI limits: {message}'

    def _worker_finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self._update_limits_ui()
        if self._limit_message:
            self.limits_summary.setText(self._limit_message)
        self.limits_status_changed.emit(self._limit_message)
        self.busy_changed.emit(False)

    def _compartment_selected(self, *_args):
        selected = self.compartments.selected_records()
        self._proxies['policies'].compartment_ocid = str(selected[0].get('id') or '') if selected else ''
        self._proxies['policies'].invalidateFilter()

    def _policy_selected(self, *_args):
        selected = self.policies.selected_records()
        self._proxies['statements'].policy_ocid = str(selected[0].get('policy_ocid') or '') if selected else ''
        self._proxies['statements'].invalidateFilter()

    def _filters_changed(self, text):
        for proxy in self._proxies.values():
            proxy.query = text.strip()
            proxy.invalidateFilter()
        self._filter_hierarchy(text)
        self._update_status()

    def _filter_hierarchy(self, text):
        query = text.strip().casefold()

        def visit(item):
            own_match = not query or query in item.text(0).casefold()
            child_matches = [visit(item.child(index)) for index in range(item.childCount())]
            child_match = any(child_matches)
            item.setHidden(not (own_match or child_match))
            if query and child_match:
                item.setExpanded(True)
            return own_match or child_match

        for index in range(self.hierarchy.topLevelItemCount()):
            visit(self.hierarchy.topLevelItem(index))

    def _update_status(self):
        if not self.context:
            self.status.setText('Counts describe the loaded snapshot. Conditions and exclusions remain relevant.')
            return
        self.status.setText(
            f'{self.compartments.proxy.rowCount():,} compartments · {self.policies.proxy.rowCount():,} policies · '
            f'{self.statements.proxy.rowCount():,} statements · {self.tags.proxy.rowCount():,} tag values shown. '
            'Counts describe the loaded snapshot; conditions and exclusions remain relevant.'
        )
