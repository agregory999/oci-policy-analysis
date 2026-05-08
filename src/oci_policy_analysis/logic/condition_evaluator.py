"""Compatibility shim for condition evaluation helpers.

The implementation moved to
`oci_policy_analysis.application.core.parser.condition_evaluator`.
Keep this shim during the modular refactor for backward compatibility.
"""

from oci_policy_analysis.application.core.parser.condition_evaluator import (
    evaluate_condition_clause,
    extract_variable_names,
    format_policy_clause,
)

__all__ = [
    'evaluate_condition_clause',
    'extract_variable_names',
    'format_policy_clause',
]
