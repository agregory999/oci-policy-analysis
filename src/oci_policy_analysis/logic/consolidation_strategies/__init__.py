"""Legacy compatibility shim package for consolidation strategies.

TODO(refactor-phase-5): remove after all imports migrate to
`oci_policy_analysis.application.core.engine.strategies`.
"""

from oci_policy_analysis.application.core.engine.strategies import (
    MoveCloserToTargetCompartment,
    MoveIntoTargetCompartment,
    MoveToRootCompartment,
    PackPoliciesByStatementDensity,
    Strategy,
)

__all__ = [
    'Strategy',
    'MoveCloserToTargetCompartment',
    'MoveIntoTargetCompartment',
    'MoveToRootCompartment',
    'PackPoliciesByStatementDensity',
]
