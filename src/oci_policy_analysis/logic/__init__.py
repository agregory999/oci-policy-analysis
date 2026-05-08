"""Top level package for OCI Policy Analysis logic components.

This module intentionally avoids eager submodule imports to prevent circular
dependencies during the ongoing application-core migration.
"""

__all__ = [
    'PolicyAnalysisRepository',
    'ReferenceDataRepo',
    'AI',
    'PolicyIntelligenceEngine',
    'PolicyStatementNormalizer',
    'PolicySimulationEngine',
    # 'ConsolidationEngine',  # Removed to prevent circular import
]
