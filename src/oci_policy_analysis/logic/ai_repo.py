"""Compatibility shim for AI repo helper.

The implementation moved to
`oci_policy_analysis.application.core.repo.ai_repo`.
Keep this shim during the modular refactor for backward compatibility.
"""

from oci_policy_analysis.application.core.repo.ai_repo import AI

__all__ = ['AI']
