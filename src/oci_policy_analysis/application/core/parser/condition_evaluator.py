"""Core parser facade for condition-clause evaluation utilities.

This module intentionally re-exports condition evaluation helpers from the
legacy logic implementation so callers can depend on a stable
``application.core.parser`` path while parser internals are reorganized.
"""

from oci_policy_analysis.logic.condition_evaluator import (
    evaluate_condition_clause,
    extract_variable_names,
    format_policy_clause,
)

__all__ = [
    'evaluate_condition_clause',
    'extract_variable_names',
    'format_policy_clause',
]
