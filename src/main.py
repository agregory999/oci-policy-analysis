import asyncio
import logging
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# Optional HTML widget (graceful fallback if not installed)
try:
    from tkhtmlview import HTMLLabel

    HAS_HTML = True
except Exception:
    HAS_HTML = False

from logic import config
from logic.caching import load_combined_cache, save_combined_cache
from logic.data_repo import AI, IdentityDomainsAnalysis, PolicyCompartmentAnalysis
from logic.logger import get_logger
from ui.settings_tab import SettingsTab
from ui.users_tab import UsersTab

# Logger
logger = get_logger()


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
        self.title('OCI Policy Analysis')
        self.geometry('1024x900')

        # Shared config & logger
        self.settings = config.load_settings()

        # Restore global logger level from settings (default INFO)
        level_name = self.settings.get('log_level', 'INFO')
        logger.setLevel(getattr(logging, level_name, logging.INFO))

        # Style / fonts
        self.style = ttk.Style()
        self.default_font = tkfont.nametofont('TkDefaultFont')
        self.style.configure('.', font=('Oracle Sans', 12))

        # Apply theme & font from settings
        self.apply_theme(self.settings.get('theme', self.style.theme_use()))
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

        # Tab References
        self.settings_tab = SettingsTab(self.notebook, self, self.settings)
        self.users_tab = UsersTab(self.notebook, self, self.identity_domain_analysis)
        self.notebook.add(self.settings_tab, text='Settings')
        self.notebook.add(self.users_tab, text='Users')

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

        # A small top-right bar with "Open Console"
        topbar = ttk.Frame(self)
        topbar.pack(fill='x')
        ttk.Button(topbar, text='Open Console', command=self.open_console).pack(side='right', padx=10, pady=6)

    # -------------------------
    # Bottom area construction
    # -------------------------
    def _build_bottom_area(self, parent: ttk.Frame):
        # Command row: Entry + quick button
        cmdrow = ttk.Frame(parent)
        cmdrow.pack(fill='x', padx=8, pady=(8, 4))

        self.bottom_entry = ttk.Entry(cmdrow)
        self.bottom_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(cmdrow, text='Log Entry', command=self._log_bottom_entry).pack(side='left')

        # A white background scrollable area with either HTMLLabel or Text
        container = ttk.Frame(parent)
        container.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        canvas = tk.Canvas(container, background='white', highlightthickness=0)
        vscroll = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)

        self.bottom_content = tk.Frame(canvas, background='white')
        content_window = canvas.create_window((0, 0), window=self.bottom_content, anchor='nw')

        def _resize(e):
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.itemconfig(content_window, width=canvas.winfo_width())

        self.bottom_content.bind('<Configure>', _resize)

        canvas.pack(side='left', fill='both', expand=True)
        vscroll.pack(side='right', fill='y')

        # HTML view or fallback Text
        if HAS_HTML:
            self.html_view = HTMLLabel(
                self.bottom_content, html='<h3>Welcome</h3><p>This area can show HTML output.</p>', background='white'
            )
            self.html_view.pack(fill='both', expand=True, padx=6, pady=6)
        else:
            self.html_view = tk.Text(self.bottom_content, wrap='word', background='white', relief='flat')
            self.html_view.insert('1.0', 'tkhtmlview not installed. Using plain Text display.\n')
            self.html_view.pack(fill='both', expand=True, padx=6, pady=6)

    def _log_bottom_entry(self):
        text = self.bottom_entry.get().strip()
        if text:
            logger.info(f'BottomEntry: {text}')

    # Public API for tabs to update the bottom entry
    def update_bottom_entry(self, text: str):
        self.bottom_entry.delete(0, tk.END)
        self.bottom_entry.insert(0, text)

    # -------------------------
    # Theme / Font application
    # -------------------------
    def apply_theme(self, theme: str):
        try:
            self.style.theme_use(theme)
            self.settings['theme'] = theme
            config.save_settings(self.settings)
            logger.info(f'Theme set to {theme}')
        except tk.TclError:
            logger.warning(f"Theme '{theme}' is not available")

    def apply_font_size(self, size_name: str):
        sizes = {'Small': 9, 'Medium': 11, 'Large': 13}
        size = sizes.get(size_name, 11)

        # Try Oracle Sans, fallback to TkDefaultFont
        families = tkfont.families()
        family = 'Oracle Sans' if 'Oracle Sans' in families else self.default_font.cget('family')

        self.default_font.configure(family=family, size=size)
        # (ttk widgets track TkDefaultFont automatically)
        self.settings['font_size'] = size_name
        config.save_settings(self.settings)
        logger.info(f'Font size set to {size_name} ({size}px)')

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
        self.console_window.geometry('800x400')

        # Text area + scrollbar
        text = tk.Text(self.console_window, wrap='word')
        scroll = ttk.Scrollbar(self.console_window, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        # Controls: Clear + Log Level
        controls = ttk.Frame(self.console_window)
        controls.pack(fill='x', pady=3)

        ttk.Button(controls, text='Clear', command=lambda: text.delete('1.0', tk.END)).pack(side='left', padx=6)

        ttk.Label(controls, text='Log Level:').pack(side='left', padx=(16, 6))
        level_var = tk.StringVar(value=logging.getLevelName(logger.level))
        level_combo = ttk.Combobox(
            controls,
            textvariable=level_var,
            values=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
            state='readonly',
            width=10,
        )
        level_combo.pack(side='left')

        def set_level(_=None):
            level = getattr(logging, level_var.get(), logging.INFO)
            logger.setLevel(level)
            self.settings['log_level'] = level_var.get()
            config.save_settings(self.settings)
            logger.info(f'Log level set to {level_var.get()}')

        level_combo.bind('<<ComboboxSelected>>', set_level)

        # Attach handler to global logger so logs from ANY module stream here
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

    # -------------------------
    # Loading of tenancy
    # -------------------------
    def load_tenancy_async(
        self,
        tenancy_id: str,
        recursive: bool,
        instance_principal: bool,
        named_profile: str,
        named_cache: str,
        callback=None,
    ):
        """Kick off tenancy loading in a background thread."""

        # Could load from cache or from tenancy with threading
        logger.info(f'Starting tenancy load: {tenancy_id} (recursive={recursive}, ip={instance_principal})')
        threading.Thread(
            target=lambda: asyncio.run(
                self._load_tenancy(tenancy_id, recursive, instance_principal, named_profile, named_cache, callback)
            ),
            daemon=True,
        ).start()

    async def _load_tenancy(  # noqa: C901
        self,
        tenancy_id: str,
        recursive: bool,
        instance_principal: bool,
        named_profile: str,
        named_cache: str,
        callback=None,
    ):
        """Async worker that actually performs the tenancy load."""
        try:
            success = False

            # If cached, simply load directly
            if named_cache:
                logger.info(f'Using named cache: {named_cache}')

                # Call into the data caching module
                success = load_combined_cache(
                    named_cache=named_cache,
                    policy_analysis=self.policy_compartment_analysis,
                    domains_analysis=self.identity_domain_analysis,
                )

            # If tenancy, initialize client
            elif named_profile:
                logger.info(f'Using named profile: {named_profile}')

                success = self.policy_compartment_analysis.initialize_client(
                    use_instance_principal=instance_principal, recursive=recursive, profile=named_profile
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
                if callback:
                    # Schedule safe UI update in main thread
                    self.after(0, lambda: callback(True, 'Loading Policies and Compartments'))

                success = self.policy_compartment_analysis.load_policies_and_compartments()

                if callback:
                    # Schedule safe UI update in main thread
                    self.after(0, lambda: callback(True, 'Loading Dynamic Groups'))

                success = self.identity_domain_analysis.load_all_dynamic_groups()

                if callback:
                    # Schedule safe UI update in main thread
                    self.after(0, lambda: callback(True, 'Loading Users and Groups'))

                success = self.identity_domain_analysis.load_domains_groups_users()

                save_combined_cache(
                    policy_analysis=self.policy_compartment_analysis, domains_analysis=self.identity_domain_analysis
                )

                if callback:
                    # Schedule safe UI update in main thread
                    self.after(
                        0,
                        lambda: callback(
                            True, f'Loading data from tenancy {self.policy_compartment_analysis.tenancy_name}'
                        ),
                    )

            # Fail if unsuccessful
            if not success:
                raise Exception('Failed to initialize')

            msg = f'Finished loading tenancy {tenancy_id}'
            logger.info(f'✅ {msg}')

            if callback:
                # Schedule safe UI update in main thread
                self.after(0, lambda: callback(True, msg, True))

            # Tell the tab to reload
            logger.info('Reload all tabs')
            self.users_tab.reload_data()

        except Exception as e:
            logger.error(f'❌ Failed to load tenancy: {e}')


if __name__ == '__main__':
    app = App()
    app.mainloop()
