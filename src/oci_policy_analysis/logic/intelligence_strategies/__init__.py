"""Legacy compatibility shim package for intelligence strategies.

TODO(refactor-phase-5): remove after all imports migrate to
`oci_policy_analysis.application.core.engine.intelligence_strategies`.
"""

from oci_policy_analysis.application.core.engine.intelligence_strategies import (
    IntelligenceStrategy,
    get_default_intelligence_strategies,
)

__all__ = [
    'IntelligenceStrategy',
    'get_default_intelligence_strategies',
]
