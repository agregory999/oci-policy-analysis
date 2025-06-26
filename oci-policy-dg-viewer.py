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
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread

# Third-party imports
import oci
import tkinter as tk
import tksheet
import ttkbootstrap as ttk
from oci import config, pagination
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.identity import IdentityClient
from oci.identity.models import Compartment, Policy
from tkinter import messagebox
from ttkbootstrap.constants import *

# Constants
THREADS = 8
POLICY_REGEX = r'^\s*?(allow|endorse)\s+(?P<subjecttype>service|any-user|any-group|dynamic-group|group|resource)\s*(?P<subject>([\w\/\'\.\\, +-]|,)+?)?\s+(to\s+)?((?P<verb>read|inspect|use|manage)\s+(?P<resource>[\w-]+)|(?P<perm>{[\s*\w\s*|\s*\w\s*,\s*]+}))\s+in\s+(?P<locationtype>any-tenancy|tenancy|compartment\s+id|compartment)\s*(?P<location>[\w\':.-]+)?(?:\s+where\s+(?P<condition>.+))?(?:(?P<optional>\s*\/\/.+))?$'
SUBJECT_REGEX = r'(\'|\")?((?P<domain>[\w\-\_]+)(\/|\\))?(?P<name>[\w\-\_]+)(\'|\")?'
STATEMENT_REGEX = r'[\w.]+\s*=\s*\'[\w\s.]+\''
OCID_REGEX = r"ocid1\.\w+\.\w+\.\w*\.\w+"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s'
)
logger = logging.getLogger('oci-policy-dg-viewer')

class PolicyAnalysis:
    def __init__(self, verbose: bool):
        self.logger = logging.getLogger('oci-policy-analysis-policies')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        self.regular_statements = []
        self.data_as_of = ""
        self.logger.info("Initialized PolicyAnalysis")

    def initialize_client(self, use_instance_principal: bool, profile: str = "DEFAULT") -> bool:
        self.use_instance_principal = use_instance_principal
        self.profile = profile
        try:
            if use_instance_principal and os.getenv("OCI_RESOURCE_PRINCIPAL_VERSION"):
                self.logger.debug("Using Instance Principal Authentication")
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            else:
                self.logger.debug(f"Using Profile Authentication: {profile}")
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.tenancy_ocid = self.config["tenancy"]
            self.logger.info(f"Set up Identity Client for tenancy: {self.tenancy_ocid}")
            return True
        except (ConfigFileNotFound, Exception) as exc:
            self.logger.fatal(f"Authentication failed: {exc}")
            return False

    def parse_statement(self, statement: str, comp_string: str, policy: Policy) -> list:
        time_created = str(policy.time_created)
        result = re.search(POLICY_REGEX, statement, re.IGNORECASE | re.MULTILINE)
        if result:
            try:
                statement_list = [
                    policy.name, policy.id, policy.compartment_id, comp_string or "ROOT", statement,
                    True, result.group('subjecttype'),
                    result.group('subject') or "",
                    result.group('verb') or "",
                    result.group('resource') or "",
                    result.group('perm') or "",
                    result.group('locationtype') or "",
                    result.group('location') or "",
                    result.group('condition') or "",
                    result.group('optional') or "",
                    time_created, True
                ]
                if statement_list[6] in ["any-user", "any-group"]:
                    statement_list[7] = [(None, statement_list[6])]
                else:
                    subject_result = re.findall(SUBJECT_REGEX, statement_list[7], re.IGNORECASE)
                    statement_list[7] = [(a[2] or "Default", a[4]) for a in subject_result]
                return statement_list
            except Exception as e:
                self.logger.warning(f"Failed to parse statement: {e}")
                return [policy.name, policy.id, policy.compartment_id, comp_string or "ROOT", statement,
                        False, "other", [], "", "", "", "", "", "", "", time_created, False]
        self.logger.debug(f"No regex match: {statement}")
        return [policy.name, policy.id, policy.compartment_id, comp_string or "ROOT", statement,
                statement.startswith("define"), "define" if statement.startswith("define") else "other",
                [], "", "", "", "", "", "", "", time_created, False]

    def get_compartment_path(self, compartment: Compartment, level: int, comp_string: str) -> str:
        if not compartment.compartment_id:
            return comp_string
        parent_response = self.identity_client.get_compartment(compartment_id=compartment.compartment_id)
        if parent_response.data is None:
            self.logger.warning(f"Failed to get parent compartment for {compartment.id}")
            return comp_string
        return self.get_compartment_path(parent_response.data, level + 1, f"{compartment.name}/{comp_string}")

    def load_policies(self, compartment: Compartment):
        try:
            self.logger.debug(f"Processing compartment: {compartment.name}")
            policies_response = self.identity_client.list_policies(compartment_id=compartment.id, limit=1000)
            if policies_response.data is None:
                self.logger.warning(f"No policies found for compartment: {compartment.id}")
                return
            policies = policies_response.data
            if not policies:
                return
            path = self.get_compartment_path(compartment, 0, "")
            for policy in policies:
                for statement in policy.statements:
                    self.regular_statements.append(self.parse_statement(str.casefold(statement), path, policy))
        except Exception as se:
            self.logger.error(f"Failed to load policies: {se}")

    def load_policies_from_client(self) -> bool:
        self.regular_statements = []
        tic = time.perf_counter()
        try:
            root_comp_response = self.identity_client.get_compartment(compartment_id=self.tenancy_ocid)
            if root_comp_response.data is None:
                self.logger.error(f"Failed to get root compartment: {self.tenancy_ocid}")
                return False
            root_comp = root_comp_response.data
            comp_list = [root_comp]
            comp_response = pagination.list_call_get_all_results(
                self.identity_client.list_compartments, self.tenancy_ocid, access_level="ACCESSIBLE",
                sort_order="ASC", compartment_id_in_subtree=True, lifecycle_state="ACTIVE", limit=1000
            )
            if comp_response.data is None:
                self.logger.error("Failed to list compartments")
                return False
            comp_list.extend(comp_response.data)
            with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix="thread") as executor:
                executor.map(self.load_policies, comp_list)
            self.data_as_of = str(datetime.datetime.now())
            self.logger.info(f"Loaded {len(self.regular_statements)} policies in {time.perf_counter() - tic:.2f}s")
            return True
        except Exception as e:
            self.logger.error(f"Failed to load policies: {e}")
            return False

    def filter_policy_statements(self, subj_filter: str, verb_filter: str, resource_filter: str, location_filter: str,
                                hierarchy_filter: str, condition_filter: str, text_filter: str, policy_filter: str) -> list:
        filtered = self.regular_statements
        for filt in subj_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in str(st[7]).casefold()]
        for filt in verb_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[8].casefold()]
        for filt in resource_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[9].casefold()]
        for filt in location_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in (st[11] if "tenancy" == filt.lower() else st[12]).casefold()]
        for filt in hierarchy_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[3].casefold()]
        for filt in condition_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[13].casefold()]
        for filt in text_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[4].casefold()]
        for filt in policy_filter.split('|'):
            filtered = [st for st in filtered if filt.casefold() in st[0].casefold()]
        self.logger.info(f"Filtered to {len(filtered)} policy statements")
        return filtered

class DynamicGroupAnalysis:
    def __init__(self, verbose: bool):
        self.logger = logging.getLogger('oci-policy-analysis-dynamic-groups')
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        self.dynamic_groups = []
        self.logger.info("Initialized DynamicGroupAnalysis")

    def initialize_client(self, use_instance_principal: bool, profile: str = "DEFAULT") -> bool:
        try:
            if use_instance_principal and os.getenv("OCI_RESOURCE_PRINCIPAL_VERSION"):
                self.logger.debug("Using Instance Principal Authentication")
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
            else:
                self.logger.debug(f"Using Profile Authentication: {profile}")
                self.config = config.from_file(profile_name=profile)
                self.identity_client = IdentityClient(self.config)
                self.tenancy_ocid = self.config["tenancy"]
            self.logger.info(f"Set up Identity Client for tenancy: {self.tenancy_ocid}")
            return True
        except (ConfigFileNotFound, Exception) as exc:
            self.logger.fatal(f"Authentication failed: {exc}")
            return False

    def parse_dynamic_group(self, dg_name: str, dg_ocid: str, dg_domain: str, dg_rule: str, dg_created: str) -> list:
        rules = re.findall(STATEMENT_REGEX, dg_rule, re.IGNORECASE | re.MULTILINE)
        return [dg_domain, dg_name, dg_ocid, dg_rule, rules, True, [], dg_created]

    def load_all_dynamic_groups(self) -> bool:
        self.dynamic_groups = []
        try:
            dg_response = pagination.list_call_get_all_results(
                self.identity_client.list_dynamic_groups, compartment_id=self.tenancy_ocid, limit=1000
            )
            if dg_response.data is None:
                self.logger.error("Failed to list dynamic groups")
                return False
            for dg in dg_response.data:
                self.dynamic_groups.append(self.parse_dynamic_group(
                    dg_domain="Default", dg_name=dg.name, dg_ocid=dg.id,
                    dg_rule=dg.matching_rule, dg_created=str(dg.time_created)
                ))
            self.logger.info(f"Loaded {len(self.dynamic_groups)} dynamic groups")
            return True
        except ServiceError as se:
            self.logger.error(f"Failed to load dynamic groups: {se}")
            return False

    def set_statements(self, statements: list):
        self.policies = statements

    def dg_in_use(self, dg: list) -> bool:
        for statement in self.policies:
            for subj in statement[7]:
                if subj[0] and dg[0].casefold() == subj[0].casefold() and dg[1].casefold() == subj[1].casefold():
                    return True
        return False

    def run_dg_in_use_analysis(self) -> list:
        unused_dynamic_groups = []
        for dg in self.dynamic_groups:
            dg[5] = self.dg_in_use(dg)
            if not dg[5]:
                unused_dynamic_groups.append(dg)
        self.logger.info(f"Found {len(unused_dynamic_groups)} unused dynamic groups")
        return unused_dynamic_groups

    def filter_dynamic_groups(self, domain_filter: str, name_filter: str, type_filter: str, ocid_filter: str) -> list:
        filtered = self.dynamic_groups
        for filt in domain_filter.split('|'):
            filtered = [dg for dg in filtered if filt.casefold() in dg[0].casefold()]
        for filt in name_filter.split('|'):
            filtered = [dg for dg in filtered if filt.casefold() in dg[1].casefold()]
        for filt in type_filter.split('|'):
            filtered = [dg for dg in filtered if filt.casefold() in dg[3].casefold()]
        for filt in ocid_filter.split('|'):
            filtered = [dg for dg in filtered if filt.casefold() in dg[2].casefold()]
        self.logger.info(f"Filtered to {len(filtered)} dynamic groups")
        return filtered

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

def select_subject_any():
    entry_subj.config(state=tk.DISABLED if use_subject_any.get() else tk.NORMAL)
    entry_subj.delete(0, tk.END)
    if use_subject_any.get():
        entry_subj.insert(0, "any-user|any-group")
    update_policy_output()

def select_location_tenancy():
    entry_loc.config(state=tk.DISABLED if location_filter_tenancy.get() else tk.NORMAL)
    entry_loc.delete(0, tk.END)
    if location_filter_tenancy.get():
        entry_loc.insert(0, "tenancy")
    update_policy_output()

def select_hierarchy_root():
    entry_hierarchy.config(state=tk.DISABLED if hierarchy_filter_root.get() else tk.NORMAL)
    entry_hierarchy.delete(0, tk.END)
    if hierarchy_filter_root.get():
        entry_hierarchy.insert(0, "ROOT")
    update_policy_output()

def update_policy_output():
    filtered = policy_analysis.filter_policy_statements(
        entry_subj.get(), entry_verb.get(), entry_res.get(), entry_loc.get(),
        entry_hierarchy.get(), entry_condition.get(), entry_text.get(), entry_policy.get()
    )
    label_status_bar.config(text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                                f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                                f"tksheet: {tksheet.__version__} | Loaded as of: {policy_analysis.data_as_of}")
    label_policy_count.config(text=f"Statements (Filtered): {len(filtered)}")
    sheet_policies.set_sheet_data(filtered, reset_highlights=True)
    sheet_policies.display_columns(
        all_columns_displayed=True if chk_show_expanded.get() else False,
        columns=[0, 3, 4] if not chk_show_expanded.get() else None
    )
    rows_to_show = [
        i for i, st in enumerate(filtered)
        if (chk_show_special.get() and (st[6] == "define" or st[4].startswith(("endorse", "admit")))
            or chk_show_service.get() and st[6] == "service"
            or chk_show_dynamic.get() and st[6] == "dynamic-group"
            or chk_show_resource.get() and st[6] == "resource"
            or chk_show_regular.get() and st[6] in ["group", "any-user", "any-group"])
    ]
    sheet_policies.display_rows(rows=rows_to_show, all_displayed=not rows_to_show)
    for i, st in enumerate(filtered):
        if not st[5]:
            sheet_policies.highlight_cells(row=i, column='all', bg="pink")

def update_dg_output():
    filtered = dyn_group_analysis.filter_dynamic_groups(
        dg_entry_domain.get(), dg_entry_name.get(), dg_entry_type.get(), dg_entry_ocid.get()
    )
    sheet_dynamic_group.set_sheet_data(filtered, reset_highlights=True)
    sheet_dynamic_group.display_columns(all_columns_displayed=True)
    for i, dg in enumerate(filtered):
        sheet_dynamic_group.set_cell_data(i, 3, "\n".join(dg[4]), keep_formatting=True)
        sheet_dynamic_group.set_cell_data(i, 5, "\n".join(dg[6]), keep_formatting=True)
        if not dg[5]:
            sheet_dynamic_group.highlight_cells(row=i, column='all', bg="pink")
    sheet_dynamic_group.set_all_cell_sizes_to_text()
    dg_label_count.config(text=f"Dynamic Groups (Filtered): {len(filtered)}")

def export_policy_to_csv():
    filepath = tk.filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    if filepath:
        filtered = policy_analysis.filter_policy_statements(
            entry_subj.get(), entry_verb.get(), entry_res.get(), entry_loc.get(),
            entry_hierarchy.get(), entry_condition.get(), entry_text.get(), entry_policy.get()
        )
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(sheet_policies.headers())
            writer.writerows(filtered)
        logger.info(f"Exported {len(filtered)} policy statements to {filepath}")

def export_dg_to_csv():
    filepath = tk.filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")])
    if filepath:
        filtered = dyn_group_analysis.filter_dynamic_groups(
            dg_entry_domain.get(), dg_entry_name.get(), dg_entry_type.get(), dg_entry_ocid.get()
        )
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(sheet_dynamic_group.headers())
            writer.writerows(filtered)
        logger.info(f"Exported {len(filtered)} dynamic groups to {filepath}")

def run_dg_analysis():
    dyn_group_analysis.set_statements(policy_analysis.regular_statements)
    dyn_group_analysis.run_dg_in_use_analysis()
    update_dg_output()

def show_policy_detail(event=None):
    current_selection = sheet_policies.get_currently_selected()
    if current_selection:
        selected_row = sheet_policies.displayed_row_to_data(current_selection.row)
        selected_column = sheet_policies.displayed_column_to_data(current_selection.column)
        data = sheet_policies.data[selected_row][selected_column]
        logger.info(f"Selected row: {current_selection.row}, column: {selected_column}, data: {data}")
        messagebox.showinfo("Policy Detailed Statement", str(data))

def show_dg_detail(event=None):
    current_selection = sheet_dynamic_group.get_currently_selected()
    if current_selection:
        selected_row = sheet_dynamic_group.displayed_row_to_data(current_selection.row)
        matching_rule = sheet_dynamic_group.data[selected_row][3]  # Matching Rule is at index 3
        logger.info(f"Selected row: {current_selection.row}, Matching Rule: {matching_rule}")
        messagebox.showinfo("Dynamic Group Matching Rule", str(matching_rule))

def toggle_profile_dropdown():
    if use_instance_principal.get() and os.getenv("OCI_RESOURCE_PRINCIPAL_VERSION"):
        input_profile.grid_remove()
        label_profile.grid_remove()
    else:
        input_profile.grid(row=0, column=2, padx=5, pady=3)
        label_profile.grid(row=0, column=1, padx=5, pady=3)

def load_from_cache():
    # Placeholder for Load from Cache implementation
    logger.info("Load from Cache button clicked - implementation pending")
    pass

def main():
    global window, profile_var, use_instance_principal, entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy, \
           entry_condition, entry_text, entry_policy, dg_entry_domain, dg_entry_name, dg_entry_type, dg_entry_ocid, \
           sheet_policies, sheet_dynamic_group, label_policy_count, dg_label_count, btn_update, btn_clear, \
           btn_export_policy, dg_btn_update, dg_btn_clear, dg_btn_export, btn_analyze, use_subject_any, location_filter_tenancy, \
           hierarchy_filter_root, chk_show_special, chk_show_service, chk_show_dynamic, chk_show_resource, chk_show_regular, \
           chk_show_expanded, input_profile, policy_analysis, dyn_group_analysis, progress_bar, label_status_bar, last_load_time, \
           label_profile, btn_load_tenancy, btn_load_cache

    args = parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Check if Instance Principal is available
    instance_principal_available = os.getenv("OCI_RESOURCE_PRINCIPAL_VERSION") is not None

    # Initialize policy and dynamic group analysis
    policy_analysis = PolicyAnalysis(args.verbose)
    dyn_group_analysis = DynamicGroupAnalysis(args.verbose)

    window = tk.Tk()
    window.title("OCI Policy and Dynamic Group Viewer")
    window.geometry("1200x800")
    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)

    # Top frame
    frm_init = ttk.Frame(window)
    frm_init.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
    frm_init.columnconfigure(5, weight=1)

    # Instance Principal checkbox (only shown if available)
    use_instance_principal = tk.BooleanVar()
    if instance_principal_available:
        ttk.Checkbutton(frm_init, text="Instance Principal", variable=use_instance_principal, command=toggle_profile_dropdown).grid(row=0, column=0, padx=5, pady=3)
        col_offset = 1
    else:
        col_offset = 0

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
    label_profile.grid(row=0, column=col_offset, padx=5, pady=3)
    input_profile = ttk.OptionMenu(frm_init, profile_var, profile_var.get(), *profile_list)
    input_profile.grid(row=0, column=col_offset + 1, padx=5, pady=3)

    # Load buttons
    btn_load_tenancy = ttk.Button(frm_init, text="Load from Tenancy", command=load_data)
    btn_load_tenancy.grid(row=0, column=col_offset + 2, padx=5, pady=3)
    btn_load_cache = ttk.Button(frm_init, text="Load from Cache", command=load_from_cache)
    btn_load_cache.grid(row=0, column=col_offset + 3, padx=5, pady=3)

    # Progress bar (initially hidden)
    progress_bar = ttk.Progressbar(frm_init, mode="indeterminate", length=100)
    progress_bar.grid(row=0, column=col_offset + 4, padx=5, pady=3, sticky="e")
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
    tab_advanced = ttk.Frame(tab_control)
    tab_control.add(tab_policy, text="All Policies")
    tab_control.add(tab_dg, text="Dynamic Groups")
    tab_control.add(tab_advanced, text="Advanced Analysis")
    tab_control.grid(row=1, column=0, sticky="nsew")

    # Policy Tab
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
    ttk.Checkbutton(frm_subj, text="Any-User/Group", variable=use_subject_any, command=select_subject_any).grid(row=0, column=1, padx=2)
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
    ttk.Checkbutton(frm_loc, text="Tenancy", variable=location_filter_tenancy, command=select_location_tenancy).grid(row=0, column=1, padx=2)
    frm_loc.grid(row=2, column=3, padx=5, pady=2, sticky="ew")

    frm_hierarchy = ttk.Frame(frm_policy_filter)
    ttk.Label(frm_policy_filter, text="Hierarchy").grid(row=3, column=0, padx=5, pady=2, sticky="w")
    entry_hierarchy = tk.Entry(frm_hierarchy, state=tk.DISABLED, width=20)
    entry_hierarchy.grid(row=0, column=0, padx=2, sticky="ew")
    hierarchy_filter_root = tk.BooleanVar()
    ttk.Checkbutton(frm_hierarchy, text="Root", variable=hierarchy_filter_root, command=select_hierarchy_root).grid(row=0, column=1, padx=2)
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
    btn_export_policy = ttk.Button(frm_policy_buttons, text="Export CSV", state=tk.DISABLED, command=export_policy_to_csv)
    btn_export_policy.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
    frm_policy_buttons.grid(row=1, column=4, rowspan=4, padx=5, pady=2, sticky="ns")

    frm_policy_output = ttk.Frame(frm_policy_top)
    frm_policy_output.grid(row=1, column=0, sticky="ew")
    frm_policy_output.columnconfigure(0, weight=1)
    label_policy_count = ttk.Label(frm_policy_output, text="Statements (Filtered): 0")
    label_policy_count.grid(row=0, column=0, padx=5, pady=3, sticky="w")
    chk_show_special = tk.BooleanVar()
    chk_show_service = tk.BooleanVar()
    chk_show_dynamic = tk.BooleanVar()
    chk_show_resource = tk.BooleanVar()
    chk_show_regular = tk.BooleanVar(value=True)
    chk_show_expanded = tk.BooleanVar()
    ttk.Checkbutton(frm_policy_output, text="Cross-Tenancy", variable=chk_show_special, command=update_policy_output).grid(row=0, column=1, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Service", variable=chk_show_service, command=update_policy_output).grid(row=0, column=2, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Dynamic", variable=chk_show_dynamic, command=update_policy_output).grid(row=0, column=3, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Resource", variable=chk_show_resource, command=update_policy_output).grid(row=0, column=4, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Regular", variable=chk_show_regular, command=update_policy_output).grid(row=0, column=5, padx=5, pady=3)
    ttk.Checkbutton(frm_policy_output, text="Expanded", variable=chk_show_expanded, command=update_policy_output).grid(row=0, column=6, padx=5, pady=3)
    btn_analyze = ttk.Button(frm_policy_output, text="Analyze DGs", state=tk.DISABLED, command=run_dg_analysis)
    btn_analyze.grid(row=0, column=7, padx=5, pady=3)

    frm_policy_sheet = ttk.Frame(tab_policy)
    frm_policy_sheet.grid(row=1, column=0, sticky="nsew")
    sheet_policies = tksheet.Sheet(
        frm_policy_sheet, theme="light green", font=("TkFixedFont", 10, "normal"),
        header_font=("TkFixedFont", 11, "bold"), index_font=("TkFixedFont", 11, "bold"),
        headers=["Policy Name", "Policy OCID", "Compartment OCID", "Hierarchy", "Statement Text", "Valid",
                 "Subject Type", "Subject", "Verb", "Resource", "Permission", "Location Type", "Location",
                 "Conditions", "Comments", "Creation Time", "Parsed"],
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )
    sheet_policies.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")
    sheet_policies.popup_menu_add_command("Show Details", show_policy_detail)
    sheet_policies.bind("<Button-3>", show_policy_detail)
    sheet_policies.pack(expand=True, fill=tk.BOTH)

    def bind_horizontal_scroll(sheet):
        sheet.bind("<MouseWheel>", lambda event: sheet.xview_scroll(-1 if event.delta > 0 else 1, "units"))
    bind_horizontal_scroll(sheet_policies)

    # Dynamic Group Tab
    frm_dg_filter = ttk.Frame(tab_dg)
    frm_dg_filter.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
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
    ttk.Label(frm_dg_filter, text="Type").grid(row=2, column=0, padx=5, pady=2, sticky="w")
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
    dg_btn_export.grid(row=2, column=0, padx=5, pady=2, sticky="ew")
    frm_dg_buttons.grid(row=1, column=4, rowspan=2, padx=5, pady=2, sticky="ns")

    frm_dg_output = ttk.Frame(tab_dg)
    frm_dg_output.grid(row=1, column=0, sticky="ew")
    frm_dg_output.columnconfigure(0, weight=1)
    dg_label_count = ttk.Label(frm_dg_output, text="Dynamic Groups (Filtered): 0")
    dg_label_count.grid(row=0, column=0, padx=5, pady=3, sticky="w")

    frm_dg_sheet = ttk.Frame(tab_dg)
    frm_dg_sheet.grid(row=2, column=0, sticky="nsew")
    sheet_dynamic_group = tksheet.Sheet(
        frm_dg_sheet, theme="light green", font=("TkFixedFont", 10, "normal"),
        header_font=("TkFixedFont", 11, "bold"), index_font=("TkFixedFont", 11, "bold"),
        headers=["Domain", "Name", "OCID", "Rule Components", "In Use", "Invalid OCIDs", "Creation Time"],
        auto_resize_columns=200, show_x_scrollbar=True, show_y_scrollbar=True
    )
    sheet_dynamic_group.enable_bindings("single_select", "column_width_resize", "row_select", "copy", "rc_select")
    sheet_dynamic_group.popup_menu_add_command("Show Matching Rule", show_dg_detail)
    sheet_dynamic_group.bind("<Button-3>", show_dg_detail)
    sheet_dynamic_group.pack(expand=True, fill=tk.BOTH)
    bind_horizontal_scroll(sheet_dynamic_group)

    window.mainloop()

def load_data():
    global last_load_time
    progress_bar.grid()
    progress_bar.start()
    label_status_bar.config(text="Loading data...")

    def load():
        try:
            profile = profile_var.get()
            use_ip = use_instance_principal.get() and os.getenv("OCI_RESOURCE_PRINCIPAL_VERSION") is not None
            success = policy_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize policy client")
            success = dyn_group_analysis.initialize_client(use_ip, profile)
            if not success:
                raise RuntimeError("Failed to initialize dynamic group client")
            success = policy_analysis.load_policies_from_client()
            if not success:
                raise RuntimeError("Failed to load policies")
            dyn_group_analysis.load_all_dynamic_groups()
            last_load_time = policy_analysis.data_as_of
            window.after(0, lambda: (
                label_status_bar.config(
                    text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                         f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                         f"tksheet: {tksheet.__version__} | Loaded as of: {last_load_time}"
                ),
                [e.config(state=tk.NORMAL) for e in [entry_subj, entry_verb, entry_res, entry_loc, entry_hierarchy,
                                                     entry_condition, entry_text, entry_policy, dg_entry_domain,
                                                     dg_entry_name, dg_entry_type, dg_entry_ocid]],
                [b.config(state=tk.NORMAL) for b in [btn_update, btn_clear, btn_export_policy, dg_btn_update,
                                                    dg_btn_clear, dg_btn_export, btn_analyze]],
                update_policy_output()
            ))
            logger.info(f"Load successful: Last Load: {last_load_time}")
        except Exception as e:
            window.after(0, lambda: label_status_bar.config(
                text=f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | "
                     f"OCI: {oci.__version__} | Tkinter: {tk.Tcl().eval('info patchlevel')} | "
                     f"tksheet: {tksheet.__version__} | Error: {e}"
            ))
            logger.error(f"Load error: {e}")
        finally:
            window.after(0, lambda: (progress_bar.stop(), progress_bar.grid_remove()))

    Thread(target=load, daemon=True).start()

if __name__ == "__main__":
    main()