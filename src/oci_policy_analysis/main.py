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

# Standard library imports
import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import tkinter as tk  # noqa: E402
import tkinter.filedialog as tkfiledialog  # noqa: E402
import tkinter.font as tkfont  # noqa: E402
import webbrowser  # noqa: E402

import markdown2  # noqa: E402
from tkhtmlview import HTMLLabel  # noqa: E402

from oci_policy_analysis.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.logic import config  # noqa: E402
from oci_policy_analysis.logic.ai_repo import AI  # noqa: E402
from oci_policy_analysis.logic.caching import CacheManager  # noqa: E402
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository  # noqa: E402
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
    """Main application window for OCI Policy Analysis."""

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

        # Style / fonts
        self.style = ttk.Style(theme='litera')
        self.default_font = tkfont.nametofont('TkDefaultFont')
        self.style.configure('.', font=('Oracle Sans', 12))
        self.style.configure('TButton', bootstyle='round')
        self.style.configure('TNotebook.Tab', padding=[40, 20, 40, 20])
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
        self.notebook.add(self.users_tab, text='Groups\nUsers')
        self.notebook.add(self.dynamic_groups_tab, text='Dynamic\nGroups')
        self.notebook.add(self.resource_principals_tab, text='Resource\nPrincipals')
        self.notebook.add(self.cross_tenancy_tab, text='Cross-Tenancy\nPolicies')
        self.notebook.add(self.policy_overlap_tab, text='Policy\nOverlap')
        self.notebook.add(self.report_tab, text='Reports\n& Export')
        self.notebook.add(self.mcp_tab, text='Embedded MCP\nServer')
        self.notebook.add(self.historical_tab, text='Historical\nComparison')
        self.notebook.add(self.console_tab, text='Console\nLog')

        # Bottom frame (Entry + output text area)
        self.bottom_frame = ttk.Frame(self.pw, height=200)
        self._build_bottom_area(self.bottom_frame)

        # Console tab Visibility
        self.console_visible = False
        self.notebook.forget(self.console_tab)

        self.settings_tab.theme_var.set(self.settings.get('theme', 'Light'))
        self.apply_theme()

    def _build_bottom_area(self, parent: ttk.Frame):
        # Command row
        cmdrow = ttk.Frame(parent)
        cmdrow.pack(fill='x', padx=8, pady=(8, 4))
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

        self.copy_md_btn = ttk.Button(cmdrow, text='Copy Markdown', command=self.copy_markdown, state='disabled')
        self.copy_md_btn.grid(row=0, column=4, padx=(10, 0), pady=5, sticky='w')
        self.last_markdown = ''

        self.ai_progress_var = tk.StringVar(value='')
        ttk.Label(cmdrow, textvariable=self.ai_progress_var, foreground='blue', width=22).grid(
            row=0, column=3, padx=5, pady=5, sticky='w'
        )

        self.bottom_content = ttk.Frame(parent)
        self.bottom_content.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        # Output HTML area (HTMLLabel in scrollable frame)
        html_frame = ttk.Frame(self.bottom_content)
        html_frame.pack(fill='both', expand=True, padx=6, pady=6)

        self.html_view = HTMLLabel(
            html_frame,
            html='<h3>Welcome</h3><p>Policy AI will appear here.</p>',
            background='white',
        )
        self.html_view.pack(fill='both', expand=True, side='left')
        vscrollbar = ttk.Scrollbar(html_frame, orient='vertical', command=self.html_view.yview)
        self.html_view.configure(yscrollcommand=vscrollbar.set)
        vscrollbar.pack(fill='y', side='right')
        # self._bind_mousewheel(self.html_view)

    # def _bind_mousewheel(self, widget):
    #     def _on_mousewheel(event):
    #         if event.num == 5 or event.delta < 0:
    #             widget.yview_scroll(1, 'units')
    #         elif event.num == 4 or event.delta > 0:
    #             widget.yview_scroll(-1, 'units')
    #         return 'break'

    #     widget.bind_all('<MouseWheel>', _on_mousewheel)
    #     widget.bind_all('<Button-4>', _on_mousewheel)
    #     widget.bind_all('<Button-5>', _on_mousewheel)

    def update_bottom_entry(self, text: str):
        self.bottom_entry.delete(0, tk.END)
        self.bottom_entry.insert(0, text)

    def apply_theme(self, *args):
        theme_choice = self.settings_tab.theme_var.get()
        mapping = {'Light': 'litera', 'Dark': 'darkly'}

        theme_name = mapping.get(theme_choice, 'litera')
        try:
            self.style.theme_use(theme_name)
            pass
        except tk.TclError:
            pass
        except Exception as e:
            logger.warning(f'Failed to apply theme {theme_choice}: {e}')

        try:
            if theme_choice == 'Dark':
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
                insert_bg = '#ffffff'
                self.mcp_tab.mcp_log.configure(background=bg, foreground=fg, insertbackground=insert_bg)
                self.text_view.configure(background=bg, foreground=fg, insertbackground=insert_bg)
            else:
                bg = 'white'
                fg = 'black'
                insert_bg = '#000000'
                self.mcp_tab.mcp_log.configure(background=bg, foreground=fg, insertbackground=insert_bg)
                self.text_view.configure(background=bg, foreground=fg, insertbackground=insert_bg)
        except Exception as e:
            logger.warning(f'Failed to apply theme {theme_choice}: {e}')

        self.settings['theme'] = theme_choice
        config.save_settings(self.settings)
        logger.info(f'Theme set to {theme_choice} ({theme_name})')

        sizes = {'Small': 9, 'Medium': 11, 'Large': 13}
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

    def show_output_widget(self, fmt: str):
        # No-op: always uses the text_view now.
        pass

    def toggle_bottom(self):
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
            self.after(120, self.restore_sash)

    def restore_sash(self):
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

    from typing import Optional

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
        logger.info(f'Starting async tenancy load: {tenancy_id} (recursive={recursive}, ip={instance_principal})')

        def worker():  # noqa: C901
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
                        if cb is not None:
                            self.after(0, lambda: cb('Loading Identity Domains'))

                    success = self.policy_compartment_analysis.load_complete_identity_domains()
                    if not success:
                        raise RuntimeError('Failed to load identity domains')
                    if callback:
                        cb = callback.get('progress')
                        if cb is not None:
                            self.after(0, lambda: cb('Loading Compartments and Policies'))
                    success = self.policy_compartment_analysis.load_policies_and_compartments()
                    if not success:
                        raise RuntimeError('Failed to load policies and compartments')
                    self.caching.save_combined_cache()

            except Exception as e:
                logger.error(f'Error occurred while Loading Data: {e}')
                if callback:
                    cb = callback.get('error')
                    if cb is not None:
                        self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore
                return

            msg = f'Finished loading tenancy {tenancy_id}'
            logger.info(f'✅ {msg}')

            if callback:
                cb = callback.get('complete')
                if cb is not None:
                    self.after(0, lambda msg=msg: cb(True, msg, True))  # type: ignore

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

    def _import_cache_from_json(self, callback: dict | None = None):  # noqa: C901
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
                        self.after(0, lambda: cb(True, 'Loaded from JSON file', True))  # type: ignore
                else:
                    logger.warning('Failed to load from saved cache')

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
                if callback:
                    cb = callback.get('error')
                    if cb is not None:
                        self.after(0, lambda: cb(False, 'Failed to load from JSON file', True))  # type: ignore
            finally:
                pass

    def _export_cache_to_json(self):
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {type(filepath)} {filepath.name}')
            self.caching.save_combined_cache(export_file=filepath)
            logger.info(f'Wrote file {filepath.name}')
        else:
            logger.info('Export cancelled by user')

    def ask_genai_async(self, prompt: str, additional_instruction: str = '', callback=None):
        logger.info(f'Submitting GenAI prompt: {prompt}')
        self.set_bottom_output(f'#### Querying GenAI \n\n`{prompt}`')

        def worker():
            try:
                start_time = time.perf_counter()
                self.after(0, lambda: self.ai_progress_var.set('⌛ Running AI Query'))
                logger.debug('Starting ai.analyze_policy_statement asyncio.run in thread')
                q = queue.Queue()
                asyncio.run(
                    self.ai.analyze_policy_statement(
                        policy_text=prompt, additional_instruction=additional_instruction, queue=q
                    )
                )
                logger.debug(
                    'Finished ai.analyze_policy_statement asyncio.run in thread, waiting for result from queue'
                )
                ai_markdown_response = q.get()  # Get the result from the queue
                logger.debug(f'Received AI result from queue, posting update to UI: {ai_markdown_response}')
                self.after(0, lambda: self.set_bottom_output(str(ai_markdown_response)))

                if callback is not None:
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
        # Smartly render markdown or extract from JSON if needed for HTMLLabel output.
        import json

        extracted_markdown = content
        if content and not content.startswith('<'):
            try:
                maybe_json = json.loads(content)
                if (
                    isinstance(maybe_json, list)
                    and len(maybe_json) > 0
                    and isinstance(maybe_json[0], dict)
                    and 'text' in maybe_json[0]
                ):
                    extracted_markdown = maybe_json[0]['text']
            except Exception:
                extracted_markdown = content
            html = markdown2.markdown(extracted_markdown)
            # Postprocess: add monospace CSS to code/pre blocks
            html = html.replace('<code>', '<code style="font-family:monospace,Consolas,\'Courier New\',Courier;">')
            html = html.replace('<pre>', '<pre style="font-family:monospace,Consolas,\'Courier New\',Courier;">')
            self.last_markdown = extracted_markdown
        else:
            html = content  # already HTML (could be an error message)
            self.last_markdown = ''
        self.html_view.set_html(html)
        # Enable or disable the Copy Markdown button based on if markdown available
        if self.last_markdown and self.last_markdown.strip():
            self.copy_md_btn.configure(state='normal')
        else:
            self.copy_md_btn.configure(state='disabled')

    def copy_markdown(self):
        if self.last_markdown and self.last_markdown.strip():
            self.clipboard_clear()
            self.clipboard_append(self.last_markdown)
            self.update()  # Ensures clipboard is updated

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

    if args.verbose:
        set_log_level('DEBUG')
        logger.debug('Verbose logging enabled via --verbose')

    app = App()
    app.mainloop()
