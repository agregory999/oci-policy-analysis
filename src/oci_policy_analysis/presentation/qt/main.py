"""Qt workbench shell: page composition, navigation, and window lifetime."""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from oci_policy_analysis._version import get_app_version
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.application.services.usage_service import UsageSession
from oci_policy_analysis.presentation.qt.api_calls import ApiCallsView
from oci_policy_analysis.presentation.qt.controller import WorkbenchController
from oci_policy_analysis.presentation.qt.details import DetailsDrawer
from oci_policy_analysis.presentation.qt.experience import ExperienceMode
from oci_policy_analysis.presentation.qt.icons import application_icon
from oci_policy_analysis.presentation.qt.logging_panel import QT_COMPONENTS, LiveLogView, LogBridge, LoggingPanel
from oci_policy_analysis.presentation.qt.pages.activity import LoadActivityPage
from oci_policy_analysis.presentation.qt.pages.browser import PolicyBrowserPage
from oci_policy_analysis.presentation.qt.pages.consolidation import ConsolidationPage
from oci_policy_analysis.presentation.qt.pages.cross_tenancy import CrossTenancyPage
from oci_policy_analysis.presentation.qt.pages.dynamic_groups import DynamicGroupsPage
from oci_policy_analysis.presentation.qt.pages.graph import PolicyGraphPage
from oci_policy_analysis.presentation.qt.pages.historical import HistoricalPage
from oci_policy_analysis.presentation.qt.pages.mcp import McpAssistantPage
from oci_policy_analysis.presentation.qt.pages.overview import OverviewSettingsPage
from oci_policy_analysis.presentation.qt.pages.permissions import PermissionsAnalysisPage
from oci_policy_analysis.presentation.qt.pages.policy_inventory import PolicyInventoryPage
from oci_policy_analysis.presentation.qt.pages.prospective import ProspectiveStatementsPage
from oci_policy_analysis.presentation.qt.pages.recommendations import RecommendationsPage
from oci_policy_analysis.presentation.qt.pages.resource_principals import ResourcePrincipalsPage
from oci_policy_analysis.presentation.qt.pages.simulation import SimulationPage
from oci_policy_analysis.presentation.qt.pages.tag_based import TagBasedPoliciesPage
from oci_policy_analysis.presentation.qt.pages.users_groups import UsersGroupsPage
from oci_policy_analysis.presentation.qt.pages.workflows import ToolsPage
from oci_policy_analysis.presentation.qt.preferences import load_preferences, save_preferences
from oci_policy_analysis.presentation.qt.themes import apply_theme, fixed_width_family
from oci_policy_analysis.presentation.qt.widgets import label

logger = get_logger(component='qt.main')


class WorkbenchWindow(QMainWindow):
    """Compose independent pages around a controller-owned analysis snapshot.

    Attributes:
        controller: Owner of asynchronous loads and the latest successful context.
        settings_page: Combined overview, load settings, and hideable logging pane.
        browser_page: Original policy evidence and shared-core search controls.
        graph_page: Native Qt graph over direct corpus grants and excluded evidence.
        dynamic_groups_page: Known inventory and exact principal-focused evidence.
        users_groups_page: Known users, group memberships, and policy evidence.
        resource_principals_page: Resource, dynamic-group and OKE workload evidence.
        drawer: Shared animated record inspector across evidence pages.
        activity_page: Load stages and handled errors.
        mcp_page: Managed loopback MCP endpoint and optional Codex conversation.

    Notes:
        No OCI connection occurs on construction. Logging settings affect the
        current process; explicit Apply actions save preferences. Close is blocked
        during loading and waits for MCP/Codex shutdown.
    """

    def __init__(self, *, verbose: bool = False, record_usage: bool = False) -> None:
        """Build the shell and connect page requests to the loading controller.

        Args:
            verbose: Lock shell/file DEBUG for this session; the UI remains INFO+.
            record_usage: Activate usage lifecycle; the launcher enables this, embedding defaults off.
        """
        super().__init__()
        self.setWindowTitle('OCI Policy Analysis · Preview')
        self.setWindowIcon(application_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1100, 760)
        self.log_bridge = LogBridge(self)
        self.verbose = bool(verbose)
        level = 'DEBUG' if self.verbose else 'INFO'
        settings = load_preferences()
        if self.verbose:
            settings.update({'global_log_level': level, 'log_levels': dict.fromkeys(QT_COMPONENTS, level)})
            settings['qt_runtime_log_levels'] = dict.fromkeys(settings.get('qt_runtime_log_levels', {}), 'DEBUG')
        LoggingService(settings).update_log_settings(settings, verbose_override=self.verbose)
        for name, runtime_level in settings.get('qt_runtime_log_levels', {}).items():
            logging.getLogger(name).setLevel('DEBUG' if self.verbose else runtime_level)
        self.usage = UsageSession(settings, get_app_version()) if record_usage else None
        self.controller = WorkbenchController(settings, self)
        self.experience = ExperienceMode(settings, self)
        self.settings_page = OverviewSettingsPage(
            LoggingPanel(settings, verbose=self.verbose), settings, self.experience
        )
        self.recommendations_page = RecommendationsPage(settings)
        self.recommendations_page.busy_changed.connect(self._recommendations_busy)
        self.recommendations_page.analysis_finished.connect(self._analysis_refreshed)
        self.prospective_page = ProspectiveStatementsPage()
        self.simulation_page = SimulationPage()
        self.simulation_page.manage_prospective.connect(
            lambda: self.navigation.setCurrentRow(self.page_index('prospective'))
        )
        self.consolidation_page = ConsolidationPage()
        self.consolidation_page.busy_changed.connect(self._consolidation_busy)
        self.consolidation_page.snapshot_changed.connect(self._analysis_refreshed)
        self.historical_page = HistoricalPage(self.settings_page.cache_service.cache)
        self.historical_page.busy_changed.connect(self._historical_busy)
        self.tools_page = ToolsPage(self.experience, self.settings_page.cache_service.cache)
        self.tools_page.maintenance.changed.connect(self._caches_changed)
        self.tools_page.maintenance.consolidation_reset.connect(self._consolidation_reset)
        self.tools_page.reports.busy_changed.connect(self._reports_busy)
        self.policy_inventory_page = PolicyInventoryPage(self.settings_page.cache_service.cache)
        self.policy_inventory_page.busy_changed.connect(self._policy_inventory_busy)
        self.policy_inventory_page.limits_changed.connect(self.recommendations_page.refresh_snapshot_data)
        self.policy_inventory_page.limits_status_changed.connect(self.recommendations_page.set_limits_feedback)
        self.recommendations_page.limits_requested.connect(
            lambda: self.policy_inventory_page.manage_limits(self.recommendations_page)
        )
        self.browser_page = PolicyBrowserPage(settings)
        self.graph_page = PolicyGraphPage()
        self.cross_tenancy_page = CrossTenancyPage()
        self.tag_based_page = TagBasedPoliciesPage()
        self.permissions_page = PermissionsAnalysisPage()
        self.dynamic_groups_page = DynamicGroupsPage()
        self.users_groups_page = UsersGroupsPage()
        self.resource_principals_page = ResourcePrincipalsPage()
        self.activity_page = LoadActivityPage()
        self.mcp_page = McpAssistantPage(settings)
        self.simulation_page.controller.busy_changed.connect(self._simulation_busy)
        self._closing = False
        self.mcp_page.locked.connect(self._mcp_locked)
        self.mcp_page.idle.connect(self._mcp_idle)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(225)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 24)
        side.addWidget(label('OCI / POLICY', 'brand'))
        side.addSpacing(20)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setWordWrap(True)
        self.navigation.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Navigation order and Standard/Advanced access policy live in this registry.
        self.page_specs = [
            ('overview', 'Overview & Settings', self.settings_page, False),
            ('policy_inventory', 'Policy Inventory', self.policy_inventory_page, False),
            ('browser', 'Policy Browser', self.browser_page, False),
            ('graph', 'Policy Graph', self.graph_page, False),
            ('users_groups', 'Users / Groups', self.users_groups_page, False),
            ('dynamic_groups', 'Dynamic Groups', self.dynamic_groups_page, False),
            ('resource_principals', 'Resource Principals', self.resource_principals_page, False),
            ('cross_tenancy', 'Cross-Tenancy', self.cross_tenancy_page, False),
            ('recommendations', 'Recommendations', self.recommendations_page, False),
            ('mcp', 'MCP & Assistant', self.mcp_page, True),
            ('tag_based', 'Tag-Based Policies', self.tag_based_page, True),
            ('permissions', 'Permissions Analysis', self.permissions_page, True),
            ('prospective', 'Prospective Statements', self.prospective_page, True),
            ('simulation', 'Simulation', self.simulation_page, True),
            ('consolidation', 'Consolidation', self.consolidation_page, True),
            ('historical', 'Historical Comparison', self.historical_page, True),
            ('tools', 'Tools', self.tools_page, False),
        ]
        self.navigation.addItems([title for key, title, _page, _advanced in self.page_specs])
        side.addWidget(self.navigation)
        layout.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(30, 28, 30, 16)
        body.setSpacing(14)
        self.heading = label('Overview & Settings', 'title')
        body.addWidget(self.heading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        body.addWidget(self.progress)
        self.pages = QStackedWidget()
        for _key, _title, page, _advanced in self.page_specs:
            self.pages.addWidget(page)
        body.addWidget(self.pages, 1)
        self.data_as_of = label('No snapshot loaded', 'muted')
        self.statusBar().addPermanentWidget(self.data_as_of)
        layout.addLayout(body, 1)
        self.drawer = DetailsDrawer(root)
        self.recommendations_page.details_requested.connect(self.drawer.show_record)
        self.recommendations_page.consolidation_requested.connect(self._focus_consolidation)
        self.browser_page.details_requested.connect(self.drawer.show_record)
        self.simulation_page.details_requested.connect(self.drawer.show_record)
        self.cross_tenancy_page.details_requested.connect(self.drawer.show_record)
        self.consolidation_page.details_requested.connect(self.drawer.show_record)
        self.policy_inventory_page.details_requested.connect(self.drawer.show_record)
        self.policy_inventory_page.focus_policy_requested.connect(self._focus_policy)
        self.permissions_page.details_requested.connect(self.drawer.show_record)
        self.permissions_page.test_condition_requested.connect(self._open_condition_tester)
        self.permissions_page.analysis_requested.connect(self.recommendations_page.run_analysis)
        self.tag_based_page.details_requested.connect(self.drawer.show_record)
        self.tag_based_page.test_condition_requested.connect(self._open_condition_tester)
        self.tag_based_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.graph_page.details_requested.connect(self.drawer.show_record)
        self.graph_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.dynamic_groups_page.details_requested.connect(self.drawer.show_record)
        self.users_groups_page.details_requested.connect(self.drawer.show_record)
        self.users_groups_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.resource_principals_page.details_requested.connect(self.drawer.show_record)
        self.resource_principals_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.browser_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.dynamic_groups_page.focus_dynamic_group.connect(self._focus_dynamic_group)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.settings_page.load_requested.connect(self.controller.start_load)
        self.controller.activity.connect(self.activity_page.appendPlainText)
        self.controller.busy_changed.connect(self._busy_changed)
        self.controller.progress.connect(self._progress)
        self.controller.loaded.connect(self._publish)
        self.controller.failed.connect(self._failed)
        self.log_dock = QDockWidget('Logs', self)
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        self.log_tabs = QTabWidget()
        self.live_log = LiveLogView(self.log_bridge)
        self.log_tabs.addTab(self.live_log, 'Live log')
        self.log_tabs.addTab(self.activity_page, 'Load activity')
        self.api_calls = ApiCallsView()
        self.log_tabs.addTab(self.api_calls, 'API Calls')
        self.log_dock.setWidget(self.log_tabs)
        self.log_dock.visibilityChanged.connect(self._log_visibility)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()
        self.menuBar().addMenu('View').addAction(self.log_dock.toggleViewAction())
        self.settings_page.show_log_requested.connect(self._show_logs)
        self.settings_page.usage_changed.connect(self._usage_changed)
        self.settings_page.appearance_panel.changed.connect(self._apply_appearance)
        self.tools_page.show_logs.connect(self._show_logs)
        self.tools_page.show_logging_settings.connect(self._show_logging_settings)
        self.prospective_page.changed.connect(self._prospects_changed)
        self.simulation_page.prospective_requested.connect(self._review_simulation_drafts)
        self.browser_page.include_prospective = self.experience.advanced
        self.graph_page.include_prospective = self.experience.advanced
        for table in (
            self.users_groups_page.group_view.inventory,
            self.users_groups_page.group_view.memberships,
            self.users_groups_page.group_view.statements,
            self.users_groups_page.user_view.inventory,
            self.users_groups_page.user_view.memberships,
            self.users_groups_page.user_view.statements,
            self.browser_page.table,
            *self.cross_tenancy_page.tables.values(),
            self.consolidation_page.protection,
            self.consolidation_page.candidates,
            self.policy_inventory_page.compartments,
            self.policy_inventory_page.policies,
            self.policy_inventory_page.statements,
            self.policy_inventory_page.tags,
            self.graph_page.statements,
            self.dynamic_groups_page.group_table,
            self.dynamic_groups_page.statements,
            self.resource_principals_page.groups,
            self.resource_principals_page.statements,
            self.prospective_page.table,
            self.simulation_page.statements.selection.table,
        ):
            table.test_condition_requested.connect(self._open_condition_tester)
        self.experience.changed.connect(self._experience_changed)
        if self.usage:
            for name, tabs in [
                ('tools', self.tools_page),
                ('recommendations', self.recommendations_page.tabs),
                ('cross_tenancy', self.cross_tenancy_page.tabs),
                ('users_groups', self.users_groups_page.tabs),
                ('simulation', self.simulation_page),
            ]:
                tabs.currentChanged.connect(
                    lambda index, name=name, tabs=tabs: self.usage.view(name, tabs.tabText(index))
                )
            self.simulation_page.controller.executed.connect(lambda *_: self.usage.operation('simulation_run'))
        self._apply_appearance(settings)
        self._set_data_available(False)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage('Ready · No snapshot loaded')
        logger.info('Qt shell ready: overview/settings, browser, graph, dynamic groups, MCP, resource principals')

    def page_index(self, key: str) -> int:
        """Return the navigation index for a stable page key.

        Args:
            key: Page registry key, independent of visual navigation order.

        Returns:
            int: Position shared by navigation and the page stack.
        """
        return next(index for index, spec in enumerate(self.page_specs) if spec[0] == key)

    def _set_data_available(self, available: bool) -> None:
        for index, (_key, _title, page, advanced) in enumerate(self.page_specs):
            item = self.navigation.item(index)
            visible = not advanced or self.experience.advanced
            enabled = visible and (_key in {'overview', 'tools', 'historical'} or available)
            item.setHidden(not visible)
            flags = item.flags()
            item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled if enabled else flags & ~Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip('' if enabled else 'Load a snapshot on Overview to open this page.')
            report_busy = self.tools_page.reports.worker is not None
            analysis_busy = self.recommendations_page.worker is not None
            history_busy = self.historical_page.worker is not None
            consolidation_busy = self.consolidation_page.worker is not None
            page.setEnabled(
                enabled
                and (not report_busy or page is self.tools_page)
                and (not analysis_busy or page is self.recommendations_page)
                and (not history_busy or page is self.historical_page)
                and (not consolidation_busy or page is self.consolidation_page)
            )

    @Slot(bool)
    def _experience_changed(self, _advanced: bool) -> None:
        self.browser_page.include_prospective = _advanced
        self.graph_page.include_prospective = _advanced
        self._prospects_changed()
        self._set_data_available(self.controller.context is not None)
        index = self.pages.currentIndex()
        if self.navigation.item(index).isHidden():
            self.navigation.setCurrentRow(0)

    @Slot()
    def _prospects_changed(self) -> None:
        self.drawer.clear()
        self.simulation_page.refresh_prospective()
        self.browser_page.apply_filters()
        self.graph_page.search()

    @Slot(object)
    def _review_simulation_drafts(self, drafts) -> None:
        if self.mcp_page.active or self.simulation_page.controller.worker is not None:
            self.simulation_page.results.status.setText(
                'Stop embedded MCP and wait for simulation work before editing prospects.'
            )
            return
        report = self.simulation_page.results.report
        if not report:
            return
        from copy import deepcopy

        request = deepcopy(report['request'])
        before = {str(row['internal_id']) for row in self.controller.context.simulation.get_prospective_statements()}
        saved = False
        for draft in drafts:
            saved = self.prospective_page.review_draft(draft) or saved
        if saved:
            self.simulation_page.prepare_followup(request, before)

    @Slot(str)
    def _open_condition_tester(self, clause: str) -> None:
        self.navigation.setCurrentRow(self.page_index('tools'))
        self.tools_page.setCurrentIndex(0)
        self.tools_page.condition_tester.set_clause_text(clause)

    @Slot()
    def _show_logging_settings(self) -> None:
        self.navigation.setCurrentRow(0)
        section = self.settings_page.sections['Logging']
        section.button.setChecked(True)
        self.settings_page.ensureWidgetVisible(section)

    @Slot(int)
    def _navigate(self, index: int) -> None:
        if index < 0 or index >= len(self.page_specs):
            return
        if self.navigation.item(index).isHidden() or (
            self.page_specs[index][0] not in {'overview', 'tools', 'historical'} and self.controller.context is None
        ):
            self.navigation.setCurrentRow(0)
            return
        self.drawer.clear()
        self.pages.setCurrentIndex(index)
        self.heading.setText(self.page_specs[index][1])
        if self.usage:
            self.usage.view(self.page_specs[index][0])
        logger.debug('Navigated to page=%s', self.page_specs[index][0])

    @Slot(dict)
    def _focus_consolidation(self, opportunity: dict) -> None:
        """Open eligible recommendation sources in the advanced planning step."""
        if self.consolidation_page.select_opportunity(opportunity):
            self.experience.set_advanced(True)
            self.navigation.setCurrentRow(self.page_index('consolidation'))

    @Slot(dict)
    def _focus_dynamic_group(self, statement: dict) -> None:
        self.navigation.setCurrentRow(self.page_index('dynamic_groups'))
        self.dynamic_groups_page.focus_statement(statement)

    @Slot(object)
    def _focus_policy(self, policy: dict) -> None:
        """Open the policy browser narrowed to the selected inventory policy."""
        self.navigation.setCurrentRow(self.page_index('browser'))
        self.browser_page.focus_policy(policy)

    @Slot(str, str, str)
    def _progress(self, stage: str, detail: str, state: str) -> None:
        self.statusBar().showMessage(f'{stage} · {detail}')
        self.settings_page.load_status.setText(f'{stage} · {detail}')

    @Slot(object, object, str)
    def _publish(self, context, result, description: str) -> None:
        if self.usage:
            self.usage.set_tenancy(context.policy_repo.tenancy_ocid)
            source = getattr(self.controller.worker, 'source', '')
            source = {'oci': 'tenancy', 'file': 'json'}.get(source, source)
            self.usage.operation('data_load', source=source, counts=result.summary)
        self.drawer.clear()
        self.settings_page.set_snapshot(context, result, description)
        self.prospective_page.set_context(context)
        self.simulation_page.set_context(context)
        self.browser_page.set_context(context)
        self.policy_inventory_page.set_context(context)
        self.graph_page.set_context(context)
        self.cross_tenancy_page.set_context(context)
        self.tag_based_page.set_context(context)
        self.permissions_page.set_context(context)
        self.consolidation_page.set_context(context)
        self.dynamic_groups_page.set_context(context)
        self.users_groups_page.set_context(context)
        self.mcp_page.set_context(context)
        self.resource_principals_page.set_context(context)
        self.tools_page.reports.set_context(context)
        self.recommendations_page.set_context(context)
        self._set_data_available(True)
        self.settings_page.refresh_caches()
        self.historical_page.refresh_caches()
        self.tools_page.maintenance.set_context(context)
        self.data_as_of.setText(f'Data as of  ·  {getattr(context.policy_repo, "data_as_of", None) or "Not recorded"}')
        self.statusBar().showMessage(f'Loaded · {description}')

    @Slot(object)
    def _caches_changed(self, change) -> None:
        context = self.controller.context
        if context is not None and change['action'] == 'Renamed':
            if context.policy_repo.current_cache_name == change['old_name']:
                context.policy_repo.current_cache_name = change['new_name']
        self.settings_page.refresh_caches()
        self.historical_page.refresh_caches()
        self.tools_page.maintenance.refresh_caches()

    @Slot(str)
    def _consolidation_reset(self, tenancy_ocid: str) -> None:
        context = self.controller.context
        if context is not None and context.policy_repo.tenancy_ocid == tenancy_ocid:
            self.consolidation_page.set_context(context)

    @Slot(str)
    def _failed(self, message: str) -> None:
        if self.usage:
            self.usage.operation('data_load', success=False)
        self.statusBar().showMessage(f'Load failed · {message}')
        self.settings_page.load_status.setText(f'Load failed: {message}')

    @Slot(bool)
    def _busy_changed(self, busy: bool) -> None:
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if busy else ''
        )
        self.historical_page.set_block_reason('Wait for snapshot loading to finish.' if busy else '')
        self.recommendations_page.set_block_reason('Wait for snapshot loading to finish.' if busy else '')
        self.tools_page.reports.set_block_reason('Wait for snapshot loading to finish.' if busy else '')
        self.consolidation_page.set_block_reason('Wait for snapshot loading to finish.' if busy else '')
        self.permissions_page.set_block_reason('Wait for snapshot loading to finish.' if busy else '')
        self.settings_page.set_busy(busy)
        self.mcp_page.set_loading(busy)
        self.simulation_page.controller.block_reason = (
            'Wait for snapshot loading to finish.'
            if busy
            else ('Stop embedded MCP before preparing simulation statements.' if self.mcp_page.active else '')
        )
        self.simulation_page.setEnabled(not busy and self.controller.context is not None)
        self.progress.setVisible(busy)

    @Slot(bool)
    def _policy_inventory_busy(self, busy: bool) -> None:
        reason = 'Wait for OCI policy-limit retrieval to finish.' if busy else ''
        self.consolidation_page.set_block_reason(reason)
        self.controller.load_block_reason = reason
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.recommendations_page.set_block_reason(reason)
        self.simulation_page.controller.block_reason = reason
        self.mcp_page.set_loading(busy)
        if busy:
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.policy_inventory_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(bool)
    def _simulation_busy(self, busy: bool) -> None:
        self.consolidation_page.set_block_reason('Wait for the current simulation task to finish.' if busy else '')
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if busy else ''
        )
        self.historical_page.set_block_reason('Wait for the current simulation task to finish.' if busy else '')
        self.recommendations_page.set_block_reason('Wait for the current simulation task to finish.' if busy else '')
        self.tools_page.reports.set_block_reason('Wait for the current simulation task to finish.' if busy else '')
        self.progress.setVisible(busy)
        self.controller.load_block_reason = 'Wait for the current simulation task to finish.' if busy else ''
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.mcp_page.set_loading(busy)
        if busy:
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.simulation_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(bool)
    def _reports_busy(self, busy: bool) -> None:
        if busy:
            self._track_worker(self.tools_page.reports.worker, 'report_generate')
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if busy else ''
        )
        reason = 'Wait for the current report to finish.' if busy else ''
        self.consolidation_page.set_block_reason(reason)
        self.historical_page.set_block_reason(reason)
        self.recommendations_page.set_block_reason(reason)
        self.progress.setVisible(busy)
        self.controller.load_block_reason = reason
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.mcp_page.set_loading(busy)
        self.simulation_page.controller.block_reason = reason
        if busy:
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.tools_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(bool)
    def _recommendations_busy(self, busy: bool) -> None:
        if busy:
            self._track_worker(self.recommendations_page.worker, 'recommendations_refresh')
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if busy else ''
        )
        reason = 'Wait for recommendation analysis to finish.' if busy else ''
        self.consolidation_page.set_block_reason(reason)
        self.historical_page.set_block_reason(reason)
        self.drawer.clear()
        self.progress.setVisible(busy)
        self.controller.load_block_reason = reason
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.mcp_page.set_loading(busy)
        self.simulation_page.controller.block_reason = reason
        self.tools_page.reports.set_block_reason(reason)
        if busy:
            # Existing report previews belong to the old derived analysis.
            self.tools_page.reports.set_context(None)
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.recommendations_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(bool)
    def _historical_busy(self, busy: bool) -> None:
        if busy:
            self._track_worker(self.historical_page.worker, 'historical_compare')
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if busy else ''
        )
        reason = 'Wait for historical comparison to finish.' if busy else ''
        self.consolidation_page.set_block_reason(reason)
        self.drawer.clear()
        self.progress.setVisible(busy)
        self.controller.load_block_reason = reason
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.mcp_page.set_loading(busy)
        self.simulation_page.controller.block_reason = reason
        self.tools_page.reports.set_block_reason(reason)
        self.recommendations_page.set_block_reason(reason)
        if busy:
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.historical_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(bool)
    def _consolidation_busy(self, busy: bool) -> None:
        reason = 'Wait for consolidation planning or progress checking to finish.' if busy else ''
        self.drawer.clear()
        self.progress.setVisible(busy)
        self.controller.load_block_reason = reason
        self.permissions_page.set_block_reason(self.controller.load_block_reason if busy else '')
        self.settings_page.set_load_locked(busy)
        self.mcp_page.set_loading(busy)
        self.simulation_page.controller.block_reason = reason
        self.historical_page.set_block_reason(reason)
        self.recommendations_page.set_block_reason(reason)
        self.tools_page.reports.set_block_reason(reason)
        self.tools_page.maintenance.set_block_reason(reason)
        if busy:
            for _key, _title, page, _advanced in self.page_specs:
                if page is not self.consolidation_page:
                    page.setEnabled(False)
        else:
            self._set_data_available(self.controller.context is not None)

    @Slot(object)
    def _analysis_refreshed(self, context) -> None:
        if context is not self.controller.context:
            return
        # Full enrichment replaces engines; discard simulation results and stale evidence.
        for page in (
            self.prospective_page,
            self.simulation_page,
            self.browser_page,
            self.graph_page,
            self.cross_tenancy_page,
            self.tag_based_page,
            self.permissions_page,
            self.consolidation_page,
            self.policy_inventory_page,
            self.dynamic_groups_page,
            self.users_groups_page,
            self.resource_principals_page,
            self.mcp_page,
            self.tools_page.reports,
            self.recommendations_page,
        ):
            page.set_context(context)
        self._apply_appearance(self.controller.settings)

    @Slot(bool)
    def _log_visibility(self, visible: bool) -> None:
        """Let the log dock resize below the stacked pages' aggregate size hint."""
        policy = self.pages.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Ignored if visible else QSizePolicy.Policy.Preferred)
        self.pages.setSizePolicy(policy)
        if visible:
            QTimer.singleShot(0, self._size_log_dock)

    def _size_log_dock(self) -> None:
        if self.log_dock.isVisible() and not self.log_dock.isFloating():
            self.resizeDocks([self.log_dock], [420], Qt.Orientation.Vertical)

    @Slot()
    def _show_logs(self) -> None:
        self.log_tabs.setCurrentIndex(0)
        self.log_dock.show()
        self.resizeDocks([self.log_dock], [420], Qt.Orientation.Vertical)

    @Slot(bool)
    def _mcp_locked(self, locked: bool) -> None:
        self.tools_page.maintenance.set_block_reason(
            'Wait for the active task or embedded MCP to stop.' if locked else ''
        )
        self.historical_page.set_block_reason('Stop embedded MCP before comparing snapshots.' if locked else '')
        self.recommendations_page.set_block_reason('Stop embedded MCP before running analysis.' if locked else '')
        self.tools_page.reports.set_block_reason('Stop embedded MCP before generating reports.' if locked else '')
        self.consolidation_page.set_block_reason(
            'Stop embedded MCP before consolidation planning or checks.' if locked else ''
        )
        self.controller.load_block_reason = 'Stop embedded MCP before loading another snapshot.' if locked else ''
        self.permissions_page.set_block_reason(self.controller.load_block_reason if locked else '')
        self.settings_page.set_load_locked(locked)
        self.simulation_page.controller.block_reason = (
            'Stop embedded MCP before preparing simulation statements.' if locked else ''
        )

    @Slot()
    def _mcp_idle(self) -> None:
        if self._closing:
            self.close()

    @Slot(dict)
    def _apply_appearance(self, settings: dict) -> None:
        size = {'Small': 11, 'Medium': 13, 'Large': 15, 'Extra Large': 20}.get(settings.get('font_size'), 13)
        style = apply_theme(settings.get('qt_theme', 'Light'), size, settings.get('qt_color_theme', 'Forest'))
        if settings.get('qt_fixed_width_font', False):
            family = fixed_width_family()
            style += f"\nQTableView, QHeaderView, QWidget#settingsContent, QWidget#settingsContent * {{ font-family: '{family}'; }}"
        self.setStyleSheet(style)
        self.settings_page.reflow_rows()
        self.sidebar.setFixedWidth(max(225, round(225 * size / 13)))
        self.graph_page.set_theme(settings.get('qt_theme', 'Light'), settings.get('qt_color_theme', 'Forest'))
        self.cross_tenancy_page.refresh_graph()
        for table in self.findChildren(QTableView):
            table.ensurePolished()
            height = QFontMetrics(table.font()).height()
            padding = 8 if settings.get('qt_compact_rows', False) else 20
            table.verticalHeader().setDefaultSectionSize(max(30, height + padding))
            table.horizontalHeader().setMinimumHeight(height + 22)
            for column, title in enumerate(table.model.headers):
                if not table.isColumnHidden(column):
                    minimum = QFontMetrics(table.horizontalHeader().font()).horizontalAdvance(title) + 34
                    if table.columnWidth(column) < minimum:
                        table.setColumnWidth(column, minimum)

    def _track_worker(self, worker, category):
        if self.usage and worker is not None:
            worker.completed.connect(lambda *_: self.usage.operation(category))
            worker.failed.connect(lambda *_: self.usage.operation(category, success=False))

    @Slot(bool)
    def _usage_changed(self, enabled):
        settings = self.controller.settings
        previous = settings.get('usage_tracking_enabled', True)
        settings['usage_tracking_enabled'] = enabled
        try:
            save_preferences(settings, ('usage_tracking_enabled',))
        except OSError:
            settings['usage_tracking_enabled'] = previous
            self.settings_page.usage_tracking.blockSignals(True)
            self.settings_page.usage_tracking.setChecked(previous)
            self.settings_page.usage_tracking.blockSignals(False)
            self.statusBar().showMessage('Could not save usage preference; previous setting retained.')
            return
        if self.usage:
            self.usage.set_enabled(enabled)
        self.statusBar().showMessage(
            'Usage publishing enabled.' if enabled else 'Usage publishing disabled; pending data discarded.'
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep an active worker alive and detach the UI log handler on close."""
        if (
            self.controller.worker is not None
            or self.policy_inventory_page.worker is not None
            or self.simulation_page.controller.worker is not None
            or self.tools_page.reports.worker is not None
            or self.recommendations_page.worker is not None
            or self.historical_page.worker is not None
            or self.consolidation_page.worker is not None
        ):
            logger.warning('Close deferred while loading')
            self.statusBar().showMessage(
                'A load, analysis, comparison, simulation or report task is running. Close the window after it finishes.'
            )
            event.ignore()
        elif self.mcp_page.active:
            self._closing = True
            self.statusBar().showMessage('Stopping MCP and assistant before closing…')
            event.ignore()
            self.mcp_page.stop_all()
        else:
            self.settings_page.save_load_preferences()
            if self.usage:
                self.usage.close(wait=False)
            logger.info('Closing Qt workbench')
            self.log_bridge.close()
            self.api_calls.close()
            event.accept()


def main(argv: list[str] | None = None) -> int:
    """Run the optional Qt workbench with independent pages over shared services.

    Args:
        argv: Application arguments; defaults to process arguments.

    Returns:
        int: Qt application exit code.

    Notes:
        --sample loads fictional data through LoadService. OCI authentication
        occurs only after the user requests a live load on Overview & settings.
    """
    parser = argparse.ArgumentParser(description='OCI Policy Analysis Qt desktop preview')
    parser.add_argument('--analytics', action='store_true', help='Open the standalone usage analytics viewer')
    parser.add_argument('--days', type=int, default=30, help='Analytics initial date window; 0 means all history')
    parser.add_argument('--sample', action='store_true', help='Load fictional data without contacting OCI')
    parser.add_argument(
        '--verbose', '--debug', action='store_true', help='DEBUG to shell/app.log; in-app logs remain INFO+'
    )
    args = parser.parse_args(argv)
    if args.analytics:
        from oci_policy_analysis.analytics.qt import main as analytics_main

        return analytics_main(['--days', str(args.days)])
    application = QApplication.instance() or QApplication([sys.argv[0]])
    application.setStyle('Fusion')
    application.setApplicationName('OCI Policy Analysis')
    application.setApplicationDisplayName('OCI Policy Analysis · Preview')
    application.setWindowIcon(application_icon())
    window = WorkbenchWindow(verbose=args.verbose, record_usage=True)
    window.show()
    if args.sample:
        window.settings_page.load_sample()
    try:
        return application.exec()
    finally:
        if window.usage:
            window.usage.close(wait=True)
