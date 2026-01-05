##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# visual_policy_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.policy_statement_normalizer import PolicyStatementNormalizer

# Logger
logger = get_logger(component='visual_policy_tab')


class VisualPolicyTab(ttk.Frame):
    """Tab for entering a policy statement and visualizing all parsed details."""

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, **kwargs)
        self.app = app

        # --- Top area: Entry for policy statement ---
        label = ttk.Label(self, text='Enter a Policy Statement to Visualize')
        label.pack(padx=12, pady=(16, 0), anchor='w')

        self.statement_var = tk.StringVar()
        entry = ttk.Entry(self, textvariable=self.statement_var, width=100)
        entry.pack(padx=12, pady=(0, 10), fill='x')

        # --- Button ---
        self.btn_parse = ttk.Button(self, text='Show Parsed Data', command=self.on_parse)
        self.btn_parse.pack(padx=12, pady=(0, 18), anchor='w')

        # --- Output area (Frame for labels or text) ---
        self.output_frame = ttk.LabelFrame(self, text='Parsed Data', padding=(10, 8))
        self.output_frame.pack(padx=12, pady=(0, 12), fill='both', expand=True)

        # For output sections, reserve labels; initial text is blank
        self.lbl_parsed = ttk.Label(
            self.output_frame, text='Parsed Statement: ', anchor='w', justify='left', wraplength=950
        )
        self.lbl_parsed.pack(fill='x', pady=2)
        self.lbl_effective_path = ttk.Label(
            self.output_frame, text='Effective Path: ', anchor='w', justify='left', wraplength=950
        )
        self.lbl_effective_path.pack(fill='x', pady=2)
        self.lbl_subject = ttk.Label(self.output_frame, text='Subject: ', anchor='w', justify='left', wraplength=950)
        self.lbl_subject.pack(fill='x', pady=2)
        self.lbl_where = ttk.Label(self.output_frame, text='Where Clause: ', anchor='w', justify='left', wraplength=950)
        self.lbl_where.pack(fill='x', pady=2)
        self.lbl_permissions = ttk.Label(
            self.output_frame, text='Permissions: ', anchor='w', justify='left', wraplength=950
        )
        self.lbl_permissions.pack(fill='x', pady=2)

        # Use the app's ReferenceDataRepo and PolicyAnalysisRepository; do not create new ones.
        # (No local self.ref_repo needed; remove if present.)

    def on_parse(self):  # noqa: C901
        logger.info(f'Parsing policy statement from Visual Policy Tab: {self.statement_var.get().strip()}')
        statement = self.statement_var.get().strip()
        if not statement:
            self.lbl_parsed.config(text='Parsed Statement: (Please enter a policy statement.)')
            self.lbl_effective_path.config(text='Effective Path: ')
            self.lbl_subject.config(text='Subject: ')
            self.lbl_where.config(text='Where Clause: ')
            self.lbl_permissions.config(text='Permissions: ')
            return

        # Run parser and show details
        try:
            # Normalizer expects base_fields - minimal for ad-hoc parse
            base_fields = {
                'policy_name': '(ad-hoc)',
                'policy_description': '',
                'policy_ocid': '',
                'compartment_ocid': '',
                'compartment_path': '',
                'statement_text': statement,
                'creation_time': '',
                'internal_id': '',
                'parsed': False,
            }
            normalizer = PolicyStatementNormalizer()
            # Default to 'allow' if not easily inferred
            parsed_obj = normalizer.normalize(statement, 'allow', base_fields)

            # Log the entire parsed object for debugging
            logger.info(f'Parsed object from statement: {parsed_obj}')

            if not parsed_obj:
                self.lbl_parsed.config(text='Parsed Statement: (Parsing failed)')
                self.lbl_effective_path.config(text='Effective Path: ')
                self.lbl_subject.config(text='Subject: ')
                self.lbl_where.config(text='Where Clause: ')
                self.lbl_permissions.config(text='Permissions: ')
                return

            # Copy to dict for effective path calculation (prevents mutating dataclass/obj)
            st_dict = dict(parsed_obj.__dict__) if hasattr(parsed_obj, '__dict__') else dict(parsed_obj)
            # Calculate effective path using the main repository indexes (if available)
            # Use app's PolicyAnalysisRepository and ReferenceDataRepo
            repo = getattr(self.app, 'policy_compartment_analysis', None)
            ref_repo = getattr(self.app, 'ref_repo', None)
            if repo and isinstance(repo, PolicyAnalysisRepository):
                logger.info(f'Calculating effective compartment/path for visualized statement: {st_dict}')
                try:
                    repo.calculate_effective_compartment_for_statement(st_dict)
                except Exception as calc_exc:
                    st_dict['effective_path'] = f'(Path calculation error: {calc_exc})'

            subj = st_dict.get('subject', '')
            verb = st_dict.get('verb', '')
            resource = st_dict.get('resource', '')
            eff_path = st_dict.get('effective_path', '') or st_dict.get('location', '')
            condition = st_dict.get('conditions', '') or st_dict.get('where_clause', '')
            perms = st_dict.get('permission', [])

            try:
                ref_perms = ''
                if resource and verb and ref_repo is not None:
                    ref_list = ref_repo.get_permissions(resource, verb)
                    if ref_list is not None:
                        if isinstance(ref_list, list | tuple):
                            ref_perms = ', '.join(str(x) for x in ref_list)
                        else:
                            ref_perms = str(ref_list)
                    else:
                        ref_perms = '(Unknown resource/verb or permissions unavailable)'
                elif not ref_repo:
                    ref_perms = '(Reference data not loaded in application.)'
                else:
                    ref_perms = '(No resource or verb identified.)'
            except Exception as e:
                ref_perms = f'(Failed to resolve permissions: {e})'

            self.lbl_parsed.config(text=f'Parsed Statement: {statement}')
            self.lbl_effective_path.config(text=f"Effective Path: {eff_path or '(not found)'}")
            self.lbl_subject.config(text=f"Subject: {subj or '(not found)'}")
            self.lbl_where.config(text=f"Where Clause: {condition or '(none)'}")
            self.lbl_permissions.config(
                text=f"Permissions: {', '.join(perms) if perms else '(none)'}\nFull permission list for resource/verb: {ref_perms}"
            )
        except Exception as exc:
            self.lbl_parsed.config(text=f'Parsed Statement: (Exception: {exc})')
            self.lbl_effective_path.config(text='Effective Path: ')
            self.lbl_subject.config(text='Subject: ')
            self.lbl_where.config(text='Where Clause: ')
            self.lbl_permissions.config(text='Permissions: ')
