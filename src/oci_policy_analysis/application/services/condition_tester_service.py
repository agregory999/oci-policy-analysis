"""Application service facade for condition tester workflows.

This service exposes a stable API for UI/API consumers while delegating core
parsing and evaluation behavior to ``oci_policy_analysis.application.core.parser``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from antlr4 import InputStream

from oci_policy_analysis.application.core.parser import (
    evaluate_condition_clause,
    extract_variable_names,
    format_policy_clause,
)
from oci_policy_analysis.application.core.parser.condition_structure import parse_condition_structure
from oci_policy_analysis.application.core.parser.policy_parser.PolicyLexer import PolicyLexer
from oci_policy_analysis.application.core.support.logger import get_logger


def extract_condition_clause(condition: str = '', statement_text: str = '') -> str:
    """Extract a tester expression from a clause or the original policy statement.

    Quoted names and string values containing ``where`` are handled by the
    policy lexer. A leading ``where`` keyword is omitted from standalone clauses.
    """
    clause = str(condition or '').strip()
    if clause and not re.match(r'(?i)^(allow|deny|admit|endorse|define)\b', clause):
        return re.sub(r'(?i)^where\b\s*', '', clause).strip()
    statement = clause or str(statement_text or '').strip()
    lexer = PolicyLexer(InputStream(statement))
    lexer.removeErrorListeners()
    for token in lexer.getAllTokens():
        if token.type == PolicyLexer.WHERE:
            return statement[token.stop + 1 :].strip()
    return ''


@dataclass
class ConditionEvaluationResult:
    """Structured result payload for condition evaluation responses.

    Attributes:
        condition_string: The evaluated condition clause.
        policy_result: ``GRANTED`` or ``DENIED``.
        log: Structured comparison/evaluation log entries.
        granted: Boolean result equivalent of ``policy_result``.
    """

    condition_string: str
    policy_result: str
    log: list[dict[str, Any]]
    granted: bool


class ConditionTesterService:
    """Service that provides format/extract/evaluate operations for conditions."""

    def __init__(self) -> None:
        """Initialize service state.

        Returns:
            None.
        """
        self.logger = get_logger(component='condition_tester_service')

    def format_clause(self, clause: str) -> str:
        """Format a condition clause for readability.

        Args:
            clause: Raw clause text.

        Returns:
            Beautified clause text.
        """
        return format_policy_clause(clause)

    def extract_variables(self, clause: str) -> list[str]:
        """Extract variable names from a condition clause.

        Args:
            clause: Condition clause text.

        Returns:
            Sorted list of discovered variable names.
        """
        return sorted(extract_variable_names(clause))

    def parse_clause(self, clause: str) -> dict[str, Any]:
        """Parse entered conditions or a full policy and discover both operand inputs.

        Args:
            clause: Condition expression, optional leading where, or full policy.

        Returns:
            dict[str, Any]: Extracted clause, display structure including syntax
            diagnostics, and sorted variable names. Invalid/absent expressions
            have no input fields and must not be treated as evaluated denials.
        """
        text = extract_condition_clause(clause)
        structure = parse_condition_structure(text)
        variables = self.extract_variables(text) if structure['parse_status'] == 'parsed' else []
        return {'clause': text, 'structure': structure, 'variables': variables}

    def evaluate(self, clause: str, variables: dict[str, Any]) -> ConditionEvaluationResult:
        """Evaluate a condition clause against simulated variables.

        Args:
            clause: Condition clause text.
            variables: Simulated variable map.

        Returns:
            Structured evaluation result payload.

        Notes:
            The returned ``policy_result`` is normalized to ``GRANTED``/``DENIED``
            even when lower-level parser output omits that field.
        """
        passed, structured = evaluate_condition_clause(clause, variables or {}, return_structured=True)
        payload = structured if isinstance(structured, dict) else {}
        policy_result = str(payload.get('Policy Result') or ('GRANTED' if passed else 'DENIED'))
        log_raw = payload.get('Log')
        log = cast(list[dict[str, Any]], log_raw) if isinstance(log_raw, list) else []
        return ConditionEvaluationResult(
            condition_string=str(payload.get('Condition String') or clause),
            policy_result=policy_result,
            log=log,
            granted=bool(passed),
        )
