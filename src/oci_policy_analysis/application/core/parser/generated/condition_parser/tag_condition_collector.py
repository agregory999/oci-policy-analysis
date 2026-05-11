"""Application-core facade for tag-condition collection over condition-parser trees."""

from oci_policy_analysis.application.core.parser.condition_parser.TagConditionCollector import (  # noqa: F401
    TagCondition,
    collect_tag_conditions,
)

__all__ = ['TagCondition', 'collect_tag_conditions']
