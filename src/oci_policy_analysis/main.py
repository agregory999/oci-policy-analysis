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

from dateutil import parser as dtparser

# Application imports
from oci_policy_analysis.common import config
from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.common.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.logic.ai_repo import AI  # noqa: E402

# REMOVED: ConsolidationEngine import (consolidation feature disabled)
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository  # noqa: E402
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine
from oci_policy_analysis.ui.condition_tester_tab import ConditionTesterTab
from oci_policy_analysis.ui.console_tab import ConsoleTab  # noqa: E402

# REMOVED: ConsolidationWorkbenchTab import (consolidation feature disabled)
from oci_policy_analysis.ui.cross_tenancy_tab import CrossTenancyTab  # noqa: E402
from oci_policy_analysis.ui.debugger_tab import DebuggerTab
from oci_policy_analysis.ui.dynamic_group_tab import DynamicGroupsTab  # noqa: E402
from oci_policy_analysis.ui.historical_tab import HistoricalTab  # noqa: E402
from oci_policy_analysis.ui.maintenance_tab import MaintenanceTab
from oci_policy_analysis.ui.mcp_tab import McpTab  # noqa: E402
from oci_policy_analysis.ui.permissions_report_tab import PermissionsReportTab  # noqa: E402
from oci_policy_analysis.ui.policies_tab import PoliciesTab  # noqa: E402
from oci_policy_analysis.ui.policy_browser_tab import PolicyBrowserTab
from oci_policy_analysis.ui.policy_recommendations_tab import PolicyRecommendationsTab
from oci_policy_analysis.ui.report_tab import ReportTab  # noqa: E402
from oci_policy_analysis.ui.resource_principals_tab import ResourcePrincipalsTab  # noqa: E402
from oci_policy_analysis.ui.settings_tab import SettingsTab  # noqa: E402
from oci_policy_analysis.ui.simulation_tab import SimulationTab
from oci_policy_analysis.ui.users_tab import UsersTab

# ----------- POST-IMPORT SETUP ------------
# Version extraction
try:
    __version__ = files('oci_policy_analysis').joinpath('version.txt').read_text().strip()
except Exception:
    __version__ = 'dev'

# Suppress OCI SDK datetime.utcnow() DeprecationWarning (Python 3.12+)
warnings.filterwarnings('ignore', category=DeprecationWarning, message=r'.*datetime\.datetime\.utcnow\(\).*')
# Suppress DeprecationWarnings from libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)


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

    def __init__(self, force_debug: bool = False):
        super().__init__()

        self.title(f'OCI Policy Analysis {__version__}')
        self.geometry('1400x900')

        # Shared config & logger - load settings and quietly return if nothing is loaded
        self.settings = config.load_settings()

        # === CENTRALIZED LOGGER CONFIGURATION (run before any tab is constructed) ===
        log_levels = self.settings.get('log_levels', {})
        global_log_level = log_levels.get('global_log_level', self.settings.get('global_log_level', 'INFO'))
        from oci_policy_analysis.common.logger import set_component_level

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
        self.reference_data_repo = ReferenceDataRepo()
        self.reference_data_repo.load_data()
        self.policy_compartment_analysis = PolicyAnalysisRepository()
        self.policy_compartment_analysis.settings = self.settings  # Inject settings for advanced logging
        self.policy_compartment_analysis.permission_reference_repo = (
            self.reference_data_repo
        )  # Inject reference data repo into main repo for access during loading and analysis
        self.ai = AI()
        self.simulation_engine = PolicySimulationEngine(
            policy_repo=self.policy_compartment_analysis,
            ref_data_repo=self.reference_data_repo,
        )
        self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)
        # REMOVED: Consolidation engine instantiation (consolidation feature disabled)

        # Caching Manager (policy caching only, no AI result caching)
        self.caching = CacheManager()

        # Guard: prevent overlapping tenancy loads
        self._tenancy_load_in_progress = False

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
        self.policy_browser_tab = PolicyBrowserTab(self.notebook, self, self.settings)
        self.policies_tab = PoliciesTab(self.notebook, self, self.settings)
        self.permissions_report_tab = PermissionsReportTab(self.notebook, self)
        self.users_tab = UsersTab(self.notebook, self)
        self.dynamic_groups_tab = DynamicGroupsTab(self.notebook, self)
        self.cross_tenancy_tab = CrossTenancyTab(self.notebook, self)
        self.report_tab = ReportTab(self.notebook, self, self.policy_compartment_analysis)
        self.mcp_tab = McpTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.resource_principals_tab = ResourcePrincipalsTab(self.notebook, self)
        self.historical_tab = HistoricalTab(self.notebook, caching=self.caching)
        self.policy_recommendations_tab = PolicyRecommendationsTab(self.notebook, self)
        self.console_tab = ConsoleTab(self.notebook, self)
        self.maintenance_tab = MaintenanceTab(self.notebook, self)
        self.condition_tester_tab = ConditionTesterTab(self.notebook, self)
        self.simulation_tab = SimulationTab(self.notebook, self, self.settings)
        self.debugger_tab = DebuggerTab(self.notebook, self)
        # REMOVED: ConsolidationWorkbenchTab instantiation (consolidation feature disabled)

        # Able to refresh maintenance tab with new data
        self.maintenance_tab.refresh_data()

        # Add tabs to notebook
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policy_browser_tab, text='Compartment/Policy\nBrowser')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Resource\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        self.notebook.add(self.mcp_tab, text='Embedded MCP\nServer')
        self.notebook.add(self.permissions_report_tab, text='Permissions Report\n(Advanced)')
        self.notebook.add(self.condition_tester_tab, text='Condition Tester\n(Advanced)')
        self.notebook.add(self.policy_recommendations_tab, text='Recommendations\n(Preview)')
        self.notebook.add(self.simulation_tab, text='API Simulation\n(Advanced)')
        self.notebook.add(self.debugger_tab, text='JSON Debugger\n(Internal)')
        self.notebook.add(self.console_tab, text='Console Logging\n(Internal)')
        self.notebook.add(self.maintenance_tab, text='Maintenance\n(Internal)')
        # REMOVED: Adding Consolidation Workbench tab to notebook (consolidation feature disabled)
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

        # Output area
        self.output_text = tk.Text(
            self.bottom_frame,
            wrap=tk.WORD,
            height=15,
            bg='white',
            fg='black',
            state='disabled',
            font=('Courier New', 11),
        )
        self.output_text.pack(fill='both', expand=True, padx=8, pady=8)

        # Console / Maintenance / Advanced tab Visibility
        self.console_visible = False
        self.advanced_tabs_visible = False
        self.maintenance_visible = False
        self.notebook.forget(self.console_tab)
        self.notebook.forget(self.debugger_tab)
        self.notebook.forget(self.maintenance_tab)
        self.notebook.forget(self.permissions_report_tab)
        self.notebook.forget(self.condition_tester_tab)
        self.notebook.forget(self.simulation_tab)
        self.notebook.forget(self.policy_recommendations_tab)
        # REMOVED: Forgetting consolidation_tab (consolidation feature disabled)

        # Ensure the correct font is applied from saved settings at startup
        self.after(0, self.apply_theme)

        # === STATUS BAR (Fixed 1-line) at window bottom ===
        self.status_var = tk.StringVar(value='Policy Data: (Not Loaded)')
        # Use a dedicated font for the status bar, will sync with theme/font size in apply_theme()
        self.status_font = (
            tkfont.Font(name='StatusFont', exists=True)
            if 'StatusFont' in tkfont.names()
            else tkfont.Font(
                name='StatusFont', family=self.default_font.actual('family'), size=self.default_font.actual('size')
            )
        )
        self.status_bar = ttk.Label(
            self, textvariable=self.status_var, relief=tk.SUNKEN, anchor='w', padding=4, font=self.status_font
        )
        self.status_bar.pack(side='bottom', fill='x')
        # [CROSS-PLATFORM PATCH] Improve status bar visibility on Windows by setting background/foreground.
        try:
            self.status_bar.configure(background='#FFF9CC', foreground='black', borderwidth=1)
        except Exception:
            pass  # configure fails on some ttk themes, but safe to ignore
        self.update_status_bar()

    def update_status_bar(self):
        """
        Update the status bar to reflect current policy data load status.
        Shows source, timestamp, and reload mark if applicable.
        """
        repo = getattr(self, 'policy_compartment_analysis', None)
        if not repo:
            self.status_var.set('Policy Data: (Not Loaded)')
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
                    reloaded_str = f" [Reloaded at {reloaddt.strftime('%Y-%m-%d %H:%M UTC')}]"
                except Exception:
                    reloaded_str = f' [Reloaded at {reload_time}]'
            else:
                reloaded_str = ''
            self.status_var.set(f'Policy Data: {load_source} loaded at {ts_str}{reloaded_str}')
        else:
            # Not loaded
            self.status_var.set('Policy Data: (Not Loaded)')

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
            self.policy_recommendations_tab,
            self.simulation_tab,
            self.debugger_tab,
            self.console_tab,
            self.maintenance_tab,
            # REMOVED: consolidation_tab (consolidation feature disabled)
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

        self.settings['font_size'] = self.settings_tab.font_var.get()
        config.save_settings(self.settings)
        logger.info(f'Font size set to {self.settings_tab.font_var.get()} ({size}px)')

        # Refresh all tab settings (context help & font) after applying font size
        self.refresh_all_tabs_settings()

    # All output is now plain text only.

    def toggle_bottom(self):
        """
        Toggle the visibility of the bottom output frame. Only available after AI is set up.
        """
        if self.bottom_frame.winfo_ismapped():
            try:
                self.settings['sashpos'] = self.pw.sashpos(0)
            except Exception:
                pass
            self.pw.forget(self.bottom_frame)
            config.save_settings(self.settings)
        else:
            self.pw.add(self.bottom_frame, weight=1)
            config.save_settings(self.settings)
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
        self.settings['log_level'] = self.log_level_var.get()
        set_log_level(self.log_level_var.get())
        config.save_settings(settings=self.settings)
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
        logger.info('Running intelligence strategies (risk, overlap, cleanup, recommendations)')
        self.policy_intelligence.run_all(enabled_strategy_ids=None, params={})
        logger.info('Building permissions report for advanced report tab')
        self.policy_intelligence.build_permissions_report()

        self.simulation_engine.policy_statements = self.policy_compartment_analysis.regular_statements
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

        step('users_tab.update_user_analysis_output', self.users_tab.update_user_analysis_output)
        step('users_tab.update_users_dropdown_options', self.users_tab.update_users_dropdown_options)
        step('policies_tab.update_policy_output', self.policies_tab.update_policy_output)
        step('policies_tab.enable_widgets_after_load', self.policies_tab.enable_widgets_after_load)
        step('policy_browser_tab.refresh_tree', self.policy_browser_tab.refresh_tree)
        step('dynamic_groups_tab.enable_controls', self.dynamic_groups_tab.enable_controls)
        step('cross_tenancy_tab.update_cross_tenancy_output', self.cross_tenancy_tab.update_cross_tenancy_output)
        step('resource_principals_tab.update_principals_sheets', self.resource_principals_tab.update_principals_sheets)
        step(
            'historical_tab.populate_cache_dropdowns',
            lambda: self.historical_tab.populate_cache_dropdowns(
                tenancy_name=self.policy_compartment_analysis.tenancy_name
            ),
        )
        step('dynamic_groups_tab.enable_controls (again)', self.dynamic_groups_tab.enable_controls)
        step('permissions_report_tab.enable_widgets_after_load', self.permissions_report_tab.enable_widgets_after_load)
        step('simulation_tab.refresh_dropdowns', self.simulation_tab.refresh_dropdowns)
        step('policy_recommendations_tab.populate_data', self.policy_recommendations_tab.populate_data)
        # REMOVED: step for consolidation_tab.populate_data (consolidation feature disabled)
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
            from oci_policy_analysis.common.caching import CacheManager

            CacheManager().update_policy_section(repo, policy_data_reloaded=repo.policy_data_reloaded)
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

    def load_tenancy_async(  # noqa: C901
        self,
        tenancy_id,
        recursive,
        instance_principal,
        named_profile=None,
        named_session=None,
        named_cache=None,
        load_all_users=True,
        domain_compartment_ocids=None,  # DEPRECATED, kept for API compatibility for now
        compartment_domain_search_depth=1,  # New parameter!
        callback=None,
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

        def worker():  # noqa: C901
            """Worker thread to load tenancy data."""
            try:
                success = False
                start_time = time.perf_counter()

                # Upon re-load, start a new repository to clear prior data
                self.policy_compartment_analysis.reset_state()
                logger.info('Reset PolicyAnalysisRepository state for tenancy load.')

                if named_cache:
                    logger.info(f'Using named cache: {named_cache}')
                    success = self.caching.load_combined_cache(
                        self.policy_compartment_analysis, named_cache=named_cache
                    )
                    # Patch: Ensure tenancy_name is set so all downstream UI consumers work
                    repo = self.policy_compartment_analysis
                    if not hasattr(repo, 'tenancy_name') or repo.tenancy_name is None:
                        # Try to infer name from data, fallback to tenancy_ocid string if not available
                        if hasattr(repo, 'tenancy_ocid') and repo.tenancy_ocid:
                            repo.tenancy_name = str(repo.tenancy_ocid)
                        else:
                            repo.tenancy_name = 'Loaded from Cache'

                elif named_profile or instance_principal or named_session:
                    if instance_principal:
                        logger.info(f'Using Instance Principal: {instance_principal}')
                    elif named_session:
                        logger.info(f'Using named session: {named_session}')
                    else:
                        logger.info(f'Using named profile: {named_profile}')

                    success = self.policy_compartment_analysis.initialize_client(
                        use_instance_principal=instance_principal,
                        session_token=named_session,
                        recursive=recursive,
                        profile=named_profile,
                    )
                    if not success:
                        raise RuntimeError('Failed to initialize PolicyAnalysisRepository client')

                    # Start polling the repo's progress per second
                    def poll_policy_repo_identity_progress():
                        domain_count = len(self.policy_compartment_analysis.identity_domains)
                        dynamic_group_count = len(self.policy_compartment_analysis.dynamic_groups)
                        group_count = len(self.policy_compartment_analysis.groups)
                        user_count = len(self.policy_compartment_analysis.users)
                        msg = f'Loaded {domain_count} domains, {dynamic_group_count} DGs, {group_count} groups, {user_count} users...'
                        cb = callback.get('progress') if callback else None
                        if cb is not None and callable(cb):
                            self.after(0, lambda m=msg: cb(m))
                        # Continue polling every second until loading is signaled complete
                        if not getattr(self.policy_compartment_analysis, 'identity_loaded_from_tenancy', False):
                            self.after(200, poll_policy_repo_identity_progress)

                    self.after(0, poll_policy_repo_identity_progress)

                    if callback:
                        cb = callback.get('progress')
                        if cb is not None and callable(cb):
                            self.after(0, lambda: cb('Loading Identity Domains'))

                    # Always load compartments (required for correct domain enumeration)
                    success = self.policy_compartment_analysis.load_compartments_only()
                    if not success:
                        raise RuntimeError('Failed to load compartments (required for domain discovery)')
                    # Now run identity domain discovery on loaded compartments
                    success = self.policy_compartment_analysis.load_complete_identity_domains(
                        load_all_users=load_all_users,
                        compartment_domain_search_depth=compartment_domain_search_depth,
                    )
                    if not success:
                        raise RuntimeError('Failed to load identity domains')
                    if callback:
                        cb = callback.get('progress')
                        if cb is not None and callable(cb):
                            self.after(0, lambda: cb('Loading Policies'))

                    # Start polling the repo's progress per second
                    def poll_policy_repo_progress():
                        p_count = len(self.policy_compartment_analysis.policies)
                        s_count = len(self.policy_compartment_analysis.regular_statements)
                        msg = f'Loaded {p_count} policies, {s_count} statements...'
                        cb = callback.get('progress') if callback else None
                        if cb is not None and callable(cb):
                            self.after(0, lambda m=msg: cb(m))
                        # Continue polling every second until loading is signaled complete
                        if not getattr(self.policy_compartment_analysis, 'policies_loaded_from_tenancy', False):
                            self.after(200, poll_policy_repo_progress)

                    self.after(0, poll_policy_repo_progress)

                    # Now make the call to load policies only (compartments already done)
                    success = self.policy_compartment_analysis.load_policies_only()
                    if not success:
                        raise RuntimeError('Failed to load policies after compartment/domain load')

                    # Ensure status bar shows loaded data
                    self.after(0, self.update_status_bar)

                    # Save cache after loading from tenancy
                    self.caching.save_combined_cache(self.policy_compartment_analysis)
            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')

                if callback:
                    cb = callback.get('error')
                    if cb is not None and callable(cb):
                        self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return
            else:
                end_time = time.perf_counter()
                msg = f'Finished loading tenancy in {end_time - start_time:.2f} seconds'
                logger.info(f'[OK] {msg}')

                # Ensure status bar accurately reflects finalized repo state
                self.after(0, self.update_status_bar)

                # Intelligence Running Message
                if callback:
                    cb = callback.get('progress')
                    if cb is not None and callable(cb):
                        self.after(300, lambda cb=cb, m='Running post-load policy intelligence analyses': cb(message=m))

                # Run post-load intelligence analysis
                self._post_load_create_intelligence()

                # Tabs Loading Message
                if callback:
                    cb = callback.get('progress')
                    if cb is not None and callable(cb):
                        self.after(300, lambda cb=cb, m='Populating Tab Data': cb(message=m))

                # Force tabs to update with new data (users, policies, compartments, cross-tenancy, etc)
                self._post_load_update_ui()

                # Show completion message
                if callback:
                    cb = callback.get('complete')
                    if cb is not None and callable(cb):
                        self.after(0, lambda msg=msg: cb(True, msg, False))  # type: ignore

                logger.info('Tenancy Load complete. Reloading all tabs')

                # Ensure status bar accurately reflects finalized repo state
                self.after(0, self.update_status_bar)
            finally:
                self.after(0, lambda: setattr(self, '_tenancy_load_in_progress', False))

        threading.Thread(target=worker, daemon=True).start()

    def load_compliance_output_async(self, dir_path: str, callback: dict | None = None, load_all_users: bool = True):
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

        def worker():
            try:
                progress_cb = callback.get('progress') if callback else None
                if progress_cb is not None and callable(progress_cb):
                    self.after(0, lambda m='Loading compliance output data': progress_cb(m))
                success = self.policy_compartment_analysis.load_from_compliance_output_dir(
                    dir_path, load_all_users=load_all_users
                )
                msg = f'Loaded compliance data from {dir_path}'
                logger.info(msg)
                # Post-processing after load
                # self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)
                progress_cb = callback.get('progress') if callback else None
                if progress_cb is not None and callable(progress_cb):
                    self.after(0, lambda m='Running post-load policy intelligence analyses': progress_cb(m))
                    # Ensure status bar accurately reflects finalized repo state
                    self.after(0, self.update_status_bar)
                self._post_load_create_intelligence()

                complete_cb = callback.get('complete') if callback else None
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda: complete_cb(success, msg, not success))
                if success:
                    logger.info('[OK] Compliance Output Load complete. Reloading all tabs.')
                    self._post_load_update_ui()
                    # Ensure status bar accurately reflects finalized repo state
                    self.after(0, self.update_status_bar)

            except Exception as e:
                logger.error(f'Error occurred during compliance output load: {e}')
                # Show stack trace if debug on main
                if logger.isEnabledFor(logging.DEBUG):
                    traceback.print_exc()
                error_cb = callback.get('error') if callback else None
                if error_cb is not None and callable(error_cb):
                    self.after(0, lambda e=e: error_cb(False, f'Compliance load failed: {e}', True))

        threading.Thread(target=worker, daemon=True).start()

    def _import_cache_from_json(self, callback: dict | None = None):  # noqa: C901
        """
        Imports cached policy analysis data from a JSON file selected by the user.

        Args:
            callback (dict, optional): A dictionary of callback functions for progress, error, and completion.
        """
        if callback is None:
            callback = {}
        filepath = tkfiledialog.askopenfilename(filetypes=[('JSON Files', '*.json')])
        if filepath:
            try:
                logger.info(f'Importing cached data from file: {filepath}')
                progress_cb = callback.get('progress') if callback else None
                if progress_cb is not None and callable(progress_cb):
                    self.after(0, lambda: progress_cb('Loading from JSON file'))
                with open(filepath, encoding='utf-8') as jsonfile:
                    loaded_json = json.load(jsonfile)
                    logger.debug(f'JSON Data: {loaded_json}')
                success = self.caching.load_cache_from_json(
                    loaded_json=loaded_json, policy_analysis=self.policy_compartment_analysis
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
                    # Show intelligence running message (same pattern as tenancy load)
                    if callback:
                        cb = callback.get('progress')
                        if cb is not None and callable(cb):
                            self.after(
                                300,
                                lambda m='Running post-load policy intelligence analyses': cb(success=True, message=m),
                            )
                    # Run the same post-load intelligence and UI update steps as a tenancy load
                    self._post_load_create_intelligence()
                complete_cb = callback.get('complete') if callback else None
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda: complete_cb(True, 'Loaded from JSON file', False))
                else:
                    logger.warning('Failed to load from saved cache')

                logger.info('Cache Load JSON complete - Reload all tabs')
                self._post_load_update_ui()
                # Ensure status bar reflects final state after display updates
                self.after(0, self.update_status_bar)
            except Exception as e:
                logger.error(f'Error importing policies from CSV: {e}')
                error_cb = callback.get('error') if callback else None
                if error_cb is not None and callable(error_cb):
                    self.after(0, lambda: error_cb(False, 'Failed to load from JSON file', True))
            finally:
                pass

    def _export_cache_to_json(self):
        """
        Exports the current cached policy analysis data to a JSON file selected by the user.
        """
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {type(filepath)} {filepath.name}')
            self.caching.save_combined_cache(self.policy_compartment_analysis, export_file=filepath)
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
                self.after(0, lambda: self.set_bottom_output(content=str(ai_text_response), test_call=test_call))

                if callback is not None:
                    if ai_text_response.startswith('Error:'):
                        self.after(
                            0,
                            lambda: callback(
                                success=False,
                                message=f'GenAI query failed: {ai_text_response.lstrip("**Error:** ")}',  # noqa: B005
                            ),  # type: ignore
                        )
                    else:
                        self.after(0, lambda: callback(success=True, message='Set up AI successfully'))

                self.after(
                    0,
                    lambda: self.ai_progress_var.set(
                        f'[OK] Finished AI Call in ({time.perf_counter()-start_time:.2f}ms)'
                    ),
                )
            except Exception as e:
                logger.error(f'GenAI request failed: {e}')
                self.after(0, lambda e=e: self.set_bottom_output(f'**Error:** {str(e)}', test_call=test_call))
                if callback is not None:
                    self.after(0, lambda e=e: callback(success=False, message=f'Failed AI: {e}'))

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

        # When switching to Settings tab, refresh Additional Identity Domain Compartment OCIDs from persisted settings
        if selected_widget is self.settings_tab and hasattr(
            self.settings_tab, '_refresh_domain_compartment_ocids_from_settings'
        ):
            self.settings_tab._refresh_domain_compartment_ocids_from_settings()

        # If the new tab is NOT in supported, and AI (bottom_frame) is shown, hide it.
        if selected_widget is not None and str(selected_widget) not in supported_tabs:
            if self.bottom_frame.winfo_ismapped():
                logger.info('AI pane will be hidden due to tab switch to unsupported tab.')
                self.toggle_bottom()
        # # Update AI Assist button (Policy Browser Tab only for now)
        # if hasattr(self, "policy_browser_tab") and hasattr(self.policy_browser_tab, "update_ai_assist_button"):
        #     self.policy_browser_tab.update_ai_assist_button()


if __name__ == '__main__':
    """Main entry point for OCI Policy Analysis application."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    # parser.add_argument('--console-log', action='store_true', help='Log to console instead of file', default=False)

    args = parser.parse_args()

    logger = get_logger(component='main')

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

    app = App(force_debug=args.verbose)
    app.mainloop()
