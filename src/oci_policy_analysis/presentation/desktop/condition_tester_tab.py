##########################################################################
# Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# condition_tester_tab.py
#
# Tab for interactive OCI Condition Tester (AST-based) with simulated variables
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

import tkinter as tk
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker
from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService
from oci_policy_analysis.presentation.desktop.base_tab import BaseUITab

logger = get_logger('condition_tester_tab')


class ConditionTesterTab(BaseUITab):
    """
    UI Tab for interactively testing OCI Condition (Where) clauses using an AST simulation (ANTLR).
    Allows user to provide a where clause and simulated environment variables,
    and see evaluation/log details.
    """

    def __init__(self, parent, app):
        super().__init__(
            parent,
            default_help_text=(
                'Test OCI policy condition (where) clauses interactively. Enter the condition clause, '
                'generate input variables, and evaluate result using simulated inputs below. '
                "Use 'Actions' for formatting, generating, or evaluating the expression."
            ),
        )
        self.app = app
        self.condition_service = ConditionTesterService()
        self._build_ui()

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Apply main settings for context help and font size.
        """
        super().apply_settings(context_help, font_size)

    def _build_ui(self):
        # Row 0: Where Clause Entry (multiline, with Format)
        clause_frame = ttk.LabelFrame(self, text='Condition (Where) Clause')
        clause_frame.pack(fill=tk.X, padx=10, pady=5)
        self.add_context_help(
            clause_frame,
            "Enter an OCI policy 'where' condition clause here. Example: all { request.principal.id=target.bucket.owner.id }",
        )

        # Make clause text 6 lines, resizable if tab expands
        self.clause_text = ScrolledText(clause_frame, height=10, width=120, wrap=tk.WORD, font=('Consolas', 10))
        self.clause_text.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)
        # Keep clause_var for compatibility, but keep in sync with clause_text content
        self.clause_var = tk.StringVar()

        def sync_clause_var(event=None):
            self.clause_var.set(self.clause_text.get('1.0', tk.END).strip())

        self.clause_text.bind('<FocusOut>', sync_clause_var)
        self.add_context_help(self.clause_text, 'Edit the policy WHERE clause here (multi-line allowed).')

        # Actions Frame: Row 1+3 together in a single label frame, all horizontally
        actions_frame = ttk.LabelFrame(self, text='Actions')
        actions_frame.pack(fill=tk.X, padx=10, pady=(2, 6))
        self.add_context_help(
            actions_frame,
            'Use these action buttons to generate variable inputs, format the clause, '
            'evaluate the clause with variables, or clear the output log.',
        )

        gen_btn = ttk.Button(actions_frame, text='Generate/Clear Inputs', command=self._generate_inputs)
        gen_btn.pack(side=tk.LEFT, padx=(8, 8), pady=7)
        self.add_context_help(gen_btn, 'Parse the clause and generate input fields for required variables.')

        format_btn = ttk.Button(actions_frame, text='Format', command=self._format_clause)
        format_btn.pack(side=tk.LEFT, padx=(0, 8), pady=7)
        self.add_context_help(format_btn, 'Auto-format and indent the condition clause for readability.')

        eval_btn = ttk.Button(actions_frame, text='Evaluate Condition', command=self._evaluate_condition)
        eval_btn.pack(side=tk.LEFT, padx=(0, 8), pady=7)
        self.add_context_help(eval_btn, 'Run the condition clause against provided input variables.')

        clear_btn = ttk.Button(actions_frame, text='Clear Output', command=self._clear_output)
        clear_btn.pack(side=tk.LEFT, padx=(0, 8), pady=7)
        self.add_context_help(clear_btn, 'Clear the output/results log below.')

        # Row 2: Simulated Inputs (Tk widgets, dynamic) - dynamically sized to content
        self.vars_frame = ttk.LabelFrame(self, text='Simulated Input Variables')
        self.vars_frame.pack(fill=tk.X, padx=10, pady=5)
        self.input_widgets = {}
        self.add_context_help(self.vars_frame, 'Input example values for the variables referenced in your clause.')

        # Row 4: Results/Log
        results_group = ttk.LabelFrame(self, text='Evaluation Result / Log')
        results_group.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        self.results_text = ScrolledText(results_group, height=12, width=100, wrap=tk.WORD, font=('Consolas', 10))
        self.results_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.results_text.insert(tk.END, 'Result details will appear here.\n')
        self.add_context_help(self.results_text, 'Result log: evaluation result, step-by-step comparison/computation.')
        # Setup tags for colored logging
        self.results_text.tag_configure('log_granted', foreground='green')
        self.results_text.tag_configure('log_denied', foreground='red')
        self.results_text.tag_configure('log_head', foreground='#006699', font=('Consolas', 11, 'bold'))

    def set_clause_text(self, text):
        """Programmatically set the contents of the where clause input."""
        self.clause_text.delete('1.0', tk.END)
        self.clause_text.insert(tk.END, text)
        self.clause_var.set(text.strip())

    # === NEW: Extract variables from clause / generate input fields ===
    def _generate_inputs(self):
        clause = self.clause_text.get('1.0', tk.END).strip()
        self.clause_var.set(clause)
        var_names = self.condition_service.extract_variables(clause)
        logger.info(f'Generating inputs for clause: {clause}')
        logger.info(f'Extracted variables ({len(var_names)}): {sorted(var_names)}')
        for widget in self.vars_frame.winfo_children():
            widget.destroy()
        self.input_widgets = {}

        # Let frame's dynamic height adjust to number of rows (no fixed height)
        EXAMPLES = {
            'request.utc-timestamp': 'e.g. 2026-01-05T12:34:56Z',
            'request.utc-timestamp.time-of-day': 'e.g. 13:27:00Z',
        }
        for i, var in enumerate(sorted(var_names)):
            var_label = ttk.Label(self.vars_frame, text=var + ':')
            var_label.grid(row=i, column=0, sticky=tk.W, padx=4, pady=2)
            var_str = tk.StringVar()
            entry = ttk.Entry(self.vars_frame, textvariable=var_str, width=40)
            entry.grid(row=i, column=1, padx=4, pady=2)
            # Add format example to the right if this is a time/timestamp variable
            example_hint = ''
            if var == 'request.utc-timestamp':
                example_hint = EXAMPLES['request.utc-timestamp']
            elif var == 'request.utc-timestamp.time-of-day':
                example_hint = EXAMPLES['request.utc-timestamp.time-of-day']
            if example_hint:
                ttk.Label(
                    self.vars_frame, text=example_hint, foreground='#666', font=('TkDefaultFont', 9, 'italic')
                ).grid(row=i, column=2, padx=(2, 2), sticky='w')
            self.input_widgets[var] = var_str

        # Adjust frame minheight to match variable count for cleaner look
        self.vars_frame.update_idletasks()
        frame_height = max(40, len(var_names) * 34)  # Rough estimate ~34px per row
        self.vars_frame.config(height=frame_height)

    def _format_clause(self):
        """Format the where-clause text using shared condition service logic."""
        raw = self.clause_text.get('1.0', tk.END).strip()
        try:
            pretty = self.condition_service.format_clause(raw)
            if pretty and pretty != raw:
                self.clause_text.delete('1.0', tk.END)
                self.clause_text.insert(tk.END, pretty)
                self.clause_var.set(pretty)
                logger.info('Condition clause formatted with beautifier.')
        except Exception as ex:
            logger.warning(f'Clause formatting failed: {ex}')

    # === Evaluate Logic Embedded ===
    def _evaluate_condition(self):
        clause = self.clause_text.get('1.0', tk.END).strip()
        self.clause_var.set(clause)
        sim_vars = {k: v.get() for k, v in self.input_widgets.items()}
        logger.info(f'Evaluate condition: {clause}')
        logger.info(f'Using simulated variables: {sim_vars}')
        # Anonymous usage tracking: record condition test metadata (no clause text).
        try:
            tracker = get_usage_tracker()
            if tracker is not None:
                tracker.track_operation(
                    'condition_test',
                    var_count=len(sim_vars),
                )
        except Exception:
            logger.debug('Usage tracking for condition_test failed', exc_info=True)
        # We should get this from the main in __init__ and not try to initialize it here
        try:
            evaluated = self.condition_service.evaluate(clause, sim_vars)
            result = {
                'Condition String': evaluated.condition_string,
                'Policy Result': evaluated.policy_result,
                'Log': evaluated.log,
            }
        except Exception as ex:
            logger.error(f'Evaluation error: {ex}')
            result = {
                'Condition String': clause,
                'Policy Result': 'ERROR',
                'Log': [
                    {
                        'type': 'Exception',
                        'result': False,
                        'variable': '?',
                        'operator': '?',
                        'sim_value': '?',
                        'expected': '?',
                        'info': str(ex),
                    }
                ],
            }
        self._show_result(result)

    def _clear_output(self):
        self.results_text.delete('1.0', tk.END)

    # No longer needed: The condition test logic is now unified in the PolicySimulationEngine.
    def _show_result(self, result_dict):  # noqa: C901
        # Robustify: Accept tuple or dict for compatibility
        if isinstance(result_dict, tuple):
            # Handle tuple of (bool, string) or sometimes (bool, dict) as returned from engine._evaluate_conditions
            # Try to convert to a display dict
            if len(result_dict) == 2 and isinstance(result_dict[0], bool) and isinstance(result_dict[1], str):
                granted = result_dict[0]
                details = result_dict[1]
                # Try to extract a variable/operator/result from the details using regex
                if 'Details:' in details and 'variable' in details:
                    # Try to eval() the details dict just for display if present
                    import ast

                    try:
                        detail_part = details.split('Details:', 1)[1].strip()
                        detail_dict = ast.literal_eval(detail_part) if '{' in detail_part and '}' in detail_part else {}
                        log_list = [detail_dict] if isinstance(detail_dict, dict) and detail_dict else []
                    except Exception:
                        log_list = []
                else:
                    log_list = []
                result_dict = {
                    'Condition String': '',
                    'Policy Result': 'GRANTED' if granted else 'DENIED',
                    'Log': log_list
                    if log_list
                    else [
                        {
                            'type': 'No detail',
                            'result': granted,
                            'variable': '?',
                            'operator': '?',
                            'sim_value': '?',
                            'expected': '?',
                            'info': details,
                        }
                    ],
                }
            else:
                # Fallback: try to find an embedded dict as before
                found_dict = None
                for item in result_dict:
                    if isinstance(item, dict) and (
                        'Policy Result' in item or 'Log' in item or 'Condition String' in item
                    ):
                        found_dict = item
                        break
                if found_dict is not None:
                    result_dict = found_dict
                else:
                    self.results_text.insert(tk.END, f'\n[Result Error] Unrecognized tuple returned: {result_dict}\n')
                    return

        # Do NOT clear previous log; append a timestamped header and result.
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results_text.insert(tk.END, f"\n{'='*20} {now} {'='*20}\n", 'log_head')
        cond_str = result_dict.get('Condition String')
        self.results_text.insert(tk.END, f'Condition: {cond_str}\n', 'log_head')
        # Color result
        outcome_str = f"Access Result: {result_dict.get('Policy Result')}\n"
        if result_dict.get('Policy Result') == 'GRANTED':
            self.results_text.insert(tk.END, outcome_str, 'log_granted')
        else:
            self.results_text.insert(tk.END, outcome_str, 'log_denied')
        # Details/log - plain text
        self.results_text.insert(tk.END, '--- Comparison Log ---\n')
        log = result_dict.get('Log', [])
        if log:
            for entry in log:
                # Print a clean/pass/fail line even if some elements are missing
                sim_val = entry.get('sim_value', '')
                result = entry.get('result', False)
                operator = entry.get('operator', '')
                expected = entry.get('expected', '')
                var = entry.get('variable', '')
                # Highlight GRANTED case (even with unknown details)
                if result is True:
                    status = 'PASS'
                else:
                    status = 'FAIL'
                if sim_val == 'MISSING':
                    self.results_text.insert(tk.END, f"  [FAIL] Variable '{var or '?'}' is MISSING.\n")
                elif all(x == '?' or x == '' for x in [sim_val, operator, expected, var]):
                    # All details are unknown or missing - just give result
                    self.results_text.insert(tk.END, f"  [{status}] {'Comparison performed; details unavailable'}\n")
                else:
                    self.results_text.insert(tk.END, f'  [{status}] {sim_val} {operator} {expected} -> {result}\n')
        else:
            self.results_text.insert(tk.END, '  No comparisons made / syntax or execution error.\n')
