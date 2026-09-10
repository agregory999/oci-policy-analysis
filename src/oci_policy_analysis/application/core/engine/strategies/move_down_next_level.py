"""One-level-down consolidation strategy."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    find_compartment_by_hierarchy_path,
    normalize_compartment_path_segments,
    resolve_policy_compartment_path,
)
from oci_policy_analysis.application.core.engine.strategies.base import (
    PlacementResult,
    StatementPlacement,
    TargetPolicySpec,
)
from oci_policy_analysis.application.core.engine.strategies.move_closer_to_target import (
    MoveCloserToTargetCompartment,
)
from oci_policy_analysis.application.core.models.models import BasePolicy
from oci_policy_analysis.application.core.models.models_consolidation import ConsolidationPlan, SkippedStatement
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class MoveDownNextLevel(MoveCloserToTargetCompartment):
    """Move a policy exactly one hierarchy level toward its selected statements.

    Each selected statement is evaluated independently. The policy moves one
    level below its source policy, toward that statement's effective path, so
    siblings with different targets do not block one another. Statements are
    skipped when they are tenancy-scoped or already have matching location and
    effective paths.
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

    @staticmethod
    def _statement_policy_path(statement: dict, source_policy: BasePolicy, compartments: list[dict]) -> list[str]:
        """Return the hierarchy path of the policy that contains the statement."""
        source_path = str(statement.get('compartment_path') or '').strip() or resolve_policy_compartment_path(
            source_policy, compartments
        )
        return normalize_compartment_path_segments(source_path)

    def build_plan(
        self,
        *,
        repo: PolicyAnalysisRepository,
        tenancy_ocid: str,
        dataset_version: str | None,
        candidate_internal_ids: set[str],
        protected_internal_ids: set[str],
        plan_id: str,
        params: dict[str, object] | None = None,
    ) -> ConsolidationPlan:
        """Move each eligible statement one level closer to its effective path."""
        context = self.planning_context(
            repo=repo, tenancy_ocid=tenancy_ocid, dataset_version=dataset_version, plan_id=plan_id, params=params
        )
        candidate_ids = self.effective_candidates(context, candidate_internal_ids, protected_internal_ids)
        if not candidate_ids:
            return self.empty_plan(
                context, reason='No effective candidates (all protected or not found in repository).'
            )

        placements: list[StatementPlacement] = []
        skipped: list[SkippedStatement] = []
        for internal_id in candidate_ids:
            statement = context.statements_by_id[internal_id]
            statement_text = str(statement.get('statement_text') or '')
            effective_segments = normalize_compartment_path_segments(
                str(statement.get('effective_path') or '').replace(':', '/')
            )
            if not effective_segments or (len(effective_segments) == 1 and effective_segments[0].casefold() == 'root'):
                skipped.append(
                    SkippedStatement(
                        internal_id=internal_id,
                        statement_text=statement_text,
                        reason='Statement effective path is tenancy/ROOT; it cannot move down the hierarchy.',
                    )
                )
                continue

            source_policy_ocid = str(statement.get('policy_ocid') or '')
            source_policy = context.policies_by_ocid.get(source_policy_ocid)
            if not source_policy:
                skipped.append(
                    SkippedStatement(
                        internal_id=internal_id,
                        statement_text=statement_text,
                        reason='Source policy was not found, so a safe move target could not be determined.',
                    )
                )
                continue

            policy_segments = self._statement_policy_path(statement, source_policy, context.compartments)
            if policy_segments and [segment.casefold() for segment in policy_segments] == [
                segment.casefold() for segment in effective_segments
            ]:
                skipped.append(
                    SkippedStatement(
                        internal_id=internal_id,
                        statement_text=statement_text,
                        reason='Statement location already matches its effective path; no move is needed.',
                    )
                )
                continue

            target_path = self._target_policy_path(
                lca=effective_segments,
                source_policy=source_policy,
                compartments=context.compartments,
            )
            target_compartment = (
                find_compartment_by_hierarchy_path(target_path, context.compartments) if target_path else None
            )
            target_ocid = (target_compartment or {}).get('compartment_ocid') or (target_compartment or {}).get('id')
            if not target_ocid:
                skipped.append(
                    SkippedStatement(
                        internal_id=internal_id,
                        statement_text=statement_text,
                        reason='No next-level compartment exists between the source policy and effective path.',
                    )
                )
                continue

            placements.append(
                StatementPlacement(
                    internal_id=internal_id,
                    source_policy_ocid=source_policy_ocid,
                    target=TargetPolicySpec(
                        compartment_ocid=str(target_ocid),
                        hierarchy_path=target_path,
                        policy_name=str(source_policy.get('policy_name') or f'Consolidated-{source_policy_ocid[:8]}'),
                        description='Policy created by consolidation (Move Down Next Level).',
                    ),
                )
            )

        steps, skipped = self.materialize_placements(context, PlacementResult(placements, skipped))
        return self.finalize_plan(
            context,
            plan_steps=steps,
            skipped_statements=skipped,
            candidate_count=len(candidate_ids),
            notes='Each eligible statement moves one policy level toward its effective path.',
        )
