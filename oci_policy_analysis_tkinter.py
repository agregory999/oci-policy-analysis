#!/usr/bin/env python3
##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at  https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application,  It does not supported by Oracle Support.
#
# oci_policy_analysis_tkinter.py
#
# @author: Andrew Gregory
#
# Supports Python 3 and above
#
# coding: utf-8
##########################################################################

# Python
import json
from pathlib import Path
import logging
from threading import Thread
import csv
import copy
import datetime
import argparse

# UI
import tkinter as tk
#import tkinter.ttk as ttk
import ttkbootstrap as ttk

from ttkbootstrap.constants import *
from tkinter.filedialog import askopenfilename, asksaveasfilename
from tkinter import messagebox as mb
from tkinter import font
from tksheet import Sheet

# Local Class
from dynamic_groups import DynamicGroupAnalysis
from policy_statements import PolicyAnalysis
from progress import Progress

###############################################################################################################
# Global variables and Helper
###############################################################################################################

progressbar_val = None

POLICY_TAB_NAME = "Policy Statement View"
DG_TAB_NAME = "Dynamic Group View"
# WORK_TAB_NAME = "Work Items"

###############################################################################################################
# Main Functions (UI and helper)
###############################################################################################################

# Load all policies in a thread
def load_policy_analysis_thread():
    """Load Statements in a thread"""
    policy_analysis.load_policies_from_client()

# Enable UI buttons after loading data
def enable_buttons():
    """Light up (enable) Policy filter widgets"""
    entry_subj.config(state=tk.NORMAL)
    entry_loc.config(state=tk.NORMAL)
    entry_res.config(state=tk.NORMAL)
    entry_verb.config(state=tk.NORMAL)
    entry_policy_loc.config(state=tk.NORMAL)
    entry_condition.config(state=tk.NORMAL)
    entry_text.config(state=tk.NORMAL)
    entry_policy.config(state=tk.NORMAL)
    btn_update.config(state=tk.ACTIVE)
    btn_clear.config(state=tk.ACTIVE)
    btn_load.config(state=tk.ACTIVE)
    btn_save.config(state=tk.ACTIVE)
    # btn_cons.config(state=tk.ACTIVE)
    # input_my_user.config(state=tk.ACTIVE)
    # input_my_compartment.config(state=tk.ACTIVE)

    # Dynamic Groups
    dg_entry_domain.config(state=tk.NORMAL)
    dg_entry_name.config(state=tk.NORMAL)
    dg_entry_ocid.config(state=tk.NORMAL)
    dg_entry_type.config(state=tk.NORMAL)
    dg_btn_clear.config(state=tk.ACTIVE)
    dg_btn_update.config(state=tk.ACTIVE)

# Load data from OCI tenancy or cache - kicks off a thread to do this in background
def load_policy_analysis_from_client():
    """Initialize identity client - kicks off a thread"""

    policy_analysis.initialize_client(profile=profile.get(),
                                      use_instance_principal=use_instance_principal.get(),
                                      use_cache=use_cache.get(),
                                      use_recursion=use_recursion.get())

    # Start background thread to load policies
    bg_thread = Thread(target=load_policy_analysis_thread)
    bg_thread.start()

    # Load Dynamic Groups
    dyn_group_analysis.initialize_client(profile.get(), 
                                      use_instance_principal=use_instance_principal.get())
    dyn_group_analysis.load_all_dynamic_groups(use_cache=use_cache.get())

    # Display populate
    update_output()
    update_output_dg()
    enable_buttons()

# Gray or un-gray location tenancy box
def select_location_tenancy():
    """Based on check box for tenancy location, change the checkbox and gray out"""
    
    if location_filter_tenancy.get():
        # only filter for tenancy
        logger.debug("tenancy clicked")
        entry_loc.delete(0, tk.END)
        entry_loc.insert(0,"tenancy")
        entry_loc.config(state=tk.DISABLED)
    else:
        entry_loc.config(state=tk.NORMAL)
        entry_loc.delete(0, tk.END)
        entry_loc.insert(0,"")
    update_output()

# Gray or un-gray subject box
def select_subject_any():
    """Based on check box for tenancy location, change the checkbox and gray out"""
    
    if use_subject_any.get():
        # only filter for tenancy
        logger.debug("any-user clicked")
        entry_subj.delete(0, tk.END)
        entry_subj.insert(0,"any-user|any-group")
        entry_subj.config(state=tk.DISABLED)
    else:
        entry_subj.config(state=tk.NORMAL)
        entry_subj.delete(0, tk.END)
        entry_subj.insert(0,"")
    update_output()

# Gray or un-gray subject box
def select_hierarchy_root():
    """Based on check box for tenancy location, change the checkbox and gray out"""
    
    if hierarchy_filter_root.get():
        # only filter for tenancy
        logger.debug("ROOT clicked")
        entry_policy_loc.delete(0, tk.END)
        entry_policy_loc.insert(0,"ROOT")
        entry_policy_loc.config(state=tk.DISABLED)
    else:
        entry_policy_loc.config(state=tk.NORMAL)
        entry_policy_loc.delete(0, tk.END)
        entry_policy_loc.insert(0,"")
    update_output()

# Process the toggle of Using Instance Principal
def select_instance_principal():
    '''Update variable in class'''

    # Disable UI for selection of profile
    if use_instance_principal.get():
        logger.info("Using Instance Principal - disable profile")
        input_profile.config(state=tk.DISABLED)
    else:
        logger.info("Using Config")
        input_profile.config(state=tk.ACTIVE)

# Clear all filters on Policy View Screen
def clear_filters():
    '''Clears the Policy filters and updates the UI'''

    logger.info(f"Clearing Filters")
    # Clear any disabled fields
    entry_subj.config(state=tk.NORMAL)
    entry_loc.config(state=tk.NORMAL)
    entry_policy_loc.config(state=tk.NORMAL)
    # Remove values
    entry_subj.delete(0, tk.END)
    entry_verb.delete(0, tk.END)
    entry_res.delete(0, tk.END)
    entry_loc.delete(0, tk.END)
    entry_condition.delete(0, tk.END)
    entry_policy_loc.delete(0, tk.END)
    entry_policy.delete(0, tk.END)
    entry_text.delete(0, tk.END)
    # Reset Checkboxes
    use_subject_any.set(False)
    location_filter_tenancy.set(False)
    hierarchy_filter_root.set(False)

    # show_only_my_compartment.set(False)
    # show_only_my_user.set(False)

    # Update the output
    update_output()

# Clear all filters on Dynamic Group View Screen
def clear_filters_dg():
    '''Clears the Dynamic Group Filters and updates the UI'''
    logger.info(f"Clearing DG Filters")
    dg_entry_type.delete(0, tk.END)
    dg_entry_ocid.delete(0, tk.END)
    dg_entry_name.delete(0, tk.END)
    dg_entry_domain.delete(0, tk.END)

    # Update the output
    update_output_dg()

def update_output():
    """Get the filtered policy statements and display them in the grid"""
    # Status Time
    label_status2.config(text=f"Loaded {policy_analysis.data_as_of}")
    # Apply Filters
    regular_statements_filtered = policy_analysis.filter_policy_statements(subj_filter=entry_subj.get(),
                                                                           verb_filter=entry_verb.get(),
                                                                           resource_filter=entry_res.get(),
                                                                           location_filter=entry_loc.get(),
                                                                           hierarchy_filter=entry_policy_loc.get(),
                                                                           condition_filter=entry_condition.get(),
                                                                           policy_filter=entry_policy.get(),
                                                                           text_filter=entry_text.get())

    # TK Sheet
    sheet_policies.data = regular_statements_filtered
    if chk_show_expanded.get():
        # Show all columns
        sheet_policies.display_columns(all_columns_displayed=True)
        #sheet_policies.column_width('displayed',50)
    else:
        sheet_policies.display_columns(columns=[0,3,4], all_columns_displayed=False)
        sheet_policies.column_width(column="displayed", width="text")
        #sheet_policies.set_all_cell_sizes_to_text()

    rows_to_show = []
    for index, statement in enumerate(regular_statements_filtered, start=0):
        # Other / Special / Cross
        if chk_show_special.get() and (statement[6] == "define" or statement[4].startswith("endorse")  or statement[4].startswith("admit")):
            rows_to_show.append(index)
        # Service
        elif chk_show_service.get() and statement[6] == "service":
            rows_to_show.append(index)
        # Dynamic
        elif chk_show_dynamic.get() and statement[6] == "dynamic-group":
            rows_to_show.append(index)
        # Resource
        elif chk_show_resource.get() and statement[6] == "resource":
            rows_to_show.append(index)
        # Regular
        elif chk_show_regular.get() and (statement[6] == "group" or statement[6] == "any-user" or statement[6] == "any-group"):
            rows_to_show.append(index)

        # Look for issues and highlight
        if not statement[5]:
            sheet_policies.highlight_cells(row=index, column='all', bg="pink")

    # Only display the rows in scope
    sheet_policies.display_rows(rows=rows_to_show, all_displayed = False)

    # Clean output and Update Count
    label_loaded.config(text=f"Statements (Filtered): {len(regular_statements_filtered)}\n"+ \
                        f"Statements (Shown): {len(rows_to_show)}"
                        )

def update_output_dg(default_open: bool = False):
    """Get filtered dynamic groups and display them in the grid"""
    # Get the data
    filtered_dynamic_groups = dyn_group_analysis.filter_dynamic_groups(domain_filter=dg_entry_domain.get(),
                                                                       name_filter=dg_entry_name.get(),
                                                                       type_filter=dg_entry_type.get(),
                                                                       ocid_filter=dg_entry_ocid.get()
                                                                       )
    
    # TK Sheet
    sheet_dynamic_group.data = copy.deepcopy(filtered_dynamic_groups)
    sheet_dynamic_group.display_columns(all_columns_displayed=True)

    # Cell to pretty
    for index, statement in enumerate(filtered_dynamic_groups, start=0):
        formatted_rules = "\n".join(statement[4])
        formatted_broken_ocid = "\n".join(statement[6])
        # formatted_rule = policy_print(statement[2], 0)
        # logger.info(f"Formatted rules: {formatted_rule}")

        sheet_dynamic_group.set_cell_data(r=index,
                                          c=4,
                                          value=formatted_rules,
                                          keep_formatting=True)
        sheet_dynamic_group.set_cell_data(r=index,
                                          c=6,
                                          value=formatted_broken_ocid,
                                          keep_formatting=True)
        
        # Look for issues and highlight
        if not statement[5]:
            sheet_dynamic_group.highlight_cells(row=index, column='all', bg="pink")
    # Size it
    sheet_dynamic_group.set_all_cell_sizes_to_text()

    # Update Count
    dg_label_loaded.config(text=f"Statements (Filtered): {len(filtered_dynamic_groups)}")

def update_load_options():
    # Control the load button
    if use_cache.get():
        # Use Cache
        btn_load.config(text="Load Policies and Dynamic Groups from cached values on disk")
        input_recursion.config(state=tk.DISABLED)
    elif use_recursion.get():
        # Load recursively
        input_cache.config(state=tk.DISABLED)
        btn_load.config(text="Load Policies and Dynamic Groups from all compartments")
    else:
        input_cache.config(state=tk.ACTIVE)
        input_recursion.config(state=tk.ACTIVE)
        btn_load.config(text="Load Policies from ROOT compartment only, and Dynamic Groups")

def analyze_dynamic_group():
    # Get name of DG from policy
    current_selection = sheet_policies.get_currently_selected()
    if current_selection:
        logger.info(f"Selected r/c: {current_selection.row} / {current_selection.column}")
        logger.info(f"Selected row data: {sheet_policies.displayed_row_to_data(current_selection.row)}")
        selected_row = sheet_policies.displayed_row_to_data(current_selection.row)
        selected_column = sheet_policies.displayed_column_to_data(current_selection.column)
        subject_type = sheet_policies.data[selected_row][6]
        subject = sheet_policies.data[selected_row][7]
        logger.info(f"Selected data: {sheet_policies.data[selected_row][selected_column]}")

        # Only take action if it is a Dynamic Group
        if subject_type == "dynamic-group":
            # Switch to DG and enable filter
            dg_entry_domain.delete(0, tk.END)
            dg_entry_name.delete(0, tk.END)
            dg_entry_domain.insert(0,subject[0])
            dg_entry_name.insert(0,subject[1])
            tab_control.select(".!notebook.!frame2")
            update_output_dg()

    logger.info(f"Called Dynamic Group analysis")

    # Parse Statement Again

# From the Policy Screen, run the DG exists Analysis
def run_policy_statement_dynamic_group_analysis():
    """Let the Policy class handle this"""
    invalid_list = policy_analysis.check_for_invalid_dynamic_groups(dynamic_groups=dyn_group_analysis.dynamic_groups)

    # Create work statements
    text_work.delete('1.0', tk.END)
    for inv in invalid_list:
        oci_command = f"# Delete Statement incorrect\noci iam policy update --policy-id {inv[0]} --st {inv[1]}\n"
        text_work.insert(tk.END, oci_command)

    update_output()
    logger.info(f"Ran Policy Analysis for DGs not in use: {len(invalid_list)}")

# From the DG Screen, run the DG in use Analysis
def run_dynamic_group_inuse_analysis():
    """Let the DG class handle this"""
    # Set Statements
    dyn_group_analysis.set_statements(policy_analysis.regular_statements)
    # Run the anlaysis
    unused_dynamic_groups = dyn_group_analysis.run_dg_in_use_analysis()

    # Create work statements
    # text_work.delete('1.0', tk.END)
    # for dg in unused_dynamic_groups:
    #     oci_command = f"# Delete Dynamic Group {dg[0]}\noci iam dynamic-group delete --dynamic-group-id {dg[1]}\n"
    #     text_work.insert(tk.END, oci_command)

    update_output_dg()
    logger.info(f"Ran DG In Use Analysis from UI - Unused: {len(unused_dynamic_groups)}")

# From the DG Screen, run the DG in use Analysis
def run_dynamic_group_ocid_analysis():
    """Run in the DG class as a thread"""

    # Set Statements
    dyn_group_analysis.set_statements(policy_analysis.regular_statements)
    # Run the anlaysis in a thread
    bg_thread = Thread(target=dyn_group_analysis.run_deep_analysis)
    bg_thread.start()

    # dyn_group_analysis.run_deep_analysis()

    update_output_dg()
    logger.info(f"Ran DG OCID Analysis from UI")

# Check progress meter for updates
def update_progress():
    logger.debug(f"Called check progress.  Value: {progress.progressbar_val} UI: {progressbar_val.get()}")
    
    # Whatever it is, set to update
    progressbar_val.set(progress.progressbar_val)

    # If the load is done, reset the finished flag
    if policy_analysis.finished:
        update_output()
        policy_analysis.finished = False
        
    
    # Set an event every 1s forever
    window.after(1000, update_progress)

# Load a pre-created filtered result (policies)
def load_file():
    """Load a JSON file from disk"""
    filepath = askopenfilename(
        defaultextension=".json"
    )
    if not filepath:
        return
    
    with open(filepath, mode="r", encoding="utf-8") as input_file:
        text = input_file.read()
    input_json = json.loads(text)

    # Load all policies from filtered file
    policy_analysis.regular_statements = input_json.get("filtered-policy-statements")
    logger.info(f"Loaded saved policies from disk")

    enable_buttons()
    last_loaded_date = input_json.get("save-date")
    entry_subj.insert(0, input_json.get("subject-filter"))
    entry_verb.insert(0, input_json.get("verb-filter"))
    entry_res.insert(0, input_json.get("resource-filter"))
    entry_loc.insert(0, input_json.get("location-filter"))
    entry_condition.insert(0, input_json.get("condition-filter"))
    entry_policy_loc.insert(0, input_json.get("hierarchy-filter"))
    entry_text.insert(0, input_json.get("text-filter"))
    entry_policy.insert(0, input_json.get("policy-name-filter"))
    update_output()

# Save filtered policy statements
def save_file():
    """Save the current tksheet file as a new file."""

    filepath = asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON Files", "*.json"), ("CSV Files", "*.csv")],
    )
    if not filepath:
        return

    # Grab filtered output
    regular_statements_filtered = policy_analysis.filter_policy_statements(subj_filter=entry_subj.get(),
                                                                        verb_filter=entry_verb.get(),
                                                                        resource_filter=entry_res.get(),
                                                                        location_filter=entry_loc.get(),
                                                                        hierarchy_filter=entry_policy_loc.get(),
                                                                        condition_filter=entry_condition.get(),
                                                                        text_filter=entry_text.get(),
                                                                        policy_filter=entry_policy.get())

    # TODO - Filter the output by what is shown after filter?
    # If not, then move the save button higher up

    # TODO - put saved details in here so they can re-load (filter details, time of load)
    save_details = { "save-date" : str(datetime.datetime.now()),
                     "subject-filter" : entry_subj.get(),
                     "verb-filter": entry_verb.get(),
                     "resource-filter": entry_res.get(),
                     "location-filter": entry_loc.get(),
                     "hierarchy-filter": entry_policy_loc.get(),
                     "condition-filter": entry_condition.get(),
                     "text-filter": entry_text.get(),
                     "policy-name-filter": entry_policy.get(),
                     "filtered-policy-statements": regular_statements_filtered
    }

    if filepath.endswith(".json"):
        logger.info(f"JSON Output: {filepath}")
        # Write JSON file using filtered data

        with open(filepath, mode="w", encoding="utf-8") as output_file:
            json_det = json.dumps(save_details, indent=2)
            output_file.write(json_det)

    else:
        logger.info(f"CSV Output: {filepath}")
        # Write CSV file using filtered data
        with open(filepath, 'w', newline='',) as csvfile:
            # Set up CSV
            csv_writer = csv.writer(csvfile)
            csv_writer.writerow(["POLICY_NAME","POLICY_OCID","POLICY_HIERARCHY","STATEMENT_TEXT","STATEMENT_TYPE","STATEMENT_SUBJECT","STATEMENT_VERB", "STATEMENT_RESOURCE", "STATEMENT_PERMISSION", "STATEMENT_LOCATION", "STATEMENT_CONDITIONS", "STATEMENT_COMMENTS"])

            # sheet_span = sheet_policies.span(header=False)
            # sheet_policies.yield_sheet_rows(get_displayed=True)
            # for st in regular_statements_filtered:
            for st in sheet_policies.yield_sheet_rows(get_displayed=True, ):
                logger.debug(f"Sheet data row: {st}")
                csv_writer.writerow([st[0], st[1], st[3], f"{st[4]}", st[6], st[7], st[8], st[9], st[10], st[12], st[13], st[14]])
    logger.info(f"Finished writing file: {filepath}")

def show_detail_dialog():
    current_selection = sheet_policies.get_currently_selected()
    if current_selection:
        logger.info(f"Selected r/c: {current_selection.row} / {current_selection.column}")
        logger.info(f"Selected row data: {sheet_policies.displayed_row_to_data(current_selection.row)}")
        selected_row = sheet_policies.displayed_row_to_data(current_selection.row)
        selected_column = sheet_policies.displayed_column_to_data(current_selection.column)
        subject_type = sheet_policies.data[selected_row][6]
        subject = sheet_policies.data[selected_row][7]
        logger.info(f"Selected data: {sheet_policies.data[selected_row][selected_column]}")

    res = mb.showinfo("Policy Detailed Statement", sheet_policies.data[selected_row][selected_column])
########################################
# Main Code
# Pre-and Post-processing
########################################

if __name__ == "__main__":

    # Parse Arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
    args = parser.parse_args()
    verbose = args.verbose

    # Main Logger
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
    logger = logging.getLogger('oci-policy-analysis-main')

    # Update Logging Level
    if verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger('oci._vendor.urllib3.connectionpool').setLevel(logging.INFO)

    # Grab Profiles
    profile_list = []
    # string to search in file
    try:
        with open(Path.home() / ".oci" / "config", 'r') as fp:
            # read all lines using readline()
            lines = fp.readlines()
            for row in lines:
                if row.find('[') != -1 and row.find(']') != -1:
                    profile_list.append(row[1:-2])
    except FileNotFoundError as e:
        logger.warning(f"Config File not found, must use instance principal: {e}")
        profile_list.append("[NONE]")
    logger.info(f"Profiles: {profile_list}")

    # UI Componentry

    window = tk.Tk()
    window.title("Policy and Dynamic Group Analysis")
    f = font.nametofont("TkDefaultFont")
    f.configure(family="Oracle Sans",
                size=12,
                weight=font.NORMAL)

    # Main Window has 2 rows, top and bottom
    # Top is inputs to load policies
    # Bottom is tabbed display
    window.rowconfigure(2, minsize=800, weight=1)
    window.columnconfigure(0, minsize=800, weight=1)

    # Tab Control (Bottom)
    # User tab - about current user (or search another)
    tab_control = ttk.Notebook(window)
    tab_policy = ttk.Frame(tab_control)
    tab_dg = ttk.Frame(tab_control)
    # tab_work_items = ttk.Frame(tab_control)

    tab_control.add(tab_policy, text=POLICY_TAB_NAME)
    tab_control.add(tab_dg, text=DG_TAB_NAME)
    # tab_control.add(tab_work_items, text=WORK_TAB_NAME)

    logger.debug(f"Tab: {tab_control}")
    
    # Frames
    frm_init = ttk.Frame(window, borderwidth=2)
    frm_policy_top = ttk.Frame(tab_policy, borderwidth=2)
    frm_policy_bottom = ttk.Frame(tab_policy, borderwidth=2)
    frm_filter = ttk.Frame(frm_policy_top, borderwidth=2)
    frm_output = ttk.Frame(frm_policy_top, borderwidth=2)
    frm_actions = ttk.Frame(frm_policy_top, borderwidth=2)
    frm_policy = ttk.Frame(frm_policy_bottom, borderwidth=2)
    frm_dyn_group_filter = ttk.Frame(tab_dg, borderwidth=2)
    frm_dyn_group_actions = ttk.Frame(tab_dg, borderwidth=2)
    frm_dyn_group_output = ttk.Frame(tab_dg, borderwidth=2)

    # Inputs
    use_instance_principal = tk.BooleanVar()
    input_use_ip = ttk.Checkbutton(frm_init, text='Instance Principal', variable=use_instance_principal, command=select_instance_principal)
    input_use_ip.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=3)

    # Profile drop-down
    label_profile = tk.Label(master=frm_init, text="Choose Profile")
    label_profile.grid(row=1, column=0, sticky="ew", padx=10, pady=3)

    # If no profiles, force instance
    profile = tk.StringVar(window)
    profile.set(profile_list[0]) 
    input_profile = ttk.OptionMenu(frm_init, profile, *profile_list)
    if "NONE" in profile_list[0]:
        use_instance_principal.set(True)
        input_profile.config(state=tk.DISABLED)
    input_profile.grid(row=1, column=1, sticky="ew", padx=10, pady=3)

    #Caching
    use_cache = tk.BooleanVar()
    input_cache = ttk.Checkbutton(frm_init, text='Use Cache?', variable=use_cache, command=update_load_options)
    input_cache.grid(row=0, column=2, columnspan=2, sticky="ew", padx=25, pady=3)

    # Recursion
    use_recursion = tk.BooleanVar()
    input_recursion= ttk.Checkbutton(frm_init, text='Recursion?', variable=use_recursion, command=update_load_options)
    input_recursion.grid(row=1, column=2, columnspan=2, sticky="ew", padx=25, pady=3)

    # Init Button
    btn_load = ttk.Button(frm_init, width=50, text="Load Policies and Dynamic Groups from ROOT compartment only", command=load_policy_analysis_from_client)
    btn_load.grid(row=0, column=4, rowspan=2, sticky="ew", padx=25)

    # Status Area
    label_status1 = ttk.Label(master=frm_init, text="Status:")
    label_status1.grid(row=0, column=5, sticky="ew", padx=5)
    label_status2 = ttk.Label(master=frm_init, text="Not Loaded")
    label_status2.grid(row=1, column=5, sticky="ew", padx=5)

    # Progress Bar
    # global progressbar_val
    progressbar_val = tk.IntVar()
    progressbar = ttk.Progressbar(orient=tk.HORIZONTAL, length=400, mode="determinate", maximum=100,variable=progressbar_val)
    progressbar.place(x=450, y=50)

    # Filters
    label_filter = tk.Label(master=frm_filter, text="Filters - Each filter supports | as OR.  Filters are AND.\nPolicy Syntax: allow <subject> to <verb> <resource> in <location> where <conditions> // Policy Comment")
    label_filter.grid(row=0, column=0, sticky="ew", columnspan=4, padx=5, pady=2)

    # Special Inner Frame for Subject / any
    frm_subj = ttk.Frame(frm_filter)

    label_subj = ttk.Label(master=frm_filter, text="Subject\n(group name)")
    label_subj.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
    entry_subj = ttk.Entry(master=frm_subj, state=tk.DISABLED, width=30)
    entry_subj.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

    use_subject_any = tk.BooleanVar()
    input_location_filter_tenancy = ttk.Checkbutton(frm_subj, text='Any-User/Any-Group', variable=use_subject_any, command=select_subject_any)
    input_location_filter_tenancy.grid(row=0, column=1, sticky="ew", padx=1, pady=1)

    # add the subject box to grid
    frm_subj.grid(row=1, column=1, sticky="ew")

    label_verb = ttk.Label(master=frm_filter, text="Verb\n(inspect/read/use/manage)")
    label_verb.grid(row=1, column=2, sticky="ew", padx=5, pady=2)
    entry_verb = ttk.Entry(master=frm_filter, state=tk.DISABLED, width=40)
    entry_verb.grid(row=1, column=3, sticky="ew", padx=5, pady=2)

    label_res = ttk.Label(master=frm_filter, text="Resource\n(name/family)")
    label_res.grid(row=2, column=0, sticky="ew", padx=5, pady=2)
    entry_res = ttk.Entry(master=frm_filter, state=tk.DISABLED, width=40)
    entry_res.grid(row=2, column=1, sticky="ew", padx=5, pady=2)

    label_loc = ttk.Label(master=frm_filter, text="Location\n(within statement)")
    label_loc.grid(row=2, column=2, sticky="ew", padx=5, pady=2)

    # Special Inner Frame for location / tenancy
    frm_location = ttk.Frame(frm_filter)

    entry_loc = ttk.Entry(master=frm_location, state=tk.DISABLED, width=30)
    entry_loc.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

    location_filter_tenancy = tk.BooleanVar()
    input_location_filter_tenancy = ttk.Checkbutton(frm_location, text='Tenancy', variable=location_filter_tenancy, command=select_location_tenancy)
    input_location_filter_tenancy.grid(row=0, column=1, sticky="ew", padx=1, pady=1)

    frm_location.grid(row=2, column=3, sticky="ew")

    # Special Inner Frame for location / tenancy
    frm_hierarchy = ttk.Frame(frm_filter)

    label_policy_loc = ttk.Label(master=frm_filter, text="Compartment\n(policy location)")
    label_policy_loc.grid(row=3, column=0, sticky="ew", padx=5, pady=2)
    entry_policy_loc = ttk.Entry(master=frm_hierarchy, state=tk.DISABLED, width=30)
    entry_policy_loc.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
       
    hierarchy_filter_root = tk.BooleanVar()
    input_hierarchy_filter = ttk.Checkbutton(frm_hierarchy, text='Root Only', variable=hierarchy_filter_root, command=select_hierarchy_root)
    input_hierarchy_filter.grid(row=0, column=1, sticky="ew", padx=1, pady=1)

    frm_hierarchy.grid(row=3, column=1, sticky="ew")

    label_condition = ttk.Label(master=frm_filter, text="Conditions\n(where clause)")
    label_condition.grid(row=3, column=2, sticky="ew", padx=5, pady=2)
    entry_condition = ttk.Entry(master=frm_filter, state=tk.DISABLED, width=40)
    entry_condition.grid(row=3, column=3, sticky="ew", padx=5, pady=2)

    label_text = ttk.Label(master=frm_filter, text="Statement Text\n(anywhere in statement)")
    label_text.grid(row=4, column=0, sticky="ew", padx=5, pady=2)
    entry_text = ttk.Entry(master=frm_filter, state=tk.DISABLED, width=40)
    entry_text.grid(row=4, column=1, sticky="ew", padx=5, pady=2)

    label_policy = ttk.Label(master=frm_filter, text="Policy Name")
    label_policy.grid(row=4, column=2, sticky="ew", padx=5, pady=2)
    entry_policy = ttk.Entry(master=frm_filter, state=tk.DISABLED, width=40)
    entry_policy.grid(row=4, column=3, sticky="ew", padx=5, pady=2)

    btn_clear = ttk.Button(frm_filter, text="Clear Filters", state=tk.DISABLED, command=clear_filters)
    btn_clear.grid(row=1, column=4, sticky="ew", padx=5, pady=2)
    btn_update = ttk.Button(frm_filter, text="Update Filter", state=tk.DISABLED, command=update_output)
    btn_update.grid(row=2, column=4, sticky="ew", padx=5, pady=2)
    btn_file_load = ttk.Button(master=frm_filter, text="Load Filtered (File)", command=load_file)
    btn_file_load.grid(row=3, column=4, sticky="ew", padx=5, pady=2)    
    btn_save = ttk.Button(master=frm_filter, text="Save Filtered (File)", state=tk.DISABLED, command=save_file)
    btn_save.grid(row=4, column=4, sticky="ew", padx=5, pady=2)

    separator = ttk.Separator(frm_policy_top, orient=tk.HORIZONTAL)
    separator.grid(row=5, column=0, columnspan=4)

    # Output Show
    label_loaded = ttk.Label(master=frm_output, text="Statements Loaded (No Filter): ")
    label_loaded.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=3)
    chk_show_special = tk.BooleanVar()
    chk_show_dynamic = tk.BooleanVar()
    chk_show_service = tk.BooleanVar()
    chk_show_resource = tk.BooleanVar()
    chk_show_regular = tk.BooleanVar(value=True)
    chk_show_expanded = tk.BooleanVar(value=False)
    show_special = ttk.Checkbutton(frm_output, text='Show Cross-Tenancy', variable=chk_show_special, command=update_output)
    show_dynamic = ttk.Checkbutton(frm_output, text='Show Dynamic', variable=chk_show_dynamic, command=update_output)
    show_service = ttk.Checkbutton(frm_output, text='Show Service', variable=chk_show_service, command=update_output)
    show_resource = ttk.Checkbutton(frm_output, text='Show Resource', variable=chk_show_resource, command=update_output)
    show_regular = ttk.Checkbutton(frm_output, text='Show Regular', variable=chk_show_regular, command=update_output)
    show_expanded = ttk.Checkbutton(frm_output, text='Expanded View?', variable=chk_show_expanded, command=update_output)
    show_special.grid(row=0, column=2, sticky="ew", padx=15, pady=3)
    show_dynamic.grid(row=0, column=3, sticky="ew", padx=15, pady=3)
    show_service.grid(row=0, column=4, sticky="ew", padx=15, pady=3)
    show_resource.grid(row=0, column=5, sticky="ew", padx=15, pady=3)
    show_regular.grid(row=0, column=6, sticky="ew", padx=15, pady=3)
    show_expanded.grid(row=0, column=7, sticky="ew", padx=15, pady=3)

    # Define dg button but don't place it
    btn_statement_dg_valid = ttk.Button(master=frm_output, text="Analyze Dynamic Group Statements", state=tk.ACTIVE, command=run_policy_statement_dynamic_group_analysis)
    btn_statement_dg_valid.grid(row=0, column=8, sticky="ew", padx=5, pady=3)
    
    ##################################
    # Dynamic Groups Tab
    # Filters
    dg_label_filter = ttk.Label(master=frm_dyn_group_filter, text="Filters (Each filter supports | as OR) - Dynamic Group has Name and matching statements")
    dg_label_filter.grid(row=0, column=0, sticky="ew", columnspan=4, padx=5, pady=3)

    dg_label_domain = ttk.Label(master=frm_dyn_group_filter, text="Dynamic Group Domain")
    dg_label_domain.grid(row=1, column=0, sticky="ew", padx=5, pady=3)
    dg_entry_domain = tk.Entry(master=frm_dyn_group_filter, state=tk.DISABLED, width=40)
    dg_entry_domain.grid(row=1, column=1, sticky="ew", padx=5, pady=3)

    dg_label_name = ttk.Label(master=frm_dyn_group_filter, text="Dynamic Group Name")
    dg_label_name.grid(row=1, column=2, sticky="ew", padx=5, pady=3)
    dg_entry_name = tk.Entry(master=frm_dyn_group_filter, state=tk.DISABLED, width=40)
    dg_entry_name.grid(row=1, column=3, sticky="ew", padx=5, pady=3)

    dg_label_type = ttk.Label(master=frm_dyn_group_filter, text="Statement type\nresource/compartment/instance etc")
    dg_label_type.grid(row=2, column=0, sticky="ew", padx=5, pady=3)
    dg_entry_type = tk.Entry(master=frm_dyn_group_filter, state=tk.DISABLED, width=40)
    dg_entry_type.grid(row=2, column=1, sticky="ew", padx=5, pady=3)

    dg_label_ocid = ttk.Label(master=frm_dyn_group_filter, text="Matching Rule OCID\n(any part of OCID within)")
    dg_label_ocid.grid(row=2, column=2, sticky="ew", padx=5, pady=3)
    dg_entry_ocid = tk.Entry(master=frm_dyn_group_filter, state=tk.DISABLED, width=40)
    dg_entry_ocid.grid(row=2, column=3, sticky="ew", padx=5, pady=3)

    dg_btn_update = ttk.Button(frm_dyn_group_filter, text="Update Filter", state=tk.DISABLED, command=update_output_dg)
    dg_btn_update.grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=3)
    dg_btn_clear = ttk.Button(frm_dyn_group_filter, text="Clear Filters", state=tk.DISABLED, command=clear_filters_dg)
    dg_btn_clear.grid(row=3, column=2, columnspan=2, sticky="ew", padx=5, pady=3)

    dg_separator = ttk.Separator(frm_dyn_group_filter, orient=tk.HORIZONTAL)
    dg_separator.grid(row=4, column=0, sticky="ew", columnspan=4)

    # DG Actions
    dg_label_loaded = ttk.Label(master=frm_dyn_group_actions, text="Statements Loaded: ")
    dg_label_loaded.grid(row=0, column=0, sticky="ew", padx=5, pady=3)

    btn_dyn_group_inuse_analysis = ttk.Button(master=frm_dyn_group_actions, text="Run In Use Analysis", command=run_dynamic_group_inuse_analysis)
    btn_dyn_group_ocid_analysis = ttk.Button(master=frm_dyn_group_actions, text="Run OCID Analysis", command=run_dynamic_group_ocid_analysis)

    btn_dyn_group_inuse_analysis.grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=3)
    btn_dyn_group_ocid_analysis.grid(row=0, column=3, columnspan=2, sticky="ew", padx=5, pady=3)

    # DG Bottom Frame
    sheet_policies = Sheet(parent=frm_policy,
                           theme="light green",
                        #    data=[[f"Row {r}, Column {c}" for c in range(10)] for r in range(100)],
                           font=("PT Mono", 11, "normal"),
                           header_font=("Oracle Sans", 12, "bold"),
                           index_font=("Oracle Sans", 12, "bold"),
                        #    displayed_columns=([0,3,4], False),
                           headers=("Policy Name","Policy OCID","Compartment OCID","Hierarchy","Statement Text", "Valid",
                                    "Subject Type","Subject","Verb","Resource","Permission","Location Type","Location",
                                    "Conditions","Comments","Creation Time"),
                           )
    
    sheet_policies.set_options(auto_resize_columns=150)
    sheet_policies.enable_bindings("column_width_resize",  # Allow column resize
                                   "single_select", # Allow single cell select
                                   "ctrl_click_select", # Allow ctrl select
                                   "ctrl_select", 
                                   "right_click_popup_menu", # Right click menu
                                   "copy", # Copy/paste
                                   "shift_cell_select", # Shift Cell
                                   "row_select" # Select rows
    )
    sheet_policies.popup_menu_add_command("Analyze Dynamic Group", analyze_dynamic_group)    # Insert to main window
    sheet_policies.popup_menu_add_command("Show Details", show_detail_dialog)    # Insert to main window
    sheet_policies.pack(expand=True, fill=tk.BOTH, side= tk.TOP)

    sheet_dynamic_group = Sheet(parent=frm_dyn_group_output,
                           theme="light blue",
                        #    data=[[f"Row {r}, Column {c}" for c in range(10)] for r in range(100)],
                           font=("PT Mono", 11, "normal"),
                           header_font=("Oracle Sans", 12, "bold"),
                           index_font=("Oracle Sans", 12, "bold"),
                           headers=("Dynamic Group Domain", "Dynamic Group Name","Dynamic Group OCID","Matching Statement","Rule Component","DG In Use", "Invalid OCIDs", "Creation Time")
    )
    
    sheet_dynamic_group.set_options(auto_resize_columns=175)
    sheet_dynamic_group.enable_bindings("column_width_resize",  # Allow column resize
                                   "single_select", # Allow single cell select
                                   "ctrl_click_select", # Allow ctrl select
                                   "ctrl_select", 
                                   "right_click_popup_menu", # Right click menu
                                   "copy", # Copy/paste
                                   "shift_cell_select" # Shift Cell
    )
    sheet_dynamic_group.pack(expand=True, fill=tk.BOTH, side= tk.TOP)

    frm_init.pack(expand=False, fill=tk.X, side=tk.TOP)
    frm_filter.grid(row=0, column=0, sticky="nsew")
    separator.grid(row=1, column=0, sticky="nsew")
    frm_output.grid(row=2, column=0, sticky="nsew")
    frm_actions.grid(row=3, column=0, sticky="nsew")
    frm_policy.pack(expand=True, fill=tk.BOTH)
    frm_policy_top.pack(expand=False, fill=tk.BOTH)
    frm_policy_bottom.pack(expand=True, fill=tk.BOTH, side=tk.TOP)
    frm_dyn_group_filter.pack(expand=False, fill=tk.BOTH)
    frm_dyn_group_actions.pack(expand=False, fill=tk.BOTH)
    frm_dyn_group_output.pack(expand=True, fill=tk.BOTH)
 
    # # Work Items Tab
    # text_work = ttk.Text(master=tab_work_items, font="TkFixedFont")
    # text_work.pack(expand=True, fill=tk.BOTH)

    # Add tabs
    tab_control.pack(expand=True, fill=tk.BOTH)

    # Create the worker classes
    progress = Progress(progress_val=0)
    policy_analysis = PolicyAnalysis(progress=progress,
                                     verbose=verbose)
    dyn_group_analysis = DynamicGroupAnalysis(progress=progress, 
                                              verbose=verbose)

    # Start updating Progress Meter, using loop
    update_progress()

    # Main Loop
    window.mainloop()
