"""Policy source browser with shared-core filtering and an evidence inspector."""

import json

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.analysis_service import AnalysisService
from oci_policy_analysis.application.services.prospective_workbench_service import ProspectiveWorkbenchService
from oci_policy_analysis.application.services.search_builders import (
    build_policy_search_from_dict,
    build_policy_search_from_saved_search,
)
from oci_policy_analysis.presentation.qt.preferences import load_preferences, save_preferences
from oci_policy_analysis.presentation.qt.tables import BrowserStatementModel, StatementTable
from oci_policy_analysis.presentation.qt.widgets import MultiSelectFilter
from oci_policy_analysis.presentation.qt.widgets import label as _label

logger = get_logger(component='qt.pages.browser')


class PolicyBrowserPage(QWidget):
    """Own the policy evidence table and source inspector."""

    details_requested = Signal(object)
    focus_dynamic_group = Signal(dict)

    def __init__(self, settings=None) -> None:
        """Build an empty browser ready to receive a loaded context."""
        super().__init__()
        self.context = None
        self.settings = settings if settings is not None else {}
        self.include_prospective = False
        self._resetting = False
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(200)
        self.filter_timer.timeout.connect(self.apply_filters)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter by policy, compartment, effective path, or statement text…')
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
        saved_row = QHBoxLayout()
        self.saved_searches = QComboBox()
        self.saved_searches.setMinimumContentsLength(18)
        saved_row.addWidget(self.saved_searches, 1)
        restore = QPushButton('Restore search')
        restore.clicked.connect(self.restore_search)
        save = QPushButton('Save search…')
        save.clicked.connect(self.prompt_save_search)
        for button in (restore, save):
            saved_row.addWidget(button)
        layout.addLayout(saved_row)
        self.refresh_saved_searches()
        layout.addWidget(self._policies_page(), 1)

    def set_context(self, context) -> None:
        """Replace the source model after a successful load."""
        self.context = context
        self.model.replace([])
        self.subject_types.set_values(
            [str(row['subject_type']) for row in context.policy_repo.regular_statements if row.get('subject_type')]
        )
        self.refresh_saved_searches()
        self.apply_filters()

    def search_payload(self) -> dict:
        """Return field filters or a validated complete JSON override."""
        if self.raw_filters.toPlainText().strip():
            try:
                payload = json.loads(self.raw_filters.toPlainText())
            except ValueError as exc:
                raise ValueError('Invalid JSON filter override. Supply an object of search filters.') from exc
            if not isinstance(payload, dict):
                raise ValueError('JSON filter override must be an object.')
            return payload
        payload = {key: field.text().strip() for key, field in self.filters.items() if field.text().strip()}
        if self.effect.currentIndex():
            payload['action'] = self.effect.currentText()
        if self.verb.currentIndex():
            payload['verb'] = self.verb.currentText()
        if self.subject_types.selected_values():
            payload['exact_subject_types'] = self.subject_types.selected_values()
        if self.validity.currentIndex():
            payload['valid'] = self.validity.currentIndex() == 1
        return payload

    def refresh_saved_searches(self):
        """Read searches saved by all interfaces without changing current filters."""
        selected = self.saved_searches.currentText()
        self.saved_searches.clear()
        self.saved_searches.addItem('Choose a saved search…', None)
        records = load_preferences().get('saved_policy_searches', [])
        for record in records:
            if isinstance(record, dict) and record.get('name'):
                self.saved_searches.addItem(str(record['name']), record)
        index = self.saved_searches.findText(selected)
        if index >= 0:
            self.saved_searches.setCurrentIndex(index)

    def restore_search(self):
        """Restore the shared filter payload, including fields without native controls."""
        record = self.saved_searches.currentData()
        if not record:
            return
        self.reset_filters()
        try:
            filters = build_policy_search_from_saved_search(record)
        except ValueError as exc:
            self.filter_status.setText(f'Cannot restore saved search: {exc}')
            return
        self.raw_filters.setPlainText(json.dumps(filters, indent=2))
        self.search.setText((record.get('qt_view') or {}).get('search', ''))
        self.filter_toggle.setChecked(True)
        self.apply_filters()

    def save_named_search(self, name: str, *, overwrite=False) -> bool:
        """Persist a named shared search while preserving other interfaces' metadata."""
        name = name.strip()
        if not name:
            raise ValueError('Enter a search name.')
        records = load_preferences().get('saved_policy_searches', [])
        old = next((record for record in records if record.get('name') == name), None)
        if old and not overwrite:
            return False
        filters = build_policy_search_from_dict(self.search_payload())
        record = {
            **(old or {}),
            'raw_json': json.dumps(filters),
            'name': name,
            'filters': filters,
            'qt_view': {'search': self.search.text()},
        }
        records = [record if entry.get('name') == name else entry for entry in records]
        if old is None:
            records.append(record)
        self.settings['saved_policy_searches'] = records
        save_preferences(self.settings, ('saved_policy_searches',))
        self.refresh_saved_searches()
        self.saved_searches.setCurrentIndex(self.saved_searches.findText(name))
        self.filter_status.setText(f'Search saved: {name}')
        return True

    def prompt_save_search(self):
        """Ask for a name and explicit replacement of an existing saved search."""
        name, accepted = QInputDialog.getText(self, 'Save policy search', 'Search name')
        if not accepted:
            return
        try:
            if (
                not self.save_named_search(name)
                and QMessageBox.question(self, 'Replace search', f'Replace the saved search “{name}”?')
                == QMessageBox.StandardButton.Yes
            ):
                self.save_named_search(name, overwrite=True)
        except (ValueError, OSError) as exc:
            self.filter_status.setText(str(exc))

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
            ('policy_ocid', 'Policy OCID (exact)'),
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
        layout.addLayout(row, 4, 0, 1, 3)
        self.filter_status = _label('AND between fields · | between alternatives', 'muted', wrap=True)
        layout.addWidget(self.filter_status, 5, 0, 1, 3)
        self.raw_filters = QPlainTextEdit()
        self.raw_filters.setPlaceholderText(
            'Optional JSON filter override, e.g. {"principal_keys": ["group:default/admins"], "tag_namespace": ["Team"], "condition_atom_terms": ["request.operation"]}'
        )
        self.raw_filters.setMaximumHeight(90)
        self.raw_filters.setToolTip(
            'An object of shared search filters. Overrides the fields above; supports structured principals, tag operators/semantics, metadata tags and condition atoms. Main text search still filters the displayed rows.'
        )
        self.raw_filters.textChanged.connect(self._schedule_filters)
        layout.addWidget(_label('Advanced JSON filter override (optional)', 'muted'), 6, 0, 1, 3)
        layout.addWidget(self.raw_filters, 7, 0, 1, 3)
        return panel

    def apply_filters(self) -> None:
        """Search the current repository through AnalysisService, including invalid evidence."""
        self.filter_timer.stop()
        if self.context is None:
            return
        try:
            payload = self.search_payload()
        except ValueError as exc:
            self.filter_status.setText(str(exc))
            self.model.replace([])
            self._row_count()
            return
        if self.subject_types.selected_values():
            payload['exact_subject_types'] = self.subject_types.selected_values()
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
            self.raw_filters.clear()
            for field in self.filters.values():
                field.clear()
            for combo in (self.effect, self.verb, self.validity):
                combo.setCurrentIndex(0)
            self.search.clear()
            self.subject_types.clear()
        finally:
            self._resetting = False
        self.apply_filters()

    def focus_policy(self, policy: dict) -> None:
        """Show source statements for one inventory policy and compartment."""
        self._resetting = True
        try:
            self.raw_filters.clear()
            for field in self.filters.values():
                field.clear()
            for combo in (self.effect, self.verb, self.validity):
                combo.setCurrentIndex(0)
            self.search.clear()
            self.subject_types.clear()
        finally:
            self._resetting = False
        if policy.get('policy_ocid'):
            self.filters['policy_ocid'].setText(str(policy['policy_ocid']))
        else:
            self.filters['policy_name'].setText(str(policy.get('policy_name') or ''))
            self.filters['compartment_path'].setText(str(policy.get('compartment_path') or ''))
        self.apply_filters()

    def _policies_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        counts = QHBoxLayout()
        self.row_label = _label('No statements loaded', 'muted', wrap=False)
        counts.addWidget(self.row_label)
        counts.addStretch()
        self.invalid_legend = _label('Invalid rows are italic/red · right-click for details.', 'muted', wrap=False)
        counts.addWidget(self.invalid_legend)
        layout.addLayout(counts)
        columns = (
            ('Policy Path', 'policy_display'),
            ('Effective path', 'effective_path'),
            ('Original statement', 'statement_text'),
        )
        self.table = StatementTable(columns, source_model=BrowserStatementModel(columns, None))
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 230)
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
        invalid = sum(
            bool((record := self.table.record_at(self.proxy.index(row, 0))) and record.get('valid') is False)
            for row in range(self.proxy.rowCount())
        )
        self.row_label.setText(
            f'{self.proxy.rowCount():,} shown · {self.model.rowCount():,} matched · {invalid:,} invalid'
        )
