##########################################################################
# Copyright (c) 2025, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# WhereClauseEvaluator.py
#
# Standalone visitor for evaluating OCI "where" clause conditions, including logging.
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

import re
from datetime import datetime

from antlr4 import CommonTokenStream, InputStream
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionLexer import OciIamPolicyConditionLexer
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionParser import OciIamPolicyConditionParser
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionVisitor import OciIamPolicyConditionVisitor

logger = get_logger(component='where_clause_evaluator')


class WhereClauseEvaluator(OciIamPolicyConditionVisitor):
    """
    Visitor/evaluator for OCI where clause expressions ("all { ... }", "any { ... }", etc.).
    """

    def __init__(self, variables: dict):
        self.variables = variables
        self.comparison_log = []
        logger.info(f'WhereClauseEvaluator initialized with variables: {self.variables}')

    def visitCondition_clause(self, ctx):
        logger.info(f'Evaluating condition_clause: {ctx.getText()}')
        return self.visit(ctx.condition_expression())

    def visitCondition_expression(self, ctx):
        if ctx.single_condition():
            logger.debug('Visiting single_condition in condition_expression.')
            return self.visit(ctx.single_condition())
        elif ctx.all_or_any():
            keyword = ctx.all_or_any().getText().lower()
            logger.debug(f"Found 'all_or_any': {keyword}")
            results = self.visit(ctx.condition_list())
            if keyword == 'all':
                result = all(results)
            else:
                result = any(results)
            logger.info(f"all_or_any result for '{keyword}': {result} (results: {results})")
            return result

    def visitCondition_list(self, ctx):
        logger.debug('Visiting condition_list; evaluating each condition_expression.')
        results = [self.visit(c) for c in ctx.condition_expression()]
        logger.info(f'Results from condition_list: {results}')
        return results

    def visitSingle_condition(self, ctx):
        variable = ctx.variable_name().getText()
        operator = ctx.OPERATOR().getText().lower()
        value = None
        value_2 = None

        logger.info(f'Evaluating condition: variable={variable}, operator={operator}')

        # Utility for ISO time normalization (uppercases T/Z if pattern matches)
        def _normalize_timestring(val):
            if not isinstance(val, str):
                return val
            iso_dt_pattern = r'^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.\d+)?([Zz]|[+\-]\d{2}:?\d{2})?$'
            m = re.match(iso_dt_pattern, val)
            if m:
                date, time, tz = m.group(1), m.group(2), m.group(3)
                new_v = f'{date}T{time}'
                if tz:
                    new_v += tz.upper() if tz.lower() == 'z' else tz
                return new_v
            return val

        # Value extraction
        value_token_type = 'none'
        try:
            if ctx.literal_list():
                logger.info('Extracting literal_list.')
                list_content = ctx.literal_list().literal_list_content()

                # Strip both types of quotes and whitespace; allow patterns in the list (e.g. /.../)
                def normalize_literal(val):
                    v = val.strip()
                    if v.startswith("'") and v.endswith("'") and len(v) > 1:
                        v = v[1:-1]
                    if v.startswith('"') and v.endswith('"') and len(v) > 1:
                        v = v[1:-1]
                    return _normalize_timestring(v)

                logger.debug(
                    'literal_list_content children type/value: %s',
                    [(type(c).__name__, c.getText()) for c in list_content.getChildren()],
                )
                values = [normalize_literal(c.getText()) for c in list_content.getChildren()]
                value = [v for v in values if v not in [',']]
                logger.debug(f"Extracted IN list literals for variable '{variable}': {value}")
                logger.debug(f'IN LIST: variable={variable!r} value_list={value!r}')
                value_token_type = 'literal_list'
            elif ctx.condition_value():
                value_ctx = ctx.condition_value(0)
                value_raw = value_ctx.getText().strip()
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
                if is_pattern:
                    value = value_raw
                elif is_string:
                    value = _normalize_timestring(value_raw[1:-1])
                else:
                    if value_token_type == 'IDENTIFIER' and value_raw in self.variables:
                        logger.info(f"RHS IDENTIFIER '{value_raw}' replaced with value '{self.variables[value_raw]}'")
                        value = self.variables[value_raw]
                    else:
                        value = _normalize_timestring(value_raw)
        except Exception as ex:
            logger.error(f'Error extracting value(s) for {variable}: {ex}')
            value = None

        if operator == 'between' and ctx.condition_value(1):
            value_2_ctx = ctx.condition_value(1)
            value_2 = value_2_ctx.getText().strip()
            if value_2_ctx.STRING_LITERAL() or value_2_ctx.PATTERN_LITERAL():
                value_2 = _normalize_timestring(value_2[1:-1])

        sim_value = self.variables.get(variable)
        log_entry = {
            'variable': variable,
            'operator': operator,
            'sim_value': sim_value if sim_value is not None else 'MISSING',
            'expected': str(value) if value_2 is None else f'[{value} AND {value_2}]',
            'result': False,
            'type': 'Simple Comparison',
        }

        logger.info(f"Comparing: sim_value={sim_value}; expected={log_entry['expected']} (operator '{operator}').")
        if sim_value is None:
            logger.warning(f'Missing value for variable {variable}.')
            self.comparison_log.append(log_entry)
            return False

        comparison_result = False

        # Enforce variable/operator constraints
        if operator in ('before', 'after'):
            if variable != 'request.utc-timestamp':
                logger.warning(f"Operator '{operator}' is only valid with 'request.utc-timestamp' (got '{variable}')")
                log_entry['type'] = f"Invalid use of '{operator}' with {variable}"
                self.comparison_log.append(log_entry)
                return False
        if operator == 'between':
            if variable != 'request.utc-timestamp.time-of-day':
                logger.warning(
                    f"Operator 'between' is only valid with 'request.utc-timestamp.time-of-day' (got '{variable}')"
                )
                log_entry['type'] = f"Invalid use of 'between' with {variable}"
                self.comparison_log.append(log_entry)
                return False

        try:
            if operator == '=':
                if (
                    value_token_type == 'PATTERN_LITERAL'
                    and isinstance(value, str)
                    and value.startswith('/')
                    and value.endswith('/')
                ):
                    pattern = value[1:-1].strip('\'"')
                    cleaned_pattern = pattern.replace('*', '.*') if '*' in pattern and '.*' not in pattern else pattern
                    compare_target = sim_value or ''
                    logger.info(f'Regex match: pattern={cleaned_pattern}, target={compare_target}')
                    compare_target_stripped = (
                        compare_target.strip() if isinstance(compare_target, str) else compare_target
                    )
                    try:
                        match_result = re.fullmatch(cleaned_pattern, compare_target_stripped)
                        logger.info(f'Regex match result: {bool(match_result)}')
                        comparison_result = bool(match_result)
                    except Exception as rgx_ex:
                        logger.warning(f'Regex error: {rgx_ex} pattern={cleaned_pattern!r}')
                        comparison_result = False
                    log_entry['type'] = f'Regex match: /{cleaned_pattern}/'
                else:
                    logger.debug(f'String equality check: {sim_value} == {value}')
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
                    pattern = value[1:-1].strip('\'"')
                    cleaned_pattern = pattern.replace('*', '.*') if '*' in pattern and '.*' not in pattern else pattern
                    compare_target = sim_value or ''
                    logger.info(f'Regex (not) match: pattern={cleaned_pattern}, target={compare_target}')
                    compare_target_stripped = (
                        compare_target.strip() if isinstance(compare_target, str) else compare_target
                    )
                    try:
                        match_result = re.fullmatch(cleaned_pattern, compare_target_stripped)
                        logger.info(f'Regex (not) match result: {not bool(match_result)}')
                        comparison_result = not bool(match_result)
                    except Exception as rgx_ex:
                        logger.warning(f'Regex error: {rgx_ex} pattern={cleaned_pattern!r}')
                        comparison_result = False
                    log_entry['type'] = f'Regex (not) match: /{cleaned_pattern}/'
                else:
                    logger.debug(f'String inequality check: {sim_value} != {value}')
                    if isinstance(sim_value, str) and isinstance(value, str):
                        comparison_result = sim_value.strip() != value.strip()
                    else:
                        comparison_result = sim_value != value
            elif operator == 'in':
                logger.info(
                    f"'in' operator debug: variable={variable!r}, sim_value={sim_value!r}, value_list={value!r}"
                )
                logger.debug(f"'in' list string-equality check: {sim_value} in {value}")
                # Now support case-insensitive string equality - always log all fields for PASS/FAIL
                if isinstance(value, list):
                    candidate = sim_value or ''
                    cand_str = str(candidate).strip()
                    match_found = False
                    for v in value:
                        norm_v = v.strip().strip('"').strip("'") if v is not None else ''
                        logger.debug(f"Comparing candidate '{cand_str}' to list item '{norm_v}'")
                        if cand_str.lower() == norm_v.lower():
                            logger.info(
                                f"IN MATCH: candidate '{cand_str}' (case-insensitive) matched list item '{norm_v}'"
                            )
                            comparison_result = True
                            log_entry['sim_value'] = cand_str
                            log_entry['expected'] = str(value)
                            log_entry['operator'] = operator
                            log_entry['type'] = "List case-insensitive 'in'"
                            log_entry['result'] = True
                            self.comparison_log.append(log_entry.copy())
                            match_found = True
                            break
                    if not match_found:
                        logger.warning(
                            f"IN NO MATCH: candidate '{cand_str}' did not match any (case-insensitive) in {value!r}"
                        )
                        comparison_result = False
                        log_entry['sim_value'] = cand_str
                        log_entry['expected'] = str(value)
                        log_entry['operator'] = operator
                        log_entry['type'] = "List case-insensitive 'in'"
                        log_entry['result'] = False
                        self.comparison_log.append(log_entry.copy())
                else:
                    # Scalar comparison for degenerate non-list case
                    norm_v = (
                        value.strip().strip('"').strip("'")
                        if isinstance(value, str)
                        else (value if value is not None else '')
                    )
                    candidate = sim_value or ''
                    cand_str = str(candidate).strip()
                    result = cand_str.lower() == norm_v.lower()
                    if result:
                        logger.info(f"IN MATCH: candidate '{cand_str}' == '{norm_v}' (scalar, case-insensitive)")
                        log_entry['sim_value'] = cand_str
                        log_entry['expected'] = str(norm_v)
                        log_entry['operator'] = operator
                        log_entry['type'] = "Scalar case-insensitive 'in'"
                        log_entry['result'] = True
                        self.comparison_log.append(log_entry.copy())
                    else:
                        logger.warning(f"IN NO MATCH: candidate '{cand_str}' != '{norm_v}' (scalar, case-insensitive)")
                        log_entry['sim_value'] = cand_str
                        log_entry['expected'] = str(norm_v)
                        log_entry['operator'] = operator
                        log_entry['type'] = "Scalar case-insensitive 'in'"
                        log_entry['result'] = False
                        self.comparison_log.append(log_entry.copy())
                    comparison_result = result
            elif operator == 'after' or operator == 'before':
                if isinstance(value, str) and sim_value:
                    try:
                        sim_dt = datetime.strptime(sim_value, '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                        exp_dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                        logger.info(f'Datetime {sim_dt} vs {exp_dt} ({operator})')
                        comparison_result = sim_dt > exp_dt if operator == 'after' else sim_dt < exp_dt
                    except Exception as dt_ex:
                        logger.warning(f'Time parsing failed: {dt_ex}')
                        log_entry['type'] = 'Time parsing failed (Non-ISO format or missing TZ).'
                        comparison_result = False
                else:
                    comparison_result = False
            elif operator == 'between':
                try:
                    from datetime import datetime as _dt

                    def safe_strip(val):
                        return val.strip("'") if isinstance(val, str) else ''

                    def parse_time_z(tstr):
                        # Accept both 'Z' and 'z' as UTC (as per user feedback)
                        ts = safe_strip(tstr)
                        if ts.endswith('z'):
                            ts = ts[:-1] + 'Z'
                        return _dt.strptime(ts, '%H:%M:%S%z').time()

                    if all(isinstance(x, str) and x for x in [sim_value, value, value_2]):
                        sim_time = parse_time_z(sim_value)
                        start_time = parse_time_z(value)
                        end_time = parse_time_z(value_2)
                        logger.info(f'Checking if {sim_time} between {start_time} and {end_time}')
                        if start_time <= end_time:
                            comparison_result = (sim_time >= start_time) and (sim_time <= end_time)
                        else:
                            comparison_result = (sim_time >= start_time) or (sim_time <= end_time)
                    else:
                        comparison_result = False
                except Exception as t_ex:
                    logger.warning(f'Time-of-day parsing failed: {t_ex}')
                    log_entry['type'] = 'Time-of-day parsing failed.'
                    comparison_result = False
            else:
                log_entry['type'] = f"Operator '{operator}' not simulated."
                logger.warning(f"Operator '{operator}' not simulated for {variable}.")
                comparison_result = False
        except Exception as eval_ex:
            log_entry['type'] = f'Evaluation error: {eval_ex}'
            logger.error(f'Exception during comparison: {eval_ex}')
            comparison_result = False

        # Only append in non-in cases (in cases above added inside clause)
        if operator != 'in':
            log_entry['result'] = comparison_result
            self.comparison_log.append(log_entry)
        logger.info(f'Condition result: {comparison_result} (variable: {variable})')
        return comparison_result


def evaluate_where_clause(condition_str: str, variables: dict):
    """
    Top-level helper to parse and evaluate a where clause string, returning (bool, log).
    """
    logger.info(f'evaluate_where_clause called: {condition_str} | variables={variables}')
    input_stream = InputStream(condition_str + '\n')
    lexer = OciIamPolicyConditionLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = OciIamPolicyConditionParser(stream)
    tree = parser.condition_clause()
    evaluator = WhereClauseEvaluator(variables)
    try:
        result = evaluator.visit(tree)
    except Exception as ex:
        logger.error(f'Exception during where clause evaluation: {ex}')
        result = False
    logger.info(f'Where clause evaluation finished: {result}')
    return result, evaluator.comparison_log
