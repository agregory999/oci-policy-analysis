"""Managed snapshot MCP controls and an optional native Codex conversation."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.presentation.qt.assistant_transcript import AssistantTranscript
from oci_policy_analysis.presentation.qt.codex_client import CodexClient
from oci_policy_analysis.presentation.qt.mcp_host import SnapshotMcpHost
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class McpAssistantPage(QWidget):
    """Operate one loaded snapshot server and an explicitly started Codex client.

    Attributes:
        host: Owned MCP worker, retained until its finished signal.
        client: Native stdio app-server client; inactive until the user connects.
        locked: Whether loading is blocked to protect the served snapshot.
        idle: Emitted when server and child process have both exited.
    """

    locked = Signal(bool)
    idle = Signal()

    def __init__(self, settings: dict) -> None:
        """Build independently usable server and assistant controls without starting either."""
        super().__init__()
        self.settings = settings
        self.context = None
        self._loading = False
        self.host = None
        self.url = ''
        self._host_error = ''
        self._running = False
        self._shutting_down = False
        self.client = CodexClient(self)
        self._pending_text = []
        self._pending_chars = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.snapshot = label('Load a snapshot on Overview before starting MCP.', 'muted', wrap=True)
        layout.addWidget(self.snapshot)
        controls = QHBoxLayout()
        controls.addWidget(label('Port'))
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText('Automatic')
        self.port.setValue(settings.get('mcp_port', 8765))
        self.port.setMinimumWidth(100)
        self.port.setToolTip('Loopback only (127.0.0.1). Automatic selects an available port.')
        self.port.valueChanged.connect(lambda value: self.settings.update(mcp_port=value))
        controls.addWidget(self.port)
        self.start_button = QPushButton('Start MCP')
        self.start_button.setObjectName('primary')
        self.start_button.clicked.connect(self.start_server)
        controls.addWidget(self.start_button)
        self.stop_button = QPushButton('Stop MCP')
        self.stop_button.clicked.connect(self.stop_all)
        controls.addWidget(self.stop_button)
        self.endpoint = QLineEdit()
        self.endpoint.setReadOnly(True)
        self.endpoint.setPlaceholderText('Verified endpoint after startup')
        self.endpoint.setMinimumWidth(160)
        self.endpoint.setMaximumWidth(300)
        controls.addWidget(self.endpoint, 1)
        self.server_status = label('Stopped', 'muted', wrap=True)
        controls.addWidget(self.server_status, 1)
        layout.addLayout(controls)
        split = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.tools = RecordTable((('Tool', 'name'), ('Description', 'description')))
        self.tools.setColumnWidth(0, 230)
        self.tools.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.tabs.addTab(self.tools, 'Available tools')
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.document().setMaximumBlockCount(500)
        self.tabs.addTab(self.events, 'Connection && tool activity')
        split.addWidget(self.tabs)
        assistant = QWidget()
        body = QVBoxLayout(assistant)
        body.setContentsMargins(0, 8, 0, 0)
        connection = QHBoxLayout()
        self.executable = QLineEdit('codex')
        self.executable.setPlaceholderText('Codex executable or absolute path')
        connection.addWidget(self.executable, 1)
        self.connect_button = QPushButton('Connect Codex')
        self.connect_button.clicked.connect(self._connect_codex)
        connection.addWidget(self.connect_button)
        self.disconnect_button = QPushButton('Disconnect')
        self.disconnect_button.clicked.connect(self.client.stop)
        connection.addWidget(self.disconnect_button)
        self.model = QComboBox()
        self.model.setMinimumWidth(190)
        self.model.setPlaceholderText('Model after connection')
        connection.addWidget(self.model)
        body.addLayout(connection)
        self.assistant_status = label('Codex disconnected', 'muted', wrap=True)
        body.addWidget(self.assistant_status)
        body.addWidget(
            label(
                'Sending a question shares your question and returned policy evidence with the selected model.',
                'muted',
                wrap=True,
            )
        )
        self.conversation = AssistantTranscript()
        self.conversation.setReadOnly(True)
        self.conversation.setPlaceholderText('Connect Codex, choose a model, and ask about the served snapshot.')
        body.addWidget(self.conversation, 1)
        row = QHBoxLayout()
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText('For example: Which statements reference the AppWorkers dynamic group?')
        self.question.setMaximumHeight(75)
        row.addWidget(self.question, 1)
        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.send_question)
        row.addWidget(self.send_button)
        self.interrupt_button = QPushButton('Stop answer')
        self.interrupt_button.clicked.connect(self.client.interrupt)
        row.addWidget(self.interrupt_button)
        body.addLayout(row)
        split.addWidget(assistant)
        split.setSizes([210, 490])
        layout.addWidget(split, 1)
        self.client.status.connect(self._assistant_status)
        self.client.activity.connect(self.events.appendPlainText)
        self.client.models.connect(self._models)
        self.client.ready_changed.connect(lambda _: self._update_controls())
        self.client.delta.connect(self._queue_text)
        self.client.turn_finished.connect(self._turn_finished)
        self.client.stopped.connect(self._client_stopped)
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(50)
        self.flush_timer.timeout.connect(self._flush_text)
        self.flush_timer.start()
        self._update_controls()

    @property
    def active(self) -> bool:
        """Whether a listener or child process still needs shutdown."""
        return self.host is not None or self.client.active

    def set_context(self, context) -> None:
        """Bind a newly published snapshot after all previous server activity stops."""
        if self.active:
            raise RuntimeError('Stop embedded MCP and Codex before replacing their snapshot')
        self.context = context
        self._pending_text.clear()
        self._pending_chars = 0
        self.conversation.clear()
        self.question.clear()
        self.tools.model.replace([])
        repo = context.policy_repo
        self.snapshot.setText(
            f'{getattr(repo, "tenancy_name", None) or "Snapshot"} · {len(repo.regular_statements):,} statements'
        )
        self._update_controls()

    def set_loading(self, loading: bool) -> None:
        """Prevent server startup while the controller builds a replacement context."""
        self._loading = loading
        self._update_controls()

    def start_server(self) -> None:
        """Pin the current snapshot and start an optional managed loopback listener."""
        if self.context is None or self.active or self._loading:
            return
        self._shutting_down = False
        self._host_error = ''
        self.url = ''
        self.endpoint.clear()
        self.tools.model.replace([])
        self.host = SnapshotMcpHost(self.context, self.port.value(), self)
        self.host.ready.connect(self._host_ready)
        self.host.failed.connect(self._host_failed)
        self.host.finished.connect(self._host_finished)
        self.locked.emit(True)
        self.server_status.setText('Starting…')
        self.events.appendPlainText('Starting loopback snapshot MCP; reload is locked until it stops.')
        self.host.start()
        self._update_controls()

    def stop_all(self) -> None:
        """Disconnect Codex and stop MCP asynchronously, retaining live worker ownership."""
        self._shutting_down = True
        self.client.stop()
        self._running = False
        if self.host is not None:
            self.server_status.setText('Stopping…')
            self.host.stop()
        self._update_controls()
        self._emit_idle()

    def _host_ready(self, url: str, tools: list) -> None:
        if self._shutting_down:
            return
        self._running = True
        self.url = url
        self.endpoint.setText(url)
        self.tools.model.replace(tools)
        self.server_status.setText('Running · MCP verified')
        self.events.appendPlainText(f'MCP initialized and listed {len(tools)} tools at {url}')
        self._update_controls()

    def _host_failed(self, message: str) -> None:
        self._host_error = message
        self._running = False
        self.server_status.setText(f'Failed: {message}')
        self.events.appendPlainText(f'MCP failed: {message}')
        self.client.stop()
        self._update_controls()

    def _host_finished(self) -> None:
        host, self.host = self.host, None
        if host is not None:
            host.deleteLater()
        self._running = False
        self.url = ''
        self.endpoint.clear()
        self.tools.model.replace([])
        if not self._host_error:
            self.server_status.setText('Stopped')
        self.events.appendPlainText('MCP listener exited.')
        self._update_controls()
        self._emit_idle()

    def _connect_codex(self) -> None:
        if self._running:
            self.model.clear()
            self.conversation.finish_answer()
            self.conversation.append_literal('New Codex session')
            self.client.start(self.url, self.executable.text().strip() or 'codex')
            self._update_controls()

    def _models(self, models: list) -> None:
        self.model.clear()
        for entry in models:
            self.model.addItem(
                entry.get('displayName') or entry.get('model') or entry['id'], entry.get('model') or entry['id']
            )
            if entry.get('isDefault'):
                self.model.setCurrentIndex(self.model.count() - 1)
        self._update_controls()

    def _assistant_status(self, text: str) -> None:
        self.assistant_status.setText(text)
        self._update_controls()

    def send_question(self) -> None:
        """Submit one explicit question and stream its answer into the native viewer."""
        text = self.question.toPlainText().strip()
        if not text or not self.client.ready or self.client.busy:
            return
        if len(text) > 50000:
            self.assistant_status.setText('Question is too long; use at most 50,000 characters.')
            return
        self._flush_text()
        self.conversation.begin_answer(text)
        self.question.clear()
        self.client.send(text, self.model.currentData())
        self._update_controls()

    def _queue_text(self, text: str) -> None:
        if self._pending_chars + len(text) > 256000:
            self.client.stop()
            self.assistant_status.setText('Response stream exceeded the UI buffer; disconnected.')
            return
        self._pending_text.append(text)
        self._pending_chars += len(text)

    def _flush_text(self) -> None:
        if not self._pending_text:
            return
        text = ''.join(self._pending_text)
        self._pending_text.clear()
        self._pending_chars = 0
        self.conversation.append_stream(text)

    def _turn_finished(self, status: str) -> None:
        self._flush_text()
        self.conversation.finish_answer()
        self.conversation.append_literal(f'[{status}]')
        self._update_controls()

    def _client_stopped(self) -> None:
        self._flush_text()
        self.conversation.finish_answer()
        self._update_controls()
        self._emit_idle()

    def _emit_idle(self) -> None:
        if not self.active:
            self.locked.emit(False)
            self.idle.emit()

    def _update_controls(self) -> None:
        self.start_button.setEnabled(self.context is not None and not self.active and not self._loading)
        self.stop_button.setEnabled(self.active)
        self.port.setEnabled(not self.active)
        self.connect_button.setEnabled(self._running and not self.client.active and not self._shutting_down)
        self.disconnect_button.setEnabled(self.client.active)
        self.executable.setEnabled(not self.client.active)
        self.model.setEnabled(self.client.ready and not self.client.busy)
        self.send_button.setEnabled(
            self._running and self.client.ready and bool(self.model.count()) and not self.client.busy
        )
        self.question.setEnabled(self._running and not self._shutting_down)
        self.interrupt_button.setEnabled(self.client.busy)
