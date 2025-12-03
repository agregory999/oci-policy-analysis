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

# import importlib.metadata
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
import warnings
import webbrowser  # noqa: E402
from importlib.resources import files

from oci_policy_analysis.common import config  # noqa: E402
from oci_policy_analysis.common.caching import CacheManager  # noqa: E402
from oci_policy_analysis.common.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.logic.ai_repo import AI  # noqa: E402
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository  # noqa: E402
from oci_policy_analysis.ui.console_tab import ConsoleTab  # noqa: E402
from oci_policy_analysis.ui.cross_tenancy_tab import CrossTenancyTab  # noqa: E402
from oci_policy_analysis.ui.dynamic_group_tab import DynamicGroupsTab  # noqa: E402
from oci_policy_analysis.ui.historical_tab import HistoricalTab  # noqa: E402
from oci_policy_analysis.ui.maintenance_tab import MaintenanceTab
from oci_policy_analysis.ui.mcp_tab import McpTab  # noqa: E402
from oci_policy_analysis.ui.permissions_report_tab import PermissionsReportTab  # noqa: E402
from oci_policy_analysis.ui.policies_tab import PoliciesTab  # noqa: E402
from oci_policy_analysis.ui.policy_overlap_tab import PolicyOverlapTab  # noqa: E402
from oci_policy_analysis.ui.report_tab import ReportTab  # noqa: E402
from oci_policy_analysis.ui.resource_principals_tab import ResourcePrincipalsTab  # noqa: E402
from oci_policy_analysis.ui.settings_tab import SettingsTab  # noqa: E402
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
    # docstring google style napoleon comments for the class with public methods and relevant private methods marked with (Internal)
    """
    Main User Interface entry point for OCI Policy Analysis application.
    Inherits from tk.Tk (TKinter) to create the main application window.
    Tabbed interface with multiple tabs for different analysis features.
    Helper classes and Repositories for data management and AI integration.
    """

    def __init__(self):
        super().__init__()

        self.title(f'OCI Policy Analysis {__version__}')
        self.geometry('1400x900')

        # Shared config & logger
        self.settings = config.load_settings()

        # Restore global logger level from settings (default INFO)
        level_name = self.settings.get('log_level', 'INFO')
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

        # Repository / Data
        self.policy_compartment_analysis = PolicyAnalysisRepository()
        self.ai = AI()

        # Caching Manager (policy caching only, no AI result caching)
        self.caching = CacheManager(policy_analysis=self.policy_compartment_analysis)

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
        self.policies_tab = PoliciesTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.policy_overlap_tab = PolicyOverlapTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.permissions_report_tab = PermissionsReportTab(
            self.notebook, self, self.policy_compartment_analysis, self.settings
        )
        self.users_tab = UsersTab(self.notebook, self, self.policy_compartment_analysis)
        self.dynamic_groups_tab = DynamicGroupsTab(self.notebook, self, self.policy_compartment_analysis)
        self.cross_tenancy_tab = CrossTenancyTab(self.notebook, self, self.policy_compartment_analysis)
        self.report_tab = ReportTab(self.notebook, self, self.policy_compartment_analysis)
        self.mcp_tab = McpTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.resource_principals_tab = ResourcePrincipalsTab(self.notebook, self, self.policy_compartment_analysis)
        self.historical_tab = HistoricalTab(self.notebook, caching=self.caching)
        self.console_tab = ConsoleTab(self.notebook, self)
        self.maintenance_tab = MaintenanceTab(self.notebook, caching=self.caching)
        # Add tabs to notebook
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Resource\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.report_tab, text='Reports\nw/ Search')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        self.notebook.add(self.mcp_tab, text='Embedded MCP\nServer')
        self.notebook.add(self.permissions_report_tab, text='Permissions Report\n(Advanced)')
        self.notebook.add(self.policy_overlap_tab, text='Policy Overlap\n(Advanced)')
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

        # Console / Maintenance tab Visibility
        self.console_visible = False
        self.notebook.forget(self.console_tab)
        self.maintenance_visible = False
        self.notebook.forget(self.maintenance_tab)

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

                if named_cache:
                    logger.info(f'Using named cache: {named_cache}')
                    success = self.caching.load_combined_cache(named_cache=named_cache)

                elif named_profile:
                    logger.info(f'Using named profile: {named_profile}')

                    success = self.policy_compartment_analysis.initialize_client(
                        use_instance_principal=instance_principal,
                        session_token=named_session,
                        recursive=recursive,
                        profile=named_profile,
                    )
                    if not success:
                        raise RuntimeError('Failed to initialize IdentityDomainAnalysis client')

                    if callback:
                        cb = callback.get('progress')
                        if callable(cb):
                            self.after(0, lambda: cb('Loading Identity Domains'))

                    success = self.policy_compartment_analysis.load_complete_identity_domains()
                    if not success:
                        raise RuntimeError('Failed to load identity domains')
                    if callback:
                        cb = callback.get('progress')
                        if callable(cb):
                            self.after(0, lambda: cb('Loading Compartments and Policies'))
                    success = self.policy_compartment_analysis.load_policies_and_compartments()
                    if not success:
                        raise RuntimeError('Failed to load policies and compartments')
                    self.caching.save_combined_cache()

            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')
                if callback:
                    cb = callback.get('error')
                    if callable(cb):
                        self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return

            msg = f'Finished loading tenancy {tenancy_id}'
            logger.info(f'✅ {msg}')

            if callback:
                cb = callback.get('complete')
                if callable(cb):
                    self.after(0, lambda msg=msg: cb(True, msg, False))  # type: ignore

            logger.info('Tenancy Load complete. Reloading all tabs')
            self.policy_overlap_tab.enable_widgets_after_load()
            self.users_tab.update_user_analysis_output()
            self.policies_tab.update_policy_output()
            self.dynamic_groups_tab.enable_controls()
            self.cross_tenancy_tab.update_cross_tenancy_output()
            self.report_tab.update_report_output()
            self.resource_principals_tab.update_principals_sheets()
            self.historical_tab.populate_cache_dropdowns(tenancy_name=self.policy_compartment_analysis.tenancy_name)
            self.dynamic_groups_tab.enable_controls()
            self.permissions_report_tab.enable_widgets_after_load()

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
                if callback:
                    cb = callback.get('progress')
                    if cb is not None:
                        self.after(0, lambda: cb('Loading from JSON file'))  # type: ignore
                with open(filepath, encoding='utf-8') as jsonfile:
                    loaded_json = json.load(jsonfile)
                    logger.debug(f'JSON Data: {loaded_json}')
                success = self.caching.load_cache_from_json(loaded_json=loaded_json)
                if success:
                    self.last_load_time = self.policy_compartment_analysis.data_as_of
                    logger.info(f'***Loaded cached data from file as of {self.last_load_time}')
                    logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
                if callback:
                    cb = callback.get('complete')
                    if cb is not None:
                        self.after(0, lambda: cb(True, 'Loaded from JSON file', False))  # type: ignore
                else:
                    logger.warning('Failed to load from saved cache')

                logger.info('Cache Load JSON complete - Reload all tabs')
                self.policy_overlap_tab.enable_widgets_after_load()
                self.users_tab.update_user_analysis_output()
                self.policies_tab.update_policy_output()
                self.dynamic_groups_tab.enable_controls()
                self.cross_tenancy_tab.update_cross_tenancy_output()
                self.report_tab.update_report_output()
                self.resource_principals_tab.update_principals_sheets()
                self.historical_tab.populate_cache_dropdowns(tenancy_name=self.policy_compartment_analysis.tenancy_name)
                self.dynamic_groups_tab.enable_controls()

            except Exception as e:
                logger.error(f'Error importing policies from CSV: {e}')
                if callback:
                    cb = callback.get('error')
                    if cb is not None:
                        self.after(0, lambda: cb(False, 'Failed to load from JSON file', True))  # type: ignore
            finally:
                pass

    def _export_cache_to_json(self):
        """
        Exports the current cached policy analysis data to a JSON file selected by the user.
        """
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {type(filepath)} {filepath.name}')
            self.caching.save_combined_cache(export_file=filepath)
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
                self.after(0, lambda: self.ai_progress_var.set('⌛ Running AI Query'))
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
                        f'✅ Finished AI Call in ({time.perf_counter()-start_time:.2f}ms)'
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


if __name__ == '__main__':
    """Main entry point for OCI Policy Analysis application."""
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    # parser.add_argument('--console-log', action='store_true', help='Log to console instead of file', default=False)

    args = parser.parse_args()

    logger = get_logger(component='main')
    logger.info('Logging to Console only')

    if args.verbose:
        set_log_level('DEBUG')
        logger.debug('Verbose logging enabled via --verbose')

    app = App()
    app.mainloop()
