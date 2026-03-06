##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# intelligence_strategies – Pluggable intelligence strategy protocol and registry.
#
# Implement IntelligenceStrategy (from .base) in your own module and register with
# PolicyIntelligenceEngine via register_strategy() or the strategies= constructor argument.
# The engine does not depend on concrete strategy implementations.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from oci_policy_analysis.logic.intelligence_strategies.base import IntelligenceStrategy
from oci_policy_analysis.logic.intelligence_strategies.cleanup_anyuser_no_where import AnyuserNoWhereCheck
from oci_policy_analysis.logic.intelligence_strategies.cleanup_invalid import InvalidStatementsCheck
from oci_policy_analysis.logic.intelligence_strategies.cleanup_statements_too_open import (
    StatementsTooOpenCheck,
)
from oci_policy_analysis.logic.intelligence_strategies.cleanup_unused_dynamic_groups import (
    UnusedDynamicGroupsCheck,
)
from oci_policy_analysis.logic.intelligence_strategies.cleanup_unused_groups import UnusedGroupsCheck
from oci_policy_analysis.logic.intelligence_strategies.consolidation_suggestion import (
    ConsolidationSuggestionStrategy,
)
from oci_policy_analysis.logic.intelligence_strategies.overlap import OverlapStrategy
from oci_policy_analysis.logic.intelligence_strategies.recommendations import OverallRecommendationStrategy
from oci_policy_analysis.logic.intelligence_strategies.risk import RiskScoreStrategy


def get_default_intelligence_strategies():
    """Return the default list of intelligence strategies (in run order)."""
    return [
        RiskScoreStrategy(),
        OverlapStrategy(),
        ConsolidationSuggestionStrategy(),
        InvalidStatementsCheck(),
        UnusedGroupsCheck(),
        UnusedDynamicGroupsCheck(),
        StatementsTooOpenCheck(),
        AnyuserNoWhereCheck(),
        OverallRecommendationStrategy(),
    ]


__all__ = [
    'IntelligenceStrategy',
    'get_default_intelligence_strategies',
]
