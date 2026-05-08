"""Application-core facade for where-clause evaluation logic."""

from oci_policy_analysis.application.core.parser.condition_parser.WhereClauseEvaluator import (  # noqa: F401
    evaluate_where_clause,
)

__all__ = ['evaluate_where_clause']
