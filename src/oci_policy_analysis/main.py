##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# main.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import argparse
import asyncio
import json
import logging
import platform
import queue
import threading
import time
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
import traceback
import warnings
import webbrowser
from importlib.resources import files

import oci
from dateutil import parser as dtparser

# Application imports
from oci_policy_analysis._version import get_app_version
from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.engine import PolicyIntelligenceEngine, PolicySimulationEngine
from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.core.support.logger import (  # noqa: E402
    get_logger,
    set_component_level,
    set_log_level,
)
from oci_policy_analysis.application.core.support.usage_tracking import (  # noqa: E402
    get_usage_tracker,
    init_usage_tracker,
)
from oci_policy_analysis.application.services.consolidation_workbench_service import ConsolidationWorkbenchService
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.application.services.prospective_statements_service import ProspectiveStatementsService
from oci_policy_analysis.presentation.desktop.condition_tester_tab import ConditionTesterTab
from oci_policy_analysis.presentation.desktop.console_tab import ConsoleTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.consolidation_workbench_tab import ConsolidationWorkbenchTab
from oci_policy_analysis.presentation.desktop.cross_tenancy_tab import CrossTenancyTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.debugger_tab import DebuggerTab
from oci_policy_analysis.presentation.desktop.dynamic_group_tab import DynamicGroupsTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.historical_tab import HistoricalTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.maintenance_tab import MaintenanceTab

try:
    from oci_policy_analysis.presentation.desktop.mcp_tab import McpTab  # noqa: E402
except ModuleNotFoundError:
    McpTab = None  # type: ignore[assignment]
from oci_policy_analysis.presentation.desktop.permissions_report_tab import PermissionsReportTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.policies_tab import PoliciesTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.policy_browser_tab import PolicyBrowserTab
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab
from oci_policy_analysis.presentation.desktop.reports_tab import ReportsTab
from oci_policy_analysis.presentation.desktop.settings_tab import SettingsTab  # noqa: E402
from oci_policy_analysis.presentation.desktop.simulation_tab import SimulationTab
from oci_policy_analysis.presentation.desktop.tag_based_access_tab import TagBasedAccessTab
from oci_policy_analysis.presentation.desktop.users_tab import UsersTab
from oci_policy_analysis.presentation.desktop.workload_principals_tab import WorkloadPrincipalsTab  # noqa: E402

# ----------- POST-IMPORT SETUP ------------
__version__ = get_app_version()
logger = get_logger(component='main')

# Suppress OCI SDK datetime.utcnow() DeprecationWarning (Python 3.12+)
warnings.filterwarnings('ignore', category=DeprecationWarning, message=r'.*datetime\.datetime\.utcnow\(\).*')
# Suppress DeprecationWarnings from libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)
# Filter out specific RuntimeWarning about module re-imports that can occur in certain environments (e.g., PyInstaller) and are non-fatal
warnings.filterwarnings(
    'ignore',
    category=RuntimeWarning,
    message=r".*'oci_policy_analysis.main' found in sys.modules after import of package 'oci_policy_analysis'.*",
)

GITHUB_REPO_BASE_URL = 'https://github.com/agregory999/oci-policy-analysis'
GITHUB_REPO_ISSUES_URL = f'{GITHUB_REPO_BASE_URL}/issues'
GITHUB_REPO_RELEASES_URL = f'{GITHUB_REPO_BASE_URL}/releases'

# ----------- MAIN APPLICATION CLASS ------------
"""
Main Tkinter UI application for OCI Policy Analysis.

This module can be executed directly:

    python -m oci_policy_analysis.main

or via the script entrypoint (if configured):

    oci-policy-analysis

When run as a script, the `__main__` block launches the full desktop UI.
"""


class App(tk.Tk):
    """
    Main User Interface entry point for OCI Policy Analysis application.
    Inherits from tk.Tk (TKinter) to create the main application window.
    Tabbed interface with multiple tabs for different analysis features.
    Helper classes and Repositories for data management and AI integration.

    Adds a fixed status bar at the window bottom showing policy data load status/source/time/reload.
    """

    # docstring google style napoleon comments for the class with public methods and relevant private methods marked with (Internal)

    def __init__(self, force_debug: bool = False, experimental_features: bool = False, enable_genai: bool = False):  # noqa: C901
        super().__init__()

        # Hidden/undocumented experimental features toggle (e.g., Consolidation tab)
        self.experimental_features = experimental_features
        # OCI GenAI remains available in the application context, but its
        # desktop UI is an opt-in preview until this flag is removed.
        self.genai_feature_enabled = enable_genai

        # Shared config & logger - load settings and quietly return if nothing is loaded
        self.settings = config.load_settings()

        # Configure basic window geometry
        self.title(f'OCI Policy Analysis {__version__}')
        self.geometry('1440x900')
        self._configure_window_icon()

        # Initialize usage tracker (may be None if disabled in settings)
        self.usage_tracker = init_usage_tracker(self.settings, __version__)

        # === CENTRALIZED LOGGER CONFIGURATION (run before any tab is constructed) ===
        log_levels = self.settings.get('log_levels', {})
        # Default to WARNING if no explicit global log level is set in settings
        global_log_level = log_levels.get(
            'global_log_level',
            self.settings.get('global_log_level', 'WARNING'),
        )

        # If --verbose is set, override global/component levels (shell and file only; ConsoleTab still shows INFO+)
        if force_debug:
            self.log_level_var = tk.StringVar(value='DEBUG')
            logger.info('Log level forcibly set to DEBUG due to --verbose argument (settings ignored)')
            set_log_level('DEBUG')
            for component in log_levels.keys():
                set_component_level(component, 'DEBUG')
        else:
            self.log_level_var = tk.StringVar(value=global_log_level)
            set_log_level(global_log_level)
            for component, level in log_levels.items():
                if component == 'global_log_level':
                    continue
                set_component_level(component, level)
            logger.info(f'Log level set to {logging.getLevelName(logger.level)} from settings')

        # Style / fonts (standard tkinter only)
        self.style = ttk.Style()
        # Native Tkinter themes: 'clam', 'alt', 'default', 'classic', ('vista' on Windows, 'xpnative') etc
        # self.style.theme_use('aqua' if sys.platform == 'darwin' else 'vista' if sys.platform == 'win32' else 'clam')
        self.style.theme_use('clam')
        self.default_font = tkfont.nametofont('TkDefaultFont')
        self.style.configure('.', font=('Oracle Sans', 12))
        self.style.configure('Treeview', padding=(0, 0, 8, 0))

        # PanedWindow (vertical split)
        self.pw = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.pw.pack(fill='both', expand=True)

        # Top frame with Notebook
        self.top_frame = ttk.Frame(self.pw)
        self.pw.add(self.top_frame, weight=3)

        self.notebook = ttk.Notebook(self.top_frame)
        self.notebook.pack(fill='both', expand=True)

        # Repository / Data / Simulation Engine
        self.app_context = AppContext.from_settings(self.settings)
        self.load_service = LoadService(self.app_context)
        self.cache_service = self.app_context.cache_service
        self.settings_service = self.app_context.settings_service

        # If settings didn't define tracking at all, default to enabled on first run
        if 'usage_tracking_enabled' not in self.settings:
            self.settings['usage_tracking_enabled'] = True
            try:
                self.settings_service.save()
            except Exception:
                pass

        self.reference_data_repo = self.app_context.reference_data
        self.policy_compartment_analysis = self.app_context.policy_repo
        self.ai = self.app_context.ai
        self.simulation_engine = self.app_context.simulation
        self.policy_intelligence = self.app_context.intelligence
        # The desktop and web workbenches use this same application-service
        # boundary for consolidation state, planning, and progress tracking.
        self.consolidation_workbench_service = ConsolidationWorkbenchService(self.app_context)

        # Caching Manager (policy caching only, no AI result caching)
        self.caching = self.app_context.cache

        # Guard: prevent overlapping tenancy loads
        self._tenancy_load_in_progress = False
        # Guard: prevent overlapping policy reloads
        self._policy_reload_in_progress = False

        # Reload progress dialog state
        self._policy_reload_dialog = None
        self._policy_reload_message_var = tk.StringVar(value='')

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
        self.policy_browser_tab = PolicyBrowserTab(self.notebook, self, self.settings)
        self.policies_tab = PoliciesTab(self.notebook, self, self.settings)
        self.permissions_report_tab = PermissionsReportTab(self.notebook, self)
        self.users_tab = UsersTab(self.notebook, self)
        self.dynamic_groups_tab = DynamicGroupsTab(self.notebook, self)
        self.cross_tenancy_tab = CrossTenancyTab(self.notebook, self)
        self.resource_principals_tab = WorkloadPrincipalsTab(self.notebook, self)
        self.historical_tab = HistoricalTab(self.notebook, caching=self.caching)
        self.policy_recommendations_tab = PolicyRecommendationsTab(self.notebook, self)
        self.reports_tab = ReportsTab(self.notebook, self)
        self.console_tab = ConsoleTab(self.notebook, self)
        self.maintenance_tab = MaintenanceTab(self.notebook, self)
        self.condition_tester_tab = ConditionTesterTab(self.notebook, self)
        self.simulation_tab = SimulationTab(self.notebook, self, self.settings)
        self.tag_based_access_tab = TagBasedAccessTab(self.notebook, self)
        self.debugger_tab = DebuggerTab(self.notebook, self)
        self.mcp_tab = (
            McpTab(self.notebook, self, self.policy_compartment_analysis)
            if McpTab is not None
            else ttk.Frame(self.notebook)
        )
        self.consolidation_tab = ConsolidationWorkbenchTab(self.notebook, self)

        # Able to refresh maintenance tab with new data
        self.maintenance_tab.refresh_data()

        # Add tabs to notebook
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policy_browser_tab, text='Policy\nInventory')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Workload\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        if McpTab is not None:
            self.notebook.add(self.mcp_tab, text='Embedded MCP\n(Advanced)')
        self.notebook.add(self.permissions_report_tab, text='Permissions\nAnalysis')
        self.notebook.add(self.condition_tester_tab, text='Condition\nTester')
        self.notebook.add(self.tag_based_access_tab, text='Tag-based Access\n(Advanced)')
        self.notebook.add(self.policy_recommendations_tab, text='Policy\nRecommendations')
        self.notebook.add(self.reports_tab, text='Reports\n(On-Demand)')
        self.notebook.add(self.consolidation_tab, text='Consolidation\n(Advanced)')
        self.notebook.add(self.simulation_tab, text='API Simulation\n(Advanced)')
        self.notebook.add(self.debugger_tab, text='JSON Debugger\n(Internal)')
        self.notebook.add(self.console_tab, text='Console Logging\n(Internal)')
        self.notebook.add(self.maintenance_tab, text='Maintenance\n(Internal)')
        # --- AI Pane/Tab Support: Bind to tab change for auto-hide logic ---
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # Propagate context help and font size settings to all tabs at startup
        self.refresh_all_tabs_settings()

        # Bottom frame (Entry + output text area)
        self.bottom_frame = ttk.Frame(self.pw, height=200)
        # Directly build a minimal output UI: Text widget only (no HTML/Markdown modes)
        cmdrow = ttk.Frame(self.bottom_frame)
        cmdrow.pack(fill='x', padx=8, pady=(8, 4))
        cmdrow.grid_columnconfigure(0, weight=8)
        cmdrow.grid_columnconfigure(1, weight=75)
        cmdrow.grid_columnconfigure(2, weight=7)
        cmdrow.grid_columnconfigure(3, weight=10)

        self.policy_query_var = tk.StringVar()
        self.policy_query_label_text = tk.StringVar(value='Policy Statement\nfor analysis:')
        ttk.Label(cmdrow, textvariable=self.policy_query_label_text).grid(row=0, column=0, padx=5, pady=5, sticky='w')

        self.bottom_entry = ttk.Entry(cmdrow, textvariable=self.policy_query_var, width=90)
        self.bottom_entry.grid(row=0, column=1, padx=5, pady=5, sticky='ew')

        # Hidden variable for additional instructions (not exposed in UI)
        self.ai_additional_instructions: str = ''
        if self.genai_feature_enabled:
            ttk.Button(
                cmdrow,
                text='Query GenAI',
                command=lambda: self.ask_genai_async(
                    prompt=self.policy_query_var.get(), additional_instruction=self.ai_additional_instructions
                ),
            ).grid(row=0, column=2, padx=5, pady=5, sticky='w')

        self.copy_txt_btn = ttk.Button(cmdrow, text='Copy Text', command=self.copy_output_text, state='disabled')
        self.copy_txt_btn.grid(row=0, column=4, padx=(10, 0), pady=5, sticky='w')
        self.last_output_text = ''

        self.ai_progress_var = tk.StringVar(value='')
        ttk.Label(cmdrow, textvariable=self.ai_progress_var, foreground='blue', width=22).grid(
            row=0, column=3, padx=5, pady=5, sticky='w'
        )

        # Output area with vertical scrollbar
        output_container = ttk.Frame(self.bottom_frame)
        output_container.pack(fill='both', expand=True, padx=8, pady=8)

        self.output_text = tk.Text(
            output_container,
            wrap=tk.WORD,
            height=15,
            bg='white',
            fg='black',
            state='disabled',
            font=('Courier New', 11),
        )
        self.output_text.pack(side='left', fill='both', expand=True)

        self.output_scrollbar = ttk.Scrollbar(
            output_container,
            orient='vertical',
            command=self.output_text.yview,
        )
        self.output_scrollbar.pack(side='right', fill='y')
        self.output_text.configure(yscrollcommand=self.output_scrollbar.set)

        # Console / Maintenance / Advanced tab Visibility
        self.console_visible = False
        self.advanced_tabs_visible = False
        self.maintenance_visible = False
        self.notebook.forget(self.console_tab)
        self.notebook.forget(self.debugger_tab)
        if McpTab is not None:
            self.notebook.forget(self.mcp_tab)
        self.notebook.forget(self.maintenance_tab)
        self.notebook.forget(self.permissions_report_tab)
        self.notebook.forget(self.tag_based_access_tab)
        self.notebook.forget(self.simulation_tab)
        self.notebook.forget(self.consolidation_tab)

        # Ensure the correct font is applied from saved settings at startup
        self.after(0, self.apply_theme)

        # === STATUS BAR (Fixed 1-line) at window bottom ===
        # Left side: dynamic policy/usage tracking text
        self.status_var = tk.StringVar(value='Policy Data: (Not Loaded)')
        # Use a dedicated font for the status bar, will sync with theme/font size in apply_theme()
        self.status_font = (
            tkfont.Font(name='StatusFont', exists=True)
            if 'StatusFont' in tkfont.names()
            else tkfont.Font(
                name='StatusFont',
                family=self.default_font.actual('family'),
                size=self.default_font.actual('size'),
            )
        )
        # Wrap status bar in a frame so we can add right-aligned clickable links
        self.status_frame = ttk.Frame(self)
        self.status_frame.pack(side='bottom', fill='x')

        self.status_bar = ttk.Label(
            self.status_frame,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor='w',
            padding=4,
            font=self.status_font,
        )
        self.status_bar.pack(side='left', fill='x', expand=True)

        self.compliance_capability_banner_var = tk.StringVar(value='')
        # Use a classic Tk label so the warning colors remain visible across
        # ttk themes; ttk.Label backgrounds are ignored by several platforms.
        self.compliance_capability_banner = tk.Label(
            self,
            textvariable=self.compliance_capability_banner_var,
            anchor='w',
            padx=8,
            pady=4,
            fg='#7A4E00',
            bg='#FFF3CD',
            relief=tk.SOLID,
            borderwidth=1,
            wraplength=1350,
        )

        # Right side: GitHub links (Issues/Comments and Latest Releases)
        links_font: tkfont.Font | None = None
        try:
            links_font = tkfont.Font(font=self.status_font)
            links_font.configure(underline=True)
        except Exception:
            links_font = None

        def _make_link(parent, text: str, url: str) -> ttk.Label:
            label = ttk.Label(
                parent,
                text=text,
                foreground='blue',
                cursor='hand2',
                padding=(8, 4),
                font=links_font or self.status_font,
            )
            label.bind('<Button-1>', lambda _event, u=url: self.open_link(u))
            return label

        # Pack order: Releases (rightmost), then Issues/Comments to its left
        self.releases_link = _make_link(self.status_frame, 'Latest Releases', GITHUB_REPO_RELEASES_URL)
        self.releases_link.pack(side='right')

        self.issues_link = _make_link(self.status_frame, 'Issues/Comments', GITHUB_REPO_ISSUES_URL)
        self.issues_link.pack(side='right')
        # [CROSS-PLATFORM PATCH] Improve status bar visibility on Windows by setting background/foreground.
        try:
            self.status_bar.configure(background='#FFF9CC', foreground='black', borderwidth=1)
        except Exception:
            pass  # configure fails on some ttk themes, but safe to ignore
        self.update_status_bar()

        # Track app start (non-fatal if tracker is None)
        try:
            tracker = get_usage_tracker()
            if tracker is not None:
                tracker.track('app_start')
        except Exception:
            pass

    def _update_compliance_capability_ui(self) -> None:
        """Show partial-CIS availability and gate tabs that require missing identity data."""
        repo = self.policy_compartment_analysis
        capabilities = getattr(repo, 'compliance_capabilities', {}) or {}
        is_compliance = bool(getattr(repo, 'loaded_from_compliance_output', False) and capabilities)
        is_partial = is_compliance and not bool(capabilities.get('principal_resolution'))
        tab_availability = (
            (self.users_tab, not is_compliance or bool(capabilities.get('principal_resolution'))),
            (self.dynamic_groups_tab, not is_compliance or bool(capabilities.get('dynamic_groups_inventory'))),
            (self.permissions_report_tab, not is_compliance or bool(capabilities.get('principal_resolution'))),
            (self.simulation_tab, not is_compliance or bool(capabilities.get('principal_resolution'))),
            (self.tag_based_access_tab, not is_compliance or bool(capabilities.get('defined_tag_catalog'))),
            (self.historical_tab, not is_partial),
        )
        for tab, available in tab_availability:
            # Some advanced tabs are intentionally forgotten until the user
            # enables them in Settings. A forgotten tab cannot be configured
            # through ttk.Notebook, but Settings reapplies this gate when it
            # adds the tab back.
            if str(tab) in self.notebook.tabs():
                self.notebook.tab(tab, state='normal' if available else 'disabled')

        recommendations_tab = getattr(self, 'policy_recommendations_tab', None)
        if hasattr(recommendations_tab, 'update_consolidation_plan_availability'):
            recommendations_tab.update_consolidation_plan_availability()

        if not is_partial:
            self.compliance_capability_banner_var.set('')
            self.compliance_capability_banner.pack_forget()
            return

        artifact_counts = getattr(repo, 'compliance_artifact_counts', {}) or {}
        compartments = artifact_counts.get('compartments', len(getattr(repo, 'compartments', []) or []))
        policies = artifact_counts.get('policies', len(getattr(repo, 'policies', []) or []))
        statements = artifact_counts.get('statements', len(getattr(repo, 'regular_statements', []) or []))
        self.compliance_capability_banner_var.set(
            'Partial CIS Compliance dataset: '
            f'loaded {compartments} compartments, {policies} policies, and {statements} statements. '
            'Policy hierarchy, statement moves, consolidation, recommendations, Workload Principals, and policy-derived '
            'principal filtering work. '
            'Groups/Users, Dynamic Groups, Permissions Analysis, API Simulation, and Tag-based Access require identity data '
            'that was not supplied and are disabled. Historical comparison is disabled because this dataset has no '
            'compatible identity snapshot.'
        )
        if not self.compliance_capability_banner.winfo_ismapped():
            self.compliance_capability_banner.pack(side='bottom', fill='x')

    def _configure_window_icon(self) -> None:
        """Set the Tk window icon from packaged assets when available."""

        try:
            icon_path = files('oci_policy_analysis.assets.icons').joinpath('oci-policy-dg-viewer.png')
            icon = tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, icon)
            self._app_icon_image = icon
        except Exception as exc:
            logger.debug('Unable to set Tk window icon: %s', exc, exc_info=True)

    def update_status_bar(self):
        """Update status bar with policy data load status and tracking flag."""
        repo = getattr(self, 'policy_compartment_analysis', None)
        if not repo:
            core_text = 'Policy Data: (Not Loaded)'
            tracking_suffix = (
                ' | Tool Usage Tracking: On'
                if self.settings.get('usage_tracking_enabled')
                else ' | Tool Usage Tracking: Off'
            )
            self.status_var.set(core_text + tracking_suffix)
            return
        # Determine source
        loaded = False
        load_source = None
        tenancy_name = getattr(repo, 'tenancy_name', None)
        # Flags set by PolicyAnalysisRepository load paths
        if getattr(repo, 'policies_loaded_from_tenancy', False):
            load_source = f'Tenancy "{tenancy_name or ""}"'
            loaded = True
        elif getattr(repo, 'loaded_from_compliance_output', False):
            load_source = 'CIS Compliance'
            loaded = True
        else:
            # If no "from tenancy" or "from compliance", but data_as_of is set, treat as cache
            if getattr(repo, 'data_as_of', None):
                load_source = 'Cache'
                loaded = True

        # Get timestamp
        if loaded:
            dt_value = getattr(repo, 'data_as_of', None)
            ts_str = ''
            if dt_value:
                # Try format as "YYYY-MM-DD HH:MM UTC", stripping off seconds, Z, etc.
                try:
                    dt_obj = dtparser.parse(dt_value)
                    ts_str = dt_obj.strftime('%Y-%m-%d %H:%M UTC')
                except Exception:
                    ts_str = dt_value
            # Check policy_data_reloaded
            reloaded_str = ''
            reload_time = getattr(repo, 'policy_data_reloaded', None)
            if reload_time and str(reload_time).strip():
                try:
                    reloaddt = dtparser.parse(reload_time)
                    reloaded_str = f' [Reloaded at {reloaddt.strftime("%Y-%m-%d %H:%M UTC")}]'
                except Exception:
                    reloaded_str = f' [Reloaded at {reload_time}]'
            else:
                reloaded_str = ''

            # Prefix status text with Experimental Mode marker if enabled
            prefix = '**Experimental Mode**  -  ' if self.experimental_features else ''
            core_text = f'{prefix}Policy Data: {load_source} loaded at {ts_str}{reloaded_str}'
            tracking_suffix = (
                ' | Tool Usage Tracking: On'
                if self.settings.get('usage_tracking_enabled')
                else ' | Tool Usage Tracking: Off'
            )
            self.status_var.set(core_text + tracking_suffix)
        else:
            # Not loaded
            prefix = '**Experimental Mode**  -  ' if self.experimental_features else ''
            core_text = f'{prefix}Policy Data: (Not Loaded)'
            tracking_suffix = (
                ' | Tool Usage Tracking: On'
                if self.settings.get('usage_tracking_enabled')
                else ' | Tool Usage Tracking: Off'
            )
            self.status_var.set(core_text + tracking_suffix)

    def refresh_all_tabs_settings(self):
        """
        Call apply_settings (context help and font) for all tabs that support it.
        """
        tabs = [
            self.settings_tab,
            self.policy_browser_tab,
            self.policies_tab,
            self.users_tab,
            self.dynamic_groups_tab,
            self.resource_principals_tab,
            self.cross_tenancy_tab,
            self.historical_tab,
            self.mcp_tab,
            self.permissions_report_tab,
            self.condition_tester_tab,
            self.tag_based_access_tab,
            self.policy_recommendations_tab,
            self.reports_tab,
            self.simulation_tab,
            self.debugger_tab,
            self.console_tab,
            self.maintenance_tab,
            self.consolidation_tab,
        ]
        context_help = self.settings.get('context_help', True)
        font_size = self.settings.get('font_size', 'Medium')
        for tab in tabs:
            if hasattr(tab, 'apply_settings'):
                try:
                    tab.apply_settings(context_help=context_help, font_size=font_size)
                except Exception:
                    pass

    # Theme switching via settings/config/combobox is removed; theme is fixed to 'clam'.
    # The following remains solely for font size setting.
    def apply_theme(self, *args):
        """
        Apply the selected font size from settings to the application style.
        Not currently exposed in UI, but used at startup to set font size from saved settings.

        TODO: Expand to full theme support if desired.

        Args:

            *args: Optional arguments (not used).
        """
        sizes = {'Small': 9, 'Medium': 11, 'Large': 13, 'Extra Large': 15}
        size = sizes.get(self.settings_tab.font_var.get(), 11)
        logger.info(f'Applying font size: {self.settings_tab.font_var.get()} ({size}px)')
        families = tkfont.families()
        family = 'Oracle Sans' if 'Oracle Sans' in families else 'Helvetica'

        font = (family, size)
        self.style.configure('.', font=font)

        # Update status bar font to keep in sync with app font
        if hasattr(self, 'status_font'):
            self.status_font.config(family=family, size=size)
        if hasattr(self, 'status_bar'):
            self.status_bar.configure(font=self.status_font)

        treeview_font = size * 2
        self.style.configure('Treeview', rowheight=treeview_font)

        self.settings_service.set('font_size', self.settings_tab.font_var.get())
        self.settings_service.save()
        logger.info(f'Font size set to {self.settings_tab.font_var.get()} ({size}px)')

        # Refresh all tab settings (context help & font) after applying font size
        self.refresh_all_tabs_settings()

    # All output is now plain text only.

    def toggle_bottom(self):
        """
        Toggle the visibility of the bottom output frame. Only available after AI is set up.
        """
        if not self.genai_feature_enabled:
            logger.debug('Ignoring AI pane toggle because the OCI GenAI feature is disabled.')
            return
        if self.bottom_frame.winfo_ismapped():
            try:
                self.settings['sashpos'] = self.pw.sashpos(0)
            except Exception:
                pass
            self.pw.forget(self.bottom_frame)
            self.settings_service.save()
        else:
            self.pw.add(self.bottom_frame, weight=1)
            self.settings_service.save()
            self.after(120, self._restore_sash)

    def _restore_sash(self):
        """
        Restore the sash position of the PanedWindow from saved settings.
        """
        pos = self.settings.get('sashpos')
        if pos is not None:
            try:
                max_y = max(120, self.winfo_height() - 120)
                self.pw.sashpos(0, min(pos, max_y))
            except Exception:
                pass

    def _apply_log_level(self, *args):
        self.settings_service.set('log_level', self.log_level_var.get())
        set_log_level(self.log_level_var.get())
        self.settings_service.save()
        logger.info(
            f'Log level set to {self.log_level_var.get()}. To use DEBUG, you must start from shell using --verbose'
        )

    def _post_load_create_intelligence(self):
        """Internal: Run all post-load policy intelligence analyses and rebuild simulation index."""
        # (re)create the PolicyIntelligenceEngine
        self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)

        logger.info('Running post-load policy intelligence analyses')
        start_post_process_time = time.perf_counter()
        logger.info('Calculating effective compartments for all policy statements')
        self.policy_intelligence.calculate_all_effective_compartments()
        logger.info('Running intelligence strategies (risk, supersession, cleanup, recommendations)')
        self.policy_intelligence.run_all(enabled_strategy_ids=None, params={})
        # This report uses parsed policy subjects, statements, and hierarchy.
        # Partial CIS imports supply those inputs, including inferred principal
        # domains and names, even when group membership data is absent.
        logger.info('Building permissions report from loaded policy statements')
        self.policy_intelligence.build_permissions_report()

        self.simulation_engine = PolicySimulationEngine(self.policy_compartment_analysis, self.reference_data_repo)
        # (Re)create the tenancy-scoped ProspectiveStatementsService so
        # that prospective (what-if) policy statements are managed as
        # part of the tenancy data model instead of being owned by a
        # single UI tab. The service is responsible for hydrating the
        # simulation engine with any saved prospective statements.
        tenancy_key = getattr(self.policy_compartment_analysis, 'tenancy_ocid', None)
        if tenancy_key:
            try:
                self.prospective_service = ProspectiveStatementsService(
                    cache_manager=self.caching,
                    policy_repo=self.policy_compartment_analysis,
                    tenancy_ocid=str(tenancy_key),
                    simulation_engine=self.simulation_engine,
                )
                logger.info(
                    'Post-load: ProspectiveStatementsService initialized for tenancy %s with %d records',
                    tenancy_key,
                    len(self.prospective_service.list_all()),
                )
                # Ensure the simulation engine has the latest
                # prospective statements for this tenancy.
                self.simulation_engine.set_prospective_statements(self.prospective_service.to_simple_list())
            except Exception:
                logger.warning(
                    'Post-load: unable to initialize ProspectiveStatementsService; '
                    'prospective statements will fall back to legacy settings-based handling.',
                    exc_info=True,
                )
        else:
            logger.info(
                'Post-load: tenancy_ocid not set on PolicyAnalysisRepository; '
                'ProspectiveStatementsService will not be initialized yet.'
            )
        # self.simulation_engine.build_index()
        logger.info('Rebuilt Simulation Engine index after post-load intelligence.')
        end_post_process_time = time.perf_counter()
        logger.info(
            f'Post-load policy intelligence analyses (including simulation index) completed in {end_post_process_time - start_post_process_time:.2f} seconds'
        )

    def _post_load_update_ui(self):
        """Internal: Re-enable and update UI components after data load."""
        import time

        timings = []
        start = time.perf_counter()

        # Wrapper for calling of load functions with timing and logging
        def step(label, fn):
            t0 = time.perf_counter()
            fn()
            t1 = time.perf_counter()
            elapsed = t1 - t0
            timings.append((label, elapsed))
            # Log at CRITICAL if always_log_timings, else INFO
            log_critical = self.settings.get('always_log_timings', False)
            msg = f'[UI Timing] {label}: {elapsed:.2f}s'
            if log_critical:
                logger.critical(msg)
            else:
                logger.info(msg)

        # Users tab: single populate_data entry point keeps other public
        # methods available for direct use (e.g. callbacks) while providing a
        # clear orchestration hook for initial load.
        step('users_tab.populate_data', self.users_tab.populate_data)
        step('policies_tab.update_policy_output', self.policies_tab.update_policy_output)
        step('policies_tab.enable_widgets_after_load', self.policies_tab.enable_widgets_after_load)
        if hasattr(self, 'policy_browser_tab') and hasattr(self.policy_browser_tab, 'post_load_update_ui'):
            step('policy_browser_tab.post_load_update_ui', self.policy_browser_tab.post_load_update_ui)
        else:
            if hasattr(self, 'policy_browser_tab') and hasattr(
                self.policy_browser_tab, '_update_reload_policy_button_state'
            ):
                step(
                    'policy_browser_tab._update_reload_policy_button_state',
                    self.policy_browser_tab._update_reload_policy_button_state,
                )
            step('policy_browser_tab.refresh_tree', self.policy_browser_tab.refresh_tree)
        step('dynamic_groups_tab.populate_data', self.dynamic_groups_tab.populate_data)
        step('cross_tenancy_tab.update_cross_tenancy_output', self.cross_tenancy_tab.update_cross_tenancy_output)
        step('resource_principals_tab.update_principals_sheets', self.resource_principals_tab.update_principals_sheets)
        step(
            'historical_tab.populate_cache_dropdowns',
            lambda: self.historical_tab.populate_cache_dropdowns(
                tenancy_name=self.policy_compartment_analysis.tenancy_name
            ),
        )
        step('permissions_report_tab.enable_widgets_after_load', self.permissions_report_tab.enable_widgets_after_load)
        step('simulation_tab.populate_data', self.simulation_tab.populate_data)
        step('tag_based_access_tab.populate_data', self.tag_based_access_tab.populate_data)
        step('policy_recommendations_tab.populate_data', self.policy_recommendations_tab.populate_data)
        step('reports_tab.populate_data', self.reports_tab.populate_data)
        if self.consolidation_tab:
            step('consolidation_tab.populate_data', self.consolidation_tab.populate_data)
        self._update_compliance_capability_ui()
        logger.info(
            'UI post-load timing (seconds): '
            + ' | '.join([f'{label}: {elapsed:.2f}' for label, elapsed in timings])
            + f' | TOTAL: {time.perf_counter() - start:.2f}s'
        )
        logger.info('All tabs reloaded after data load.')

    def reload_policies_and_compartments_and_update_cache(self):
        """
        Reload just policies, compartments, statements (not IAM) from tenancy,
        update the 'policy_data_reloaded' timestamp, persist sections in cache,
        and update all UI components as if a tenancy load had completed.
        Legacy synchronous reload path.
        """
        logger.info(
            'Initiating reload of policies and compartments (main driver, includes cache update and UI refresh)'
        )
        repo = self.policy_compartment_analysis
        if not hasattr(repo, 'reload_compartment_policy_data'):
            logger.error('reload_compartment_policy_data method not present on PolicyAnalysisRepository.')
            return False

        reload_ok = repo.reload_compartment_policy_data()
        if not reload_ok:
            logger.error('reload_compartment_policy_data failed, policies/compartments not reloaded')
            return False

        # Now update the cache for just these sections
        try:
            self.cache_service.update_policy_section(repo, policy_data_reloaded=repo.policy_data_reloaded)
        except Exception as e:
            logger.error(f'Policy/compartment cache update failed after reload: {e}')

        # Re-run policy intelligence (effective compartments, invalid statements, cleanup, recommendations)
        self._post_load_create_intelligence()

        # Update the UI (replicates post-load signal)
        self._post_load_update_ui()
        # Update status bar to indicate reload
        self.after(0, self.update_status_bar)
        logger.info('Reload policies/compartments complete; cache and UI updated')
        return True

    def _build_data_load_summary(self) -> str:
        """Build a short, human-readable repository summary for completion messages."""
        repo = getattr(self, 'policy_compartment_analysis', None)
        if repo is None:
            return ''
        try:
            compartments = len(getattr(repo, 'compartments', []) or [])
            policies = len(getattr(repo, 'policies', []) or [])
            statements = len(getattr(repo, 'regular_statements', []) or [])
            groups = len(getattr(repo, 'groups', []) or [])
            users = len(getattr(repo, 'users', []) or [])
            return (
                f'Summary: {compartments} compartments, {policies} policies, '
                f'{statements} statements, {groups} groups, {users} users.'
            )
        except Exception:
            return ''

    def _show_policy_reload_progress_dialog(
        self,
        title: str = 'Reloading Policy Data',
        intro_text: str = 'Please wait while policy data reload completes...',
    ):
        """Show a small modal progress dialog for policy reload operations."""
        try:
            if self._policy_reload_dialog and self._policy_reload_dialog.winfo_exists():
                return
        except Exception:
            pass

        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=intro_text).pack(anchor='w')
        ttk.Label(frame, textvariable=self._policy_reload_message_var, foreground='blue').pack(anchor='w', pady=(8, 8))

        bar = ttk.Progressbar(frame, mode='indeterminate', length=735)
        bar.pack(fill='x')
        bar.start(12)

        # Prevent manual close while reload is active.
        dialog.protocol('WM_DELETE_WINDOW', lambda: None)

        # Center dialog over parent.
        self.update_idletasks()
        try:
            width = 828
            height = 120
            x = self.winfo_rootx() + (self.winfo_width() // 2) - (width // 2)
            y = self.winfo_rooty() + (self.winfo_height() // 2) - (height // 2)
            dialog.geometry(f'{width}x{height}+{max(0, x)}+{max(0, y)}')
        except Exception:
            pass

        self._policy_reload_dialog = dialog

    def _close_policy_reload_progress_dialog(self):
        """Close policy reload progress dialog if currently shown."""
        dialog = getattr(self, '_policy_reload_dialog', None)
        if dialog is None:
            return
        try:
            if dialog.winfo_exists():
                dialog.grab_release()
                dialog.destroy()
        except Exception:
            pass
        finally:
            self._policy_reload_dialog = None

    def _set_policy_reload_progress_message(self, message: str):
        """Set progress message in reload progress dialog."""
        try:
            self._policy_reload_message_var.set(message)
            dialog = getattr(self, '_policy_reload_dialog', None)
            if dialog is not None and dialog.winfo_exists():
                dialog.update_idletasks()
        except Exception:
            pass

    def _publish_operation_progress(self, message: str, callback: dict | None = None, show_popup: bool = False):
        """Publish a progress stage to popup and optional callback."""
        logger.info('Load progress: %s', message)
        if show_popup:
            self.after(0, lambda m=message: self._set_policy_reload_progress_message(m))
        cb = callback.get('progress') if callback else None
        if cb is not None and callable(cb):
            self.after(0, lambda m=message, fn=cb: fn(m))

    def _finalize_operation_popup(self, show_popup: bool, success: bool, final_message: str = ''):
        """Set final popup message and close popup after a readable delay."""
        if not show_popup:
            return
        if final_message:
            self.after(0, lambda m=final_message: self._set_policy_reload_progress_message(m))
        close_delay_ms = 2200 if success else 1800
        self.after(close_delay_ms, self._close_policy_reload_progress_dialog)

    def reload_policies_and_compartments_and_update_cache_async(  # noqa: C901
        self, callback: dict | None = None, show_popup: bool = True
    ):
        """
        Non-blocking policy/compartment reload with progress dialog and callbacks.

        Callback keys (all optional):
            - progress(message: str)
            - complete(success: bool, message: str, is_error: bool)
            - error(success: bool, message: str, is_error: bool)
        """
        if self._tenancy_load_in_progress:
            messagebox.showinfo(
                'Load in progress', 'A tenancy load is already in progress. Please wait for it to complete.'
            )
            return

        if self._policy_reload_in_progress:
            messagebox.showinfo(
                'Reload in progress', 'A policy reload is already in progress. Please wait for it to complete.'
            )
            return

        self._policy_reload_in_progress = True

        if callback is None:
            callback = {}

        def publish_progress(msg: str):
            logger.info('Policy reload progress: %s', msg)
            self.after(0, lambda m=msg: self._set_policy_reload_progress_message(m))
            cb = callback.get('progress') if callback else None
            if cb is not None and callable(cb):
                self.after(0, lambda m=msg: cb(m))

        def finalize(success: bool, msg: str, error: Exception | None = None):
            def _ui_finalize():
                try:
                    if success:
                        publish_progress('Refreshing tabs and updating status...')
                        self._post_load_update_ui()
                        self.update_status_bar()
                        publish_progress(msg)
                        logger.info('Async policy reload complete; cache and UI updated')
                    else:
                        logger.error('Async policy reload failed: %s', msg)
                        if error:
                            logger.debug('Async policy reload exception details', exc_info=True)
                finally:
                    # Briefly show final "Done" status before closing the dialog.
                    close_delay_ms = 1800 if success else 1200

                    def _close_dialog_and_mark_done():
                        self._close_policy_reload_progress_dialog()
                        self._policy_reload_in_progress = False

                    self.after(close_delay_ms, _close_dialog_and_mark_done)

                if success:
                    cb = callback.get('complete') if callback else None
                    if cb is not None and callable(cb):
                        cb(True, msg, False)
                else:
                    cb = callback.get('error') if callback else None
                    if cb is not None and callable(cb):
                        cb(False, msg, True)
                    else:
                        # Fallback to complete callback for consumers that only provide one handler.
                        cb_complete = callback.get('complete') if callback else None
                        if cb_complete is not None and callable(cb_complete):
                            cb_complete(False, msg, True)

            self.after(0, _ui_finalize)

        if show_popup:
            self._set_policy_reload_progress_message('Preparing reload...')
            self._show_policy_reload_progress_dialog()

        def worker():
            try:
                start = time.perf_counter()
                publish_progress('Reloading compartments and policies from tenancy...')
                repo = self.policy_compartment_analysis
                if not hasattr(repo, 'reload_compartment_policy_data'):
                    raise RuntimeError('reload_compartment_policy_data method not present on PolicyAnalysisRepository.')

                reload_ok = repo.reload_compartment_policy_data()
                if not reload_ok:
                    raise RuntimeError('reload_compartment_policy_data failed, policies/compartments not reloaded')

                publish_progress('Updating cached policy section...')
                try:
                    self.cache_service.update_policy_section(repo, policy_data_reloaded=repo.policy_data_reloaded)
                except Exception as cache_error:
                    logger.error('Policy/compartment cache update failed after reload: %s', cache_error)

                publish_progress('Running policy intelligence analyses...')
                self._post_load_create_intelligence()

                elapsed = time.perf_counter() - start
                summary = self._build_data_load_summary()
                done_msg = f'Done Loading in {elapsed:.2f}s.'
                if summary:
                    done_msg = f'{done_msg} {summary}'
                finalize(True, done_msg)
            except Exception as e:
                finalize(False, f'Policy data reload from tenancy failed: {e}', error=e)

        threading.Thread(target=worker, daemon=True).start()

    def load_tenancy_async(  # noqa: C901
        self,
        tenancy_id,
        recursive,
        instance_principal,
        named_profile=None,
        named_session=None,
        named_cache=None,
        load_all_users=True,
        compartment_domain_search_depth=1,  # New parameter!
        callback=None,
        show_popup: bool = False,
    ):
        """
        Asynchronously loads tenancy data, policies, and compartments.  Requires parameters for authentication method, whether to load compartments recursively, and optional named profile/session/cache.

        Args:
            tenancy_id (str): The OCID of the tenancy to load.
            recursive (bool): Whether to load compartments recursively.
            instance_principal (bool): Whether to use instance principal authentication.
            named_profile (str): The named profile to use for authentication.
            named_session (str): The named session token if applicable.
            named_cache (str): The named cache file to load if applicable.
            load_all_users (bool): Whether to load all users from identity domains.
            compartment_domain_search_depth (int): How many levels below root to enumerate for domains (1 = root only).
            callback (dict, optional): A dictionary of callback functions for progress, error, and completion
            show_popup (bool): Whether to show modal progress popup for initial tenancy load.
        """
        logger.info(
            f'Starting async tenancy load: {tenancy_id} (recursive={recursive}, ip={instance_principal}, domain_enum_depth={compartment_domain_search_depth})'
        )

        if self._tenancy_load_in_progress:
            messagebox.showinfo(
                'Load in progress',
                'A tenancy load is already in progress. Please wait for it to complete.',
            )
            return

        self._tenancy_load_in_progress = True

        if show_popup:
            self._set_policy_reload_progress_message('Preparing tenancy load...')
            self._show_policy_reload_progress_dialog(
                title='Loading Tenancy Data',
                intro_text='Please wait while tenancy data is loaded...',
            )

        def worker():  # noqa: C901
            """Worker thread to load tenancy data."""
            popup_final_message = ''
            popup_success = False

            try:
                success = False
                start_time = time.perf_counter()

                # Upon re-load, start a new repository to clear prior data
                self.policy_compartment_analysis.reset_state()
                logger.info('Reset PolicyAnalysisRepository state for tenancy load.')

                if named_cache:
                    logger.info(f'Using named cache: {named_cache}')
                    cache_result = self.load_service.load_from_cache(
                        cache_name=named_cache,
                        run_post_load_intelligence=False,
                    )
                    success = bool(cache_result.success)
                    # Patch: Ensure tenancy_name is set so all downstream UI consumers work
                    repo = self.policy_compartment_analysis
                    if not hasattr(repo, 'tenancy_name') or repo.tenancy_name is None:
                        # Try to infer name from data, fallback to tenancy_ocid string if not available
                        if hasattr(repo, 'tenancy_ocid') and repo.tenancy_ocid:
                            repo.tenancy_name = str(repo.tenancy_ocid)
                        else:
                            repo.tenancy_name = 'Loaded from Cache'

                    # Update usage tracking tenancy suffix for cache-based loads
                    try:
                        tracker = get_usage_tracker()
                        if tracker is not None:
                            tenancy_ocid = getattr(repo, 'tenancy_ocid', '') or ''
                            tracker.set_tenancy_suffix(tenancy_ocid[-6:] if tenancy_ocid else None)
                            # Record non-personal load source for analytics (cache).
                            tracker.track_operation('data_load', source='cache')
                    except Exception:
                        pass

                elif named_profile or instance_principal or named_session:
                    if instance_principal:
                        logger.info(f'Using Instance Principal: {instance_principal}')
                    elif named_session:
                        logger.info(f'Using named session: {named_session}')
                    else:
                        logger.info(f'Using named profile: {named_profile}')

                    tenancy_result = self.load_service.load_from_tenancy(
                        use_instance_principal=instance_principal,
                        profile=(named_profile or ''),
                        session_token=named_session,
                        recursive=recursive,
                        load_all_users=load_all_users,
                        compartment_domain_search_depth=compartment_domain_search_depth,
                        run_post_load_intelligence=False,
                        on_stage=lambda stage, detail, state: self._publish_operation_progress(
                            f'{stage}: {detail}' if detail else stage,
                            callback=callback,
                            show_popup=show_popup,
                        ),
                    )
                    success = bool(tenancy_result.success)
                    if not success:
                        raise RuntimeError(tenancy_result.message)

                    # Update usage tracking tenancy suffix for live-tenancy loads
                    try:
                        tracker = get_usage_tracker()
                        if tracker is not None:
                            tenancy_ocid = getattr(self.policy_compartment_analysis, 'tenancy_ocid', '') or ''
                            tracker.set_tenancy_suffix(tenancy_ocid[-6:] if tenancy_ocid else None)
                            # Record non-personal load source for analytics (live tenancy).
                            tracker.track_operation(
                                'data_load',
                                source='live',
                                recursive=bool(recursive),
                                instance_principal=bool(instance_principal),
                                named_profile=bool(named_profile),
                                named_session=bool(named_session),
                            )
                    except Exception:
                        pass

                    # Ensure status bar shows loaded data
                    self.after(0, self.update_status_bar)

                    # Save cache after loading from tenancy
                    self.cache_service.save_cache(self.policy_compartment_analysis)
            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')
                popup_final_message = f'Load failed: {e}'

                if callback:
                    cb = callback.get('error')
                    if cb is not None and callable(cb):
                        self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return
            else:
                end_time = time.perf_counter()
                elapsed = end_time - start_time
                msg = f'Done Loading in {elapsed:.2f}s.'
                logger.info(f'[OK] {msg}')

                # Ensure status bar accurately reflects finalized repo state
                self.after(0, self.update_status_bar)

                # Intelligence Running Message
                self._publish_operation_progress(
                    'Running post-load policy intelligence analyses', callback=callback, show_popup=show_popup
                )

                # Run post-load intelligence analysis
                self._post_load_create_intelligence()

                # Tabs Loading Message
                self._publish_operation_progress('Populating Tab Data', callback=callback, show_popup=show_popup)

                # Force tabs to update with new data (users, policies, compartments, cross-tenancy, etc)
                self._post_load_update_ui()

                self._publish_operation_progress('Updating status bar', callback=callback, show_popup=show_popup)

                summary = self._build_data_load_summary()
                final_msg = f'{msg} {summary}'.strip()
                popup_final_message = final_msg
                popup_success = True
                if callback:
                    cb = callback.get('progress')
                    if cb is not None and callable(cb):
                        self.after(0, lambda cb=cb, m=final_msg: cb(m))

                # Show completion message
                if callback:
                    cb = callback.get('complete')
                    if cb is not None and callable(cb):
                        self.after(0, lambda msg=final_msg: cb(True, msg, False))  # type: ignore

                logger.info('Tenancy Load complete. Reloading all tabs')

                # Ensure status bar accurately reflects finalized repo state
                self.after(0, self.update_status_bar)
            finally:
                self._finalize_operation_popup(show_popup, popup_success, popup_final_message)
                self.after(0, lambda: setattr(self, '_tenancy_load_in_progress', False))

        threading.Thread(target=worker, daemon=True).start()

    def load_compliance_output_async(
        self,
        dir_path: str,
        callback: dict | None = None,
        load_all_users: bool = True,
        show_popup: bool = False,
    ):  # noqa: C901
        """
        Asynchronously loads policy, compartment, group, user, dynamic group, and domain data from compliance output .csv files.
        Args:
            dir_path (str): The directory containing compliance output files as per spec.
            callback (dict, optional): Callbacks for progress, error, and complete.
            load_all_users (bool, optional): If False, skip loading users. Defaults to True.
        """
        logger.info(
            f'[ASYNC] Loading compliance analysis data from directory: {dir_path} (load_all_users={load_all_users})'
        )

        if show_popup:
            self._set_policy_reload_progress_message('Preparing compliance data load...')
            self._show_policy_reload_progress_dialog(
                title='Loading Compliance Output Data',
                intro_text='Please wait while compliance output data is loaded...',
            )

        def worker():
            popup_final_message = ''
            popup_success = False
            try:
                start_time = time.perf_counter()
                # Upon re-load, start a new repository to clear prior data
                self.policy_compartment_analysis.reset_state()

                self._publish_operation_progress(
                    'Loading compliance output data', callback=callback, show_popup=show_popup
                )
                result = self.load_service.load_from_compliance_output(
                    dir_path,
                    load_all_users=load_all_users,
                    run_post_load_intelligence=False,
                )
                success = bool(result.success)
                if not success:
                    popup_final_message = result.message
                    logger.error(popup_final_message)
                    error_cb = callback.get('error') if callback else None
                    if error_cb is not None and callable(error_cb):
                        self.after(0, lambda m=popup_final_message: error_cb(False, m, True))
                    return

                # Update usage tracking tenancy suffix for compliance-output loads
                try:
                    tracker = get_usage_tracker()
                    if tracker is not None:
                        tenancy_ocid = getattr(self.policy_compartment_analysis, 'tenancy_ocid', '') or ''
                        tracker.set_tenancy_suffix(tenancy_ocid[-6:] if tenancy_ocid else None)
                        # Record non-personal load source for analytics (CIS compliance output).
                        tracker.track_operation('data_load', source='compliance')
                except Exception:
                    pass
                msg = f'Loaded compliance data from {dir_path}'
                logger.info(msg)
                # Post-processing after load
                # self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)
                self._publish_operation_progress(
                    'Running post-load policy intelligence analyses', callback=callback, show_popup=show_popup
                )
                # Ensure status bar accurately reflects finalized repo state
                self.after(0, self.update_status_bar)
                self._post_load_create_intelligence()

                self._publish_operation_progress('Populating Tab Data', callback=callback, show_popup=show_popup)
                self._post_load_update_ui()

                self._publish_operation_progress('Updating status bar', callback=callback, show_popup=show_popup)
                self.after(0, self.update_status_bar)

                elapsed = time.perf_counter() - start_time
                summary = self._build_data_load_summary()
                final_msg = f'Done Loading in {elapsed:.2f}s. {summary}'.strip()
                popup_final_message = final_msg
                popup_success = bool(success)

                complete_cb = callback.get('complete') if callback else None
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda m=final_msg: complete_cb(success, m, not success))
                if success:
                    logger.info('[OK] Compliance Output Load complete. Reloading all tabs.')

            except Exception as e:
                logger.error(f'Error occurred during compliance output load: {e}')
                popup_final_message = f'Compliance load failed: {e}'
                # Show stack trace if debug on main
                if logger.isEnabledFor(logging.DEBUG):
                    traceback.print_exc()
                error_cb = callback.get('error') if callback else None
                if error_cb is not None and callable(error_cb):
                    self.after(0, lambda e=e: error_cb(False, f'Compliance load failed: {e}', True))
            finally:
                self._finalize_operation_popup(show_popup, popup_success, popup_final_message)

        threading.Thread(target=worker, daemon=True).start()

    def _import_cache_from_json(self, callback: dict | None = None, show_popup: bool = False):  # noqa: C901
        """
        Imports cached policy analysis data from a JSON file selected by the user.

        Args:
            callback (dict, optional): A dictionary of callback functions for progress, error, and completion.
        """
        if callback is None:
            callback = {}
        if show_popup:
            self._set_policy_reload_progress_message('Preparing JSON import...')
            self._show_policy_reload_progress_dialog(
                title='Importing JSON Cache',
                intro_text='Please wait while cache data is imported...',
            )
        filepath = tkfiledialog.askopenfilename(filetypes=[('JSON Files', '*.json')])
        if filepath:
            popup_success = False
            popup_final_message = ''
            try:
                start_time = time.perf_counter()
                logger.info(f'Importing cached data from file: {filepath}')
                self._publish_operation_progress('Loading from JSON file', callback=callback, show_popup=show_popup)
                with open(filepath, encoding='utf-8') as jsonfile:
                    loaded_json = json.load(jsonfile)
                    logger.debug(f'JSON Data: {loaded_json}')
                success = self.cache_service.import_from_json(
                    loaded_json=loaded_json, policy_repo=self.policy_compartment_analysis
                )
                # Patch: Ensure tenancy_name is set so all downstream UI consumers work
                repo = self.policy_compartment_analysis
                if not hasattr(repo, 'tenancy_name') or repo.tenancy_name is None:
                    # Try to infer name from data, fallback to tenancy_ocid string if not available
                    if hasattr(repo, 'tenancy_ocid') and repo.tenancy_ocid:
                        repo.tenancy_name = str(repo.tenancy_ocid)
                    else:
                        repo.tenancy_name = 'Loaded from Cache'
                if success:
                    self.last_load_time = self.policy_compartment_analysis.data_as_of
                    logger.info(f'***Loaded cached data from file as of {self.last_load_time}')
                    logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
                    # Ensure status bar accurately reflects finalized repo state after cache load
                    self.after(0, self.update_status_bar)
                    # Record non-personal load source for analytics (JSON cache file).
                    try:
                        tracker = get_usage_tracker()
                        if tracker is not None:
                            tenancy_ocid = getattr(self.policy_compartment_analysis, 'tenancy_ocid', '') or ''
                            tracker.set_tenancy_suffix(tenancy_ocid[-6:] if tenancy_ocid else None)
                            tracker.track_operation('data_load', source='json_file')
                    except Exception:
                        pass
                    # Show intelligence running message (same pattern as tenancy load)
                    self._publish_operation_progress(
                        'Running post-load policy intelligence analyses', callback=callback, show_popup=show_popup
                    )
                    # Run the same post-load intelligence and UI update steps as a tenancy load
                    self._post_load_create_intelligence()
                complete_cb = callback.get('complete') if callback else None
                self._publish_operation_progress('Populating Tab Data', callback=callback, show_popup=show_popup)
                self._post_load_update_ui()
                self._publish_operation_progress('Updating status bar', callback=callback, show_popup=show_popup)
                self.after(0, self.update_status_bar)
                elapsed = time.perf_counter() - start_time
                summary = self._build_data_load_summary()
                final_msg = f'Done Loading in {elapsed:.2f}s. {summary}'.strip()
                popup_success = bool(success)
                popup_final_message = final_msg
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda s=bool(success), m=final_msg: complete_cb(s, m, not s))
                else:
                    logger.warning('Failed to load from saved cache')

                logger.info('Cache Load JSON complete - Reload all tabs')
            except Exception as e:
                logger.error(f'Error importing policies from CSV: {e}')
                popup_final_message = f'JSON import failed: {e}'
                error_cb = callback.get('error') if callback else None
                if error_cb is not None and callable(error_cb):
                    self.after(0, lambda: error_cb(False, 'Failed to load from JSON file', True))
            finally:
                self._finalize_operation_popup(show_popup, popup_success, popup_final_message)

    def _export_cache_to_json(self):
        """
        Exports the current cached policy analysis data to a JSON file selected by the user.
        """
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {type(filepath)} {filepath.name}')
            self.cache_service.save_cache(self.policy_compartment_analysis, export_file=filepath)
            logger.info(f'Wrote file {filepath.name}')
        else:
            logger.info('Export cancelled by user')

    def ask_genai_async(self, prompt: str, additional_instruction: str = '', callback=None, test_call: bool = False):
        """
        Asynchronously queries the GenAI model with the given prompt and additional instructions.

        Args:
            prompt (str): The main prompt to send to the GenAI model.
            additional_instruction (str, optional): Any additional instructions to include in the query.
            callback (dict, optional): A dictionary of callback functions for different stages of the query.
        """
        if not self.genai_feature_enabled:
            message = 'OCI GenAI is disabled. Launch with --enable-genai to use this preview feature.'
            logger.warning(message)
            if callable(callback):
                self.after(0, lambda: callback(success=False, message=message))
            return
        logger.info(f'Submitting GenAI prompt: {prompt} with additional instructions: {additional_instruction}')
        self.set_bottom_output(content=f'Querying GenAI for:\n\n{prompt}', test_call=test_call)

        def worker():
            try:
                start_time = time.perf_counter()
                self.after(0, lambda: self.ai_progress_var.set('[...] Running AI Query'))
                logger.debug('Starting ai.analyze_policy_statement asyncio.run in thread')
                q = queue.Queue()
                # Always ask for plain text output now, no more toggles
                asyncio.run(
                    self.ai.analyze_policy_statement(
                        policy_text=prompt, format='Text', additional_instruction=additional_instruction, queue=q
                    )
                )
                logger.debug(
                    'Finished ai.analyze_policy_statement asyncio.run in thread, waiting for result from queue'
                )
                ai_text_response = q.get()  # Get the result from the queue
                logger.debug(f'Received AI result from queue, posting update to UI: {ai_text_response}')

                # Track AI Assist usage once per call, including timing, model, tab, and setup/normal flag.
                try:
                    tracker = get_usage_tracker()
                    if tracker is not None:
                        current_tab_name: str | None = None
                        try:
                            selected_tab_id = self.notebook.select()
                            selected_widget = self.nametowidget(selected_tab_id) if selected_tab_id else None
                            if selected_widget is not None:
                                current_tab_name = type(selected_widget).__name__
                        except Exception:
                            current_tab_name = None

                        is_error = isinstance(ai_text_response, str) and ai_text_response.startswith('Error:')
                        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                        tracker.track_operation(
                            'ai_assist',
                            success=not is_error,
                            model=getattr(self.ai, 'model_ocid', None) or getattr(self.ai, 'model_id', None),
                            tab=current_tab_name,
                            duration_ms=round(elapsed_ms, 2),
                            is_setup_call=bool(test_call),
                        )
                except Exception:
                    logger.debug('AI usage tracking (ai_assist) failed', exc_info=True)
                self.after(0, lambda: self.set_bottom_output(content=str(ai_text_response), test_call=test_call))

                if callable(callback):
                    if ai_text_response.startswith('Error:'):
                        self.after(
                            0,
                            lambda cb=callback: cb(
                                success=False,
                                message=f'GenAI query failed: {ai_text_response.lstrip("**Error:** ")}',  # noqa: B005
                            ),  # type: ignore
                        )
                    else:
                        self.after(0, lambda cb=callback: cb(success=True, message='Set up AI successfully'))

                self.after(
                    0,
                    lambda: self.ai_progress_var.set(
                        f'[OK] Finished AI Call ({time.perf_counter() - start_time:.2f}ms)'
                    ),
                )
            except Exception as e:
                logger.error(f'GenAI request failed: {e}')
                self.after(0, lambda e=e: self.set_bottom_output(f'**Error:** {str(e)}', test_call=test_call))
                if callable(callback):
                    self.after(0, lambda e=e, cb=callback: cb(success=False, message=f'Failed AI: {e}'))

        threading.Thread(target=worker, daemon=True).start()

    def set_bottom_output(self, content: str, test_call: bool = False):
        """
        Display the given string content as plain text in the output_text widget.

        Args:
            content (str): The text content to display in the output area.
            test_call (bool): Indicates if this is a test call to set output.
        """

        output_string = content
        if content and not content.startswith('<'):
            try:
                maybe_json = json.loads(content)
                if (
                    isinstance(maybe_json, list)
                    and len(maybe_json) > 0
                    and isinstance(maybe_json[0], dict)
                    and 'text' in maybe_json[0]
                ):
                    output_string = maybe_json[0]['text']
            except Exception:
                output_string = content

        # If test call, don't add the response to the widget, just print it to the console and save it to last_output_text for potential copying.
        if test_call:
            logger.info(f'Test call - output: {output_string}')
            return
        # Actually put it in the display
        self.last_output_text = output_string or ''
        self.output_text.configure(state='normal')
        self.output_text.delete('1.0', tk.END)
        self.output_text.insert(
            tk.END, self.last_output_text if self.last_output_text else 'Policy AI will appear here.'
        )
        self.output_text.configure(state='disabled')

        # Enable or disable the copy button
        if self.last_output_text and self.last_output_text.strip():
            self.copy_txt_btn.configure(state='normal')
        else:
            self.copy_txt_btn.configure(state='disabled')

    def copy_output_text(self):
        """
        Copies the current output text to the clipboard if it is non-empty.
        """
        if self.last_output_text and self.last_output_text.strip():
            self.clipboard_clear()
            self.clipboard_append(self.last_output_text)
            self.update()

    def open_link(self, link):
        """
        Opens the given web link in the default browser.

        Args:
            link (str): The URL to open.
        """
        logger.info(f'Opening web link: {link}')
        webbrowser.open_new(link)

    def open_condition_tester_with_condition(self, condition_text):
        """
        Open the Condition Tester tab, populate it with the given condition string,
        auto-generate inputs for it, and switch focus to this tab.

        Args:
            condition_text (str): The condition string to test.
        """
        logger.info(f'Opening Condition Tester tab with condition: {condition_text}')
        self.notebook.select(self.condition_tester_tab)
        self.condition_tester_tab.clause_var.set(condition_text)
        self.condition_tester_tab._generate_inputs()

    def _on_tab_changed(self, event):
        """
        Auto-disable AI pane if navigating to a tab that does not support it.
        Update AI Assist button on supported tab.
        """
        # Only these tabs support AI currently (can expand this in the future)
        supported_tabs = {
            str(self.policy_browser_tab),
            str(self.policies_tab),
            str(self.users_tab),
            str(self.dynamic_groups_tab),
            str(self.resource_principals_tab),
            # str(self.cross_tenancy_tab),
        }
        # Which tab is now selected?
        selected_tab_id = self.notebook.select()
        # All tabs: list of tab IDs -> widget names
        # e.g. tuple(self.notebook.tabs())
        # e.g. self.notebook.nametowidget(selected_tab_id)
        selected_widget = self.nametowidget(selected_tab_id) if selected_tab_id else None

        # # When switching to Settings tab, refresh Additional Identity Domain Compartment OCIDs from persisted settings
        # if selected_widget is self.settings_tab:
        #     refresh_fn = getattr(self.settings_tab, '_refresh_domain_compartment_ocids_from_settings', None)
        #     if callable(refresh_fn):
        #         refresh_fn()

        # Anonymous usage tracking: record tab changes (if enabled)
        try:
            tracker = get_usage_tracker()
            if tracker is not None and selected_widget is not None:
                # Use the tab's class name as a stable key
                tab_name = type(selected_widget).__name__
                tracker.track('tab_change', tab_name=tab_name)
        except Exception:
            pass

        # If the new tab is NOT in supported, and AI (bottom_frame) is shown, hide it.
        if self.genai_feature_enabled and selected_widget is not None and str(selected_widget) not in supported_tabs:
            if self.bottom_frame.winfo_ismapped():
                logger.info('AI pane will be hidden due to tab switch to unsupported tab.')
                self.toggle_bottom()
        # # Update AI Assist button (Policy Browser Tab only for now)
        # if hasattr(self, "policy_browser_tab") and hasattr(self.policy_browser_tab, "update_ai_assist_button"):
        #     self.policy_browser_tab.update_ai_assist_button()


def main() -> None:
    """Main entry point for OCI Policy Analysis application."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    parser.add_argument(
        '--experimental-features',
        action='store_true',
        help=argparse.SUPPRESS,  # Hidden/undocumented flag to enable preview features
    )
    parser.add_argument(
        '--enable-genai',
        action='store_true',
        help=argparse.SUPPRESS,  # Hidden preview flag for the desktop OCI GenAI UI.
    )
    # parser.add_argument('--console-log', action='store_true', help='Log to console instead of file', default=False)

    args = parser.parse_args()

    # Print a welcome message with version info at startup
    logger.info('--- Starting OCI Policy Analysis Application ---')
    logger.info(f'Application version: {__version__}')
    logger.info(f'Python version: {platform.python_version()}')
    logger.info(f'OCI SDK version: {oci.__version__}')

    # --- OVERRIDE: Force ALL loggers to DEBUG level if --verbose is set ---
    if args.verbose:
        import logging

        # Set root logger level to DEBUG
        logging.getLogger().setLevel(logging.DEBUG)
        # Set all existing loggers (regardless of name) to DEBUG
        for _name, obj in logging.root.manager.loggerDict.items():
            if isinstance(obj, logging.Logger):
                obj.setLevel(logging.DEBUG)
        logger.debug('Verbose logging enabled via --verbose (all loggers set to DEBUG)')
    # ----------------------------------------------------------------------

    app = App(
        force_debug=args.verbose,
        experimental_features=args.experimental_features,
        enable_genai=args.enable_genai,
    )
    app.mainloop()

    # On clean exit, attempt to flush anonymous usage tracking so a single
    # run document is written to Object Storage (best-effort only).
    try:
        from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker

        tracker = get_usage_tracker()
        if tracker is not None:
            logger.warning('Flushing anonymous usage tracking on app exit')
            tracker.flush()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning('Failed to flush usage tracking on exit: %s', e)


if __name__ == '__main__':
    main()
