"""Legacy compatibility shim for policy helper utilities.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.common.policy_helpers`.
"""

from oci_policy_analysis.application.core.common.policy_helpers import (
    calculate_principal_key,
    resolve_effective_path,
)

__all__ = ['calculate_principal_key', 'resolve_effective_path']
