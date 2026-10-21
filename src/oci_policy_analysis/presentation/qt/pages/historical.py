"""Advanced, read-only historical comparison of saved tenancy JSON snapshots."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.cache_service import CacheService
from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService
from oci_policy_analysis.presentation.qt.audit_commands import AuditCommandsDialog
from oci_policy_analysis.presentation.qt.json_view import FieldChanges, JsonTree, json_text
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, label

logger = get_logger(component='qt.historical')


class HistoricalWorker(QThread):
    """Read selected snapshot sources and compare them without touching AppContext.

    Args:
        cache: Existing cache manager, used only for named cache reads.
        sources: Detached baseline/target source descriptors.
        meaningful_only: Omit ephemeral internal IDs from changed-field analysis.
        generation: Owner's selection generation for stale result rejection.
        parent: Owning page retaining this worker until finished.
        include_incomplete: Compare observed incomplete inventories with explicit warnings.
    """

    completed = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, cache, sources, meaningful_only, generation, parent, *, include_incomplete=False):
        super().__init__(parent)
        self.cache, self.sources = cache, deepcopy(sources)
        self.meaningful_only, self.generation = meaningful_only, generation
        self.include_incomplete = include_incomplete

    def run(self) -> None:
        """Load each source once and run the shared section comparison off-thread."""
        try:
            snapshots = []
            for source in self.sources:
                if source['kind'] == 'cache':
                    snapshots.append(self.cache.load_cache_into_local_json(cached_tenancy=source['value']))
                else:
                    snapshots.append(json.loads(Path(source['value']).read_text(encoding='utf-8-sig')))
            result = HistoricalAnalysisService(self.cache).compare_snapshots(
                *snapshots,
                left_name=self.sources[0]['value'],
                right_name=self.sources[1]['value'],
                meaningful_only=self.meaningful_only,
                include_incomplete=self.include_incomplete,
            )
            self.completed.emit(self.generation, result)
        except Exception as exc:
            logger.exception('Historical comparison failed')
            self.failed.emit(self.generation, str(exc))


class HistoricalPage(QWidget):
    """Compare saved caches/files with separate policy and IAM change queues.

    Args:
        cache: Existing cache manager used for listing and read-only snapshot access.

    Attributes:
        busy_changed: Shell gate for competing snapshot work and closing.
        worker: Retained comparison thread, or None while idle.
        result: Current comparison result, cleared whenever source/options change.
    """

    busy_changed = Signal(bool)

    def __init__(self, cache):
        super().__init__()
        self.cache = cache
        self.worker, self.result = None, None
        self.generation = 0
        self.block_reason = ''
        self.selected_change = None
        layout = QVBoxLayout(self)
        options = QWidget()
        option_layout = QVBoxLayout(options)
        form = QFormLayout()
        self.sources = []
        self.file_buttons = []
        for side, title in enumerate(('Baseline (before)', 'Target (after)')):
            row = QHBoxLayout()
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(18)
            row.addWidget(combo, 1)
            button = QPushButton('Open JSON…')
            button.clicked.connect(lambda checked=False, index=side: self.open_file(index))
            row.addWidget(button)
            self.sources.append(combo)
            self.file_buttons.append(button)
            combo.currentIndexChanged.connect(self._invalidate)
            form.addRow(title, row)
        option_layout.addLayout(form)
        actions = QHBoxLayout()
        self.compare_button = QPushButton('Compare snapshots')
        self.compare_button.setObjectName('primary')
        self.compare_button.clicked.connect(self.compare)
        self.refresh_button = QPushButton('Refresh caches')
        self.refresh_button.clicked.connect(self.refresh_caches)
        self.swap_button = QPushButton('Swap')
        self.swap_button.clicked.connect(self.swap_sources)
        for button in (self.compare_button, self.refresh_button, self.swap_button):
            actions.addWidget(button)
        actions.addStretch()
        self.source_section = CollapsibleSection('Snapshots and comparison options', options)
        self.source_section.button.setChecked(True)
        layout.addWidget(self.source_section)
        layout.addLayout(actions)
        self.meaningful = QCheckBox('Ignore ephemeral internal IDs')
        self.meaningful.setChecked(True)
        self.meaningful.setToolTip(
            'Omits entity-level internal_id, stable_key and underscore-prefixed runtime fields; nested JSON and tags remain literal. OCI IDs, conditions, timestamps and array order remain comparable. Original JSON remains available.'
        )
        self.meaningful.toggled.connect(self._invalidate)
        option_layout.addWidget(self.meaningful)
        self.include_incomplete = QCheckBox('Compare incomplete snapshots with warnings')
        self.include_incomplete.setChecked(True)
        self.include_incomplete.setToolTip(
            'Shows differences in observed JSON even when collection reported errors. Missing records are unverified; this does not confirm OCI deletion. Missing sections and incompatible scopes remain unavailable.'
        )
        self.include_incomplete.toggled.connect(self._invalidate)
        option_layout.addWidget(self.include_incomplete)
        option_layout.addWidget(
            label(
                'Changes are from baseline to target. Stable identities align entities; changes to identity keys can appear as removal/addition. Nested arrays retain order. Snapshot differences do not establish effective OCI access.',
                'muted',
                wrap=True,
            )
        )
        self.provenance = QPlainTextEdit()
        self.provenance.setReadOnly(True)
        self.provenance.setMaximumHeight(145)
        self.provenance.hide()
        option_layout.addWidget(self.provenance)
        self.status = label(
            'Choose saved caches or JSON snapshots, then compare. Active tenancy data is unchanged.',
            'notice',
            wrap=True,
        )
        layout.addWidget(self.status)
        self.categories = QTabWidget()
        self.tables, self.searches, self.sections, self.counts = {}, {}, {}, {}
        for category, title in (('policy', 'Policy changes'), ('iam', 'IAM changes')):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            filters = QHBoxLayout()
            search = QLineEdit()
            search.setPlaceholderText('Search changes by title, key or field…')
            search.setClearButtonEnabled(True)
            section = QComboBox()
            section.setMinimumContentsLength(10)
            section.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            filters.addWidget(search, 1)
            filters.addWidget(section)
            panel_layout.addLayout(filters)
            table = RecordTable(
                (('Change', 'action'), ('Section', 'section'), ('Item', 'title'), ('Fields', 'fields')),
                details_title='Inspect JSON change',
            )
            table.details_requested.connect(self._show_record)
            table.doubleClicked.connect(lambda index, view=table: self._show_record(view.record_at(index)))
            table.selectionModel().selectionChanged.connect(lambda *args, key=category: self._selection(key))
            panel_layout.addWidget(table, 1)
            count = label('', 'muted', wrap=True)
            panel_layout.addWidget(count)
            self.tables[category], self.searches[category], self.sections[category], self.counts[category] = (
                table,
                search,
                section,
                count,
            )
            search.textChanged.connect(lambda text, key=category: self._filter(key))
            section.currentIndexChanged.connect(lambda index, key=category: self._filter(key))
            self.categories.addTab(panel, title)
        self.categories.currentChanged.connect(lambda *_: self.inspect(None))
        layout.addWidget(self.categories, 1)
        self.detail_window = QDialog(self)
        self.detail_window.setWindowTitle('Historical JSON change')
        self.detail_window.resize(1080, 740)
        self.detail_window.setMinimumSize(720, 480)
        detail_layout = QVBoxLayout(self.detail_window)
        self.item_title = label('Select a changed item to inspect its JSON.', 'muted', wrap=True)
        detail_layout.addWidget(self.item_title)
        self.inspector = QTabWidget()
        self.changes = FieldChanges()
        field_page = QWidget()
        field_layout = QVBoxLayout(field_page)
        field_layout.addWidget(self.changes, 2)
        values = QHBoxLayout()
        self.field_values = []
        for title in ('Baseline value', 'Target value'):
            column = QVBoxLayout()
            column.addWidget(label(title, 'muted'))
            value = QPlainTextEdit()
            value.setReadOnly(True)
            value.setMaximumHeight(170)
            column.addWidget(value)
            values.addLayout(column)
            self.field_values.append(value)
        field_layout.addLayout(values, 1)
        self.changes.field_selected.connect(self._field_selected)
        self.before, self.after = JsonTree(), JsonTree()
        for widget, title in (
            (field_page, 'Field changes'),
            (self.before, 'Baseline JSON'),
            (self.after, 'Target JSON'),
        ):
            self.inspector.addTab(widget, title)
        detail_layout.addWidget(self.inspector, 1)
        detail_actions = QHBoxLayout()
        expand = QPushButton('Expand fields')
        expand.clicked.connect(self.changes.expandAll)
        collapse = QPushButton('Collapse fields')
        collapse.clicked.connect(self.changes.collapseAll)
        copy_detail = QPushButton('Copy change JSON')
        copy_detail.clicked.connect(self.copy_change)
        close = QPushButton('Close')
        close.clicked.connect(self.detail_window.close)
        for button in (expand, collapse, copy_detail, close):
            detail_actions.addWidget(button)
        audit = QPushButton('Find OCI Audit records…')
        audit.clicked.connect(self.show_audit_commands)
        detail_actions.insertWidget(0, audit)
        detail_layout.addLayout(detail_actions)
        export_row = QHBoxLayout()
        self.inspect_button = QPushButton('Inspect JSON change')
        self.inspect_button.clicked.connect(self.show_details)
        export_row.addWidget(self.inspect_button)
        self.copy_button = QPushButton('Copy change')
        self.copy_button.clicked.connect(self.copy_change)
        self.export_button = QPushButton('Export JSON…')
        self.export_button.clicked.connect(self.export_comparison)
        for button in (self.copy_button, self.export_button):
            export_row.addWidget(button)
        export_row.addStretch()
        layout.addLayout(export_row)
        self.refresh_caches()
        self._controls()

    def show_audit_commands(self):
        """Open a command-only helper scoped to the selected original change."""
        if self.selected_change and self.result:
            AuditCommandsDialog(self.selected_change, self.result.metadata, self).exec()

    def refresh_caches(self) -> None:
        """Refresh saved source choices, preserving selected cache and file inputs."""
        if self.worker is not None:
            return
        try:
            names = CacheService(self.cache).list_caches()
        except Exception as exc:
            self.status.setText(f'Could not list caches: {exc}. Open a JSON snapshot directly instead.')
            names = []
        changed = False
        for combo in self.sources:
            selected = combo.currentData()
            files = [
                combo.itemData(index)
                for index in range(combo.count())
                if (combo.itemData(index) or {}).get('kind') == 'file'
            ]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('Choose a snapshot…', None)
            for name in names:
                combo.addItem(name, {'kind': 'cache', 'value': name})
            for source in files:
                combo.addItem(Path(source['value']).name, source)
            found = next((index for index in range(combo.count()) if combo.itemData(index) == selected), 0)
            combo.setCurrentIndex(found)
            combo.blockSignals(False)
            changed |= combo.currentData() != selected
        if changed:
            self._invalidate()
        self._controls()

    def open_file(self, side: int) -> None:
        """Choose a JSON file without importing it into the active repository."""
        path, _ = QFileDialog.getOpenFileName(self, 'Choose snapshot JSON', '', 'JSON snapshots (*.json)')
        if not path:
            return
        combo = self.sources[side]
        source = {'kind': 'file', 'value': path}
        index = next((index for index in range(combo.count()) if combo.itemData(index) == source), -1)
        if index < 0:
            combo.addItem(Path(path).name, source)
            index = combo.count() - 1
            combo.setItemData(index, path, Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(index)

    def swap_sources(self) -> None:
        """Reverse baseline/target choices and invalidate direction-sensitive results."""
        values = [combo.currentData() for combo in self.sources]
        for combo, source in zip(self.sources, reversed(values), strict=True):
            if source is not None and not any(combo.itemData(i) == source for i in range(combo.count())):
                combo.addItem(Path(source['value']).name, source)
            combo.setCurrentIndex(next((i for i in range(combo.count()) if combo.itemData(i) == source), 0))

    def set_block_reason(self, reason: str) -> None:
        """Gate comparison while another workflow owns snapshot operations."""
        self.block_reason = reason
        self._controls()

    def compare(self) -> None:
        """Start one read-only comparison with retained source choices and options."""
        if not self.compare_button.isEnabled() or self.worker is not None:
            return
        self._invalidate()
        self.status.setText('Reading snapshots and comparing sections…')
        self.worker = HistoricalWorker(
            self.cache,
            [combo.currentData() for combo in self.sources],
            self.meaningful.isChecked(),
            self.generation,
            self,
            include_incomplete=self.include_incomplete.isChecked(),
        )
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self._controls()
        self.worker.start()

    def _invalidate(self, *_args):
        self.generation += 1
        self.result = None
        self.inspect(None)
        self.provenance.clear()
        for category, table in self.tables.items():
            table.model.replace([])
            self.counts[category].setText('No current comparison.')
            combo = self.sections[category]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('All sections', '')
            combo.blockSignals(False)
        self.status.setText('Inputs changed. Compare to generate a new result.')
        self._controls()

    def _controls(self):
        busy = self.worker is not None
        for widget in (
            *self.sources,
            *self.file_buttons,
            self.refresh_button,
            self.swap_button,
            self.meaningful,
            self.include_incomplete,
        ):
            widget.setEnabled(not busy)
        self.compare_button.setEnabled(
            not busy and not self.block_reason and all(combo.currentData() for combo in self.sources)
        )
        self.compare_button.setToolTip(self.block_reason)
        self.export_button.setEnabled(self.result is not None and not busy)
        self.copy_button.setEnabled(self.selected_change is not None)
        self.inspect_button.setEnabled(self.selected_change is not None)

    def _completed(self, generation, result):
        if generation != self.generation:
            return
        self.result = result
        self.source_section.button.setChecked(False)
        meta = result.metadata
        self.provenance.show()
        warning_text = '\n'.join(f'{section}: {reason}' for section, reason in result.section_warnings.items())
        skipped_text = '\n'.join(f'{section}: {reason}' for section, reason in result.skipped_sections.items())
        self.provenance.setPlainText(
            f'Baseline: {result.left_cache}\n{meta.get("baseline", "")}\n\nTarget: {result.right_cache}\n{meta.get("target", "")}\n\nNot compared:\n{skipped_text or "None"}\nWarnings:\n{warning_text or "None"}\nLegacy metadata can leave tenancy identity or load scope unverified.'
        )
        for category, definitions, sections in (
            ('policy', HistoricalAnalysisService.POLICY_SECTIONS, result.policy_sections),
            ('iam', HistoricalAnalysisService.IDENTITY_SECTIONS, result.identity_sections),
        ):
            combo = self.sections[category]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('All sections', '')
            by_key = {section.key: section for section in sections}
            for title, key in definitions:
                section = by_key.get(key)
                summary = f'+{section.added} / −{section.removed} / ~{section.modified}' if section else 'Not compared'
                combo.addItem(f'{title} · {summary}', title)
            combo.blockSignals(False)
            self._filter(category)
        items = [item for section in (*result.policy_sections, *result.identity_sections) for item in section.items]
        summary = ' · '.join(
            f'{sum(item.action == action for item in items)} {action.lower()}'
            for action in ('Added', 'Removed', 'Modified')
        )
        warnings = f' · {len(result.skipped_sections)} sections not compared' if result.skipped_sections else ''
        if not meta.get('tenancy_verified'):
            warnings += ' · Tenancy identity not recorded on both sources'
        if result.section_warnings:
            self.status.setText(
                f'Unverified snapshot differences: {summary}{warnings}. Collection is incomplete; missing records are not confirmed OCI deletions.'
            )
        elif not result.policy_sections and not result.identity_sections:
            self.status.setText(
                'No sections were compared. Review the section reasons; this does not mean there were no changes.'
            )
        else:
            self.status.setText(f'{summary}{warnings}. Select a row for JSON details.')
        self._controls()

    def _filter(self, category):
        self.inspect(None)
        if self.result is None:
            return
        sections = self.result.policy_sections if category == 'policy' else self.result.identity_sections
        selected = self.sections[category].currentData()
        rows = []
        for section in sections:
            if selected and section.section != selected:
                continue
            for item in section.items:
                rows.append(
                    {
                        'action': item.action,
                        'section': item.section,
                        'title': item.title,
                        'fields': ', '.join(change['field'] for change in item.changed_fields or []) or 'Whole item',
                        'change': {
                            **asdict(item),
                            'comparison_warning': self.result.section_warnings.get(section.section, ''),
                        },
                    }
                )
        table = self.tables[category]
        table.model.replace(rows)
        table.proxy.setFilterFixedString(self.searches[category].text())
        skipped = self.result.skipped_sections
        definitions = (
            HistoricalAnalysisService.POLICY_SECTIONS
            if category == 'policy'
            else HistoricalAnalysisService.IDENTITY_SECTIONS
        )
        unavailable = [title for title, _ in definitions if title in skipped]
        reason = (
            skipped.get(selected, '')
            if selected
            else (f'{len(unavailable)} sections unavailable; choose a section for its reason.' if unavailable else '')
        )
        qualification = (
            self.result.section_warnings.get(selected, '')
            if selected
            else (
                'Incomplete collection: differences are unverified.'
                if any(title in self.result.section_warnings for title, _ in definitions)
                else ''
            )
        )
        self.counts[category].setText(
            f'Showing {table.proxy.rowCount()} of {len(rows)} changes.'
            + (f' Not compared: {reason}' if reason else '')
            + (f' {qualification}' if qualification else '')
        )

    def _selection(self, category):
        selected = self.tables[category].selected_records()
        self.inspect(selected[0] if selected else None)

    def inspect(self, record) -> None:
        """Render selected field deltas and original JSON without reparsing policies."""
        self.selected_change = record.get('change') if record else None
        change = self.selected_change or {}
        if not change:
            self.detail_window.hide()
        self.item_title.setToolTip(change.get('comparison_warning', ''))
        self.item_title.setText(
            f'{"UNVERIFIED · " if change.get("comparison_warning") else ""}{change.get("action")} · {change.get("section")} · {change.get("title")}'
            if change
            else 'Select a changed item to inspect its JSON.'
        )
        before_present = bool(change) and change.get('action') != 'Added'
        after_present = bool(change) and change.get('action') != 'Removed'
        self.before.set_json(change.get('old_value'), present=before_present)
        self.after.set_json(change.get('new_value'), present=after_present)
        self.inspector.setTabText(1, 'Baseline JSON' if before_present else 'Baseline · item absent')
        self.inspector.setTabText(2, 'Target JSON' if after_present else 'Target · item absent')
        fields = change.get('changed_fields') or []
        if change and not fields:
            fields = [
                {
                    'field': '$',
                    'path': ['$'],
                    'action': change['action'],
                    'old': change.get('old_value'),
                    'new': change.get('new_value'),
                    'old_present': change['action'] != 'Added',
                    'new_present': change['action'] != 'Removed',
                }
            ]
        self.changes.set_changes(fields)
        self.copy_button.setEnabled(bool(change))
        self.inspect_button.setEnabled(bool(change))

    def _field_selected(self, field):
        for widget, key, presence in zip(
            self.field_values, ('old', 'new'), ('old_present', 'new_present'), strict=True
        ):
            widget.setPlainText(
                json_text(field.get(key), field.get(presence, True))
                if field
                else 'Select a field to read its full value.'
            )

    def _show_record(self, record):
        self.inspect(record)
        if record:
            self.show_details()

    def show_details(self) -> None:
        """Open the resizable JSON inspector for the explicitly selected change."""
        if self.selected_change:
            self.detail_window.show()
            self.detail_window.raise_()

    def copy_change(self) -> None:
        """Copy complete selected change JSON, including full before/after evidence."""
        if self.selected_change:
            QApplication.clipboard().setText(
                json.dumps(self.selected_change, indent=2, ensure_ascii=False, default=str)
            )

    def export_comparison(self) -> None:
        """Export the completed comparison and metadata after an explicit file choice."""
        if self.result is None or self.worker is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export historical comparison', 'historical-comparison.json', 'JSON files (*.json)'
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(asdict(self.result), indent=2, ensure_ascii=False, default=str), encoding='utf-8'
                )
                self.status.setText(f'Comparison exported: {path}')
            except OSError as exc:
                self.status.setText(f'Export failed: {exc}')

    def _failed(self, generation, message):
        if generation == self.generation:
            self.status.setText(f'Comparison failed: {message}')

    def _finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self._controls()
        self.busy_changed.emit(False)
