"""Compatibility shim for parse_policy_subjects.

The implementation moved to
`oci_policy_analysis.application.core.parser.policy_subject_parser`.
Keep this shim during the modular refactor for backward compatibility.
"""

from oci_policy_analysis.application.core.parser.policy_subject_parser import parse_policy_subjects

__all__ = ['parse_policy_subjects']
