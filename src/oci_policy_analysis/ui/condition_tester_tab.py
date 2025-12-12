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

import re
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# ANTLR + condition parser imports inlined and used in place of condition_tester.run_condition_test
from antlr4 import CommonTokenStream, InputStream

from condition_parser.OciIamPolicyConditionLexer import OciIamPolicyConditionLexer
from condition_parser.OciIamPolicyConditionParser import OciIamPolicyConditionParser
from condition_parser.OciIamPolicyConditionVisitor import OciIamPolicyConditionVisitor
from oci_policy_analysis.common.logger import get_logger

logger = get_logger('condition_tester_tab')


class ConditionTesterTab(ttk.Frame):
    """
    UI Tab for interactively testing OCI Condition (Where) clauses using an AST simulation (ANTLR).
    Allows user to provide a where clause and simulated environment variables,
    and see evaluation/log details.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build_ui()

    def _build_ui(self):
        # Row 0: Where Clause Entry (multiline, with Format)
        clause_frame = ttk.LabelFrame(self, text='Condition (Where) Clause')
        clause_frame.pack(fill=tk.X, padx=10, pady=5)
        # Make clause text 6 lines, resizable if tab expands
        self.clause_text = ScrolledText(clause_frame, height=6, width=120, wrap=tk.WORD, font=('Consolas', 10))
        self.clause_text.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.BOTH, expand=True)
        # No manual pack_propagate or columnconfigure! Let default geometry work.
        # Keep clause_var for compatibility, but keep in sync with clause_text content
        self.clause_var = tk.StringVar()

        def sync_clause_var(event=None):
            self.clause_var.set(self.clause_text.get('1.0', tk.END).strip())

        self.clause_text.bind('<FocusOut>', sync_clause_var)

        # Row 1: Generate and Format buttons (below clause input)
        generate_row = ttk.Frame(self)
        generate_row.pack(fill=tk.X, padx=10, pady=(0, 5))
        gen_btn = ttk.Button(generate_row, text='Generate/Clear Inputs', command=self._generate_inputs)
        gen_btn.pack(side=tk.LEFT, padx=(0, 8))
        format_btn = ttk.Button(generate_row, text='Format', command=self._format_clause)
        format_btn.pack(side=tk.LEFT, padx=3)

        # Row 2: Simulated Inputs (Tk widgets, dynamic) - dynamically sized to content
        self.vars_frame = ttk.LabelFrame(self, text='Simulated Input Variables')
        self.vars_frame.pack(fill=tk.X, padx=10, pady=5)
        self.input_widgets = {}

        # Row 3: Evaluate/Clear
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        eval_btn = ttk.Button(button_frame, text='Evaluate Condition', command=self._evaluate_condition)
        eval_btn.pack(side=tk.LEFT, padx=(0, 8))
        clear_btn = ttk.Button(button_frame, text='Clear Output', command=self._clear_output)
        clear_btn.pack(side=tk.LEFT, padx=3)

        # Row 4: Results/Log
        results_group = ttk.LabelFrame(self, text='Evaluation Result / Log')
        results_group.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        self.results_text = ScrolledText(results_group, height=12, width=100, wrap=tk.WORD, font=('Consolas', 10))
        self.results_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.results_text.insert(tk.END, 'Result details will appear here.\n')

    def set_clause_text(self, text):
        """Programmatically set the contents of the where clause input."""
        self.clause_text.delete('1.0', tk.END)
        self.clause_text.insert(tk.END, text)
        self.clause_var.set(text.strip())

    # === NEW: Extract variables from clause / generate input fields ===
    def _generate_inputs(self):
        clause = self.clause_text.get('1.0', tk.END).strip()
        self.clause_var.set(clause)
        var_names = self._extract_variable_names(clause)
        logger.info(f'Generating inputs for clause: {clause}')
        logger.info(f'Extracted variables ({len(var_names)}): {sorted(var_names)}')
        for widget in self.vars_frame.winfo_children():
            widget.destroy()
        self.input_widgets = {}

        # Let frame's dynamic height adjust to number of rows (no fixed height)
        for i, var in enumerate(sorted(var_names)):
            var_label = ttk.Label(self.vars_frame, text=var + ':')
            var_label.grid(row=i, column=0, sticky=tk.W, padx=4, pady=2)
            var_str = tk.StringVar()
            entry = ttk.Entry(self.vars_frame, textvariable=var_str, width=40)
            entry.grid(row=i, column=1, padx=4, pady=2)
            self.input_widgets[var] = var_str

        # Adjust frame minheight to match variable count for cleaner look
        self.vars_frame.update_idletasks()
        frame_height = max(40, len(var_names) * 34)  # Rough estimate ~34px per row
        self.vars_frame.config(height=frame_height)

    def _format_clause(self):  # noqa: C901
        """Formats the where clause for readability (adds newlines/indents for { } blocks, preserves syntax)."""
        raw = self.clause_text.get('1.0', tk.END).strip()

        def beautify_policy_clause(txt):
            out = []
            indent = 0
            in_quote = False
            i = 0
            while i < len(txt):
                c = txt[i]
                # Handle quoted/pattern literals
                if in_quote:
                    if c == in_quote:
                        in_quote = False
                    out.append(c)
                elif c in ("'", '"', '/'):
                    in_quote = c
                    out.append(c)
                elif c == '{':
                    out.append(' {\n')
                    indent += 1
                    out.append('  ' * indent)
                elif c == '}':
                    out.append('\n')
                    indent = max(0, indent - 1)
                    out.append('  ' * indent)
                    out.append('}')
                elif c == ',':
                    out.append(',\n')
                    out.append('  ' * indent)
                elif c == '\n':
                    out.append('\n' + '  ' * indent)
                else:
                    out.append(c)
                i += 1
            return ''.join(out).strip()

        try:
            pretty = beautify_policy_clause(raw)
            if pretty and pretty != raw:
                self.clause_text.delete('1.0', tk.END)
                self.clause_text.insert(tk.END, pretty)
                self.clause_var.set(pretty)
                logger.info('Condition clause formatted with beautifier.')
        except Exception as ex:
            logger.warning(f'Clause formatting failed: {ex}')

    def _extract_variable_names(self, cond_str):
        # Use ANTLR parse: collect all variable names via tree walker or simple visitor
        input_stream = InputStream(cond_str + '\n')
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = OciIamPolicyConditionParser(stream)
        tree = parser.condition_clause()

        class VarCollector(OciIamPolicyConditionVisitor):
            def __init__(self):
                self.vars = set()

            def visitVariable_name(self, ctx):
                self.vars.add(ctx.getText())

        collector = VarCollector()
        collector.visit(tree)
        return collector.vars

    # === Evaluate Logic Embedded ===
    def _evaluate_condition(self):
        clause = self.clause_text.get('1.0', tk.END).strip()
        self.clause_var.set(clause)
        sim_vars = {k: v.get() for k, v in self.input_widgets.items()}
        logger.info(f'Evaluate condition: {clause}')
        logger.info(f'Using simulated variables: {sim_vars}')
        try:
            result = self._run_condition_test(clause, sim_vars)
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

    # === Inline run_condition_test logic from condition_tester.py ===
    def _run_condition_test(self, condition_str, variables):  # noqa: C901
        input_stream = InputStream(condition_str + '\n')  # noqa: F405
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)  # noqa: F405
        parser = OciIamPolicyConditionParser(stream)
        tree = parser.condition_clause()

        class ConditionExecutionVisitor(OciIamPolicyConditionVisitor):
            def __init__(self, simulated_variables):
                self.simulated_variables = simulated_variables
                self.comparison_log = []

            def visitSingle_condition(self, ctx):  # noqa: C901
                variable = ctx.variable_name().getText()
                operator = ctx.OPERATOR().getText().lower()
                value = None
                # --- Value Extraction ---
                if ctx.literal_list():
                    list_content = ctx.literal_list().literal_list_content()
                    values = [c.getText().strip("'") for c in list_content.getChildren()]
                    value = [v for v in values if v not in [',']]
                    value_token_type = 'literal_list'
                elif ctx.condition_value():  # covers single value and non-list
                    value_ctx = ctx.condition_value(0)
                    value_raw = value_ctx.getText().strip()
                    # Determine the token type (pattern, string, or identifier)
                    is_pattern = value_ctx.PATTERN_LITERAL() is not None
                    is_string = value_ctx.STRING_LITERAL() is not None
                    is_identifier = value_ctx.IDENTIFIER() is not None
                    value_token_type = (
                        'PATTERN_LITERAL'
                        if is_pattern
                        else 'STRING_LITERAL'
                        if is_string
                        else 'IDENTIFIER'
                        if is_identifier
                        else 'UNKNOWN'
                    )
                    logger.info(f'[RE-EVAL] Detected value raw: {repr(value_raw)}, token_type: {value_token_type}')
                    if is_pattern:
                        # Already includes slashes, e.g. /A-*/
                        value = value_raw
                    elif is_string:
                        value = value_raw[1:-1]
                    else:
                        value = value_raw
                else:
                    value = None
                    value_token_type = 'none'
                value_2 = None
                if operator == 'between' and ctx.condition_value(1):
                    value_2_ctx = ctx.condition_value(1)
                    value_2 = value_2_ctx.getText().strip()
                    if value_2_ctx.STRING_LITERAL() or value_2_ctx.PATTERN_LITERAL():
                        value_2 = value_2[1:-1]
                sim_value = self.simulated_variables.get(variable)

                log_entry = {
                    'variable': variable,
                    'operator': operator,
                    'sim_value': sim_value if sim_value is not None else 'MISSING',
                    'expected': str(value) if value_2 is None else f'[{value} AND {value_2}]',
                    'result': False,
                    'type': 'Simple Comparison',
                }
                if sim_value is None:
                    self.comparison_log.append(log_entry)
                    return False
                comparison_result = False
                # --- Main comparison logic; handle cases with value None or wrong type
                try:
                    if operator == '=':
                        # Regex match if explicitly pattern-literal
                        if (
                            value_token_type == 'PATTERN_LITERAL'
                            and isinstance(value, str)
                            and value.startswith('/')
                            and value.endswith('/')
                        ):
                            # Remove /.../ delimiters (pattern) and any wrapping quotes
                            pattern = value[1:-1]
                            pattern = pattern.strip('\'"')
                            cleaned_pattern = pattern
                            if '*' in pattern and '.*' not in pattern:
                                cleaned_pattern = cleaned_pattern.replace('*', '.*')
                            compare_target = sim_value or ''
                            logger.info(
                                f"[RE-EVAL] '=' Pattern: orig={repr(value)}, pattern={repr(pattern)}, cleaned_pattern={repr(cleaned_pattern)}, sim_value={repr(sim_value)}, compare_target(no strip)={repr(compare_target)}"
                            )
                            compare_target_stripped = (
                                compare_target.strip() if isinstance(compare_target, str) else compare_target
                            )
                            logger.info(
                                f'[RE-EVAL] Regex call: re.fullmatch({repr(cleaned_pattern)}, {repr(compare_target_stripped)})'
                            )
                            try:
                                match_result = re.fullmatch(cleaned_pattern, compare_target_stripped)
                                logger.info(
                                    f'[RE-EVAL] Regex match? {bool(match_result)} - Result object: {match_result}'
                                )
                                comparison_result = bool(match_result)
                            except Exception as rgx_ex:
                                logger.warning(f'Regex error: {rgx_ex} pattern={cleaned_pattern!r}')
                                comparison_result = False
                            log_entry['type'] = f'Regex match: /{cleaned_pattern}/'
                        else:
                            logger.info(
                                f"[RE-EVAL] '=' String compare: sim_value={repr(sim_value)}, value={repr(value)}"
                            )
                            if isinstance(sim_value, str) and isinstance(value, str):
                                comparison_result = sim_value.strip() == value.strip()
                            else:
                                comparison_result = sim_value == value
                    elif operator == '!=':
                        if (
                            value_token_type == 'PATTERN_LITERAL'
                            and isinstance(value, str)
                            and value.startswith('/')
                            and value.endswith('/')
                        ):
                            pattern = value[1:-1]
                            pattern = pattern.strip('\'"')
                            cleaned_pattern = pattern
                            if '*' in pattern and '.*' not in pattern:
                                cleaned_pattern = cleaned_pattern.replace('*', '.*')
                            compare_target = sim_value or ''
                            logger.info(
                                f"[RE-EVAL] '!=' Pattern: orig={repr(value)}, pattern={repr(pattern)}, cleaned_pattern={repr(cleaned_pattern)}, sim_value={repr(sim_value)}, compare_target(no strip)={repr(compare_target)}"
                            )
                            compare_target_stripped = (
                                compare_target.strip() if isinstance(compare_target, str) else compare_target
                            )
                            logger.info(
                                f'[RE-EVAL] Regex call (inverted): re.fullmatch({repr(cleaned_pattern)}, {repr(compare_target_stripped)})'
                            )
                            try:
                                match_result = re.fullmatch(cleaned_pattern, compare_target_stripped)
                                logger.info(
                                    f'[RE-EVAL] Regex match? {bool(match_result)} - Result object: {match_result}'
                                )
                                comparison_result = not bool(match_result)
                            except Exception as rgx_ex:
                                logger.warning(f'Regex error: {rgx_ex} pattern={cleaned_pattern!r}')
                                comparison_result = False
                            log_entry['type'] = f'Regex (not) match: /{cleaned_pattern}/'
                        else:
                            logger.info(
                                f"[RE-EVAL] '!=' String compare: sim_value={repr(sim_value)}, value={repr(value)}"
                            )
                            if isinstance(sim_value, str) and isinstance(value, str):
                                comparison_result = sim_value.strip() != value.strip()
                            else:
                                comparison_result = sim_value != value
                    elif operator == 'in':
                        if isinstance(value, list):
                            comparison_result = sim_value in value
                        else:
                            comparison_result = sim_value == value
                    elif operator == 'after' or operator == 'before':
                        # Only parse dates if value is a string
                        if isinstance(value, str) and sim_value:
                            try:
                                sim_dt = datetime.strptime(sim_value, '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                                exp_dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                                comparison_result = sim_dt > exp_dt if operator == 'after' else sim_dt < exp_dt
                            except Exception:
                                log_entry['type'] = 'Time parsing failed (Non-ISO format or missing TZ).'
                                comparison_result = False
                        else:
                            comparison_result = False
                    elif operator == 'between':
                        try:

                            def safe_strip(val):
                                return val.strip("'") if isinstance(val, str) else ''

                            if all(isinstance(x, str) and x for x in [sim_value, value, value_2]):
                                sim_time = datetime.strptime(safe_strip(sim_value), '%H:%M:%S%z').time()
                                start_time = datetime.strptime(safe_strip(value), '%H:%M:%S%z').time()
                                end_time = datetime.strptime(safe_strip(value_2), '%H:%M:%S%z').time()
                                if start_time <= end_time:
                                    comparison_result = (sim_time >= start_time) and (sim_time <= end_time)
                                else:
                                    comparison_result = (sim_time >= start_time) or (sim_time <= end_time)
                            else:
                                comparison_result = False
                        except Exception:
                            log_entry['type'] = 'Time-of-day parsing failed.'
                            comparison_result = False
                    else:
                        log_entry['type'] = f"Operator '{operator}' not simulated."
                        comparison_result = False
                except Exception as eval_ex:
                    log_entry['type'] = f'Evaluation error: {eval_ex}'
                    comparison_result = False
                log_entry['result'] = comparison_result
                self.comparison_log.append(log_entry)
                return comparison_result

            def visitCondition_clause(self, ctx):
                return self.visit(ctx.condition_expression())

            def visitCondition_expression(self, ctx):
                if ctx.single_condition():
                    return self.visit(ctx.single_condition())
                elif ctx.all_or_any():
                    is_all = ctx.all_or_any().getText().lower() == 'all'
                    passes = self.visit(ctx.condition_list())
                    if is_all:
                        return all(passes)
                    else:
                        return any(passes)

            def visitCondition_list(self, ctx):
                return [self.visit(c) for c in ctx.condition_expression()]

        # Actual visit and return
        visitor = ConditionExecutionVisitor(variables)
        condition_passed = visitor.visit(tree)
        logger.info(f'Evaluation result: {condition_passed}')
        result = {'Condition String': condition_str, 'Log': visitor.comparison_log}
        if condition_passed is True:
            result['Policy Result'] = 'GRANTED'
        else:
            result['Policy Result'] = 'DENIED'
        return result

    def _show_result(self, result_dict):
        self.results_text.delete('1.0', tk.END)
        # Basic outcome
        self.results_text.insert(tk.END, f"Condition: {result_dict.get('Condition String')}\n")
        self.results_text.insert(tk.END, f"Access Result: {result_dict.get('Policy Result')}\n")
        # Details/log
        self.results_text.insert(tk.END, '--- Comparison Log ---\n')
        log = result_dict.get('Log', [])
        if log:
            for entry in log:
                sim_val = entry['sim_value']
                result = entry['result']
                operator = entry['operator']
                expected = entry['expected']
                var = entry['variable']
                if sim_val == 'MISSING':
                    self.results_text.insert(tk.END, f"  [FAIL] Variable '{var}' is MISSING.\n")
                else:
                    self.results_text.insert(
                        tk.END, f"  [{'PASS' if result else 'FAIL'}] {sim_val} {operator} {expected} -> {result}\n"
                    )
        else:
            self.results_text.insert(tk.END, '  No comparisons made / syntax or execution error.\n')
