"""Legacy compatibility shim for prospective statements service.

TODO(refactor-phase-5): Remove after all imports migrate to
`oci_policy_analysis.application.services.prospective_statements_service`.
"""

from oci_policy_analysis.application.services.prospective_statements_service import (  # noqa: F401
    SETTINGS_KEY_PROSPECTIVE_BY_TENANCY,
    ProspectiveStatementRecord,
    ProspectiveStatementsService,
)

__all__ = [
    'SETTINGS_KEY_PROSPECTIVE_BY_TENANCY',
    'ProspectiveStatementRecord',
    'ProspectiveStatementsService',
]
