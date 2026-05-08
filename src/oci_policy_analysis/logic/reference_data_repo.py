"""Legacy compatibility shim for ReferenceDataRepo.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.repo.reference_data_repo`.
"""

from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo

__all__ = ['ReferenceDataRepo']
