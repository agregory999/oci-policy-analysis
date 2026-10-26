"""Legacy UI compatibility shim for builder helper functions.

Canonical implementation lives in
``oci_policy_analysis.application.core.common.builder_helpers``.
"""

from oci_policy_analysis.application.core.common.builder_helpers import (  # noqa: F401
    build_full_statement,
    build_location_clause,
    build_subject_phrase,
    build_tag_variable_and_snippet,
)

__all__ = [
    'build_tag_variable_and_snippet',
    'build_subject_phrase',
    'build_location_clause',
    'build_full_statement',
]
