"""Legacy compatibility shim for PolicyIntelligenceEngine.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.engine.policy_intelligence_engine`.
"""

from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine

__all__ = ['PolicyIntelligenceEngine']
