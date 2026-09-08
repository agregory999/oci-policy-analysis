"""One-level-down consolidation strategy."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    normalize_compartment_path_segments,
    resolve_policy_compartment_path,
)
from oci_policy_analysis.application.core.engine.strategies.move_closer_to_target import (
    MoveCloserToTargetCompartment,
)
from oci_policy_analysis.application.core.models.models import BasePolicy


@dataclass(frozen=True)
class MoveDownNextLevel(MoveCloserToTargetCompartment):
    """Move a policy exactly one hierarchy level toward its selected statements.

    All selected statements for a source policy must share a child compartment
    below that policy.  The inherited planner rewrites location clauses
    relative to that child so the effective scope is retained.  Statements
    effective at tenancy root cannot move down and are skipped.
    """

    strategy_id: str = 'move_down_next_level'
    display_name: str = 'Move Down Next Level'

    def _target_policy_path(
        self,
        *,
        lca: list[str],
        source_policy: BasePolicy,
        compartments: list[dict],
    ) -> str:
        """Return the common immediate child below the source policy."""
        source_path = resolve_policy_compartment_path(source_policy, compartments) or 'ROOT'
        source_segments = normalize_compartment_path_segments(source_path)
        normalized_lca = [segment.casefold() for segment in lca]
        normalized_source = [segment.casefold() for segment in source_segments]
        if (
            not source_segments
            or normalized_lca[: len(normalized_source)] != normalized_source
            or len(lca) <= len(source_segments)
        ):
            return ''
        return '/'.join(lca[: len(source_segments) + 1])
