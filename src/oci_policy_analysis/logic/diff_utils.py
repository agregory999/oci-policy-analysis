"""Legacy compatibility shim for diff utility helpers.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.common.diff_utils`.
"""

from oci_policy_analysis.application.core.common.diff_utils import canonical_filter

__all__ = ['canonical_filter']
