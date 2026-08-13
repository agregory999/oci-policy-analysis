"""Application-core intelligence strategy package.

Defines the intelligence strategy protocol and default strategy registry used
by PolicyIntelligenceEngine.
"""

from oci_policy_analysis.application.core.engine.intelligence_strategies.base import IntelligenceStrategy
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_anyuser_no_where import (
    AnyuserNoWhereCheck,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_invalid import InvalidStatementsCheck
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_statements_too_open import (
    StatementsTooOpenCheck,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_unused_dynamic_groups import (
    UnusedDynamicGroupsCheck,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_unused_groups import (
    UnusedGroupsCheck,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.consolidation_suggestion import (
    ConsolidationSuggestionStrategy,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.recommendations import (
    OverallRecommendationStrategy,
)
from oci_policy_analysis.application.core.engine.intelligence_strategies.risk import RiskScoreStrategy
from oci_policy_analysis.application.core.engine.intelligence_strategies.supersession import SupersessionStrategy


def get_default_intelligence_strategies():
    """Return the default ordered set of policy intelligence strategies."""
    return [
        RiskScoreStrategy(),
        SupersessionStrategy(),
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
    'SupersessionStrategy',
    'get_default_intelligence_strategies',
]
