"""Combined overview, load settings, and collapsible logging controls."""

import configparser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.services.cache_service import CacheService
from oci_policy_analysis.application.services.load_service import LoadResult
from oci_policy_analysis.presentation.qt.preferences import save_preferences
from oci_policy_analysis.presentation.qt.profiles import profile_names
from oci_policy_analysis.presentation.qt.settings_panels import AppearancePanel, IntelligencePanel
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection, SegmentedControl
from oci_policy_analysis.presentation.qt.widgets import label as _label


class OverviewSettingsPage(QScrollArea):
    """Own loading inputs and snapshot overview; emit requests to the controller."""

    load_requested = Signal(str, dict, str)
    browse_requested = Signal()

    show_log_requested = Signal()
    usage_changed = Signal(bool)

    def __init__(self, logging_panel: QWidget, settings: dict, experience=None) -> None:
        """Restore the selected load source and start with settings sections collapsed."""
        super().__init__()
        self.settings = settings
        # Load lifecycle flags keep controls and status text in sync with the
        # worker and embedded MCP lock without replacing the active snapshot.
        self._responsive_rows = []
        self._busy = False
        self._load_locked = False
        self._load_preferences_dirty = False
        self._loaded_connection_signature = None
        self._loaded_status = 'Not loaded'
        self.preference_timer = QTimer(self)
        self.preference_timer.setSingleShot(True)
        self.preference_timer.setInterval(300)
        self.preference_timer.timeout.connect(self.save_load_preferences)
        self.cache_service = CacheService(CacheManager())
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName('settingsContent')
        layout = QVBoxLayout(content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        if experience is not None:
            mode = QFrame()
            mode.setObjectName('card')
            controls = QVBoxLayout(mode)
            self.advanced_mode = QCheckBox('Advanced mode')
            self.advanced_mode.setChecked(experience.advanced)
            self.advanced_mode.setAccessibleDescription(
                'Show MCP & assistant, prospective statements, simulation, tag-based policies, consolidation and advanced tools.'
            )
            self.advanced_mode.toggled.connect(experience.set_advanced)
            experience.changed.connect(self.advanced_mode.setChecked)
            controls.addWidget(self.advanced_mode)
            controls.addWidget(
                _label(
                    'Standard mode keeps everyday browsing and recommendations easy to find. Enable advanced mode for MCP & assistant, what-if policy editing, simulation, tag-based policies, consolidation and maintenance. You can switch back without reloading data.',
                    'muted',
                    wrap=True,
                )
            )
            self.mode_status = _label('', 'muted')
            experience.status.connect(self.mode_status.setText)
            controls.addWidget(self.mode_status)
            layout.addWidget(mode)
        layout.addWidget(self._load_controls())
        if experience is not None:
            experience.bind_advanced(self.policy_loading_controls)
            experience.bind_advanced(self.recursive)
            experience.bind_advanced(self.load_all_users)
        else:
            self.policy_loading_controls.hide()
            self.recursive.hide()
            self.load_all_users.hide()
        for signal in (
            self.profile.currentTextChanged,
            self.auth.currentIndexChanged,
            self.recursive.toggled,
            self.load_all_users.toggled,
            self.depth.valueChanged,
            self.policy_load_method.currentIndexChanged,
            self.source_selector.currentIndexChanged,
        ):
            signal.connect(self._load_preferences_changed)
        # Snapshot details live under a persistent status header so load state
        # remains visible even before or between successful loads.
        self.active_data_card = self._active_data_card()
        layout.addWidget(self.active_data_card)
        self.results = self._overview_page()
        self.results.hide()
        self.active_data_layout.addWidget(self.results)
        layout.addWidget(self._separator())
        layout.addWidget(_label('Additional Settings', 'eyebrow'))
        self.logging_panel = logging_panel
        self.intelligence_panel = IntelligencePanel(settings)
        self.appearance_panel = AppearancePanel(settings)
        self.sections = {}
        for name, panel in [
            ('Logging', logging_panel),
            ('Intelligence', self.intelligence_panel),
            ('Look and Feel', self.appearance_panel),
        ]:
            section = CollapsibleSection(name, panel)
            self.sections[name] = section
            layout.addWidget(section)
        logging_panel.show_log_requested.connect(self.show_log_requested.emit)
        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        self.usage_tracking = QCheckBox('Publish anonymous usage data')
        self.usage_tracking.setChecked(settings.get('usage_tracking_enabled', True))
        privacy_layout.addWidget(self.usage_tracking)
        self.usage_notice = _label(
            'Enabled by default. Publishes app version, OS/Python version, timestamps, feature usage, '
            'inventory counts and the last six tenancy OCID characters to the project usage bucket. '
            'No policy text, names, full OCIDs, search text, prompts or credentials are included. '
            'Best-effort uploads occur on exit or tenancy change. Turn off to discard pending usage data.',
            wrap=True,
        )
        privacy_layout.addWidget(self.usage_notice)
        self.usage_tracking.toggled.connect(self.usage_changed.emit)
        self.sections['Usage tracking'] = CollapsibleSection('Usage tracking', privacy)
        layout.addWidget(self.sections['Usage tracking'])
        layout.addStretch()
        self.setWidget(content)

    def _load_controls(self) -> QWidget:
        """Build the source switch and controls for each supported input type."""
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(_label('Load data', 'eyebrow'))
        # One selector swaps the four source-specific panels below it.
        self.source_keys = ('oci', 'snapshot', 'compliance', 'sample')
        self.source_selector = SegmentedControl(['Live Tenancy', 'Local Snapshot', 'CIS Import', 'Sample'])
        layout.addWidget(self.source_selector)
        self.source_panels = [QWidget() for _ in self.source_keys]
        for panel in self.source_panels:
            layout.addWidget(panel)
        live = QVBoxLayout(self.source_panels[0])
        live.setContentsMargins(0, 8, 0, 0)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        live.addLayout(grid)
        # Authentication controls occupy the first row; the six-column grid
        # keeps both selectors aligned when the page is resized.
        self.auth = QComboBox()
        for title, mode in [
            ('OCI config profile', 'profile'),
            ('Instance principal', 'instance_principal'),
        ]:
            self.auth.addItem(title, mode)
        self.profile = QComboBox()
        self.profile.setEditable(True)
        try:
            self.profile.addItems(profile_names())
        except (OSError, configparser.Error) as exc:
            self.profile.addItem('DEFAULT')
            self.profile.setToolTip(f'Could not read OCI profiles: {exc}. Enter a profile name manually.')
        self.profile.setCurrentText(str(self.settings.get('named_profile') or 'DEFAULT'))
        mode = self.settings.get('qt_auth_mode')
        if self.settings.get('instance_principal', False):
            mode = 'instance_principal'
        elif mode != 'profile':
            mode = 'profile'
        self.auth.setCurrentIndex(self.auth.findData(mode))
        self.profile.setEnabled(mode == 'profile')
        self.auth.currentIndexChanged.connect(lambda index: self.profile.setEnabled(index == 0))
        self.profile.setMinimumWidth(160)
        grid.addWidget(_label('Authentication'), 0, 0)
        grid.addWidget(self.auth, 0, 1, 1, 2)
        grid.addWidget(_label('Profile'), 0, 3)
        grid.addWidget(self.profile, 0, 4, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(4, 1)
        grid.setColumnStretch(5, 1)

        # Scope controls share the second row. The two checkboxes are advanced
        # options, while domain depth remains available in Standard mode.
        self.recursive = QCheckBox('All compartments')
        self.recursive.setChecked(bool(self.settings.get('recursive', True)))
        self.recursive.setToolTip('Include the tenancy root and all child compartments.')
        self.load_all_users = QCheckBox('Load all users')
        self.load_all_users.setChecked(bool(self.settings.get('load_all_users', True)))

        self.depth = QSpinBox()
        self.depth.setRange(1, 6)
        try:
            depth = int(self.settings.get('domain_compartment_depth', 1))
        except (TypeError, ValueError):
            depth = 1
        self.depth.setValue(max(1, min(6, depth)))
        self.depth.setFixedWidth(85)
        self.depth.setToolTip('1 = root; 2 = root and immediate children. Independent of policy recursion.')
        grid.addWidget(_label('Compartment Depth - Domain Search'), 1, 0, 1, 2)
        grid.addWidget(self.depth, 1, 2)
        grid.addWidget(self.load_all_users, 1, 3)
        grid.addWidget(self.recursive, 1, 4, 1, 2)

        # The final row pairs the primary action at the left with advanced
        # policy-fetch behavior at the right.
        self.policy_loading_controls = QWidget()
        policy_loading = QHBoxLayout(self.policy_loading_controls)
        policy_loading.setContentsMargins(0, 0, 0, 0)
        policy_loading.setSpacing(10)
        policy_loading.addWidget(_label('Policy Loading'))
        self.policy_load_method = QComboBox()
        self.policy_load_method.addItem('Resource Search', 'resource_search')
        self.policy_load_method.addItem('Compartment-based Policy Get', 'compartment')
        self.policy_load_method.setCurrentIndex(
            max(0, self.policy_load_method.findData(self.settings.get('policy_load_method', 'resource_search')))
        )
        self.policy_load_method.setToolTip(
            'Resource Search can lag recent changes. Compartment-based loading lists policies directly in each selected compartment, then fetches their details. The saved choice applies to live loads in either display mode.'
        )
        policy_loading.addWidget(self.policy_load_method, 1)
        grid.addWidget(self.policy_loading_controls, 2, 3, 1, 3)

        self.load_button = QPushButton('Load from OCI')
        self.load_button.setObjectName('primary')
        self.load_button.clicked.connect(self._load_oci)
        grid.addWidget(self.load_button, 2, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft)

        # Local snapshot panel: select a named cache, refresh the list, or open
        # an exported JSON file directly.
        saved = QVBoxLayout(self.source_panels[1])
        saved.setContentsMargins(0, 8, 0, 0)
        saved.addWidget(_label('Load a saved cache or open an exported JSON snapshot.', 'muted', wrap=True))
        actions = QHBoxLayout()
        self._responsive_rows.append(actions)
        self.cache_list = QComboBox()
        self.cache_list.setMinimumWidth(240)
        actions.addWidget(self.cache_list, 1)
        self.cache_button = QPushButton('Load cache')
        self.cache_button.setObjectName('primary')
        self.cache_button.clicked.connect(self._load_cache)
        actions.addWidget(self.cache_button)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh_caches)
        actions.addWidget(self.refresh_button)
        self.open_button = QPushButton('Open snapshot…')
        self.open_button.clicked.connect(self._open_snapshot)
        actions.addWidget(self.open_button)
        saved.addLayout(actions)
        self.refresh_caches()
        # CIS import has its own user-loading checkbox but shares the same
        # preference as the live tenancy option.
        cis = QVBoxLayout(self.source_panels[2])
        cis.setContentsMargins(0, 8, 0, 0)
        cis.addWidget(
            _label('Import the unzipped output directory from a CIS Compliance run with --raw.', 'muted', wrap=True)
        )
        cis_row = QHBoxLayout()
        self._responsive_rows.append(cis_row)
        self.cis_users = QCheckBox('Load all users')
        self.cis_users.setChecked(self.load_all_users.isChecked())
        self.cis_users.toggled.connect(self.load_all_users.setChecked)
        self.load_all_users.toggled.connect(self.cis_users.setChecked)
        cis_row.addWidget(self.cis_users)
        self.cis_button = QPushButton('Load CIS output…')
        self.cis_button.setObjectName('primary')
        self.cis_button.clicked.connect(self._load_compliance)
        cis_row.addWidget(self.cis_button)
        cis_row.addStretch()
        cis.addLayout(cis_row)
        # Sample data is entirely local and does not need connection settings.
        sample = QVBoxLayout(self.source_panels[3])
        sample.setContentsMargins(0, 8, 0, 0)
        sample.addWidget(
            _label('Explore fictional policies and identities without connecting to OCI.', 'muted', wrap=True)
        )
        self.sample_button = QPushButton('Load sample data')
        self.sample_button.setObjectName('primary')
        self.sample_button.clicked.connect(self.load_sample)
        sample_actions = QHBoxLayout()
        sample_actions.addWidget(self.sample_button)
        sample_actions.addStretch()
        sample.addLayout(sample_actions)
        self.source_selector.currentIndexChanged.connect(self._show_source)
        saved_source = self.settings.get('qt_load_source', 'oci')
        source_index = self.source_keys.index(saved_source) if saved_source in self.source_keys else 0
        self.source_selector.setCurrentIndex(source_index)
        self._show_source(source_index)

        return card

    def _show_source(self, index: int) -> None:
        """Show only the panel selected by the four-way source switch."""
        for panel_index, panel in enumerate(self.source_panels):
            panel.setVisible(panel_index == index)

    @staticmethod
    def _separator() -> QFrame:
        """Create the shared divider between the active data and settings."""
        line = QFrame()
        line.setObjectName('separator')
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def refresh_caches(self) -> None:
        """List saved caches without loading or rewriting a snapshot."""
        previous = self.cache_list.currentData()
        self.cache_list.clear()
        try:
            preserved = self.cache_service.get_preserved_cache_set()
            for name in self.cache_service.list_caches():
                self.cache_list.addItem(('(P) ' if name in preserved else '') + name, name)
            if previous is not None:
                self.cache_list.setCurrentIndex(max(0, self.cache_list.findData(previous)))
        except OSError as exc:
            self.cache_list.setToolTip(f'Could not list caches: {exc}')
        if not self.cache_list.count():
            self.cache_list.addItem('No saved caches', None)
        self.cache_button.setEnabled(self.cache_list.currentData() is not None)

    def _load_cache(self) -> None:
        """Request the currently selected saved cache from the load controller."""
        name = self.cache_list.currentData()
        if name:
            self.load_requested.emit('cache', {'cache_name': name}, f'Cache: {name}')

    def _load_compliance(self) -> None:
        """Choose a CIS raw-output folder and request its import."""
        path = QFileDialog.getExistingDirectory(
            self,
            'Select CIS Compliance raw output directory',
            '',
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.load_requested.emit(
                'compliance',
                {'path': path, 'load_all_users': self.cis_users.isChecked()},
                f'CIS output: {Path(path).name}',
            )

    def _active_data_card(self) -> QWidget:
        """Create the always-visible summary card for the active snapshot."""
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        header = QHBoxLayout()
        header.addWidget(_label('Active Data Set', 'eyebrow'))
        header.addStretch()
        self.load_status = _label(self._loaded_status, 'muted', wrap=True)
        self.load_status.setMinimumWidth(380)
        self.load_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.load_status)
        layout.addLayout(header)
        self.active_data_layout = QVBoxLayout()
        self.active_data_layout.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(self.active_data_layout)
        return card

    def _overview_page(self) -> QWidget:
        """Build snapshot counts and collection-coverage details."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.snapshot_label = _label('', 'eyebrow', wrap=True)
        layout.addWidget(self.snapshot_label)
        metrics = QHBoxLayout()
        self._responsive_rows.append(metrics)
        # Keep count labels keyed by stable result fields so publishing a new
        # snapshot can update the cards without depending on visual order.
        self.counts: dict[str, QLabel] = {}
        for title, entries in [
            ('Policy data', [('policies', 'Policies'), ('statements', 'Statements'), ('invalid', 'Invalid')]),
            ('Identities', [('users', 'Users'), ('groups', 'Groups'), ('dynamic_groups', 'Dynamic groups')]),
            (
                'Resource principals · provisional',
                [('resource_principal_statements', 'Any-user / any-group statements')],
            ),
            ('Scope', [('compartments', 'Compartments')]),
        ]:
            card = QFrame()
            card.setObjectName('card')
            group = QVBoxLayout(card)
            group.setContentsMargins(12, 8, 12, 8)
            group.addWidget(_label(title, 'eyebrow', wrap=True))
            columns = QHBoxLayout()
            group.addLayout(columns)
            for key, title in entries:
                column = QVBoxLayout()
                self.counts[key] = _label('—', 'metric')
                column.addWidget(self.counts[key])
                column.addWidget(_label(title, 'metricTitle', wrap=True))
                columns.addLayout(column)
            metrics.addWidget(card)
        self.counts['invalid'].setToolTip(
            'Source statements explicitly marked invalid; missing validity is not counted as invalid.'
        )
        self.counts['resource_principal_statements'].parentWidget().setToolTip(
            'Provisional evidence count: source statements with subject type any-user or any-group. '
            'Includes invalid statements with that parsed subject type. This is not a count of distinct '
            'resource principals or proof that those statements apply to workloads.'
        )
        layout.addLayout(metrics)
        self.coverage = QPlainTextEdit()
        self.coverage.setReadOnly(True)
        self.coverage.setFixedHeight(120)
        layout.addWidget(self.coverage)
        return page

    def reflow_rows(self) -> None:
        """Stack Overview control rows when text sizing exceeds the viewport width."""
        available = max(200, self.viewport().width() - 32)
        self.intelligence_panel.reflow_columns(available)
        for row in self._responsive_rows:
            required = sum(row.itemAt(i).sizeHint().width() for i in range(row.count()))
            required += max(0, row.count() - 1) * max(6, row.spacing())
            row.setDirection(
                QBoxLayout.Direction.TopToBottom if required > available else QBoxLayout.Direction.LeftToRight
            )

    def resizeEvent(self, event) -> None:
        """Reflow loading controls after the scroll viewport or font size changes."""
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reflow_rows)

    def _load_preferences_changed(self, *_args):
        """Debounce preference saves and flag changes to the loaded OCI source."""
        self._load_preferences_dirty = True
        if self._loaded_connection_signature is not None:
            changed = self._connection_signature() != self._loaded_connection_signature
            self._loaded_status = 'Loaded · OCI connection settings changed; reload to apply.' if changed else 'Loaded'
            self._refresh_active_status()
        self.preference_timer.start()

    def _connection_signature(self) -> tuple[str, str]:
        """Return the authentication inputs used to identify an OCI connection."""
        return (str(self.auth.currentData() or ''), self.profile.currentText().strip() or 'DEFAULT')

    def _refresh_active_status(self) -> None:
        """Restore the saved load state when no load or lock message is active."""
        if not self._busy and not self._load_locked:
            self.load_status.setText(self._loaded_status)

    def save_load_preferences(self, *, force: bool = False) -> None:
        """Persist load source, authentication and scope, including edits before close.

        Args:
            force: Save an explicit load request even when controls are unchanged.

        Notes:
            Uses existing Tk/web setting keys and merges only these preferences.
            Saving does not authenticate or collect tenancy data.
        """
        self.preference_timer.stop()
        if not force and not self._load_preferences_dirty:
            return
        self.settings.update(
            {
                'named_profile': self.profile.currentText().strip() or 'DEFAULT',
                'qt_auth_mode': self.auth.currentData(),
                'qt_load_source': self.source_keys[self.source_selector.currentIndex()],
                'instance_principal': self.auth.currentData() == 'instance_principal',
                'recursive': self.recursive.isChecked(),
                'load_all_users': self.load_all_users.isChecked(),
                'policy_load_method': self.policy_load_method.currentData(),
                'domain_compartment_depth': self.depth.value(),
            }
        )
        try:
            save_preferences(
                self.settings,
                (
                    'named_profile',
                    'qt_auth_mode',
                    'qt_load_source',
                    'instance_principal',
                    'recursive',
                    'load_all_users',
                    'domain_compartment_depth',
                    'policy_load_method',
                ),
            )
            self._load_preferences_dirty = False
        except OSError:
            self._loaded_status = 'Connection preferences could not be saved.'
            self._refresh_active_status()

    def load_options(self) -> dict:
        """Return explicit authentication and scope inputs without connecting to OCI."""
        return {
            'profile': self.profile.currentText().strip() or 'DEFAULT',
            'auth': self.auth.currentData(),
            'recursive': self.recursive.isChecked(),
            'depth': self.depth.value(),
            'load_all_users': self.load_all_users.isChecked(),
            'policy_load_method': self.policy_load_method.currentData(),
        }

    def load_sample(self) -> None:
        """Load fictional data through LoadService without authenticating to OCI."""
        self.load_requested.emit('sample', {}, 'Synthetic sample · no OCI connection')

    def _load_oci(self) -> None:
        """Save current options and emit a live OCI load request."""
        self.save_load_preferences(force=True)
        options = self.load_options()
        description = (
            f'OCI profile: {options["profile"]}'
            if options['auth'] == 'profile'
            else options['auth'].replace('_', ' ').title()
        )
        self.load_requested.emit('oci', options, description)

    def _open_snapshot(self) -> None:
        """Choose an exported JSON snapshot and request it be loaded."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Open exported policy snapshot',
            '',
            'JSON snapshots (*.json)',
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.load_requested.emit('file', {'path': path}, f'Export: {Path(path).name}')

    def set_busy(self, busy: bool) -> None:
        """Disable load and logging inputs until the current worker finishes."""
        self._busy = busy
        self._update_controls()

    def set_load_locked(self, locked: bool) -> None:
        """Lock load sources while MCP serves the current snapshot."""
        self._load_locked = locked
        self._update_controls()

    def _update_controls(self) -> None:
        """Enable or disable load controls based on worker and MCP state."""
        busy = self._busy or self._load_locked
        # Loading and source selection are locked during either state; optional
        # settings panels only lock while a background load is active.
        for widget in (
            self.auth,
            self.profile,
            self.recursive,
            self.load_all_users,
            self.depth,
            self.policy_load_method,
            self.load_button,
            self.open_button,
            self.sample_button,
            self.cache_list,
            self.cache_button,
            self.refresh_button,
            self.cis_button,
            self.cis_users,
        ):
            widget.setEnabled(not busy)
        self.profile.setEnabled(not busy and self.auth.currentData() == 'profile')
        self.cache_button.setEnabled(not busy and self.cache_list.currentData() is not None)
        for panel in (self.logging_panel, self.intelligence_panel):
            panel.setEnabled(not self._busy)
        if self._busy:
            self.load_status.setText('Loading… Previous results remain available.')
        elif self._load_locked:
            self.load_status.setText('Stop embedded MCP to load another snapshot.')
        elif self.load_status.text() == 'Stop embedded MCP to load another snapshot.':
            self._refresh_active_status()

    def set_snapshot(self, context: AppContext, result: LoadResult, description: str) -> None:
        """Refresh counts and collection scope from the newly published context."""
        self.results.show()
        self._loaded_connection_signature = (
            self._connection_signature()
            if description.startswith('OCI profile:') or description == 'Instance Principal'
            else None
        )
        self._loaded_status = 'Loaded'
        self.load_status.setText(self._loaded_status)
        repo = context.policy_repo
        counts = {
            **(result.summary or {}),
            'users': len(repo.users or []),
            'groups': len(repo.groups or []),
            'dynamic_groups': len(repo.dynamic_groups or []),
            'invalid': sum(statement.get('valid') is False for statement in repo.regular_statements),
            'resource_principal_statements': sum(
                str(statement.get('subject_type') or '').casefold() in {'any-user', 'any-group'}
                for statement in repo.regular_statements
            ),
        }
        for key, value in self.counts.items():
            value.setText(f'{counts.get(key, 0):,}')
        self.snapshot_label.setText(f'{getattr(repo, "tenancy_name", None) or "Loaded snapshot"}  /  {description}')
        recursion = getattr(repo, 'recursive', None)
        traversal = {True: 'Root and descendants', False: 'Root only'}.get(recursion, 'Not recorded')
        completeness = 'Reported complete' if getattr(repo, 'inventory_complete', None) is True else 'Not established'
        warnings = getattr(repo, '_cleanup_reload_api_errors', []) or []
        self.coverage.setPlainText(
            f'Snapshot type: {getattr(repo, "snapshot_kind", None) or "Not recorded"}\n'
            f'Policy collection scope: {traversal}\n'
            f'Policy loading method: {getattr(repo, "policy_load_method", None) or "Not recorded"}\n'
            f'Identity domain depth: {getattr(repo, "compartment_domain_search_depth", None) or "Not recorded"}\n'
            f'Inventory completeness: {completeness}\n'
            f'Collection errors reported: {len(warnings)} (not a completeness guarantee)\n'
            'Detailed call results: View → Logs → API Calls (current application session only)\n'
            f'Analysis: {context.settings.get("qt_post_load_profile", "minimal")}'
        )
