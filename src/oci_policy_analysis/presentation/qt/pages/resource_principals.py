"""Resource and workload principal evidence over the shared analysis service."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
from oci_policy_analysis.presentation.qt.tables import RecordTable, StatementTable
from oci_policy_analysis.presentation.qt.widgets import label

logger = get_logger(component='qt.pages.resource_principals')
MODES = ['any-user / any-group', 'any-user', 'any-group', 'Dynamic Group', 'OKE Workload Identity']


class ResourcePrincipalsPage(QWidget):
    """Inspect broad subjects, exact dynamic groups, and OKE workload evidence.

    Attributes:
        context: Current snapshot; replaced after each successful load.
        statements: Source statements with confidence and explicit detail actions.
        groups: Multi-select inventory used only in Dynamic Group mode.
        details_requested: Request for the shell's shared detail drawer.
        focus_dynamic_group: Request to focus a source statement on the DG page.

    Notes:
        Matching is evidence from the loaded snapshot, not an OCI authorization
        decision or an inventory of distinct resource principals.
    """

    details_requested = Signal(object, str)
    focus_dynamic_group = Signal(dict)

    def __init__(self) -> None:
        """Build live principal selectors and a vertically split evidence view."""
        super().__init__()
        self.context = None
        self._binding = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.setMinimumWidth(230)
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        row.addWidget(label('Principal type', 'muted'))
        row.addWidget(self.mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter displayed policy evidence…')
        self.search.setClearButtonEnabled(True)
        row.addStretch()
        reset = QPushButton('Reset filters')
        reset.clicked.connect(self.reset_filters)
        row.addWidget(reset)
        layout.addLayout(row)
        self.resource_options = QWidget()
        form = QHBoxLayout(self.resource_options)
        form.setContentsMargins(0, 0, 0, 0)
        self.resource_type = QComboBox()
        self.resource_type.addItem('Any')
        self.resource_type.setFixedWidth(230)
        self.compartment = QLineEdit()
        self.compartment.setMinimumWidth(240)
        self.compartment.setPlaceholderText('Resource compartment OCID · optional')
        self.compartment.setClearButtonEnabled(True)
        form.addWidget(label('Resource type', 'muted'))
        form.addWidget(self.resource_type)
        form.addWidget(label('Principal compartment', 'muted'))
        form.addWidget(self.compartment, 1)
        layout.addWidget(self.resource_options)
        self.oke_options = QWidget()
        oke = QGridLayout(self.oke_options)
        oke.setContentsMargins(0, 0, 0, 0)
        self.oke = {}
        for index, (key, title) in enumerate(
            [
                ('namespaces', 'Namespace'),
                ('service_accounts', 'Service account'),
                ('cluster_ids', 'Cluster OCID'),
            ]
        ):
            combo = QComboBox()
            combo.setEditable(True)
            combo.setMinimumWidth(180)
            combo.addItem('')
            combo.currentTextChanged.connect(self._schedule)
            self.oke[key] = combo
            oke.addWidget(label(title, 'muted'), index // 2, (index % 2) * 2)
            oke.addWidget(combo, index // 2, (index % 2) * 2 + 1)
        layout.addWidget(self.oke_options)
        self.status = label('No snapshot loaded', 'muted')
        status_row = QHBoxLayout()
        status_row.addWidget(self.status)
        status_row.addStretch()
        status_row.addWidget(label('Right-click a row for more details.', 'muted'))
        layout.addLayout(status_row)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.group_section = QWidget()
        group_layout = QVBoxLayout(self.group_section)
        group_layout.setContentsMargins(0, 0, 0, 0)
        self.group_search = QLineEdit()
        self.group_search.setPlaceholderText('Filter dynamic groups · Ctrl/Cmd-click selects several')
        self.group_search.setClearButtonEnabled(True)
        group_layout.addWidget(self.group_search)
        self.groups = RecordTable(
            (
                ('Domain', 'domain_name'),
                ('Dynamic group', 'dynamic_group_name'),
                ('In use', 'in_use'),
                ('Matching rule', 'matching_rule'),
            ),
            multi_select=True,
            details_title='Dynamic group details',
        )
        group_layout.addWidget(self.groups)
        splitter.addWidget(self.group_section)
        evidence = QWidget()
        evidence_layout = QVBoxLayout(evidence)
        evidence_layout.setContentsMargins(0, 8, 0, 0)
        evidence_layout.addWidget(self.search)
        self.statements = StatementTable()
        evidence_layout.addWidget(self.statements)
        splitter.addWidget(evidence)
        splitter.setSizes([230, 430])
        layout.addWidget(splitter, 1)
        self.statements.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Resource principal statement details')
        )
        self.groups.details_requested.connect(
            lambda record: self.details_requested.emit(record, 'Dynamic group details')
        )
        self.statements.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
        self.mode.currentIndexChanged.connect(self.apply_filters)
        self.resource_type.currentIndexChanged.connect(self.apply_filters)
        self.compartment.textChanged.connect(self._schedule)
        self.search.textChanged.connect(self.statements.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._counts)
        self.groups.selectionModel().selectionChanged.connect(self.apply_filters)
        self.group_search.textChanged.connect(self._filter_groups)
        self._visibility()

    def set_context(self, context) -> None:
        """Replace all inventory and discovered selectors from the active context."""
        self._binding = True
        self.context = context
        service = PrincipalAnalysisService(context)
        self.resource_type.clear()
        self.resource_type.addItems(service.get_resource_types())
        for key, values in service.get_workload_identity_values().items():
            self.oke[key].clear()
            self.oke[key].addItems(['', *values])
        self.compartment.clear()
        self.search.clear()
        self.group_search.clear()
        self.groups.model.replace(
            [
                {**group, 'dynamic_group_ocid': group.get('dynamic_group_ocid') or group.get('dynamic_group_id')}
                for group in context.policy_repo.dynamic_groups
            ]
        )
        self._binding = False
        self.apply_filters()

    def _schedule(self, *_args) -> None:
        if not self._binding:
            self.timer.start()

    def _visibility(self) -> None:
        mode = self.mode.currentText()
        self.resource_options.setVisible(mode not in {'Dynamic Group', 'OKE Workload Identity'})
        self.oke_options.setVisible(mode == 'OKE Workload Identity')
        self.group_section.setVisible(mode == 'Dynamic Group')

    def _filter_groups(self, text: str) -> None:
        self.groups.clearSelection()
        self.groups.proxy.setFilterFixedString(text)
        self.apply_filters()

    def apply_filters(self, *_args) -> None:
        """Query shared principal matching; retain original fields and confidence."""
        if self._binding:
            return
        self.timer.stop()
        self._visibility()
        if self.context is None:
            return
        service = PrincipalAnalysisService(self.context)
        mode = self.mode.currentText()
        if mode == 'Dynamic Group':
            result = service.by_exact_dynamic_groups(self.groups.selected_records())
        elif mode == 'OKE Workload Identity':
            result = service.by_oke_workload_identity(
                workload_namespace=self.oke['namespaces'].currentText().strip(),
                workload_service_account=self.oke['service_accounts'].currentText().strip(),
                workload_cluster_id=self.oke['cluster_ids'].currentText().strip(),
            )
        else:
            result = service.by_subject_types(
                subject_types=['any-user', 'any-group'] if mode == MODES[0] else [mode],
                resource_type=self.resource_type.currentText(),
                resource_compartment_ocid=self.compartment.text().strip(),
            )
        self.statements.model.replace(result.statements)
        self._counts()
        logger.info('Resource principal mode=%s statements=%d', mode, len(result.statements))

    def _counts(self, *_args) -> None:
        self.status.setText(
            f'{self.statements.proxy.rowCount():,} shown · {self.statements.model.rowCount():,} matching statements'
        )

    def reset_filters(self) -> None:
        """Clear selectors and return to combined any-user / any-group evidence."""
        self._binding = True
        self.mode.setCurrentIndex(0)
        self.resource_type.setCurrentIndex(0)
        self.compartment.clear()
        self.search.clear()
        self.group_search.clear()
        self.groups.clearSelection()
        for combo in self.oke.values():
            combo.setCurrentIndex(0)
        self._binding = False
        self.apply_filters()
