#!/usr/bin/env python3
##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# oci_policy_dg_viewer.py
#
# @author: Andrew Gregory (original), enhanced by Grok
#
# Supports Python 3.13 and above
#
# coding: utf-8
##########################################################################

# Standard library imports
import argparse
import csv
import datetime
import logging
import queue
import sys
import time
import tkinter as tk
import tkinter.filedialog as tkfiledialog
from pathlib import Path
from queue import Queue
from threading import Thread

# Third-party imports
import oci
import tksheet
import ttkbootstrap as ttk

from oci_policy_dg_viewer._version import __version__
from oci_policy_dg_viewer.oci_policy_dg_core import (
    IdentityDomainsAnalysis,
    PolicyCompartmentAnalysis,
    get_available_cache,
    load_combined_cache,
    save_combined_cache,
)

# Constants
THREADS = 8

# Global variables
last_error = ''

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
logger = logging.getLogger('oci-policy-dg-viewer')
logger.warning(f'Version {__version__}')


# Classes for TKSheet Extensions
class Tooltip:
    """A class to create tooltips for Tkinter widgets."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind('<Enter>', self.show_tooltip)
        self.widget.bind('<Leave>', self.hide_tooltip)

    def show_tooltip(self, event):
        """Show the tooltip window."""
        if self.tip_window or not self.text:
            return
        x, y = self.widget.winfo_pointerxy()
        self.tip_window = tk.Toplevel(self.widget)
        self.tip_window.wm_overrideredirect(True)
        self.tip_window.wm_geometry(f'+{x + 10}+{y + 10}')
        label = tk.Label(
            self.tip_window, text=self.text, background='#ffffe0', relief='solid', borderwidth=1, font=('Arial', 10)
        )
        label.pack()

    def hide_tooltip(self, event):
        """Hide the tooltip window."""
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class SortableSheetMixin:
    def enable_sorting(self):
        """Enable sorting functionality for a tksheet instance."""
        self.sort_reverse = {i: False for i in range(len(self.headers()))}
        # Use both Button-1 and ButtonRelease-1 for better macOS compatibility
        self.bind('<Button-1>', self._handle_header_click)
        self.bind('<ButtonRelease-1>', self._handle_header_click)
        logging.debug('Sorting bindings enabled for sheet')

    def _handle_header_click(self, event):
        """Handle column header click to sort the sheet."""
        region = self.identify_region(event)
        logging.debug(f'Click event: type={event.type}, region={region}, x={event.x}, y={event.y}')
        if region == 'header':
            col = self.identify_column(event)
            logging.debug(f'Column {col} clicked')
            self.sort_reverse[col] = not self.sort_reverse[col]
            self._sort_column(col)
        else:
            logging.debug(f'Non-header click ignored: region={region}')

    def _sort_column(self, col):
        """Sort the sheet by the specified column."""
        data = self.get_sheet_data()
        reverse = self.sort_reverse[col]
        sorted_data = sorted(data, key=lambda x: x[col], reverse=reverse)
        self.set_sheet_data(sorted_data)
        self.refresh()
        logging.debug(f'Sheet sorted by column {col}, reverse={reverse}')


class SortableSheet(tksheet.Sheet, SortableSheetMixin):
    """A tksheet class with sortable columns."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        # Apply solar theme styling to tksheet
        # Apply solar theme styling using set_options (compatible with older tksheet versions)
        # self.set_options(
        #     header_bg="#ff6b6b",  # Reddish-orange
        #     table_bg="#2c2c2c",   # Dark gray
        #     index_bg="#ff8c00",   # Orange
        #     header_fg="#f5f6f5",  # Light text
        #     table_fg="#f5f6f5",
        #     index_fg="#f5f6f5",
        #     table_selected_cells_bg="#e63939",  # Darker red
        #     table_selected_rows_bg="#e63939",
        #     table_selected_columns_bg="#e63939",
        #     font=("Courier New", 10, 'normal')
        # )
        """self.header_bg("#ff6b6b")  # Reddish-orange for headers
        self.header_fg("#f5f6f5")  # Light text
        self.table_bg("#2c2c2c")   # Dark background
        self.table_fg("#f5f6f5")   # Light text
        self.index_bg("#ff8c00")   # Orange for row indices
        self.index_fg("#f5f6f5")   # Light text
        self.table_selected_cells_bg("#e63939")  # Darker red for selected cells
        self.table_selected_rows_bg("#e63939")   # Darker red for selected rows
        self.table_selected_columns_bg("#e63939")  # Darker red for selected columns
        self.set_options(font=("Arial", 10))
        """
        self.set_options(font=('Courier New', 10, 'normal'))
        self.set_options(header_font=('Courier New', 11, 'bold'))
        self.set_options(index_font=('Courier New', 11, 'bold'))
        self.enable_sorting()


class OCIPolicyDGViewer:
    def __init__(self, root, verbose=False):
        self.root = root
        self.root.title('OCI Policy and Dynamic Group Viewer')
        # Track last selected row for Shift+click range selection
        self.last_selected_row = None

        # State
        # sheet_cross_tenancy_define_search_order = False
        # sheet_cross_tenancy_policies_search_order = False

        # Centralized tooltip text
        self.tooltips = {
            'tab1_sheet': 'Click column headers to sort. Ctrl+click for multiple rows, Shift+click for range.',
            'tab1_label': 'Student data table with sortable columns and multi-row selection.',
            'tab1_progress': 'Data is loaded in 2-week chunks for a year.',
            'tab2_sheet': 'Click column headers to sort cities data.',
            'tab2_label': 'City population and area data table.',
            'tab3_sheet': 'Click column headers to sort products data.',
            'tab3_label': 'Product inventory data table.',
        }

        # Queue for thread communication
        self.queue = Queue()

        # Create Top-level menu - grid row 0
        self.create_top_menu(verbose)

        # Create notebook - grid row 1
        self.notebook = ttk.Notebook(root, bootstyle='danger')
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Configure root grid to expand notebook
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Create tabs
        self.create_tab_policy()  # Regular Policy Statements
        self.create_tab_dynamic_groups()  # Dynamic Groups
        self.create_tab_resource_principals()  # Resource Principals
        self.create_tab_user_analysis()  # User Analysis
        self.create_tab_cross_tenancy()  # Cross Tenancy
        self.create_tab_report()  # Report
        self.create_tab_history()  # History
        # self.tab_sample() # Grok-based

        # Grid the notebook once tabs are created
        self.notebook.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

        # Initialize analysis classes
        self.policy_compartment_analysis = PolicyCompartmentAnalysis(verbose)
        self.identity_domain_analysis = IdentityDomainsAnalysis(verbose)

    def create_top_menu(self, verbose=False):
        """Create the top-level menu with File and Help options."""
        frm_init = ttk.Frame(self.root, bootstyle='light')  # type: ignore
        frm_init.grid(row=0, column=0, sticky='ew', padx=5, pady=5)

        # Instance Principal checkbox
        self.use_instance_principal = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_init,
            text='Instance Principal',
            variable=self.use_instance_principal,
            command=self._toggle_profile_dropdown,
        ).grid(row=0, column=0, padx=5, pady=3)

        # Profile selection
        profile_list = ['DEFAULT']
        try:
            # TODO - Check Env OCI_CLI_CONFIG_FILE
            with open(Path.home() / '.oci' / 'config') as fp:
                profile_list = [line[1:-2] for line in fp if line.startswith('[') and line.endswith(']\n')]
        except FileNotFoundError:
            logger.warning('OCI config file not found')
            profile_list = ['NONE']
            self.use_instance_principal.set(True)

        self.profile_var = tk.StringVar(value=profile_list[0])
        self.label_profile = ttk.Label(frm_init, text='Profile:')
        self.label_profile.grid(row=0, column=1, padx=5, pady=3)
        self.input_profile = ttk.OptionMenu(frm_init, self.profile_var, self.profile_var.get(), *profile_list)
        self.input_profile.config(width=20)
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)

        # Get available cached copies
        self.label_cache = ttk.Label(frm_init, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.cache_list = get_available_cache(None)
        self.cache_var = tk.StringVar(value=self.cache_list[0] if len(self.cache_list) > 0 else 'No Cache Available')
        self.cache_list_dropdown = ttk.OptionMenu(
            frm_init, self.cache_var, self.cache_var.get(), *self.cache_list, bootstyle='default'
        )
        self.cache_list_dropdown.config(width=20)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)

        # If the instance principal was selected, disable this
        if self.use_instance_principal.get():
            self.input_profile.config(state=tk.DISABLED)

        # Load buttons
        self.btn_load_tenancy = ttk.Button(
            frm_init, text='Load from Tenancy', command=self._load_from_tenancy, width=20, bootstyle='default'
        )
        self.btn_load_tenancy.grid(row=0, column=3, padx=5, pady=3)
        self.btn_load_cache = ttk.Button(
            frm_init, text='Load from Cache', command=self._load_from_cache, width=20, bootstyle='default'
        )
        self.btn_load_cache.grid(row=1, column=3, padx=5, pady=3)

        # Font Size Options
        menubutton = ttk.Menubutton(frm_init, text='Display Options', bootstyle='default')
        menu = tk.Menu(menubutton, tearoff=False)
        menubutton['menu'] = menu

        def on_font_size_select(new_font_size):
            self.sheet_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_policies.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_dynamic_group.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_dynamic_group.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_user_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_user_policies.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_cross_tenancy_define.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_cross_tenancy_define.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_cross_tenancy_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_cross_tenancy_policies.set_all_cell_sizes_to_text(redraw=True)
            logger.info(f'Changing font size globally to {self.font_size_var.get()}/{new_font_size}')

        # Add a Tooltip checkbutton
        self.option_tooltips_var = tk.IntVar()
        menu.add_checkbutton(
            label='Enable Tooltips',
            variable=self.option_tooltips_var,
            command=lambda: print(f'Tooltips enabled: {self.option_tooltips_var.get()}'),
        )
        menu.add_separator()

        # Add a submenu
        submenu = tk.Menu(menu, tearoff=False)
        submenu.add_command(label='Small', command=lambda: on_font_size_select(10))
        submenu.add_command(label='Large', command=lambda: on_font_size_select(12))
        menu.add_cascade(label='Font size...', menu=submenu)
        menubutton.grid(row=0, column=9, padx=5, pady=3)
        self.font_size_var = tk.StringVar()

        # Progress bar and label
        self.progress_bar_label = ttk.Label(frm_init, text='')
        self.progress_bar_label.grid(row=0, column=7, padx=5, pady=3)
        self.progress_bar_label.grid_remove()
        self.progress_bar = ttk.Progressbar(frm_init, mode='indeterminate', length=100)
        self.progress_bar.grid(row=0, column=8, padx=5, pady=3, sticky='e')
        self.progress_bar.grid_remove()

        # Status bar
        frm_status = ttk.Frame(self.root, style='TFrame')
        frm_status.grid(row=2, column=0, sticky='ew', padx=5, pady=2)
        frm_status.columnconfigure(0, weight=1)
        python_version = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
        oci_version = oci.__version__
        tkinter_version = tk.Tcl().eval('info patchlevel')
        tksheet_version = tksheet.__version__
        # last_load_time = 'Not Initialized'
        self.status_bar_text = f'© 2025 Andrew Gregory    |    OCI Policy & Dynamic Group Analysis v{__version__}'
        if verbose:
            self.status_bar_text += f'    |    Python: {python_version}    |    OCI: {oci_version}    |    Tkinter: {tkinter_version}    |    tksheet: {tksheet_version}    |'

        self.label_status_bar = ttk.Label(
            frm_status,
            text=self.status_bar_text,
            anchor='w',
        )
        self.label_status_bar.grid(row=0, column=0, sticky='ew')

    def create_tab_policy(self):
        # Tab and add to Notebook
        tab_policy = ttk.Frame(self.notebook)  # type: ignore
        self.notebook.add(tab_policy, text='Regular Policy\nStatements')
        tab_policy.grid_rowconfigure(1, weight=1)
        tab_policy.grid_columnconfigure(0, weight=1)

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

        # Within the policy filter frame, create the filter fields and buttons
        frm_subj = ttk.Frame(frm_policy_filter)
        ttk.Label(frm_policy_filter, text='Subject').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        self.entry_subj = tk.Entry(frm_subj, state=tk.DISABLED, width=20)
        self.entry_subj.grid(row=0, column=0, padx=2, sticky='ew')
        self.use_subject_any = tk.BooleanVar()
        ttk.Checkbutton(
            frm_subj, text='Any-User/Group', variable=self.use_subject_any, command=self._toggle_any_subject
        ).grid(row=0, column=1, padx=2)
        frm_subj.grid(row=1, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Verb').grid(row=1, column=2, padx=5, pady=2, sticky='w')
        self.entry_verb = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
        self.entry_verb.grid(row=1, column=3, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Resource').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.entry_res = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
        self.entry_res.grid(row=2, column=1, padx=5, pady=2, sticky='ew')

        frm_loc = ttk.Frame(frm_policy_filter)
        ttk.Label(frm_policy_filter, text='Location').grid(row=2, column=2, padx=5, pady=2, sticky='w')
        self.entry_loc = tk.Entry(frm_loc, state=tk.DISABLED, width=20)
        self.entry_loc.grid(row=0, column=0, padx=2, sticky='ew')
        self.location_filter_tenancy = tk.BooleanVar()
        ttk.Checkbutton(
            frm_loc, text='Tenancy', variable=self.location_filter_tenancy, command=self._toggle_location_tenancy
        ).grid(row=0, column=1, padx=2)
        frm_loc.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        frm_hierarchy = ttk.Frame(frm_policy_filter)
        ttk.Label(frm_policy_filter, text='Hierarchy').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        self.entry_hierarchy = tk.Entry(frm_hierarchy, state=tk.DISABLED, width=20)
        self.entry_hierarchy.grid(row=0, column=0, padx=2, sticky='ew')
        self.hierarchy_filter_root = tk.BooleanVar()
        ttk.Checkbutton(
            frm_hierarchy, text='Root', variable=self.hierarchy_filter_root, command=self._toggle_hierarchy_root
        ).grid(row=0, column=1, padx=2)
        frm_hierarchy.grid(row=3, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Condition').grid(row=3, column=2, padx=5, pady=2, sticky='w')
        self.entry_condition = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
        self.entry_condition.grid(row=3, column=3, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Text').grid(row=4, column=0, padx=5, pady=2, sticky='w')
        self.entry_text = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
        self.entry_text.grid(row=4, column=1, padx=5, pady=2, sticky='ew')

        ttk.Label(frm_policy_filter, text='Policy Name').grid(row=4, column=2, padx=5, pady=2, sticky='w')
        self.entry_policy = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
        self.entry_policy.grid(row=4, column=3, padx=5, pady=2, sticky='ew')

        frm_policy_buttons = ttk.Frame(frm_policy_filter)
        self.btn_update = ttk.Button(
            frm_policy_buttons, text='Update', state=tk.DISABLED, command=self._update_policy_output
        )
        self.btn_update.grid(row=0, column=0, padx=5, pady=2, sticky='ew')
        self.btn_clear = ttk.Button(
            frm_policy_buttons, text='Clear', state=tk.DISABLED, command=self._clear_policy_filters
        )
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
        self.label_policy_count = ttk.Label(frm_policy_output, text='Statements (Filtered): 0')
        self.label_policy_count.grid(row=0, column=0, padx=5, pady=3, sticky='w')
        # Add a tooltip
        Tooltip(self.label_policy_count, 'This label shows the number of filtered statements and those displayed.')

        self.chk_show_service = tk.BooleanVar()
        self.chk_show_dynamic = tk.BooleanVar()
        self.chk_show_resource = tk.BooleanVar()
        self.chk_show_invalid = tk.BooleanVar()
        self.chk_show_regular = tk.BooleanVar(value=True)
        self.chk_show_expanded = tk.BooleanVar()
        ttk.Separator(frm_policy_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(frm_policy_output, text='Statement Type\nto display:').grid(row=0, column=2, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Service', variable=self.chk_show_service, command=self._update_policy_output
        ).grid(row=0, column=3, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Dynamic Group', variable=self.chk_show_dynamic, command=self._update_policy_output
        ).grid(row=0, column=4, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Resource', variable=self.chk_show_resource, command=self._update_policy_output
        ).grid(row=0, column=5, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Regular', variable=self.chk_show_regular, command=self._update_policy_output
        ).grid(row=0, column=6, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output, text='Invalid', variable=self.chk_show_invalid, command=self._update_policy_output
        ).grid(row=0, column=7, padx=5, pady=3)
        ttk.Checkbutton(
            frm_policy_output,
            text='Expanded Output',
            variable=self.chk_show_expanded,
            command=self._update_policy_output,
        ).grid(row=0, column=8, padx=5, pady=3)

        # Frame for policy sheet - row 1 of tab_policy
        frm_policy_sheet = ttk.Frame(tab_policy)
        frm_policy_sheet.grid(row=1, column=0, sticky='nsew')
        frm_policy_sheet.rowconfigure(0, weight=1)
        frm_policy_sheet.columnconfigure(0, weight=1)
        self.sheet_policies = SortableSheet(
            frm_policy_sheet,
            font=('Courier New', 10, 'normal'),
            header_font=('Courier New', 11, 'bold'),
            index_font=('Courier New', 11, 'bold'),
            headers=[
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
            ],
            auto_resize_columns=200,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )

        self.sheet_policies.grid(row=0, column=0, sticky='nsew')
        self.sheet_policies.enable_bindings('single_select', 'column_width_resize', 'row_select', 'copy', 'rc_select')

        # Label below the sheet
        self.label_sheet_status = ttk.Label(frm_policy_sheet, text='No policies loaded yet.')
        self.label_sheet_status.grid(row=1, column=0, sticky='ew', padx=5, pady=3)
        Tooltip(self.label_sheet_status, 'This label will update with the status of the sheet.')

    def create_tab_dynamic_groups(self):
        # Tab creation for Dynamic Groups
        tab_dg = ttk.Frame(self.notebook)
        self.notebook.add(tab_dg, text='Dynamic Groups / \nInstance Principals')
        tab_dg.grid_rowconfigure(0, weight=1)
        tab_dg.grid_columnconfigure(0, weight=1)

        # Top of frame
        frm_dg_filter = ttk.Frame(tab_dg)
        frm_dg_filter.grid(row=0, column=0, sticky='w', padx=5, pady=5)
        frm_dg_filter.columnconfigure([1, 3], weight=1)
        ttk.Label(frm_dg_filter, text='Filters (| for OR, AND between fields)').grid(
            row=0, column=0, columnspan=5, pady=2, sticky='ew'
        )
        ttk.Label(frm_dg_filter, text='Domain').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_domain = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
        self.dg_entry_domain.grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Name').grid(row=1, column=2, padx=5, pady=2, sticky='w')
        self.dg_entry_name = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
        self.dg_entry_name.grid(row=1, column=3, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='Rule Component').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.dg_entry_type = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
        self.dg_entry_type.grid(row=2, column=1, padx=5, pady=2, sticky='ew')
        ttk.Label(frm_dg_filter, text='OCID').grid(row=2, column=2, padx=5, pady=2, sticky='w')
        self.dg_entry_ocid = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
        self.dg_entry_ocid.grid(row=2, column=3, padx=5, pady=2, sticky='ew')

        # Frame for buttons
        frm_dg_buttons = ttk.Frame(frm_dg_filter)
        self.dg_btn_update = ttk.Button(
            frm_dg_buttons, text='Update', state=tk.DISABLED, command=self._update_dg_output
        )
        self.dg_btn_update.grid(row=0, column=0, padx=5, pady=2, sticky='ew')
        self.dg_btn_clear = ttk.Button(frm_dg_buttons, text='Clear', state=tk.DISABLED, command=self._clear_dg_filters)
        self.dg_btn_clear.grid(row=1, column=0, padx=5, pady=2, sticky='ew')
        self.dg_btn_export = ttk.Button(
            frm_dg_buttons, text='Export Selected\nDGs to CSV', state=tk.DISABLED, command=self._export_dg_to_csv
        )
        self.dg_btn_export.grid(row=2, column=0, padx=5, pady=2, sticky='ew')
        frm_dg_buttons.grid(row=1, column=4, rowspan=2, padx=5, pady=2, sticky='ns')

        # Frame Output filter
        frm_dg_output = ttk.Frame(tab_dg)
        frm_dg_output.grid(row=1, column=0, sticky='w')
        frm_dg_output.columnconfigure(0, weight=1)
        self.dg_label_count = ttk.Label(frm_dg_output, text='Dynamic Groups (Filtered): 0')
        self.dg_label_count.grid(row=0, column=0, padx=5, pady=3, sticky='w')
        ttk.Separator(frm_dg_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        self.chk_show_instance_principals = tk.BooleanVar()
        self.chk_show_not_in_use = tk.BooleanVar()
        ttk.Checkbutton(
            frm_dg_output,
            text='Show Instance Principals Only',
            variable=self.chk_show_instance_principals,
            command=self._update_dg_output,
        ).grid(row=0, column=2, padx=5, pady=3)
        ttk.Checkbutton(
            frm_dg_output,
            text='Highlight Unused Dynamic Groups',
            variable=self.chk_show_not_in_use,
            command=self._update_dg_output,
        ).grid(row=0, column=3, padx=5, pady=3)

        # Frame for Bottom Sheet
        frm_dg_sheet = ttk.Frame(tab_dg)
        frm_dg_sheet.grid(row=2, column=0, sticky='nsew')
        frm_dg_sheet.grid_rowconfigure(0, weight=1)
        frm_dg_sheet.grid_columnconfigure(0, weight=1)
        self.sheet_dynamic_group = SortableSheet(
            frm_dg_sheet,
            headers=['Domain', 'Name', 'Matching Rule', 'In Use?', 'OCID', 'Creation Time'],
            # To-do: Add back Invalid OCID functionality "Invalid OCIDs" and maybe rules components
            auto_resize_columns=200,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )
        self.sheet_dynamic_group.grid(row=0, column=0, sticky='nsew')
        self.sheet_dynamic_group.enable_bindings(
            'single_select', 'column_width_resize', 'row_select', 'copy', 'rc_select'
        )

    def create_tab_resource_principals(self):
        # Create Resource Principals tab
        tab_principals = ttk.Frame(self.notebook)
        self.notebook.add(tab_principals, text='Resource\nPrincipals')
        tab_principals.grid_rowconfigure(0, weight=1)
        tab_principals.grid_columnconfigure(0, weight=1)

        # Frame for top
        frm_principals_top = tk.Frame(tab_principals)
        frm_principals_top.pack(fill='x', padx=5, pady=5)

        # Principals Style dropdown
        tk.Label(frm_principals_top, text='Principals Style:').pack(side=tk.LEFT, padx=5)
        self.principals_style_var = tk.StringVar(value='Dynamic Group')
        self.principals_style_list = ['Dynamic Group', 'any-user']
        self.principals_style_dropdown = ttk.OptionMenu(
            frm_principals_top, self.principals_style_var, self.principals_style_var.get(), *self.principals_style_list
        )
        self.principals_style_dropdown.pack(side=tk.LEFT, padx=5)

        # Resource Type dropdown
        tk.Label(frm_principals_top, text='Resource Type:').pack(side=tk.LEFT, padx=5)
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
        self.resource_type_dropdown.pack(side=tk.LEFT, padx=5)

        # Bottom frame for sheets using grid
        frm_principals_bottom = tk.Frame(tab_principals)
        frm_principals_bottom.pack(fill='both', expand=True, padx=5, pady=5)
        frm_principals_bottom.grid_rowconfigure(0, weight=1)
        frm_principals_bottom.grid_rowconfigure(1, weight=1)
        frm_principals_bottom.columnconfigure(0, weight=1)

        self.principals_sheet_dynamic_groups = SortableSheet(
            frm_principals_bottom,
            headers=['Domain', 'Name', 'OCID', 'Matching Rule', 'Rule Components', 'In Use?', 'Creation Time'],
            auto_resize_columns=80,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )
        self.principals_sheet_dynamic_groups.grid(row=0, column=0, sticky='nsew')
        self.principals_sheet_dynamic_groups.enable_bindings(
            'single_select', 'column_width_resize', 'row_select', 'copy', 'rc_select'
        )

        self.principals_sheet_policies_instance = SortableSheet(
            frm_principals_bottom,
            headers=[
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
            ],
            auto_resize_columns=200,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )
        self.principals_sheet_policies_instance.grid(row=1, column=0, sticky='nsew')
        self.principals_sheet_policies_instance.enable_bindings('column_width_resize', 'row_select', 'copy')
        self.principals_sheet_policies_instance.display_columns(
            all_columns_displayed=False, columns=[0, 3, 4, 7, 8, 9, 10, 12, 13, 14, 15]
        )

        # Bind dropdowns to update function
        self.principals_style_var.trace_add('write', self._update_principals_sheets)
        self.resource_type_var.trace_add('write', self._update_principals_sheets)

    def create_tab_user_analysis(self):
        # Create tab with 20/80 rows
        tab_users = ttk.Frame(self.notebook)
        self.notebook.add(tab_users, text='User\nAnalysis')
        tab_users.grid_rowconfigure(0, weight=2)
        tab_users.grid_rowconfigure(1, weight=8)

        # Frame for top
        frm_user_top = ttk.Frame(tab_users)
        frm_user_top.grid_rowconfigure(0, weight=3)
        frm_user_top.grid_rowconfigure(1, weight=7)
        frm_user_top.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # User Selection Frame
        frm_user_select = ttk.Frame(frm_user_top)
        frm_user_select.grid(row=0, column=0, sticky='ew')

        ttk.Label(frm_user_select, text='Select the Domain and User in order to\nload all applicable policies.').grid(
            row=0, column=0, columnspan=2, padx=5, pady=2, sticky='w'
        )

        ttk.Label(frm_user_select, text='Identity Domain:').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        self.domain_var = tk.StringVar(value='None')
        self.domain_display_var = tk.StringVar(value='None')
        self.domain_dropdown = ttk.OptionMenu(frm_user_select, self.domain_display_var, 'None', 'None')
        self.domain_dropdown.grid(row=2, column=1, padx=5, pady=2, sticky='ew')
        self.domain_dropdown.config(state=tk.DISABLED)

        ttk.Label(frm_user_select, text='User:').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        self.user_var = tk.StringVar(value='None')
        self.user_display_var = tk.StringVar(value='None')
        self.user_dropdown = ttk.OptionMenu(
            frm_user_select,
            self.user_display_var,
            'None',
            'None',
            command=lambda _: self.__update_user_analysis_output(),
        )
        self.user_dropdown.grid(row=3, column=1, padx=5, pady=2, sticky='ew')
        self.user_dropdown.config(state=tk.DISABLED)

        # TODO: Bring back compartment selection
        # ttk.Label(frm_user_select, text="Compartment:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        # compartment_var = tk.StringVar(value='All Compartments')
        # compartment_display_var = tk.StringVar(value='All Compartments')
        # compartment_dropdown = ttk.OptionMenu(
        #     frm_user_select, compartment_display_var, 'All Compartments', 'All Compartments'
        # )
        # compartment_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky="ew")
        # compartment_dropdown.config(state=tk.DISABLED)

        # User Buttons
        frm_user_buttons = ttk.Frame(frm_user_select)
        self.btn_export_user = ttk.Button(
            frm_user_buttons, text='Export User Policies to CSV', state=tk.DISABLED, command=self._export_user_to_csv
        )
        self.btn_export_user.grid(row=0, column=0, padx=5, pady=2, sticky='ew')
        frm_user_buttons.grid(row=4, column=0, padx=5, pady=2, sticky='ns')

        # Top Right Pane for User Info
        frm_user_details = ttk.Frame(frm_user_top)
        self.text_user_details = tk.Text(
            frm_user_details, wrap=tk.WORD, font=('TkFixedFont'), state=tk.NORMAL, height=10, width=80
        )
        self.text_user_scroll = ttk.Scrollbar(
            frm_user_details, orient=tk.VERTICAL, command=self.text_user_details.yview
        )
        self.text_user_details.grid(row=0, column=0)
        self.text_user_scroll.grid(row=0, column=1, sticky='ns')
        frm_user_details.grid(row=0, column=1)

        # user_selection_label = ttk.Label(frm_user_select, text="Domain: None (None)\nUser: None (None)\nCompartment: All Compartments (All Compartments)", anchor="w")
        # user_selection_label.grid(row=2, column=0, columnspan=5, padx=5, pady=5, sticky="ew")

        # Bottom Output
        frm_user_output = ttk.Frame(frm_user_top)
        frm_user_output.grid(row=1, column=0, sticky='nsew')
        frm_user_output.columnconfigure(0, weight=1)
        self.user_label_count = ttk.Label(frm_user_output, text='Policy Statements (Filtered): 0')
        self.user_label_count.grid(row=0, column=0, padx=5, pady=3, sticky='w')
        ttk.Separator(frm_user_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        ttk.Label(frm_user_output, text='Display Options:').grid(row=0, column=2, padx=5, pady=3)
        ttk.Checkbutton(
            frm_user_output, text='Expanded', variable=self.chk_show_expanded, command=self._update_user_analysis_output
        ).grid(row=0, column=5, padx=5, pady=3)

        frm_user_sheet = ttk.Frame(tab_users)
        frm_user_sheet.grid(row=1, column=0, sticky='nsew')
        frm_user_sheet.rowconfigure(0, weight=1)
        frm_user_sheet.columnconfigure(0, weight=1)
        self.sheet_user_policies = SortableSheet(
            frm_user_sheet,
            headers=[
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
            ],
            auto_resize_columns=200,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )
        self.sheet_user_policies.grid(row=0, column=0, sticky='nsew')
        self.sheet_user_policies.enable_bindings(
            'single_select', 'column_width_resize', 'row_select', 'copy', 'rc_select'
        )
        # bind_horizontal_scroll(sheet_user_policies)

    def create_tab_report(self):
        # Create tab with 20/80 rows
        tab_report = ttk.Frame(self.notebook)
        tab_report.grid_rowconfigure(0, weight=2)
        tab_report.grid_rowconfigure(1, weight=8)
        frm_report_top = ttk.Frame(tab_report)
        frm_report_top.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        tab_report.rowconfigure(1, weight=1)
        tab_report.columnconfigure(0, weight=1)

        # Top Section
        frm_report_buttons = ttk.Frame(frm_report_top)
        ttk.Label(frm_report_buttons, text='Text Highlight:', font=('TkFixedFont', 10, 'bold')).grid(
            row=0, column=0, padx=5, pady=5, sticky='w'
        )
        highlight_entry_var = tk.StringVar()
        tk.Entry(frm_report_buttons, textvariable=highlight_entry_var).grid(row=0, column=1)

        # Export Button
        btn_export_report = ttk.Button(
            frm_report_buttons, text='Export Report', state=tk.DISABLED, command=self._export_report_to_txt
        )
        btn_export_report.grid(row=0, column=2, padx=5, pady=2, sticky='ew')
        frm_report_buttons.grid(row=0, column=0, sticky='e')

        frm_report = ttk.PanedWindow(tab_report, orient=tk.HORIZONTAL)
        frm_report.grid(row=1, column=0, sticky='nsew')

        # Cache Compare Section
        label_cache_compare = ttk.Label(frm_report_buttons, text='Compare Cache:')
        label_cache_compare.grid(row=0, column=3, padx=5, pady=3)
        cache_compare_list = ['No Cache Available']
        cache_compare_var = tk.StringVar(
            value=cache_compare_list[0] if len(cache_compare_list) > 0 else 'No Cache Available'
        )
        cache_compare_list_dropdown = ttk.OptionMenu(
            frm_report_buttons, cache_compare_var, cache_compare_var.get(), *cache_compare_list
        )
        cache_compare_list_dropdown.grid(row=0, column=4, padx=5, pady=3)
        btn_cache_compare = ttk.Button(
            frm_report_buttons,
            text='Compare Cache',
            # state=tk.DISABLED,
            command=self._compare_against_cache,
        )
        btn_cache_compare.grid(row=0, column=5, padx=5, pady=3, sticky='ew')
        # Bottom Section
        frm_dg_report = ttk.Frame(frm_report)
        frm_dg_report.grid(sticky='nsew')
        frm_dg_report.rowconfigure(1, weight=1)
        frm_dg_report.columnconfigure(0, weight=1)
        ttk.Label(frm_dg_report, text='Dynamic Groups', font=('TkFixedFont', 12, 'bold')).grid(
            row=0, column=0, padx=5, pady=5, sticky='w'
        )
        text_dg_report = tk.Text(frm_dg_report, wrap=tk.WORD, font=('TkFixedFont'), state=tk.DISABLED)
        text_dg_report.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        dg_scroll = ttk.Scrollbar(frm_dg_report, orient=tk.VERTICAL, command=text_dg_report.yview)
        dg_scroll.grid(row=1, column=1, sticky='ns')
        text_dg_report.config(yscrollcommand=dg_scroll.set)

        frm_policy_report = ttk.Frame(frm_report)
        frm_policy_report.grid(sticky='nsew')
        frm_policy_report.rowconfigure(1, weight=1)
        frm_policy_report.columnconfigure(0, weight=1)
        ttk.Label(frm_policy_report, text='Policies by Compartment', font=('TkFixedFont', 12, 'bold')).grid(
            row=0, column=0, padx=5, pady=5, sticky='w'
        )
        text_policy_report = tk.Text(frm_policy_report, wrap=tk.WORD, font=('TkFixedFont'), state=tk.DISABLED)
        text_policy_report.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        policy_scroll = ttk.Scrollbar(frm_policy_report, orient=tk.VERTICAL, command=text_policy_report.yview)
        policy_scroll.grid(row=1, column=1, sticky='ns')
        text_policy_report.config(yscrollcommand=policy_scroll.set)

        frm_report.add(frm_dg_report, weight=3)
        frm_report.add(frm_policy_report, weight=7)

        # Call the highlight functionality
        highlight_entry_var.trace_add('write', self._report_text_search)

    def create_tab_cross_tenancy(self):
        # Create tab with 20/80 rows
        tab_cross_tenancy = ttk.Frame(self.notebook)
        self.notebook.add(tab_cross_tenancy, text='Cross Tenancy\nPolicies')
        frm_cross_tenancy = ttk.Frame(tab_cross_tenancy)
        frm_cross_tenancy.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        frm_cross_tenancy.grid_rowconfigure(0, weight=3)
        frm_cross_tenancy.grid_rowconfigure(1, weight=7)
        frm_cross_tenancy.grid_columnconfigure(0, weight=2)
        frm_cross_tenancy.grid_columnconfigure(1, weight=8)
        ttk.Label(
            frm_cross_tenancy,
            text='Select one or more rows to the right\nin order to narrow down cross-tenancy policies\n\nSort by clicking column headers',
            font=('TkFixedFont', 10, 'normal'),
        ).grid(row=0, column=0, padx=5, pady=5, sticky='w')

        self.sheet_cross_tenancy_define = SortableSheet(
            frm_cross_tenancy,
            headers=['Defined Alias', 'Define Type', 'Remote Tenancy OCID'],
            show_x_scrollbar=True,
            show_y_scrollbar=True,
            auto_resize_columns=True,
        )
        self.sheet_cross_tenancy_define.enable_bindings('all')
        self.sheet_cross_tenancy_define.extra_bindings('row_select', self._update_cross_tenancy_alias_selection)
        self.sheet_cross_tenancy_define.grid(row=0, column=1, sticky='nsew')
        self.sheet_cross_tenancy_policies = SortableSheet(
            frm_cross_tenancy,
            headers=[
                'Policy Name',
                'Statement Text',
                'Policy OCID',
                'Create Date',
                'Parsing Available',
                'Subject Type',
                'Subject',
                'Action / Verb / Resource',
                'Location Type',
                'Location',
                'Condition',
                'Optional',
            ],
            auto_resize_columns=200,
            show_x_scrollbar=True,
            show_y_scrollbar=True,
        )
        self.sheet_cross_tenancy_policies.enable_bindings('all')
        self.sheet_cross_tenancy_policies.grid(row=1, column=0, columnspan=2, sticky='nsew')

    def create_tab_history(self):
        # Create tab with 2 equal rows
        tab_history = ttk.Frame(self.notebook)
        tab_history.grid_rowconfigure(0, weight=1)
        tab_history.grid_rowconfigure(1, weight=1)
        self.notebook.add(tab_history, text='Policy Compare/\nAuditHistory')
        frm_history_top = ttk.Frame(tab_history)
        frm_history_top.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        frm_history_bottom = ttk.Frame(tab_history)
        frm_history_bottom.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)

    def tab_sample(self):
        """Create layout and sheet for Tab 1 with threaded loading, multiple row selection, and tooltips."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text='Students')

        # Configure grid layout
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Create sheet
        self.tab1_sheet = SortableSheet(
            frame,
            headers=['Name', 'Date', 'Score'],
            data=[],  # Start empty, populate via thread
            width=400,
            height=200,
        )
        self.tab1_sheet.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Enable multiple row selection and bindings
        self.tab1_sheet.enable_bindings(
            'multiple_row_select', 'row_select', 'column_select', 'single_select', 'drag_select'
        )
        self.tab1_sheet.bind('<Shift-Button-1>', lambda event: self._handle_shift_click(self.tab1_sheet, event))
        self.tab1_sheet.bind('<Shift-ButtonRelease-1>', lambda event: self._handle_shift_click(self.tab1_sheet, event))
        # Bind regular click to track last selected row
        self.tab1_sheet.bind('<Button-1>', lambda event: self._handle_row_click(self.tab1_sheet, event))
        logging.debug('Row selection bindings enabled for Tab 1 sheet')

        # Add tooltip to sheet
        Tooltip(self.tab1_sheet, self.tooltips['tab1_sheet'])

        # Add a label for static text
        label = ttk.Label(frame, text='Student Data (Multi-Select Enabled)')
        label.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        Tooltip(label, self.tooltips['tab1_label'])

        # Add a progress label
        self.tab1_progress_label = ttk.Label(frame, text='Starting data load...')
        self.tab1_progress_label.grid(row=2, column=0, sticky='ew', padx=5, pady=5)
        Tooltip(self.tab1_progress_label, self.tooltips['tab1_progress'])

        # Start threaded data loading
        self._start_data_loading()

    def create_tab2(self):
        """Create layout and sheet for Tab 2 with tooltips."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text='Cities')

        # Configure grid layout
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Create sheet
        sheet = SortableSheet(
            frame,
            headers=['City', 'Population', 'Area'],
            data=[['New York', 8336817, 302.6], ['London', 8982256, 606], ['Tokyo', 37468000, 847]],
            width=400,
            height=200,
        )
        sheet.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Add tooltip to sheet
        Tooltip(sheet, self.tooltips['tab2_sheet'])

        # Add a label
        label = ttk.Label(frame, text='City Data')
        label.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        Tooltip(label, self.tooltips['tab2_label'])

    def create_tab3(self):
        """Create layout and sheet for Tab 3 with tooltips."""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text='Products')

        # Configure grid layout
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Create sheet
        sheet = SortableSheet(
            frame,
            headers=['Product', 'Price', 'Stock'],
            data=[['Laptop', 999.99, 50], ['Phone', 699.99, 100], ['Tablet', 299.99, 75]],
            width=400,
            height=200,
        )
        sheet.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)

        # Add tooltip to sheet
        Tooltip(sheet, self.tooltips['tab3_sheet'])

        # Add a label
        label = ttk.Label(frame, text='Product Inventory')
        label.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        Tooltip(label, self.tooltips['tab3_label'])

    def _handle_row_click(self, sheet, event):
        """Handle regular click to track last selected row."""
        region = sheet.identify_region(event)
        logging.debug(f'Row click event: type={event.type}, region={region}, x={event.x}, y={event.y}')
        if region == 'index':
            row = sheet.identify_row(event)
            self.last_selected_row = row
            logging.debug(f'Last selected row updated: {row}')

    def _handle_shift_click(self, sheet, event):
        """Handle Shift-click for range row selection."""
        region = sheet.identify_region(event)
        logging.debug(f'Shift-click event: type={event.type}, region={region}, x={event.x}, y={event.y}')
        if region == 'index':
            current_row = sheet.identify_row(event)
            if self.last_selected_row is not None:
                # Clear previous selections (optional, remove if you want to keep existing selections)
                sheet.deselect('all')
                # Select range from last_selected_row to current_row
                start_row = min(self.last_selected_row, current_row)
                end_row = max(self.last_selected_row, current_row)
                for row in range(start_row, end_row + 1):
                    sheet.select_row(row)
                logging.debug(f'Selected row range: {start_row} to {end_row}')
            else:
                # If no last selected row, select just the current row
                sheet.select_row(current_row)
                logging.debug(f'Selected single row: {current_row}')
            self.last_selected_row = current_row
        else:
            logging.debug(f'Non-index click ignored: region={region}')

    def _start_data_loading(self):
        """Start the threaded data loading process for Tab 1."""
        self.total_chunks = 26  # 52 weeks / 2 = 26 chunks
        self.current_chunk = 0
        self.data_queue = Queue()

        # Start the background thread
        thread = Thread(target=self._load_data_in_chunks, daemon=True)
        thread.start()

        # Start checking the queue for updates
        self._check_queue()

    def _load_data_in_chunks(self):
        """Simulate loading data in 2-week chunks."""
        start_date = datetime.datetime(2025, 1, 1)
        names = ['John', 'Alice', 'Bob']
        for chunk in range(self.total_chunks):
            time.sleep(1)  # Simulate long-running task
            chunk_data = []
            for i in range(5):  # 5 rows per chunk
                date = start_date + datetime.timedelta(weeks=2 * chunk)
                chunk_data.append([names[i % len(names)], date.strftime('%Y-%m-%d'), 70 + i + chunk])
            self.data_queue.put((chunk + 1, chunk_data))
        self.data_queue.put('done')

    def _check_queue(self):
        """Check the queue for new data and update the sheet and label."""
        try:
            item = self.data_queue.get_nowait()
            if item == 'done':
                self.tab1_progress_label.config(text='Data loading complete!')
            else:
                chunk_num, chunk_data = item
                self.current_chunk = chunk_num
                current_data = self.tab1_sheet.get_sheet_data()
                current_data.extend(chunk_data)
                self.tab1_sheet.set_sheet_data(current_data)
                self.tab1_sheet.refresh()
                self.tab1_progress_label.config(text=f'Loading chunk {self.current_chunk} of {self.total_chunks}...')
        except queue.Empty:
            pass
        self.root.after(100, self._check_queue)

    # Main Update functions - per tab
    def _update_policy_output(self):
        filtered = self.policy_compartment_analysis.filter_policy_statements(
            self.entry_subj.get(),
            self.entry_verb.get(),
            self.entry_res.get(),
            self.entry_loc.get(),
            self.entry_hierarchy.get(),
            self.entry_condition.get(),
            self.entry_text.get(),
            self.entry_policy.get(),
        )

        # Convert back to list to support tksheet
        headers = list(filtered[0].keys())
        sheet_data = [[row[col] for col in headers] for row in filtered]
        self.sheet_policies.set_sheet_data(sheet_data, reset_highlights=True)
        self.sheet_policies.display_columns(
            all_columns_displayed=True if self.chk_show_expanded.get() else False,
            columns=[0, 3, 4] if not self.chk_show_expanded.get() else None,
        )
        # Display Output
        rows_to_show: list = [
            i
            for i, st in enumerate(filtered)
            if (
                self.chk_show_service.get()
                and st.get('subject_type') == 'service'
                or self.chk_show_dynamic.get()
                and st.get('subject_type') == 'dynamic-group'
                or self.chk_show_resource.get()
                and st.get('subject_type') == 'resource'
                or self.chk_show_regular.get()
                and st.get('subject_type') in ['group', 'any-user', 'any-group']
                or self.chk_show_invalid.get()
                and not st.get('validity')
            )
        ]
        self.label_policy_count.config(
            text=f'Statements (Filtered): {len(filtered)}\nStatements (Shown): {len(rows_to_show)}'
        )
        if rows_to_show and len(rows_to_show) == 0:
            self.sheet_policies.display_rows(rows=[], all_rows_displayed=False, redraw=True)
            logger.info(f'Clearing sheet because there are {len(rows_to_show)} rows to display')

        logger.info(f'Displaying {len(rows_to_show)} rows on sheet')

        # Resize to text
        self.sheet_policies.set_all_cell_sizes_to_text()

    def _update_dg_output(self):
        if self.chk_show_instance_principals.get():
            self.dg_entry_type.delete(0, tk.END)
            self.dg_entry_type.insert(0, 'instance.compartment.id|instance.id')

        filtered = self.identity_domain_analysis.filter_dynamic_groups(
            self.dg_entry_domain.get() if self.dg_entry_domain.get() != '' else None,
            self.dg_entry_name.get() if self.dg_entry_name.get() != '' else None,
            self.dg_entry_type.get() if self.dg_entry_type.get() != '' else None,
            self.dg_entry_ocid.get() if self.dg_entry_ocid.get() != '' else None,
        )
        self.sheet_dynamic_group.display_columns(all_columns_displayed=True)
        for dg in filtered:
            dg[2] = format_dgrule(dg[2], 0)

        self.sheet_dynamic_group.set_sheet_data(filtered, reset_highlights=True)
        self.sheet_dynamic_group.set_all_cell_sizes_to_text()
        self.dg_label_count.config(text=f'Dynamic Groups (Filtered): {len(filtered)} \n ')

        filtered_stage2: int = 0

        if self.chk_show_not_in_use.get():
            self._run_dg_analysis()
            for i, dg in enumerate(filtered):
                if not dg[3]:
                    filtered_stage2 += 1
                    self.sheet_dynamic_group.highlight_rows(rows=[i], bg='red')  # type: ignore
                    # filtered_stage2.append(dg)
            self.dg_label_count.config(text=f'Dynamic Groups (Highlighted): {filtered_stage2}')

    def _update_principals_sheets(self, *args):
        """Update sheets based on dropdown selections and dynamic group selection."""
        principals_style = self.principals_style_var.get()
        resource_type = self.resource_type_var.get()

        # Enable/disable Resource Type dropdown
        self.resource_type_dropdown.configure(state='normal')

        # Enable/disable Principals Style
        self.principals_style_dropdown.configure(state='normal')

        # Clear sheets and hide both sheets by default
        self.principals_sheet_dynamic_groups.set_sheet_data([])  # Clear data
        # frm_bottom.grid_forget()
        self.principals_sheet_dynamic_groups.grid_forget()  # Hide dynamic group sheet
        self.principals_sheet_policies_instance.grid_forget()  # Hide policy sheet temporarily

        if principals_style == 'any-user':
            # Start with "any-user" style statement
            # Don't care about Dynamic groups
            if resource_type == 'Any':
                logger.info('Case 1 - Any-User with no type specified')
                policies = self.policy_compartment_analysis.filter_policy_statements(
                    condition_filter='request.principal.type'
                )
                self.principals_sheet_policies_instance.set_sheet_data(policies)
            else:
                logger.info(f'Case 2 - Any-User with type {resource_type} specified')
                condition_filter = f"request.principal.type='{resource_type}'"
                policies = self.policy_compartment_analysis.filter_policy_statements(condition_filter=condition_filter)
                self.principals_sheet_policies_instance.set_sheet_data(policies)

            # UI Elements - re-grid with only Policy viewer
            self.principals_sheet_policies_instance.grid(
                row=0, column=0, rowspan=2, sticky='nsew'
            )  # Show policy sheet in row 1

        elif principals_style == 'Dynamic Group':
            logger.info('Case 3 - Dynamic Group')

            # # Configure frm_bottom weights to split space evenly
            # frm_bottom.rowconfigure(0, weight=1)
            # frm_bottom.rowconfigure(1, weight=1)
            # # Show both sheets in their respective grid positions
            # principals_sheet_dynamic_groups.grid(row=0, column=0, sticky='nsew')  # Show dynamic group sheet
            # principals_sheet_policies_instance.grid(row=1, column=0, sticky='nsew')  # Show policy sheet in row 1

            # Populate dynamic group sheet
            filtered_dynamic_groups = []
            # if type_principal == "Instance Principals":
            # filtered_dynamic_groups = identity_domain_analysis.filter_dynamic_groups(type_filter="instance.compartment.id")
            # elif type_principal == "Resource Principals":
            filtered_dynamic_groups = self.identity_domain_analysis.filter_dynamic_groups(
                type_filter='resource.type|resource.principal|resource.id'
            )
            self.principals_sheet_dynamic_groups.set_sheet_data(filtered_dynamic_groups)

            # Populate policy sheet with initial filter
            # For DG style, search any policy that refers to a DG in the list of dynamic groups
            # Build a list of DGs from previous output
            selected_dgs: list = []
            for dg in filtered_dynamic_groups:
                selected_dgs.append(dg[1])

            # Now build a policy search based on a string of all DGs
            subject_search = '|'.join(selected_dgs)

            # Now search policies based on DG type and subject string
            policies = self.policy_compartment_analysis.filter_policy_statements(subj_filter=subject_search)
            # policies = policy_compartment_analysis.filter_resource_principal_policies('Resource Principals', principals_style, resource_type)
            self.principals_sheet_policies_instance.set_sheet_data(policies)

            # Enable row selection on dynamic group sheet
            def on_row_select(event):
                selected_rows = self.principals_sheet_dynamic_groups.get_selected_rows()
                logger.info(f'Selected row in DG sheet: {selected_rows}')
                # if selected_rows:
                #     selected_idx = list(selected_rows)[0]
                #     logger.info(f'Selected row in DG sheet: {list(selected_rows)[0]}')
                #     selected_dg = (filtered_dynamic_groups[selected_idx][0], filtered_dynamic_groups[selected_idx][1])
                #     filtered_policies = policy_compartment_analysis.filter_resource_principal_policies(
                #         'Resource Principals', principals_style, resource_type, selected_dg
                #     )
                #     logger.info(f'Filtered Policy count for {selected_dg}: {len(filtered_policies)}')
                #     principals_sheet_policies_instance.set_sheet_data(filtered_policies)
                # else:
                #     # Reset to all dynamic group policies
                #     filtered_policies = policy_compartment_analysis.filter_resource_principal_policies(
                #         'Resource Principals', principals_style, resource_type
                #     )
                #     principals_sheet_policies_instance.set_sheet_data(filtered_policies)

            # UI Elements - re-grid with both DG and Policy viewer
            self.principals_sheet_dynamic_groups.grid(row=0, column=0, sticky='nsew')  # Show dynamic group sheet
            self.principals_sheet_policies_instance.grid(row=1, column=0, sticky='nsew')  # Show policy sheet in row 1

            self.principals_sheet_dynamic_groups.bind('<ButtonRelease-1>', on_row_select)
        else:
            logger.info('Nothing selected')

        # Resize data
        self.principals_sheet_dynamic_groups.set_all_cell_sizes_to_text(slim=False)
        self.principals_sheet_policies_instance.set_all_cell_sizes_to_text(slim=False)

    def _update_user_analysis_output(self):
        # TODO: Compartment Analysis
        domain_id = self.domain_var.get()
        user_id = self.user_var.get()
        # compartment_id = compartment_var.get()
        if domain_id == 'None' or user_id == 'None':
            self.sheet_user_policies.set_sheet_data([], reset_highlights=True)
            self.user_label_count.config(text='Policy Statements (Filtered): 0')
            self._update_user_selection_info()
            return

        filtered = self.policy_compartment_analysis.get_user_group_statements(
            user_id=user_id,
            # compartment_id=compartment_id if compartment_id != 'All Compartments' else None,
            compartment_id=None,
            user_group_names=self.identity_domain_analysis.get_user_groups(domain_id, user_id),
            user_domain_name=self.identity_domain_analysis.get_domain_name_by_id(domain_id),
        )
        self.sheet_user_policies.set_sheet_data(filtered, reset_highlights=True)
        self.sheet_user_policies.set_all_cell_sizes_to_text()
        self.sheet_user_policies.display_columns(
            all_columns_displayed=True if self.chk_show_expanded.get() else False,
            columns=[0, 3, 4] if not self.chk_show_expanded.get() else None,
        )

        self.user_label_count.config(text=f'Policy Statements (Filtered): {len(filtered)}')
        self._update_user_selection_info()

    def _update_report_output(self):
        self.text_dg_report.delete(1.0, tk.END)
        self.text_policy_report.delete(1.0, tk.END)
        sorted_dgs = sorted(self.identity_domain_analysis.dynamic_groups, key=lambda x: (x[0], x[1]))
        dg_text = 'Dynamic Groups Report\n====================\n'
        if not sorted_dgs:
            dg_text += 'No dynamic groups found.\n'
        else:
            for dg in sorted_dgs:
                dg_text += f"Domain: {dg[0]}\nName: {dg[1]}\nMatching Rule: {dg[2]}\nOCID: {dg[4]}\nCreated: {dg[5]}\nIn Use: {'Yes' if dg[3] else 'No'}\n\n"
        self.text_dg_report.config(state=tk.NORMAL)
        self.text_dg_report.insert(tk.END, dg_text)
        self.text_dg_report.config(state=tk.DISABLED)

        sorted_comps = sorted(self.policy_compartment_analysis.compartments, key=lambda x: x['hierarchy_path'])
        policy_text = 'Compartment and Policy Report\n============================\n'
        if not sorted_comps:
            policy_text += 'No compartments or policies found.\n'
        else:
            for comp in sorted_comps:
                policy_text += f"Compartment: {comp['hierarchy_path']} (OCID: {comp['id']})\n"
                statements = [
                    s
                    for s in self.policy_compartment_analysis.regular_statements
                    if s.get('compartment_id') == comp['id']
                ]
                if statements:
                    policy_dict = {}
                    for s in statements:
                        policy_name = s.get('policy_name', 'Unknown Policy')
                        policy_ocid = s.get('policy_id', 'Unknown OCID')
                        if policy_name not in policy_dict:
                            policy_dict[policy_name] = {'ocid': policy_ocid, 'statements': []}
                        policy_dict[policy_name]['statements'].append(s.get('statement_text', 'No Statement Text'))
                    for policy_name, data in sorted(policy_dict.items()):
                        policy_text += f"  Policy: {policy_name} (OCID: {data['ocid']})\n"
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
        logger.debug(f'cross: {len(self.policy_compartment_analysis.cross_tenancy_statements)}')
        defined_aliases = self.policy_compartment_analysis.defined_aliases
        alias_list = []
        for alias in defined_aliases:
            logger.debug(f'Alias {alias}: {defined_aliases[alias]}')
            alias_list.append([alias, defined_aliases[alias][0], defined_aliases[alias][1]])
        self.sheet_cross_tenancy_define.set_sheet_data(alias_list)
        self.sheet_cross_tenancy_policies.display_columns(columns=[0, 1, 2, 3, 4], all_columns_displayed=False)
        self.sheet_cross_tenancy_policies.set_sheet_data(self.policy_compartment_analysis.cross_tenancy_statements)
        self.sheet_cross_tenancy_policies.set_all_cell_sizes_to_text()

    # Calls into core to make updates
    def _run_dg_analysis(self):
        logger.info(
            f'Running Dynamic Group Analysis for {len(self.identity_domain_analysis.dynamic_groups)} DGs and {len(self.policy_compartment_analysis.regular_statements)} Policies'
        )
        self.identity_domain_analysis.set_statements(self.policy_compartment_analysis.regular_statements)
        self.identity_domain_analysis.run_dg_in_use_analysis()

    def _compare_against_cache(self):
        selected_cache = self.cache_compare_var.get()
        ten, dat = selected_cache.split('\n')
        self.policy_compartment_analysis.compare_against_cache(cached_tenancy=ten, cached_date=dat)

    # Additional widget Updates
    def _update_font(self, var_name, index, mode):
        if self.font_size_var:
            new_font_size = (
                8 if self.font_size_var.get() == 'Small' else 10 if self.font_size_var.get() == 'Medium' else 12
            )
            self.sheet_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_policies.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_dynamic_group.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_dynamic_group.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_user_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_user_policies.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_cross_tenancy_define.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_cross_tenancy_define.set_all_cell_sizes_to_text(redraw=True)
            self.sheet_cross_tenancy_policies.font(newfont=('Courier New', new_font_size, 'normal'))
            self.sheet_cross_tenancy_policies.set_all_cell_sizes_to_text(redraw=True)
            logger.info(f'Changing font size globally to {self.font_size_var.get()}/{new_font_size}')

    def _toggle_profile_dropdown(self):
        if self.use_instance_principal.get():
            self.input_profile.config(state=tk.DISABLED)
            self.label_profile.config(state=tk.DISABLED)
        else:
            self.input_profile.config(state=tk.NORMAL)
            self.label_profile.config(state=tk.NORMAL)

    def _clear_policy_filters(self):
        for entry in [
            self.entry_subj,
            self.entry_verb,
            self.entry_res,
            self.entry_loc,
            self.entry_hierarchy,
            self.entry_condition,
            self.entry_text,
            self.entry_policy,
        ]:
            entry.delete(0, tk.END)
        self.use_subject_any.set(False)
        self.location_filter_tenancy.set(False)
        self.hierarchy_filter_root.set(False)
        self._update_policy_output()

    def _toggle_any_subject(self):
        if self.use_subject_any.get():
            self.entry_subj.insert(0, 'any-user|any-group')
            self.entry_subj.config(state=tk.DISABLED)
        else:
            self.entry_subj.config(state=tk.NORMAL)
            self.entry_subj.delete(0, tk.END)

        # Update the Output
        self._update_policy_output()

    def _toggle_location_tenancy(self):
        if self.location_filter_tenancy.get():
            self.entry_loc.delete(0, tk.END)
            self.entry_loc.insert(0, 'tenancy')
            self.entry_loc.config(state=tk.DISABLED)
        else:
            self.entry_loc.config(state=tk.NORMAL)
            self.entry_loc.delete(0, tk.END)

        # Update the output
        self._update_policy_output()

    def _toggle_hierarchy_root(self):
        if self.hierarchy_filter_root.get():
            self.entry_hierarchy.delete(0, tk.END)
            self.entry_hierarchy.insert(0, 'ROOT')
            self.entry_hierarchy.config(state=tk.DISABLED)
        else:
            self.entry_hierarchy.config(state=tk.NORMAL)
            self.entry_hierarchy.delete(0, tk.END)

        # Update the Output
        self._update_policy_output()

    def _clear_dg_filters(self):
        for entry in [self.dg_entry_domain, self.dg_entry_name, self.dg_entry_type, self.dg_entry_ocid]:
            entry.delete(0, tk.END)
        self._update_dg_output()

    def _update_user_dropdown(self):
        domain_id = self.domain_var.get()
        users = ['None']
        if domain_id != 'None':
            users = [
                u['display_name']
                for u in sorted(
                    self.identity_domain_analysis.get_users_by_domain(domain_id), key=lambda x: x['display_name']
                )
            ]
            if not users:
                users = ['None']
        self.user_dropdown['menu'].delete(0, tk.END)
        self.user_var.set('None')
        for user in users:
            user_id = (
                next(
                    (
                        u['id']
                        for u in self.identity_domain_analysis.get_users_by_domain(domain_id)
                        if u['display_name'] == user
                    ),
                    'None',
                )
                if user != 'None'
                else 'None'
            )
            self.user_dropdown['menu'].add_command(
                label=user,
                command=lambda u=user, uid=user_id: [
                    self.user_var.set(uid),
                    self.user_display_var.set(u),
                    self._update_user_analysis_output(),
                ],
            )
        self._update_user_analysis_output()

    def _update_domain_dropdown(self):
        domains = ['None'] + [
            d['display_name']
            for d in sorted(self.identity_domain_analysis.get_domains(), key=lambda x: x['display_name'])
        ]
        self.domain_dropdown['menu'].delete(0, tk.END)
        self.domain_var.set('None')
        self.domain_display_var.set('None')
        for domain in domains:
            domain_id = (
                next(
                    (d['id'] for d in self.identity_domain_analysis.get_domains() if d['display_name'] == domain),
                    'None',
                )
                if domain != 'None'
                else 'None'
            )
            self.domain_dropdown['menu'].add_command(
                label=domain,
                command=lambda d=domain, did=domain_id: [
                    self.domain_var.set(did),
                    self.domain_display_var.set(d),
                    self._update_user_dropdown(),
                ],
            )
        self._update_user_dropdown()

    def _update_user_selection_info(self):
        domain_id = self.domain_var.get()
        user_id = self.user_var.get()
        # compartment_id = compartment_var.get()
        domain_display = (
            next(
                (d['display_name'] for d in self.identity_domain_analysis.get_domains() if d['id'] == domain_id), 'None'
            )
            if domain_id != 'None'
            else 'None'
        )
        user_display = (
            next(
                (
                    u['display_name']
                    for u in self.identity_domain_analysis.get_users_by_domain(domain_id)
                    if u['id'] == user_id
                ),
                'None',
            )
            if user_id != 'None'
            else 'None'
        )
        # TODO: Compartment Selection
        # compartment_display = (
        #     next(
        #         (c['hierarchy_path'] for c in policy_compartment_analysis.compartments if c['id'] == compartment_id),
        #         'All Compartments',
        #     )
        #     if compartment_id != 'All Compartments'
        #     else 'All Compartments'
        # )
        selection_info = f'Domain: {domain_display} ({domain_id})\nUser: {user_display} ({user_id})\nUser groups: {self.identity_domain_analysis.get_user_groups(domain_id=domain_id, user_id=user_id)}'
        self.text_user_details.delete(1.0, tk.END)
        self.text_user_details.insert(1.0, selection_info)

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

    def _update_cross_tenancy_alias_selection(self, row):
        selected_rows = self.sheet_cross_tenancy_define.get_selected_rows()
        if selected_rows:
            aliases_to_filter = []
            for idx in selected_rows:
                # selected_idx = list(selected_rows)
                alias = self.sheet_cross_tenancy_define.get_cell_data(r=idx, c=0)
                logger.debug(f'Selected row {idx} - Using alias {alias} for search in policies')
                aliases_to_filter.append(alias)

            logger.info(f'Using aliases {aliases_to_filter} for search in policies')
            # Filter bottom sheet
            filtered = self.policy_compartment_analysis.filter_cross_tenancy_policy_statements(
                alias_filter=aliases_to_filter
            )
            self.sheet_cross_tenancy_policies.set_sheet_data(filtered, redraw=True)
            self.sheet_cross_tenancy_policies.set_all_cell_sizes_to_text()
        else:
            logger.debug('no row selected')

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
                self.entry_subj.get(),
                self.entry_verb.get(),
                self.entry_res.get(),
                self.entry_loc.get(),
                self.entry_hierarchy.get(),
                self.entry_condition.get(),
                self.entry_text.get(),
                self.entry_policy.get(),
            )
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(self.sheet_policies.headers())
                writer.writerows(filtered)
            logger.info(f'Exported {len(filtered)} policy statements to {filepath}')

    def _export_dg_to_csv(self):
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
        if filepath:
            filtered = self.identity_domain_analysis.filter_dynamic_groups(
                self.dg_entry_domain.get(), self.dg_entry_name.get(), self.dg_entry_type.get(), self.dg_entry_ocid.get()
            )
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(self.sheet_dynamic_group.headers())
                writer.writerows(filtered)
            logger.info(f'Exported {len(filtered)} dynamic groups to {filepath}')

    def _export_user_to_csv(self):
        filepath = tkfiledialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV Files', '*.csv')])
        if filepath:
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(self.sheet_user_policies.headers())
                writer.writerows(self.sheet_user_policies.data)
            logger.info(f'Exported {len(self.sheet_user_policies.data)} user policy statements to {filepath}')

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
        self.label_status_bar.config(text=f'{self.status_bar_text} | Loaded data as of {last_load_time}')
        [
            e.config(state=tk.NORMAL)
            for e in [
                self.entry_subj,
                self.entry_verb,
                self.entry_res,
                self.entry_loc,
                self.entry_hierarchy,
                self.entry_condition,
                self.entry_text,
                self.entry_policy,
                self.dg_entry_domain,
                self.dg_entry_name,
                self.dg_entry_type,
                self.dg_entry_ocid,
                self.domain_dropdown,
                self.user_dropdown,
                # compartment_dropdown,
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
                self.dg_btn_export,
                self.btn_export_user,
                # self.btn_export_report,
            ]
        ]
        # _update_domain_dropdown()
        # update_compartment_dropdown()
        self._update_policy_output()
        self._update_dg_output()
        self._update_principals_sheets()
        self._update_user_analysis_output()
        self._update_report_output()
        # _update_cross_tenancy_output()
        # _update_history_cache_compare_dropdown()

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
                profile = self.profile_var.get()
                use_ip = self.use_instance_principal.get()
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
                last_load_time = self.policy_compartment_analysis.data_as_of
                logger.info(f'***Loaded cached data as of {last_load_time}')

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
        self.label_status_bar.config(
            text=f'Loading data from tenancy {self.policy_compartment_analysis.tenancy_name}...'
        )

        def load():
            global last_error, last_load_time
            try:
                profile = self.profile_var.get()
                use_ip = self.use_instance_principal.get()
                self.progress_bar_label.config(text='Initializing Clients')
                success = self.policy_compartment_analysis.initialize_client(use_ip, profile)
                if not success:
                    raise RuntimeError('Failed to initialize PolicyCompartmentAnalysis client')
                success = self.identity_domain_analysis.initialize_client(use_ip, profile)
                if not success:
                    raise RuntimeError('Failed to initialize IdentityDomainAnalysis client')
                self.progress_bar_label.config(text='Loading Policies and Compartments')
                success = self.policy_compartment_analysis.load_policies_and_compartments()
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
                last_load_time = self.policy_compartment_analysis.data_as_of
                logger.info(f'***Loaded tenancy data as of {last_load_time}')
                self.root.after(
                    0,
                    self._window_after_lambda,
                )
                logger.info(f'Loaded data for tenancy: {self.policy_compartment_analysis.tenancy_ocid}')
            except Exception as exc:
                last_error = str(exc)
                self.root.after(
                    0,
                    lambda: self.label_status_bar.config(text=self.status_bar_text),
                )
                logger.error(f'Data load error: {last_error}')
            finally:
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


### Main Code Helpers


def parse_args():
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    return parser.parse_args()


def format_dgrule(text, indent_level=0) -> str:  # noqa: C901
    """
    Recursively formats the input language string with 2-space indentation.

    Args:
        text (str): The input language string to format
        indent_level (int): Current indentation level (default: 0)

    Returns:
        str: Formatted string with newlines and 2-space indentation
    """
    result = []
    current = ''
    i = 0
    while i < len(text):
        char = text[i]

        if char == '{':
            result.append('  ' * indent_level + current.strip() + ' {')
            brace_count = 1
            start = i + 1
            while i < len(text) and brace_count > 0:
                i += 1
                if i < len(text):
                    if text[i] == '{':
                        brace_count += 1
                    elif text[i] == '}':
                        brace_count -= 1
            result.append(format_dgrule(text[start:i], indent_level + 1))
            current = ''
            continue
        elif char == '}':
            if current.strip():
                result.append('  ' * indent_level + current.strip())
            result.append('  ' * indent_level + '}')
            current = ''
        elif char == ',':
            if current.strip():
                result.append('  ' * indent_level + current.strip())
            current = ''
        else:
            current += char
        i += 1

    if current.strip():
        result.append('  ' * indent_level + current.strip())

    return '\n'.join(line for line in result if line.strip())


########################
# UI Elements
def main():
    # Parse command line arguments
    args = parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Create Tkinter root and NotebookApp with parsed arguments
    window = ttk.Window(themename='litera')
    window.geometry('1280x1024')
    app = OCIPolicyDGViewer(window, verbose=args.verbose)
    logger.info(f'Starting OCI Policy and Dynamic Group Viewer with profile: {type(app)}')
    window.mainloop()


# Start Program
if __name__ == '__main__':
    main()

# End of src/oci_policy_dg_viewer.py

#     # Try to use ttkbootstrap theme
#     try:
#         if hasattr(ttk, 'Style'):
#             style = ttk.Style()
#             if hasattr(style, 'theme_use'):
#                 style.theme_use('cosmo')  # Modern blue theme
#     except:
#         pass


#     # Notebook
#     tab_control = ttk.Notebook(window)
#     tab_policy = ttk.Frame(tab_control)
#     tab_dg = ttk.Frame(tab_control)
#     tab_principals = ttk.Frame(tab_control)
#     tab_users = ttk.Frame(tab_control)
#     tab_users.grid_rowconfigure(0, weight=2)
#     tab_users.grid_rowconfigure(1, weight=8)
#     tab_users.grid_columnconfigure(0, weight=1)
#     tab_report = ttk.Frame(tab_control)
#     tab_cross_tenancy = tk.Frame(tab_control)
#     tab_cross_tenancy.grid_rowconfigure(0, weight=1)
#     tab_cross_tenancy.grid_columnconfigure(0, weight=1)

#     tab_control.add(tab_policy, text='Regular Policy\nStatements')
#     tab_control.add(tab_dg, text='Dynamic Groups / \nInstance Principals')
#     tab_control.add(tab_principals, text='Resource\nPrincipals')
#     tab_control.add(tab_users, text='User Permission\nAnalysis')
#     tab_control.add(tab_report, text='Policy/Dynamic\nGroup Report')
#     tab_control.add(tab_cross_tenancy, text='Cross Tenancy\nPolicies')
#     tab_control.grid(row=1, column=0, sticky='nsew')


# def update_compartment_dropdown():
#     compartments = ['All Compartments'] + [
#         c['hierarchy_path'] for c in sorted(policy_compartment_analysis.compartments, key=lambda x: x['hierarchy_path'])
#     ]
#     compartment_dropdown['menu'].delete(0, tk.END)
#     compartment_var.set('All Compartments')
#     compartment_display_var.set('All Compartments')
#     for compartment in compartments:
#         compartment_id = (
#             next(
#                 (c['id'] for c in policy_compartment_analysis.compartments if c['hierarchy_path'] == compartment),
#                 'All Compartments',
#             )
#             if compartment != 'All Compartments'
#             else 'All Compartments'
#         )
#         compartment_dropdown['menu'].add_command(
#             label=compartment,
#             command=lambda c=compartment, cid=compartment_id: [
#                 compartment_var.set(cid),
#                 compartment_display_var.set(c),
#                 _update_user_analysis_output(),
#             ],
#         )
#     _update_user_analysis_output()
