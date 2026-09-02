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
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from oci_policy_analysis.application.core.repo import AI
from oci_policy_analysis.application.core.repo.ai_repo import load_inference_model_overrides, load_tested_model_ids
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab
from oci_policy_analysis.presentation.desktop.data_table import DataTable

# Constants for data table
AI_MODEL_COLUMNS = ['Model Name', 'Model OCID', 'Capabilities', 'Lifecycle State', 'Creation Date', 'Tested']
AI_MODEL_COLUMN_WIDTHS = {
    'Model Name': 250,
    'Model OCID': 450,
    'Capabilities': 200,
    'Lifecycle State': 125,
    'Creation Date': 250,
    'Tested': 90,
}

# Context help messages for the SettingsTab
CONTEXT_HELP = {
    'DISPLAY_OPTIONS': 'Adjust general UI settings such as font size, context help, console/maintenance/advanced tabs, and optional anonymous usage tracking.',
    'MCP_CONFIG': 'Configure the built-in MCP server for advanced automation and API analysis integration.',
    'TENANCY_CONFIG': (
        'Set your OCI tenancy and authentication method. Choose between instance principal, named profile, or session token. '
        'Load data either directly from OCI or from a cached JSON, manage policy data, and import/export backups. '
        'Use these controls to initialize or refresh the core analysis dataset.'
    ),
    'INSTANCE_PRINCIPAL': (
        'Use only on OCI instances configured in a dynamic group with permissions; profile selection is disabled and not used when enabled. Use of Instance Principal supersedes Profile selection, but recursion and compartment depth are supported.'
    ),
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
        'Control which intelligence strategies run (risk, complete supersession, cleanup checks, consolidation suggestions, recommendations). '
        'Uncheck to skip. Preferences are saved globally and used by the Recommendations tab.'
    ),
    'RISK_REDUCTION_SETTINGS': (
        'Set default risk scoring reductions used during intelligence calculations. '
        'These are persisted settings shared by desktop and web flows.'
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
            default_help_text='Manage core settings for the OCI Policy Analysis tool, including tenancy authentication, caching, MCP server configuration, and general UI preferences.',
            page_help_link='/usage.html#settings-tab-start-here',
        )
        self.app = app
        self.settings = settings
        self.ai_repo = ai_repo
        # Test status is intentionally session-local; the model matrix documents
        # repeatable results across environments and dates.
        self.ai_test_results: dict[str, str] = {}
        self.tested_model_ids = load_tested_model_ids()
        self.inference_model_overrides = load_inference_model_overrides()
        self.show_only_tested_var = tk.BooleanVar(value=True)
        self._all_ai_models: list[dict] = []
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
        self.ai_compartment_var = tk.StringVar(value=self.settings.get('ai_compartment_ocid', ''))
        self.format_var = tk.StringVar(value=self.settings.get('result_format', 'Markdown'))
        self.mcp_port_var = tk.StringVar(value=str(self.settings.get('mcp_port', '8765')))
        self.mcp_host_var = tk.StringVar(value=self.settings.get('mcp_host', '127.0.0.1'))
        allowed_pct = {0, 25, 50, 75, 90}
        where_pct = int(self.settings.get('risk_where_clause_reduction_pct', 50) or 50)
        service_pct = int(self.settings.get('risk_service_principal_reduction_pct', 50) or 50)
        self.risk_where_reduction_var = tk.StringVar(value=f'{where_pct if where_pct in allowed_pct else 50}%')
        self.risk_service_reduction_var = tk.StringVar(value=f'{service_pct if service_pct in allowed_pct else 50}%')

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

        # One-time inline banner at the very top of the Settings tab, above the
        # normal Context Help area, instead of a separate messagebox. This
        # avoids z-order/focus issues on macOS while still being prominent.
        if not bool(self.settings.get('intro_unofficial_tracking_shown', False)):
            self._create_intro_banner()

    # ----- Page Help (Context Help) helpers -----
    # (Now inherited from BaseUITab. Any customizations can override as needed.)

    def _create_intro_banner(self) -> None:
        """Create a dismissible intro banner above the Context Help area.

        This avoids OS focus issues with message boxes while still clearly
        communicating that the tool is unofficial and that anonymous usage
        tracking is enabled by default and controllable from this tab.
        """

        # Outer frame pinned at the very top of this tab, before any other
        # content (including the normal Context Help area from BaseUITab).
        banner = ttk.Frame(self, style='IntroBanner.TFrame')
        # Insert before existing children (Context Help frame is already packed)
        try:
            first_child = self.winfo_children()[0] if self.winfo_children() else None
        except Exception:
            first_child = None

        if first_child is not None:
            banner.pack(fill='x', padx=10, pady=(10, 0), before=first_child)
        else:
            banner.pack(fill='x', padx=10, pady=(10, 0))

        # Left: explanatory text
        intro_banner_text = (
            'This is an UNOFFICIAL desktop helper tool that uses the official OCI Python SDK '
            'to analyze and explore IAM policies. Anonymous Usage Tracking is enabled '
            'by default and is controlled from the "Anonymous Usage Tracking" '
            'checkbox below. It only sends anonymous, non-personal usage data (for example: which '
            'tabs are opened and high-level counts of loaded data). No policy text, usernames, '
            'email addresses, or resource OCIDs are ever sent.'
        )

        label = ttk.Label(banner, text=intro_banner_text, wraplength=1300, justify='left')
        label.pack(side='left', fill='x', expand=True, padx=(4, 8), pady=4)

        # Right: Dismiss button that hides the banner and persists the flag
        def _dismiss() -> None:
            try:
                self.settings['intro_unofficial_tracking_shown'] = True
                self.app.settings_service.save()
            except Exception:
                logger.debug('Failed to persist intro_unofficial_tracking_shown flag', exc_info=True)
            try:
                banner.destroy()
            except Exception:
                pass

        btn = ttk.Button(banner, text='Dismiss', command=_dismiss)
        btn.pack(side='right', padx=(0, 8), pady=4)

        # Optionally tweak style to make it visually distinct but not jarring
        try:
            style = ttk.Style()
            style.configure('IntroBanner.TFrame', background='#FFF4CC')
            label.configure(background='#FFF4CC')
        except Exception:
            pass

    def _build_ui(self):  # noqa: C901
        # ---- Top Row: Settings + MCP ----
        top_row = ttk.Frame(self)
        top_row.pack(fill='x', padx=10, pady=10)

        # General settings (LabelFrame, LEFT)
        disp = ttk.LabelFrame(top_row, text='Settings')
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

        # --- Anonymous Usage Tracking Checkbox ---
        self.usage_tracking_var = tk.BooleanVar(value=self.settings.get('usage_tracking_enabled', False))
        usage_checkbox = ttk.Checkbutton(
            disp,
            text='Anonymous Usage Tracking',
            variable=self.usage_tracking_var,
            command=self._on_usage_tracking_changed,
        )
        usage_checkbox.pack(side='left', padx=10, pady=6)
        self.add_context_help(
            usage_checkbox,
            'When enabled, the tool sends anonymous, non-personal usage data (for example: which tabs are opened and high-level counts of loaded data) to a write-only OCI Object Storage bucket controlled by the tool author. No policy text, usernames, email addresses, or resource OCIDs are ever sent. You can turn this on or off at any time.',
        )

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
            self.app.settings_service.save()
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

        def _update_load_tenancy_state(*_args):
            has_profile = bool((self.profile_var.get() or '').strip())
            if self.ip_var.get() or has_profile:
                self.load_tenancy_button.config(state='normal')
            else:
                self.load_tenancy_button.config(state='disabled')

        def _on_instance_principal_changed(*_):
            """
            When Instance Principal is checked, disable (grey out) the profile selector.
            When unchecked, enable profile selection.
            """
            if self.ip_var.get():
                self.input_profile.config(state='disabled')
            else:
                self.input_profile.config(state='normal' if len(self.profile_list) > 0 else 'disabled')
            _update_load_tenancy_state()

        # Trace the variable to update OptionMenu state whenever Instance Principal toggled
        self.ip_var.trace_add('write', _on_instance_principal_changed)

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
        # Load the global compartment depth from settings
        global_depth = self.settings.get('domain_compartment_depth', 1)
        self.compartment_depth_var = tk.IntVar(value=global_depth)
        depth_val_strings = [label for label, val in COMPARTMENT_DEPTH_CHOICES]
        self.depth_value_map = dict(COMPARTMENT_DEPTH_CHOICES)
        self.depth_string_map = {val: label for label, val in COMPARTMENT_DEPTH_CHOICES}
        self.compartment_depth_dropdown = ttk.Combobox(
            label_frm_tenancy_config, state='readonly', width=16, values=depth_val_strings
        )
        self.compartment_depth_dropdown.grid(row=3, column=2, padx=5, pady=(10, 2), sticky='w')

        # Add Setup Guide link next to compartment depth selector
        setup_doc_url = self.DOCROOT + '/setup.html'
        setup_guide_link = self.create_doc_link_label(
            label_frm_tenancy_config,
            text='Tenancy Setup Guide',
            url=setup_doc_url,
            row=3,
            column=3,
            padx=3,
            pady=3,
            sticky='w',
        )
        self.add_context_help(
            setup_guide_link,
            'Open the full OCI Policy Analysis setup instructions (docs/source/setup.md) in your web browser.',
        )

        # CIS Compliance Guide link - https://github.com/oci-landing-zones/oci-cis-landingzone-quickstart/blob/main/README.md#cis-compliance-script
        cis_doc_url = 'https://github.com/oci-landing-zones/oci-cis-landingzone-quickstart/blob/main/README.md#cis-compliance-script'
        cis_guide_link = self.create_doc_link_label(
            label_frm_tenancy_config,
            text='CIS Compliance Output Setup',
            url=cis_doc_url,
            row=3,
            column=5,
            padx=3,
            pady=3,
            sticky='w',
        )
        self.add_context_help(
            cis_guide_link,
            'How to get CIS Compliance Output data for use with the "Load from Compliance Output Data" button on this page. Instructions are in the linked documentation. Point to the output directory after running script with --raw option.',
        )

        def on_depth_select(event):
            selected_label = self.compartment_depth_dropdown.get()
            selected_val = self.depth_value_map.get(selected_label, 1)
            # Save globally in settings (not per-tenancy)
            self.settings['domain_compartment_depth'] = selected_val
            self.app.settings_service.save()
            self.compartment_depth_var.set(selected_val)

        # Bind update logic on dropdown selection
        self.compartment_depth_dropdown.bind('<<ComboboxSelected>>', on_depth_select)
        # Set initial value from global config
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
        # Compartment depth now global-only; any trace/dependency on tenancy_var for depth is removed.
        self.input_profile.config(width=28, state='normal' if len(self.profile_list) > 0 else 'disabled')
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)
        # Call once to set initial state
        if self.ip_var.get():
            self.input_profile.config(state='disabled')

        # Get available cached copies
        self.label_cache = ttk.Label(label_frm_tenancy_config, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.add_context_help(self.label_cache, CONTEXT_HELP['CACHE_LABEL'])
        self.cache_list = self.app.cache_service.list_caches(None)
        # Use preserved_caches set from CacheManager for cache list display
        preserved_caches = self.app.cache_service.get_preserved_cache_set()
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
        self.cache_list_dropdown.config(width=28)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)
        self.add_context_help(self.cache_list_dropdown, CONTEXT_HELP['CACHE_DROPDOWN'])

        # Load button (lambda function with boolean for cache)
        self.load_tenancy_button = ttk.Button(
            label_frm_tenancy_config,
            width=25,
            text='Load from Tenancy',
            command=lambda: self._on_load_clicked(use_cache=False),
        )
        self.load_tenancy_button.grid(row=0, column=3, padx=5, pady=5, sticky='w')
        ttk.Button(
            label_frm_tenancy_config,
            width=25,
            text='Load from Cache',
            command=lambda: self._on_load_clicked(use_cache=True),
        ).grid(row=1, column=3, padx=5, pady=5, sticky='w')

        # Session Token (with link)
        session_doc_url = 'https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clitoken.htm'
        session_auth_link_label = self.create_doc_link_label(
            label_frm_tenancy_config,
            text='Session Token (oci session authenticate)',
            url=session_doc_url,
            row=2,
            column=0,
            columnspan=2,
            padx=5,
            pady=3,
            sticky='w',
        )
        self.add_context_help(
            session_auth_link_label,
            CONTEXT_HELP['SESSION_TOKEN'],
        )
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
            command=lambda: self.app._import_cache_from_json(
                callback={
                    'complete': self._on_load_finished,
                    'error': self._on_load_finished,
                },
                show_popup=True,
            ),
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
            # Call the app method (must exist/app-supports), use same callbacks as tenancy load
            self.app.load_compliance_output_async(
                folder_selected,
                callback={
                    'complete': self._on_load_finished,
                    'error': self._on_load_finished,
                },
                load_all_users=self.load_all_users_var.get(),
                show_popup=True,
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

        # Intelligence strategies: get list from engine (risk, supersession, cleanup, consolidation, recommendations)
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
            self.app.settings_service.save()
            if hasattr(self.app, 'policy_recommendations_tab') and hasattr(
                self.app.policy_recommendations_tab, 'on_enabled_cleanup_checks_changed'
            ):
                self.app.policy_recommendations_tab.on_enabled_cleanup_checks_changed()

        checks_inner = ttk.Frame(label_frm_rec_cons)
        checks_inner.pack(fill='x', padx=8, pady=6)
        self.add_context_help(checks_inner, CONTEXT_HELP['RECOMMENDATION_CONSOLIDATION'])

        risk_defaults_row = ttk.Frame(label_frm_rec_cons)
        risk_defaults_row.pack(fill='x', padx=8, pady=(0, 4))
        self.add_context_help(risk_defaults_row, CONTEXT_HELP['RISK_REDUCTION_SETTINGS'])
        ttk.Label(risk_defaults_row, text='Risk defaults: WHERE reduction').pack(side='left', padx=(0, 4))
        risk_options = ['0%', '25%', '50%', '75%', '90%']
        risk_where_combo = ttk.Combobox(
            risk_defaults_row,
            textvariable=self.risk_where_reduction_var,
            state='readonly',
            values=risk_options,
            width=7,
        )
        risk_where_combo.pack(side='left', padx=(0, 12))
        ttk.Label(risk_defaults_row, text='Service principal reduction').pack(side='left', padx=(0, 4))
        risk_service_combo = ttk.Combobox(
            risk_defaults_row,
            textvariable=self.risk_service_reduction_var,
            state='readonly',
            values=risk_options,
            width=7,
        )
        risk_service_combo.pack(side='left', padx=(0, 12))

        def _save_risk_reduction_defaults(*_args):
            try:
                self.settings['risk_where_clause_reduction_pct'] = int(
                    str(self.risk_where_reduction_var.get() or '50').replace('%', '')
                )
                self.settings['risk_service_principal_reduction_pct'] = int(
                    str(self.risk_service_reduction_var.get() or '50').replace('%', '')
                )
            except ValueError:
                return
            self.app.settings_service.save()

        risk_where_combo.bind('<<ComboboxSelected>>', _save_risk_reduction_defaults)
        risk_service_combo.bind('<<ComboboxSelected>>', _save_risk_reduction_defaults)

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

        if not self.is_genai_feature_enabled():
            logger.debug('OCI GenAI settings are hidden because the preview feature is disabled.')
            return

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
        self.ai_toggle_btn.grid(row=0, column=0, padx=3, pady=3, sticky='w')

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
                self._all_ai_models = ai_models
                for model in ai_models:
                    model['Tested'] = self.ai_test_results.get(
                        model.get('Model OCID', ''),
                        'Yes' if model.get('Model OCID', '') in self.tested_model_ids else 'No',
                    )
                self._refresh_model_table()
                logger.info(f'list_models returned {len(ai_models)} models')

                # Put in Model Data Table
            else:
                logger.warning('AI client not initialized, cannot list models')

        self.region_var = tk.StringVar(value='')
        self.load_regions_button = ttk.Button(
            self.label_frm_ai_config, text='Load Regions', command=self._load_subscribed_regions
        )
        self.load_regions_button.grid(row=0, column=1, padx=3, pady=3, sticky='w')
        ttk.Label(self.label_frm_ai_config, text='Region:').grid(row=0, column=2, padx=(10, 2), pady=3, sticky='e')
        self.region_combo = ttk.Combobox(
            self.label_frm_ai_config, textvariable=self.region_var, state='readonly', width=18
        )
        self.region_combo.grid(row=0, column=3, padx=3, pady=3, sticky='w')
        self.region_combo.bind('<<ComboboxSelected>>', self._on_ai_region_changed)

        self.refresh_button = ttk.Button(
            self.label_frm_ai_config, text='(1) Refresh Models (using selected profile)', command=populate_model_tree
        )
        self.refresh_button.grid(row=0, column=4, padx=3, pady=3, sticky='w')

        ttk.Checkbutton(
            self.label_frm_ai_config,
            text='Show Only Tested Models',
            variable=self.show_only_tested_var,
            command=self._refresh_model_table,
        ).grid(row=0, column=5, padx=12, pady=3, sticky='w')

        self.ai_progress_var = tk.StringVar(value='')
        self.ai_progress_label = ttk.Label(
            self.label_frm_ai_config, textvariable=self.ai_progress_var, foreground='blue'
        )
        self.ai_progress_label.grid(row=0, column=6, columnspan=2, padx=3, pady=3, sticky='we')

        def update_model_ocid(selected_items):
            if selected_items:
                model_ocid = selected_items[0].get('Model OCID', '')
                inference_model_id = self.inference_model_overrides.get(model_ocid, model_ocid)
                self.model_id_var.set(inference_model_id)
                logger.info('Selected model OCID=%s; inference model ID=%s', model_ocid, inference_model_id)

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
        self.ai_model_table.grid(row=1, column=0, columnspan=8, padx=3, pady=3, sticky='nsew')

        self.create_doc_link_label(
            self.label_frm_ai_config,
            'Open AI model test matrix and troubleshooting notes',
            self.DOCROOT + '/ai_model_testing.html',
            row=2,
            column=0,
            columnspan=8,
            padx=3,
            pady=3,
            sticky='w',
        )

        self.model_id_var = tk.StringVar()

        ttk.Label(self.label_frm_ai_config, text='Regional Endpoint:').grid(row=3, column=0, padx=2, pady=3, sticky='w')
        self.endpoint_var = tk.StringVar()
        self.endpoint_entry = ttk.Entry(self.label_frm_ai_config, textvariable=self.endpoint_var, width=80)
        self.endpoint_entry.grid(row=3, column=1, columnspan=6, padx=3, pady=3, sticky='ew')

        ttk.Label(self.label_frm_ai_config, text='Compartment (for GenAI):').grid(
            row=4, column=0, padx=2, pady=3, sticky='w'
        )
        self.ai_compartment_var = tk.StringVar()
        self.ai_compartment_entry = ttk.Entry(self.label_frm_ai_config, textvariable=self.ai_compartment_var, width=80)
        self.ai_compartment_entry.grid(row=4, column=1, columnspan=6, padx=3, pady=3, sticky='ew')

        apply_button = ttk.Button(
            self.label_frm_ai_config, text='(2) Apply and Test GenAI Settings', command=self.apply_config
        )
        apply_button.grid(row=3, column=7, rowspan=2, padx=3, pady=3, sticky='ew')
        for column in range(1, 6):
            self.label_frm_ai_config.columnconfigure(column, weight=1)
        self.label_frm_ai_config.rowconfigure(1, weight=1)
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
        self.app.settings_service.save()
        logger.info(f'Context Help setting changed to: {self.context_help_var.get()}')
        if hasattr(self.app, 'refresh_all_tabs_settings'):
            self.app.refresh_all_tabs_settings()

    def _on_usage_tracking_changed(self):
        """Callback when Anonymous Usage Tracking checkbox is toggled."""
        self.settings['usage_tracking_enabled'] = self.usage_tracking_var.get()
        self.app.settings_service.save()
        logger.info('Anonymous usage tracking setting changed to: %s', self.usage_tracking_var.get())
        # Update status bar indicator immediately if available
        if hasattr(self.app, 'update_status_bar'):
            try:
                self.app.update_status_bar()
            except Exception:
                logger.debug('Failed to refresh status bar after usage tracking toggle', exc_info=True)

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
        self.app.settings_service.save()
        logger.info('MCP configuration saved to settings.')

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
        # Save compartment depth globally
        self.settings['domain_compartment_depth'] = self.compartment_depth_var.get()
        self.app.settings_service.save()
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
                'complete': self._on_load_finished,
                'error': self._on_load_finished,
            },
            show_popup=True,
        )

    def _on_load_finished(self, success: bool, message: str, clear: bool = False):  # noqa: C901
        """Callback from App once a load/import operation completes.

        Popup messaging is handled centrally in main.py. This callback now only
        performs post-load side effects needed by Settings UI.
        """
        logger.info('Load callback received: success=%s message=%s', success, message)
        logger.info('Updating cache list after load/import operation')
        self.refresh_cache_list()

    def refresh_cache_list(self):
        """Update the cache list OptionMenu in the Settings tab to reflect the current state, preserving selection."""
        # Save the currently selected value (user's selection)
        previous_selection = self.cache_var.get()

        self.cache_list = self.app.cache_service.list_caches(None)
        preserved_caches = self.app.cache_service.get_preserved_cache_set()
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
        self.app.settings_service.save()
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
    def _refresh_model_table(self) -> None:
        """Apply the model-list filters without making another OCI request."""
        if not self.is_genai_feature_enabled():
            return
        rows = []
        for model in self._all_ai_models:
            model_id = model.get('Model OCID', '')
            model['Tested'] = self.ai_test_results.get(model_id, 'Yes' if model_id in self.tested_model_ids else 'No')
            if self.show_only_tested_var.get() and model['Tested'] != 'Yes':
                continue
            rows.append(model)
        self.ai_model_table.update_data(new_data=rows)

    def _on_ai_region_changed(self, _event=None) -> None:
        """Switch GenAI clients to the selected subscribed region."""
        if not self.is_genai_feature_enabled():
            return
        region = self.region_var.get().strip()
        if not region or not self.ai_repo.initialized:
            return
        try:
            self.ai_repo.set_region(region)
            self.endpoint_var.set(self.ai_repo.base_endpoint)
            self._all_ai_models = []
            self.ai_model_table.update_data(new_data=[])
            self.ai_progress_var.set(f'Region set to {region}; refresh models to continue')
        except Exception as exc:
            logger.error('Failed to change AI region to %s', region, exc_info=True)
            self.ai_progress_var.set(f'Unable to change region: {exc}')

    def _load_subscribed_regions(self) -> None:
        """Load tenancy regions on explicit user request."""
        if not self.is_genai_feature_enabled():
            return
        try:
            if not self.ai_repo.initialized:
                self.ai_repo.initialize_client(use_instance_principal=self.ip_var.get(), profile=self.profile_var.get())
            if not self.ai_repo.initialized:
                raise RuntimeError('AI client could not be initialized')
            regions = self.ai_repo.list_subscribed_regions()
            self.region_combo['values'] = regions
            if self.ai_repo.region in regions:
                self.region_var.set(self.ai_repo.region)
            self.ai_progress_var.set(f'Loaded {len(regions)} subscribed regions')
        except Exception as exc:
            logger.error('Unable to load subscribed AI regions', exc_info=True)
            self.ai_progress_var.set(f'Unable to load subscribed regions: {exc}')

    def apply_config(self):
        """
        Apply changes to Model ID and Endpoint in AI client.
        """
        if not self.is_genai_feature_enabled():
            logger.warning('Ignoring GenAI configuration because the preview feature is disabled.')
            return
        start_time = time.perf_counter()
        model_id = self.model_id_var.get().strip()
        endpoint = self.endpoint_var.get().strip()
        compartment_ocid = self.ai_compartment_var.get().strip() or getattr(self.ai_repo, 'tenancy_ocid', '')
        if compartment_ocid:
            self.ai_compartment_var.set(compartment_ocid)
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
        if not self.is_genai_feature_enabled():
            return
        model_id = self.model_id_var.get().strip()
        if model_id:
            self.ai_test_results[model_id] = 'Yes' if success else 'No'
            for row in self.ai_model_table.data:
                if row.get('Model OCID') == model_id:
                    row['Tested'] = self.ai_test_results[model_id]
            self.ai_model_table.update_data(new_data=self.ai_model_table.data)

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
            # Enable WorkloadPrincipalsTab (and other tabs in the future) to show the AI Assist button
            if hasattr(self.app, 'resource_principals_tab') and hasattr(
                self.app.resource_principals_tab, 'ai_assist_btn'
            ):
                self.app.resource_principals_tab.ai_assist_btn.config(state=tk.NORMAL)
                logger.info('AI Assist button on WorkloadPrincipalsTab enabled')
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
            self.app.tag_based_access_tab,
            self.app.simulation_tab,
            self.app.mcp_tab,
        ]

        # Only treat consolidation tab as advanced if experimental features are enabled
        if getattr(self.app, 'consolidation_tab', None) is not None:
            advanced_tabs.append(self.app.consolidation_tab)

        if self.app.advanced_tabs_visible:
            for tab in advanced_tabs:
                notebook.forget(tab)
            self.advanced_btn_var.set('Show Advanced Tabs')
            self.app.advanced_tabs_visible = False
            logger.info('Advanced tabs hidden')
        else:
            notebook.add(self.app.mcp_tab, text='Embedded MCP\n(Advanced)')
            notebook.add(self.app.permissions_report_tab, text='Permissions Report\n(Advanced)')
            notebook.add(self.app.tag_based_access_tab, text='Tag-based Access\n(Advanced)')
            notebook.add(self.app.simulation_tab, text='API Simulation\n(Advanced)')
            # Only add consolidation tab if experimental features are enabled
            if getattr(self.app, 'consolidation_tab', None) is not None:
                notebook.add(self.app.consolidation_tab, text='Consolidation Workbench\n(Preview)')
            self.advanced_btn_var.set('Hide Advanced Tabs')
            self.app.advanced_tabs_visible = True
            logger.info('Advanced tabs shown')
