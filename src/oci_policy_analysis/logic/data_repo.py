"""Compatibility shim for PolicyAnalysisRepository.

The implementation moved to
`oci_policy_analysis.application.core.repo.policy_analysis_repository`.
Keep this shim during the modular refactor for backward compatibility.
"""

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository

__all__ = ['PolicyAnalysisRepository']
