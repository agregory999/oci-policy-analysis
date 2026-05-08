"""Core parser facade for policy statement normalization.

Keeps external imports on ``application.core.parser`` while the underlying
ANTLR-backed normalizer remains in the logic layer during migration.
"""

from oci_policy_analysis.logic.policy_statement_normalizer import PolicyStatementNormalizer

__all__ = ['PolicyStatementNormalizer']
