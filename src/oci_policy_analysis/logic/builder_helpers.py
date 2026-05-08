"""Legacy compatibility shim for builder helper utilities.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.common.builder_helpers`.
"""

from oci_policy_analysis.application.core.common.builder_helpers import (
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
