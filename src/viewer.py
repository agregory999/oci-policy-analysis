##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# viewer.py
#
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import argparse
import csv
import datetime
import json
import logging
import queue
import sys
import tkinter as tk
import tkinter.filedialog as tkfiledialog
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tkinter import font

# Third-party imports
from tkinter.font import Font

# from oci_policy_dg_viewer.formatting import format_dgrule
import markdown
import oci
import ttkbootstrap as ttk

# from _version import __version__
# from ai import AI  # AI functionality
# from core import (
#     IdentityDomainsAnalysis,  # Analysis of Identity Domains
#     PolicyCompartmentAnalysis,  # Analysis of Policy Compartments
#     get_available_cache,  # Get available cache files
#     load_cache_from_json,  # Load imported
#     load_cache_into_local_json,  # Loading of cache to a json
#     load_combined_cache,  # Load combined cache from file
#     save_combined_cache,  # Save combined cache to file
# )
# from data_table import DataTable
from deepdiff import DeepDiff
from tkhtmlview import HTMLText

from oci_policy_dg_viewer._version import __version__
from oci_policy_dg_viewer.ai import AI
from oci_policy_dg_viewer.core import (
    IdentityDomainsAnalysis,
    PolicyCompartmentAnalysis,
    get_available_cache,
    load_cache_from_json,
    load_cache_into_local_json,
    load_combined_cache,
    save_combined_cache,
)
from oci_policy_dg_viewer.data_table import DataTable
from oci_policy_dg_viewer.formatting import clean_markdown

# Constants
THREADS = 8

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'

# Column information and widths
AI_MODEL_COLUMNS = ['Model Name', 'Model OCID', 'Lifecycle State', 'Creation Date']
AI_MODEL_COLUMN_WIDTHS = {'Model Name': 250, 'Model OCID': 450, 'Lifecycle State': 125, 'Creation Date': 250}

GROUPS_COLUMNS = ['Domain Name', 'Group Name', 'Group OCID']
GROUPS_COLUMNS_WIDTHS = {'Domain Name': 150, 'Group Name': 300, 'Group OCID': 450}

USERS_COLUMNS = ['Domain Name', 'User Name', 'User OCID']
USERS_COLUMNS_WIDTHS = {'Domain Name': 150, 'User Name': 300, 'User OCID': 450}

AUDIT_COLUMNS = ['Policy OCID', 'Change Date', 'Change User', 'Before', 'After']
AUDIT_COLUMN_WIDTHS = {'Policy OCID': 250, 'Change Date': 100, 'Change User': 150, 'Before': 300, 'After': 300}

# Global variables
last_error = ''

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
logger = logging.getLogger('viewer-main')
# logger.warning(f'Version {__version__} of oci-policy-dg-viewer is running')


# Custom handler to redirect logging to Tkinter Text widget (thread-safe)
class TextHandler(logging.Handler):
    def __init__(self, text_widget, root):
        super().__init__()
        self.text_widget = text_widget
        self.root = root
        self.queue = Queue()
        self.text_widget.config(state='disabled')
        self.check_queue()

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)  # Queue message for main thread to process

    def check_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, msg + '\n')
                self.text_widget.see(tk.END)
                self.text_widget.config(state='disabled')
        except Empty:
            pass
        self.root.after(100, self.check_queue)  # Schedule next check


class OCIPolicyDGViewer:
    def __init__(self, root, verbose=False):
        self.root = root
        self.root.title('OCI Policy and Dynamic Group Viewer')

        # Verbose
        self.verbose = verbose
        self.log_level = tk.StringVar(value='INFO')
        # AI Queue
        self.result_queue = Queue()
        # Logger
        self.formatter = logging.Formatter('%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
        # Configure root logger to ensure all logging calls are captured
        # logger = logging.getLogger('viewer')  # Get root logger
        if self.verbose:
            logger.setLevel(logging.DEBUG)
            # logger.setLevel(logging.DEBUG)
            self.log_level.set('DEBUG')
        else:
            logger.setLevel(logging.INFO)
            # logger.setLevel(logging.INFO)

        # Load options quietly (defaults for all)
        self.load_options()

        # Status Bar Text
        self.status_bar_text = ''
        self.currently_loading = False

        # Font (size can be changed)
        # self.font = Font(family='Courier New', size=10, weight='normal')
        # self.bold_font = Font(family='Courier New', size=10, weight='bold')
        self.font = Font(family='TkFixedFont', size=10, weight='normal')
        self.bold_font = Font(family='TkFixedFont', size=10, weight='bold')

        # Display Tree Style
        self.style = ttk.Style()
        self.style.configure('Treeview', font=self.font, padding=(0, 0, 5, 0))
        self.style.configure('Treeview.Heading', font=self.bold_font, padding=(0, 0, 5, 0))

        # Queue for thread communication
        self.queue = Queue()

        # Initialize analysis classes
        self.policy_compartment_analysis = PolicyCompartmentAnalysis(verbose)  # Core
        self.identity_domain_analysis = IdentityDomainsAnalysis(verbose)  # Core
        self.ai = AI(verbose)  # AI functionality

        # Initialize Reference Data
        self.load_reference_data()

        # Column data for Custom Data Table
        self.all_policy_columns = [
            'Policy Name',
            'Policy OCID',
            'Compartment OCID',
            'Policy Compartment',
            'Statement Text',
            'Valid',
            'Subject Type',
            'Subject',
            'Verb',
            'Resource',
            'Permission',
            'Location Type',
            'Location',
            'Conditions',
            'Comments',
            'Creation Time',
            'Parsed',
        ]
        self.basic_policy_columns = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Valid']
        self.policy_column_widths = {
            'Policy Name': 250,
            'Policy OCID': 450,
            'Compartment OCID': 450,
            'Policy Compartment': 250,
            'Statement Text': 700,
            'Valid': 80,
            'Subject Type': 120,
            'Subject': 200,
            'Verb': 100,
            'Resource': 150,
            'Permission': 150,
            'Location Type': 120,
            'Location': 200,
            'Conditions': 200,
            'Comments': 200,
            'Creation Time': 150,
            'Parsed': 80,
        }
        self.basic_dg_columns = ['Domain', 'DG Name', 'Matching Rule', 'In Use']
        self.all_dg_columns = ['Domain', 'DG Name', 'DG OCID', 'Matching Rule', 'In Use', 'Creation Time']

        self.dg_column_widths = {
            'Domain': 150,
            'DG Name': 300,
            'DG OCID': 450,
            'Matching Rule': 700,
            'In Use': 80,
            'Creation Time': 150,
        }
        # Users and Groups
        self.all_groups_columns = ['Domain Name', 'Group Name', 'Group OCID']
        self.all_users_columns = ['Domain Name', 'User Name', 'User OCID']
        self.groups_column_widths = {'Domain Name': 150, 'Group Name': 300, 'Group OCID': 450}
        self.users_column_widths = {'Domain Name': 150, 'User Name': 300, 'User OCID': 450}

        # For cross-tenancy policies, just show all we have
        self.all_defined_alias_columns = ['Defined Name', 'Defined Type', 'OCID Alias']
        self.all_cross_tenancy_columns = ['Policy Name', 'Policy OCID', 'Statement Text', 'Creation Time']
        self.all_defined_alias_column_widths = {'Defined Name': 150, 'Defined Type': 150, 'OCID Alias': 500}
        self.all_cross_tenancy_column_widths = {
            'Policy Name': 150,
            'Policy OCID': 300,
            'Statement Text': 600,
            'Creation Time': 150,
        }

        # AI reference columns
        self.resource_data_all_columns = ['Resource', 'Permissions', 'Families']

        # Packed frame
        self.create_main_shell()

        # Create Top-level menu, notebook, console, and status bar
        # self.create_top_menu()
        self.create_notebook()
        self.create_console()
        self.create_ai_insights()
        self.create_status_bar()

        # Create tabs
        self.create_tab_start()  # Start Tab (Configuration)
        self.create_tab_policy()  # Regular Policy Statements
        self.create_tab_dynamic_groups()  # Dynamic Groups
        self.create_tab_resource_principals()  # Resource Principals
        self.create_tab_user_analysis()  # User Analysis
        self.create_tab_cross_tenancy()  # Cross Tenancy
        self.create_tab_report()  # Report
        self.create_tab_history()  # History
        # self.create_tab_resource_reference()  # Resource Reference Data

        # # Disable tabs until data loaded
        # self.notebook.tab(1, state="disabled")
        # self.notebook.tab(2, state="disabled")
        # self.notebook.tab(3, state="disabled")
        # self.notebook.tab(4, state="disabled")
        # self.notebook.tab(5, state="disabled")
        # self.notebook.tab(6, state="disabled")

        # Kick off the scheduled Status Bar Updates:
        self._update_status_bar_text()
        self._update_ai_insights_response()

        # Update the layout
        self._update_layout()

    def load_reference_data(self):
        """Load data from persistent file if available, else return empty dict."""
        CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'
        DATA_FILE = CACHE_DIR / 'oci_resources_data.json'

        logger.info('Loading data from %s', DATA_FILE)
        try:
            with open(DATA_FILE) as f:
                self.resource_reference_data = json.load(f)
                logger.info('Successfully loaded resource data with %d resources', len(self.resource_reference_data))
                # return self.resource_reference_data
        except FileNotFoundError:
            logger.debug('Data file %s not found, returning empty dict', DATA_FILE)
            self.resource_reference_data = {}
        except json.JSONDecodeError as e:
            logger.error('Failed to parse JSON from %s: %s', DATA_FILE, e)
            self.resource_reference_data = {}

    def create_main_shell(self):
        # Use pack for top and bottom
        # Configure main shell with pack
        self.header_frame = ttk.Frame(self.root)
        self.header_frame.pack(fill='x', padx=2, pady=5)
        self.context_label = ttk.Label(
            self.header_frame,
            text='Start with the configuration, load tenancy data live or from a saved cache, then set up GenAI if desired, and then begin to analyze policies, dynamic groups, and resource principals.\nCross-tenancy policies will be separated out and displayed separately.  Use AI Insights to analyze statements further.',
        )
        self.context_label.pack(side='left')

        # Status bar
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.pack(fill='x', side='bottom', padx=5, pady=5)

        # Main Content Area (Notebook)
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill='both', expand=True)

        # AI Insights Frame (add and remove as needed)
        self.ai_insights_frame = ttk.Frame(self.main_frame)  # AI frame (not packed initially)

        # Console Frame (add and remove as needed)
        self.console_frame = ttk.Frame(self.main_frame)  # Console frame (not packed initially)

        # Notebook Frame
        self.notebook_frame = ttk.Frame(self.main_frame)
        # self.notebook_frame.pack(fill='both', expand=True)

    def create_status_bar(self):
        # Status bar

        self.label_status_bar = ttk.Label(
            self.status_frame,
            text=self.status_bar_text,
            anchor='w',
        )
        self.label_status_bar.grid(row=0, column=0, sticky='ew')

    def create_top_menu(self):  # noqa: C901
        """Create the top-level menu with File and Help options."""

    def create_notebook(self):  # noqa: C901
        def on_tab_change(event):
            selected_tab_id = self.notebook.select()  # Get the ID of the currently selected tab
            selected_tab_index = self.notebook.index(selected_tab_id)  # Get the index
            logger.debug(f'Tab changed to: {selected_tab_index} ({selected_tab_id})')
            # Change the context help text based on the selected tab
            if selected_tab_index == 0:
                self.context_label.config(
                    text='Start with the configuration, load tenancy data live or from a saved cache, then set up other settings and GenAI if desired.\n\
Once Loaded, use the tabs to analyze policies, dynamic groups, resource principals, and cross-tenancy policies.  Use AI Insights to analyze statements further.'
                )
            elif selected_tab_index == 1:
                self.context_label.config(
                    text='View and analyze standard IAM policy statements here. Use the filters to narrow down to specific compartments, permissions, or keywords.\n\
Select a statement to see detailed parsing and AI insights if enabled.'
                )
            elif selected_tab_index == 2:
                self.context_label.config(
                    text='View and analyze Dynamic Groups here. See which dynamic groups are in use by policies, and examine their matching rules.\n'
                    'Select a dynamic group to see detailed formatting and AI insights if enabled.'
                )
            elif selected_tab_index == 3:
                self.context_label.config(
                    text='View and analyze Resource Principals here. See which resource principals are in use by policies, and examine their details.\n'
                    'Select a resource principal to see detailed information and AI insights if enabled.'
                )
            elif selected_tab_index == 4:
                self.context_label.config(
                    text='Analyze users and their group memberships here. Identify which users are members of groups that have policy permissions, and see\n'
                    'if any users have direct policy assignments.'
                )
            elif selected_tab_index == 5:
                self.context_label.config(
                    text='View cross-tenancy policy statements here. These are policies that reference resources or groups in other tenancies.\n'
                    'Analyze these statements and see which defined aliases they use.'
                )
            elif selected_tab_index == 6:
                self.context_label.config(
                    text='Generate and view reports of your policy and dynamic group analysis here. Export the data to CSV for further examination or sharing.'
                )
            elif selected_tab_index == 7:
                self.context_label.config(
                    text='View the history of actions taken within the application here. This includes loading data, applying configurations,\n'
                    'and any errors encountered.'
                )
            elif selected_tab_index == 8:
                self.context_label.config(
                    text='Reference data for OCI resources, including permissions and families. This data is used to enhance the analysis of policies and dynamic groups.'
                )
            else:
                self.context_label.config(
                    text='OCI Policy and Dynamic Group Viewer. Use the tabs to navigate through different analyses and configurations.'
                )

        # Create notebook - grid row 0
        self.notebook = ttk.Notebook(self.notebook_frame, bootstyle='primary')
        # self.notebook.grid(row=0, column=0, sticky='nsew', padx=3, pady=5)
        self.notebook.pack(expand=True, fill='both', padx=3, pady=3)
        self.notebook.bind('<<NotebookTabChanged>>', on_tab_change)

    def create_console(self):
        """Console frame with clear and level button can control main logging level"""

        # Sub-frame for text widget
        self.text_frame = ttk.Labelframe(self.console_frame, text='Console Log', bootstyle='secondary')
        self.text_frame.pack(side='left', fill=tk.BOTH, expand=True)
        self.console_text = ttk.ScrolledText(
            self.text_frame, height=12, state='disabled', borderwidth=0, highlightthickness=0, relief='flat'
        )
        self.console_text.pack(fill='both')

    def create_ai_insights(self):
        # Sub-frame for text widget
        self.policy_response_frame = ttk.Labelframe(self.ai_insights_frame, text='AI Insights', bootstyle='secondary')
        self.policy_response_frame.pack(side='right', fill=tk.BOTH, expand=True)

        # AI Response Markdown
        self.ai_insights_response_html = HTMLText(
            self.policy_response_frame, borderwidth=0, highlightthickness=0, relief='flat', height=12
        )
        self.ai_insights_response_html.pack(fill=tk.BOTH, expand=True)

    def create_tab_start(self):  # noqa: C901
        # Tab and add to Notebook
        tab_start = ttk.Frame(self.notebook)  # type: ignore
        self.notebook.add(tab_start, text='Start\n(Configuration)')
        tab_start.grid_rowconfigure(0, weight=1)
        tab_start.grid_columnconfigure(0, weight=1)

        # Top-level frame for start tab
        frm_start = ttk.Frame(tab_start)
        frm_start.grid_rowconfigure(0, weight=1)
        frm_start.grid_columnconfigure(0, weight=1)
        frm_start.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        def clear_console():
            self.console_text.config(state='normal')
            self.console_text.delete(1.0, tk.END)
            self.console_text.config(state='disabled')
            logger.info('Console cleared')

        def _update_log_level(level):
            level_map = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO, 'WARNING': logging.WARNING}
            logger.setLevel(level_map[level])
            if level == 'DEBUG':
                self.verbose = True
            else:
                self.verbose = False
            logger.info(f'Log level set to {level}')
            self.persist_options()

        def populate_model_tree():
            """Populate the model Treeview with available models from list_models."""
            logger.info('Populating model tree')
            # Check and initialize AI client if needed
            if not self.ai.initialized:
                logger.info(
                    f'Creating AI Clients from selected Profile: {self.profile_var.get()} or IP:{self.use_instance_principal_var.get()}.'
                )
                self.ai.initialize_client(
                    use_instance_principal=self.use_instance_principal_var.get(), profile=self.profile_var.get()
                )
                # Grab endpoint/compartment for variable
                self.endpoint_var.set(self.ai.base_endpoint)
                self.ai_compartment_var.set(self.ai.tenancy_ocid)
                logger.debug(f'AI initialized: {self.ai.initialized}')

            if self.ai.initialized:
                ai_models = self.ai.list_models()
                logger.info(f'list_models returned {len(ai_models)} models')

                # Put in Model Data Table
                ai_model_table.update_data(new_data=ai_models)
            else:
                logger.warning('AI client not initialized, cannot list models')

        def apply_config():
            """Apply changes to Model ID and Endpoint in AI client."""
            start_time = datetime.datetime.now()
            model_id = self.model_id_var.get().strip()
            endpoint = self.endpoint_var.get().strip()
            compartment_ocid = self.ai_compartment_var.get().strip()
            logger.info('Applying config changes: Model ID=%s, Endpoint=%s', model_id, endpoint)

            try:
                self.ai.update_config(model_ocid=model_id, endpoint=endpoint, compartment_ocid=compartment_ocid)
                logger.info(
                    'Configuration updated successfully in %s seconds',
                    (datetime.datetime.now() - start_time).total_seconds(),
                )
                # Make AI Call to test
                if self.option_ai_var.get():
                    # self.ai_insights_frame.pack(fill='both', before=self.status_frame, padx=10, pady=5)
                    logger.info('AI analysis before call')
                    self.ai_insights_response_html.set_html(
                        '<p style="font-size: 8px;">Testing AI configuration...</p>'
                    )
                    ai_thread = Thread(
                        target=self.ai.test_ai_call,
                        args=('What is the meaning of life?', self.result_queue, False, 'Short answer please.'),
                        daemon=True,
                        name='AI-Test-Thread',
                    )
                    ai_thread.start()
                    # ai_result = self.ai.analyze_policy_statement(policy_text="allow any-user to manage instances in compartment X", queue=self.result_queue, use_cache=False)
                    logger.info('AI analysis thread started')
            except Exception as e:
                logger.error('Failed to update configuration: %s', e)

        def update_tree_style(new_font_size: int, lines: int = 1):
            logger.info(f'Update font to size {new_font_size}')
            self.font.configure(size=new_font_size)
            self.bold_font.configure(size=new_font_size)
            # style = ttk.Style()
            self.style.configure('Treeview', font=self.font, rowheight=(new_font_size + 10))
            self.style.configure('Treeview.Heading', font=self.bold_font, rowheight=(new_font_size + 10))

        def toggle_recursive_load():
            logger.info(f'Changing to recursive load: {self.recursive_load_var.get()}')
            # Persist Options
            self.persist_options()

        def toggle_profile_dropdown():
            if self.use_instance_principal_var.get():
                self.input_profile.config(state=tk.DISABLED)
                self.label_profile.config(state=tk.DISABLED)
            else:
                self.input_profile.config(state=tk.NORMAL)
                self.label_profile.config(state=tk.NORMAL)
            self.persist_options()

        # Label Frame for Tenancy and Config
        label_frm_tenancy_config = ttk.Labelframe(frm_start, text='Tenancy and Config', bootstyle='secondary')
        label_frm_tenancy_config.pack(fill='x', padx=5, pady=5)

        # Instance Principal checkbox
        # self.use_instance_principal_var = tk.BooleanVar(value=False)
        self.chk_instance_principal = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Instance Principal',
            variable=self.use_instance_principal_var,
            command=toggle_profile_dropdown,
        )
        self.chk_instance_principal.grid(row=0, column=0, padx=5, pady=5, sticky='w')

        # Recursion checkbox
        # self.recursive_load_var = tk.BooleanVar(value=True)
        self.recursive_load = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Recursive',
            variable=self.recursive_load_var,
            command=toggle_recursive_load,
        )
        self.recursive_load.grid(row=1, column=0, padx=5, pady=5, sticky='w')

        # self.profile_var = tk.StringVar(value=profile_list[0])
        self.label_profile = ttk.Label(label_frm_tenancy_config, text='Profile:')

        self.label_profile.grid(row=0, column=1, padx=5, pady=3)
        self.input_profile = ttk.OptionMenu(
            label_frm_tenancy_config, self.profile_var, self.profile_var.get(), *self.profile_list
        )
        self.input_profile.config(width=20)
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)

        # Get available cached copies
        self.label_cache = ttk.Label(label_frm_tenancy_config, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.cache_list = get_available_cache(None)
        self.cache_var = tk.StringVar(value=self.cache_list[0] if len(self.cache_list) > 0 else 'No Cache Available')
        self.cache_list_dropdown = ttk.OptionMenu(
            label_frm_tenancy_config, self.cache_var, self.cache_var.get(), *self.cache_list, bootstyle='default'
        )
        self.cache_list_dropdown.config(width=20)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)

        # If the instance principal was selected, disable this
        if self.use_instance_principal_var.get():
            self.input_profile.config(state=tk.DISABLED)

        # Load buttons
        self.btn_load_tenancy = ttk.Button(
            label_frm_tenancy_config,
            text='Load from Tenancy',
            command=self._load_from_tenancy,
            width=20,
            bootstyle='default',
        )
        self.btn_load_tenancy.grid(row=0, column=3, padx=5, pady=3)
        self.btn_load_cache = ttk.Button(
            label_frm_tenancy_config,
            text='Load from Cache',
            command=self._load_from_cache,
            width=20,
            bootstyle='default',
        )
        self.btn_load_cache.grid(row=1, column=3, padx=5, pady=3)

        ttk.Separator(label_frm_tenancy_config, orient=tk.VERTICAL).grid(row=0, column=4, rowspan=2, padx=5, pady=3)

        # Import button
        self.btn_import_cache = ttk.Button(
            label_frm_tenancy_config,
            text='Import from JSON',
            command=self._import_cache_from_json,
        )
        self.btn_import_cache.grid(row=0, column=5, padx=5, pady=2, sticky='ew')

        # Export button
        self.btn_export_cache = ttk.Button(
            label_frm_tenancy_config, text='Export to JSON', command=self._export_cache_to_json, state=tk.DISABLED
        )
        self.btn_export_cache.grid(row=1, column=5, padx=5, pady=2, sticky='ew')

        # Progress bar and label
        self.progress_bar_label = ttk.Label(label_frm_tenancy_config, text='')
        self.progress_bar_label.grid(row=0, column=6, padx=5, pady=3)
        self.progress_bar_label.grid_remove()
        self.progress_bar = ttk.Progressbar(label_frm_tenancy_config, mode='indeterminate', length=100)
        self.progress_bar.grid(row=1, column=6, padx=5, pady=3, sticky='ew')
        self.progress_bar.grid_remove()

        ###############################
        # Label Frame for AI Connection
        self.label_frm_ai_config = ttk.Labelframe(frm_start, text='OCI GenAI', bootstyle='secondary')
        self.label_frm_ai_config.pack(fill='x', padx=5, pady=5)

        self.option_ai_var = tk.BooleanVar()
        self.enable_ai_insights = ttk.Checkbutton(
            self.label_frm_ai_config,
            text='Enable AI Insights?',
            variable=self.option_ai_var,
            command=self._update_layout,
        )
        self.enable_ai_insights.grid(row=0, column=0, padx=3, pady=3, sticky='ew')

        self.refresh_button = ttk.Button(
            self.label_frm_ai_config, text='Refresh Models (using selected profile)', command=populate_model_tree
        )
        self.refresh_button.grid(row=0, column=1, padx=3, pady=3, sticky='ew')
        logger.debug('Refresh Models button created')

        def update_model_ocid(selected_items):
            if selected_items:
                model_ocid = selected_items[0].get('Model OCID', '')
                self.model_id_var.set(model_ocid)
                logger.info(f'Updated Model ID entry with OCID {model_ocid} from data table selection')

        def model_ocid_right_click(row_index: int) -> tk.Menu:
            menu = tk.Menu(self.label_frm_ai_config, tearoff=0)
            menu.add_command(
                label=f'View Details (Row {row_index})',
                command=lambda: logger.info(f'View details for row {row_index}'),
            )
            # menu.add_command(
            #     label=f"Delete Row {row_index}",
            #     command=lambda: print(f"Delete row {row_index}")
            # )
            return menu

        # Data Table for models
        ai_model_table = DataTable(
            parent=self.label_frm_ai_config,
            columns=AI_MODEL_COLUMNS,
            display_columns=AI_MODEL_COLUMNS,
            column_widths=AI_MODEL_COLUMN_WIDTHS,
            data=[],
            selection_callback=update_model_ocid,
            row_context_menu_callback=model_ocid_right_click,
            multi_select=False,
        )
        ai_model_table.grid(row=1, column=0, columnspan=3, padx=3, pady=3, sticky='ew')

        # Configuration inputs
        tk.Label(self.label_frm_ai_config, text='Model ID (default Grok3 Fast):').grid(
            row=2, column=0, padx=2, pady=3, sticky='ew'
        )
        self.model_id_var = tk.StringVar()
        self.model_id_entry = tk.Entry(self.label_frm_ai_config, textvariable=self.model_id_var, width=80)
        self.model_id_entry.grid(row=2, column=1, padx=3, pady=3, sticky='ew')

        tk.Label(self.label_frm_ai_config, text='Regional Endpoint:').grid(row=3, column=0, padx=2, pady=3, sticky='ew')
        self.endpoint_var = tk.StringVar()
        self.endpoint_entry = tk.Entry(self.label_frm_ai_config, textvariable=self.endpoint_var, width=80)
        self.endpoint_entry.grid(row=3, column=1, padx=3, pady=3, sticky='ew')

        tk.Label(self.label_frm_ai_config, text='Compartment (for GenAI):').grid(
            row=4, column=0, padx=2, pady=3, sticky='ew'
        )
        self.ai_compartment_var = tk.StringVar()
        self.ai_compartment_entry = tk.Entry(self.label_frm_ai_config, textvariable=self.ai_compartment_var, width=80)
        self.ai_compartment_entry.grid(row=4, column=1, padx=3, pady=3, sticky='ew')

        apply_button = ttk.Button(self.label_frm_ai_config, text='Apply and Test GenAI Settings', command=apply_config)
        apply_button.grid(row=2, column=2, rowspan=3, padx=3, pady=3, sticky='ew')
        logger.debug('Apply button created')

        # Label Frame for Display
        self.label_frm_display_config = ttk.Labelframe(frm_start, text='Display Settings', bootstyle='secondary')
        self.label_frm_display_config.pack(fill='x', padx=5, pady=5)

        # Console Options
        self.option_console_var = tk.BooleanVar()
        self.enable_console = ttk.Checkbutton(
            self.label_frm_display_config,
            text='Console Log Window',
            variable=self.option_console_var,
            command=self._update_layout,
        )
        self.enable_console.grid(row=0, column=0, padx=3, pady=3, sticky='ew')

        # Clear Log
        ttk.Button(self.label_frm_display_config, text='Clear Log', command=clear_console).grid(
            row=0, column=1, padx=3, pady=3, sticky='ew'
        )

        # Log Level
        ttk.Label(self.label_frm_display_config, text='Log Level').grid(row=0, column=2, padx=3, pady=3, sticky='ew')
        ttk.OptionMenu(
            self.label_frm_display_config, self.log_level, 'INFO', 'DEBUG', 'INFO', 'WARNING', command=_update_log_level
        ).grid(row=0, column=3, padx=3, pady=3, sticky='ew')

        # Font Size
        ttk.Label(self.label_frm_display_config, text='Font Size (Tables)').grid(
            row=1, column=0, padx=3, pady=3, sticky='ew'
        )
        ttk.OptionMenu(
            self.label_frm_display_config, self.font_size_var, 10, 8, 10, 12, 14, 16, command=update_tree_style
        ).grid(row=1, column=1, padx=3, pady=3, sticky='ew')

        # Add a test button for the popup
        # test_popup_button = ttk.Button(self.label_frm_display_config, text="Show Popup", command=lambda: self.show_popup("Policy Loaded Successfully!", side="right"))
        # test_popup_button.grid(row=0, column=5, padx=5, pady=5)

        # # Create console handler but don't add it yet
        self.console_handler = TextHandler(self.console_text, self.root)
        self.console_handler.setFormatter(self.formatter)
        # logger.info('Application started')

    def create_tab_policy(self):  # noqa: C901
        # Toggles
        def _toggle_any_subject():
            if self.use_subject_any.get():
                self.subject_filter_var.set('any-user|any-group')
            else:
                self.subject_filter_var.set('')

            # Update the Output
            self._update_policy_output()

        def _toggle_location_tenancy():
            if self.location_filter_tenancy.get():
                self.location_filter_var.set('tenancy')
            else:
                self.location_filter_var.set('')

            # Update the output
            self._update_policy_output()

        def _toggle_hierarchy_root():
            if self.hierarchy_filter_root.get():
                self.hierarchy_filter_var.set('ROOTONLY')
            else:
                self.hierarchy_filter_var.set('')

            # Update the Output
            self._update_policy_output()

        def _clear_policy_filters():
            # Clear all filters
            for entry in [
                self.subject_filter_var,
                self.verb_filter_var,
                self.resource_filter_var,
                self.location_filter_var,
                self.hierarchy_filter_var,
                self.condition_filter_var,
                self.text_filter_var,
                self.policy_filter_var,
            ]:
                entry.set('')
            self.use_subject_any.set(False)
            self.location_filter_tenancy.set(False)
            self.hierarchy_filter_root.set(False)
            self._update_policy_output()

        # Tab and add to Notebook
        tab_policy = ttk.Frame(self.notebook)  # type: ignore
        self.notebook.add(tab_policy, text='Regular Policy\nStatements')
        tab_policy.grid_rowconfigure(1, weight=1)
        tab_policy.grid_columnconfigure(0, weight=1)
        tab_policy.configure(style='disabled.TNotebook.Tab')
        tab_policy.state(['disabled'])

        # Top-level frame for policy tab
        frm_policy_top = ttk.Frame(tab_policy)
        frm_policy_top.grid_rowconfigure(0, weight=1)
        frm_policy_top.grid_columnconfigure(0, weight=1)
        frm_policy_top.grid(row=0, column=0, sticky='ew', padx=5, pady=5)

        # Create the policy filter frame
        frm_policy_filter = ttk.Frame(frm_policy_top)
        frm_policy_filter.grid(row=0, column=0, sticky='ew')
        frm_policy_filter.columnconfigure([1, 3], weight=1)
        ttk.Label(frm_policy_filter, text='Filters - use | in fields for OR)').grid(
            row=0, column=0, columnspan=5, pady=2, sticky='ew'
        )

        # Variables for filter
        self.subject_filter_var = tk.StringVar()
        self.use_subject_any = tk.BooleanVar()
        self.verb_filter_var = tk.StringVar()
        self.location_filter_var = tk.StringVar()
        self.resource_filter_var = tk.StringVar()
        self.hierarchy_filter_var = tk.StringVar()
        self.condition_filter_var = tk.StringVar()
        self.text_filter_var = tk.StringVar()
        self.policy_filter_var = tk.StringVar()
        self.hierarchy_filter_root = tk.BooleanVar()
        self.location_filter_tenancy = tk.BooleanVar()

        # Within the policy filter frame, create the filter fields and buttons
        frm_subj = ttk.Frame(frm_policy_filter)
        ttk.Label(frm_policy_filter, text='Subject').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(frm_subj, textvariable=self.subject_filter_var, width=20, bootstyle='info').grid(
            row=0, column=0, padx=2, sticky='ew'
        )
        ttk.Checkbutton(
            frm_subj, text='Any-User/Group', variable=self.use_subject_any, command=_toggle_any_subject
        ).grid(row=0, column=1, padx=2)
        frm_subj.grid(row=1, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Verb').grid(row=1, column=2, padx=5, pady=2, sticky='w')
        tk.Entry(frm_policy_filter, textvariable=self.verb_filter_var, width=20).grid(
            row=1, column=3, padx=5, pady=2, sticky='ew'
        )

        ttk.Label(frm_policy_filter, text='Resource').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        tk.Entry(frm_policy_filter, textvariable=self.resource_filter_var, width=20).grid(
            row=2, column=1, padx=5, pady=2, sticky='ew'
        )

        frm_loc = ttk.Frame(frm_policy_filter)
        ttk.Label(frm_policy_filter, text='Location').grid(row=2, column=2, padx=5, pady=2, sticky='w')
        entry_loc = tk.Entry(frm_loc, width=20, textvariable=self.location_filter_var)
        entry_loc.grid(row=0, column=0, padx=2, sticky='ew')
        ttk.Checkbutton(
            frm_loc, text='in tenancy', variable=self.location_filter_tenancy, command=_toggle_location_tenancy
        ).grid(row=0, column=1, padx=2)
        frm_loc.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        frm_hierarchy = ttk.Frame(frm_policy_filter)
        frm_hierarchy.grid_columnconfigure(0, weight=15)
        frm_hierarchy.grid_columnconfigure(1, weight=70)
        frm_hierarchy.grid_columnconfigure(2, weight=15)
        ttk.Label(frm_policy_filter, text='Hierarchy').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        entry_hierarchy = tk.Entry(frm_hierarchy, width=40, textvariable=self.hierarchy_filter_var)
        entry_hierarchy.grid(row=0, column=0, padx=2, sticky='ew')
        ttk.Checkbutton(
            frm_hierarchy, text='Tenancy Root Only', variable=self.hierarchy_filter_root, command=_toggle_hierarchy_root
        ).grid(row=0, column=1, padx=2)
        frm_hierarchy.grid(row=3, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Condition').grid(row=3, column=2, padx=5, pady=2, sticky='w')
        entry_condition = tk.Entry(frm_policy_filter, width=20, textvariable=self.condition_filter_var)
        entry_condition.grid(row=3, column=3, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Text').grid(row=4, column=0, padx=5, pady=2, sticky='w')
        entry_text = tk.Entry(frm_policy_filter, width=20, textvariable=self.text_filter_var)
        entry_text.grid(row=4, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Policy Name').grid(row=4, column=2, padx=5, pady=2, sticky='w')
        entry_policy = tk.Entry(frm_policy_filter, textvariable=self.policy_filter_var, width=20)
        entry_policy.grid(row=4, column=3, padx=5, pady=2, sticky='ew')

        frm_policy_buttons = ttk.Frame(frm_policy_filter)
        self.btn_update = ttk.Button(
            frm_policy_buttons, text='Update', state=tk.DISABLED, command=self._update_policy_output
        )
        # Clear Button
        self.btn_clear = ttk.Button(frm_policy_buttons, text='Clear', state=tk.DISABLED, command=_clear_policy_filters)
        self.btn_clear.grid(row=1, column=0, padx=5, pady=2, sticky='ew')

        self.btn_export_policy = ttk.Button(
            frm_policy_buttons,
            text='Export Filtered\nStatements to CSV',
            state=tk.DISABLED,
            command=self._export_policy_to_csv,
        )
        self.btn_export_policy.grid(row=2, column=0, padx=5, pady=2, sticky='ew')
        frm_policy_buttons.grid(row=1, column=4, rowspan=4, padx=5, pady=2, sticky='ns')

        # Output Filters Frame
        frm_policy_output = ttk.Frame(frm_policy_top)
        frm_policy_output.grid(row=1, column=0, sticky='w')
        frm_policy_output.columnconfigure(0, weight=1)

        # Show Tenancy Name
        self.tenancy_name_var = tk.StringVar()
        ttk.Label(frm_policy_output, textvariable=self.tenancy_name_var).grid(row=0, column=0, padx=5, pady=3)
        ttk.Separator(frm_policy_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        # Statements count
        self.label_policy_count = ttk.Label(frm_policy_output, text='Statements (Filtered): 0')
        self.label_policy_count.grid(row=0, column=2, padx=5, pady=3, sticky='w')

        self.chk_show_service = tk.BooleanVar()
        self.chk_show_dynamic = tk.BooleanVar()
        self.chk_show_resource = tk.BooleanVar()
        self.chk_show_invalid = tk.BooleanVar()
        self.chk_show_regular = tk.BooleanVar(value=True)
        self.chk_show_expanded = tk.BooleanVar()
        ttk.Separator(frm_policy_output, orient=tk.VERTICAL).grid(row=0, column=3, padx=5, pady=3)
        # Display Output Selection
        ttk.Label(frm_policy_output, text='Statement Type\nto display:').grid(row=0, column=4, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Service', variable=self.chk_show_service, command=self._update_policy_output
        ).grid(row=0, column=5, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Dynamic Group', variable=self.chk_show_dynamic, command=self._update_policy_output
        ).grid(row=0, column=6, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Resource', variable=self.chk_show_resource, command=self._update_policy_output
        ).grid(row=0, column=7, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Regular', variable=self.chk_show_regular, command=self._update_policy_output
        ).grid(row=0, column=8, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Invalid Only', variable=self.chk_show_invalid, command=self._update_policy_output
        ).grid(row=0, column=9, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Parsed Output', variable=self.chk_show_expanded, command=self._update_policy_output
        ).grid(row=0, column=10, padx=5, pady=3)

        def selection_callback(selected_rows: list[dict]) -> None:
            for row in selected_rows:
                logger.info(f"Selected policy statement: {row.get('Statement Text')}")
                # Update the policy box
                self.policy_analyze_statement_var.set(row.get('Statement Text'))

        # Frame for policy table - row 1 of tab_policy
        frm_policy_sheet = ttk.Frame(tab_policy)
        frm_policy_sheet.grid_rowconfigure(0, weight=1)
        frm_policy_sheet.grid_columnconfigure(0, weight=1)
        frm_policy_sheet.grid(row=1, column=0, columnspan=2, sticky='nsew')

        # Use the Data Table here with fields
        self.policy_table = DataTable(
            frm_policy_sheet,
            columns=self.all_policy_columns,
            display_columns=self.basic_policy_columns,
            data=[],
            column_widths=self.policy_column_widths,
            # font_size=10,
            selection_callback=selection_callback,
            multi_select=True,
        )
        # self.policy_table.grid(row=0, column=0, sticky="nsew")
        self.policy_table.pack(fill='both', expand=True)

        # Field and button for analysis
        frm_policy_analyze = ttk.Frame(tab_policy)
        frm_policy_analyze.grid_rowconfigure(0, weight=1)
        frm_policy_analyze.grid_columnconfigure(0, weight=15)
        frm_policy_analyze.grid_columnconfigure(1, weight=70)
        frm_policy_analyze.grid_columnconfigure(2, weight=15)
        frm_policy_analyze.grid(row=2, column=0, columnspan=2, sticky='nsew')

        ttk.Label(frm_policy_analyze, text='Policy Statement to Analyze').grid(
            row=0, column=0, padx=5, pady=2, sticky='w'
        )
        self.policy_analyze_statement_var = tk.StringVar()
        self.policy_analyze_statement_entry = tk.Entry(
            frm_policy_analyze, state=tk.NORMAL, width=120, textvariable=self.policy_analyze_statement_var
        )
        self.policy_analyze_statement_entry.grid(row=0, column=1, padx=5, pady=2, sticky='w')

        self.btn_policy_analyze_statement = ttk.Button(
            frm_policy_analyze,
            text='Analyze Statement',
            state=tk.DISABLED,
            command=lambda: self._analyze_policy_statment_ai(
                additional_context='Put the actual policy statement into a markdown fenced code block.'
            ),
            bootstyle='primary',
        )
        self.btn_policy_analyze_statement.grid(row=0, column=2, padx=5, pady=2, sticky='ew')

        # Trace for auto-update
        # _update_policy_output
        self.subject_filter_var.trace_add('write', self._update_policy_output)
        self.verb_filter_var.trace_add('write', self._update_policy_output)
        self.resource_filter_var.trace_add('write', self._update_policy_output)
        self.location_filter_var.trace_add('write', self._update_policy_output)
        self.hierarchy_filter_var.trace_add('write', self._update_policy_output)
        self.condition_filter_var.trace_add('write', self._update_policy_output)
        self.text_filter_var.trace_add('write', self._update_policy_output)
        self.policy_filter_var.trace_add('write', self._update_policy_output)

    def create_tab_dynamic_groups(self):
        # Tab creation for Dynamic Groups
        tab_dg = ttk.Frame(self.notebook)
        self.notebook.add(tab_dg, text='Dynamic Groups / \nInstance Principals')
        # 20% / 40% / 40% (Filter / DG Sheet / Policy Sheet)
        tab_dg.grid_rowconfigure(0, weight=2)
        tab_dg.grid_rowconfigure(1, weight=4)
        tab_dg.grid_rowconfigure(2, weight=4)
        tab_dg.grid_columnconfigure(0, weight=1)

        # Inner methods
        def clear_dg_filters():
            for entry in [self.dg_entry_domain, self.dg_entry_name, self.dg_entry_type, self.dg_entry_ocid]:
                entry.delete(0, tk.END)
            self._update_dg_output()

        # Top of frame
        frm_dg_filter = ttk.Frame(tab_dg)
        frm_dg_filter.grid(row=0, column=0, sticky='w', padx=5, pady=5)
        frm_dg_filter.columnconfigure([1, 3], weight=1)
        ttk.Label(frm_dg_filter, text='Filters (| for OR, AND between fields)').grid(
            row=0, column=0, columnspan=5, pady=2, sticky='ew'
        )
        ttk.Label(frm_dg_filter, text='Domain').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_domain = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=25)
        self.dg_entry_domain.grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='OCID').grid(row=1, column=2, padx=5, pady=2, sticky='w')
        self.dg_entry_ocid = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=40)
        self.dg_entry_ocid.grid(row=1, column=3, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Name').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_name = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=25)
        self.dg_entry_name.grid(row=2, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Rule Component').grid(row=2, column=2, padx=5, pady=2, sticky='w')
        self.dg_entry_type = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=40)
        self.dg_entry_type.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        # Buttons
        self.dg_btn_update = ttk.Button(frm_dg_filter, text='Update', state=tk.DISABLED, command=self._update_dg_output)
        self.dg_btn_update.grid(row=1, column=4, padx=5, pady=2, sticky='ew')
        self.dg_btn_clear = ttk.Button(frm_dg_filter, text='Clear', state=tk.DISABLED, command=clear_dg_filters)
        self.dg_btn_clear.grid(row=2, column=4, padx=5, pady=2, sticky='ew')

        self.dg_btn_analyze_dg = ttk.Button(
            frm_dg_filter, text='Run In\nUse Analysis', state=tk.DISABLED, command=self._run_dg_analysis
        )
        self.dg_btn_analyze_dg.grid(row=1, column=5, rowspan=2, padx=5, pady=2, sticky='ew')

        self.dg_label_count = ttk.Label(frm_dg_filter, text='Dynamic Groups (Filtered): 0')
        self.dg_label_count.grid(row=3, column=0, columnspan=2, padx=5, pady=3, sticky='w')
        self.chk_show_instance_principals = tk.BooleanVar()
        self.chk_show_not_in_use = tk.BooleanVar()
        self.chk_show_dg_ocid = tk.BooleanVar()
        ttk.Checkbutton(
            frm_dg_filter,
            text='Show Only Instance Principals',
            variable=self.chk_show_instance_principals,
            command=self._update_dg_output,
        ).grid(row=3, column=2, padx=5, pady=3)
        ttk.Checkbutton(
            frm_dg_filter,
            text='Show Only Unused Dynamic Groups',
            variable=self.chk_show_not_in_use,
            command=self._update_dg_output,
        ).grid(row=3, column=3, padx=5, pady=3)
        ttk.Checkbutton(
            frm_dg_filter,
            text='Show OCID and Creation Time',
            variable=self.chk_show_dg_ocid,
            command=self._update_dg_output,
        ).grid(row=3, column=4, padx=5, pady=3)

        # Frames for Bottom Sheets
        frm_dg_sheet = ttk.Frame(tab_dg)
        frm_dg_sheet.grid(row=1, column=0, sticky='nsew')
        frm_dg_sheet.grid_rowconfigure(0, weight=1)
        frm_dg_sheet.grid_columnconfigure(0, weight=1)

        frm_dg_policy_sheet = ttk.Frame(tab_dg)
        frm_dg_policy_sheet.grid(row=2, column=0, sticky='nsew')
        frm_dg_policy_sheet.grid_rowconfigure(0, weight=1)
        frm_dg_policy_sheet.grid_columnconfigure(0, weight=2)
        frm_dg_policy_sheet.grid_columnconfigure(1, weight=6)
        frm_dg_policy_sheet.grid_columnconfigure(2, weight=2)

        def dg_selection_callback(selected_rows: list[dict]) -> None:
            """When a Dynamic Group is selected, update the policy statements below"""
            dgs_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.info(f"Selected DG: {row.get('Domain')}, {row.get('DG Name')}")
                dgs_for_filter.append((row.get('Domain'), row.get('DG Name')))
            logger.info(f'DGs for filter: {dgs_for_filter}')
            # Call the filter
            filtered = self.policy_compartment_analysis.filter_policy_statements_by_dynamic_group_name(dgs_for_filter)

            logger.info(f'type: {type(filtered)} len: {len(filtered)}')
            # Set them into the next table
            self.dg_policy_table.update_data(filtered)
            logger.info(f'Policies added to policy table: {len(filtered)}')

        def dg_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.policy_analyze_statement_var.set(selected_statement)
            else:
                self.policy_analyze_statement_var.set('')

        # Dynamic Groups
        self.custom_data_dynamic_group = DataTable(
            frm_dg_sheet,
            columns=self.all_dg_columns,
            display_columns=self.basic_dg_columns,
            column_widths=self.dg_column_widths,
            data=[],
            selection_callback=dg_selection_callback,
            multi_select=True,
        )
        self.custom_data_dynamic_group.grid(row=0, column=0, sticky='nsew')

        # Use a Policy Table here with fields
        self.dg_policy_table = DataTable(
            frm_dg_policy_sheet,
            columns=self.all_policy_columns,
            display_columns=self.basic_policy_columns,
            data=[],
            column_widths=self.policy_column_widths,
            # font_size=10,
            selection_callback=dg_policy_selection_callback,
            multi_select=False,
        )
        self.dg_policy_table.grid(row=0, column=0, columnspan=3, sticky='nsew')

        ttk.Label(frm_dg_policy_sheet, text='Policy Statement to Analyze').grid(
            row=1, column=0, padx=5, pady=2, sticky='w'
        )
        # self.policy_analyze_statement_var = tk.StringVar()
        # Re-use the same variable for policy to analyze
        self.policy_analyze_statement_entry = tk.Entry(
            frm_dg_policy_sheet, state=tk.NORMAL, width=100, textvariable=self.policy_analyze_statement_var
        )
        self.policy_analyze_statement_entry.grid(row=1, column=1, padx=5, pady=2, sticky='w')

        self.btn_dg_analyze_statement = ttk.Button(
            frm_dg_policy_sheet, text='Analyze Statement', state=tk.DISABLED, command=self._analyze_policy_statment_ai
        )
        self.btn_dg_analyze_statement.grid(row=1, column=2, padx=5, pady=2, sticky='ew')

    def create_tab_resource_principals(self):
        # Create Resource Principals tab
        tab_principals = ttk.Frame(self.notebook)
        self.notebook.add(tab_principals, text='Resource\nPrincipals')
        # 3 Rows Filter / (DG / RP) / AI (10% / 25% / 25% / 10%)
        tab_principals.grid_rowconfigure(0, weight=10)
        tab_principals.grid_rowconfigure(1, weight=80)  # Separate Form
        tab_principals.grid_rowconfigure(2, weight=10)
        tab_principals.grid_columnconfigure(0, weight=1)

        # Frame for top
        frm_principals_top = tk.Frame(tab_principals)
        frm_principals_top.grid(row=0, column=0, sticky='w', padx=5, pady=5)

        # Principals Style dropdown
        tk.Label(frm_principals_top, text='Principals Style:').grid(row=0, column=0, padx=5, pady=2, sticky='w')
        self.principals_style_var = tk.StringVar(value='Dynamic Group')
        self.principals_style_list = ['Dynamic Group', 'any-user']
        self.principals_style_dropdown = ttk.OptionMenu(
            frm_principals_top, self.principals_style_var, self.principals_style_var.get(), *self.principals_style_list
        )
        self.principals_style_dropdown.grid(row=0, column=1, padx=5, pady=2, sticky='ew')

        # Resource Type dropdown
        tk.Label(frm_principals_top, text='Resource Type:').grid(row=0, column=2, padx=5, pady=2, sticky='w')
        self.resource_type_var = tk.StringVar(value='Any')
        self.resource_type_list = [
            'Any',
            'autonomousdatabase',
            'function',
            'apigateway',
            'disworkspace',
            'dataflow',
            'dbmgmt',
            'serviceconnector',
            'stackmon',
        ]
        self.resource_type_dropdown = ttk.OptionMenu(
            frm_principals_top, self.resource_type_var, self.resource_type_var.get(), *self.resource_type_list
        )
        self.resource_type_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky='ew')

        def rp_dg_selection_callback(selected_rows: list[dict]) -> None:
            """When a Dynamic Group is selected, update the policy statements below"""
            dgs_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.info(f'Selected row: {row}')
                dgs_for_filter.append((row.get('Domain'), row.get('DG Name')))
            logger.info(f'DGs for filter: {dgs_for_filter}')
            # Call the filter
            filtered = self.policy_compartment_analysis.filter_policy_statements_by_dynamic_group_name(dgs_for_filter)

            logger.info(f'type: {type(filtered)} len: {len(filtered)}')
            # Set them into the next table
            self.rp_policy_table.update_data(filtered)
            logger.info(f'Policies added to RP policy table: {len(filtered)}')

        def rp_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.policy_analyze_statement_var.set(selected_statement)
            else:
                self.policy_analyze_statement_var.set('')

        # Bottom frame (row 1) for sheets using grid (bottom 2 rows if DG, bottom 1 if any-user)
        frm_principals_bottom = tk.Frame(tab_principals)
        frm_principals_bottom.grid_rowconfigure(0, weight=1)
        frm_principals_bottom.grid_rowconfigure(1, weight=1)
        frm_principals_bottom.grid_columnconfigure(0, weight=1)
        frm_principals_bottom.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Dynamic Groups Sheet (can be ungridded when not needed)
        self.rp_dg_table = DataTable(
            frm_principals_bottom,
            columns=self.all_dg_columns,
            display_columns=self.basic_dg_columns,
            column_widths=self.dg_column_widths,
            data=[],
            selection_callback=rp_dg_selection_callback,
            multi_select=True,
        )
        self.rp_dg_table.grid(row=0, column=0, sticky='nsew')

        # RP Policy Table
        self.rp_policy_table = DataTable(
            frm_principals_bottom,
            columns=self.all_policy_columns,
            display_columns=self.basic_policy_columns,
            data=[],
            column_widths=self.policy_column_widths,
            # font_size=10,
            selection_callback=rp_policy_selection_callback,
            multi_select=False,
        )
        self.rp_policy_table.grid(row=1, column=0, sticky='nsew')

        # Frame for AI
        frm_principals_ai = tk.Frame(tab_principals)
        frm_principals_ai.grid(row=2, column=0, sticky='w', padx=5, pady=5)

        ttk.Label(frm_principals_ai, text='Policy Statement to Analyze').grid(
            row=0, column=0, padx=5, pady=2, sticky='w'
        )
        # self.policy_analyze_statement_var = tk.StringVar()
        # Re-use the same variable as other tabs for policy statement
        self.rp_policy_analyze_statement_entry = tk.Entry(
            frm_principals_ai, state=tk.NORMAL, width=100, textvariable=self.policy_analyze_statement_var
        )
        self.rp_policy_analyze_statement_entry.grid(row=0, column=1, padx=5, pady=2, sticky='w')

        self.btn_rp_analyze_statement = ttk.Button(
            frm_principals_ai, text='Analyze Statement', state=tk.DISABLED, command=self._analyze_policy_statment_ai
        )
        self.btn_rp_analyze_statement.grid(row=0, column=2, padx=5, pady=2, sticky='ew')

        # Update the sheet
        self._update_principals_sheets()

        # # Bind dropdowns to update function
        self.principals_style_var.trace_add('write', self._update_principals_sheets)
        self.resource_type_var.trace_add('write', self._update_principals_sheets)

    def create_tab_user_analysis(self):  # noqa: C901
        # Create tab with 20/80 rows
        tab_users = ttk.Frame(self.notebook)
        self.notebook.add(tab_users, text='User\nAnalysis')
        # Groups/Users on top (20%), Policies on bottom (70%), AI on bottom (10%)
        tab_users.grid_rowconfigure(0, weight=2)
        tab_users.grid_rowconfigure(1, weight=7)
        tab_users.grid_rowconfigure(2, weight=1)
        tab_users.grid_columnconfigure(0, weight=1)

        # For this tab, on the top left, include a table for all Groups with Domain/Group.  Allow Multi-Select
        # On the top right, include a table for all users, which is unfiltered, but if any group is selected on the left,
        # only show users in those groups.  This table is multi-select as well.
        # Depending on what is selected on the right, show all policies for those users in the bottom frame.
        # Bottom Frame is a policy table, similar to the other tabs, but only showing policies for the selected users/groups.
        # Similar AI analysis as well.

        # Frame for top (left form, right table)
        frm_user_top = ttk.Frame(tab_users)
        frm_user_top.grid_rowconfigure(0, weight=1)
        frm_user_top.grid_rowconfigure(1, weight=1)
        frm_user_top.grid_columnconfigure(0, weight=4)  # Options
        frm_user_top.grid_columnconfigure(1, weight=6)  # Table
        # frm_user_top.grid_columnconfigure(2, weight=4)
        frm_user_top.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Frame for Policy Statements (row 1)
        frm_users_policies = ttk.Frame(tab_users)
        frm_users_policies.grid_rowconfigure(0, weight=1)
        frm_users_policies.grid_rowconfigure(1, weight=9)
        frm_users_policies.grid_columnconfigure(0, weight=1)
        frm_users_policies.grid_columnconfigure(1, weight=1)
        frm_users_policies.grid_columnconfigure(2, weight=1)
        frm_users_policies.grid_columnconfigure(3, weight=7)
        frm_users_policies.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Frame for AI (row 2)
        frm_principals_ai = tk.Frame(tab_users)
        frm_principals_ai.grid(row=2, column=0, sticky='w', padx=5, pady=5)

        # Frame for AI
        ttk.Label(frm_principals_ai, text='Policy Statement to Analyze').grid(
            row=0, column=0, padx=5, pady=2, sticky='w'
        )

        # Re-use the same variable as other tabs for policy statement
        self.rp_policy_analyze_statement_entry = tk.Entry(
            frm_principals_ai, state=tk.NORMAL, width=100, textvariable=self.policy_analyze_statement_var
        )
        self.rp_policy_analyze_statement_entry.grid(row=0, column=1, padx=5, pady=2, sticky='ew')

        self.btn_user_analyze_statement = ttk.Button(
            frm_principals_ai, text='Analyze Statement', state=tk.DISABLED, command=self._analyze_policy_statment_ai
        )
        self.btn_user_analyze_statement.grid(row=0, column=2, padx=5, pady=2, sticky='ew')

        def users_group_selection_callback(selected_rows: list[dict]) -> None:
            """When a Group is selected, update the users/groups and policy statements below"""
            groups_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.debug(f"Selected Group: {row.get('Domain Name')} / {row.get('Group Name')}")
                if 'Group Name' in row:
                    groups_for_filter.append((row.get('Domain Name'), row.get('Group Name')))
            logger.info(f'Groups for filter: {groups_for_filter}')

            self._update_user_analysis_policy_output(groups_for_filter=groups_for_filter, users_for_filter=None)

        def users_user_selection_callback(selected_rows: list[dict]) -> None:
            """When a User is selected, update the users/groups and policy statements below"""
            users_for_filter = []
            # Make the DG list (Domain,Name) for all selected rows
            for row in selected_rows:
                logger.debug(f"Selected User: {row.get('Domain Name')} / {row.get('User Name')}")
                if 'User Name' in row:
                    users_for_filter.append((row.get('Domain Name'), row.get('User Name')))
            logger.info(f'Users for filter: {users_for_filter}')

            self._update_user_analysis_policy_output(groups_for_filter=None, users_for_filter=users_for_filter)

        def users_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.policy_analyze_statement_var.set(selected_statement)
            else:
                self.policy_analyze_statement_var.set('')

        def switch_groups_users_selection(*args):
            """probably get rid of this"""
            logger.debug('Calling update for users')
            self._update_user_analysis_output()

        def update_search(*args):
            """probably get rid of this"""
            logger.debug(f'Updating search: {self.user_group_search.get()}')
            self._update_user_analysis_output()

        def clear_filter():
            self.user_group_search.set('')

        def update_user_policy_output():
            # Change to more output
            if self.chk_show_expanded.get():
                self.users_policy_table.set_display_columns(self.all_policy_columns)
            else:
                self.users_policy_table.set_display_columns(self.basic_policy_columns)
            logger.info(f'Updated display for expanded output: {self.chk_show_expanded.get()}')

        # Frame for selection and Search
        frm_user_selection = ttk.Frame(frm_user_top)
        frm_user_selection.grid_columnconfigure(0, weight=3)
        frm_user_selection.grid_columnconfigure(1, weight=7)
        frm_user_selection.grid(row=0, column=0, padx=5, pady=2, sticky='w')

        # User / Group Selection
        ttk.Label(frm_user_selection, text='Select Groups or Users').grid(row=0, column=0, padx=5, pady=2, sticky='w')

        # Selection Dropdown (users or groups)
        self.groups_option_var = tk.StringVar(value='GROUPS')
        self.groups_users_dropdown = ttk.OptionMenu(
            frm_user_selection,
            self.groups_option_var,
            self.groups_option_var.get(),
            *['GROUPS', 'USERS'],
            bootstyle='default',
            command=switch_groups_users_selection,
        )
        self.groups_users_dropdown.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frm_user_selection, text='Search').grid(row=1, column=0, padx=5, pady=2, sticky='w')

        # Search with trace
        self.user_group_search = tk.StringVar()
        ttk.Entry(frm_user_selection, textvariable=self.user_group_search, width=30).grid(
            row=1, column=1, padx=5, pady=2, sticky='w'
        )
        self.user_group_search.trace_add('write', update_search)
        self.btn_clear_groups_users = ttk.Button(frm_user_selection, text='Clear Filter', command=clear_filter)
        self.btn_clear_groups_users.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky='w')

        self.user_selected_groups = ttk.Label(frm_user_selection, text='Selected Groups: ')
        self.user_selected_groups.grid(row=3, column=0, columnspan=2, padx=5, pady=2, sticky='w')

        self.selected_groups_table = DataTable(
            frm_user_selection,
            columns=['Domain', 'Group'],
            display_columns=['Domain', 'Group'],
            data=[],
            column_widths={'Domain': 150, 'Group': 200},
            # font_size=10,
            # selection_callback=users_group_selection_callback,
            # multi_select=True,
        )
        self.selected_groups_table.grid(row=4, column=0, columnspan=2, padx=5, pady=2, sticky='w')

        # Table for Groups on the left
        # Groups Table
        self.users_groups_table = DataTable(
            frm_user_top,
            columns=GROUPS_COLUMNS,
            display_columns=GROUPS_COLUMNS,
            data=[],
            column_widths=self.groups_column_widths,
            # font_size=10,
            selection_callback=users_group_selection_callback,
            multi_select=True,
        )

        # Users Table
        self.users_users_table = DataTable(
            frm_user_top,
            columns=USERS_COLUMNS,
            display_columns=USERS_COLUMNS,
            data=[],
            column_widths=USERS_COLUMNS_WIDTHS,
            # font_size=10,
            selection_callback=users_user_selection_callback,
            multi_select=True,
        )

        # Users Page Policy Table
        self.user_label_count = ttk.Label(frm_users_policies, text='Policy Statements (Filtered): 0')
        self.user_label_count.grid(row=0, column=0, padx=5, pady=3, sticky='w')

        ttk.Separator(frm_users_policies, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)

        ttk.Checkbutton(
            frm_users_policies, text='Parsed Output', variable=self.chk_show_expanded, command=update_user_policy_output
        ).grid(row=0, column=2, padx=5, pady=3)

        # Policy Table
        self.users_policy_table = DataTable(
            frm_users_policies,
            columns=self.all_policy_columns,
            display_columns=self.basic_policy_columns,
            data=[],
            column_widths=self.policy_column_widths,
            # font_size=10,
            selection_callback=users_policy_selection_callback,
            multi_select=False,
        )
        self.users_policy_table.grid(row=1, column=0, columnspan=4, sticky='nsew')

    def create_tab_report(self):
        # Create tab with 20/80 rows
        tab_report = ttk.Frame(self.notebook)
        self.notebook.add(tab_report, text='Policy and DG\nReport')

        tab_report.grid_rowconfigure(0, weight=2)
        tab_report.grid_rowconfigure(1, weight=8)
        frm_report_top = ttk.Frame(tab_report)
        frm_report_top.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        # tab_report.rowconfigure(1, weight=1)
        # tab_report.columnconfigure(0, weight=1)

        # Top Section
        frm_report_buttons = ttk.Frame(frm_report_top)
        ttk.Label(frm_report_buttons, text='Text Highlight:').grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.highlight_entry_var = tk.StringVar()
        tk.Entry(frm_report_buttons, textvariable=self.highlight_entry_var).grid(row=0, column=1)

        # Export Button
        self.btn_export_report = ttk.Button(
            frm_report_buttons, text='Export Report', state=tk.DISABLED, command=self._export_report_to_txt
        )
        self.btn_export_report.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky='ew')
        frm_report_buttons.grid(row=0, column=0, sticky='e')

        # Bottom row of grid for tab
        frm_report = ttk.PanedWindow(tab_report, orient=tk.HORIZONTAL)
        frm_report.grid(row=1, column=0, sticky='nsew')

        # Bottom Section
        frm_dg_report = ttk.Frame(frm_report)
        frm_dg_report.grid(sticky='nsew')
        frm_dg_report.rowconfigure(1, weight=1)
        frm_dg_report.columnconfigure(0, weight=1)
        ttk.Label(frm_dg_report, text='Dynamic Groups', font=('TkFixedFont', 12, 'bold')).grid(
            row=0, column=0, padx=5, pady=5, sticky='w'
        )
        self.text_dg_report = tk.Text(frm_dg_report, wrap=tk.WORD, font=('TkFixedFont'), state=tk.DISABLED)
        self.text_dg_report.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        self.dg_scroll = ttk.Scrollbar(frm_dg_report, orient=tk.VERTICAL, command=self.text_dg_report.yview)
        self.dg_scroll.grid(row=1, column=1, sticky='ns')
        self.text_dg_report.config(yscrollcommand=self.dg_scroll.set)

        frm_policy_report = ttk.Frame(frm_report)
        frm_policy_report.grid(sticky='nsew')
        frm_policy_report.rowconfigure(1, weight=1)
        frm_policy_report.columnconfigure(0, weight=1)
        ttk.Label(frm_policy_report, text='Policies by Compartment', font=('TkFixedFont', 12, 'bold')).grid(
            row=0, column=0, padx=5, pady=5, sticky='w'
        )
        self.text_policy_report = tk.Text(frm_policy_report, wrap=tk.WORD, font=('TkFixedFont'), state=tk.DISABLED)
        self.text_policy_report.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        self.policy_scroll = ttk.Scrollbar(frm_policy_report, orient=tk.VERTICAL, command=self.text_policy_report.yview)
        self.policy_scroll.grid(row=1, column=1, sticky='ns')
        self.text_policy_report.config(yscrollcommand=self.policy_scroll.set)

        frm_report.add(frm_dg_report, weight=3)
        frm_report.add(frm_policy_report, weight=7)

        # Call the highlight functionality
        self.highlight_entry_var.trace_add('write', self._report_text_search)

    def create_tab_cross_tenancy(self):
        # Create tab with 30/60/10 rows (top label, tables, AI), 2 columns (tables)
        tab_cross_tenancy = ttk.Frame(self.notebook)
        tab_cross_tenancy.grid_rowconfigure(0, weight=3)
        tab_cross_tenancy.grid_rowconfigure(1, weight=6)
        tab_cross_tenancy.grid_rowconfigure(2, weight=1)
        tab_cross_tenancy.grid_columnconfigure(0, weight=1)
        tab_cross_tenancy.grid_columnconfigure(1, weight=6)
        self.notebook.add(tab_cross_tenancy, text='Cross Tenancy\nPolicies')

        # For now, a label on the left
        ttk.Label(
            tab_cross_tenancy,
            text='Select one or more rows to the right\nin order to narrow down cross-tenancy policies\n\nSort by clicking column headers',
            font=('TkFixedFont', 10, 'normal'),
        ).grid(row=0, column=0, padx=5, pady=5, sticky='w')

        def cross_tenancy_define_selection_callback(selected_rows: list[dict]) -> None:
            """When a Defined Alias is selected, update the policy statements below"""
            defined_aliases_for_filter = []
            # Make the Defined Alias list for all selected rows
            for row in selected_rows:
                logger.info(f"Selected row: {row.get('Defined Name')}")
                defined_aliases_for_filter.append(row.get('Defined Name'))
            logger.info(f'Defined Aliases for filter: {defined_aliases_for_filter}')

            # Call the filter
            filtered = self.policy_compartment_analysis.filter_cross_tenancy_policy_statements(
                defined_aliases_for_filter
            )

            logger.info(f'Cross-tenancy: {len(filtered)}')
            # Set them into the next table
            self.cross_tenancy_table.update_data(filtered)
            logger.info(f'Policies added to cross-tenancy policy table: {len(filtered)}')

        def cross_tenancy_policy_selection_callback(selected_rows: list[dict]) -> None:
            """When a Policy Statement is selected, update the policy statement below"""
            if len(selected_rows) == 1:
                selected_statement = selected_rows[0].get('Statement Text', '')
                logger.info(f'Selected policy statement: {selected_statement}')
                self.policy_analyze_statement_var.set(selected_statement)
            else:
                self.policy_analyze_statement_var.set('')

        def switch_tab_policy_analysis():
            self.notebook.select(tab_id=1)  # Policy Analysis tab
            # Set the policy name entry
            # self.policy_name_var.set(self.defined_aliases_table.get_row_data(row_index).get('Defined Name', ''))

        def defined_aliases_row_details(row_index: int) -> tk.Menu:
            menu = tk.Menu(tab_cross_tenancy, tearoff=0)
            menu.add_command(label=f'View Details (Row {row_index})', command=switch_tab_policy_analysis)

            return menu

        # Defined Aliases
        self.defined_aliases_table = DataTable(
            tab_cross_tenancy,
            columns=self.all_defined_alias_columns,
            display_columns=self.all_defined_alias_columns,
            data=[],
            column_widths=self.all_defined_alias_column_widths,
            selection_callback=cross_tenancy_define_selection_callback,
            row_context_menu_callback=defined_aliases_row_details,
            multi_select=True,
        )
        self.defined_aliases_table.grid(row=0, column=1, sticky='nsew')

        # Cross Tenancy Policies Table
        self.cross_tenancy_table = DataTable(
            tab_cross_tenancy,
            columns=self.all_cross_tenancy_columns,
            display_columns=self.all_cross_tenancy_columns,
            data=[],
            column_widths=self.all_cross_tenancy_column_widths,
            selection_callback=cross_tenancy_policy_selection_callback,
            multi_select=False,
        )
        self.cross_tenancy_table.grid(row=1, column=0, columnspan=2, sticky='nsew')

        # Frame for AI - take up both column
        frm_cross_tenancy_ai = tk.Frame(tab_cross_tenancy)
        frm_cross_tenancy_ai.grid(row=2, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        ttk.Label(frm_cross_tenancy_ai, text='Policy Statement to Analyze').grid(
            row=0, column=0, padx=5, pady=2, sticky='w'
        )
        # self.policy_analyze_statement_var = tk.StringVar()
        # Re-use the same variable as other tabs for policy statement
        self.rp_policy_analyze_statement_entry = tk.Entry(
            frm_cross_tenancy_ai, state=tk.NORMAL, width=100, textvariable=self.policy_analyze_statement_var
        )
        self.rp_policy_analyze_statement_entry.grid(row=0, column=1, padx=5, pady=2, sticky='ew')

        self.btn_ct_analyze_statement = ttk.Button(
            frm_cross_tenancy_ai,
            text='Analyze Statement',
            state=tk.DISABLED,
            command=lambda: self._analyze_policy_statment_ai(
                additional_context=' This policy statement is from an OCI cross-tenancy policy, add additional detail.'
            ),
        )
        self.btn_ct_analyze_statement.grid(row=0, column=2, padx=5, pady=2, sticky='ew')

    def create_tab_history(self):  # noqa: C901
        # Create tab with 2 equal rows
        tab_history = ttk.Frame(self.notebook)
        self.notebook.add(tab_history, text='Policy Set Compare/\nAudit History (W.I.P.)')
        tab_history.grid_rowconfigure(0, weight=2)  # JSON dropdowns
        tab_history.grid_rowconfigure(1, weight=2)  # Comparison Output
        tab_history.grid_rowconfigure(2, weight=2)  # Comparison Output
        tab_history.grid_rowconfigure(3, weight=2)  # Comparison Output
        tab_history.grid_rowconfigure(4, weight=2)  # Comparison Output
        tab_history.grid_columnconfigure(0, weight=1)
        tab_history.grid_columnconfigure(1, weight=1)

        # Top left and right allow selection of cache (need to include current)
        frm_history_left = ttk.Frame(tab_history)
        frm_history_left.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        frm_history_right = ttk.Frame(tab_history)
        frm_history_right.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)

        def load_audit_for_policy():
            logger.info('Load audit for policy:')

        def open_audit_link(event):
            """Open a link in the default web browser."""
            import webbrowser

            webbrowser.open_new('https://cloud.oracle.com/logging/audit')

        # History dropdown (include current)
        # comparison_list = [f'(Current)']
        # comparison_list.extend(self.cache_list)
        self.cache_comparison_list = []

        def autosize_columns(tree: ttk.Treeview, padding: int = 20):
            """Resize Treeview columns to fit the widest cell in each column."""
            style = ttk.Style(tree)
            tree_font = font.nametofont(style.lookup('Treeview', 'font', default='TkDefaultFont'))

            for col in tree['columns']:
                # Start with width of heading text
                max_width = tree_font.measure(text=tree.heading(col)['text'])

                # Check width of each cell in this column
                for item in tree.get_children():
                    cell_text = str(tree.set(item, col))
                    cell_width = tree_font.measure(cell_text)
                    max_width = max(max_width, cell_width)

                # Apply new width (+padding for spacing)
                tree.column(col, width=max_width + padding, stretch=False)

        def compare(*args):  # noqa: C901
            logger.info(f'Compare begin {self.left_version.get()} and {self.right_version.get()}')

            # Only do this if they are set
            if self.left_version.get() and self.right_version.get():
                left_json = load_cache_into_local_json(
                    cached_tenancy=self.policy_compartment_analysis.tenancy_name, cached_date=self.left_version.get()
                )
                right_json = load_cache_into_local_json(
                    cached_tenancy=self.policy_compartment_analysis.tenancy_name, cached_date=self.right_version.get()
                )
                logger.info(f'Loaded Left: {left_json.keys()} and Right: {right_json.keys()} into memory')

                # Actual Comparison
                diff_result = DeepDiff(left_json, right_json, ignore_order=True, exclude_paths='data_as_of')
                for change_type, changes in diff_result.items():
                    logger.debug(f'Diff: {change_type} Diff: {changes}')

            else:
                logger.info('No comparison yet')

            # Clean up tree
            self.comparison_tree.delete(*self.comparison_tree.get_children())

            # Put in new values
            for change_type, changes in diff_result.items():
                if 'added' in change_type:
                    parent_tag = 'added'
                elif 'removed' in change_type:
                    parent_tag = 'removed'
                elif 'changed' in change_type:
                    parent_tag = 'changed'
                else:
                    parent_tag = ''
                parent_id = self.comparison_tree.insert('', 'end', text=change_type, open=True, tags=(parent_tag,))
                for path, details in changes.items():
                    if isinstance(details, dict) and 'old_value' in details:
                        # this is a change
                        # # Ignore the data_as_of field
                        # old_value = details['old_value']
                        # new_value = details['new_value']

                        # # Attempt to make a dictionary because everything is essentially a list
                        # old_dict = {}
                        # new_dict = {}
                        # logger.info(f"Change details: {details}")
                        # logger.info(f"{type(old_value)} / {old_value}")
                        # logger.info(f"{type(new_value)} / {new_value}")
                        # try:
                        #     old_dict = json.loads(old_value)
                        #     new_dict = json.loads(new_value)
                        #     logger.info(f'Old value is {old_dict}')
                        #     logger.info(f'New value is {new_dict}')
                        # except Exception as e:
                        #     logger.debug(f'Error: {e}')
                        # if old_dict.get('Statement Text'):
                        #     node_text = f'Policy changed: {old_dict} → {new_dict}'
                        # else:
                        # node_text = f"Change Path: {path}:\n  {details['old_value']}\n  →\n  {details['new_value']}"
                        self.comparison_tree.insert(
                            parent_id, 'end', text=f'Change Path: {path}', values=(path,), tags=('changed')
                        )
                        self.comparison_tree.insert(
                            parent_id, 'end', text=details['old_value'], values=(path,), tags=('changed')
                        )
                        self.comparison_tree.insert(parent_id, 'end', text=' → ', values=(path,), tags=('changed'))
                        self.comparison_tree.insert(
                            parent_id, 'end', text=details['new_value'], values=(path,), tags=('changed')
                        )

                    elif 'added' in change_type:
                        # Check the JSON fields
                        if details.get('Statement Text'):
                            node_text = f"Policy added: {details.get('Policy Name')} // {details.get('Statement Text')}"
                        elif details.get('User Name'):
                            node_text = f"User added: {details.get('Domain Name')} // {details.get('User Name')}"
                        elif details.get('Group Name'):
                            node_text = f"Group added: {details.get('Domain Name')} // {details.get('Group Name')}"
                        elif details.get('DG Name'):
                            node_text = f"DG added: {details.get('DG Domain')} // {details.get('DG Name')}"
                        elif details.get('Defined Name'):
                            node_text = f"Define added: {details.get('Policy Name')} // {details.get('Defined Name')}"
                        else:
                            node_text = f'{path}: {details}'
                        self.comparison_tree.insert(parent_id, 'end', text=node_text, values=(path,), tags=('added'))

                    elif 'removed' in change_type:
                        # Check the JSON fields
                        if details.get('Statement Text'):
                            node_text = f"Policy statement removed: {details.get('Policy Name')} // {details.get('Statement Text')}"
                        elif details.get('User Name'):
                            node_text = f"User removed: {details.get('Domain Name')} // {details.get('User Name')}"
                        elif details.get('Group Name'):
                            node_text = f"Group removed: {details.get('Domain Name')} // {details.get('Group Name')}"
                        elif details.get('DG Name'):
                            node_text = f"DG removed: {details.get('Domain Name')} // {details.get('DG Name')}"
                        elif details.get('Defined Name'):
                            node_text = f"Define removed: {details.get('Policy Name')} // {details.get('Defined Name')}"
                        else:
                            node_text = f'{path}: {details}'
                        self.comparison_tree.insert(parent_id, 'end', text=node_text, values=(path,), tags=('removed'))
                        # tag = 'removed'
                    else:
                        node_text = f'{path}: {details}'
                        self.comparison_tree.insert(parent_id, 'end', text=node_text, values=(path,))

            if not self.show_diff_only.get():
                all_keys = set(left_json.keys()) | set(right_json.keys())
                for k in all_keys:
                    if f"root['{k}']" not in str(diff_result):
                        self.comparison_tree.insert('', 'end', text=f'Unchanged: {k}')

            # Resize
            autosize_columns(self.comparison_tree)

        # Dropdown menus for selecting JSON versions
        ttk.Label(frm_history_left, text='Left JSON Version:', bootstyle='info').grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.left_version = tk.StringVar(value='none')
        self.left_dropdown = ttk.Combobox(
            frm_history_left,
            textvariable=self.left_version,
            values=self.cache_comparison_list,
            state='readonly',
            bootstyle='info',
        )
        self.left_dropdown.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.left_dropdown.bind('<<ComboboxSelected>>', compare)

        ttk.Label(frm_history_right, text='Right JSON Version:', bootstyle='info').grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.right_version = tk.StringVar(value='none')
        self.right_dropdown = ttk.Combobox(
            frm_history_right,
            textvariable=self.right_version,
            values=self.cache_comparison_list,
            state='readonly',
            bootstyle='info',
        )
        self.right_dropdown.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.right_dropdown.bind('<<ComboboxSelected>>', compare)

        # Checkbox: show differences only
        self.show_diff_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            tab_history,
            text='Show differences only',
            variable=self.show_diff_only,
            bootstyle='round-toggle',
            command=compare,
        ).grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky='w')

        # Treeview Frame
        frm_comparison_tree = ttk.Frame(tab_history)
        frm_comparison_tree.grid(row=2, column=0, columnspan=2, sticky='nsew', padx=5, pady=5)
        frm_comparison_tree.grid_rowconfigure(0, weight=1)
        frm_comparison_tree.grid_columnconfigure(0, weight=1)

        # Add tree view to frame
        self.comparison_tree = ttk.Treeview(frm_comparison_tree, bootstyle='primary')
        self.comparison_tree.heading('#0', text='Differences')
        self.comparison_tree.column('#0', width=200, stretch=False)
        # self.comparison_tree.bind("<<TreeviewSelect>>", self.on_row_select)
        self.comparison_tree.grid(row=0, column=0, sticky='nsew')

        # Define tags with ttkbootstrap colors
        self.comparison_tree.tag_configure('added', foreground=self.style.colors.success)
        self.comparison_tree.tag_configure('removed', foreground=self.style.colors.danger)
        self.comparison_tree.tag_configure('changed', foreground=self.style.colors.warning)

        # Add scrollbars to Tree view
        vsb = ttk.Scrollbar(frm_comparison_tree, orient='vertical', command=self.comparison_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        hsb = ttk.Scrollbar(frm_comparison_tree, orient='horizontal', command=self.comparison_tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        self.comparison_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # Audit Button
        self.btn_show_audit_left = ttk.Button(
            tab_history,
            text='Show Audit for selected policy statement',
            state=tk.DISABLED,
            command=load_audit_for_policy,
        )
        self.btn_show_audit_left.grid(row=4, column=0, columnspan=2, padx=5, pady=3, sticky='ew')

        # Below everything, table
        ttk.Label(tab_history, text='Not Implemented').grid(row=5, column=0)
        # Use a Policy Table here with fields
        self.audit_policy_table = DataTable(
            tab_history,
            columns=AUDIT_COLUMNS,
            display_columns=AUDIT_COLUMNS,
            data=[],
            column_widths=AUDIT_COLUMN_WIDTHS,
            # font_size=10,
            # selection_callback=dg_policy_selection_callback,
            # multi_select=False,
        )
        self.audit_policy_table.grid(row=6, column=0, columnspan=2, sticky='nsew')

        # # Bottom Frame for History
        # self.text_compare_report = tk.Text(frm_history_bottom, wrap=tk.WORD, font=('TkFixedFont'), state=tk.DISABLED)
        # self.text_compare_report.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        # self.compare_scroll = ttk.Scrollbar(
        #     frm_history_bottom, orient=tk.VERTICAL, command=self.text_compare_report.yview
        # )
        # self.compare_scroll.grid(row=0, column=1, sticky='ns')
        # self.text_compare_report.config(yscrollcommand=self.compare_scroll.set)

        # # Open a Link
        # audit_link = ttk.Label(
        #     frm_history_top, text='Open OCI Audit (have logged in browser)', cursor='hand2', foreground='#0000EE'
        # )
        # audit_link.bind('<Button-1>', open_audit_link)
        # audit_link.grid(row=0, column=6, padx=5, pady=3, sticky='w')

    def create_tab_resource_reference(self):
        # Create tab
        tab_resource_ref = ttk.Frame(self.notebook)
        # 60/40
        tab_resource_ref.grid_rowconfigure(0, weight=2)
        tab_resource_ref.grid_rowconfigure(1, weight=8)
        tab_resource_ref.grid_columnconfigure(0, weight=1)
        self.notebook.add(tab_resource_ref, text='AI-based\nResource Reference')

        # Top Frame
        frm_reference_top = ttk.Frame(tab_resource_ref)
        frm_reference_top.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Bottom Frame
        frm_reference_bot = ttk.Frame(tab_resource_ref)
        frm_reference_bot.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Search frame
        self.search_frame = ttk.Frame(frm_reference_top)
        self.search_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(self.search_frame, text='Search (pipe-separated terms for OR):').pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.search_frame, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        clear_button = tk.Button(self.search_frame, text='Clear', command=lambda: self.search_var.set(''))
        clear_button.pack(side=tk.LEFT, padx=5)
        logger.debug('Search frame setup')

        # Set initial Column widths
        column_widths = {
            'Resource': 250,
            'Permissions': 300,
            'Families': 600,
        }
        # Use the Data Table here with fields
        self.reference_data_table = DataTable(
            frm_reference_bot,
            columns=self.resource_data_all_columns,
            display_columns=self.resource_data_all_columns,
            # data=self.resource_reference_data,
            data=[],
            column_widths=column_widths,
            font_size=10,
            # selection_callback=selection_callback,
            # multi_select=True,
        )
        # self.policy_table.grid(row=0, column=0, sticky='nsew')
        self.reference_data_table.pack(fill=tk.BOTH, expand=True)
        # self.search_var.trace_add('write', lambda *args: populate_tree(self.search_var.get()))

    def create_tab_policy_tree(self):
        """Create layout and sheet for Tab 1 with threaded loading, multiple row selection"""
        frm_policy_tree = ttk.Frame(self.notebook)
        self.notebook.add(frm_policy_tree, text='Policy Tree')

        # Configure grid layout
        frm_policy_tree.grid_rowconfigure(0, weight=1)
        frm_policy_tree.grid_columnconfigure(0, weight=1)

        # Top Frames
        control_frame = ttk.Frame(frm_policy_tree)
        control_frame.grid(row=0, column=0, sticky='e', padx=5, pady=3)
        # Bottom Frame
        tree_frame = ttk.Frame(frm_policy_tree)
        tree_frame.grid(row=1, column=0, sticky='nsew')

        display_fields = ['subject', 'verb', 'resource', 'location', 'conditions', 'comment']
        display_vars = {field: tk.BooleanVar(value=field in ['type', 'release']) for field in display_fields}
        ttk.Label(control_frame, text='Display:').pack(side='left', padx=2)

        for field in display_fields:
            chk = ttk.Checkbutton(control_frame, text=field, variable=display_vars[field])
            chk.pack(side='left', padx=2)

        self.policy_tree = ttk.Treeview(tree_frame, columns=('Name', 'Type', 'OCID'), show='tree headings')
        self.policy_tree.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

    # Based on checkboxes for AI and console, update the layout
    def _update_layout(self):
        """Dynamically adjust the layout based on console log and AI insights checkboxes."""
        console_enabled = self.option_console_var.get()
        ai_enabled = self.option_ai_var.get()

        # Remove existing placements
        self.notebook_frame.grid_forget()
        self.console_frame.grid_forget()
        self.ai_insights_frame.grid_forget()

        if console_enabled or ai_enabled:
            # Notebook takes top 2/3, console/AI takes bottom 1/3
            # self.main_frame.rowconfigure(0, weight=2)  # Notebook
            # self.main_frame.rowconfigure(1, weight=2)  # Console/AI
            # self.main_frame.grid_rowconfigure(0, weight=1)  # Notebook
            # self.main_frame.grid_rowconfigure(1, weight=2)  # Console/AI
            self.notebook_frame.grid(row=0, column=0, columnspan=2, sticky='nsew', padx=3, pady=3)

            if console_enabled and ai_enabled:
                # Split bottom third 50/50 left and right
                self.main_frame.grid_columnconfigure(0, weight=1)
                self.main_frame.grid_columnconfigure(1, weight=1)
                self.console_frame.grid(row=1, column=0, sticky='nsew', padx=3, pady=3)
                self.ai_insights_frame.grid(row=1, column=1, sticky='nsew', padx=3, pady=3)
            elif console_enabled:
                # Console takes full bottom third
                self.main_frame.grid_columnconfigure(0, weight=1)
                self.main_frame.grid_columnconfigure(1, weight=0)
                self.console_frame.grid(row=1, column=0, sticky='nsew', padx=3, pady=3)
            elif ai_enabled:
                # AI Insights takes full bottom third
                self.main_frame.grid_columnconfigure(0, weight=1)
                self.main_frame.grid_columnconfigure(1, weight=0)
                self.ai_insights_frame.grid(row=1, column=0, sticky='nsew', padx=3, pady=3)
        else:
            # Notebook takes full space
            self.main_frame.grid_rowconfigure(0, weight=1)
            self.main_frame.grid_rowconfigure(1, weight=0)
            self.main_frame.grid_columnconfigure(0, weight=1)
            self.main_frame.grid_columnconfigure(1, weight=0)
            self.notebook_frame.grid(row=0, column=0, columnspan=2, sticky='nsew')

        logger.debug('Layout updated: console=%s, ai_insights=%s', console_enabled, ai_enabled)

        # Update Console
        if console_enabled:
            if self.console_handler not in logger.handlers:
                logger.addHandler(self.console_handler)
                logger.info('Console enabled (in addition to default shell)')
        else:
            if self.console_handler in logger.handlers:
                logger.removeHandler(self.console_handler)
                logger.info('Console disabled (only default shell)')

        # AI enablement of buttons
        if ai_enabled:
            self.refresh_button.config(state=tk.NORMAL)
            self.btn_policy_analyze_statement.config(state=tk.NORMAL)
            self.btn_dg_analyze_statement.config(state=tk.NORMAL)
            self.btn_user_analyze_statement.config(state=tk.NORMAL)
            self.btn_ct_analyze_statement.config(state=tk.NORMAL)
            self.btn_rp_analyze_statement.config(state=tk.NORMAL)
        else:
            self.refresh_button.config(state=tk.DISABLED)
            self.btn_policy_analyze_statement.config(state=tk.DISABLED)
            self.btn_dg_analyze_statement.config(state=tk.DISABLED)
            self.btn_user_analyze_statement.config(state=tk.DISABLED)
            self.btn_ct_analyze_statement.config(state=tk.DISABLED)
            self.btn_rp_analyze_statement.config(state=tk.DISABLED)

    # Main Update functions - per tab
    def _update_policy_output(self, *args):
        # Tenancy Display
        if self.policy_compartment_analysis and self.policy_compartment_analysis.tenancy_name:
            self.tenancy_name_var.set(f'Tenancy:\n{self.policy_compartment_analysis.tenancy_name}')
        else:
            self.tenancy_name_var.set('Please Load a Tenancy')

        # Get filtered statements
        filtered = self.policy_compartment_analysis.filter_policy_statements(
            self.subject_filter_var.get(),
            self.verb_filter_var.get(),
            self.resource_filter_var.get(),
            self.location_filter_var.get(),
            'ROOTONLY' if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get(),
            self.condition_filter_var.get(),
            self.text_filter_var.get(),
            self.policy_filter_var.get(),
        )

        # Apply additional filters for output

        # Determine which rows to show based on checkboxes
        rows_to_show: list = [
            st
            for st in filtered
            if (
                self.chk_show_service.get()
                and st.get('Subject Type') == 'service'
                or self.chk_show_dynamic.get()
                and st.get('Subject Type') == 'dynamic-group'
                or self.chk_show_resource.get()
                and st.get('Subject Type') == 'resource'
                or self.chk_show_regular.get()
                and st.get('Subject Type') in ['group', 'any-user', 'any-group']
                or self.chk_show_invalid.get()
                and (not st.get('Valid') or not st.get('Parsed'))
            )
        ]
        self.label_policy_count.config(
            text=f'Statements (Filtered): {len(filtered)}\nStatements (Shown): {len(rows_to_show)}'
        )
        # Populate Data Table
        logger.debug(rows_to_show)
        self.policy_table.update_data(rows_to_show)
        logger.info(f'Populating policy data table with {len(rows_to_show)} statements')

        # Open up all columns if expanded is checked
        if self.chk_show_expanded.get():
            self.policy_table.set_display_columns(self.all_policy_columns)
            logger.debug('Setting policy table to expanded view with all columns')
        else:
            self.policy_table.set_display_columns(self.basic_policy_columns)
            logger.debug('Setting policy table to expanded view with basic columns')

    def _update_dg_output(self):
        if self.chk_show_instance_principals.get():
            self.dg_entry_type.delete(0, tk.END)
            self.dg_entry_type.insert(0, 'instance.compartment.id|instance.id')
        else:
            if self.dg_entry_type.get() == 'instance.compartment.id|instance.id':
                self.dg_entry_type.delete(0, tk.END)

        filtered = self.identity_domain_analysis.filter_dynamic_groups(
            self.dg_entry_domain.get() if self.dg_entry_domain.get() != '' else None,
            self.dg_entry_name.get() if self.dg_entry_name.get() != '' else None,
            self.dg_entry_type.get() if self.dg_entry_type.get() != '' else None,
            self.dg_entry_ocid.get() if self.dg_entry_ocid.get() != '' else None,
        )

        # Apply additional filter for In Use
        output_filtered = []
        for dg in filtered:
            if self.chk_show_not_in_use.get():
                if not dg.get('In Use'):
                    output_filtered.append(dg)
            else:
                output_filtered.append(dg)
        self.custom_data_dynamic_group.update_data(output_filtered)

        # If expanded, show all columns, else show a subset
        if self.chk_show_dg_ocid.get():
            self.custom_data_dynamic_group.set_display_columns(self.all_dg_columns)
            logger.info('Setting dynamic group table to expanded view with all columns')
        else:
            self.custom_data_dynamic_group.set_display_columns(self.basic_dg_columns)
            logger.info('Setting dynamic group table to basic view with key columns')

        # Update label with counts
        self.dg_label_count.config(
            text=f'Dynamic Groups (Total): {len(self.identity_domain_analysis.dynamic_groups)}\nDynamic Groups (Filtered): {len(output_filtered)}'
        )

    def _update_principals_sheets(self, *args):
        """Update sheets based on dropdown selections and dynamic group selection."""
        principals_style = self.principals_style_var.get()
        resource_type = self.resource_type_var.get()

        # Enable/disable Resource Type dropdown
        self.resource_type_dropdown.configure(state='normal')

        # Enable/disable Principals Style
        self.principals_style_dropdown.configure(state='normal')

        # Un-grid both sheets (re-grid in a sec)
        self.rp_dg_table.grid_forget()
        self.rp_policy_table.grid_forget()

        if principals_style == 'any-user':
            # Start with "any-user" style statement

            # Re-grid RP sheet
            self.rp_policy_table.grid(row=0, column=0, rowspan=2, sticky='nsew')
            logger.info('Added both DG and Policy tables to grid')

            # Don't care about Dynamic groups
            if resource_type == 'Any':
                logger.info('Case 1 - Any-User with no type specified')
                policies = self.policy_compartment_analysis.filter_policy_statements(
                    condition_filter='request.principal.type'
                )
                self.rp_policy_table.update_data(policies)
                logger.info(f'Filtered to {len(policies)} policies with any principal type')
                # self.principals_sheet_policies_instance.set_sheet_data(policies)
            else:
                logger.info(f'Case 2 - Any-User with type {resource_type} specified')
                condition_filter = f"request.principal.type='{resource_type}'"
                policies = self.policy_compartment_analysis.filter_policy_statements(condition_filter=condition_filter)
                self.rp_policy_table.update_data(policies)
                logger.info(f'Filtered to {len(policies)} policies with principal type {resource_type}')

        elif principals_style == 'Dynamic Group':
            logger.info('Case 3 - Dynamic Group')

            # Re-grid DG and RP sheet
            self.rp_dg_table.grid(row=0, column=0, sticky='nsew')
            self.rp_policy_table.grid(row=1, column=0, sticky='nsew')

            logger.info('Added both DG and Policy tables to grid')

            # Populate dynamic group sheet
            filtered_dynamic_groups = []
            # if type_principal == "Instance Principals":
            # filtered_dynamic_groups = identity_domain_analysis.filter_dynamic_groups(type_filter="instance.compartment.id")
            # elif type_principal == "Resource Principals":
            filtered_dynamic_groups = self.identity_domain_analysis.filter_dynamic_groups(
                type_filter='resource.type|resource.principal|resource.id'
            )

            self.rp_dg_table.update_data(filtered_dynamic_groups)

    def _update_user_analysis_output(self):
        # TODO: Compartment Analysis
        logger.info(f'Displaying: {self.groups_option_var.get()} with search of {self.user_group_search.get()}')
        # Grid the correct table
        if self.groups_option_var.get() == 'GROUPS':
            # Load the groups into grid and search
            self.users_users_table.grid_forget()
            self.users_groups_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Filter and display
            filtered_groups = self.identity_domain_analysis.filter_groups(name_filter=self.user_group_search.get())
            self.users_groups_table.update_data(filtered_groups)
            logger.info(f'Loaded {len(filtered_groups)} groups into table')
        elif self.groups_option_var.get() == 'USERS':
            self.users_groups_table.grid_forget()
            self.users_users_table.grid(row=0, column=1, rowspan=3, sticky='nsew')

            # Filter and display
            filtered_users = self.identity_domain_analysis.filter_users(name_filter=self.user_group_search.get())
            self.users_users_table.update_data(filtered_users)
            logger.info(f'Loaded {len(filtered_users)} users into data')
        else:
            logger.warning('Should not get here')

    def _update_user_analysis_policy_output(self, groups_for_filter, users_for_filter):
        logger.info('Getting policies for groups and users')

        if users_for_filter and len(users_for_filter) > 0:
            groups_for_filter = []
            # If we only have users, populate the groups for those users
            for user in users_for_filter:
                logger.info(f'Getting groups for user: {user}')
                groups_for_user = self.identity_domain_analysis.get_groups_for_user(user)
                groups_for_filter.extend(groups_for_user)

        # Take the list of groups, make a group filter, and update policy table
        logger.info(f'Searching for policies for groups: {groups_for_filter}')
        filtered_policies = self.policy_compartment_analysis.filter_policy_statements_by_groups(
            groups_filter=groups_for_filter
        )
        self.users_policy_table.update_data(filtered_policies)

        # Update the labels and table
        # Create a list of dict for the table
        selected_groups_for_table = []
        for dom, gr in groups_for_filter:
            selected_groups_for_table.append({'Domain': dom, 'Group': gr})
        # Update the group and policies table
        self.selected_groups_table.update_data(selected_groups_for_table)
        self.user_label_count.configure(text=f'Policy Statements (Filtered): {len(filtered_policies)}')

    def _update_report_output(self):
        self.text_dg_report.delete(1.0, tk.END)
        self.text_policy_report.delete(1.0, tk.END)
        sorted_dgs = sorted(
            self.identity_domain_analysis.dynamic_groups, key=lambda dg: (dg.get('Domain'), dg.get('DG Name'))
        )
        dg_text = 'Dynamic Groups Report\n====================\n'
        if not sorted_dgs:
            dg_text += 'No dynamic groups found.\n'
        else:
            for dg in sorted_dgs:
                dg_text += f'Domain: {dg.get("Domain")}\nName: {dg.get("DG Name")}\nMatching Rule: {dg.get("Matching Rule")}\nOCID: {dg.get("DG OCID")}\nCreated: {dg.get("Creation Time")}\nIn Use: {"Yes" if dg.get("In Use") else "No"}\n\n'
        self.text_dg_report.config(state=tk.NORMAL)
        self.text_dg_report.insert(tk.END, dg_text)
        self.text_dg_report.config(state=tk.DISABLED)

        logger.info(f'Compartments to sort: {len(self.policy_compartment_analysis.compartments)}')
        # Now update the policy report
        sorted_comps = sorted(self.policy_compartment_analysis.compartments, key=lambda x: x['hierarchy_path'])
        policy_text = 'Compartment and Policy Report\n============================\n'
        if not sorted_comps:
            policy_text += 'No compartments or policies found.\n'
        else:
            for comp in sorted_comps:
                policy_text += f'Compartment: {comp["hierarchy_path"]} (OCID: {comp["id"]})\n'
                statements = [
                    s
                    for s in self.policy_compartment_analysis.regular_statements
                    if s.get('Compartment OCID') == comp['id']
                ]
                if statements:
                    policy_dict = {}
                    for s in statements:
                        policy_name = s.get('Policy Name', 'Unknown Policy')
                        policy_ocid = s.get('Policy OCID', 'Unknown OCID')
                        if policy_name not in policy_dict:
                            policy_dict[policy_name] = {'ocid': policy_ocid, 'statements': []}
                        policy_dict[policy_name]['statements'].append(s.get('Statement Text', 'No Statement Text'))
                    for policy_name, data in sorted(policy_dict.items()):
                        policy_text += f'  Policy: {policy_name} (OCID: {data["ocid"]})\n'
                        for i, stmt in enumerate(data['statements'], 1):
                            policy_text += f'    {i}. {stmt}\n'
                else:
                    policy_text += '  No policies\n'
                policy_text += '\n'
        self.text_policy_report.config(state=tk.NORMAL)
        self.text_policy_report.insert(tk.END, policy_text)
        self.text_policy_report.config(state=tk.DISABLED)
        logger.info('Updated Policy/Dynamic Group Report tab')

    def _update_cross_tenancy_output(self):
        logger.info(f'Displaying: {len(self.policy_compartment_analysis.cross_tenancy_statements)} CT Statements')
        defined_aliases = self.policy_compartment_analysis.defined_aliases
        cross_tenancy_statements = self.policy_compartment_analysis.cross_tenancy_statements
        logger.debug(f'Defined Aliases: {defined_aliases}')
        logger.debug(f'Cross-Tenancy Statements: {cross_tenancy_statements}')

        self.defined_aliases_table.update_data(defined_aliases)
        self.cross_tenancy_table.update_data(cross_tenancy_statements)

    def _update_cache_comparison(self):
        # Make the list of caches available
        self.cache_comparison_list = []
        # Somehow separate the dates
        new_comparison_list = get_available_cache(tenancy_name=self.policy_compartment_analysis.tenancy_name)
        for item in new_comparison_list:
            tenancy, cache_date = item.split('\n')
            self.cache_comparison_list.append(cache_date)
        logger.info(f'Loaded {len(self.cache_comparison_list)} cache entries for comparison')
        self.left_dropdown['values'] = self.cache_comparison_list
        self.right_dropdown['values'] = self.cache_comparison_list

    # Calls into core to make updates
    def _run_dg_analysis(self):
        logger.info(
            f'Running Dynamic Group Analysis for {len(self.identity_domain_analysis.dynamic_groups)} DGs and {len(self.policy_compartment_analysis.regular_statements)} Policies'
        )
        start_time = datetime.datetime.now()
        # Send in the statemetns directly for DG processing.
        # TODO: Maybe the CT statements could have a dynamic group in them
        self.identity_domain_analysis.run_dg_in_use_analysis(
            policy_statements=self.policy_compartment_analysis.regular_statements
        )

        # Now set the data again, in case it changed
        self._update_dg_output()
        # self.dg_policy_table.update_data(self.identity_domain_analysis.dynamic_groups)
        total_time = (datetime.datetime.now() - start_time).total_seconds()
        logger.info(f'Ran DG Analysis in {total_time}s')

    def _compare_against_cache(self):
        selected_cache = self.cache_compare_var.get()
        ten, dat = selected_cache.split('\n')
        results = self.policy_compartment_analysis.compare_against_cache(cached_tenancy=ten, cached_date=dat)
        logger.info(f'Comparing current policies against cache: {selected_cache} - {results}')

        self.text_compare_report.config(state=tk.NORMAL)
        self.text_compare_report.delete(1.0, tk.END)
        if results:
            self.text_compare_report.insert(tk.END, f'Comparison Results for {selected_cache}:\n\n')
            self.text_compare_report.insert(tk.END, f'{results}\n')
        else:
            self.text_compare_report.insert(tk.END, 'No differences found or no cache available.\n')
        self.text_compare_report.config(state=tk.DISABLED)

    def _report_text_search(self, var_name, index, mode):
        if self.highlight_entry_var:
            search_pattern = self.highlight_entry_var.get()
            logger.debug(f'Search for {search_pattern} - {var_name}/{index}/{mode}')
            self.text_dg_report.tag_remove('found', '1.0', tk.END)
            self.text_policy_report.tag_remove('found', '1.0', tk.END)
            if self.highlight_entry_var.get() == '':
                return

            # If there was a highlight, do it for both
            start_index = '1.0'
            while True:
                pos = self.text_dg_report.search(search_pattern, start_index, tk.END, nocase=True)
                if not pos:
                    break
                end_index = f'{pos}+{len(search_pattern)}c'
                self.text_dg_report.tag_add('found', pos, end_index)
                start_index = end_index
            self.text_dg_report.tag_config('found', background='yellow')

            start_index = '1.0'
            while True:
                pos = self.text_policy_report.search(search_pattern, start_index, tk.END, nocase=True)
                if not pos:
                    break
                end_index = f'{pos}+{len(search_pattern)}c'
                self.text_policy_report.tag_add('found', pos, end_index)
                start_index = end_index
            self.text_policy_report.tag_config('found', background='yellow')

    def _update_history_cache_compare_dropdown(self):
        """Update the cache dropdown with available caches."""
        available_caches = get_available_cache(tenancy_name=self.policy_compartment_analysis.tenancy_name)
        if not available_caches:
            logger.warning('No caches found. Please load data first.')
            self.cache_var.set('No caches available')
            return

        self.cache_compare_list_dropdown['menu'].delete(0, tk.END)
        self.cache_compare_var.set('Select Cache')
        for cache in available_caches:
            self.cache_compare_list_dropdown['menu'].add_command(
                label=cache,
                command=lambda c=cache: self.cache_compare_var.set(c),
            )
        logger.info(f'Updated cache dropdown with {len(available_caches)} caches')

    # Exports
    def _export_policy_to_csv(self):
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
        if filepath:
            filtered = self.policy_compartment_analysis.filter_policy_statements(
                self.subject_filter_var.get(),
                self.verb_filter_var.get(),
                self.resource_filter_var.get(),
                self.location_filter_var.get(),
                self.hierarchy_filter_var.get(),
                self.condition_filter_var.get(),
                self.text_filter_var.get(),
                self.policy_filter_var.get(),
            )
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # writer.writerow(self.sheet_policies.headers())
                # Write header row
                writer.writerow(self.all_policy_columns)
                # Write data rows
                for row in filtered:
                    writer.writerow(row.values())
            logger.info(f'Exported {len(filtered)} policy statements to {filepath}')

    def _export_cache_to_json(self):
        filepath = tkfiledialog.asksaveasfile(filetypes=[('JSON Files', '*.json')])
        if filepath:
            logger.info(f'Writing file: {filepath.name}')
            save_combined_cache(
                policy_analysis=self.policy_compartment_analysis,
                domains_analysis=self.identity_domain_analysis,
                export_file=filepath,
            )
        logger.info(f'Wrote file {filepath.name}')

    def _import_cache_from_json(self):
        filepath = tkfiledialog.askopenfilename(filetypes=[('JSON Files', '*.json')])
        if filepath:
            self.progress_bar.grid()
            self.progress_bar_label.grid()
            self.progress_bar_label.config(text=f'Loading Policies and Compartments from file: {filepath}')
            self.progress_bar.start()
            try:
                # Load the file into local JSON
                with open(filepath, encoding='utf-8') as jsonfile:
                    loaded_json = json.load(jsonfile)
                    logger.debug(f'JSON Data: {loaded_json}')
                # Load the data into Data Classes
                success = load_cache_from_json(
                    loaded_json=loaded_json,
                    policy_analysis=self.policy_compartment_analysis,
                    domains_analysis=self.identity_domain_analysis,
                )
                if success:
                    # Update the last load time and enable UI elements
                    self.last_load_time = self.policy_compartment_analysis.data_as_of
                    logger.info(f'***Loaded cached data as of {self.last_load_time}')

                    # If the cache load was successful, update the last load time, enable UI elements, and update outputs
                    self.root.after(
                        0,
                        self._window_after_lambda,
                    )
                    logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
                else:
                    logger.warning('Failed to load from saved cache')

            except Exception as e:
                logger.error(f'Error importing policies from CSV: {e}')
            finally:
                self.root.after(
                    0,
                    lambda: (
                        self.progress_bar.stop(),
                        self.progress_bar.grid_remove(),
                        self.progress_bar_label.grid_remove(),
                    ),
                )

    # load_cache_from_json

    # def _export_user_to_csv(self):
    #     filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
    #     if filepath:
    #         with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
    #             writer = csv.writer(csvfile)
    #             writer.writerow(self.sheet_user_policies.headers())
    #             writer.writerows(self.sheet_user_policies.data)
    #         logger.info(f'Exported {len(self.sheet_user_policies.data)} user policy statements to {filepath}')

    def _export_report_to_txt(self):
        # Export the report to a text file
        import tkinter.filedialog as fd

        filepath = fd.asksaveasfilename(defaultextension='.txt', filetypes=[('Text Files', '*.txt')])
        if filepath:
            dg_content = self.text_dg_report.get(1.0, tk.END).strip()
            policy_content = self.text_policy_report.get(1.0, tk.END).strip()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(dg_content + '\n\n' + policy_content)
            logger.info(f'Exported report to {filepath}')

    # Define window after lambda (used to update UI after data load)
    def _window_after_lambda(self):
        # global last_load_time, last_error
        self.label_status_bar.config(text=f'{self.status_bar_text} | Loaded data as of {self.last_load_time}')
        [
            # Allow entry in some of the widgets (after load)
            e.config(state=tk.NORMAL)
            for e in [
                self.dg_entry_domain,
                self.dg_entry_name,
                self.dg_entry_type,
                self.dg_entry_ocid,
            ]
        ]
        [
            b.config(state=tk.NORMAL)
            for b in [
                self.btn_update,
                self.btn_clear,
                self.btn_export_policy,
                self.dg_btn_update,
                self.dg_btn_clear,
                self.btn_export_cache,
                self.dg_btn_analyze_dg,
                # self.btn_cache_compare,
                self.btn_export_report,
            ]
        ]
        # update_compartment_dropdown()
        self._update_policy_output()
        self._update_dg_output()
        self._update_principals_sheets()
        self._update_user_analysis_output()
        # self._update_user_analysis_combo()
        self._update_report_output()
        self._update_cross_tenancy_output()
        self._update_cache_comparison()
        # self._update_history_cache_compare_dropdown()

        # self.show_popup("Data loaded successfully!", side="right", duration=10000)
        # self.show_toast("Data loaded successfully!", side="right", duration=10000)

    # Process Load Buttons
    def _load_from_cache(self):
        """Load data from the selected cache."""
        global last_load_time, last_error
        self.progress_bar.grid()
        self.progress_bar_label.grid()
        self.progress_bar_label.config(text='Loading Policies and Compartments')
        self.progress_bar.start()

        # Grab cache details
        selected_cache = self.cache_var.get()
        ten, dat = selected_cache.split('\n')
        self.label_status_bar.config(text=f'Loading tenancy ({ten}) from cache dated {dat}...')

        def load_cache():
            """Load the cache in a separate thread to avoid blocking the UI."""
            global last_load_time, last_error
            try:
                logger.info('Kicking off cached tenancy load')

                profile = self.profile_var.get()
                use_ip = self.use_instance_principal_var.get()
                self.progress_bar_label.config(text='Loading Policies, Dynamic Groups and Compartments from cache')
                success = self.policy_compartment_analysis.initialize_client(use_ip, profile)
                if not success:
                    raise RuntimeError('Failed to initialize PolicyCompartmentAnalysis client for cache')
                success = self.identity_domain_analysis.initialize_client(use_ip, profile)
                if not success:
                    raise RuntimeError('Failed to initialize IdentityDomainAnalysis client for cache')
                success = load_combined_cache(
                    cached_tenancy=ten,
                    cached_date=dat,
                    policy_analysis=self.policy_compartment_analysis,
                    domains_analysis=self.identity_domain_analysis,
                )

                # Update the last load time and enable UI elements
                self.last_load_time = self.policy_compartment_analysis.data_as_of
                logger.info(f'***Loaded cached data as of {self.last_load_time}')

                # If the cache load was successful, update the last load time, enable UI elements, and update outputs
                self.root.after(
                    0,
                    self._window_after_lambda,
                )
                logger.info(f'Loaded cache for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
            except Exception as exc:
                last_error = str(exc)
                self.root.after(
                    0,
                    lambda: self.label_status_bar.config(text=self.status_bar_text),
                )
                logger.error(f'Cache load error: {last_error}')
            finally:
                self.root.after(
                    0,
                    lambda: (
                        self.progress_bar.stop(),
                        self.progress_bar.grid_remove(),
                        self.progress_bar_label.grid_remove(),
                    ),
                )

        # Start the cache loading in a separate thread
        logger.info(f'Loading cache for tenancy {ten} dated {dat}')
        Thread(target=load_cache, daemon=True).start()

    def _load_from_tenancy(self):
        """Load data from OCI tenancy."""
        """This function initializes the clients, loads policies, compartments, and dynamic groups, and updates the UI."""
        global last_load_time, last_error
        self.progress_bar.grid()
        self.progress_bar_label.grid()
        self.progress_bar_label.config(text='Loading Policies and Compartments')
        self.progress_bar.start()

        # Start Progress of Policy Load
        self.currently_loading = True
        self._update_progress_label()

        def load():
            global last_error, last_load_time
            try:
                logger.info('Kicking off tenancy load')
                profile = self.profile_var.get()
                use_ip = self.use_instance_principal_var.get()
                self.progress_bar_label.config(text=f'Initializing Clients for {profile}')
                success = self.policy_compartment_analysis.initialize_client(
                    use_instance_principal=use_ip, recursive=self.recursive_load_var.get(), profile=profile
                )
                if not success:
                    raise RuntimeError('Failed to initialize PolicyCompartmentAnalysis client')
                success = self.identity_domain_analysis.initialize_client(use_ip, profile)
                if not success:
                    raise RuntimeError('Failed to initialize IdentityDomainAnalysis client')
                self.progress_bar_label.config(text='Loading Policies and Compartments')
                success = self.policy_compartment_analysis.load_policies_and_compartments()
                self.label_status_bar.config(
                    text=f'Loading data from tenancy {self.policy_compartment_analysis.tenancy_name}...'
                )

                if not success:
                    raise RuntimeError('Failed to load policies and compartments')
                self.progress_bar_label.config(text='Loading Dynamic Groups')
                success = self.identity_domain_analysis.load_all_dynamic_groups()
                if not success:
                    raise RuntimeError('Failed to load dynamic groups')
                self.progress_bar_label.config(text='Loading Identity Domains and Users')
                success = self.identity_domain_analysis.load_domains_groups_users()
                if not success:
                    raise RuntimeError('Failed to load identity domains and users')
                self.progress_bar_label.config(text='Saving to Cache')
                save_combined_cache(
                    policy_analysis=self.policy_compartment_analysis, domains_analysis=self.identity_domain_analysis
                )

                # Update the last load time and enable UI elements
                self.last_load_time = self.policy_compartment_analysis.data_as_of
                logger.info(f'***Loaded tenancy data as of {self.last_load_time}')
                self.root.after(
                    0,
                    self._window_after_lambda,
                )
                # logger.info(f'Loaded data for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
            except Exception as exc:
                last_error = str(exc)
                self.root.after(
                    0,
                    lambda: self.label_status_bar.config(text=f'{self.status_bar_text} | Load Error: {last_error}'),
                )
                logger.error(f'Data load error: {last_error}')
            finally:
                self.currently_loading = False
                self.root.after(
                    0,
                    lambda: (
                        self.progress_bar.stop(),
                        self.progress_bar.grid_remove(),
                        self.progress_bar_label.grid_remove(),
                    ),
                )

        # Start the data loading in a separate thread to avoid blocking the UI
        Thread(target=load, daemon=True).start()

    # Set the results from the AI call
    def _analyze_policy_statment_ai(self, additional_context: str = ''):
        logger.info(f'Call Analyze for: {self.policy_analyze_statement_entry.get()}')
        self.ai_insights_response_html.set_html(
            f'<p>Analyzing statement <code style="font-family: "Courier New", Courier, monospace;">{self.policy_analyze_statement_entry.get()}</code>...</p>'
        )
        ai_thread = Thread(
            target=self.ai.analyze_policy_statement,
            args=(self.policy_analyze_statement_entry.get(), self.result_queue, False, additional_context),
            daemon=True,
            name='AI-Analyze-Statement-Thread',
        )
        ai_thread.start()

    def _update_response(self, result):
        logger.info(f'Setting Result from AI into Response area: {result[:-100]}')
        # Clean and create Markdown as HTML
        cleaned_result = clean_markdown(result)
        html_content = markdown.markdown(cleaned_result, extensions=['tables', 'fenced_code'])

        # Set in the widget
        # TODO - Sanitize HTML?
        self.ai_insights_response_html.set_html(html_content)

    # Timer-based continous or periodic updates
    def _update_progress_label(self):
        if self.currently_loading:
            self.progress_bar_label.config(
                text=f'Policies Loaded: {len(self.policy_compartment_analysis.regular_statements)}'
            )
            self.root.after(1000, self._update_progress_label)

    def _update_status_bar_text(self):
        """every 2 sec update the text for the status bar"""
        self.status_bar_text = f'© 2025 Andrew Gregory  |  OCI Policy & Dynamic Group Analysis v{__version__}  '
        if (
            not self.policy_compartment_analysis
            or not self.identity_domain_analysis
            or not self.policy_compartment_analysis.data_as_of
        ):
            self.status_bar_text += '| Not initialized'
        elif self.currently_loading:
            self.status_bar_text += f'| Loading ({len(self.policy_compartment_analysis.regular_statements)})'
        else:
            self.status_bar_text += f'| Policies as of {self.policy_compartment_analysis.data_as_of}'

        if self.verbose:
            python_version = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
            oci_version = oci.__version__
            tkinter_version = tk.Tcl().eval('info patchlevel')
            self.status_bar_text += f'| Python: {python_version} | OCI: {oci_version} | Tkinter: {tkinter_version} '
        # logger.debug(f'Status: {self.status_bar_text}')
        self.label_status_bar.config(text=self.status_bar_text)
        self.root.after(2000, self._update_status_bar_text)

    def _update_ai_insights_response(self):
        try:
            while True:
                # result, policy_text, response_type = self.result_queue.get_nowait()
                result = self.result_queue.get_nowait()
                # self._update_response(result, policy_text, response_type)
                self._update_response(result)
        except queue.Empty:
            pass
        self.root.after(100, self._update_ai_insights_response)

    # Options Load and Save
    def load_options(self):
        # Load options from Cache directory
        options = {}

        # Try to load - if not there, no big deal
        options_file = CACHE_DIR / 'options.json'
        if options_file.exists():
            try:
                with open(options_file, encoding='utf-8') as f:
                    options = json.load(f)
                logger.info(f'Loaded options from {options_file}')
            except Exception as exc:
                logger.error(f'Error loading options from {options_file}: {exc}')
        else:
            logger.info(f'No options file found at {options_file}, using defaults.')

        # Define variables
        self.use_instance_principal_var = tk.BooleanVar(value=False)
        self.recursive_load_var = tk.BooleanVar(value=options.get('recursion', True))
        self.profile_var = tk.StringVar(value='DEFAULT')
        self.font_size_var = tk.IntVar()

        # Load profiles from ~/.oci/config
        self.profile_list = ['DEFAULT']
        try:
            # TODO - Check Env OCI_CLI_CONFIG_FILE
            with open(Path.home() / '.oci' / 'config') as fp:
                self.profile_list = [line[1:-2] for line in fp if line.startswith('[') and line.endswith(']\n')]
        except FileNotFoundError:
            logger.warning('OCI config file not found')
            self.profile_list = ['NONE']
            self.use_instance_principal_var.set(True)

        # Start loading options
        # self.font.size = options.get("font-size", 10)
        self.profile_var.set(options.get('profile', 'DEFAULT'))
        # logger.info(f"Setting font: {self.font}")
        logger.info(f'Setting Recursive: {self.recursive_load_var.get()}')
        logger.info(f'Setting Instance Principal: {self.use_instance_principal_var.get()}')
        logger.info(f'Setting Profile: {self.profile_var.get()}')

    def persist_options(self):
        # Save all options
        # with blah as
        # write json
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        options_file = CACHE_DIR / 'options.json'
        options = {
            # "font-size": self.font.size,
            'recursion': self.recursive_load_var.get(),
            'instance_principal': self.use_instance_principal_var.get(),
            'profile': self.profile_var.get(),
        }
        # Write out options
        try:
            with open(options_file, 'w', encoding='utf-8') as f:
                json.dump(options, f, indent=4)
            logger.info(f'Wrote options to {options_file}')
        except Exception as exc:
            logger.error(f'Error writing options to {options_file}: {exc}')
        pass


### Main Code Helpers


def parse_args():
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    return parser.parse_args()


########################
# UI Elements
def main():
    # Parse command line arguments
    args = parse_args()

    # Create Tkinter root and NotebookApp with parsed arguments
    window = ttk.Window(themename='litera')
    window.geometry('1280x900')
    OCIPolicyDGViewer(window, verbose=args.verbose)
    # logger.info(f'Starting OCI Policy and Dynamic Group Viewer with profile: {type(app)}')
    window.mainloop()
    # logger.info('OCI Policy and Dynamic Group Viewer has exited.')


# Start Program
if __name__ == '__main__':
    main()
