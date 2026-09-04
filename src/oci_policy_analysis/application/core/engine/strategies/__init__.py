"""Application-core consolidation strategy package.

Defines the Strategy protocol and built-in strategy implementations used by
ConsolidationEngine. This package is the canonical import surface for strategy
registration/extension during modular refactor.
"""

from oci_policy_analysis.application.core.engine.strategies.base import (
    BaseConsolidationStrategy,
    PlacementResult,
    PlanningContext,
    StatementPlacement,
    Strategy,
    TargetPolicySpec,
)
from oci_policy_analysis.application.core.engine.strategies.group_similar_statements import GroupSimilarStatements
from oci_policy_analysis.application.core.engine.strategies.move_closer_to_target import MoveCloserToTargetCompartment
from oci_policy_analysis.application.core.engine.strategies.move_down_next_level import MoveDownNextLevel
from oci_policy_analysis.application.core.engine.strategies.move_into_target import MoveIntoTargetCompartment
from oci_policy_analysis.application.core.engine.strategies.move_to_root import MoveToRootCompartment
from oci_policy_analysis.application.core.engine.strategies.statement_density import PackPoliciesByStatementDensity

__all__ = [
    'Strategy',
    'BaseConsolidationStrategy',
    'PlanningContext',
    'TargetPolicySpec',
    'StatementPlacement',
    'PlacementResult',
    'MoveCloserToTargetCompartment',
    'MoveDownNextLevel',
    'MoveIntoTargetCompartment',
    'MoveToRootCompartment',
    'PackPoliciesByStatementDensity',
    'GroupSimilarStatements',
]
