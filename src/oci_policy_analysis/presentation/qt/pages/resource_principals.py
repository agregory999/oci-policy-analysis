"""Resource and workload principal evidence over the shared analysis service."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
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
        self.mode.setFixedWidth(230)
        row.addWidget(self.mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter displayed policy evidence…')
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        reset = QPushButton('Reset filters')
        reset.clicked.connect(self.reset_filters)
        row.addWidget(reset)
        layout.addLayout(row)
        self.resource_options = QWidget()
        form = QFormLayout(self.resource_options)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.resource_type = QComboBox()
        self.resource_type.addItem('Any')
        self.resource_type.setFixedWidth(230)
        self.compartment = QLineEdit()
        self.compartment.setMinimumWidth(450)
        self.compartment.setPlaceholderText('Resource compartment OCID · optional')
        self.compartment.setClearButtonEnabled(True)
        form.addRow('Resource type', self.resource_type)
        form.addRow('Principal compartment', self.compartment)
        layout.addWidget(self.resource_options)
        self.oke_options = QWidget()
        oke = QFormLayout(self.oke_options)
        oke.setContentsMargins(0, 0, 0, 0)
        oke.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.oke = {}
        for key, title in [
            ('namespaces', 'Namespace'),
            ('service_accounts', 'Service account'),
            ('cluster_ids', 'Cluster OCID'),
        ]:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setMinimumWidth(340)
            combo.addItem('')
            combo.currentTextChanged.connect(self._schedule)
            self.oke[key] = combo
            oke.addRow(title, combo)
        layout.addWidget(self.oke_options)
        self.status = label('No snapshot loaded', 'muted')
        layout.addWidget(self.status)
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
        self.statements = StatementTable(
            (
                ('Policy', 'policy_name'),
                ('Compartment', 'compartment_path'),
                ('Valid', 'valid'),
                ('Confidence', 'match_confidence'),
                ('Original statement', 'statement_text'),
            )
        )
        self.statements.setColumnWidth(2, 55)
        self.statements.setColumnWidth(3, 100)
        splitter.addWidget(self.statements)
        splitter.setSizes([230, 430])
        layout.addWidget(splitter, 1)
        layout.addWidget(
            label(
                'Snapshot evidence only · Conditions, residual constraints and match reasons are available in right-click details.',
                'muted',
                wrap=True,
            )
        )
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
            f'{self.statements.proxy.rowCount():,} shown / {self.statements.model.rowCount():,} matching statements · Not a count of distinct resources'
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
