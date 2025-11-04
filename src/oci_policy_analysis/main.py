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
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################
##########################################################################
# Safe startup patches for PyInstaller / FastMCP builds
##########################################################################
import importlib.metadata
import io
import sys
from datetime import UTC
from importlib.resources import files

import ttkbootstrap as ttk

# FastMCP No console patch
# Patch for PyInstaller windowed executables where sys.stdout/stderr may be None
if getattr(sys, 'frozen', False) and (sys.stdout is None or sys.stderr is None):

    class DummyStream(io.StringIO):
        def isatty(self):
            return False  # Pretend it's not a TTY to disable color detection

    if sys.stdout is None:
        sys.stdout = DummyStream()
    if sys.stderr is None:
        sys.stderr = DummyStream()

# Version extraction
try:
    __version__ = files('oci_policy_analysis').joinpath('version.txt').read_text().strip()
except Exception:
    __version__ = 'dev'


# -- Patch importlib.metadata.version to avoid PackageNotFoundError
def _safe_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return '0.0.0'


importlib.metadata.version = _safe_version

# # -- Ensure fake Rich package works if the real one is missing
# try:
#     import rich  # noqa: F401
# except ModuleNotFoundError:
#     import sys, os  # noqa: E401, I001

#     rich_path = os.path.join(os.path.dirname(__file__), 'rich')
#     if os.path.isdir(rich_path):
#         sys.path.insert(0, os.path.dirname(__file__))
# ##########################################################################

# Standard library imports
import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import tkinter as tk  # noqa: E402
import tkinter.filedialog as tkfiledialog  # noqa: E402
import tkinter.font as tkfont  # noqa: E402
import webbrowser  # noqa: E402
from datetime import datetime  # noqa: E402
from tkinter.scrolledtext import ScrolledText  # noqa: E402

# import markdown
import markdown2  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from tkhtmlview import HTMLLabel  # noqa: E402

from oci_policy_analysis.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.logic import config  # noqa: E402
from oci_policy_analysis.logic.caching import CacheManager  # noqa: E402
from oci_policy_analysis.logic.data_repo import AI, PolicyAnalysisRepository  # noqa: E402
from oci_policy_analysis.ui.console_tab import ConsoleTab  # noqa: E402
from oci_policy_analysis.ui.cross_tenancy_tab import CrossTenancyTab  # noqa: E402
from oci_policy_analysis.ui.dynamic_group_tab import DynamicGroupsTab  # noqa: E402
from oci_policy_analysis.ui.historical_tab import HistoricalTab  # noqa: E402
from oci_policy_analysis.ui.mcp_tab import McpTab  # noqa: E402
from oci_policy_analysis.ui.policies_tab import PoliciesTab  # noqa: E402
from oci_policy_analysis.ui.policy_overlap_tab import PolicyOverlapTab  # noqa: E402
from oci_policy_analysis.ui.report_tab import ReportTab  # noqa: E402
from oci_policy_analysis.ui.resource_principals_tab import ResourcePrincipalsTab  # noqa: E402
from oci_policy_analysis.ui.settings_tab import SettingsTab  # noqa: E402
from oci_policy_analysis.ui.users_tab import UsersTab  # noqa: E402


class App(tk.Tk):
    """Main application window for OCI Policy Analysis.

    This class manages the main Tkinter window, top Notebook tabs, bottom pane,
    settings persistence, and a detachable logging console window.

    Attributes:
        settings (dict): Application settings loaded from config.json.
        logger (logging.Logger): Shared application logger.
        style (ttk.Style): Tkinter style manager for theme changes.
        default_font (tkinter.font.Font): Default font, configurable by size and family.
        pw (ttk.Panedwindow): Vertical split container for top/bottom layout.
        top_frame (ttk.Frame): Container for the Notebook tabs.
        notebook (ttk.Notebook): Notebook widget holding all tabs.
        repo (DataRepository): Example data repository for users.
        bottom_frame (ttk.Frame): Bottom panel container.
        bottom_entry (ttk.Entry): Entry widget for quick text input in bottom pane.
        html_view (tk.Widget): HTMLLabel (if available) or Text widget for bottom output.
        console_window (tk.Toplevel | None): Detached console window for live logs.
        console_handler (logging.Handler | None): Logging handler attached to console window.
    """

    def __init__(self):
        super().__init__()

        # --- Title with version ---
        self.title(f'OCI Policy Analysis {__version__}')
        self.geometry('1400x900')

        # Shared config & logger
        self.settings = config.load_settings()

        # Restore global logger level from settings (default INFO)
        level_name = self.settings.get('log_level', 'INFO')
        # logger.setLevel(getattr(logging, level_name, logging.INFO))
        self.log_level_var = tk.StringVar(value=level_name)
        logger.info(f'Log level set to {logging.getLevelName(logger.level)} from settings')
        set_log_level(level=level_name)

        # Style / fonts
        self.style = ttk.Style(theme='litera')
        self.default_font = tkfont.nametofont('TkDefaultFont')
        self.style.configure('.', font=('Oracle Sans', 12))
        self.style.configure('TButton', bootstyle='round')  # all buttons get round style
        self.style.configure('TNotebook.Tab', padding=[40, 20, 40, 20])  # notebook tab [left, top, right, bottom]
        self.style.configure('Treeview', padding=(0, 0, 8, 0))  # (left, top, right, bottom)

        # PanedWindow (vertical split)
        self.pw = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.pw.pack(fill='both', expand=True)

        # Top frame with Notebook
        self.top_frame = ttk.Frame(self.pw)
        self.pw.add(self.top_frame, weight=3)

        self.notebook = ttk.Notebook(self.top_frame)
        self.notebook.pack(fill='both', expand=True)

        # Repository / Data
        self.policy_compartment_analysis = PolicyAnalysisRepository()  # Core
        self.ai = AI()  # AI functionality

        # Caching Manager
        self.caching = CacheManager(policy_analysis=self.policy_compartment_analysis)

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
        self.policies_tab = PoliciesTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.policy_overlap_tab = PolicyOverlapTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.users_tab = UsersTab(self.notebook, self, self.policy_compartment_analysis)
        self.dynamic_groups_tab = DynamicGroupsTab(self.notebook, self, self.policy_compartment_analysis)
        self.cross_tenancy_tab = CrossTenancyTab(self.notebook, self, self.policy_compartment_analysis)
        self.report_tab = ReportTab(self.notebook, self, self.policy_compartment_analysis)
        self.mcp_tab = McpTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.resource_principals_tab = ResourcePrincipalsTab(self.notebook, self, self.policy_compartment_analysis)
        self.historical_tab = HistoricalTab(self.notebook, caching=self.caching)
        self.console_tab = ConsoleTab(self.notebook, self)
        # Add tabs to notebook
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.policy_overlap_tab, text='Policy\nOverlap')
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Resource\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.report_tab, text='Reports\n& Export')
        self.notebook.add(self.mcp_tab, text='Embedded MCP\nServer')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        self.notebook.add(self.console_tab, text='Console\nLog')

        # Bottom frame (Entry + HTML/Text area)
        self.bottom_frame = ttk.Frame(self.pw, height=200)
        self._build_bottom_area(self.bottom_frame)

        # Console tab Visibility
        self.console_visible = False
        self.notebook.forget(self.console_tab)

        # Apply theme & font from settings - set the tab variable and then all calls to apply_theme need no args
        self.settings_tab.theme_var.set(self.settings.get('theme', 'Light'))
        self.apply_theme()
        # self.apply_font_size(self.settings.get('font_size', 'Medium'))

    # -------------------------
    # Bottom area construction
    # -------------------------

    def _build_bottom_area(self, parent: ttk.Frame):
        # -------------------------
        # Command row
        # -------------------------
        cmdrow = ttk.Frame(parent)
        cmdrow.pack(fill='x', padx=8, pady=(8, 4))
        # Grid this
        cmdrow.grid_columnconfigure(0, weight=8)
        cmdrow.grid_columnconfigure(1, weight=75)
        cmdrow.grid_columnconfigure(2, weight=7)
        cmdrow.grid_columnconfigure(3, weight=10)

        self.policy_query_var = tk.StringVar()
        ttk.Label(cmdrow, text='Policy Statement\nfor analysis:').grid(row=0, column=0, padx=5, pady=5, sticky='w')

        self.bottom_entry = ttk.Entry(cmdrow, textvariable=self.policy_query_var, width=90)
        self.bottom_entry.grid(row=0, column=1, padx=5, pady=5, sticky='ew')

        ttk.Button(
            cmdrow,
            text='Query GenAI',
            command=lambda: self.ask_genai_async(prompt=self.policy_query_var.get()),
        ).grid(row=0, column=2, padx=5, pady=5, sticky='w')

        self.ai_progress_var = tk.StringVar(value='')
        ttk.Label(cmdrow, textvariable=self.ai_progress_var, foreground='blue', width=22).grid(
            row=0, column=3, padx=5, pady=5, sticky='w'
        )

        # -------------------------
        # Bottom content (direct, no Canvas wrapper)
        # -------------------------
        self.bottom_content = ttk.Frame(parent)
        self.bottom_content.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        # Frame for scrollbar for HTML
        self.md_frame = ttk.Frame(self.bottom_content)
        self.md_frame.pack(fill='both', expand=True)
        self.md_canvas = tk.Canvas(self.md_frame, background='white', highlightthickness=0)
        self.md_vscroll = ttk.Scrollbar(self.md_frame, orient='vertical', command=self.md_canvas.yview)
        self.md_canvas.configure(yscrollcommand=self.md_vscroll.set)

        # Markdown view (HTMLLabel)
        self.html_view = HTMLLabel(
            self.md_canvas,
            html='<h3>Welcome</h3><p>This area can show Markdown as HTML output.</p>',
            background='white',
        )
        content_window = self.md_canvas.create_window((0, 0), window=self.html_view, anchor='nw')

        def _resize(event):
            self.md_canvas.configure(scrollregion=self.md_canvas.bbox('all'))
            self.md_canvas.itemconfig(content_window, width=self.md_canvas.winfo_width())

        self.html_view.bind('<Configure>', _resize)

        self.md_canvas.pack(side='left', fill='both', expand=True)
        self.md_vscroll.pack(side='right', fill='y')

        # Text view (ScrolledText, already has scrollbar built-in)
        self.text_view = ScrolledText(self.bottom_content, wrap='word', background='white', relief='flat')
        self.text_view.insert('1.0', 'Plain text output will appear here.\n')

        # Start with Markdown visible
        self.md_frame.pack(fill='both', expand=True)
        # self.text_frame = self.md_frame  # keep reference to toggle later
        # self.html_view.pack(fill="both", expand=True, padx=6, pady=6)

        # bind mousewheel properly
        self._bind_mousewheel(self.md_canvas)
        self._bind_mousewheel(self.text_view)

    def _bind_mousewheel(self, widget):
        def _on_mousewheel(event):
            if event.num == 5 or event.delta < 0:
                widget.yview_scroll(1, 'units')
            elif event.num == 4 or event.delta > 0:
                widget.yview_scroll(-1, 'units')
            return 'break'

        # Windows / Mac
        widget.bind_all('<MouseWheel>', _on_mousewheel)
        # Linux
        widget.bind_all('<Button-4>', _on_mousewheel)
        widget.bind_all('<Button-5>', _on_mousewheel)

    # Public API for tabs to update the bottom entry
    # Called from any tab to set the entry text for the AI call
    def update_bottom_entry(self, text: str):
        self.bottom_entry.delete(0, tk.END)
        self.bottom_entry.insert(0, text)

    # -------------------------
    # Theme / Font application
    # -------------------------
    def apply_theme(self, *args):
        """Apply either Light (litera) or Dark (darkly)."""
        theme_choice = self.settings_tab.theme_var.get()
        mapping = {'Light': 'litera', 'Dark': 'darkly'}

        # General theme change
        theme_name = mapping.get(theme_choice, 'litera')
        try:
            # Apply the theme
            self.style.theme_use(theme_name)
            pass
        except tk.TclError:
            # import traceback
            # traceback.print_exc()
            pass  # dont show this error
        except Exception as e:
            logger.warning(f'Failed to apply theme {theme_choice}: {e}')

        try:
            # Set the treeview background and foreground colors appropriately
            if theme_choice == 'Dark':
                # Change all data_tables to dark theme
                for table in [
                    self.policy_overlap_tab.policy_table,
                    self.users_tab.users_policy_table,
                    self.users_tab.users_users_table,
                    self.users_tab.users_groups_table,
                    self.users_tab.selected_groups_table,
                    self.dynamic_groups_tab.custom_data_dynamic_group,
                    self.dynamic_groups_tab.dg_policy_table,
                    self.cross_tenancy_tab.cross_tenancy_table,
                    self.cross_tenancy_tab.defined_aliases_table,
                    self.resource_principals_tab.rp_dg_table,
                    self.resource_principals_tab.rp_policy_table,
                    self.policies_tab.policy_table,
                    self.settings_tab.ai_model_table,
                ]:
                    table.apply_theme('dark')

            else:
                for table in [
                    self.policy_overlap_tab.policy_table,
                    self.users_tab.users_policy_table,
                    self.users_tab.users_users_table,
                    self.users_tab.users_groups_table,
                    self.users_tab.selected_groups_table,
                    self.dynamic_groups_tab.custom_data_dynamic_group,
                    self.dynamic_groups_tab.dg_policy_table,
                    self.cross_tenancy_tab.cross_tenancy_table,
                    self.cross_tenancy_tab.defined_aliases_table,
                    self.resource_principals_tab.rp_dg_table,
                    self.resource_principals_tab.rp_policy_table,
                    self.policies_tab.policy_table,
                    self.settings_tab.ai_model_table,
                ]:
                    table.apply_theme('light')
            # Scrolled Text widgets have different backgrounds
            if theme_choice == 'Dark':
                bg = '#2b2b2b'
                fg = '#f0f0f0'
                insert_bg = '#ffffff'  # cursor color
                self.mcp_tab.mcp_log.configure(background=bg, foreground=fg, insertbackground=insert_bg)
            else:
                bg = 'white'
                fg = 'black'
                insert_bg = '#000000'  # cursor color
                self.mcp_tab.mcp_log.configure(background=bg, foreground=fg, insertbackground=insert_bg)
        except Exception as e:
            logger.warning(f'Failed to apply theme {theme_choice}: {e}')

        # Also update HTML view colors
        if hasattr(self, 'html_view'):
            logger.debug(f'Change HTML to {theme_choice} ({theme_name})')
            if theme_choice == 'Dark':
                self.html_view.configure(background='black', foreground='white')
            else:
                self.html_view.configure(background='white', foreground='black')
        # Save the theme
        self.settings['theme'] = theme_choice
        config.save_settings(self.settings)
        logger.info(f'Theme set to {theme_choice} ({theme_name})')

        # def apply_font_size(self, size_name: str):
        sizes = {'Small': 9, 'Medium': 11, 'Large': 13}
        size = sizes.get(self.settings_tab.font_var.get(), 11)
        logger.info(f'Applying font size: {self.settings_tab.font_var.get()} ({size}px)')
        # Choose family (Oracle Sans if installed, else fallback)
        families = tkfont.families()
        family = 'Oracle Sans' if 'Oracle Sans' in families else 'Helvetica'

        # Tell ttkbootstrap to use this font globally
        font = (family, size)
        self.style.configure('.', font=font)  # "." applies to *all* widgets

        # Update the table font for TreeView
        treeview_font = size * 2
        self.style.configure('Treeview', rowheight=treeview_font)
        # self.historical_tab.update_row_height("small")   # or "medium" / "large"

        # Save & log
        self.settings['font_size'] = self.settings_tab.font_var.get()
        config.save_settings(self.settings)
        logger.info(f'Font size set to {self.settings_tab.font_var.get()} ({size}px)')

    def show_output_widget(self, fmt: str):
        self.text_view.pack_forget()
        self.md_frame.pack_forget()

        if fmt == 'Text':
            self.text_view.pack(fill='both', expand=True, padx=6, pady=6)
        else:  # Markdown
            self.md_frame.pack(fill='both', expand=True, padx=6, pady=6)

    # -------------------------
    # Bottom pane toggle & sash
    # -------------------------
    def toggle_bottom(self):
        if self.bottom_frame.winfo_ismapped():
            # Save sash pos, then remove bottom
            try:
                self.settings['sashpos'] = self.pw.sashpos(0)
            except Exception:
                pass
            self.pw.forget(self.bottom_frame)
            # self.settings['bottom_visible'] = False
            config.save_settings(self.settings)
        else:
            self.pw.add(self.bottom_frame, weight=1)
            # self.settings['bottom_visible'] = True
            config.save_settings(self.settings)
            self.after(120, self.restore_sash)

    def restore_sash(self):
        pos = self.settings.get('sashpos')
        if pos is not None:
            try:
                # Clamp to within window height
                max_y = max(120, self.winfo_height() - 120)
                self.pw.sashpos(0, min(pos, max_y))
            except Exception:
                pass

    def _apply_log_level(self, *args):
        """Called when log level dropdown changes."""
        # Set the level locally in dropdown var, in the logger, and then save it to settings
        self.settings['log_level'] = self.log_level_var.get()
        set_log_level(self.log_level_var.get())
        config.save_settings(settings=self.settings)
        logger.info(
            f'Log level set to {self.log_level_var.get()}. To use DEBUG, you must start from shell using --verbose'
        )

    # -------------------------
    # Loading / exporting of tenancy data
    # -------------------------
    def load_tenancy_async(  # noqa: C901
        self,
        tenancy_id: str,
        recursive: bool,
        instance_principal: bool,
        named_profile: str,
        named_session: str,
        named_cache: str,
        callback: dict = None,
    ):
        """Kick off tenancy loading in a background thread."""
        # Could load from cache or from tenancy with threading
        logger.info(f'Starting async tenancy load: {tenancy_id} (recursive={recursive}, ip={instance_principal})')

        def worker():  # noqa: C901
            """Async worker that actually performs the tenancy load."""
            try:
                success = False

                # If cached, simply load directly
                if named_cache:
                    logger.info(f'Using named cache: {named_cache}')

                    # Call into the data caching module
                    success = self.caching.load_combined_cache(named_cache=named_cache)

                # If tenancy, initialize client
                elif named_profile:
                    logger.info(f'Using named profile: {named_profile}')

                    success = self.policy_compartment_analysis.initialize_client(
                        use_instance_principal=instance_principal,
                        session_token=named_session,
                        recursive=recursive,
                        profile=named_profile,
                    )
                    # Fail if unable to initialize client
                    if not success:
                        raise RuntimeError('Failed to initialize IdentityDomainAnalysis client')

                    # Update the message
                    if callback and callback.get('progress'):
                        cb = callback.get('progress')
                        self.after(0, lambda: cb('Loading Identity Domains'))

                    # Load identity domains
                    success = self.policy_compartment_analysis.load_complete_identity_domains()
                    if not success:
                        raise RuntimeError('Failed to load identity domains')
                    # Update the message
                    if callback and callback.get('progress'):
                        cb = callback.get('progress')
                        self.after(0, lambda: cb('Loading Compartments and Policies'))
                    # Load policies and compartments
                    success = self.policy_compartment_analysis.load_policies_and_compartments()
                    if not success:
                        raise RuntimeError('Failed to load policies and compartments')
                    # Save cached data after load
                    self.caching.save_combined_cache()

            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')
                if callback and callback.get('error'):
                    cb = callback.get('error')
                    self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return

            # We got this far, all good
            msg = f'Finished loading tenancy {tenancy_id}'
            logger.info(f'✅ {msg}')

            if callback and callback.get('complete'):
                cb = callback.get('complete')
                self.after(0, lambda msg=msg: cb(True, msg, True))  # type: ignore

            # Tell the tab to reload
            logger.info('Tenancy Load complete. Reloading all tabs')
            self.policy_overlap_tab.enable_widgets_after_load()
            self.users_tab._update_user_analysis_output()
            self.policies_tab.update_policy_output()
            self.dynamic_groups_tab.enable_controls()
            self.cross_tenancy_tab.update_cross_tenancy_output()
            self.report_tab.update_report_output()
            self.resource_principals_tab.update_principals_sheets()
            self.historical_tab.populate_cache_dropdowns(tenancy_name=self.policy_compartment_analysis.tenancy_name)
            self.dynamic_groups_tab.enable_controls()

        threading.Thread(target=worker, daemon=True).start()

    def _import_cache_from_json(self, callback: dict = None):
        """Import cached data from a JSON file asynchronously. There can be a 3 callback(progress, complete, error) to update the UI."""
        if callback is None:
            callback = {}
        filepath = tkfiledialog.askopenfilename(filetypes=[('JSON Files', '*.json')])
        if filepath:
            try:
                logger.info(f'Importing cached data from file: {filepath}')
                if callback and callback.get('progress'):
                    # Schedule safe UI update in main thread
                    cb = callback.get('progress')
                    self.after(0, lambda: cb('Loading from JSON file'))  # type: ignore
                # Load the file into local JSON
                with open(filepath, encoding='utf-8') as jsonfile:
                    loaded_json = json.load(jsonfile)
                    logger.debug(f'JSON Data: {loaded_json}')
                # Load the data into Data Classes
                success = self.caching.load_cache_from_json(loaded_json=loaded_json)
                if success and callback.get('complete'):
                    # Update the last load time and enable UI elements
                    self.last_load_time = self.policy_compartment_analysis.data_as_of
                    logger.info(f'***Loaded cached data from file as of {self.last_load_time}')
                    logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
                    if callback:
                        # Schedule safe UI update in main thread
                        cb = callback.get('complete')
                        self.after(0, lambda: cb(True, 'Loaded from JSON file', True))  # type: ignore
                else:
                    logger.warning('Failed to load from saved cache')

                # Tell the tab to reload
                logger.info('Cache Load JSON complete - Reload all tabs')
                self.policy_overlap_tab.enable_widgets_after_load()
                self.users_tab._update_user_analysis_output()
                self.policies_tab.update_policy_output()
                self.dynamic_groups_tab.enable_controls()
                self.cross_tenancy_tab.update_cross_tenancy_output()
                self.report_tab.update_report_output()
                self.resource_principals_tab.update_principals_sheets()
                self.historical_tab.populate_cache_dropdowns(tenancy_name=self.policy_compartment_analysis.tenancy_name)
                self.dynamic_groups_tab.enable_controls()

            except Exception as e:
                logger.error(f'Error importing policies from CSV: {e}')
                if callback and callback.get('error'):
                    # Schedule safe UI update in main thread
                    cb = callback.get('error')
                    self.after(0, lambda: cb(False, 'Failed to load from JSON file', True))  # type: ignore
            finally:
                pass

            # # Tell the tab to reload
            # self.users_tab._update_user_analysis_output()
            # self.policies_tab.update_policy_output()

    def _export_cache_to_json(self):
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {type(filepath)} {filepath.name}')
            self.caching.save_combined_cache(export_file=filepath)
            logger.info(f'Wrote file {filepath.name}')
        else:
            logger.info('Export cancelled by user')

    # -------------------------
    # AI Calls
    # -------------------------
    def ask_genai_async(self, prompt: str, test=False, callback=None):
        """Run a GenAI query asynchronously in a thread and update the UI."""
        logger.info(f'Submitting GenAI prompt: {prompt}')
        self.set_bottom_output(f'## Querying GenAI \n\n`{prompt}`')

        def worker():
            try:
                start_time = time.perf_counter()
                if test:
                    ai_markdown_response = asyncio.run(
                        self.ai.test_ai_call(
                            query=prompt, additional_instruction='Super-fast and funny answer please.', queue=None
                        )
                    )
                    self.after(
                        0, lambda: self.ai_progress_var.set(f'✅ Test GenAI ({time.perf_counter()-start_time:.2f}ms)')
                    )

                else:
                    self.after(0, lambda: self.ai_progress_var.set('⌛ Running AI Query'))
                    # Check the cache
                    for entry in self.caching.ai_result_cache:
                        if entry.get('type') == 'analyze_policy_statement' and entry.get('query') == prompt:
                            logger.info('Cache hit for policy analysis: %s', prompt)

                            # Cache result to display
                            self.after(0, lambda entry=entry: self.set_bottom_output(entry['result']))

                            # message to user
                            self.after(0, lambda: self.ai_progress_var.set('✅ Result from AI Cache'))

                    # run the async AI call inside this thread
                    ai_markdown_response = asyncio.run(self.ai.analyze_policy_statement(policy_text=prompt, queue=None))

                    # Add to the cache
                    self.caching.ai_result_cache.append(
                        {
                            'type': 'analyze_policy_statement',
                            'query': prompt,
                            'result': ai_markdown_response,
                            'date_ms': int(datetime.now(UTC).timestamp() * 1000),
                        }
                    )
                    self.caching.save_cache()
                # update UI in main thread
                self.after(0, lambda: self.set_bottom_output(ai_markdown_response))  # type: ignore

                if callback:
                    self.after(0, lambda: callback(success=True, message='Set up AI successfully'))  # type: ignore

                # progress label
                self.after(
                    0,
                    lambda: self.ai_progress_var.set(
                        f'✅ Finished AI Call in ({time.perf_counter()-start_time:.2f}ms)'
                    ),
                )
                # self.after(3000, lambda: self.ai_progress_var.set(''))

            except Exception as e:
                logger.error(f'GenAI request failed: {e}')
                self.after(0, lambda e=e: self.set_bottom_output(f'**Error:** {e}'))
                if callback:
                    self.after(0, lambda e=e: callback(success=False, message=f'Failed AI: {e}'))  # type: ignore

        threading.Thread(target=worker, daemon=True).start()

    def _markdown_to_text(self, md: str) -> str:
        html = markdown2.markdown(md, extras=['fenced-code-blocks', 'tables', 'strike', 'break-on-newline'])
        soup = BeautifulSoup(html, 'html.parser')
        return soup.get_text('\n').strip()

    def set_bottom_output(self, content: str):
        fmt = self.settings.get('result_format', 'Markdown')
        self.show_output_widget(fmt)

        try:
            # Text
            plain = self._markdown_to_text(content)
            self.text_view.delete('1.0', tk.END)
            self.text_view.insert('1.0', plain)
            # HTML
            html_body = markdown2.markdown(
                content, extras=['fenced-code-blocks', 'tables', 'strike', 'break-on-newline']
            )
            # Generate a theme
            if self.settings.get('theme', 'Light') == 'Dark':
                themed = f"""
                <div style="font-family:sans-serif; color:black;">
                    {html_body}
                </div>
                """
            else:
                themed = f"""
                    <div style="font-family:sans-serif; color:black; background:white;">
                        {html_body}
                    </div>
                """
            self.html_view.set_html(themed)

        except Exception as e:
            if fmt == 'Text':
                self.text_view.insert('1.0', f'Error rendering text: {e}')
            else:
                self.html_view.set_html(f"<p style='color:red;'>Error rendering Markdown: {e}</p>")

    # -------------------------
    # Web Links
    # -------------------------
    def open_link(self, link):
        logger.info(f'Opening web link: {link}')
        webbrowser.open_new(link)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer CLI')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    # parser.add_argument('--console-log', action='store_true', help='Log to console instead of file', default=False)

    args = parser.parse_args()

    logger = get_logger(component='main')
    logger.info('Logging to Console only')

    # Configure logging based on verbose flag
    if args.verbose:
        set_log_level('DEBUG')
        logger.debug('Verbose logging enabled via --verbose')

    # Run the app
    app = App()
    app.mainloop()
