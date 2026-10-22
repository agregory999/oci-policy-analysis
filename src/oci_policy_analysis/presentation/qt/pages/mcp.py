"""Managed snapshot MCP, native Codex chat, and external desktop assistants."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.presentation.qt.assistant_launcher import _launch_desktop_assistant
from oci_policy_analysis.presentation.qt.assistant_transcript import AssistantTranscript
from oci_policy_analysis.presentation.qt.claude_client import ClaudeClient
from oci_policy_analysis.presentation.qt.codex_client import CodexClient
from oci_policy_analysis.presentation.qt.mcp_host import SnapshotMcpHost
from oci_policy_analysis.presentation.qt.tables import RecordTable
from oci_policy_analysis.presentation.qt.widgets import label


class McpAssistantPage(QWidget):
    """Operate a snapshot server with embedded CLI chat or external desktop apps.

    Attributes:
        host: Owned MCP worker, retained until its finished signal.
        client: Selected native CLI client; inactive until the user connects.
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
        self._clients = {'codex': CodexClient(self), 'claude': ClaudeClient(self)}
        self.client = self._clients['codex']
        self._selected_provider = 'codex'
        self._cli_provider = 'codex'
        self._cli_paths = {'codex': 'codex', 'claude': 'claude'}
        self._pending_text = []
        self._pending_chars = 0
        self._desktop_paths = {}
        self._desktop_provider = 'claude-desktop'
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
        provider_row = QHBoxLayout()
        provider_row.addWidget(label('Assistant'))
        self.provider = QComboBox()
        self.provider.addItem('Codex · embedded chat', 'codex')
        self.provider.addItem('Claude Desktop · external app', 'claude-desktop')
        self.provider.addItem('ChatGPT Desktop · external app', 'chatgpt-desktop')
        self.provider.addItem('Codex Desktop · external app', 'codex-desktop')
        self.provider.addItem('Claude Code · embedded chat', 'claude')
        provider_row.addWidget(self.provider)
        provider_row.addStretch()
        body.addLayout(provider_row)
        self.assistant_pages = QStackedWidget()
        codex_page = QWidget()
        codex_body = QVBoxLayout(codex_page)
        codex_body.setContentsMargins(0, 0, 0, 0)
        connection = QHBoxLayout()
        self.cli_label = label('Codex CLI')
        connection.addWidget(self.cli_label)
        self.executable = QLineEdit('codex')
        self.executable.setPlaceholderText('Codex executable or absolute path')
        self.executable.setMaximumWidth(260)
        self.executable.setToolTip('Codex CLI only; other assistants use different protocols. No command arguments.')
        connection.addWidget(self.executable)
        self.browse_codex = QPushButton('Browse…')
        self.browse_codex.clicked.connect(
            lambda: self._browse_application(self.executable, self._assistant_name() + ' CLI')
        )
        connection.addWidget(self.browse_codex)
        self.connect_button = QPushButton('Connect Codex')
        self.connect_button.clicked.connect(self._connect_assistant)
        connection.addWidget(self.connect_button)
        self.disconnect_button = QPushButton('Disconnect')
        self.disconnect_button.clicked.connect(lambda: self.client.stop())
        connection.addWidget(self.disconnect_button)
        self.model = QComboBox()
        self.model.setMinimumWidth(190)
        self.model.setPlaceholderText('Model after connection')
        connection.addWidget(self.model)
        connection.addStretch()
        codex_body.addLayout(connection)
        self.assistant_status = label('Codex disconnected', 'muted', wrap=True)
        codex_body.addWidget(self.assistant_status)
        codex_body.addWidget(
            label(
                'Sending a question shares your question and returned policy evidence with the selected model.',
                'muted',
                wrap=True,
            )
        )
        self.conversation = AssistantTranscript()
        self.conversation.setReadOnly(True)
        self.conversation.setPlaceholderText('Connect Codex, choose a model, and ask about the served snapshot.')
        codex_body.addWidget(self.conversation, 1)
        row = QHBoxLayout()
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText('For example: Which statements reference the AppWorkers dynamic group?')
        self.question.setMaximumHeight(75)
        row.addWidget(self.question, 1)
        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.send_question)
        row.addWidget(self.send_button)
        self.interrupt_button = QPushButton('Stop answer')
        self.interrupt_button.clicked.connect(lambda: self.client.interrupt())
        row.addWidget(self.interrupt_button)
        codex_body.addLayout(row)
        self.assistant_pages.addWidget(codex_page)
        desktop_page = QWidget()
        desktop_body = QVBoxLayout(desktop_page)
        desktop_body.setContentsMargins(0, 0, 0, 0)
        self.desktop_help = label(
            'Start MCP above, then chat in your pre-configured desktop app. '
            'Its local MCP connection must match the verified endpoint, including /mcp. '
            'Use a fixed port (default 8765) for an existing configuration; Automatic can choose another port.',
            'muted',
            wrap=True,
        )
        desktop_body.addWidget(self.desktop_help)
        desktop_row = QHBoxLayout()
        desktop_row.addWidget(label('Application'))
        self.desktop_executable = QLineEdit()
        self.desktop_executable.setMaximumWidth(260)
        self.desktop_executable.setPlaceholderText('Automatic, or application / shortcut path')
        self.desktop_executable.setToolTip(
            'Desktop application, without arguments. Windows shortcuts (.lnk) supported.'
        )
        desktop_row.addWidget(self.desktop_executable)
        self.browse_desktop = QPushButton('Browse…')
        self.browse_desktop.clicked.connect(
            lambda: self._browse_application(self.desktop_executable, self._desktop_name())
        )
        desktop_row.addWidget(self.browse_desktop)
        self.launch_desktop = QPushButton('Open Claude Desktop')
        self.launch_desktop.clicked.connect(self._open_desktop)
        desktop_row.addWidget(self.launch_desktop)
        self.copy_endpoint = QPushButton('Copy MCP URL')
        self.copy_endpoint.clicked.connect(lambda: QApplication.clipboard().setText(self.url))
        desktop_row.addWidget(self.copy_endpoint)
        desktop_row.addStretch()
        desktop_body.addLayout(desktop_row)
        self.desktop_status = label(
            'Claude Desktop opens separately and stays open when MCP stops. '
            'This page does not change or verify its MCP configuration.',
            'muted',
            wrap=True,
        )
        desktop_body.addWidget(self.desktop_status)
        desktop_body.addStretch()
        self.assistant_pages.addWidget(desktop_page)
        body.addWidget(self.assistant_pages, 1)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        split.addWidget(assistant)
        split.setSizes([210, 490])
        layout.addWidget(split, 1)
        for client in self._clients.values():
            for signal, handler in (
                (client.status, self._assistant_status),
                (client.activity, self.events.appendPlainText),
                (client.models, self._models),
                (client.delta, self._queue_text),
                (client.turn_finished, self._turn_finished),
            ):
                signal.connect(
                    lambda value, source=client, slot=handler: slot(value) if source is self.client else None
                )
            client.ready_changed.connect(lambda _: self._update_controls())
            client.stopped.connect(self._client_stopped)
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(50)
        self.flush_timer.timeout.connect(self._flush_text)
        self.flush_timer.start()
        self._update_controls()

    @property
    def active(self) -> bool:
        """Whether a listener or child process still needs shutdown."""
        return self.host is not None or any(client.active for client in self._clients.values())

    def set_context(self, context) -> None:
        """Bind a newly published snapshot after all previous server activity stops."""
        if self.active:
            raise RuntimeError('Stop embedded MCP and assistant before replacing their snapshot')
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
        self.host.activity.connect(self.events.appendPlainText)
        self.host.finished.connect(self._host_finished)
        self.locked.emit(True)
        self.server_status.setText('Starting…')
        self.events.appendPlainText('Starting loopback snapshot MCP; reload is locked until it stops.')
        self.host.start()
        self._update_controls()

    def stop_all(self) -> None:
        """Disconnect CLI clients and stop MCP, retaining ownership until workers exit."""
        self._shutting_down = True
        for client in self._clients.values():
            client.stop()
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

    def _connect_assistant(self) -> None:
        provider = self.provider.currentData()
        if self._running and provider in self._clients:
            self.model.clear()
            self.conversation.finish_answer()
            self.conversation.append_literal(f'New {self._assistant_name()} session')
            self.client.start(self.url, self.executable.text().strip() or provider)
            self._update_controls()

    def _provider_changed(self, index: int) -> None:
        if any(client.active for client in self._clients.values()):
            self.provider.blockSignals(True)
            self.provider.setCurrentIndex(self.provider.findData(self._selected_provider))
            self.provider.blockSignals(False)
            return
        provider = self.provider.currentData()
        self._selected_provider = provider
        embedded = provider in self._clients
        self.assistant_pages.setCurrentIndex(0 if embedded else 1)
        if embedded:
            self._cli_paths[self._cli_provider] = self.executable.text()
            self._cli_provider = provider
            self.client = self._clients[provider]
            self.executable.setText(self._cli_paths[provider])
            name = self._assistant_name()
            self.cli_label.setText(f'{name} CLI')
            self.connect_button.setText(f'Connect {name}')
            self.executable.setPlaceholderText(f'{name} CLI executable or absolute path')
            self.executable.setToolTip(f'{name} CLI, without arguments. Uses your CLI login and billing setup.')
            self.conversation.setPlaceholderText(f'Connect {name}, choose a model, and ask about the served snapshot.')
            self.model.clear()
            self.model.setEditable(provider == 'claude')
            self.assistant_status.setText(f'{name} disconnected · Configure login and billing in its CLI first.')
            self._pending_text.clear()
            self._pending_chars = 0
            self.conversation.clear()
        else:
            self._desktop_paths[self._desktop_provider] = self.desktop_executable.text()
            self._desktop_provider = provider
            self.desktop_executable.setText(self._desktop_paths.get(provider, ''))
            name = self._desktop_name()
            self.launch_desktop.setText(f'Open {name}')
            self.desktop_status.setText(
                f'{name} opens separately and stays open when MCP stops. '
                'This page does not change or verify its MCP configuration.'
                + (
                    ' If Codex is included in your ChatGPT app, choose ChatGPT Desktop.'
                    if provider == 'codex-desktop'
                    else ''
                )
            )
        self._update_controls()

    def _assistant_name(self) -> str:
        return 'Claude' if self._cli_provider == 'claude' else 'Codex'

    def _desktop_name(self) -> str:
        return {
            'claude-desktop': 'Claude Desktop',
            'chatgpt-desktop': 'ChatGPT Desktop',
            'codex-desktop': 'Codex Desktop',
        }.get(self.provider.currentData(), 'Desktop assistant')

    def _browse_application(self, field: QLineEdit, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f'Select {name} application or shortcut', field.text())
        if path:
            field.setText(path)

    def _open_desktop(self) -> None:
        provider = self.provider.currentData()
        if not self._running or self._shutting_down or provider in self._clients:
            return
        name = self._desktop_name()
        if _launch_desktop_assistant(provider, self.desktop_executable.text()):
            self.desktop_status.setText(
                f'Launch requested. Continue in {name} and check its MCP tools for {self.url}. '
                'Keep MCP running while chatting.'
            )
        else:
            self.desktop_status.setText(
                f'Could not open {name}. Browse to its installed application or Windows shortcut (.lnk). '
                'You can also open the app yourself and use Copy MCP URL.'
            )

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
        model = self.model.currentData()
        if self.model.isEditable() and self.model.currentText() != self.model.itemText(self.model.currentIndex()):
            model = self.model.currentText().strip()
        if not model:
            self.assistant_status.setText('Choose a model or enter a model ID before sending.')
            return
        self._flush_text()
        self.conversation.begin_answer(text, self._assistant_name())
        self.question.clear()
        self.client.send(text, model)
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
        marker = f'[{status}]'
        if status == 'failed' and self.assistant_status.text():
            # Show the reason inline; a bare [failed] hides why the turn stopped.
            marker = f'{marker} {self.assistant_status.text()}'
        self.conversation.append_literal(marker)
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
        self.browse_codex.setEnabled(not self.client.active)
        self.provider.setEnabled(not self.client.active)
        self.launch_desktop.setEnabled(self._running and not self._shutting_down)
        self.copy_endpoint.setEnabled(self._running and not self._shutting_down)
        self.model.setEnabled(self.client.ready and not self.client.busy)
        self.send_button.setEnabled(
            self._running and self.client.ready and bool(self.model.count()) and not self.client.busy
        )
        self.question.setEnabled(self._running and not self._shutting_down)
        self.interrupt_button.setEnabled(self.client.busy)
