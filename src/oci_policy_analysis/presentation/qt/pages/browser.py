"""Policy source browser with shared-core filtering and an evidence inspector."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.analysis_service import AnalysisService
from oci_policy_analysis.application.services.prospective_workbench_service import ProspectiveWorkbenchService
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict
from oci_policy_analysis.presentation.qt.tables import StatementTable
from oci_policy_analysis.presentation.qt.widgets import MultiSelectFilter
from oci_policy_analysis.presentation.qt.widgets import label as _label

logger = get_logger(component='qt.pages.browser')


class PolicyBrowserPage(QWidget):
    """Own the policy evidence table and source inspector."""

    details_requested = Signal(object)
    focus_dynamic_group = Signal(dict)

    def __init__(self) -> None:
        """Build an empty browser ready to receive a loaded context."""
        super().__init__()
        self.context = None
        self.include_prospective = False
        self._resetting = False
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(200)
        self.filter_timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter by policy, compartment, or statement text…')
        self.search.setClearButtonEnabled(True)
        self.subject_types = MultiSelectFilter('Subject types')
        self.subject_types.changed.connect(self._apply_dropdown)
        main_filters = QHBoxLayout()
        main_filters.addWidget(self.search, 1)
        main_filters.addWidget(self.subject_types)
        layout.addLayout(main_filters)
        self.filter_toggle = QPushButton('Detailed Filters')
        self.filter_toggle.setCheckable(True)
        layout.addWidget(self.filter_toggle)
        self.filters_panel = self._filter_controls()
        self.filters_panel.hide()
        self.filter_toggle.toggled.connect(self.filters_panel.setVisible)
        layout.addWidget(self.filters_panel)
        layout.addWidget(self._policies_page(), 1)

    def set_context(self, context) -> None:
        """Replace the source model after a successful load."""
        self.context = context
        self.model.replace([])
        self.subject_types.set_values(
            [str(row['subject_type']) for row in context.policy_repo.regular_statements if row.get('subject_type')]
        )
        self.apply_filters()

    def _filter_controls(self) -> QWidget:
        panel = QWidget()
        layout = QGridLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.filters = {}
        fields = [
            ('policy_name', 'Policy name'),
            ('compartment_path', 'Policy compartment'),
            ('subject', 'Subject / group'),
            ('resource', 'Resource'),
            ('permission', 'Permission'),
            ('conditions', 'Condition text'),
            ('effective_path', 'Effective path'),
            ('statement_text', 'Statement text'),
        ]
        for index, (key, title) in enumerate(fields):
            field = QLineEdit()
            field.setPlaceholderText(title)
            field.setToolTip('Core substring filter; separate alternatives with |. Different fields combine with AND.')
            field.returnPressed.connect(self.apply_filters)
            field.textChanged.connect(self._schedule_filters)
            self.filters[key] = field
            layout.addWidget(field, index // 3, index % 3)
        self.effect = QComboBox()
        self.effect.addItems(['All effects', 'allow', 'deny'])
        self.verb = QComboBox()
        self.verb.addItems(['All verbs', 'inspect', 'read', 'use', 'manage'])
        self.validity = QComboBox()
        self.validity.addItems(['All validity', 'Valid', 'Invalid'])
        row = QHBoxLayout()
        for field in (self.effect, self.verb, self.validity):
            row.addWidget(field)
            field.currentIndexChanged.connect(self._apply_dropdown)
        apply = QPushButton('Apply filters')
        apply.clicked.connect(self.apply_filters)
        clear = QPushButton('Reset filters')
        clear.clicked.connect(self.reset_filters)
        row.addWidget(apply)
        row.addWidget(clear)
        layout.addLayout(row, 3, 0, 1, 3)
        self.filter_status = _label('AND between fields · | between alternatives', 'muted', wrap=True)
        layout.addWidget(self.filter_status, 4, 0, 1, 3)
        return panel

    def apply_filters(self) -> None:
        """Search the current repository through AnalysisService, including invalid evidence."""
        self.filter_timer.stop()
        if self.context is None:
            return
        payload = {key: field.text().strip() for key, field in self.filters.items() if field.text().strip()}
        if self.subject_types.selected_values():
            payload['exact_subject_types'] = self.subject_types.selected_values()
        if self.effect.currentIndex():
            payload['action'] = self.effect.currentText()
        if self.verb.currentIndex():
            payload['verb'] = self.verb.currentText()
        if self.validity.currentIndex():
            payload['valid'] = self.validity.currentIndex() == 1
        try:
            result = AnalysisService(self.context).filter_policy_statements_from_payload(payload)
            self.details_requested.emit(None)
            rows = list(result.statements)
            if self.include_prospective and self.context.policy_repo.tenancy_ocid:
                prospects = ProspectiveWorkbenchService(self.context).statement_views()
                rows.extend(
                    AnalysisService(self.context)
                    .filter_policy_statements_subset(
                        filters=build_policy_search_from_dict(payload),
                        statements=prospects,
                    )
                    .statements
                )
            self.model.replace(rows)
            self.filter_status.setText('Filters applied to source statements.')
            self._row_count()
            logger.info(
                'Core browser filter complete: fields=%d matched=%d total=%d',
                len(payload),
                result.matched,
                result.total,
            )
        except Exception:
            logger.exception('Core policy filtering failed')
            self.filter_status.setText('Could not apply filters. See Qt logging for details.')

    def _schedule_filters(self, *_args) -> None:
        if not self._resetting:
            self.filter_timer.start()

    def _apply_dropdown(self, *_args) -> None:
        if not self._resetting:
            self.apply_filters()

    def reset_filters(self) -> None:
        """Clear filters once, cancelling any pending debounced search."""
        self._resetting = True
        try:
            for field in self.filters.values():
                field.clear()
            for combo in (self.effect, self.verb, self.validity):
                combo.setCurrentIndex(0)
            self.search.clear()
            self.subject_types.clear()
        finally:
            self._resetting = False
        self.apply_filters()

    def _policies_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.row_label = _label('No statements loaded', 'muted')
        layout.addWidget(self.row_label)
        self.table = StatementTable()
        self.table.setColumnHidden(2, True)
        self.model = self.table.model
        self.proxy = self.table.proxy
        self.table.details_requested.connect(self.details_requested.emit)
        self.table.focus_dynamic_group.connect(self.focus_dynamic_group.emit)
        layout.addWidget(self.table, 1)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.search.textChanged.connect(self._row_count)
        self.search.textChanged.connect(lambda: self.details_requested.emit(None))
        return page

    def _row_count(self) -> None:
        prospects = sum(bool(row.get('is_prospective')) for row in self.model.records)
        self.row_label.setText(
            f'{self.proxy.rowCount():,} shown · {self.model.rowCount():,} matches · '
            f'{len(self.context.policy_repo.regular_statements) if self.context else 0:,} source statements'
            + (f' · {prospects:,} prospective matches' if self.include_prospective else '')
        )
