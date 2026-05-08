"""Compatibility shim for PolicyStatementNormalizer.

The implementation moved to
`oci_policy_analysis.application.core.parser.policy_statement_normalizer`.
Keep this shim during the modular refactor for backward compatibility.
"""

from oci_policy_analysis.application.core.parser.policy_statement_normalizer import (
    PolicyStatementNormalizer,
    PolicyStatementParser,
)

__all__ = ['PolicyStatementNormalizer', 'PolicyStatementParser']
