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
from oci_policy_analysis.ui.base_tab import BaseUITab
from oci_policy_analysis.ui.data_table import DataTable

# Constants for data table
AI_MODEL_COLUMNS = ['Model Name', 'Model OCID', 'Lifecycle State', 'Creation Date']
AI_MODEL_COLUMN_WIDTHS = {'Model Name': 250, 'Model OCID': 450, 'Lifecycle State': 125, 'Creation Date': 250}

# Context help messages for the SettingsTab
CONTEXT_HELP = {
    'DISPLAY_OPTIONS': 'Adjust display, font size, and power-user tab features. Affects the entire UI experience.',
    'MCP_CONFIG': 'Configure the built-in MCP server for advanced automation and API analysis integration.',
    'TENANCY_CONFIG': (
        'Set your OCI tenancy and authentication method. Choose between instance principal, named profile, or session token. '
        'Load data either directly from OCI or from a cached JSON, manage policy data, and import/export backups. '
        'Use these controls to initialize or refresh the core analysis dataset.'
    ),
    'INSTANCE_PRINCIPAL': 'Use when running from OCI Compute with permissions. No config needed.',
    'LOAD_ALL_USERS': 'If checked, loads all users for analysis. Uncheck for groups-only mode.',
    'RECURSIVE_LOAD': 'If checked, load policies from all compartments.\nUncheck for root compartment only.',
    'CACHE_LABEL': "A (P) before a cache means it is 'preserved' and will not be automatically overwritten or deleted. To update or manage the cache list, use the Maintenance Tab.",
    'CACHE_DROPDOWN': "A (P) before a cache means it is 'preserved' and will not be automatically overwritten or deleted. To update or manage the cache list, use the Maintenance Tab.",
    'SESSION_TOKEN': "Paste temporary token from 'oci session authenticate'. Use for cloud OCI CLI auth.",
    'COMPLIANCE_OUTPUT': (
        'Load from the output of an unzipped CIS Complaince run - these scripts are provided by Oracle as part of MAP engagement, '
        'or freely downloadable from https://github.com/oci-landing-zones/oci-cis-landingzone-quickstart/blob/main/README.md'
    ),
    'OCI_GENAI': (
        'Set up connectivity to Oracle’s Generative AI services. Select or refresh models, test endpoints and compartments, and verify access. '
        'Use this panel to enable policy text analysis and AI-driven explanations.'
    ),
    'RECOMMENDATION_CONSOLIDATION': (
        'Control which intelligence strategies run (risk, overlap, cleanup checks, consolidation suggestions, recommendations). '
        'Uncheck to skip. Preferences are saved globally and used by the Recommendations tab.'
    ),
    # 'DOMAIN_COMPARTMENTS': Removed; replaced by compartment depth selector.
}

# Global logger for this module
logger = get_logger(component='settings_tab')


class SettingsTab(BaseUITab):
    """
    Settings Tab for OCI Policy Analysis UI.
    Allows configuration of tenancy, profile, MCP server, and AI settings.
    All tenancy data is loaded via this tab.
    """

    def __init__(self, parent, app, caching: CacheManager, ai_repo: AI, settings):
        """Initialize Settings Tab UI. Everything that the tab needs to exist in the notebook-based app."""
        super().__init__(
            parent,
            default_help_text='Manage core settings for the OCI Policy Analysis tool, including tenancy authentication, caching, MCP server configuration, GenAI options, and general UI preferences.',
        )
        self.app = app
        self.settings = settings
        self.ai_repo = ai_repo
        self.caching = caching
        self.page_help_text = self.default_help_text
        # Remove redundant page_help_frame, label, and methods; now in base

        # Set the options from the saved settings
        self.tenancy_var = tk.StringVar(value=self.settings.get('tenancy_ocid', ''))
        self.profile_var = tk.StringVar(value=self.settings.get('named_profile', ''))
        # Remove: tenancy_var trace for domain compartment OCID field, as that textbox/feature is now gone.

        # When profile_var changes, optionally auto-update tenancy OCID if a profile->tenancy mapping is present.
        # This ensures that if the application keeps a mapping of profiles to tenancy OCIDs, changing
        # the profile will also automatically update tenancy_var, which itself triggers the OCID refresh logic.
        # If no such mapping exists in settings (profile_ocid_map), nothing happens.
        self.recursive_var = tk.BooleanVar(value=self.settings.get('recursive', True))
        self.ip_var = tk.BooleanVar(value=self.settings.get('instance_principal', False))
        self.context_help_var = tk.BooleanVar(value=self.settings.get('context_help', True))
        # ----- NEW: Load All Users Option -----
        self.load_all_users_var = tk.BooleanVar(value=self.settings.get('load_all_users', True))
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

    # ----- Page Help (Context Help) helpers -----
    # (Now inherited from BaseUITab. Any customizations can override as needed.)

    def _build_ui(self):  # noqa: C901
        # ---- Top Row: Display + MCP ----
        top_row = ttk.Frame(self)
        top_row.pack(fill='x', padx=10, pady=10)

        # Display options (LabelFrame, LEFT)
        disp = ttk.LabelFrame(top_row, text='Display Options')
        disp.pack(side='left', fill='both', expand=True, padx=(0, 8), pady=0)

        # --- Page Help context for Display Options ---
        self.add_context_help(disp, CONTEXT_HELP['DISPLAY_OPTIONS'])

        # MCP Config (LabelFrame, RIGHT of display)
        label_frm_mcp_config = ttk.LabelFrame(top_row, text='Embedded MCP')
        label_frm_mcp_config.pack(side='left', fill='both', expand=True)
        self.add_context_help(
            label_frm_mcp_config,
            CONTEXT_HELP['MCP_CONFIG'],
        )

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
        # Instead of direct apply_theme,
        # call App.apply_theme, which itself triggers refresh_all_tabs_settings.
        font_combo.bind('<<ComboboxSelected>>', self.app.apply_theme)

        # --- Context Help Checkbox ---
        self.context_help_check = ttk.Checkbutton(
            disp,
            text='Context Help',
            variable=self.context_help_var,
            command=self._on_context_help_changed,
        )
        self.context_help_check.pack(side='left', padx=10, pady=6)

        # --- Console / Debug Button ---
        self.console_btn_var = tk.StringVar(value='Show Console and Debug Tab')
        self.console_button = ttk.Button(disp, textvariable=self.console_btn_var, command=self._toggle_console_tab)
        self.console_button.pack(side='left', padx=10, pady=6)

        # --- Maintenance Button next to Console ---
        self.maintenance_btn_var = tk.StringVar(value='Show Maintenance Tab')
        self.maintenance_button = ttk.Button(
            disp, textvariable=self.maintenance_btn_var, command=self._toggle_maintenance_tab
        )
        self.maintenance_button.pack(side='left', padx=10, pady=6)

        # --- Advanced Tabs Button ---
        self.advanced_btn_var = tk.StringVar(value='Show Advanced Tabs')
        self.advanced_button = ttk.Button(disp, textvariable=self.advanced_btn_var, command=self._toggle_advanced_tabs)
        self.advanced_button.pack(side='left', padx=10, pady=6)

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

        # --- Page Help context for Tenancy and Config ---
        def _show_tenancy_help(_event=None):
            self.set_page_help_text(CONTEXT_HELP['TENANCY_CONFIG'])

        label_frm_tenancy_config.bind('<Enter>', _show_tenancy_help)
        label_frm_tenancy_config.bind('<Leave>', lambda e=None: self.set_page_help_text(self.default_help_text))

        # --- Checkbox group: Instance Principal, Load All Users, Recursive ---
        frm_chkboxes = ttk.Frame(label_frm_tenancy_config)
        frm_chkboxes.grid(row=0, column=0, rowspan=2, padx=(0, 2), pady=(0, 1), sticky='nw')

        # Instance Principal checkbox
        chk_instance_principal = ttk.Checkbutton(
            frm_chkboxes,
            text='Instance Principal',
            variable=self.ip_var,
        )
        chk_instance_principal.grid(row=0, column=0, padx=4, pady=(2, 2), sticky='w')
        self.add_context_help(chk_instance_principal, CONTEXT_HELP['INSTANCE_PRINCIPAL'])

        # Load All Users checkbox
        self.load_all_users_check = ttk.Checkbutton(
            frm_chkboxes,
            text='Load All Users',
            variable=self.load_all_users_var,
            command=self._on_load_all_users_changed,
        )
        self.load_all_users_check.grid(row=1, column=0, padx=4, pady=(2, 2), sticky='w')
        self.add_context_help(self.load_all_users_check, CONTEXT_HELP['LOAD_ALL_USERS'])

        # Recursion checkbox
        self.recursive_load = ttk.Checkbutton(
            frm_chkboxes,
            text='Recursive',
            variable=self.recursive_var,
        )
        self.recursive_load.grid(row=2, column=0, padx=4, pady=(2, 2), sticky='w')
        self.add_context_help(self.recursive_load, CONTEXT_HELP['RECURSIVE_LOAD'])

        # Profile Selection
        self.label_profile = ttk.Label(label_frm_tenancy_config, text='Profile:')
        self.label_profile.grid(row=0, column=1, padx=5, pady=3)
        self.input_profile = ttk.OptionMenu(
            label_frm_tenancy_config, self.profile_var, self.profile_var.get(), *self.profile_list
        )

        # --- Compartment Level for Additional Domains ---
        lvl_label = ttk.Label(label_frm_tenancy_config, text='Compartment Level for Additional Domains:')
        lvl_label.grid(row=3, column=0, columnspan=2, padx=5, pady=(10, 2), sticky='w')
        self.add_context_help(
            lvl_label,
            'Choose how many levels below the root compartment will be searched for identity domains. '
            'Level 1 is root only (fastest, recommended), higher levels (up to 6) will search deeper compartment trees. '
            'Selecting the maximum level may cause much longer load times and many extra API calls in large environments.',
        )
        COMPARTMENT_DEPTH_CHOICES = [('1 (Root Only)', 1), ('2', 2), ('3', 3), ('4', 4), ('5', 5), ('6', 6)]
        self.compartment_depth_var = tk.IntVar(value=1)

        def update_depth_from_settings():
            by_tenancy = self.settings.get('domain_compartment_depth_by_tenancy', {})
            tenancy = (self.tenancy_var.get() or '').strip()
            depth = by_tenancy.get(tenancy, 1)
            self.compartment_depth_var.set(depth)
            self.compartment_depth_dropdown.set(self.depth_string_map.get(depth, '1 (Root Only)'))

        def depth_on_tenancy_change(*_):
            update_depth_from_settings()

        # Bind update logic on tenancy switch
        self.tenancy_var.trace_add('write', depth_on_tenancy_change)
        # Dropdown UI
        depth_val_strings = [label for label, val in COMPARTMENT_DEPTH_CHOICES]
        self.depth_value_map = dict(COMPARTMENT_DEPTH_CHOICES)
        self.depth_string_map = {val: label for label, val in COMPARTMENT_DEPTH_CHOICES}
        self.compartment_depth_dropdown = ttk.Combobox(
            label_frm_tenancy_config, state='readonly', width=16, values=depth_val_strings
        )
        self.compartment_depth_dropdown.grid(row=3, column=2, padx=5, pady=(10, 2), sticky='w')

        # Add Setup Guide link next to compartment depth selector
        setup_guide_link = ttk.Label(
            label_frm_tenancy_config,
            text='Tenancy Setup Guide',
            foreground='#0645AD',
            cursor='hand2',
            font=('TkDefaultFont', 10, 'underline'),
        )
        setup_guide_link.grid(row=3, column=3, padx=3, pady=(10, 2), sticky='w')
        setup_doc_url = self.DOCROOT + '/setup.html'
        setup_guide_link.bind('<Button-1>', lambda e: self.open_link(setup_doc_url))
        self.add_context_help(
            setup_guide_link,
            'Open the full OCI Policy Analysis setup instructions (docs/source/setup.md) in your web browser.',
        )

        # Add Settings link next to compartment depth selector
        settings_link = ttk.Label(
            label_frm_tenancy_config,
            text='Settings Page Guide',
            foreground='#0645AD',
            cursor='hand2',
            font=('TkDefaultFont', 10, 'underline'),
        )
        settings_link.grid(row=3, column=5, padx=3, pady=(10, 2), sticky='w')
        settings_doc_url = self.DOCROOT + '/usage.html#settings-tab-start-here'
        settings_link.bind('<Button-1>', lambda e: self.open_link(settings_doc_url))
        self.add_context_help(
            settings_link, 'Open the Settings Tab as part of Usage documentation in your web browser.'
        )

        def on_depth_select(event):
            selected_label = self.compartment_depth_dropdown.get()
            selected_val = self.depth_value_map.get(selected_label, 1)
            # Save for this tenancy
            tenancy = (self.tenancy_var.get() or '').strip()
            if tenancy:
                by_tenancy = self.settings.get('domain_compartment_depth_by_tenancy', {})
                by_tenancy[tenancy] = selected_val
                self.settings['domain_compartment_depth_by_tenancy'] = by_tenancy
                config.save_settings(self.settings)
            self.compartment_depth_var.set(selected_val)

        # Bind update logic on dropdown selection
        self.compartment_depth_dropdown.bind('<<ComboboxSelected>>', on_depth_select)
        # Set initial value
        self.compartment_depth_dropdown.set(
            self.depth_string_map.get(self.compartment_depth_var.get(), '1 (Root Only)')
        )
        # Context Help
        self.add_context_help(
            self.compartment_depth_dropdown,
            'Controls how many levels below the root compartment will be searched for identity domains. '
            'Level 1 is root only (recommended for most tenancies). Selecting higher levels increases search depth, but can significantly slow load times (many more API calls in large hierarchies).',
        )

        # When profile_var is changed, optionally auto-update tenancy OCID from settings (if your app does this)
        def _on_profile_changed(*_args):
            # This logic assumes a mapping from profile name to tenancy_ocid in settings
            profiles_by_tenancy = self.settings.get('profile_ocid_map', {})
            tenancy_for_profile = profiles_by_tenancy.get(self.profile_var.get())
            if tenancy_for_profile:
                self.tenancy_var.set(tenancy_for_profile)
            else:
                self.tenancy_var.set('')

        self.profile_var.trace_add('write', _on_profile_changed)
        self.input_profile.config(width=20, state='normal' if len(self.profile_list) > 0 else 'disabled')
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)

        # Get available cached copies
        self.label_cache = ttk.Label(label_frm_tenancy_config, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.add_context_help(self.label_cache, CONTEXT_HELP['CACHE_LABEL'])
        self.cache_list = self.caching.get_available_cache(None)
        # Use preserved_caches set from CacheManager for cache list display
        preserved_caches = self.caching.get_preserved_cache_set()
        self.cache_list_display = [f'(P) {name}' if name in preserved_caches else name for name in self.cache_list]
        # Mapping: display -> actual cache key
        self.display_to_cache_key = {
            f'(P) {name}' if name in preserved_caches else name: name for name in self.cache_list
        }
        self.cache_var = tk.StringVar(
            value=self.cache_list_display[0] if len(self.cache_list_display) > 0 else 'No Cache Available'
        )
        self.cache_list_dropdown = ttk.OptionMenu(
            label_frm_tenancy_config, self.cache_var, self.cache_var.get(), *self.cache_list_display
        )
        self.cache_list_dropdown.config(width=20)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)
        self.add_context_help(self.cache_list_dropdown, CONTEXT_HELP['CACHE_DROPDOWN'])

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
        self.add_context_help(
            session_auth_link_label,
            CONTEXT_HELP['SESSION_TOKEN'],
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
                load_all_users=self.load_all_users_var.get(),
            )

        self.btn_load_compliance = ttk.Button(
            label_frm_tenancy_config,
            width=30,
            text='Load from Compliance Output Data',
            command=_on_load_compliance_output,
        )
        self.btn_load_compliance.grid(row=2, column=5, padx=5, pady=5, sticky='w')

        # --- Page Help context for Compliance Output button ---
        def _show_compliance_help(_event=None):
            self.set_page_help_text(CONTEXT_HELP['COMPLIANCE_OUTPUT'])

        self.btn_load_compliance.bind('<Enter>', _show_compliance_help)
        self.btn_load_compliance.bind('<Leave>', lambda e=None: self.set_page_help_text(self.default_help_text))

        ttk.Separator(label_frm_tenancy_config, orient=tk.VERTICAL).grid(row=0, column=6, rowspan=5, pady=5, sticky='w')

        # Progress indicator - move to its own row below buttons, at right
        self.progress_var = tk.StringVar(value='')
        self.progress_label = ttk.Label(label_frm_tenancy_config, textvariable=self.progress_var, foreground='blue')
        self.progress_label.grid(row=1, column=6, padx=5, pady=(1, 5), sticky='w')

        # --- Additional Identity Domain Compartment OCIDs UI (REMOVED) ---
        # All widgets and logic for manual compartment OCID entry have been removed.
        # Instead, a dropdown for compartment search depth will be added in a following step.

        # --- Recommendation / Consolidation (LabelFrame) ---
        label_frm_rec_cons = ttk.Labelframe(self, text='Recommendation / Consolidation')
        label_frm_rec_cons.pack(fill='x', padx=10, pady=10)

        def _show_rec_cons_help(_event=None):
            self.set_page_help_text(CONTEXT_HELP['RECOMMENDATION_CONSOLIDATION'])

        label_frm_rec_cons.bind('<Enter>', _show_rec_cons_help)
        label_frm_rec_cons.bind('<Leave>', lambda e=None: self.set_page_help_text(self.default_help_text))

        # Intelligence strategies: get list from engine (risk, overlap, cleanup, consolidation, recommendations)
        strategy_list = []
        if hasattr(self.app, 'policy_intelligence') and self.app.policy_intelligence:
            strategy_list = getattr(self.app.policy_intelligence, 'get_strategies_for_settings', lambda: [])()
        saved_ids = self.settings.get('enabled_intelligence_checks', None)
        # None or [] means all enabled; otherwise only those in the list are enabled
        all_enabled = saved_ids is None or (
            isinstance(saved_ids, list) and (len(saved_ids) == 0 or len(saved_ids) >= len(strategy_list))
        )
        self.enabled_intelligence_check_vars = {}
        for sid, _display_name, _category in strategy_list:
            self.enabled_intelligence_check_vars[sid] = tk.BooleanVar(
                value=all_enabled or (isinstance(saved_ids, list) and sid in saved_ids)
            )

        def _on_intelligence_check_toggled():
            enabled = [sid for sid, var in self.enabled_intelligence_check_vars.items() if var.get()]
            self.settings['enabled_intelligence_checks'] = (
                enabled if len(enabled) < len(self.enabled_intelligence_check_vars) else []
            )
            config.save_settings(self.settings)
            if hasattr(self.app, 'policy_recommendations_tab') and hasattr(
                self.app.policy_recommendations_tab, 'on_enabled_cleanup_checks_changed'
            ):
                self.app.policy_recommendations_tab.on_enabled_cleanup_checks_changed()

        checks_inner = ttk.Frame(label_frm_rec_cons)
        checks_inner.pack(fill='x', padx=8, pady=6)
        self.add_context_help(checks_inner, CONTEXT_HELP['RECOMMENDATION_CONSOLIDATION'])
        for sid, display_name, _category in strategy_list:
            if sid not in self.enabled_intelligence_check_vars:
                continue
            cb = ttk.Checkbutton(
                checks_inner,
                text=display_name,
                variable=self.enabled_intelligence_check_vars[sid],
                command=_on_intelligence_check_toggled,
            )
            cb.pack(side='left', padx=(0, 16), pady=4)

        # Label Frame for AI Connection
        self.label_frm_ai_config = ttk.Labelframe(self, text='OCI GenAI')
        self.label_frm_ai_config.pack(fill='x', padx=5, pady=5)

        # --- Page Help context for OCI GenAI ---
        def _show_genai_help(_event=None):
            self.set_page_help_text(CONTEXT_HELP['OCI_GENAI'])

        self.label_frm_ai_config.bind('<Enter>', _show_genai_help)
        self.label_frm_ai_config.bind('<Leave>', lambda e=None: self.set_page_help_text(self.default_help_text))

        # AI Toggle
        self.ai_toggle_btn = ttk.Button(
            self.label_frm_ai_config, state=tk.DISABLED, text='(3) Toggle AI Pane', command=self.app.toggle_bottom
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
            self.label_frm_ai_config, text='(1) Refresh Models (using selected profile)', command=populate_model_tree
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
            self.label_frm_ai_config, text='(2) Apply and Test GenAI Settings', command=self.apply_config
        )
        apply_button.grid(row=2, column=2, rowspan=3, padx=3, pady=3, sticky='ew')
        logger.debug('Apply button created')

        # (Moved MCP block to top and made autosave; original section removed)

    # -------------------------
    # Context Help Handlers
    # -------------------------
    def _on_context_help_changed(self):
        """
        Callback when Context Help checkbox is toggled.
        Notifies main.py to globally propagate the update to all tabs using App.refresh_all_tabs_settings.
        """
        self.settings['context_help'] = self.context_help_var.get()
        config.save_settings(self.settings)
        logger.info(f'Context Help setting changed to: {self.context_help_var.get()}')
        if hasattr(self.app, 'refresh_all_tabs_settings'):
            self.app.refresh_all_tabs_settings()

    def refresh_context_help(self):
        """Refresh style/visibility of Page Help label. (SettingsTab extension point)"""
        BaseUITab.refresh_context_help(self)  # type: ignore

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

    # def _refresh_domain_compartment_ocids_from_settings(self):
    #     """REMOVED: No longer tracking OCID list per tenancy (now using compartment depth)."""
    #     pass

    def _on_load_clicked(self, use_cache: bool):
        """Handle Load Tenancy button click.  Calls main app to load tenancy asynchronously.
        Args:
            use_cache (bool): Whether to load from cache or live tenancy.
        """
        tenancy_ocid = (self.tenancy_var.get() or '').strip()
        # If tenancy_var is empty, try to look it up from the OCI config for the current profile
        if not tenancy_ocid:
            profile = (self.profile_var.get() or '').strip() or 'DEFAULT'
            config_path = os.path.expanduser('~/.oci/config')
            try:
                with open(config_path) as fp:
                    cur_profile = None
                    cur_tenancy = None
                    for line in fp:
                        line = line.strip()
                        if line.startswith('[') and line.endswith(']'):
                            cur_profile = line[1:-1].strip()
                        elif '=' in line and cur_profile == profile:
                            key, val = line.split('=', 1)
                            key = key.strip().lower()
                            val = val.strip()
                            if key == 'tenancy':
                                cur_tenancy = val
                        if cur_profile == profile and cur_tenancy:
                            tenancy_ocid = cur_tenancy
                            break
            except Exception as e:
                logger.warning(f'Failed to load OCI tenancy from config: {e}')
            if tenancy_ocid:
                self.tenancy_var.set(tenancy_ocid)
                logger.info(f"Auto-populated tenancy_ocid for profile '{profile}': {tenancy_ocid}")
            else:
                logger.warning(f"Could not find tenancy OCID for profile '{profile}'")
        self.settings['tenancy_ocid'] = tenancy_ocid

        self.settings['recursive'] = self.recursive_var.get()
        self.settings['instance_principal'] = self.ip_var.get()
        self.settings['named_profile'] = self.profile_var.get()
        self.settings['ai_compartment_ocid'] = self.profile_var.get()
        self.settings['load_all_users'] = self.load_all_users_var.get()
        # Remove persistence, save, and variable harvesting for Additional Identity Domain Compartment OCIDs.
        # (Entire block deleted.)
        # Save compartment depth for tenancy being loaded (guarantee up-to-date)
        tenancy = (self.tenancy_var.get() or '').strip()
        if tenancy:
            by_tenancy = self.settings.get('domain_compartment_depth_by_tenancy', {})
            by_tenancy[tenancy] = self.compartment_depth_var.get()
            self.settings['domain_compartment_depth_by_tenancy'] = by_tenancy
            config.save_settings(self.settings)
        self.app.load_tenancy_async(
            tenancy_id=tenancy_ocid,
            recursive=self.recursive_var.get(),
            instance_principal=self.ip_var.get(),
            named_profile=self.profile_var.get() if not use_cache else None,
            named_session=self.session_token_var.get() if self.session_token_var.get() != '' else None,
            named_cache=self.display_to_cache_key.get(self.cache_var.get(), None) if use_cache else None,
            load_all_users=self.load_all_users_var.get(),
            # Pass depth configuration for downstream domain search logic
            compartment_domain_search_depth=self.compartment_depth_var.get(),
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
            self.after(1000, lambda: self.progress_var.set(''))

    def _on_load_finished(self, success: bool, message: str, clear: bool = False):  # noqa: C901
        """Callback from App once tenancy loading completes."""
        if success:
            # Format "data as of" date to "YYYY-Mon-DD hh:mi:ssZ"; show reload (if present)
            data_repo = getattr(self.app, 'policy_compartment_analysis', None)
            date_note = ''
            if data_repo is not None:
                data_as_of = getattr(data_repo, 'data_as_of', None)
                policy_reload = getattr(data_repo, 'policy_data_reloaded', None)
                import datetime

                date_str = ''
                reload_str = ''
                if data_as_of:
                    try:
                        dt = datetime.datetime.fromisoformat(data_as_of.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%b-%d %H:%M:%SZ')
                    except Exception:
                        date_str = str(data_as_of)
                if policy_reload:
                    try:
                        dt2 = datetime.datetime.fromisoformat(policy_reload.replace('Z', '+00:00'))
                        reload_str = dt2.strftime('%Y-%b-%d %H:%M:%SZ')
                    except Exception:
                        reload_str = str(policy_reload)
                if date_str and reload_str:
                    date_note = f'Data as of: {date_str}\nPolicy data reloaded: {reload_str}'
                elif date_str:
                    date_note = f'Data as of: {date_str}'
                elif reload_str:
                    date_note = f'Policy data reloaded: {reload_str}'
            self.progress_var.set(f'[OK]{message}')
            self.after(2000, lambda date_note=date_note: self.progress_var.set(date_note))
            # logger.info('Updating UI after load')
            # self.app.policies_tab.update_policy_output()
            # self.app.policies_tab.enable_widgets_after_load()
            # self.app.users_tab.update_user_analysis_output()
        else:
            self.progress_var.set(f'[X]{message}')

        # Schedule it to go away if clear was set
        if clear:
            self.after(5000, lambda: self.progress_var.set(''))

        # After loading, update the cache list in case new one was created
        logger.info('Updating cache list after load')
        self.refresh_cache_list()

    def refresh_cache_list(self):
        """Update the cache list OptionMenu in the Settings tab to reflect the current state, preserving selection."""
        # Save the currently selected value (user's selection)
        previous_selection = self.cache_var.get()

        self.cache_list = self.caching.get_available_cache(None)
        preserved_caches = self.caching.get_preserved_cache_set()
        self.cache_list_display = [f'(P) {name}' if name in preserved_caches else name for name in self.cache_list]
        self.display_to_cache_key = {
            f'(P) {name}' if name in preserved_caches else name: name for name in self.cache_list
        }
        menu = self.cache_list_dropdown['menu']
        menu.delete(0, 'end')
        for display_name in self.cache_list_display:
            menu.add_command(label=display_name, command=lambda value=display_name: self.cache_var.set(value))
        # Restore previous selection if it's still in the new list, otherwise fallback to first item
        if previous_selection in self.cache_list_display:
            self.cache_var.set(previous_selection)
        elif self.cache_list_display:
            self.cache_var.set(self.cache_list_display[0])
        else:
            self.cache_var.set('No Cache Available')

    def _on_load_all_users_changed(self):
        """Callback when Load All Users checkbox is toggled; saves to settings."""
        self.settings['load_all_users'] = self.load_all_users_var.get()
        config.save_settings(self.settings)
        # Optionally: Trigger UI hide/show of user info on tabs if implemented
        if hasattr(self.app, 'users_tab') and hasattr(self.app.users_tab, 'on_load_all_users_setting_changed'):
            self.app.users_tab.on_load_all_users_setting_changed(self.load_all_users_var.get())
        if hasattr(self.app, 'simulation_tab') and hasattr(
            self.app.simulation_tab, 'on_load_all_users_setting_changed'
        ):
            self.app.simulation_tab.on_load_all_users_setting_changed(self.load_all_users_var.get())

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
        self.ai_progress_var.set('[-] Running AI test call…')

        try:
            self.ai_repo.update_config(model_ocid=model_id, endpoint=endpoint, compartment_ocid=compartment_ocid)
            logger.info(f'Configuration updated successfully in {time.perf_counter() - start_time:.2f} seconds')

            # Make AI Call to test with callback
            self.app.ask_genai_async(
                prompt='What is the meaning of life?',
                additional_instruction='TEST',
                callback=self._on_ai_enablement_finished,
                test_call=True,  # Flag to indicate this is just a test call for enablement purposes
            )

        except Exception as e:
            logger.error('Failed to update configuration: %s', e)

    def _on_ai_enablement_finished(self, success: bool, message: str, clear: bool = False):  # noqa: C901
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
            # Enable AI Assist button on PoliciesTab after AI enablement success
            if hasattr(self.app, 'policies_tab') and hasattr(self.app.policies_tab, 'ai_assist_btn'):
                self.app.policies_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on PoliciesTab enabled')
            # Enable AI Assist button on PolicyBrowserTab after AI enablement success
            if hasattr(self.app, 'policy_browser_tab') and hasattr(self.app.policy_browser_tab, 'ai_assist_btn'):
                self.app.policy_browser_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on PolicyBrowserTab enabled')
            # Enable AI Assist button on DynamicGroupTab after AI enablement success
            if hasattr(self.app, 'dynamic_groups_tab') and hasattr(self.app.dynamic_groups_tab, 'ai_assist_btn'):
                self.app.dynamic_groups_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on DynamicGroupsTab enabled')
            # Enable UsersTab (and other tabs in the future) to show the AI Assist button
            if hasattr(self.app, 'users_tab') and hasattr(self.app.users_tab, 'ai_assist_btn'):
                self.app.users_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on UsersTab enabled')
            # Enable ResourcePrincipalsTab (and other tabs in the future) to show the AI Assist button
            if hasattr(self.app, 'resource_principals_tab') and hasattr(
                self.app.resource_principals_tab, 'ai_assist_btn'
            ):
                self.app.resource_principals_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on ResourcePrincipalsTab enabled')
            # Clear previous AI Assistant search and results after enablement
            if hasattr(self.app, 'policy_query_var'):
                self.app.policy_query_var.set('')
            # if hasattr(self.app, "policy_query_label_text"):
            #     self.app.policy_query_label_text.set('')
            self.app.output_text.delete('1.0', tk.END)
            # Common for result/response variable: ai_output_var or genai_response_var or similar
            if hasattr(self.app, 'ai_output_var'):
                self.app.ai_output_var.set('')
            if hasattr(self.app, 'genai_response_var'):
                self.app.genai_response_var.set('')
        else:
            self.ai_progress_var.set(f'[X] {message}')

        # Schedule it to go away if clear was set
        if clear:
            self.after(2000, lambda: self.ai_progress_var.set(''))

    # -------------------------
    # Console/ Debug Tab Toggle
    # -------------------------

    def _toggle_console_tab(self):
        """Toggle the visibility of the console and debug tab in the notebook."""
        notebook = self.app.notebook
        console_tab = self.app.console_tab
        debugger_tab = getattr(self.app, 'debugger_tab', None)

        if self.app.console_visible:
            notebook.forget(console_tab)
            if debugger_tab:
                notebook.forget(debugger_tab)
            self.console_btn_var.set('Show Console and Debug Tab')
            self.app.console_visible = False
            logger.info('Console and Debug tabs hidden')
        else:
            notebook.add(console_tab, text='Console Logging\n(Internal)')
            if debugger_tab:
                notebook.add(debugger_tab, text='JSON Debugger\n(Internal)')
            self.console_btn_var.set('Hide Console and Debug Tab')
            self.app.console_visible = True
            logger.info('Console and Debug tabs shown')

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
            notebook.add(maintenance_tab, text='Maintenance\n(Internal)')
            self.maintenance_btn_var.set('Hide Maintenance Tab')
            self.app.maintenance_visible = True
            logger.info('Maintenance tab shown')

    # -------------------------
    # Advanced Tabs Toggle
    # -------------------------

    def _toggle_advanced_tabs(self):
        """Toggle the visibility of the advanced tabs in the notebook."""
        notebook = self.app.notebook
        advanced_tabs = [
            self.app.permissions_report_tab,
            self.app.condition_tester_tab,
            self.app.simulation_tab,
            self.app.policy_recommendations_tab,
        ]

        if self.app.advanced_tabs_visible:
            for tab in advanced_tabs:
                notebook.forget(tab)
            self.advanced_btn_var.set('Show Advanced Tabs')
            self.app.advanced_tabs_visible = False
            logger.info('Advanced tabs hidden')
        else:
            notebook.add(self.app.permissions_report_tab, text='Permissions Report\n(Advanced)')
            notebook.add(self.app.condition_tester_tab, text='Condition Tester\n(Advanced)')
            notebook.add(self.app.simulation_tab, text='API Simulation\n(Advanced)')
            notebook.add(self.app.policy_recommendations_tab, text='Policy Recommendations\n(Preview)')
            # REMOVED: consolidation_tab from advanced tabs (consolidation feature disabled)
            self.advanced_btn_var.set('Hide Advanced Tabs')
            self.app.advanced_tabs_visible = True
            logger.info('Advanced tabs shown')
