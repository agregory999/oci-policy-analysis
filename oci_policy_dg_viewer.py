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
import logging
import sys
from pathlib import Path
from threading import Thread

from oci_policy_dg_core import PolicyCompartmentAnalysis, IdentityDomainsAnalysis

# Third-party imports
import oci
import tkinter as tk
import tkinter.filedialog as tkfiledialog
import tksheet
import ttkbootstrap as ttk

from tkinter import messagebox

# Constants
THREADS = 8

# Global variables
last_error = ""

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s'
)
logger = logging.getLogger('oci-policy-dg-viewer')

### Main Code Helpers

def parse_args():
    parser = argparse.ArgumentParser(description='OCI Policy and Dynamic Group Viewer')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    return parser.parse_args()

def clear_policy_filters():
    for entry in [entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy, entry_condition, entry_text, entry_policy]:
        entry.delete(0, tk.END)
    use_subject_any.set(False)
    location_filter_tenancy.set(False)
    hierarchy_filter_root.set(False)
    update_policy_output()

def clear_dg_filters():
    for entry in [dg_entry_domain, dg_entry_name, dg_entry_type, dg_entry_ocid]:
        entry.delete(0, tk.END)
    update_dg_output()

def toggle_any_subject():
    if use_subject_any.get():
        entry_subj.insert(0, "any-user|any-group")
        entry_subj.config(state=tk.DISABLED)
    else:
        entry_subj.config(state=tk.NORMAL)
        entry_subj.delete(0, tk.END)

    # Update the Output
    update_policy_output()

def toggle_location_tenancy():
    if location_filter_tenancy.get():
        entry_loc.delete(0, tk.END)
        entry_loc.insert(0, "tenancy")
        entry_loc.config(state=tk.DISABLED)
    else:
        entry_loc.config(state=tk.NORMAL)
        entry_loc.delete(0, tk.END)
    
    
        
    
    # Update the output
    update_policy_output()

def toggle_hierarchy_root():
    if hierarchy_filter_root.get():
        entry_hierarchy.delete(0, tk.END)
        entry_hierarchy.insert(0, "ROOT")
        entry_hierarchy.config(state=tk.DISABLED)
    else:
        entry_hierarchy.config(state=tk.NORMAL)
        entry_hierarchy.delete(0, tk.END)

    # Update the Output
    update_policy_output()

def update_report_output():
    text_dg_report.delete(1.0, tk.END)
    text_policy_report.delete(1.0, tk.END)
    sorted_dgs = sorted(identity_domain_analysis.dynamic_groups, key=lambda x: (x[0], x[1]))
    dg_text = "Dynamic Groups Report\n====================\n"
    if not sorted_dgs:
        dg_text += "No dynamic groups found.\n"
    else:
        for dg in sorted_dgs:
            dg_text += f"Domain: {dg[0]}\nName: {dg[1]}\nMatching Rule: {dg[2]}\nOCID: {dg[4]}\nCreated: {dg[5]}\nIn Use: {'Yes' if dg[3] else 'No'}\n\n"
    text_dg_report.config(state=tk.NORMAL)
    text_dg_report.insert(tk.END, dg_text)
    text_dg_report.config(state=tk.DISABLED)
    
    sorted_comps = sorted(policy_compartment_analysis.compartments, key=lambda x: x["hierarchy_path"])
    policy_text = "Compartment and Policy Report\n============================\n"
    if not sorted_comps:
        policy_text += "No compartments or policies found.\n"
    else:
        for comp in sorted_comps:
            policy_text += f"Compartment: {comp['hierarchy_path']} (OCID: {comp['id']})\n"
            statements = [s for s in policy_compartment_analysis.regular_statements if s[2] == comp['id']]
            if statements:
                policy_dict = {}
                for s in statements:
                    policy_name = s[0]
                    policy_ocid = s[1]
                    if policy_name not in policy_dict:
                        policy_dict[policy_name] = {"ocid": policy_ocid, "statements": []}
                    policy_dict[policy_name]["statements"].append(s[4])
                for policy_name, data in sorted(policy_dict.items()):
                    policy_text += f"  Policy: {policy_name} (OCID: {data['ocid']})\n"
                    for i, stmt in enumerate(data["statements"], 1):
                        policy_text += f"    {i}. {stmt}\n"
            else:
                policy_text += "  No policies\n"
            policy_text += "\n"
    text_policy_report.config(state=tk.NORMAL)
    text_policy_report.insert(tk.END, policy_text)
    text_policy_report.config(state=tk.DISABLED)
    logger.info("Updated Policy/Dynamic Group Report tab")
 
def update_policy_output():
    filtered = policy_compartment_analysis.filter_policy_statements(
        entry_subj.get(), entry_verb.get(), entry_res.get(), entry_loc.get(),
        entry_hierarchy.get(), entry_condition.get(), entry_text.get(), entry_policy.get()
    )
    label_status_bar.config(text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                                f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                                f"tksheet: {tksheet.__version__} | Loaded as of: {policy_compartment_analysis.data_as_of}")
    sheet_policies.set_sheet_data(filtered, reset_highlights=True)
    sheet_policies.display_columns(
        all_columns_displayed=True if chk_show_expanded.get() else False,
        columns=[0, 3, 4] if not chk_show_expanded.get() else None
    )
    # Display Output
    rows_to_show = [
        i for i, st in enumerate(filtered)
        if (chk_show_service.get() and st[6] == "service"
            or chk_show_dynamic.get() and st[6] == "dynamic-group"
            or chk_show_resource.get() and st[6] == "resource"
            or chk_show_regular.get() and st[6] in ["group", "any-user", "any-group"]
            or chk_show_invalid.get() and not st[5])
    ]
    label_policy_count.config(text=f"Statements (Filtered): {len(filtered)}\nStatements (Shown): {len(rows_to_show)}")
    if rows_to_show and len(rows_to_show) == 0:
        
        sheet_policies.display_rows(rows=[], all_rows_displayed=False, redraw=True)
        logger.info(f"Clearing sheet because there are {len(rows_to_show)} rows to display")
    else:
        sheet_policies.display_rows(rows=rows_to_show, 
                                    all_rows_displayed=False)
        
    logger.info(f"Displaying {len(rows_to_show)} rows on sheet")

    # Resize to text
    sheet_policies.set_all_cell_sizes_to_text()

def format_dgrule(text, indent_level=0):
    """
    Recursively formats the input language string with 2-space indentation.
    
    Args:
        text (str): The input language string to format
        indent_level (int): Current indentation level (default: 0)
    
    Returns:
        str: Formatted string with newlines and 2-space indentation
    """
    result = []
    current = ""
    i = 0
    while i < len(text):
        char = text[i]
        
        if char == '{':
            result.append("  " * indent_level + current.strip() + " {")
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
            current = ""
            continue
        elif char == '}':
            if current.strip():
                result.append("  " * indent_level + current.strip())
            result.append("  " * indent_level + "}")
            current = ""
        elif char == ',':
            if current.strip():
                result.append("  " * indent_level + current.strip())
            current = ""
        else:
            current += char
        i += 1
    
    if current.strip():
        result.append("  " * indent_level + current.strip())
    
    return "\n".join(line for line in result if line.strip())

def update_dg_output():
    if chk_show_instance_principals.get():
        dg_entry_type.delete(0,tk.END)
        dg_entry_type.insert(0,"instance.compartment.id|instance.id")

    filtered = identity_domain_analysis.filter_dynamic_groups(
        dg_entry_domain.get() if dg_entry_domain.get() != "" else None, 
        dg_entry_name.get() if dg_entry_name.get() != "" else None, 
        dg_entry_type.get() if dg_entry_type.get() != "" else None, 
        dg_entry_ocid.get() if dg_entry_ocid.get() != "" else None
    )
    sheet_dynamic_group.display_columns(all_columns_displayed=True)
    for i, dg in enumerate(filtered):
        dg[2] = format_dgrule(dg[2],0)

    sheet_dynamic_group.set_sheet_data(filtered, reset_highlights=True)
    sheet_dynamic_group.set_all_cell_sizes_to_text()
    dg_label_count.config(text=f"Dynamic Groups (Filtered): {len(filtered)} \n ")

    filtered_stage2:int = 0

    if chk_show_not_in_use.get():
        run_dg_analysis()
        for i, dg in enumerate(filtered):
            if not dg[3]:
                filtered_stage2 += 1
                sheet_dynamic_group.highlight_rows(rows=[i],bg="red")
                # filtered_stage2.append(dg)
        # sheet_dynamic_group.display_columns(all_columns_displayed=False, columns=[0,1,5])
        # sheet_dynamic_group.set_sheet_data(filtered_stage2, reset_highlights=True)
        dg_label_count.config(text=f"Dynamic Groups (Highlighted): {filtered_stage2}")

def update_user_analysis_output():
    domain_id = domain_var.get()
    user_id = user_var.get()
    compartment_id = compartment_var.get()
    if domain_id == "None" or user_id == "None":
        sheet_user_policies.set_sheet_data([], reset_highlights=True)
        user_label_count.config(text="Policy Statements (Filtered): 0")
        update_selection_info()
        return

    filtered = policy_compartment_analysis.get_user_group_statements(
        user_id = user_id, 
        compartment_id = compartment_id if compartment_id != "All Compartments" else None,
        user_group_names=identity_domain_analysis.get_user_groups(domain_id, user_id),
        user_domain_name=identity_domain_analysis.get_domain_name_by_id(domain_id))
    sheet_user_policies.set_sheet_data(filtered, reset_highlights=True)
    sheet_user_policies.set_all_cell_sizes_to_text()
    sheet_user_policies.display_columns(
        all_columns_displayed=True if chk_show_expanded.get() else False,
        columns=[0, 3, 4] if not chk_show_expanded.get() else None
    )

    user_label_count.config(text=f"Policy Statements (Filtered): {len(filtered)}")
    update_selection_info()

def update_cross_tenancy_output():
    logger.debug(f"cross: {len(policy_compartment_analysis.cross_tenancy_statements)}")
    defined_aliases = policy_compartment_analysis.defined_aliases
    alias_list = []
    for alias in defined_aliases:
        logger.debug(f"Alias {alias}: {defined_aliases[alias]}")
        alias_list.append([alias,defined_aliases[alias][0], defined_aliases[alias][1]])
    sheet_cross_tenancy_define.set_sheet_data(alias_list)
    sheet_cross_tenancy_policies.display_columns(columns=[0,1,10,11], all_columns_displayed=False)
    sheet_cross_tenancy_policies.set_sheet_data(policy_compartment_analysis.cross_tenancy_statements)
    sheet_cross_tenancy_policies.set_all_cell_sizes_to_text()

def update_cross_tenancy_alias_selection(row):
    selected_rows = sheet_cross_tenancy_define.get_selected_rows()
    if selected_rows:
        aliases_to_filter = []
        for idx in selected_rows:
            # selected_idx = list(selected_rows)
            alias = sheet_cross_tenancy_define.get_cell_data(r=idx, c=0)
            logger.debug(f"Selected row {idx} - Using alias {alias} for search in policies")
            aliases_to_filter.append(alias)

        logger.debug(f"Using aliases {aliases_to_filter} for search in policies")
        # Filter bottom sheet
        filtered = policy_compartment_analysis.filter_cross_tenancy_policy_statements(alias_filter=aliases_to_filter)
        sheet_cross_tenancy_policies.set_sheet_data(filtered, redraw=True)
    else:
        logger.debug("no row selected")

def update_selection_info():
    domain_id = domain_var.get()
    user_id = user_var.get()
    compartment_id = compartment_var.get()
    domain_display = next((d['display_name'] for d in identity_domain_analysis.get_domains() if d['id'] == domain_id), "None") if domain_id != "None" else "None"
    user_display = next((u['display_name'] for u in identity_domain_analysis.get_users_by_domain(domain_id) if u['id'] == user_id), "None") if user_id != "None" else "None"
    compartment_display = next((c["hierarchy_path"] for c in policy_compartment_analysis.compartments if c["id"] == compartment_id), "All Compartments") if compartment_id != "All Compartments" else "All Compartments"
    selection_info = f"Domain: {domain_display} ({domain_id})\nUser: {user_display} ({user_id})\nUser groups: {identity_domain_analysis.get_user_groups(domain_id=domain_id, user_id=user_id)}\nCompartment: {compartment_display} ({compartment_id})"
    text_user_details.delete(1.0, tk.END)
    text_user_details.insert(1.0, selection_info)

def sort_sheet_cross_tenancy_define(col):
    global sheet_cross_tenancy_define_search_order
    logger.debug(f"Sorting Cross-tenancy Define reverse={sheet_cross_tenancy_define_search_order}")
    seleced_column_index = col['selected'].column
    sheet_cross_tenancy_define.sort_rows_by_column(column=seleced_column_index, reverse=sheet_cross_tenancy_define_search_order)
    sheet_cross_tenancy_define_search_order = True if not sheet_cross_tenancy_define_search_order else False

def sort_sheet_cross_tenancy_policies(col):
    global sheet_cross_tenancy_policies_search_order
    logger.debug(f"Sorting Cross-tenancy Output reverse={sheet_cross_tenancy_policies_search_order}")
    seleced_column_index = col['selected'].column
    sheet_cross_tenancy_policies.sort_rows_by_column(column=seleced_column_index, reverse=sheet_cross_tenancy_policies_search_order)
    sheet_cross_tenancy_policies_search_order = True if not sheet_cross_tenancy_policies_search_order else False

def export_policy_to_csv():
    filepath = tkfiledialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    if filepath:
        filtered = policy_compartment_analysis.filter_policy_statements(
            entry_subj.get(), entry_verb.get(), entry_res.get(), entry_loc.get(),
            entry_hierarchy.get(), entry_condition.get(), entry_text.get(), entry_policy.get()
        )
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(sheet_policies.headers())
            writer.writerows(filtered)
        logger.info(f"Exported {len(filtered)} policy statements to {filepath}")

def export_dg_to_csv():
    filepath = tkfiledialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    if filepath:
        filtered = identity_domain_analysis.filter_dynamic_groups(
            dg_entry_domain.get(), dg_entry_name.get(), dg_entry_type.get(), dg_entry_ocid.get()
        )
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(sheet_dynamic_group.headers())
            writer.writerows(filtered)
        logger.info(f"Exported {len(filtered)} dynamic groups to {filepath}")

def export_user_to_csv():
    filepath = tkfiledialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    if filepath:
        domain_id = domain_var.get()
        user_id = user_var.get()
        compartment_id = compartment_var.get()
        filtered = policy_compartment_analysis.get_user_group_statements(user_id, domain_id, compartment_id if compartment_id != "All Compartments" else None)
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(sheet_user_policies.headers())
            writer.writerows(filtered)
        logger.info(f"Exported {len(filtered)} user policy statements to {filepath}")

def export_report_to_txt():
    import tkinter.filedialog as fd
    filepath = fd.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
    if filepath:
        dg_content = text_dg_report.get(1.0, tk.END).strip()
        policy_content = text_policy_report.get(1.0, tk.END).strip()
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(dg_content + "\n\n" + policy_content)
        logger.info(f"Exported report to {filepath}")

def run_dg_analysis():
    logger.info(f"Running Dynamic Group Analysis for {len(identity_domain_analysis.dynamic_groups)} DGs and {len(policy_compartment_analysis.regular_statements)} Policies")
    identity_domain_analysis.set_statements(policy_compartment_analysis.regular_statements)
    identity_domain_analysis.run_dg_in_use_analysis()
    # update_dg_output()

def report_text_search(var_name, index, mode):
    if highlight_entry_var:
        search_pattern = highlight_entry_var.get()
        logger.debug(f"Search for {search_pattern} - {var_name}/{index}/{mode}")
        text_dg_report.tag_remove("found", "1.0", tk.END)
        text_policy_report.tag_remove("found", "1.0", tk.END)
        if highlight_entry_var.get() == "":
            return
        
        # If there was a highlight, do it for both
        start_index = "1.0"
        while True:
            pos = text_dg_report.search(search_pattern, start_index, tk.END, nocase=True)
            if not pos:
                break
            end_index = f"{pos}+{len(search_pattern)}c"
            text_dg_report.tag_add("found", pos, end_index)
            start_index = end_index
        text_dg_report.tag_config("found", background="yellow")

        start_index = "1.0"
        while True:
            pos = text_policy_report.search(search_pattern, start_index, tk.END, nocase=True)
            if not pos:
                break
            end_index = f"{pos}+{len(search_pattern)}c"
            text_policy_report.tag_add("found", pos, end_index)
            start_index = end_index
        text_policy_report.tag_config("found", background="yellow")

def toggle_profile_dropdown():
    if use_instance_principal.get():
        input_profile.config(state=tk.DISABLED)
        label_profile.config(state=tk.DISABLED)
    else:
        input_profile.config(state=tk.NORMAL)
        label_profile.config(state=tk.NORMAL)

def update_user_dropdown():
    domain_id = domain_var.get()
    users = ["None"]
    if domain_id != "None":
        users = [u['display_name'] for u in sorted(identity_domain_analysis.get_users_by_domain(domain_id), key=lambda x: x['display_name'])]
        if not users:
            users = ["None"]
    user_dropdown["menu"].delete(0, tk.END)
    user_var.set("None")
    for user in users:
        user_id = next((u['id'] for u in identity_domain_analysis.get_users_by_domain(domain_id) if u['display_name'] == user), "None") if user != "None" else "None"
        user_dropdown["menu"].add_command(label=user, command=lambda u=user, uid=user_id: [user_var.set(uid), user_display_var.set(u), update_user_analysis_output()])
    update_user_analysis_output()

def update_domain_dropdown():
    domains = ["None"] + [d['display_name'] for d in sorted(identity_domain_analysis.get_domains(), key=lambda x: x['display_name'])]
    domain_dropdown["menu"].delete(0, tk.END)
    domain_var.set("None")
    domain_display_var.set("None")
    for domain in domains:
        domain_id = next((d['id'] for d in identity_domain_analysis.get_domains() if d['display_name'] == domain), "None") if domain != "None" else "None"
        domain_dropdown["menu"].add_command(label=domain, command=lambda d=domain, did=domain_id: [domain_var.set(did), domain_display_var.set(d), update_user_dropdown()])
    update_user_dropdown()

def update_compartment_dropdown():
    compartments = ["All Compartments"] + [c["hierarchy_path"] for c in sorted(policy_compartment_analysis.compartments, key=lambda x: x["hierarchy_path"])]
    compartment_dropdown["menu"].delete(0, tk.END)
    compartment_var.set("All Compartments")
    compartment_display_var.set("All Compartments")
    for compartment in compartments:
        compartment_id = next((c["id"] for c in policy_compartment_analysis.compartments if c["hierarchy_path"] == compartment), "All Compartments") if compartment != "All Compartments" else "All Compartments"
        compartment_dropdown["menu"].add_command(label=compartment, command=lambda c=compartment, cid=compartment_id: [compartment_var.set(cid), compartment_display_var.set(c), update_user_analysis_output()])
    update_user_analysis_output()

def update_principals_sheets(*args):
    """Update sheets based on dropdown selections and dynamic group selection."""
    principals_style = principals_style_var.get()
    resource_type = resource_type_var.get()
    
    # Enable/disable Resource Type dropdown
    resource_type_dropdown.configure(state="normal")
    
    # Enable/disable Principals Style
    principals_style_dropdown.configure(state="normal")

    # Clear sheets and hide both sheets by default
    principals_sheet_dynamic_groups.set_sheet_data([])  # Clear data
    frm_bottom.grid_remove()
    principals_sheet_dynamic_groups.grid_remove()  # Hide dynamic group sheet
    principals_sheet_policies_instance.grid_remove()  # Hide policy sheet temporarily

    if principals_style == "Dynamic Group":
        # Configure frm_bottom weights to split space evenly
        frm_bottom.rowconfigure(0, weight=1)
        frm_bottom.rowconfigure(1, weight=1)
        # Show both sheets in their respective grid positions
        principals_sheet_dynamic_groups.grid(row=0, column=0, sticky="nsew")  # Show dynamic group sheet
        principals_sheet_policies_instance.grid(row=1, column=0, sticky="nsew")  # Show policy sheet in row 1

        # Populate dynamic group sheet
        filtered_dynamic_groups = []
        # if type_principal == "Instance Principals":
            # filtered_dynamic_groups = identity_domain_analysis.filter_dynamic_groups(type_filter="instance.compartment.id")
        # elif type_principal == "Resource Principals":
        filtered_dynamic_groups = identity_domain_analysis.filter_dynamic_groups(type_filter="resource.type|resource.principal|resource.id")
        principals_sheet_dynamic_groups.set_sheet_data(filtered_dynamic_groups)
        
        # Populate policy sheet with initial filter
        policies = policy_compartment_analysis.filter_policies('Resource Principals', principals_style, resource_type)
        principals_sheet_policies_instance.set_sheet_data(policies)
        
        # Enable row selection on dynamic group sheet
        def on_row_select(event):
            selected_rows = principals_sheet_dynamic_groups.get_selected_rows()
            logger.info(f"Selected row in DG sheet: {selected_rows}")
            if selected_rows:
                selected_idx = list(selected_rows)[0]
                logger.info(f"Selected row in DG sheet: {list(selected_rows)[0]}")
                selected_dg = (filtered_dynamic_groups[selected_idx][0], filtered_dynamic_groups[selected_idx][1]) 
                filtered_policies = policy_compartment_analysis.filter_policies('Resource Principals', principals_style, resource_type, selected_dg)
                logger.info(f"Filtered Policy count for {selected_dg}: {len(filtered_policies)}")
                principals_sheet_policies_instance.set_sheet_data(filtered_policies)
            else:
                # Reset to all dynamic group policies
                filtered_policies = policy_compartment_analysis.filter_policies('Resource Principals', principals_style, resource_type)
                principals_sheet_policies_instance.set_sheet_data(filtered_policies)
        
        principals_sheet_dynamic_groups.bind("<ButtonRelease-1>", on_row_select)
    else:
        # Configure frm_bottom to give all weight to row 0
        frm_bottom.rowconfigure(0, weight=1)
        frm_bottom.rowconfigure(1, weight=0)  # Remove weight from row 1
        # Show only policy sheet, spanning both rows
        principals_sheet_policies_instance.grid(row=0, column=0, sticky="nsew", rowspan=2)  # Span rows 0 and 1
        policies = policy_compartment_analysis.filter_policies('Resource Principals', principals_style, resource_type)
        principals_sheet_policies_instance.set_sheet_data(policies)

    # Resize data
    principals_sheet_dynamic_groups.set_all_cell_sizes_to_text(slim=False)
    principals_sheet_policies_instance.set_all_cell_sizes_to_text(slim=False)

def update_font(var_name, index, mode):
    if font_size_var:
        new_font_size = 8 if font_size_var.get() == "Small" else 10 if font_size_var.get() == "Medium" else 12
        sheet_policies.font(newfont=("Courier New", new_font_size, "normal"))
        sheet_policies.set_all_cell_sizes_to_text(redraw=True)
        sheet_dynamic_group.font(newfont=("Courier New", new_font_size, "normal"))
        sheet_dynamic_group.set_all_cell_sizes_to_text(redraw=True)
        sheet_user_policies.font(newfont=("Courier New", new_font_size, "normal"))
        sheet_user_policies.set_all_cell_sizes_to_text(redraw=True)
        sheet_cross_tenancy_define.font(newfont=("Courier New", new_font_size, "normal"))
        sheet_cross_tenancy_define.set_all_cell_sizes_to_text(redraw=True)
        sheet_cross_tenancy_policies.font(newfont=("Courier New", new_font_size, "normal"))
        sheet_cross_tenancy_policies.set_all_cell_sizes_to_text(redraw=True)
        logger.info(f"Changing font size globally to {font_size_var.get()}/{new_font_size}")


# Process Load Buttons
def load_from_cache():
    global last_load_time, last_error
    progress_bar.grid()
    progress_bar_label.grid()
    progress_bar_label.config(text="Loading Policies and Compartments")
    progress_bar.start()
    label_status_bar.config(text="Loading from cache...")

    def load_cache():
        global last_error
        try:
            profile = profile_var.get()
            use_ip = use_instance_principal.get()
            progress_bar_label.config(text="Loading Policies and Compartments")
            success = policy_compartment_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize PolicyCompartmentAnalysis client for cache")
            success = identity_domain_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize IdentityDomainAnalysis client for cache")
            success = policy_compartment_analysis.load_policies_from_cache()
            if not success:
                raise FileNotFoundError(f"Cache file not found for tenancy {policy_compartment_analysis.tenancy_ocid}")
            progress_bar_label.config(text="Loading Dynamic Groups")
            success = identity_domain_analysis.load_from_cache()
            if not success:
                raise FileNotFoundError(f"Cache file not found for tenancy {identity_domain_analysis.tenancy_ocid}")
            progress_bar_label.config(text="Loading User Details")
            success = identity_domain_analysis.load_from_cache()
            if not success:
                raise FileNotFoundError(f"Cache file not found for tenancy {identity_domain_analysis.tenancy_ocid}")
            last_load_time = policy_compartment_analysis.data_as_of
            window.after(0, lambda: (
                label_status_bar.config(
                    text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                         f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                         f"tksheet: {tksheet.__version__} | Loaded as of: {last_load_time}"
                ),
                [e.config(state=tk.NORMAL) for e in [entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy,
                                                     entry_condition, entry_text, entry_policy, dg_entry_domain,
                                                     dg_entry_name, dg_entry_type, dg_entry_ocid, domain_dropdown,
                                                     user_dropdown, compartment_dropdown]],
                [b.config(state=tk.NORMAL) for b in [btn_update, btn_clear, btn_export_policy, dg_btn_update,
                                                    dg_btn_clear, dg_btn_export, dg_btn_analyze, btn_analyze_user, 
                                                    btn_export_report]],
                update_domain_dropdown(),
                update_compartment_dropdown(),
                update_policy_output(),
                update_dg_output(),
                update_user_analysis_output(),
                update_report_output(),
                update_cross_tenancy_output(),

            ))
            logger.info(f"Loaded cache for tenancy: {policy_compartment_analysis.tenancy_ocid}")
        except Exception as exc:
            last_error = str(exc)
            window.after(0, lambda: label_status_bar.config(
                text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                     f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                     f"tksheet: {tksheet.__version__} | Cache Load Error: {last_error}"
            ))
            logger.error(f"Cache load error: {last_error}")
        finally:
            window.after(0, lambda: (progress_bar.stop(), progress_bar.grid_remove(), progress_bar_label.grid_remove()))

    Thread(target=load_cache, daemon=True).start()

def load_data():
    global last_load_time, last_error
    progress_bar.grid()
    progress_bar_label.grid()
    progress_bar_label.config(text="Loading Policies and Compartments")
    progress_bar.start()
    label_status_bar.config(text="Loading data...")

    def load():
        global last_error
        try:
            profile = profile_var.get()
            use_ip = use_instance_principal.get()
            progress_bar_label.config(text="Initializing Clients")
            success = policy_compartment_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize PolicyCompartmentAnalysis client")
            success = identity_domain_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize IdentityDomainAnalysis client")
            progress_bar_label.config(text="Loading Policies and Compartments")
            success = policy_compartment_analysis.load_policies_and_compartments()
            if not success:
                raise RuntimeError("Failed to load policies and compartments")
            progress_bar_label.config(text="Loading Dynamic Groups")
            success = identity_domain_analysis.load_all_dynamic_groups()
            if not success:
                raise RuntimeError("Failed to load dynamic groups")
            progress_bar_label.config(text="Loading Identity Domains and Users")
            success = identity_domain_analysis.load_domains_groups_users()
            if not success:
                raise RuntimeError("Failed to load identity domains and users")
            progress_bar_label.config(text="Saving to Cache")
            policy_compartment_analysis.save_to_cache()
            # dyn_group_analysis.save_to_cache()
            identity_domain_analysis.save_to_cache()
            last_load_time = policy_compartment_analysis.data_as_of
            window.after(0, lambda: (
                label_status_bar.config(
                    text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                         f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                         f"tksheet: {tksheet.__version__} | Loaded as of: {last_load_time}"
                ),
                [e.config(state=tk.NORMAL) for e in [entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy,
                                                     entry_condition, entry_text, entry_policy, dg_entry_domain,
                                                     dg_entry_name, dg_entry_type, dg_entry_ocid, domain_dropdown,
                                                     user_dropdown, compartment_dropdown]],
                [b.config(state=tk.NORMAL) for b in [btn_update, btn_clear, btn_export_policy, dg_btn_update,
                                                    dg_btn_clear, dg_btn_export, dg_btn_analyze, btn_analyze_user, 
                                                    btn_export_report]],
                update_domain_dropdown(),
                update_compartment_dropdown(),
                update_policy_output(),
                update_dg_output(),
                update_user_analysis_output(),
                update_report_output(),
                update_cross_tenancy_output()
            ))
            logger.info(f"Loaded data for tenancy: {policy_compartment_analysis.tenancy_ocid}")
        except Exception as exc:
            last_error = str(exc)
            window.after(0, lambda: label_status_bar.config(
                text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                     f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                     f"tksheet: {tksheet.__version__} | Load Error: {last_error}"
            ))
            logger.error(f"Data load error: {last_error}")
        finally:
            window.after(0, lambda: (progress_bar.stop(), progress_bar.grid_remove(), progress_bar_label.grid_remove()))

    Thread(target=load, daemon=True).start()

# UI Elements
def main():
    # To-do - split these up by tab
    global window, profile_var, use_instance_principal, entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy, \
           entry_condition, entry_text, entry_policy, dg_entry_domain, dg_entry_name, dg_entry_type, dg_entry_ocid, \
           sheet_policies, sheet_dynamic_group, label_policy_count, dg_label_count, btn_update, btn_clear, \
           btn_export_policy, dg_btn_update, dg_btn_clear, dg_btn_export, dg_btn_analyze, use_subject_any, location_filter_tenancy, \
           hierarchy_filter_root, chk_show_special, chk_show_service, chk_show_dynamic, chk_show_resource, chk_show_regular, \
           chk_show_invalid, chk_show_expanded, input_profile, policy_compartment_analysis, identity_domain_analysis, progress_bar, \
           label_status_bar, last_load_time, label_profile, btn_load_tenancy, btn_load_cache, principals_sheet_dynamic_groups, principals_sheet_policies_instance, \
           tab_users, domain_var, domain_display_var, user_var, user_display_var, compartment_var, compartment_display_var, \
           domain_dropdown, user_dropdown, compartment_dropdown, btn_analyze_user, sheet_user_policies, user_label_count, \
           progress_bar_label, last_error, btn_export_report, \
           principals_style_var, resource_type_var, resource_type_dropdown, principals_style_dropdown, frm_bottom, chk_show_instance_principals, \
           chk_show_not_in_use
    # Main Options
    global font_size_var
    
    # User Report tab
    global text_dg_report, text_policy_report, highlight_entry_var, text_user_details
    
    # Cross-tenancy tab
    global sheet_cross_tenancy_policies, sheet_cross_tenancy_define, sheet_cross_tenancy_define_search_order, sheet_cross_tenancy_policies_search_order

    args = parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Initialize analysis classes
    policy_compartment_analysis = PolicyCompartmentAnalysis(args.verbose)
    identity_domain_analysis = IdentityDomainsAnalysis(args.verbose)

    window = tk.Tk()
    window.title("OCI Policy and Dynamic Group Viewer")
    window.geometry("1200x800")
    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)

    # State 
    sheet_cross_tenancy_define_search_order = False
    sheet_cross_tenancy_policies_search_order = False
    
    # Top frame
    frm_init = ttk.Frame(window)
    frm_init.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

    # Instance Principal checkbox
    use_instance_principal = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm_init, text="Instance Principal", variable=use_instance_principal, command=toggle_profile_dropdown).grid(row=0, column=0, padx=5, pady=3)

    # Profile selection
    profile_list = ["DEFAULT"]
    try:
        with open(Path.home() / ".oci" / "config", 'r') as fp:
            profile_list = [line[1:-2] for line in fp if line.startswith('[') and line.endswith(']\n')]
    except FileNotFoundError:
        logger.warning("OCI config file not found")
        profile_list = ["NONE"]

    profile_var = tk.StringVar(value=profile_list[0])
    label_profile = ttk.Label(frm_init, text="Profile:")
    label_profile.grid(row=0, column=1, padx=5, pady=3)
    input_profile = ttk.OptionMenu(frm_init, profile_var, profile_var.get(), *profile_list)
    input_profile.grid(row=0, column=2, padx=5, pady=3)

    # Load buttons
    btn_load_tenancy = ttk.Button(frm_init, text="Load from Tenancy", command=load_data)
    btn_load_tenancy.grid(row=0, column=3, padx=5, pady=3)
    btn_load_cache = ttk.Button(frm_init, text="Load from Cache", command=load_from_cache)
    btn_load_cache.grid(row=0, column=4, padx=5, pady=3)

    # Font Size
    font_size_var = tk.StringVar()
    ttk.Label(frm_init, text="Font Size:").grid(row=0, column=5, padx=5, pady=3)
    options = ["Small", "Medium", "Large"]
    ttk.OptionMenu(frm_init, font_size_var, "Medium", *options).grid(row=0, column=6, padx=5, pady=3)
    font_size_var.trace_add("write", update_font)

    # Progress bar and label
    progress_bar_label = ttk.Label(frm_init, text="")
    progress_bar_label.grid(row=0, column=7, padx=5, pady=3)
    progress_bar_label.grid_remove()
    progress_bar = ttk.Progressbar(frm_init, mode="indeterminate", length=100)
    progress_bar.grid(row=0, column=8, padx=5, pady=3, sticky="e")
    progress_bar.grid_remove()

    # Status bar
    frm_status = ttk.Frame(window, style="TFrame")
    frm_status.grid(row=2, column=0, sticky="ew", padx=5, pady=2)
    frm_status.columnconfigure(0, weight=1)
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    oci_version = oci.__version__
    tkinter_version = tk.Tcl().eval('info patchlevel')
    tksheet_version = tksheet.__version__
    last_load_time = "Not Initialized"
    label_status_bar = ttk.Label(
        frm_status,
        text=f"Python: {python_version} | OCI: {oci_version} | Tkinter: {tkinter_version} | tksheet: {tksheet_version} | Last Load: {last_load_time}",
        anchor="w"
    )
    label_status_bar.grid(row=0, column=0, sticky="ew")

    # Notebook
    tab_control = ttk.Notebook(window)
    tab_policy = ttk.Frame(tab_control)
    tab_dg = ttk.Frame(tab_control)
    tab_principals = ttk.Frame(tab_control)
    tab_users = ttk.Frame(tab_control)
    tab_users.grid_rowconfigure(0, weight=2)
    tab_users.grid_rowconfigure(1, weight=8)
    tab_users.grid_columnconfigure(0, weight=1)
    tab_report = ttk.Frame(tab_control)
    tab_cross_tenancy = tk.Frame(tab_control)
    tab_cross_tenancy.grid_rowconfigure(0, weight=1)
    tab_cross_tenancy.grid_columnconfigure(0, weight=1)
    
    tab_control.add(tab_policy, text="Regular Policy\nStatements")
    tab_control.add(tab_dg, text="Dynamic Groups / \nInstance Principals")
    tab_control.add(tab_principals, text="Resource\nPrincipals")
    tab_control.add(tab_users, text="User Permission\nAnalysis")
    tab_control.add(tab_report, text="Policy/Dynamic\nGroup Report")
    tab_control.add(tab_cross_tenancy, text="Cross Tenancy\nPolicies")
    tab_control.grid(row=1, column=0, sticky="nsew")

    #############################
    # All Policy Tab
    frm_policy_top = ttk.Frame(tab_policy)
    frm_policy_top.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    tab_policy.rowconfigure(1, weight=1)
    tab_policy.columnconfigure(0, weight=1)
    frm_policy_filter = ttk.Frame(frm_policy_top)
    frm_policy_filter.grid(row=0, column=0, sticky="ew")
    frm_policy_filter.columnconfigure([1, 3], weight=1)
    ttk.Label(frm_policy_filter, text="Filters (| for OR, AND between fields)").grid(row=0, column=0, columnspan=5, pady=2, sticky="ew")

    frm_subj = ttk.Frame(frm_policy_filter)
    ttk.Label(frm_policy_filter, text="Subject").grid(row=1, column=0, padx=5, pady=2, sticky="w")
    entry_subj = tk.Entry(frm_subj, state=tk.DISABLED, width=20)
    entry_subj.grid(row=0, column=0, padx=2, sticky="ew")
    use_subject_any = tk.BooleanVar()
    ttk.Checkbutton(frm_subj, text="Any-User/Group", variable=use_subject_any, command=toggle_any_subject).grid(row=0, column=1, padx=2)
    frm_subj.grid(row=1, column=1, padx=5, pady=2, sticky="ew")

    ttk.Label(frm_policy_filter, text="Verb").grid(row=1, column=2, padx=5, pady=2, sticky="w")
    entry_verb = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
    entry_verb.grid(row=1, column=3, padx=5, pady=2, sticky="ew")

    ttk.Label(frm_policy_filter, text="Resource").grid(row=2, column=0, padx=5, pady=2, sticky="w")
    entry_res = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
    entry_res.grid(row=2, column=1, padx=5, pady=2, sticky="ew")

    frm_loc = ttk.Frame(frm_policy_filter)
    ttk.Label(frm_policy_filter, text="Location").grid(row=2, column=2, padx=5, pady=2, sticky="w")
    entry_loc = tk.Entry(frm_loc, state=tk.DISABLED, width=20)
    entry_loc.grid(row=0, column=0, padx=2, sticky="ew")
    location_filter_tenancy = tk.BooleanVar()
    ttk.Checkbutton(frm_loc, text="Tenancy", variable=location_filter_tenancy, command=toggle_location_tenancy).grid(row=0, column=1, padx=2)
    frm_loc.grid(row=2, column=3, padx=5, pady=2, sticky="ew")

    frm_hierarchy = ttk.Frame(frm_policy_filter)
    ttk.Label(frm_policy_filter, text="Hierarchy").grid(row=3, column=0, padx=5, pady=2, sticky="w")
    entry_hierarchy = tk.Entry(frm_hierarchy, state=tk.DISABLED, width=20)
    entry_hierarchy.grid(row=0, column=0, padx=2, sticky="ew")
    hierarchy_filter_root = tk.BooleanVar()
    ttk.Checkbutton(frm_hierarchy, text="Root", variable=hierarchy_filter_root, command=toggle_hierarchy_root).grid(row=0, column=1, padx=2)
    frm_hierarchy.grid(row=3, column=1, padx=5, pady=2, sticky="ew")

    ttk.Label(frm_policy_filter, text="Condition").grid(row=3, column=2, padx=5, pady=2, sticky="w")
    entry_condition = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
    entry_condition.grid(row=3, column=3, padx=5, pady=2, sticky="ew")

    ttk.Label(frm_policy_filter, text="Text").grid(row=4, column=0, padx=5, pady=2, sticky="w")
    entry_text = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
    entry_text.grid(row=4, column=1, padx=5, pady=2, sticky="ew")

    ttk.Label(frm_policy_filter, text="Policy Name").grid(row=4, column=2, padx=5, pady=2, sticky="w")
    entry_policy = tk.Entry(frm_policy_filter, state=tk.DISABLED, width=20)
    entry_policy.grid(row=4, column=3, padx=5, pady=2, sticky="ew")

    frm_policy_buttons = ttk.Frame(frm_policy_filter)
    btn_update = ttk.Button(frm_policy_buttons, text="Update", state=tk.DISABLED, command=update_policy_output)
    btn_update.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
    btn_clear = ttk.Button(frm_policy_buttons, text="Clear", state=tk.DISABLED, command=clear_policy_filters)
    btn_clear.grid(row=1, column=0, padx=5, pady=2, sticky="ew")
    btn_export_policy = ttk.Button(frm_policy_buttons, text="Export Filtered\nStatements to CSV", state=tk.DISABLED, command=export_policy_to_csv)
    btn_export_policy.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
    frm_policy_buttons.grid(row=1, column=4, rowspan=4, padx=5, pady=2, sticky="ns")

    frm_policy_output = ttk.Frame(frm_policy_top)
    frm_policy_output.grid(row=1, column=0, sticky="w")
    frm_policy_output.columnconfigure(0, weight=1)
    label_policy_count = ttk.Label(frm_policy_output, text="Statements (Filtered): 0")
    label_policy_count.grid(row=0, column=0, padx=5, pady=3, sticky="w")
    chk_show_service = tk.BooleanVar()
    chk_show_dynamic = tk.BooleanVar()
    chk_show_resource = tk.BooleanVar()
    chk_show_invalid = tk.BooleanVar()
    chk_show_regular = tk.BooleanVar(value=True)
    chk_show_expanded = tk.BooleanVar()
    ttk.Separator(frm_policy_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
    ttk.Label(frm_policy_output, text="Statement Type\nto display:").grid(row=0, column=2, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Service", variable=chk_show_service, command=update_policy_output).grid(row=0, column=3, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Dynamic Group", variable=chk_show_dynamic, command=update_policy_output).grid(row=0, column=4, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Resource", variable=chk_show_resource, command=update_policy_output).grid(row=0, column=5, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Regular", variable=chk_show_regular, command=update_policy_output).grid(row=0, column=6, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Invalid", variable=chk_show_invalid, command=update_policy_output).grid(row=0, column=7, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Expanded Output", variable=chk_show_expanded, command=update_policy_output).grid(row=0, column=8, padx=5, pady=3)

    frm_policy_sheet = ttk.Frame(tab_policy)
    frm_policy_sheet.grid(row=1, column=0, sticky="nsew")
    frm_policy_sheet.rowconfigure(0, weight=1)
    frm_policy_sheet.columnconfigure(0, weight=1)
    sheet_policies = tksheet.Sheet(
        frm_policy_sheet, theme="light green", font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), index_font=("Courier New", 11, "bold"),
        headers=["Policy Name", "Policy OCID", "Compartment OCID", "Hierarchy", "Statement Text", "Valid",
                 "Subject Type", "Subject", "Verb", "Resource", "Permission", "Location Type", "Location",
                 "Conditions", "Comments", "Creation Time", "Parsed"],
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )

    sheet_policies.grid(row=0, column=0, sticky="nsew")
    sheet_policies.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")

    #############################
    # Dynamic Group Tab
    frm_dg_filter = ttk.Frame(tab_dg)
    frm_dg_filter.grid(row=0, column=0, sticky="w", padx=5, pady=5)
    frm_dg_filter.columnconfigure([1, 3], weight=1)
    tab_dg.rowconfigure(2, weight=1)
    tab_dg.columnconfigure(0, weight=1)
    ttk.Label(frm_dg_filter, text="Filters (| for OR, AND between fields)").grid(row=0, column=0, columnspan=5, pady=2, sticky="ew")
    ttk.Label(frm_dg_filter, text="Domain").grid(row=1, column=0, padx=5, pady=2, sticky="w")
    dg_entry_domain = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
    dg_entry_domain.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
    ttk.Label(frm_dg_filter, text="Name").grid(row=1, column=2, padx=5, pady=2, sticky="w")
    dg_entry_name = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
    dg_entry_name.grid(row=1, column=3, padx=5, pady=2, sticky="ew")
    ttk.Label(frm_dg_filter, text="Rule Component").grid(row=2, column=0, padx=5, pady=2, sticky="w")
    dg_entry_type = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
    dg_entry_type.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
    ttk.Label(frm_dg_filter, text="OCID").grid(row=2, column=2, padx=5, pady=2, sticky="w")
    dg_entry_ocid = tk.Entry(frm_dg_filter, state=tk.DISABLED, width=20)
    dg_entry_ocid.grid(row=2, column=3, padx=5, pady=2, sticky="ew")
    frm_dg_buttons = ttk.Frame(frm_dg_filter)
    dg_btn_update = ttk.Button(frm_dg_buttons, text="Update", state=tk.DISABLED, command=update_dg_output)
    dg_btn_update.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
    dg_btn_clear = ttk.Button(frm_dg_buttons, text="Clear", state=tk.DISABLED, command=clear_dg_filters)
    dg_btn_clear.grid(row=1, column=0, padx=5, pady=2, sticky="ew")
    dg_btn_export = ttk.Button(frm_dg_buttons, text="Export CSV", state=tk.DISABLED, command=export_dg_to_csv)
    dg_btn_analyze = ttk.Button(frm_dg_buttons, text="Analyze DGs", state=tk.DISABLED, command=run_dg_analysis)
    # dg_btn_analyze.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
    #dg_btn_export.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
    frm_dg_buttons.grid(row=1, column=4, rowspan=2, padx=5, pady=2, sticky="ns")

    # Output filter
    frm_dg_output = ttk.Frame(tab_dg)
    frm_dg_output.grid(row=1, column=0, sticky="w")
    frm_dg_output.columnconfigure(0, weight=1)
    dg_label_count = ttk.Label(frm_dg_output, text="Dynamic Groups (Filtered): 0")
    dg_label_count.grid(row=0, column=0, padx=5, pady=3, sticky="w")
    ttk.Separator(frm_dg_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
    chk_show_instance_principals = tk.BooleanVar()
    chk_show_not_in_use = tk.BooleanVar()
    ttk.Checkbutton(frm_dg_output, text="Show Instance Principals Only", variable=chk_show_instance_principals, command=update_dg_output).grid(row=0, column=2, padx=5, pady=3)
    ttk.Checkbutton(frm_dg_output, text="Highlight Unused Dynamic Groups", variable=chk_show_not_in_use, command=update_dg_output).grid(row=0, column=3, padx=5, pady=3)

    # Bottom Sheet
    frm_dg_sheet = ttk.Frame(tab_dg)
    frm_dg_sheet.grid(row=2, column=0, sticky="nsew")
    frm_dg_sheet.rowconfigure(0, weight=1)
    frm_dg_sheet.columnconfigure(0, weight=1)
    sheet_dynamic_group = tksheet.Sheet(
        frm_dg_sheet, theme="light green", font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), index_font=("Courier New", 11, "bold"),
        headers=["Domain", "Name", "Matching Rule", "In Use?", "OCID", "Creation Time"],
        # To-do: Add back Invalid OCID functionality "Invalid OCIDs" and maybe rules components
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )
    sheet_dynamic_group.grid(row=0, column=0, sticky="nsew")
    sheet_dynamic_group.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")
    # bind_horizontal_scroll(sheet_dynamic_group)

    #######################
    # Principals Tab
    frm_top = tk.Frame(tab_principals)
    frm_top.pack(fill="x", padx=5, pady=5)

    # # Type dropdown
    # tk.Label(frm_top, text="Type:").pack(side=tk.LEFT, padx=5)
    # type_var = tk.StringVar(value="Instance Principals")
    # type_dropdown = ttk.Combobox(frm_top, textvariable=type_var, values=["Instance Principals", "Resource Principals"])
    # type_dropdown.pack(side=tk.LEFT, padx=5)
    
    # Principals Style dropdown
    tk.Label(frm_top, text="Principals Style:").pack(side=tk.LEFT, padx=5)
    principals_style_var = tk.StringVar(value="Dynamic Group")
    principals_style_dropdown = ttk.Combobox(frm_top, textvariable=principals_style_var, values=["Dynamic Group", "any-user + conditions"])
    principals_style_dropdown.pack(side=tk.LEFT, padx=5)
    
    # Resource Type dropdown
    tk.Label(frm_top, text="Resource Type:").pack(side=tk.LEFT, padx=5)
    resource_type_var = tk.StringVar(value="Any")
    resource_type_dropdown = ttk.Combobox(frm_top, textvariable=resource_type_var, values=["Any", "ADB", "Function"])
    resource_type_dropdown.pack(side=tk.LEFT, padx=5)

    # Bottom frame for sheets using grid
    frm_bottom = tk.Frame(tab_principals)
    frm_bottom.pack(fill="both", expand=True, padx=5, pady=5)
    frm_bottom.rowconfigure(0, weight=1)
    frm_bottom.rowconfigure(1, weight=1)
    frm_bottom.columnconfigure(0, weight=1)
    
    # Dynamic group sheet frame
    frm_dg_sheet = tk.Frame(frm_bottom)
    frm_dg_sheet.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    frm_dg_sheet.rowconfigure(0, weight=1)
    frm_dg_sheet.columnconfigure(0, weight=1)
    
    principals_sheet_dynamic_groups = tksheet.Sheet(
        frm_dg_sheet, 
        theme="light green", 
        font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), 
        index_font=("Courier New", 11, "bold"),
        headers=["Domain", "Name", "OCID", "Matching Rule", "Rule Components", "In Use?", "Creation Time"],
        auto_resize_columns=80, 
        show_x_scrollbar=True, 
        show_y_scrollbar=True
    )
    principals_sheet_dynamic_groups.grid(row=0, column=0, sticky="nsew")
    principals_sheet_dynamic_groups.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")
    
    # Policy sheet frame
    frm_policy_sheet = tk.Frame(frm_bottom)
    frm_policy_sheet.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    frm_policy_sheet.rowconfigure(0, weight=1)
    frm_policy_sheet.columnconfigure(0, weight=1)
    
    principals_sheet_policies_instance = tksheet.Sheet(
        frm_policy_sheet, 
        theme="light green", 
        font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), 
        index_font=("Courier New", 11, "bold"),
        headers=["Policy Name", "Policy OCID", "Compartment OCID", "Hierarchy", "Statement Text", "Valid",
                 "Subject Type", "Subject", "Verb", "Resource", "Permission", "Location Type", "Location",
                 "Conditions", "Comments", "Creation Time", "Parsed"],
        auto_resize_columns=200, 
        show_x_scrollbar=True, 
        show_y_scrollbar=True,
    )
    principals_sheet_policies_instance.grid(row=0, column=0, sticky="nsew")
    principals_sheet_policies_instance.enable_bindings("column_width_resize", "row_select", "copy")
    principals_sheet_policies_instance.display_columns(all_columns_displayed=False, columns=[0, 3, 4, 7, 8, 9, 10, 12, 13, 14, 15])

    # Bind dropdowns to update function
    principals_style_var.trace_add("write", update_principals_sheets)
    resource_type_var.trace_add("write", update_principals_sheets)

    # # Initial run
    # update_principals_sheets()

    #############################
    # User Analysis Tab
    frm_user_top = ttk.Frame(tab_users)
    frm_user_top.grid_rowconfigure(0, weight=3)
    frm_user_top.grid_rowconfigure(1, weight=7)
    frm_user_top.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
    # tab_users.rowconfigure(1, weight=1)
    # tab_users.columnconfigure(0, weight=1)

    frm_user_select = ttk.Frame(frm_user_top)
    frm_user_select.grid(row=0, column=0, sticky="ew")

    ttk.Label(frm_user_select, text="Select the Domain and User in order to\nload all applicable policies.").grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky="w")

    ttk.Label(frm_user_select, text="Identity Domain:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
    domain_var = tk.StringVar(value="None")
    domain_display_var = tk.StringVar(value="None")
    domain_dropdown = ttk.OptionMenu(frm_user_select, domain_display_var, "None", "None")
    domain_dropdown.grid(row=2, column=1, padx=5, pady=2, sticky="ew")
    domain_dropdown.config(state=tk.DISABLED)

    ttk.Label(frm_user_select, text="User:").grid(row=3, column=0, padx=5, pady=2, sticky="w")
    user_var = tk.StringVar(value="None")
    user_display_var = tk.StringVar(value="None")
    user_dropdown = ttk.OptionMenu(frm_user_select, user_display_var, "None", "None", command=lambda _: update_user_analysis_output())
    user_dropdown.grid(row=3, column=1, padx=5, pady=2, sticky="ew")
    user_dropdown.config(state=tk.DISABLED)

    # ttk.Label(frm_user_select, text="Compartment:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
    compartment_var = tk.StringVar(value="All Compartments")
    compartment_display_var = tk.StringVar(value="All Compartments")
    compartment_dropdown = ttk.OptionMenu(frm_user_select, compartment_display_var, "All Compartments", "All Compartments")
    # compartment_dropdown.grid(row=0, column=3, padx=5, pady=2, sticky="ew")
    compartment_dropdown.config(state=tk.DISABLED)

    frm_user_buttons = ttk.Frame(frm_user_select)
    btn_analyze_user = ttk.Button(frm_user_buttons, text="Analyze User", state=tk.DISABLED, command=update_user_analysis_output)
    # btn_analyze_user.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
    btn_export_user = ttk.Button(frm_user_buttons, text="Export CSV", state=tk.DISABLED, command=export_user_to_csv)
    # btn_export_user.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
    frm_user_buttons.grid(row=0, column=4, rowspan=2, padx=5, pady=2, sticky="ns")

    # Top Right Pane for User Info
    frm_user_details = ttk.Frame(frm_user_top)
    text_user_details = tk.Text(frm_user_details, wrap=tk.WORD, font=("TkFixedFont"), state=tk.NORMAL, height=10,width=80)
    text_user_scroll = ttk.Scrollbar(frm_user_details, orient=tk.VERTICAL, command=text_user_details.yview)
    text_user_details.grid(row=0, column=0)
    text_user_scroll.grid(row=0, column=1, sticky="ns")
    frm_user_details.grid(row=0, column=1)

    # user_selection_label = ttk.Label(frm_user_select, text="Domain: None (None)\nUser: None (None)\nCompartment: All Compartments (All Compartments)", anchor="w")
    # user_selection_label.grid(row=2, column=0, columnspan=5, padx=5, pady=5, sticky="ew")

    # Bottom Output
    frm_user_output = ttk.Frame(frm_user_top)
    frm_user_output.grid(row=1, column=0, sticky="nsew")
    frm_user_output.columnconfigure(0, weight=1)
    user_label_count = ttk.Label(frm_user_output, text="Policy Statements (Filtered): 0")
    user_label_count.grid(row=0, column=0, padx=5, pady=3, sticky="w")
    ttk.Separator(frm_user_output, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
    ttk.Label(frm_user_output, text="Display Options:").grid(row=0, column=2, padx=5, pady=3)
    ttk.Checkbutton(frm_user_output, text="Expanded", variable=chk_show_expanded, command=update_user_analysis_output).grid(row=0, column=5, padx=5, pady=3)

    frm_user_sheet = ttk.Frame(tab_users)
    frm_user_sheet.grid(row=1, column=0, sticky="nsew")
    frm_user_sheet.rowconfigure(0, weight=1)
    frm_user_sheet.columnconfigure(0, weight=1)
    sheet_user_policies = tksheet.Sheet(
        frm_user_sheet, theme="light green", font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), index_font=("Courier New", 11, "bold"),
        headers=["Policy Name", "Policy OCID", "Compartment OCID", "Hierarchy", "Statement Text", "Valid",
                 "Subject Type", "Subject", "Verb", "Resource", "Permission", "Location Type", "Location",
                 "Conditions", "Comments", "Creation Time", "Parsed"],
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )
    sheet_user_policies.grid(row=0, column=0, sticky="nsew")
    sheet_user_policies.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")
    # bind_horizontal_scroll(sheet_user_policies)

    #############################
    # Policy/Dynamic Group Report Tab
    frm_report_top = ttk.Frame(tab_report)
    frm_report_top.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    tab_report.rowconfigure(1, weight=1)
    tab_report.columnconfigure(0, weight=1)

    # Top Section
    frm_report_buttons = ttk.Frame(frm_report_top)
    ttk.Label(frm_report_buttons, text="Text Highlight:", font=("TkFixedFont", 10, "bold")).grid(row=0, column=0, padx=5, pady=5, sticky="w")
    highlight_entry_var = tk.StringVar()
    tk.Entry(frm_report_buttons, textvariable=highlight_entry_var).grid(row=0, column=1)

    btn_export_report = ttk.Button(frm_report_buttons, text="Export Report", state=tk.DISABLED, command=export_report_to_txt)
    btn_export_report.grid(row=0, column=2, padx=5, pady=2, sticky="ew")
    frm_report_buttons.grid(row=0, column=0, sticky="e")

    frm_report = ttk.PanedWindow(tab_report, orient=tk.HORIZONTAL)
    frm_report.grid(row=1, column=0, sticky="nsew")

    # Bottom Section
    frm_dg_report = ttk.Frame(frm_report)
    frm_dg_report.grid(sticky="nsew")
    frm_dg_report.rowconfigure(1, weight=1)
    frm_dg_report.columnconfigure(0, weight=1)
    ttk.Label(frm_dg_report, text="Dynamic Groups", font=("TkFixedFont", 12, "bold")).grid(row=0, column=0, padx=5, pady=5, sticky="w")
    text_dg_report = tk.Text(frm_dg_report, wrap=tk.WORD, font=("TkFixedFont"), state=tk.DISABLED)
    text_dg_report.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    dg_scroll = ttk.Scrollbar(frm_dg_report, orient=tk.VERTICAL, command=text_dg_report.yview)
    dg_scroll.grid(row=1, column=1, sticky="ns")
    text_dg_report.config(yscrollcommand=dg_scroll.set)

    frm_policy_report = ttk.Frame(frm_report)
    frm_policy_report.grid(sticky="nsew")
    frm_policy_report.rowconfigure(1, weight=1)
    frm_policy_report.columnconfigure(0, weight=1)
    ttk.Label(frm_policy_report, text="Policies by Compartment", font=("TkFixedFont", 12, "bold")).grid(row=0, column=0, padx=5, pady=5, sticky="w")
    text_policy_report = tk.Text(frm_policy_report, wrap=tk.WORD, font=("TkFixedFont"), state=tk.DISABLED)
    text_policy_report.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
    policy_scroll = ttk.Scrollbar(frm_policy_report, orient=tk.VERTICAL, command=text_policy_report.yview)
    policy_scroll.grid(row=1, column=1, sticky="ns")
    text_policy_report.config(yscrollcommand=policy_scroll.set)

    frm_report.add(frm_dg_report, weight=3)
    frm_report.add(frm_policy_report, weight=7)

    # Call the highlight functionality
    highlight_entry_var.trace_add("write", report_text_search)

    #############################
    # Cross-tenancy Tab
    frm_cross_tenancy = ttk.Frame(tab_cross_tenancy)
    frm_cross_tenancy.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    frm_cross_tenancy.grid_rowconfigure(0, weight=3)
    frm_cross_tenancy.grid_rowconfigure(1, weight=7)
    frm_cross_tenancy.grid_columnconfigure(0, weight=2)
    frm_cross_tenancy.grid_columnconfigure(1, weight=8)
    ttk.Label(frm_cross_tenancy, text="Select one or more rows to the right\nin order to narrow down cross-tenancy policies\n\nSort by clicking column headers", font=("TkFixedFont", 10, "normal")).grid(row=0, column=0, padx=5, pady=5, sticky="w")

    sheet_cross_tenancy_define = tksheet.Sheet(
        frm_cross_tenancy, theme="light green", font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), index_font=("Courier New", 11, "bold"),
        headers=["Defined Alias", "Define Type", "Remote Tenancy OCID"],
        show_x_scrollbar=True, show_y_scrollbar=True, auto_resize_columns=True
    )
    sheet_cross_tenancy_define.enable_bindings("all")
    sheet_cross_tenancy_define.extra_bindings("column_select",sort_sheet_cross_tenancy_define)
    sheet_cross_tenancy_define.extra_bindings("row_select",update_cross_tenancy_alias_selection)
    sheet_cross_tenancy_define.grid(row=0, column=1, sticky="nsew")
    sheet_cross_tenancy_policies = tksheet.Sheet(
        frm_cross_tenancy, theme="light green", font=("Courier New", 10, "normal"),
        header_font=("Courier New", 11, "bold"), index_font=("Courier New", 11, "bold"),
        headers=["Policy Name", "Statement Text", "Subject Type", "Subject", "Action", "Verb / Resource", "Location Type", 
                 "Location", "Condition", "Optional", "Policy OCID", "Create Date"],
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )
    sheet_cross_tenancy_policies.enable_bindings("all")
    sheet_cross_tenancy_policies.extra_bindings("column_select",sort_sheet_cross_tenancy_policies)
    sheet_cross_tenancy_policies.grid(row=1, column=0, columnspan=2, sticky="nsew")

    #############################
    # Start Main loop
    window.mainloop()

# Start Program
if __name__ == "__main__":
    main()