"""Legacy compatibility shim for ConsolidationEngine.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.engine.consolidation_engine`.
"""

from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine

__all__ = ['ConsolidationEngine']
