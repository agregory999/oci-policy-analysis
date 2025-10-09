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

# Standard library imports
import argparse
import asyncio
import json
import logging
import threading
import time
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tkinter.font as tkfont
import webbrowser
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# import markdown
import markdown2
from bs4 import BeautifulSoup
from tkhtmlview import HTMLLabel
from ttkbootstrap import Window

from logic import config
from logic.caching import CacheManager
from logic.data_repo import AI, IdentityDomainsAnalysis, PolicyCompartmentAnalysis
from logic.logger import get_logger, set_log_level
from ui.policies_tab import PoliciesTab
from ui.settings_tab import SettingsTab
from ui.users_tab import UsersTab


class TextHandler(logging.Handler):
    """A logging handler that redirects log messages into a Tkinter Text widget.

    Attributes:
        text_widget (tk.Text): The text widget where log messages are appended.
    """

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)
        self.text_widget.after(0, self._append, msg)

    def _append(self, msg):
        self.text_widget.insert(tk.END, msg + '\n')
        self.text_widget.see(tk.END)


class App(Window):
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
        super().__init__(themename='litera')
        self.title('OCI Policy Analysis')
        self.geometry('1400x900')

        # Shared config & logger
        self.settings = config.load_settings()

        # Restore global logger level from settings (default INFO)
        level_name = self.settings.get('log_level', 'INFO')
        logger.setLevel(getattr(logging, level_name, logging.INFO))
        self.log_level_var = tk.StringVar(value=logging.getLevelName(logger.level))

        # Style / fonts
        # self.style = ttk.Style()
        self.default_font = tkfont.nametofont('TkDefaultFont')
        self.style.configure('.', font=('Oracle Sans', 12))
        self.style.configure('TButton', bootstyle='round')  # all buttons get round style
        self.style.configure('TNotebook.Tab', padding=[40, 20, 40, 20])  # notebook tab [left, top, right, bottom]

        # Apply theme & font from settings
        self.apply_theme(self.settings.get('theme', 'Light'))
        self.apply_font_size(self.settings.get('font_size', 'Medium'))

        # PanedWindow (vertical split)
        self.pw = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.pw.pack(fill='both', expand=True)

        # Top frame with Notebook
        self.top_frame = ttk.Frame(self.pw)
        self.pw.add(self.top_frame, weight=3)

        self.notebook = ttk.Notebook(self.top_frame)
        self.notebook.pack(fill='both', expand=True)

        # Repository / Data
        self.policy_compartment_analysis = PolicyCompartmentAnalysis()  # Core
        self.identity_domain_analysis = IdentityDomainsAnalysis()  # Core
        self.ai = AI()  # AI functionality

        # Caching Manager
        self.caching = CacheManager(
            policy_analysis=self.policy_compartment_analysis, domains_analysis=self.identity_domain_analysis
        )

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.caching, self.ai, self.settings)
        self.policies_tab = PoliciesTab(self.notebook, self, self.policy_compartment_analysis, self.settings)
        self.users_tab = UsersTab(self.notebook, self, self.identity_domain_analysis, self.policy_compartment_analysis)
        self.notebook.add(self.settings_tab, text='Settings\n(Start Here)')
        self.notebook.add(self.policies_tab, text='Policy\nAnalysis')
        self.notebook.add(self.users_tab, text='Groups\nUsers')

        # Bottom frame (Entry + HTML/Text area)
        self.bottom_frame = ttk.Frame(self.pw, height=200)
        self._build_bottom_area(self.bottom_frame)

        # Show/hide bottom according to settings
        if self.settings.get('bottom_visible', True):
            self.pw.add(self.bottom_frame, weight=1)
            # Restore sash position shortly after layout
            self.after(120, self.restore_sash)
        else:
            # not added initially
            pass

        # Console window state
        self.console_window = None
        self.console_handler = None

        # # A small top-right bar with "Open Console"
        # topbar = ttk.Frame(self)
        # topbar.pack(fill='x')
        # ttk.Button(topbar, text='Open Console', command=self.open_console).pack(side='right', padx=10, pady=6)

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
    def update_bottom_entry(self, text: str):
        self.bottom_entry.delete(0, tk.END)
        self.bottom_entry.insert(0, text)

    # -------------------------
    # Theme / Font application
    # -------------------------
    def apply_theme(self, choice: str):
        """Apply either Light (litera) or Dark (darkly)."""
        mapping = {'Light': 'litera', 'Dark': 'darkly'}
        theme_name = mapping.get(choice, 'litera')
        try:
            self.style.theme_use(theme_name)
            self.settings['theme'] = choice
            config.save_settings(self.settings)
            logger.info(f'Theme set to {choice} ({theme_name})')

        except Exception as e:
            logger.warning(f'Failed to apply theme {choice}: {e}')

        # Also update HTML view colors
        if hasattr(self, 'html_view'):
            logger.info(f'Change HTML to {choice} ({theme_name})')
            if choice == 'Dark':
                self.html_view.configure(background='black', foreground='white')
            else:
                self.html_view.configure(background='white', foreground='black')

    def apply_font_size(self, size_name: str):
        sizes = {'Small': 9, 'Medium': 11, 'Large': 13}
        size = sizes.get(size_name, 11)

        # Choose family (Oracle Sans if installed, else fallback)
        families = tkfont.families()
        family = 'Oracle Sans' if 'Oracle Sans' in families else 'Helvetica'

        # Tell ttkbootstrap to use this font globally
        font = (family, size)
        self.style.configure('.', font=font)  # "." applies to *all* widgets

        # Save & log
        self.settings['font_size'] = size_name
        config.save_settings(self.settings)
        logger.info(f'Font size set to {size_name} ({size}px)')

    def show_output_widget(self, fmt: str):
        self.text_view.pack_forget()
        self.md_frame.pack_forget()

        if fmt == 'Text':
            self.text_view.pack(fill='both', expand=True, padx=6, pady=6)
        else:  # Markdown
            self.md_frame.pack(fill='both', expand=True, padx=6, pady=6)

    # def show_output_widget(self, fmt: str):
    #     """Switch between Markdown (HTMLLabel) and Text (ScrolledText)."""
    #     self.html_view.pack_forget()
    #     self.text_view.pack_forget()

    #     if fmt == "Text":
    #         self.text_view.pack(fill="both", expand=True, padx=6, pady=6)
    #     else:  # "Markdown"
    #         self.html_view.pack(fill="both", expand=True, padx=6, pady=6)
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
            self.settings['bottom_visible'] = False
            config.save_settings(self.settings)
        else:
            self.pw.add(self.bottom_frame, weight=1)
            self.settings['bottom_visible'] = True
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

    # -------------------------
    # Console window & logging
    # -------------------------

    def open_console(self):
        if self.console_window and tk.Toplevel.winfo_exists(self.console_window):
            self.console_window.lift()
            return

        self.console_window = tk.Toplevel(self)
        self.console_window.title('Console Log')
        self.console_window.geometry('900x500')

        # --- Controls row at top ---
        controls = ttk.Frame(self.console_window)
        controls.pack(fill='x', padx=5, pady=5)

        ttk.Button(controls, text='Clear', command=lambda: text.delete('1.0', tk.END)).pack(side='left', padx=(0, 10))

        ttk.Label(controls, text='Log Level:').pack(side='left')
        level_combo = ttk.Combobox(
            controls,
            textvariable=self.log_level_var,
            values=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            state='readonly',
            width=10,
        )
        level_combo.pack(side='left')
        level_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_log_level())

        # --- Text area ---
        text = tk.Text(self.console_window, wrap='word')
        scroll = ttk.Scrollbar(self.console_window, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        # Attach handler
        self.console_handler = TextHandler(text)
        self.console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(self.console_handler)

        self.console_window.protocol('WM_DELETE_WINDOW', self.close_console)

    def close_console(self):
        if self.console_handler:
            logger.removeHandler(self.console_handler)
            self.console_handler = None
        if self.console_window:
            self.console_window.destroy()
            self.console_window = None

    def _apply_log_level(self):
        level = getattr(logging, self.log_level_var.get(), logging.INFO)
        set_log_level(level, component='main')

        # logger.setLevel(level)
        self.settings['log_level'] = self.log_level_var.get()
        config.save_settings(self.settings)
        logger.info(f'Log level set to {self.log_level_var.get()}')

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
                        session=named_session,
                        recursive=recursive,
                        profile=named_profile,
                    )
                    if not success:
                        raise RuntimeError('Failed to initialize PolicyCompartmentAnalysis client')
                    success = self.identity_domain_analysis.initialize_client(
                        use_instance_principal=instance_principal, profile=named_profile
                    )
                    # Fail if unable to initialize client
                    if not success:
                        raise RuntimeError('Failed to initialize IdentityDomainAnalysis client')

                    # Update the message
                    if callback and callback.get('progress'):
                        cb = callback.get('progress')
                        self.after(0, lambda: cb('Loading Policies and Compartments'))

                    success = self.policy_compartment_analysis.load_policies_and_compartments()

                    # Update the message
                    if callback and callback.get('progress'):
                        cb = callback.get('progress')
                        self.after(0, lambda: cb('Loading Users and Groups'))

                    success = self.identity_domain_analysis.load_complete_identity_domains()

                    # Write the cache
                    self.caching.save_combined_cache()

                    if callback and callback.get('progress'):
                        cb = callback.get('progress')
                        self.after(
                            0, lambda: cb(f'Loading data from tenancy {self.policy_compartment_analysis.tenancy_name}')
                        )  # type: ignore

                # Fail if unsuccessful
                if not success:
                    raise Exception('Failed to initialize')

                msg = f'Finished loading tenancy {tenancy_id}'
                logger.info(f'✅ {msg}')

                if callback and callback.get('complete'):
                    cb = callback.get('complete')
                    self.after(0, lambda msg=msg: cb(True, msg, True))  # type: ignore

                # Tell the tab to reload
                logger.info('Tenancy Load completeReload all tabs')
                self.users_tab._update_user_analysis_output()
                self.policies_tab.update_policy_output()

            except Exception as e:
                logger.error(f'❌ Failed to load tenancy: {e}')
                if callback and callback.get('error'):
                    cb = callback.get('error')
                    self.after(0, lambda e=e: cb(False, f'Failed to load tenancy - {e} - please try again', True))  # type: ignore

        threading.Thread(target=worker, daemon=True).start()

    def _import_cache_from_json(self, callback: dict = None):
        """Import cached data from a JSON file asynchronously. There can be a 3 callback(progress, complete, error) to update the UI."""
        if callback is None:
            callback = {}
        filepath = tkfiledialog.askopenfilename(filetypes=[('JSON Files', '*.json')])
        if filepath:
            try:
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
                self.users_tab._update_user_analysis_output()
                self.policies_tab.update_policy_output()

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
                            'date_ms': int(datetime.now().timestamp() * 1000),
                        }
                    )
                    self.caching.save_cache()
                # update UI in main thread
                self.after(0, lambda: self.set_bottom_output(ai_markdown_response))

                if callback:
                    self.after(0, lambda: callback(success=True, message='Set up AI successfully'))

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
                    self.after(0, lambda e=e: callback(success=False, message=f'Failed AI: {e}'))

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
    parser.add_argument('--console-log', action='store_true', help='Log to console instead of file')

    args = parser.parse_args()

    if args.console_log:
        # Reconfigure logger to use console
        logger = get_logger(use_console=True, component='main')
        logger.info('Logging to console')
    else:
        logger = get_logger(component='main')
        logger.info('Logging to app.log')

    # Configure logging based on verbose flag
    if args.verbose:
        set_log_level('DEBUG', component='main')
        # logger.setLevel('DEBUG')
        logger.debug('Verbose logging enabled')

    app = App()
    app.mainloop()
