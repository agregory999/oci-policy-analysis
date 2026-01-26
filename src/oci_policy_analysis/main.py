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
##########################################################################
# Safe startup patches for PyInstaller / FastMCP builds
##########################################################################

# Standard library imports
import argparse  # noqa: E402
import asyncio  # noqa: E402

# import io
import json  # noqa: E402
import logging  # noqa: E402
import queue  # noqa: E402

# import sys
import threading  # noqa: E402
import time  # noqa: E402
import tkinter as tk  # noqa: E402
import tkinter.filedialog as tkfiledialog  # noqa: E402
import tkinter.font as tkfont  # noqa: E402
import tkinter.ttk as ttk
import traceback
import warnings
import webbrowser  # noqa: E402
from importlib.resources import files

from oci_policy_analysis.common import config  # noqa: E402
from oci_policy_analysis.common.caching import CacheManager  # noqa: E402
from oci_policy_analysis.common.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.logic.ai_repo import AI  # noqa: E402
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository  # noqa: E402
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.logic.simulation_engine import PolicySimulationEngine
from oci_policy_analysis.ui.condition_tester_tab import ConditionTesterTab
from oci_policy_analysis.ui.console_tab import ConsoleTab  # noqa: E402
from oci_policy_analysis.ui.cross_tenancy_tab import CrossTenancyTab  # noqa: E402
from oci_policy_analysis.ui.debugger_tab import DebuggerTab
from oci_policy_analysis.ui.dynamic_group_tab import DynamicGroupsTab  # noqa: E402
from oci_policy_analysis.ui.historical_tab import HistoricalTab  # noqa: E402
from oci_policy_analysis.ui.maintenance_tab import MaintenanceTab
from oci_policy_analysis.ui.mcp_tab import McpTab  # noqa: E402
from oci_policy_analysis.ui.permissions_report_tab import PermissionsReportTab  # noqa: E402
from oci_policy_analysis.ui.policies_tab import PoliciesTab  # noqa: E402
from oci_policy_analysis.ui.policy_recommendations_tab import PolicyRecommendationsTab
from oci_policy_analysis.ui.report_tab import ReportTab  # noqa: E402
from oci_policy_analysis.ui.resource_principals_tab import ResourcePrincipalsTab  # noqa: E402
from oci_policy_analysis.ui.settings_tab import SettingsTab  # noqa: E402
from oci_policy_analysis.ui.simulation_tab import SimulationTab
from oci_policy_analysis.ui.users_tab import UsersTab  # noqa: E402

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
    """

    # docstring google style napoleon comments for the class with public methods and relevant private methods marked with (Internal)

    def __init__(self, force_debug: bool = False):
        super().__init__()

        self.title(f'OCI Policy Analysis {__version__}')
        self.geometry('1400x900')

        # Shared config & logger
        self.settings = config.load_settings()

        # Restore global logger level from settings (default INFO)
        level_name = self.settings.get('log_level', 'INFO')
        # If --verbose (force_debug) is set, override any setting-driven log level
        if force_debug:
            self.log_level_var = tk.StringVar(value='DEBUG')
            logger.info('Log level forcibly set to DEBUG due to --verbose argument (settings ignored)')
            set_log_level('DEBUG')
        else:
            self.log_level_var = tk.StringVar(value=level_name)
            logger.info(f'Log level set to {logging.getLevelName(logger.level)} from settings')
            set_log_level(level=level_name)

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
        self.policy_compartment_analysis = PolicyAnalysisRepository()
        self.ai = AI()
        self.reference_data_repo = ReferenceDataRepo()
        self.simulation_engine = PolicySimulationEngine(
            policy_repo=self.policy_compartment_analysis,
            ref_data_repo=self.reference_data_repo,
        )
        self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)

        # Caching Manager (policy caching only, no AI result caching)
        self.caching = CacheManager()

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
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
        self.maintenance_tab = MaintenanceTab(self.notebook, self, caching=self.caching, settings=self.settings)
        self.condition_tester_tab = ConditionTesterTab(self.notebook, self)
        self.simulation_tab = SimulationTab(self.notebook, self, self.settings)
        self.debugger_tab = DebuggerTab(self.notebook, self)

        # Add tabs to notebook
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Resource\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        self.notebook.add(self.mcp_tab, text='Embedded MCP\nServer')
        self.notebook.add(self.permissions_report_tab, text='Permissions Report\n(Advanced)')
        self.notebook.add(self.condition_tester_tab, text='Condition Tester\n(Advanced)')
        self.notebook.add(self.policy_recommendations_tab, text='Policy Recommendations\n(Advanced)')
        self.notebook.add(self.simulation_tab, text='API Simulation\n(Advanced)')
        self.notebook.add(self.debugger_tab, text='JSON Debugger\n(Admin)')
        self.notebook.add(self.console_tab, text='Console Logging\n(Admin)')
        self.notebook.add(self.maintenance_tab, text='Maintenance\n(Admin)')

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

        # Ensure the correct font is applied from saved settings at startup
        self.after(0, self.apply_theme)

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

        treeview_font = size * 2
        self.style.configure('Treeview', rowheight=treeview_font)

        self.settings['font_size'] = self.settings_tab.font_var.get()
        config.save_settings(self.settings)
        logger.info(f'Font size set to {self.settings_tab.font_var.get()} ({size}px)')

        # Ensure Page Help and other special widgets refresh font when theme is applied
        if hasattr(self.policies_tab, 'refresh_context_help'):
            self.policies_tab.refresh_context_help()
        if hasattr(self.users_tab, 'refresh_context_help'):
            self.users_tab.refresh_context_help()

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
        logger.info('Finding invalid policy statements')
        self.policy_intelligence.find_invalid_statements()
        logger.info('Running dynamic group in-use analysis')
        self.policy_intelligence.run_dg_in_use_analysis()
        logger.info('Analyzing policy overlaps')
        self.policy_intelligence.analyze_policy_overlap()
        logger.info('Calculating policy risk scores')
        self.policy_intelligence.calculate_potential_risk_scores()
        logger.info('Building policy consolidation findings')
        self.policy_intelligence.build_policy_consolidation()
        logger.info('Building permissions report for advanced report tab')
        self.policy_intelligence.build_permissions_report()

        # NEW: Build cleanup items before building overall recommendations
        logger.info('Building actionable cleanup items')
        self.policy_intelligence.build_cleanup_items()

        # Ensure recommendations are built last to leverage all overlays and intelligence
        logger.info('Building overall recommendations')
        self.policy_intelligence.build_overall_recommendations()

        self.simulation_engine.policy_statements = self.policy_compartment_analysis.regular_statements
        # self.simulation_engine.build_index()
        logger.info('Rebuilt Simulation Engine index after post-load intelligence.')
        end_post_process_time = time.perf_counter()
        logger.info(
            f'Post-load policy intelligence analyses (including simulation index) completed in {end_post_process_time - start_post_process_time:.2f} seconds'
        )

    def _post_load_update_ui(self):
        """Internal: Re-enable and update UI components after data load."""
        self.users_tab.update_user_analysis_output()
        self.policies_tab.update_policy_output()
        self.policies_tab.enable_widgets_after_load()
        self.dynamic_groups_tab.enable_controls()
        self.cross_tenancy_tab.update_cross_tenancy_output()
        # self.report_tab.update_report_output()
        self.resource_principals_tab.update_principals_sheets()
        self.historical_tab.populate_cache_dropdowns(tenancy_name=self.policy_compartment_analysis.tenancy_name)
        self.dynamic_groups_tab.enable_controls()
        self.permissions_report_tab.enable_widgets_after_load()
        self.simulation_tab.refresh_dropdowns()
        # Immediately update analytics tab with new data
        self.policy_recommendations_tab.reload_all_analytics()
        logger.info('All tabs reloaded after data load.')

    def load_tenancy_async(  # noqa: C901
        self,
        tenancy_id: str,
        recursive: bool,
        instance_principal: bool,
        named_profile: str,
        named_session: str,
        named_cache: str,
        callback: dict | None = None,
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
            callback (dict, optional): A dictionary of callback functions for progress, error, and completion
        """
        logger.info(f'Starting async tenancy load: {tenancy_id} (recursive={recursive}, ip={instance_principal})')

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
                        group_count = len(self.policy_compartment_analysis.groups)
                        user_count = len(self.policy_compartment_analysis.users)
                        msg = f'Loaded {domain_count} domains, {group_count} groups, {user_count} users...'
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

                    success = self.policy_compartment_analysis.load_complete_identity_domains()
                    if not success:
                        raise RuntimeError('Failed to load identity domains')
                    if callback:
                        cb = callback.get('progress')
                        if cb is not None and callable(cb):
                            self.after(0, lambda: cb('Loading Compartments and Policies'))

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

                    # Now make the call to load policies and compartments
                    success = self.policy_compartment_analysis.load_policies_and_compartments()
                    if not success:
                        raise RuntimeError('Failed to load policies and compartments')

                    if callback:
                        cb = callback.get('progress')
                        if cb is not None and callable(cb):
                            self.after(
                                300,
                                lambda m='Running post-load policy intelligence analyses': cb(success=True, message=m),
                            )

                    # Save cache after loading from tenancy
                    self.caching.save_combined_cache(self.policy_compartment_analysis)
            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')

                if callback:
                    cb = callback.get('error')
                    if cb is not None and callable(cb):
                        self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return

            end_time = time.perf_counter()
            msg = f'Finished loading tenancy in {end_time - start_time:.2f} seconds'
            logger.info(f'[OK] {msg}')

            if callback:
                cb = callback.get('complete')
                if cb is not None and callable(cb):
                    self.after(0, lambda msg=msg: cb(True, msg, False))  # type: ignore

            logger.info('Tenancy Load complete. Reloading all tabs')

            # Run post-load intelligence analysis
            self._post_load_create_intelligence()
            self._post_load_update_ui()

        threading.Thread(target=worker, daemon=True).start()

    def load_compliance_output_async(self, dir_path: str, callback: dict | None = None):
        """
        Asynchronously loads policy, compartment, group, user, dynamic group, and domain data from compliance output .csv files.
        Args:
            dir_path (str): The directory containing compliance output files as per spec.
            callback (dict, optional): Callbacks for progress, error, and complete.
        """
        logger.info(f'[ASYNC] Loading compliance analysis data from directory: {dir_path}')

        def worker():
            try:
                progress_cb = callback.get('progress') if callback else None
                if progress_cb is not None and callable(progress_cb):
                    self.after(0, lambda m='Loading compliance output data': progress_cb(m))
                success = self.policy_compartment_analysis.load_from_compliance_output_dir(dir_path)
                msg = f'Loaded compliance data from {dir_path}'
                logger.info(msg)
                # Post-processing after load
                # self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)
                progress_cb = callback.get('progress') if callback else None
                if progress_cb is not None and callable(progress_cb):
                    self.after(0, lambda m='Running post-load policy intelligence analyses': progress_cb(m))
                self._post_load_create_intelligence()

                complete_cb = callback.get('complete') if callback else None
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda: complete_cb(success, msg, not success))
                if success:
                    logger.info('[OK] Compliance Output Load complete. Reloading all tabs.')
                    self._post_load_update_ui()
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
                success = self.caching.load_cache_from_json(loaded_json=loaded_json)
                if success:
                    self.last_load_time = self.policy_compartment_analysis.data_as_of
                    logger.info(f'***Loaded cached data from file as of {self.last_load_time}')
                    logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
                    self._post_load_create_intelligence()
                complete_cb = callback.get('complete') if callback else None
                if complete_cb is not None and callable(complete_cb):
                    self.after(0, lambda: complete_cb(True, 'Loaded from JSON file', False))
                else:
                    logger.warning('Failed to load from saved cache')

                logger.info('Cache Load JSON complete - Reload all tabs')
                self._post_load_update_ui()
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

    def ask_genai_async(self, prompt: str, additional_instruction: str = '', callback=None):
        """
        Asynchronously queries the GenAI model with the given prompt and additional instructions.

        Args:
            prompt (str): The main prompt to send to the GenAI model.
            additional_instruction (str, optional): Any additional instructions to include in the query.
            callback (dict, optional): A dictionary of callback functions for different stages of the query.
        """
        logger.info(f'Submitting GenAI prompt: {prompt} with additional instructions: {additional_instruction}')
        self.set_bottom_output(f'Querying GenAI for:\n\n{prompt}')

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
                self.after(0, lambda: self.set_bottom_output(str(ai_text_response)))

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
                self.after(0, lambda e=e: self.set_bottom_output(f'**Error:** {str(e)}'))
                if callback is not None:
                    self.after(0, lambda e=e: callback(success=False, message=f'Failed AI: {e}'))

        threading.Thread(target=worker, daemon=True).start()

    def set_bottom_output(self, content: str):
        """
        Display the given string content as plain text in the output_text widget.

        Args:
            content (str): The text content to display in the output area.
        """
        import json

        # Support legacy case: AI may return [{"text": ...}] list (output from previous code path)
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


if __name__ == '__main__':
    """Main entry point for OCI Policy Analysis application."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    # parser.add_argument('--console-log', action='store_true', help='Log to console instead of file', default=False)

    args = parser.parse_args()

    logger = get_logger(component='main')
    logger.info('Logging to Console only')

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
