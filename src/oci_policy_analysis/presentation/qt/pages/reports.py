"""On-demand native report previews and exports over the current snapshot."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QByteArray, QThread, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.reports_service import ReportsService
from oci_policy_analysis.presentation.qt.widgets import label

logger = get_logger(component='qt.reports')


class ReportWorker(QThread):
    """Retain a snapshot and generate a detached report off the GUI thread.

    Args:
        context: Snapshot exclusively held by the shell's task gate.
        report_id: Shared report catalog identifier.
        parent: Owning Reports page, which retains the thread until finished.
    """

    completed = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, context, report_id: str, parent) -> None:
        super().__init__(parent)
        self.context, self.report_id = context, report_id

    def run(self) -> None:
        """Generate only on explicit request; emit detached export strings."""
        try:
            logger.info('Generating report: %s', self.report_id)
            service = ReportsService(self.context)
            report = deepcopy(service.get_report(self.report_id))
            self.completed.emit(self.context, {'report': report, 'formats': service.export_formats(report)})
        except Exception as exc:
            logger.info('Report failed: %s', self.report_id, exc_info=True)
            self.failed.emit(self.context, str(exc))


class ReportPreview(QTextBrowser):
    """Render report HTML without fetching images, local files or linked pages."""

    def loadResource(self, resource_type, url):
        """Block linked resource loading from source-controlled report text.

        Args:
            resource_type: QTextDocument resource kind requested by Qt.
            url: Resource reference; no scheme is fetched.

        Returns:
            QByteArray: Empty resource data.
        """
        return QByteArray()


class ReportsPage(QWidget):
    """Generate and export snapshot reports with serialized background work.

    Attributes:
        busy_changed: Shell gate for loads, simulation, prospective edits and MCP.
        worker: Retained active report thread; close must wait for completion.
        report: Detached report or None, cleared on snapshot replacement.
    """

    busy_changed = Signal(bool)

    def __init__(self) -> None:
        """Build native, read-only previews without running any report."""
        super().__init__()
        self.context = None
        self.worker = None
        self.report = None
        self.formats = {}
        self.block_reason = ''
        self.catalog = ReportsService.catalog()
        layout = QVBoxLayout(self)
        layout.addWidget(label('Reports', 'eyebrow'))
        layout.addWidget(
            label(
                'Generate a report explicitly, review the snapshot evidence, then export it. Results do not authorize OCI access.',
                'muted',
                wrap=True,
            )
        )
        controls = QHBoxLayout()
        self.report_choice = QComboBox()
        for item in self.catalog:
            self.report_choice.addItem(item['label'], item['id'])
        controls.addWidget(self.report_choice, 1)
        self.run_button = QPushButton('Run report')
        self.run_button.setObjectName('primary')
        self.run_button.clicked.connect(self.run_report)
        controls.addWidget(self.run_button)
        self.format_choice = QComboBox()
        for title, key in [('JSON', 'json'), ('Markdown', 'markdown'), ('Rendered HTML', 'html')]:
            self.format_choice.addItem(title, key)
        self.export_button = QPushButton('Export…')
        self.export_button.clicked.connect(self.export_report)
        layout.addLayout(controls)
        formats = QHBoxLayout()
        formats.addWidget(label('Preview format'))
        formats.addWidget(self.format_choice)
        formats.addStretch()
        formats.addWidget(self.export_button)
        layout.addLayout(formats)
        self.description = label('', 'notice', wrap=True)
        layout.addWidget(self.description)
        self.status = label('Load policy data, then run a report.', 'muted', wrap=True)
        layout.addWidget(self.status)
        self.previews = QStackedWidget()
        self.text_preview = QPlainTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text_preview.setPlaceholderText('No report generated for this snapshot.')
        self.html_preview = ReportPreview()
        self.html_preview.setOpenLinks(False)
        self.html_preview.setOpenExternalLinks(False)
        self.previews.addWidget(self.text_preview)
        self.previews.addWidget(self.html_preview)
        layout.addWidget(self.previews, 1)
        self.report_choice.currentIndexChanged.connect(self._selection_changed)
        self.format_choice.currentIndexChanged.connect(self._refresh_preview)
        self._update_controls()

    def set_context(self, context) -> None:
        """Bind a newly published snapshot and clear older report evidence.

        Args:
            context: Current loaded AppContext, or None before loading.
        """
        self.context = context
        self._clear()
        self.status.setText(
            'Policy data loaded. Run a report when needed.' if context else 'Load policy data, then run a report.'
        )
        self._update_controls()

    def set_block_reason(self, reason: str) -> None:
        """Gate generation while another workflow holds the active snapshot.

        Args:
            reason: User-facing reason, or empty when generation is permitted.
        """
        self.block_reason = reason
        self._update_controls()

    def run_report(self) -> None:
        """Start the selected shared report only when the shell permits it."""
        if not self.run_button.isEnabled() or self.worker is not None:
            return
        self._clear()
        self.status.setText('Generating report…')
        self.worker = ReportWorker(self.context, self.report_choice.currentData(), self)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        self._update_controls()
        self.worker.start()

    def export_report(self) -> None:
        """Export the current immutable preview after an explicit file choice."""
        if not self.report or self.worker is not None:
            return
        key = self.format_choice.currentData()
        extension = {'json': 'json', 'markdown': 'md', 'html': 'html'}[key]
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Export report',
            f'{self.report["report_id"]}-report.{extension}',
            f'{extension.upper()} files (*.{extension})',
        )
        if not path:
            return
        try:
            Path(path).write_text(self.formats[key], encoding='utf-8')
        except OSError as exc:
            self.status.setText(f'Export failed: {exc}')
            return
        self.status.setText(f'Report exported: {path}')

    def _clear(self) -> None:
        self.report, self.formats = None, {}
        self.text_preview.clear()
        self.html_preview.clear()

    def _selection_changed(self) -> None:
        self._clear()
        self.status.setText('Report changed. Run it to generate a new preview.')
        self._update_controls()

    def _update_controls(self) -> None:
        identifier = self.report_choice.currentData()
        message = next(item['description'] for item in self.catalog if item['id'] == identifier)
        missing_permissions = (
            identifier == 'permissions'
            and self.context is not None
            and not getattr(self.context.intelligence, 'permissions_report', {})
        )
        if missing_permissions:
            message += ' Permissions have not been built for this snapshot. Reload with Full intelligence enrichment.'
        self.description.setText(self.block_reason or message)
        self.run_button.setEnabled(
            self.context is not None and self.worker is None and not self.block_reason and not missing_permissions
        )
        self.report_choice.setEnabled(self.worker is None)
        self.export_button.setEnabled(self.report is not None and self.worker is None)

    def _completed(self, context, result) -> None:
        if context is not self.context:
            return
        self.report, self.formats = result['report'], result['formats']
        count = self.report.get('item_count', self.report.get('finding_count', 0))
        counts = self.report.get('counts') or {}
        detail = (
            ', '.join(f'{value} {key}' for key, value in counts.items())
            or f'{count} {self.report.get("item_label", "items").lower()}'
        )
        self.status.setText(
            f'Report complete: {detail}. Source data as of {self.report.get("generated_at") or "not recorded"}.'
        )
        self._refresh_preview()

    def _failed(self, context, message: str) -> None:
        if context is self.context:
            self.status.setText(f'Report failed: {message}')

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self._update_controls()
        self.busy_changed.emit(False)

    def _refresh_preview(self) -> None:
        if not self.report:
            return
        key = self.format_choice.currentData()
        if key == 'html':
            # Use the widget palette for preview; portable HTML exports retain their own styling.
            body = self.formats[key].split('<body>', 1)[1].rsplit('</body>', 1)[0]
            self.html_preview.document().setDefaultStyleSheet(
                'table { border-collapse: collapse; } th, td { padding: 6px; text-align: left; } code, pre { white-space: pre-wrap; }'
            )
            self.html_preview.setHtml(body)
            self.previews.setCurrentWidget(self.html_preview)
        else:
            self.text_preview.setPlainText(self.formats[key])
            self.previews.setCurrentWidget(self.text_preview)
