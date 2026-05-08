"""Core parser facade for tag-condition collection helpers.

This keeps service/engine imports on ``application.core.parser`` while the
ANTLR-tree traversal implementation remains in the legacy logic parser package.
"""

from oci_policy_analysis.logic.parsers.condition_parser.TagConditionCollector import (
    TagCondition,
    collect_tag_conditions,
)

__all__ = ['TagCondition', 'collect_tag_conditions']
