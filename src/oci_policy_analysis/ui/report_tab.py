##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# report_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.11 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
import tkinter.filedialog as fd
from tkinter import ttk

from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.logger import get_logger

logger = get_logger(component='report_tab')


class ReportTab(ttk.Frame):
    def __init__(
        self,
        parent,
        main_app,
        policy_compartment_analysis: PolicyAnalysisRepository,
    ):
        super().__init__(parent)
        self.main_app = main_app
        self.policy_compartment_analysis = policy_compartment_analysis
        self.create_tab()

    def create_tab(self):
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=6)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        # self.grid_columnconfigure(1, weight=6)

        logger.info('Creating Report Tab')
        frm_report_top = ttk.Frame(self)
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
        frm_report = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
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

    def update_report_output(self):
        self.text_dg_report.delete(1.0, tk.END)
        self.text_policy_report.delete(1.0, tk.END)
        sorted_dgs = sorted(
            self.policy_compartment_analysis.dynamic_groups,
            key=lambda dg: (dg.get('domain_name'), dg.get('dynamic_group_name')),
        )
        dg_text = 'Dynamic Groups Report\n====================\n'
        if not sorted_dgs:
            dg_text += 'No dynamic groups found.\n'
        else:
            for dg in sorted_dgs:
                dg_text += f'Domain: {dg.get("domain_name")}\nName: {dg.get("dynamic_group_name")}\nMatching Rule: {dg.get("matching_rule")}\nOCID: {dg.get("dynamic_group_ocid")}\nCreated: {dg.get("creation_time")}\nIn Use: {"Yes" if dg.get("in_use") else "No"}\n\n'
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
                    if s.get('compartment_ocid') == comp['id']
                ]
                if statements:
                    policy_dict = {}
                    for s in statements:
                        policy_name = s.get('policy_name', 'Unknown Policy')
                        policy_ocid = s.get('policy_ocid', 'Unknown OCID')
                        if policy_name not in policy_dict:
                            policy_dict[policy_name] = {'ocid': policy_ocid, 'statements': []}
                        policy_dict[policy_name]['statements'].append(s.get('statement_text', 'No Statement Text'))
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

    def _export_report_to_txt(self):
        # Export the report to a text file
        filepath = fd.asksaveasfilename(defaultextension='.txt', filetypes=[('Text Files', '*.txt')])
        if filepath:
            dg_content = self.text_dg_report.get(1.0, tk.END).strip()
            policy_content = self.text_policy_report.get(1.0, tk.END).strip()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(dg_content + '\n\n' + policy_content)
            logger.info(f'Exported report to {filepath}')
