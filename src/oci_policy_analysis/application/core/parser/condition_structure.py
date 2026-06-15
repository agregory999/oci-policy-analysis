"""Display-oriented condition structure extraction."""

from __future__ import annotations

from typing import Any

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionLexer import (
    OciIamPolicyConditionLexer,
)
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionParser import (
    OciIamPolicyConditionParser,
)
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionVisitor import (
    OciIamPolicyConditionVisitor,
)
from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='condition_structure')


class _CapturingErrorListener(ErrorListener):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[dict[str, Any]] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802, ANN001
        self.errors.append(
            {
                'line': line,
                'column': column,
                'message': str(msg),
                'symbol': str(offendingSymbol),
            }
        )


class _ConditionStructureVisitor(OciIamPolicyConditionVisitor):
    """Collect a shallow logical structure and flat condition atoms."""

    def __init__(self) -> None:
        super().__init__()
        self._next_id = 1
        self.atoms: list[dict[str, Any]] = []
        self.structure = ''

    def visitCondition_clause(self, ctx):  # noqa: D401, ANN001
        self.structure = self._visit_condition_expression(ctx.condition_expression())
        return None

    def _visit_condition_expression(self, ctx) -> str:  # noqa: ANN001
        if ctx.single_condition():
            return self._visit_single_condition(ctx.single_condition())
        if ctx.all_or_any():
            keyword = ctx.all_or_any().getText().upper()
            children = [
                self._visit_condition_expression(child) for child in ctx.condition_list().condition_expression()
            ]
            joined = ', '.join(child for child in children if child)
            return f'{keyword} {{ {joined} }}' if joined else f'{keyword} {{}}'
        return ctx.getText()

    def _visit_single_condition(self, ctx) -> str:  # noqa: ANN001
        condition_id = f'c{self._next_id}'
        self._next_id += 1

        left = ''
        variable_ctx = ctx.variable_name()
        if variable_ctx is not None:
            left = variable_ctx.getText()

        not_in_token = getattr(ctx, 'NOT_IN', lambda: None)()
        if not_in_token is not None:
            operator = 'not in'
        else:
            op_token = ctx.OPERATOR()
            operator = op_token.getText().lower() if op_token is not None else ''

        right, value_type = self._extract_right(ctx)
        subexpression = ctx.getText()
        evidence_kind = _classify_evidence(left, right)
        self.atoms.append(
            {
                'id': condition_id,
                'left': left,
                'operator': operator,
                'right': right,
                'normalized_left': left.casefold(),
                'value_type': value_type,
                'evidence_kind': evidence_kind,
                'subexpression': subexpression,
            }
        )
        return condition_id

    def _extract_right(self, ctx) -> tuple[str, str]:  # noqa: ANN001
        if ctx.literal_list():
            try:
                content = ctx.literal_list().literal_list_content()
                values = []
                for child in list(content.getChildren()):
                    text = getattr(child, 'getText', lambda child=child: str(child))()
                    if text == ',':
                        continue
                    values.append(_strip_quotes(text))
                return ', '.join(values), 'list'
            except Exception as exc:  # pragma: no cover - defensive only
                logger.debug('Failed to parse literal list from condition atom: %s', exc)

        try:
            if ctx.condition_value():
                value = ctx.condition_value(0).getText().strip()
                return _strip_quotes(value), _classify_value_type(value)
        except Exception as exc:  # pragma: no cover - defensive only
            logger.debug('Failed to parse condition value: %s', exc)
        return '', 'unknown'


def parse_condition_structure(text: str | None) -> dict[str, Any]:
    """Parse a where clause or dynamic group rule into display metadata."""
    raw_text = str(text or '').strip()
    if not raw_text:
        return {
            'raw_text': '',
            'parse_status': 'absent',
            'structure': '',
            'atoms': [],
            'residual_text': '',
            'warnings': [],
        }

    try:
        input_stream = InputStream(raw_text + '\n')
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = OciIamPolicyConditionParser(stream)
        errors = _CapturingErrorListener()
        parser.removeErrorListeners()
        parser.addErrorListener(errors)
        tree = parser.condition_clause()
        if parser.getNumberOfSyntaxErrors() > 0:
            return {
                'raw_text': raw_text,
                'parse_status': 'unsupported',
                'structure': '',
                'atoms': [],
                'residual_text': raw_text,
                'warnings': [err.get('message', 'syntax error') for err in errors.errors],
            }

        visitor = _ConditionStructureVisitor()
        visitor.visit(tree)
        return {
            'raw_text': raw_text,
            'parse_status': 'parsed',
            'structure': visitor.structure,
            'atoms': visitor.atoms,
            'residual_text': '',
            'warnings': [],
        }
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug('parse_condition_structure failed for %r: %s', raw_text, exc, exc_info=True)
        return {
            'raw_text': raw_text,
            'parse_status': 'unsupported',
            'structure': '',
            'atoms': [],
            'residual_text': raw_text,
            'warnings': [str(exc)],
        }


def format_condition_structure_summary(structure: dict[str, Any] | None) -> str:
    """Return compact display text for a parsed structure."""
    if not isinstance(structure, dict):
        return ''
    status = str(structure.get('parse_status') or '')
    if status == 'absent':
        return ''
    label = str(structure.get('structure') or '').strip()
    atom_count = len(structure.get('atoms') or []) if isinstance(structure.get('atoms'), list) else 0
    if label and atom_count:
        return f'{status}: {label} ({atom_count} atom{"s" if atom_count != 1 else ""})'
    if label:
        return f'{status}: {label}'
    return status


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
        return value[1:-1]
    return value


def _classify_value_type(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return 'empty'
    if stripped.startswith(("'", '"')) and stripped.endswith(("'", '"')):
        return 'string'
    if stripped.casefold() in {'true', 'false'}:
        return 'boolean'
    if stripped.replace('.', '', 1).isdigit():
        return 'number'
    if '.' in stripped:
        return 'variable'
    return 'literal'


def _classify_evidence(left: str, right: str) -> str:
    haystack = f'{left} {right}'.casefold()
    if '.tag.' in haystack:
        return 'tag'
    if left.casefold().startswith('request.principal.'):
        return 'resource_principal'
    if left.casefold().startswith('instance.'):
        return 'instance_principal'
    if left.casefold().startswith(('resource.', 'target.resource.')):
        return 'target_resource'
    return 'condition'
