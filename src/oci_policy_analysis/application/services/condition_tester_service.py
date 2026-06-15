"""Application service facade for condition tester workflows.

This service exposes a stable API for UI/API consumers while delegating core
parsing and evaluation behavior to ``oci_policy_analysis.application.core.parser``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from oci_policy_analysis.application.core.parser import (
    evaluate_condition_clause,
    extract_variable_names,
    format_policy_clause,
)
from oci_policy_analysis.application.core.support.logger import get_logger


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
