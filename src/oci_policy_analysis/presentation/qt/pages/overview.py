"""Combined overview, load settings, and collapsible logging controls."""

import configparser
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
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
from oci_policy_analysis.presentation.qt.widgets import CollapsibleSection
from oci_policy_analysis.presentation.qt.widgets import label as _label


class OverviewSettingsPage(QScrollArea):
    """Own loading inputs and snapshot overview; emit requests to the controller."""

    load_requested = Signal(str, dict, str)
    browse_requested = Signal()

    show_log_requested = Signal()
    usage_changed = Signal(bool)

    def __init__(self, logging_panel: QWidget, settings: dict, experience=None) -> None:
        """Start with tenancy controls expanded and each settings section collapsed."""
        super().__init__()
        self.settings = settings
        self._responsive_rows = []
        self._busy = False
        self._load_locked = False
        self._load_preferences_dirty = False
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
        else:
            self.policy_loading_controls.hide()
        self.load_settings_status = _label('Connection and scope preferences are saved locally.', 'muted', wrap=True)
        layout.addWidget(self.load_settings_status)
        for signal in (
            self.profile.currentTextChanged,
            self.auth.currentIndexChanged,
            self.recursive.toggled,
            self.load_all_users.toggled,
            self.depth.valueChanged,
            self.policy_load_method.currentIndexChanged,
        ):
            signal.connect(self._load_preferences_changed)
        self.results = self._overview_page()
        self.results.hide()
        layout.addWidget(self.results)
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
        card = QFrame()
        card.setObjectName('card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(_label('01  Live tenancy · OCI', 'eyebrow'))
        row = QHBoxLayout()
        self._responsive_rows.append(row)
        self.auth = QComboBox()
        for title, mode in [
            ('OCI config profile', 'profile'),
            ('Instance principal', 'instance_principal'),
        ]:
            self.auth.addItem(title, mode)
        row.addWidget(self.auth)
        row.addWidget(_label('Profile'))
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
        self.profile.setMaximumWidth(230)
        self.profile.setMinimumWidth(160)
        row.addWidget(self.profile)
        self.load_button = QPushButton('Load from OCI')
        self.load_button.setObjectName('primary')
        self.load_button.clicked.connect(self._load_oci)
        row.addWidget(self.load_button)
        row.addStretch()
        layout.addLayout(row)
        scope = QHBoxLayout()
        self._responsive_rows.append(scope)
        self.recursive = QCheckBox('Include child compartments')
        self.recursive.setChecked(bool(self.settings.get('recursive', True)))
        scope.addWidget(self.recursive)
        self.load_all_users = QCheckBox('Load all users')
        self.load_all_users.setChecked(bool(self.settings.get('load_all_users', True)))
        scope.addWidget(self.load_all_users)
        scope.addWidget(_label('Identity domain depth'))
        self.depth = QSpinBox()
        self.depth.setRange(1, 6)
        try:
            depth = int(self.settings.get('domain_compartment_depth', 1))
        except (TypeError, ValueError):
            depth = 1
        self.depth.setValue(max(1, min(6, depth)))
        self.depth.setFixedWidth(85)
        self.depth.setToolTip('1 = root; 2 = root and immediate children. Independent of policy recursion.')
        scope.addWidget(self.depth)
        scope.addStretch()
        layout.addLayout(scope)
        self.policy_loading_controls = QWidget()
        policy_loading = QHBoxLayout(self.policy_loading_controls)
        policy_loading.setContentsMargins(0, 0, 0, 0)
        self._responsive_rows.append(policy_loading)
        policy_loading.addWidget(_label('Policy loading'))
        self.policy_load_method = QComboBox()
        self.policy_load_method.addItem('Resource Search', 'resource_search')
        self.policy_load_method.addItem('Compartment-based Policy Get', 'compartment')
        self.policy_load_method.setCurrentIndex(
            max(0, self.policy_load_method.findData(self.settings.get('policy_load_method', 'resource_search')))
        )
        self.policy_load_method.setToolTip(
            'Resource Search can lag recent changes. Compartment-based loading lists policies directly in each selected compartment, then fetches their details. The saved choice applies to live loads in either display mode.'
        )
        policy_loading.addWidget(self.policy_load_method)
        policy_loading.addStretch()
        layout.addWidget(self.policy_loading_controls)
        layout.addWidget(self._separator())
        layout.addWidget(_label('02  Saved data · Cache or exported snapshot', 'eyebrow'))
        actions = QHBoxLayout()
        self._responsive_rows.append(actions)
        self.cache_list = QComboBox()
        self.cache_list.setMinimumWidth(240)
        actions.addWidget(self.cache_list, 1)
        self.cache_button = QPushButton('Load cache')
        self.cache_button.clicked.connect(self._load_cache)
        actions.addWidget(self.cache_button)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.refresh_caches)
        actions.addWidget(self.refresh_button)
        self.open_button = QPushButton('Open snapshot…')
        self.open_button.clicked.connect(self._open_snapshot)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
        self.refresh_caches()
        layout.addWidget(self._separator())
        layout.addWidget(_label('03  CIS Compliance · Unzipped raw output', 'eyebrow'))
        cis_row = QHBoxLayout()
        self._responsive_rows.append(cis_row)
        cis_row.addWidget(_label('Choose the output directory from a CIS run with --raw.', 'muted', wrap=True), 1)
        self.cis_users = QCheckBox('Load all users')
        self.cis_users.setChecked(self.load_all_users.isChecked())
        self.cis_users.toggled.connect(self.load_all_users.setChecked)
        self.load_all_users.toggled.connect(self.cis_users.setChecked)
        cis_row.addWidget(self.cis_users)
        self.cis_button = QPushButton('Load CIS output…')
        self.cis_button.clicked.connect(self._load_compliance)
        cis_row.addWidget(self.cis_button)
        layout.addLayout(cis_row)
        layout.addWidget(self._separator())
        actions = QHBoxLayout()
        self._responsive_rows.append(actions)
        self.sample_button = QPushButton('Sample data')
        self.sample_button.clicked.connect(self.load_sample)
        actions.addWidget(self.sample_button)
        self.show_log = QPushButton('Show live log')
        self.show_log.clicked.connect(self.show_log_requested.emit)
        actions.addWidget(self.show_log)
        actions.addStretch()
        layout.addLayout(actions)
        self.load_status = _label('Ready', 'muted', wrap=True)
        layout.addWidget(self.load_status)
        return card

    @staticmethod
    def _separator() -> QFrame:
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
        name = self.cache_list.currentData()
        if name:
            self.load_requested.emit('cache', {'cache_name': name}, f'Cache: {name}')

    def _load_compliance(self) -> None:
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

    def _overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.snapshot_label = _label('', 'eyebrow', wrap=True)
        layout.addWidget(self.snapshot_label)
        metrics = QHBoxLayout()
        self._responsive_rows.append(metrics)
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
        self._load_preferences_dirty = True
        self.preference_timer.start()

    def save_load_preferences(self, *, force: bool = False) -> None:
        """Persist authentication selection and scope, including edits before close.

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
                    'instance_principal',
                    'recursive',
                    'load_all_users',
                    'domain_compartment_depth',
                    'policy_load_method',
                ),
            )
            self._load_preferences_dirty = False
            self.load_settings_status.setText('Connection and scope preferences saved locally.')
        except OSError:
            self.load_settings_status.setText(
                'Could not save connection preferences; current selections remain usable.'
            )

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
        self.save_load_preferences(force=True)
        options = self.load_options()
        description = (
            f'OCI profile: {options["profile"]}'
            if options['auth'] == 'profile'
            else options['auth'].replace('_', ' ').title()
        )
        self.load_requested.emit('oci', options, description)

    def _open_snapshot(self) -> None:
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
        busy = self._busy or self._load_locked
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
            self.load_status.setText('Ready' if self.results.isHidden() else 'Loaded')

    def set_snapshot(self, context: AppContext, result: LoadResult, description: str) -> None:
        """Refresh counts and collection scope from the newly published context."""
        self.results.show()
        self.load_status.setText('Loaded')
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
