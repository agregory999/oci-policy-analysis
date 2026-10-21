"""Logging controls and a bounded INFO+ UI sink, independent of shell verbosity."""

import logging
import queue

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.presentation.qt.logger_catalog import available_components, declared_components
from oci_policy_analysis.presentation.qt.preferences import save_preferences
from oci_policy_analysis.presentation.qt.widgets import label

QT_COMPONENTS = (
    'qt.main',
    'qt.load',
    'qt.simulation',
    'qt.reports',
    'qt.recommendations',
    'qt.historical',
    'qt.pages.browser',
    'qt.pages.graph',
    'qt.pages.dynamic_groups',
    'qt.mcp',
    'qt.codex',
)
LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')


class _QtHandler(logging.Handler):
    def __init__(self, bridge: 'LogBridge') -> None:
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.pending = queue.Queue(maxsize=5000)
        self.dropped = 0
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(name)s · %(message)s', datefmt='%H:%M:%S'))

    def emit(self, record: logging.LogRecord) -> None:
        """Reject DEBUG before formatting/queueing; never touch widgets here."""
        if record.levelno < logging.INFO or not record.name.startswith(self.bridge.prefix):
            return
        try:
            self.pending.put_nowait(self.format(record))
        except queue.Full:
            self.dropped += 1


class LogBridge(QObject):
    """Batch at most 100 INFO+ records per timer tick into the UI.

    Attributes:
        message: Batched formatted text delivered on the GUI thread.
        prefix: Visible namespace or tuple of namespaces; all components by default.
        handler: INFO+ sink with a bounded 5,000-record pending queue.

    Notes:
        DEBUG continues to the existing shell and file handlers. The GUI timer
        polls every 200 ms; queue overflow is reported rather than blocking loads.
    """

    message = Signal(str)

    def __init__(self, parent: QObject) -> None:
        """Install a window-owned handler and start the batching timer."""
        super().__init__(parent)
        self.prefix = 'oci-policy-analysis.'
        self.handler = _QtHandler(self)
        logging.getLogger().addHandler(self.handler)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.flush)
        self.timer.start()

    def flush(self) -> None:
        """Deliver a bounded batch of pending records without blocking the UI."""
        lines = []
        for _ in range(100):
            try:
                lines.append(self.handler.pending.get_nowait())
                self.handler.pending.task_done()
            except queue.Empty:
                break
        self.handler.acquire()
        try:
            dropped = self.handler.dropped
            self.handler.dropped = 0
        finally:
            self.handler.release()
        if dropped:
            lines.append(
                f'UI buffer full: {dropped} log records omitted. Full output remains in the shell and app.log.'
            )
        if lines:
            self.message.emit('\n'.join(lines))

    def clear(self) -> None:
        """Discard queued UI copies without changing shell or file output."""
        while True:
            try:
                self.handler.pending.get_nowait()
                self.handler.pending.task_done()
            except queue.Empty:
                break

    def close(self) -> None:
        """Stop polling and detach the sink before its widgets are destroyed."""
        self.timer.stop()
        logging.getLogger().removeHandler(self.handler)
        self.handler.close()


class LiveLogView(QFrame):
    """Read-only, bounded INFO+ output for the shell's hideable log dock."""

    def __init__(self, bridge: LogBridge) -> None:
        """Build display controls; keep this viewer usable while a load runs."""
        super().__init__()
        self.bridge = bridge
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(label('Live log · INFO and above'))
        self.scope = QComboBox()
        self.scope.addItems(['All application components', 'Qt components', 'Simulation'])
        self.scope.currentIndexChanged.connect(self._scope_changed)
        row.addWidget(self.scope)
        row.addStretch()
        clear = QPushButton('Clear view')
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        layout.addLayout(row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(2000)
        layout.addWidget(self.output)
        bridge.message.connect(self.output.appendPlainText)

    def _scope_changed(self, index: int) -> None:
        self.bridge.prefix = (
            (
                'oci-policy-analysis.qt.simulation',
                'oci-policy-analysis.application.services.simulation',
                'oci-policy-analysis.core.engine.policy_simulation_engine',
                'oci-policy-analysis.core.policy_corpus',
            )
            if index == 2
            else 'oci-policy-analysis.qt.'
            if index
            else 'oci-policy-analysis.'
        )

    def _clear(self) -> None:
        self.bridge.clear()
        self.output.clear()


class LoggingPanel(QFrame):
    """Compact saved component controls with global reset and an INFO+ UI sink.

    Args:
        settings: Shared settings, including saved component overrides.
        verbose: Whether startup DEBUG is locked for this process.
    """

    show_log_requested = Signal()

    def __init__(self, settings: dict, *, verbose: bool = False) -> None:
        """List declared and active loggers without importing other presentations."""
        super().__init__()
        self.settings = settings
        self.service = LoggingService(settings)
        self.verbose = verbose
        self.levels = {}
        self.runtime = set()
        self.entries = []
        layout = QVBoxLayout(self)
        layout.addWidget(
            label('Global resets every component. DEBUG goes to shell/file; live view remains INFO+.', wrap=True)
        )
        row = QHBoxLayout()
        row.addWidget(label('Global'))
        combo = QComboBox()
        combo.addItems(LEVELS if verbose or settings.get('global_log_level') == 'DEBUG' else LEVELS[1:])
        combo.setCurrentText(settings.get('global_log_level', 'INFO'))
        combo.setEnabled(not verbose)
        self.levels['global'] = combo
        row.addWidget(combo)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find logger…')
        self.search.textChanged.connect(self._filter_rows)
        row.addWidget(self.search, 1)
        refresh = QPushButton('Refresh list')
        refresh.clicked.connect(self.refresh_components)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(250)
        self.scroll.setMaximumHeight(350)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(2, 1)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll)
        row = QHBoxLayout()
        self.apply_button = QPushButton('Apply and save log levels')
        self.apply_button.setEnabled(not verbose)
        self.apply_button.clicked.connect(self.apply_levels)
        row.addWidget(self.apply_button)
        show = QPushButton('Show live log')
        show.clicked.connect(self.show_log_requested.emit)
        row.addWidget(show)
        row.addStretch()
        layout.addLayout(row)
        self.effective = label(
            '--verbose active: DEBUG locked for this session.' if verbose else 'Saved preferences apply at startup.',
            'muted',
            wrap=True,
        )
        layout.addWidget(self.effective)
        self.refresh_components()
        combo.currentTextChanged.connect(self._reset_components)

    def refresh_components(self) -> None:
        """Add newly registered loggers and reflow two compact label/level columns."""
        prefix = 'oci-policy-analysis.'
        canonical = self.service.get_log_settings()['log_levels']
        for name in available_components({'log_levels': canonical}):
            if name in self.levels or name == 'oci-policy-analysis':
                continue
            runtime = (
                name in logging.root.manager.loggerDict
                and not name.startswith(prefix)
                and name not in declared_components()
            )
            if runtime:
                self.runtime.add(name)
            full_name = name if runtime else prefix + name
            combo = QComboBox(self.content)
            combo.setObjectName('logLevel')
            combo.addItems(LEVELS)
            saved = self.settings.get('qt_runtime_log_levels', {}) if runtime else canonical
            level = saved.get(name, logging.getLevelName(logging.getLogger(full_name).getEffectiveLevel()))
            combo.setCurrentText(
                'DEBUG' if self.verbose else level if level in LEVELS else self.levels['global'].currentText()
            )
            combo.setEnabled(not self.verbose)
            title = label(name)
            title.setParent(self.content)
            title.setToolTip(full_name)
            combo.setAccessibleName(f'{name} log level')
            self.levels[name] = combo
            self.entries.append((name, title, combo))
        self.entries.sort(key=lambda entry: entry[0])
        self._filter_rows()

    def _filter_rows(self, *_args) -> None:
        while self.grid.count():
            self.grid.takeAt(0)
        visible = 0
        query = self.search.text().casefold()
        for name, title, combo in self.entries:
            match = query in name.casefold()
            title.setVisible(match)
            combo.setVisible(match)
            if match:
                self.grid.addWidget(title, visible // 2, visible % 2 * 2)
                self.grid.addWidget(combo, visible // 2, visible % 2 * 2 + 1)
                visible += 1

    def _reset_components(self, level: str) -> None:
        self.refresh_components()
        for name, combo in self.levels.items():
            if name != 'global':
                combo.setCurrentText(level)

    def apply_levels(self) -> None:
        """Apply levels and persist preferences without saving startup --verbose."""
        if self.verbose:
            return
        levels = {
            name: combo.currentText()
            for name, combo in self.levels.items()
            if name != 'global' and name not in self.runtime
        }
        self.service.update_log_settings(
            {'global_log_level': self.levels['global'].currentText(), 'clear_log_levels': True, 'log_levels': levels},
            verbose_override=False,
        )
        runtime = {name: self.levels[name].currentText() for name in self.runtime}
        for name, level in runtime.items():
            logging.getLogger(name).setLevel(level)
        self.settings['qt_runtime_log_levels'] = runtime
        try:
            save_preferences(self.settings, ('global_log_level', 'log_levels', 'qt_runtime_log_levels'))
            self.effective.setText(f'Global: {self.levels["global"].currentText()} · Saved · Live view: INFO+ only')
        except OSError as exc:
            self.effective.setText(f'Applied for this session. {exc}')
        get_logger(component='qt.main').info('Qt logging preferences applied; UI remains INFO+')
