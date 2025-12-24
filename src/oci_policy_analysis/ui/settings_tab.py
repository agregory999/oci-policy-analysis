##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# settings_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import os
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from oci_policy_analysis.common import config
from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.ai_repo import AI
from oci_policy_analysis.ui.data_table import DataTable

# Constants for data table
AI_MODEL_COLUMNS = ['Model Name', 'Model OCID', 'Lifecycle State', 'Creation Date']
AI_MODEL_COLUMN_WIDTHS = {'Model Name': 250, 'Model OCID': 450, 'Lifecycle State': 125, 'Creation Date': 250}

# Global logger for this module
logger = get_logger(component='settings')


class SettingsTab(ttk.Frame):
    """
    Settings Tab for OCI Policy Analysis UI.
    Allows configuration of tenancy, profile, MCP server, and AI settings.
    All tenancy data is loaded via this tab.
    """

    def __init__(self, parent, app, caching: CacheManager, ai_repo: AI, settings):
        """Initialize Settings Tab UI. Everything that the tab needs to exist in the notebook-based app.
        Args:
            parent (tk.Widget): The parent widget.
            app (App): The main application instance.
            caching (CacheManager): The caching manager instance.
            ai_repo (AI): The AI repository instance.
            settings (dict): The settings dictionary.
        """
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.ai_repo = ai_repo
        self.caching = caching

        # Set the options from the saved settings
        self.tenancy_var = tk.StringVar(value=self.settings.get('tenancy_ocid', ''))
        self.profile_var = tk.StringVar(value=self.settings.get('named_profile', ''))
        self.recursive_var = tk.BooleanVar(value=self.settings.get('recursive', True))
        self.ip_var = tk.BooleanVar(value=self.settings.get('instance_principal', False))
        self.ai_compartment_var = tk.StringVar(
            value=self.settings.get('ai_compartment_ocid', '<use compartment or tenancy ocid with genai permission>')
        )
        self.format_var = tk.StringVar(value=self.settings.get('result_format', 'Markdown'))
        self.mcp_port_var = tk.StringVar(value=str(self.settings.get('mcp_port', '8765')))
        self.mcp_host_var = tk.StringVar(value=self.settings.get('mcp_host', '127.0.0.1'))

        # Load profiles from ~/.oci/config
        self.profile_list = ['DEFAULT']
        try:
            # TODO - Check Env OCI_CLI_CONFIG_FILE
            with open(Path.home() / '.oci' / 'config') as fp:
                self.profile_list = [line[1:-2] for line in fp if line.startswith('[') and line.endswith(']\n')]
        except FileNotFoundError:
            logger.warning('OCI config file not found - default to instance principal only')
            self.profile_list = []
            self.ip_var.set(True)

        # Build the UI
        self._build_ui()

    def _build_ui(self):  # noqa: C901
        # ---- Top Row: Display + MCP ----
        top_row = ttk.Frame(self)
        top_row.pack(fill='x', padx=10, pady=10)

        # Display options (LabelFrame, LEFT)
        disp = ttk.LabelFrame(top_row, text='Display Options')
        disp.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=0)

        # MCP Config (LabelFrame, RIGHT of display)
        label_frm_mcp_config = ttk.LabelFrame(top_row, text='Embedded MCP')
        label_frm_mcp_config.pack(side='left', fill='both', expand=True)

        # Font size (in Display Panel)
        ttk.Label(disp, text='Font Size:').pack(side='left', padx=(8, 4))
        self.font_var = tk.StringVar(value=self.settings.get('font_size', 'Medium'))
        font_combo = ttk.Combobox(
            disp,
            textvariable=self.font_var,
            values=['Small', 'Medium', 'Large', 'Extra Large'],
            state='readonly',
            width=10,
        )
        font_combo.pack(side='left')
        font_combo.bind('<<ComboboxSelected>>', self.app.apply_theme)

        self.console_btn_var = tk.StringVar(value='Show Console Tab')
        self.console_button = ttk.Button(disp, textvariable=self.console_btn_var, command=self._toggle_console_tab)
        self.console_button.pack(side='left', padx=10, pady=6)

        # --- Maintenance Button next to Console ---
        self.maintenance_btn_var = tk.StringVar(value='Show Maintenance Tab')
        self.maintenance_button = ttk.Button(
            disp, textvariable=self.maintenance_btn_var, command=self._toggle_maintenance_tab
        )
        self.maintenance_button.pack(side='left', padx=10, pady=6)

        # --- MCP Configuration (RIGHT of Display Options) ---
        ttk.Label(label_frm_mcp_config, text='Host:').grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        ttk.Entry(label_frm_mcp_config, textvariable=self.mcp_host_var, width=20).grid(
            row=0, column=1, sticky=tk.W, padx=5
        )
        ttk.Label(label_frm_mcp_config, text='Port:').grid(row=0, column=2, sticky=tk.W, padx=5)
        ttk.Entry(label_frm_mcp_config, textvariable=self.mcp_port_var, width=10).grid(
            row=0, column=3, sticky=tk.W, padx=5
        )

        # Autosave for Host and Port
        def autosave_mcp_var(*args):
            try:
                port_val = int(self.mcp_port_var.get())
            except ValueError:
                # Don't autosave until a valid integer - could add error state if desired
                return
            self.settings['mcp_port'] = port_val
            self.settings['mcp_host'] = self.mcp_host_var.get().strip() or '127.0.0.1'
            config.save_settings(self.settings)
            logger.info('MCP configuration AUTOSAVED.')

        self.mcp_host_var.trace_add('write', autosave_mcp_var)
        self.mcp_port_var.trace_add('write', autosave_mcp_var)

        # Remove Save Config button (no longer needed)

        # --- Tenancy Config (LabelFrame) ---
        label_frm_tenancy_config = ttk.Labelframe(self, text='Tenancy and Config')
        label_frm_tenancy_config.pack(fill='x', padx=10, pady=10)

        # Instance Principal checkbox
        chk_instance_principal = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Instance Principal',
            variable=self.ip_var,
        )
        chk_instance_principal.grid(row=0, column=0, padx=5, pady=5, sticky='w')

        # Recursion checkbox
        self.recursive_load = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Recursive',
            variable=self.recursive_var,
        )
        self.recursive_load.grid(row=1, column=0, padx=5, pady=5, sticky='w')

        # Profile Selection
        self.label_profile = ttk.Label(label_frm_tenancy_config, text='Profile:')
        self.label_profile.grid(row=0, column=1, padx=5, pady=3)
        self.input_profile = ttk.OptionMenu(
            label_frm_tenancy_config, self.profile_var, self.profile_var.get(), *self.profile_list
        )
        self.input_profile.config(width=20, state='normal' if len(self.profile_list) > 0 else 'disabled')
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)

        # Get available cached copies
        self.label_cache = ttk.Label(label_frm_tenancy_config, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.cache_list = self.caching.get_available_cache(None)
        self.cache_var = tk.StringVar(value=self.cache_list[0] if len(self.cache_list) > 0 else 'No Cache Available')
        # self.cache_var = tk.StringVar()
        self.cache_list_dropdown = ttk.OptionMenu(
            label_frm_tenancy_config, self.cache_var, self.cache_var.get(), *self.cache_list
        )
        self.cache_list_dropdown.config(width=20)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)

        # Load button (lambda function with boolean for cache)
        ttk.Button(
            label_frm_tenancy_config,
            width=25,
            text='Load from Tenancy',
            command=lambda: self._on_load_clicked(use_cache=False),
        ).grid(row=0, column=3, padx=5, pady=5, sticky='w')
        ttk.Button(
            label_frm_tenancy_config,
            width=25,
            text='Load from Cache',
            command=lambda: self._on_load_clicked(use_cache=True),
        ).grid(row=1, column=3, padx=5, pady=5, sticky='w')

        def open_link(event):
            link = 'https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clitoken.htm'
            logger.info(f'Opening link in browser: {link}')
            webbrowser.open_new(link)

        # Session Token (with link)
        session_auth_link_label = ttk.Label(
            label_frm_tenancy_config,
            text='Session Token (oci session authenticate)',
            cursor='hand2',
            foreground='#0000EE',  # Make it a link
        )
        session_auth_link_label.bind('<Button-1>', open_link)
        session_auth_link_label.grid(row=2, column=0, columnspan=2, padx=5, pady=3)
        self.session_token_var = tk.StringVar()
        self.session_token_entry = ttk.Entry(label_frm_tenancy_config, textvariable=self.session_token_var, width=25)
        self.session_token_entry.grid(row=2, column=2, padx=5, pady=3)
        ttk.Button(
            label_frm_tenancy_config,
            width=25,
            text='Load via Session Token',
            command=lambda: self._on_load_clicked(use_cache=False),
        ).grid(row=2, column=3, padx=5, pady=5, sticky='w')

        ttk.Separator(label_frm_tenancy_config, orient=tk.VERTICAL).grid(
            row=0, column=4, rowspan=4, padx=5, pady=5, sticky='w'
        )

        # Import / Export buttons
        ttk.Button(
            label_frm_tenancy_config,
            width=30,
            text='Import JSON (share/backup)',
            command=lambda: self.app._import_cache_from_json(callback={'complete': self._on_load_finished}),
        ).grid(row=0, column=5, padx=5, pady=5, sticky='w')

        ttk.Button(
            label_frm_tenancy_config,
            width=30,
            text='Export JSON (share/backup)',
            command=lambda: self.app._export_cache_to_json(),
        ).grid(row=1, column=5, padx=5, pady=5, sticky='w')

        # --- New Button: Load from Compliance Output Data ---
        def _on_load_compliance_output():
            # from tkinter import filedialog
            # import os

            folder_selected = filedialog.askdirectory(title='Select Compliance Output Directory')
            if not folder_selected or not os.path.isdir(folder_selected):
                messagebox.showinfo('Load Compliance Output', 'No directory was selected or path is invalid.')
                return
            # Show quick UI progress
            self.progress_var.set(f'Loading compliance data from: {folder_selected}')
            # Call the app method (must exist/app-supports), use same callbacks as tenancy load
            self.app.load_compliance_output_async(
                folder_selected,
                callback={
                    'progress': self._on_load_progress,
                    'complete': self._on_load_finished,
                    'error': self._on_load_finished,
                },
            )

        ttk.Button(
            label_frm_tenancy_config,
            width=30,
            text='Load from Compliance Output Data',
            command=_on_load_compliance_output,
        ).grid(row=2, column=5, padx=5, pady=5, sticky='w')

        ttk.Separator(label_frm_tenancy_config, orient=tk.VERTICAL).grid(row=0, column=6, rowspan=4, pady=5, sticky='w')

        # Progress indicator - move to its own row below buttons, at right
        self.progress_var = tk.StringVar(value='')
        self.progress_label = ttk.Label(label_frm_tenancy_config, textvariable=self.progress_var, foreground='blue')
        self.progress_label.grid(row=1, column=6, padx=5, pady=(1, 5), sticky='w')

        # Label Frame for AI Connection
        self.label_frm_ai_config = ttk.Labelframe(self, text='OCI GenAI')
        self.label_frm_ai_config.pack(fill='x', padx=5, pady=5)

        # AI Toggle
        self.ai_toggle_btn = ttk.Button(
            self.label_frm_ai_config, state=tk.DISABLED, text='Toggle AI Pane', command=self.app.toggle_bottom
        )
        self.ai_toggle_btn.grid(row=0, column=0, padx=3, pady=3, sticky='ew')

        def populate_model_tree():
            """Populate the model Treeview with available models from list_models."""
            logger.info('Populating model tree')
            # Check and initialize AI client if needed
            if not self.ai_repo.initialized:
                logger.info(
                    f'Creating AI Clients from selected Profile: {self.profile_var.get()} or IP:{self.ip_var.get()}.'
                )
                self.ai_repo.initialize_client(use_instance_principal=self.ip_var.get(), profile=self.profile_var.get())
                # Grab endpoint/compartment for variable
                self.endpoint_var.set(self.ai_repo.base_endpoint)
                self.ai_compartment_var.set(self.ai_repo.tenancy_ocid)
                logger.debug(f'AI initialized: {self.ai_repo.initialized}')

            if self.ai_repo.initialized:
                ai_models = self.ai_repo.list_models()
                logger.info(f'list_models returned {len(ai_models)} models')

                # Put in Model Data Table
                self.ai_model_table.update_data(new_data=ai_models)
            else:
                logger.warning('AI client not initialized, cannot list models')

        self.refresh_button = ttk.Button(
            self.label_frm_ai_config, text='Refresh Models (using selected profile)', command=populate_model_tree
        )
        self.refresh_button.grid(row=0, column=1, padx=3, pady=3, sticky='ew')

        self.ai_progress_var = tk.StringVar(value='')
        self.ai_progress_label = ttk.Label(
            self.label_frm_ai_config, textvariable=self.ai_progress_var, foreground='blue'
        )
        self.ai_progress_label.grid(row=0, column=2, padx=3, pady=3, sticky='w')

        def update_model_ocid(selected_items):
            if selected_items:
                model_ocid = selected_items[0].get('Model OCID', '')
                self.model_id_var.set(model_ocid)
                logger.info(f'Updated Model ID entry with OCID {model_ocid} from data table selection')

        # Data Table for models
        self.ai_model_table = DataTable(
            parent=self.label_frm_ai_config,
            columns=AI_MODEL_COLUMNS,
            display_columns=AI_MODEL_COLUMNS,
            column_widths=AI_MODEL_COLUMN_WIDTHS,
            data=[],
            selection_callback=update_model_ocid,
            # row_context_menu_callback=model_ocid_right_click,
            multi_select=False,
        )
        self.ai_model_table.grid(row=1, column=0, columnspan=3, padx=3, pady=3, sticky='ew')

        self.model_id_var = tk.StringVar()

        ttk.Label(self.label_frm_ai_config, text='Regional Endpoint:').grid(
            row=3, column=0, padx=2, pady=3, sticky='ew'
        )
        self.endpoint_var = tk.StringVar()
        self.endpoint_entry = ttk.Entry(self.label_frm_ai_config, textvariable=self.endpoint_var, width=80)
        self.endpoint_entry.grid(row=3, column=1, padx=3, pady=3, sticky='ew')

        ttk.Label(self.label_frm_ai_config, text='Compartment (for GenAI):').grid(
            row=4, column=0, padx=2, pady=3, sticky='ew'
        )
        self.ai_compartment_var = tk.StringVar()
        self.ai_compartment_entry = ttk.Entry(self.label_frm_ai_config, textvariable=self.ai_compartment_var, width=80)
        self.ai_compartment_entry.grid(row=4, column=1, padx=3, pady=3, sticky='ew')

        apply_button = ttk.Button(
            self.label_frm_ai_config, text='Apply and Test GenAI Settings', command=self.apply_config
        )
        apply_button.grid(row=2, column=2, rowspan=3, padx=3, pady=3, sticky='ew')
        logger.debug('Apply button created')

        # (Moved MCP block to top and made autosave; original section removed)

    # -------------------------
    # Loading of tenancy buttons
    # -------------------------
    def _save_mcp_config(self):
        """Save full settings to disk."""
        # Update MCP settings
        try:
            port_val = int(self.mcp_port_var.get())
        except ValueError:
            messagebox.showerror('Invalid Port', 'Port must be an integer.')
            return

        self.settings['mcp_port'] = port_val
        self.settings['mcp_host'] = self.mcp_host_var.get().strip() or '127.0.0.1'
        config.save_settings(self.settings)
        logger.info('MCP configuration saved to settings.')

    def _on_load_clicked(self, use_cache: bool):
        """Handle Load Tenancy button click.  Calls main app to load tenancy asynchronously.
        Args:
            use_cache (bool): Whether to load from cache or live tenancy.
        """
        self.settings['tenancy_ocid'] = self.tenancy_var.get()
        self.settings['recursive'] = self.recursive_var.get()
        self.settings['instance_principal'] = self.ip_var.get()
        self.settings['named_profile'] = self.profile_var.get()
        self.settings['ai_compartment_ocid'] = self.profile_var.get()

        # Save the settings now
        config.save_settings(self.settings)

        # Kick off async call in main app
        self.app.load_tenancy_async(
            tenancy_id=self.tenancy_var.get(),
            recursive=self.recursive_var.get(),
            instance_principal=self.ip_var.get(),
            named_profile=self.profile_var.get() if not use_cache else None,
            named_session=self.session_token_var.get() if self.session_token_var.get() != '' else None,
            # named_cache=self.cache_var.get().replace('\n', '_') if use_cache else None,
            named_cache=self.cache_var.get() if use_cache else None,
            callback={
                'progress': self._on_load_progress,
                'complete': self._on_load_finished,
                'error': self._on_load_finished,
            },
        )

    def _on_load_progress(self, message: str, clear: bool = False):
        """Callback from App to update progress during tenancy loading."""
        self.progress_var.set(f'{message}')
        if clear:
            self.after(2000, lambda: self.progress_var.set(''))

    def _on_load_finished(self, success: bool, message: str, clear: bool = False):
        """Callback from App once tenancy loading completes."""
        if success:
            # Format "data as of" date to "YYYY-Mon-DD hh:mi:ssZ"
            data_as_of = getattr(getattr(self.app, 'policy_compartment_analysis', None), 'data_as_of', None)
            if data_as_of:
                import datetime

                try:
                    dt = datetime.datetime.fromisoformat(data_as_of.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%b-%d %H:%M:%SZ')
                except Exception:
                    date_str = str(data_as_of)
                date_note = f'Data as of: {date_str}'
            else:
                date_note = ''
            self.progress_var.set(f'[OK]{message}')
            self.after(2000, lambda date_note=date_note: self.progress_var.set(date_note))
            logger.info('Updating UI after load')
            self.app.policies_tab.update_policy_output()
            self.app.policies_tab.enable_widgets_after_load()
            self.app.users_tab.update_user_analysis_output()
        else:
            self.progress_var.set(f'[X]{message}')

        # Schedule it to go away if clear was set
        if clear:
            self.after(5000, lambda: self.progress_var.set(''))

        # After loading, update the cache list in case new one was created
        logger.info('Updating cache list after load')
        self.refresh_cache_list()

    def refresh_cache_list(self):
        """Update the cache list OptionMenu in the Settings tab to reflect the current state."""
        self.cache_list = self.caching.get_available_cache(None)
        menu = self.cache_list_dropdown['menu']
        menu.delete(0, 'end')
        for cache_name in self.cache_list:
            menu.add_command(label=cache_name, command=lambda value=cache_name: self.cache_var.set(value))
        if self.cache_list:
            self.cache_var.set(self.cache_list[0])
        else:
            self.cache_var.set('No Cache Available')

    # -------------------------
    # AI Enablement
    # -------------------------
    def apply_config(self):
        """
        Apply changes to Model ID and Endpoint in AI client.
        """
        start_time = time.perf_counter()
        model_id = self.model_id_var.get().strip()
        endpoint = self.endpoint_var.get().strip()
        compartment_ocid = self.ai_compartment_var.get().strip()
        logger.info('Applying config changes: Model ID=%s, Endpoint=%s', model_id, endpoint)
        self.ai_progress_var.set('⌛ Running AI test call…')

        try:
            self.ai_repo.update_config(model_ocid=model_id, endpoint=endpoint, compartment_ocid=compartment_ocid)
            logger.info(f'Configuration updated successfully in {time.perf_counter() - start_time:.2f} seconds')

            # Make AI Call to test with callback
            self.app.ask_genai_async(
                prompt='What is the meaning of life?',
                additional_instruction='TEST',
                callback=self._on_ai_enablement_finished,
            )

        except Exception as e:
            logger.error('Failed to update configuration: %s', e)

    def _on_ai_enablement_finished(self, success: bool, message: str, clear: bool = False):
        """
        Callback from App once AI loading completes. Used to enable AI toggle button if successful.

        Args:
            success (bool): Whether the AI call was successful.
            message (str): Message to display.
            clear (bool): Whether to clear the message after a delay.
        """
        if success:
            self.ai_progress_var.set(f'[OK] {message}')
            # Enable the toggle button
            self.ai_toggle_btn.config(state=tk.NORMAL)
            logger.info('AI Enablement successful, toggle button enabled')
        else:
            self.ai_progress_var.set(f'[X] {message}')

        # Schedule it to go away if clear was set
        if clear:
            self.after(2000, lambda: self.ai_progress_var.set(''))

    # -------------------------
    # Console Tab Toggle
    # -------------------------

    def _toggle_console_tab(self):
        """Toggle the visibility of the console tab in the notebook."""
        notebook = self.app.notebook
        console_tab = self.app.console_tab

        if self.app.console_visible:
            notebook.forget(console_tab)
            self.console_btn_var.set('Show Console Tab')
            self.app.console_visible = False
            logger.info('Console tab hidden')
        else:
            notebook.add(console_tab, text='Console Logging\n(Admin)')
            self.console_btn_var.set('Hide Console Tab')
            self.app.console_visible = True
            logger.info('Console tab shown')

    # -------------------------
    # Maintenance Tab Toggle
    # -------------------------

    def _toggle_maintenance_tab(self):
        """Toggle the visibility of the maintenance tab in the notebook."""
        notebook = self.app.notebook
        maintenance_tab = self.app.maintenance_tab

        if self.app.maintenance_visible:
            notebook.forget(maintenance_tab)
            self.maintenance_btn_var.set('Show Maintenance Tab')
            self.app.maintenance_visible = False
            logger.info('Maintenance tab hidden')
        else:
            notebook.add(maintenance_tab, text='Maintenance\n(Admin)')
            self.maintenance_btn_var.set('Hide Maintenance Tab')
            self.app.maintenance_visible = True
            logger.info('Maintenance tab shown')
