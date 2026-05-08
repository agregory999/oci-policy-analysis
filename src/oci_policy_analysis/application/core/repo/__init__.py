"""Repository-layer exports for application core.

These aliases provide stable import paths while legacy logic modules are
incrementally migrated.
"""

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.logic.ai_repo import AI

__all__ = [
    'AI',
    'PolicyAnalysisRepository',
    'ReferenceDataRepo',
]
