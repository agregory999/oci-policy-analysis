"""Reusable condition-clause utilities for Tk, web, and simulation consumers.

This module centralizes condition formatting, variable extraction, and
condition evaluation so Tk, web, and simulation flows all reuse the same
core behavior.
"""

from __future__ import annotations

from typing import Any, cast

from antlr4 import CommonTokenStream, InputStream

from oci_policy_analysis.application.core.parser.generated.condition_parser import (
    OciIamPolicyConditionLexer,
    OciIamPolicyConditionParser,
    OciIamPolicyConditionVisitor,
)
from oci_policy_analysis.application.core.parser.generated.condition_parser.where_clause_evaluator import (
    evaluate_where_clause,
)
from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='condition_evaluator')


def _normalize_clause_spacing(raw_clause: str) -> str:
    """Normalize non-semantic whitespace before clause formatting.

    Collapses repeated whitespace outside quoted/pattern literals while keeping
    single spaces where useful for readability.
    """
    txt = str(raw_clause or '').strip()
    if not txt:
        return ''

    out: list[str] = []
    in_quote: str | bool = False
    pending_space = False

    for ch in txt:
        if in_quote:
            out.append(ch)
            if ch == in_quote:
                in_quote = False
            continue

        if ch in ("'", '"', '/'):
            if pending_space and out and out[-1] not in ('{', '(', ','):
                out.append(' ')
            pending_space = False
            in_quote = ch
            out.append(ch)
            continue

        if ch.isspace():
            pending_space = True
            continue

        if ch in '{},()':
            pending_space = False
            if ch == ',' and out and out[-1] == ' ':
                out.pop()
            out.append(ch)
            continue

        if ch in '=!<>':
            pending_space = False
            if out and out[-1] == ' ':
                out.pop()
            out.append(ch)
            continue

        if pending_space and out and out[-1] not in ('{', '(', ',', '='):
            out.append(' ')
        pending_space = False
        out.append(ch)

    return ''.join(out).strip()


def format_policy_clause(raw_clause: str) -> str:
    """Format a where-clause for readability while preserving syntax tokens.

    Args:
        raw_clause: Raw clause text entered by a user.

    Returns:
        Formatted clause string with indentation and line breaks for block and
        list readability.
    """
    txt = _normalize_clause_spacing(raw_clause)
    if not txt:
        return ''
    out: list[str] = []
    indent = 0
    in_quote = False
    i = 0
    while i < len(txt):
        c = txt[i]
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
    formatted = ''.join(out).strip()
    # Keep formatter idempotent by collapsing repeated blank lines that can
    # appear when formatting already-formatted multi-line clauses.
    lines = [line.rstrip() for line in formatted.splitlines()]
    collapsed: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line.strip() == ''
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return '\n'.join(collapsed).strip()


def extract_variable_names(cond_str: str) -> set[str]:
    """Extract dotted identifier variable names from a condition clause.

    Args:
        cond_str: Condition clause text to parse.

    Returns:
        Set of discovered variable names, including dotted identifiers found in
        variable-name nodes and identifier terminals.
    """
    text = str(cond_str or '').strip()
    if not text:
        return set()
    input_stream = InputStream(text + '\n')
    lexer = OciIamPolicyConditionLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = OciIamPolicyConditionParser(stream)
    tree = parser.condition_clause()

    class VarCollector(OciIamPolicyConditionVisitor):
        """ANTLR visitor that accumulates variable names from a parse tree."""

        def __init__(self):
            """Initialize collector state."""
            self.vars: set[str] = set()

        def visitVariable_name(self, ctx):
            """Collect a parsed variable_name node.

            Args:
                ctx: ANTLR parser context for a variable_name node.

            Returns:
                None.
            """
            self.vars.add(ctx.getText())

        def visitTerminal(self, node):
            """Collect dotted identifiers seen as terminal nodes.

            Args:
                node: ANTLR terminal node.

            Returns:
                None.
            """
            symbol = getattr(node, 'symbol', None)
            token_type = getattr(symbol, 'type', None)
            node_text = cast(str, getattr(node, 'getText', lambda: '')())
            if token_type == OciIamPolicyConditionLexer.IDENTIFIER and '.' in node_text:
                self.vars.add(node_text)
            return None

    collector = VarCollector()
    collector.visit(tree)
    return collector.vars


def _normalize_timestring(value: str) -> str:
    import re

    iso_dt_pattern = r'^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.\d+)?([Zz]|[+\-]\d{2}:?\d{2})?$'
    if isinstance(value, str):
        m = re.match(iso_dt_pattern, value)
        if m:
            date, time, tz = m.group(1), m.group(2), m.group(3)
            new_v = f'{date}T{time}'
            if tz:
                new_v += tz.upper() if tz.lower() == 'z' else tz
            return new_v
    return value


def _normalize_where_context_times(where_context: dict[str, Any]) -> dict[str, Any]:
    norm: dict[str, Any] = {}
    for k, v in where_context.items():
        if isinstance(v, str):
            norm[k] = _normalize_timestring(v)
        elif isinstance(v, dict):
            norm[k] = _normalize_where_context_times(v)
        else:
            norm[k] = v
    return norm


def _normalize_where_context_nulls(where_context: dict[str, Any]) -> dict[str, Any]:
    """Represent blank UI inputs as explicit nulls, not empty string values.

    OCI's unary presence condition (``!request.variable``) distinguishes an
    absent variable from a supplied empty string. Desktop and web input fields
    naturally submit empty strings, so normalize them at the shared evaluator
    boundary used by the tester and simulation.
    """
    normalized: dict[str, Any] = {}
    for key, value in where_context.items():
        if value == '':
            normalized[key] = None
        elif isinstance(value, dict):
            normalized[key] = _normalize_where_context_nulls(value)
        else:
            normalized[key] = value
    return normalized


def evaluate_condition_clause(
    cond: object,
    where_context: dict[str, Any],
    *,
    return_structured: bool = False,
) -> tuple[bool, str] | tuple[bool, dict[str, Any]]:
    """Evaluate condition text against simulated variables.

    Keeps backward compatibility with existing tuple return shape while
    optionally returning structured payload for UI consumers.

    Args:
        cond: Condition input, typically a clause string or dict containing
            clause text.
        where_context: Simulated variable map used for evaluation.
        return_structured: When True, returns a structured dict payload;
            otherwise returns a legacy reason string.

    Returns:
        Tuple where the first value is pass/fail and the second value is either
        a reason string or a structured result dict.
    """
    where_context = _normalize_where_context_nulls(_normalize_where_context_times(where_context or {}))
    if isinstance(cond, dict):
        condition_str = None
        for k in ('where_clause', 'condition_string', 'clause', 'string'):
            if k in cond:
                condition_str = cond[k]
                break
        if not condition_str:
            for v in cond.values():
                if isinstance(v, str):
                    condition_str = v
                    break
        if not condition_str:
            condition_str = str(cond)
    elif isinstance(cond, str):
        condition_str = cond
    else:
        condition_str = str(cond)

    try:
        result_bool, log = evaluate_where_clause(condition_str, where_context)
        result_bool = bool(result_bool)
    except Exception as ex:
        logger.error('Exception during condition evaluation: %s', ex)
        result_bool = False
        log = [
            {
                'type': 'Exception',
                'result': False,
                'variable': '?',
                'operator': '?',
                'sim_value': '?',
                'expected': '?',
                'info': str(ex),
            }
        ]

    if return_structured:
        status = 'GRANTED' if result_bool else 'DENIED'
        return result_bool, {
            'Condition String': condition_str,
            'Policy Result': status,
            'Log': log if isinstance(log, list) else [{'type': 'Summary', 'info': str(log), 'result': result_bool}],
        }

    reason_lines: list[str] = []
    if log:
        if isinstance(log, str):
            reason_lines.append(log)
        elif isinstance(log, list):
            for entry in log:
                if isinstance(entry, dict):
                    msg = entry.get('info') or entry.get('result') or str(entry)
                    reason_lines.append(str(msg))
                else:
                    reason_lines.append(str(entry))
    reason = '; '.join([line for line in reason_lines if line])
    status = 'GRANTED' if result_bool else 'DENIED'
    if not reason:
        reason = f'Policy Result: {status}'
    else:
        reason = f'Policy Result: {status}. Details: {reason}'
    return result_bool, reason
