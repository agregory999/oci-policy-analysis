"""Standalone Qt usage analytics over existing read models and aggregations."""

import argparse
import json
import threading
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QDate, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.analytics.aggregator import (
    compute_ai_assist_summary,
    compute_mcp_tool_summary,
    compute_operation_summaries,
    compute_overview_metrics,
    compute_subtab_usage_metrics,
    compute_tab_usage_metrics,
    compute_tenancy_metrics,
    compute_web_traffic_summary,
)
from oci_policy_analysis.analytics.loader import get_analytics_par_base_url, load_usage_report
from oci_policy_analysis.analytics.model import UsageDoc
from oci_policy_analysis.presentation.qt.icons import application_icon
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.themes import apply_theme
from oci_policy_analysis.presentation.qt.widgets import label


class AnalyticsWorker(QThread):
    """Read the bucket or local JSON files off the GUI thread.

    Args:
        base_url: Runtime-only read/list PAR; never persisted or logged.
        dates: Inclusive date bounds, or (None, None) for all history.
        files: Explicit local usage JSON files, or no files for bucket loading.
        parent: Window retaining the worker until finished.
    """

    completed = Signal(object, str)
    failed = Signal(str)

    def __init__(self, base_url, dates, files, parent):
        super().__init__(parent)
        self.base_url, self.dates, self.files = base_url, dates, files
        self.cancelled = threading.Event()

    def run(self):
        """Read compatible documents and report partial coverage explicitly."""
        try:
            if self.files:
                docs, skipped = [], 0
                for path in self.files:
                    if self.cancelled.is_set():
                        return
                    try:
                        raw = json.loads(Path(path).read_text(encoding='utf-8'))
                        records = raw if isinstance(raw, list) else [raw]
                        for record in records:
                            doc = UsageDoc.from_dict(record, tenancy_suffix=None)
                            if doc:
                                docs.append(doc)
                            else:
                                skipped += 1
                    except (OSError, ValueError, TypeError):
                        skipped += 1
                message = f'Local files: {len(docs)} valid runs; {skipped} malformed records/files skipped.'
            else:
                result = load_usage_report(*self.dates, base_url=self.base_url, cancelled=self.cancelled)
                docs = result.docs
                message = f'Bucket: {len(docs)} valid runs / {result.listed} listed objects; {result.skipped} unreadable/malformed objects skipped.'
            if not self.cancelled.is_set():
                self.completed.emit(docs, message)
        except Exception:
            self.failed.emit(
                'Unable to load usage data. Check the read/list PAR, expiry, listing permission and connection. Previous results retained.'
            )


class AnalyticsWindow(QMainWindow):
    """Inspect usage data read-only, independently of the policy workbench.

    Args:
        days: Initial inclusive UTC date window, or zero for all history.

    Attributes:
        docs: Last successfully read compatible usage documents.
        worker: Retained background reader; close waits for cancellation to finish.
    """

    def __init__(self, days: int = 30):
        super().__init__()
        self.docs, self.worker = [], None
        self._closing = False
        self.setWindowTitle('OCI Policy Analysis · Usage Analytics')
        self.setWindowIcon(application_icon())
        self.resize(1280, 850)
        self.setMinimumSize(950, 650)
        self.setStyleSheet(apply_theme('Light', 13, 'Forest'))
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(label('Usage Analytics', 'heading'))
        layout.addWidget(
            label(
                'Read-only bucket viewer · legacy and Qt usage documents · no tracking is published by this viewer',
                wrap=True,
            )
        )
        self.endpoint = QLineEdit(get_analytics_par_base_url() or '')
        self.endpoint.setEchoMode(QLineEdit.EchoMode.Password)
        self.endpoint.setPlaceholderText('Read/list PAR base URL, or set OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL')
        layout.addWidget(self.endpoint)
        controls = QHBoxLayout()
        self.start, self.end = QDateEdit(), QDateEdit()
        today = QDate.fromString(datetime.now(UTC).date().isoformat(), 'yyyy-MM-dd')
        for edit in (self.start, self.end):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat('yyyy-MM-dd')
        self.start.setDate(today.addDays(-max(0, days - 1)))
        self.end.setDate(today)
        self.all_history = QCheckBox('All history')
        self.all_history.setChecked(days == 0)
        self.load_button = QPushButton('Load bucket')
        self.local_button = QPushButton('Open usage JSON…')
        self.export_button = QPushButton('Export filtered runs…')
        for widget in (self.start, self.end, self.all_history, self.load_button, self.local_button, self.export_button):
            controls.addWidget(widget)
        layout.addLayout(controls)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Filter run ID, version, interface, runtime or tenancy suffix')
        self.interface = QComboBox()
        self.interface.addItems(['All interfaces', 'qt', 'unknown'])
        self.unknown = QCheckBox('Include unknown tenancy')
        self.unknown.setChecked(True)
        for widget in (self.search, self.interface, self.unknown):
            filters.addWidget(widget)
        layout.addLayout(filters)
        self.summary = label('Load a bucket or open exported usage JSON files to begin.', wrap=True)
        layout.addWidget(self.summary)
        splitter = QSplitter()
        self.tabs = QTabWidget()
        self.tables = {}
        definitions = {
            'Runs': (
                ('Started (UTC)', 'started'),
                ('Ended (UTC)', 'ended'),
                ('Version', 'version'),
                ('Interface', 'interface'),
                ('Tenancy suffix', 'tenancy'),
                ('Run ID', 'run_id'),
            ),
            'Overview': (('Metric', 'metric'), ('Value', 'value')),
            'Daily activity': (('Day (UTC)', 'key'), ('Runs', 'count')),
            'Versions & runtime': (('Category', 'category'), ('Value', 'key'), ('Runs', 'count')),
            'Tenancies': (('Suffix', 'key'), ('Runs', 'count'), ('First seen', 'first'), ('Last seen', 'last')),
            'Features': (('Page', 'key'), ('Subview', 'subview'), ('Visits', 'count')),
            'Operations': (('Operation', 'key'), ('Count', 'count')),
            'MCP': (('Tool', 'key'), ('Calls', 'count'), ('Success', 'success'), ('Failure', 'failure')),
            'Web': (('Route', 'key'), ('Status', 'status'), ('Calls', 'count'), ('Avg duration (ms)', 'duration')),
            'AI': (('Metric', 'key'), ('Value', 'count')),
        }
        for name, columns in definitions.items():
            table = RecordTable(columns)
            self.tables[name] = table
            self.tabs.addTab(table, name)
            table.details_requested.connect(self._inspect)
        self.tables['Runs'].selectionModel().selectionChanged.connect(self._run_selected)
        splitter.addWidget(self.tabs)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Select a run or right-click a row to inspect its JSON.')
        splitter.addWidget(self.details)
        splitter.setSizes([900, 300])
        layout.addWidget(splitter, 1)
        self.status = label('PAR URLs stay in memory and are never written to settings.', wrap=True)
        layout.addWidget(self.status)
        self.setCentralWidget(content)
        self.load_button.clicked.connect(self.load_bucket)
        self.local_button.clicked.connect(self._open_local)
        self.export_button.clicked.connect(self._export)
        self.search.textChanged.connect(self.render)
        self.interface.currentIndexChanged.connect(self.render)
        self.unknown.toggled.connect(self.render)
        self.all_history.toggled.connect(self._controls)
        self.all_history.toggled.connect(self.render)
        self.start.dateChanged.connect(self.render)
        self.end.dateChanged.connect(self.render)
        self._controls()

    def _controls(self):
        busy = self.worker is not None
        for widget in (self.endpoint, self.load_button, self.local_button, self.all_history):
            widget.setEnabled(not busy)
        for widget in (self.start, self.end):
            widget.setEnabled(not busy and not self.all_history.isChecked())
        self.export_button.setEnabled(bool(self.docs) and not busy)

    def load_bucket(self):
        """Start an explicit bucket read; never auto-load or write usage data."""
        dates = (
            (None, None) if self.all_history.isChecked() else (self.start.date().toPython(), self.end.date().toPython())
        )
        if dates[0] and dates[0] > dates[1]:
            self.status.setText('Start date must precede end date.')
            return
        if not self.endpoint.text().strip():
            self.status.setText('Enter a read/list PAR URL or configure OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL.')
            return
        self._start(dates, [])

    def _open_local(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Open usage JSON', '', 'JSON (*.json)')
        if files:
            self._start((None, None), files)

    def _start(self, dates, files):
        if self.worker is not None:
            return
        self.worker = AnalyticsWorker(self.endpoint.text().strip(), dates, files, self)
        self.worker.completed.connect(self._loaded)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.status.setText('Reading usage documents…')
        self._controls()
        self.worker.start()

    def _loaded(self, docs, message):
        # A run may be imported from overlapping exports; count it once.
        self.docs = list({doc.run_id: doc for doc in docs}.values())
        self.status.setText(message)
        interfaces = sorted({doc.interface for doc in self.docs})
        previous = self.interface.currentText()
        self.interface.blockSignals(True)
        self.interface.clear()
        self.interface.addItems(['All interfaces', *interfaces])
        self.interface.setCurrentIndex(max(0, self.interface.findText(previous)))
        self.interface.blockSignals(False)
        self.render()

    def _finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self._controls()
        if self._closing:
            self.close()

    def filtered_docs(self):
        """Return the common filtered cohort used by every aggregate and export."""
        query = self.search.text().casefold()
        lower, upper = self.start.date().toPython(), self.end.date().toPython()
        return [
            doc
            for doc in self.docs
            if (
                self.all_history.isChecked()
                or lower <= (doc.ended_at or doc.started_at).astimezone(UTC).date() <= upper
            )
            and (self.unknown.isChecked() or doc.tenancy_suffix not in {None, '', 'unknown'})
            and (self.interface.currentIndex() == 0 or doc.interface == self.interface.currentText())
            and (
                not query
                or query
                in ' '.join(
                    [doc.run_id, doc.app_version, doc.interface, doc.tenancy_suffix or 'unknown', doc.os, doc.python]
                ).casefold()
            )
        ]

    def render(self, *_args):
        """Reuse pure aggregations for legacy and current documents."""
        docs = self.filtered_docs()
        metrics = compute_overview_metrics(docs)
        self.summary.setText(
            f'{len(docs)} of {len(self.docs)} runs · {metrics["distinct_tenancies"]} known tenancy suffixes · {sum(len(doc.events) for doc in docs)} events · {sum(len(doc.operations) for doc in docs)} operations'
        )
        rows = {}
        rows['Runs'] = [
            {
                'started': doc.started_at.astimezone(UTC).isoformat(),
                'ended': doc.ended_at.astimezone(UTC).isoformat() if doc.ended_at else '',
                'version': doc.app_version,
                'interface': doc.interface,
                'tenancy': doc.tenancy_suffix or 'unknown',
                'run_id': doc.run_id,
                'document': asdict(doc),
            }
            for doc in docs
        ]
        rows['Overview'] = [
            {'metric': key, 'value': value} for key, value in metrics.items() if not key.endswith('_distribution')
        ]
        rows['Daily activity'] = [
            {'key': day, 'count': count}
            for day, count in sorted(
                Counter((doc.ended_at or doc.started_at).astimezone(UTC).date().isoformat() for doc in docs).items()
            )
        ]
        rows['Versions & runtime'] = [
            {'category': category, 'key': key, 'count': count}
            for category in ['os', 'python', 'app_version']
            for key, count in metrics[f'{category}_distribution'].most_common()
        ]
        rows['Tenancies'] = [
            {'key': key, 'count': value.run_count, 'first': value.first_seen, 'last': value.last_seen}
            for key, value in compute_tenancy_metrics(docs).items()
        ]
        rows['Features'] = [
            {'key': key, 'subview': '', 'count': value.count} for key, value in compute_tab_usage_metrics(docs).items()
        ]
        rows['Features'] += [
            {'key': key[0], 'subview': key[1], 'count': value.count}
            for key, value in compute_subtab_usage_metrics(docs).items()
        ]
        rows['Operations'] = [{'key': key, 'count': value} for key, value in compute_operation_summaries(docs).items()]
        mcp = compute_mcp_tool_summary(docs)
        rows['MCP'] = [
            {
                'key': key,
                'count': count,
                'success': mcp.success_by_tool.get(key, 0),
                'failure': mcp.failure_by_tool.get(key, 0),
            }
            for key, count in mcp.by_tool.items()
        ]
        web = compute_web_traffic_summary(docs)
        rows['Web'] = [
            {
                'key': key[0],
                'status': key[1],
                'count': count,
                'duration': round(web.avg_duration_ms_by_route_status[key], 1)
                if key in web.avg_duration_ms_by_route_status
                else '',
            }
            for key, count in web.by_route_status.items()
        ]
        ai = compute_ai_assist_summary(docs)
        rows['AI'] = [{'key': key, 'count': value} for key, value in asdict(ai).items()]
        for name, table in self.tables.items():
            table.model.replace(rows[name])
        self.details.clear()

    def _run_selected(self, *_args):
        rows = self.tables['Runs'].selected_records()
        self._inspect(rows[0] if rows else None)

    def _inspect(self, row):
        self.details.setPlainText(
            json.dumps(row.get('document', row), indent=2, ensure_ascii=False, default=str) if row else ''
        )

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export filtered usage runs', 'usage-runs.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(
                    json.dumps([asdict(doc) for doc in self.filtered_docs()], indent=2, default=str), encoding='utf-8'
                )
                self.status.setText('Filtered runs exported.')
            except OSError:
                self.status.setText('Could not write the export. Check file permissions.')

    def closeEvent(self, event):
        """Cancel pending reads and retain the worker until its bounded I/O finishes."""
        if self.worker is not None:
            self._closing = True
            self.worker.cancelled.set()
            self.status.setText('Finishing active read before closing…')
            event.ignore()
        else:
            event.accept()


def main(argv: list[str] | None = None) -> int:
    """Launch the independent Qt analytics viewer without initializing tracking.

    Args:
        argv: Optional arguments; --days 0 selects all history.

    Returns:
        int: Qt application exit code.
    """
    parser = argparse.ArgumentParser(description='Read-only Qt usage analytics')
    parser.add_argument('--days', type=int, default=30)
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication([])
    application.setStyle('Fusion')
    window = AnalyticsWindow(days=max(0, args.days))
    window.show()
    return application.exec()


if __name__ == '__main__':
    raise SystemExit(main())
