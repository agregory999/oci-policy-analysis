"""Legacy compatibility shim for PolicySimulationEngine.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.engine.policy_simulation_engine`.
"""

from oci_policy_analysis.application.core.engine.policy_simulation_engine import PolicySimulationEngine

__all__ = ['PolicySimulationEngine']
