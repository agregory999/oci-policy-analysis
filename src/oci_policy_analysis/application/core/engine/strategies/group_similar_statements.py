"""Create a new policy for semantically identical named-group statements."""

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.common.consolidation_helpers import resolve_policy_compartment_path
from oci_policy_analysis.application.core.common.grouping_helpers import (
    find_similar_principal_statement_groups,
    render_grouped_statement,
)
from oci_policy_analysis.application.core.engine.strategies.base import (
    BaseConsolidationStrategy,
    PlacementResult,
    StatementPlacement,
    TargetPolicySpec,
)
from oci_policy_analysis.application.core.models.models_consolidation import ConsolidationPlan, SkippedStatement
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class GroupSimilarStatements(BaseConsolidationStrategy):
    """Consolidate matching ``group`` or ``dynamic-group`` statements.

    The strategy deliberately creates a new policy in the source policy
    compartment. This preserves the original location clause and avoids an
    arbitrary choice of which existing policy should own the grouped statement.
    """

    strategy_id: str = 'group_similar_statements'
    display_name: str = 'Group Similar Statements'
    required_capabilities: frozenset[str] = frozenset({'policy_statements', 'policy_objects', 'compartment_hierarchy'})

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
        """Build one new-policy grouping plan for each compatible statement set."""
        context = self.planning_context(
            repo=repo, tenancy_ocid=tenancy_ocid, dataset_version=dataset_version, plan_id=plan_id, params=params
        )
        candidate_ids = self.effective_candidates(context, candidate_internal_ids, protected_internal_ids)
        if not candidate_ids:
            return self.empty_plan(
                context, reason='No effective candidates (all protected or not found in repository).'
            )

        candidate_statements = [context.statements_by_id[internal_id] for internal_id in candidate_ids]
        groups = find_similar_principal_statement_groups(candidate_statements)
        placements: list[StatementPlacement] = []
        grouped_texts: dict[str, str] = {}
        grouped_notes: dict[str, str] = {}
        grouped_ids: set[str] = set()
        skipped: list[SkippedStatement] = []

        for index, group in enumerate(groups, start=1):
            first = group.statements[0]
            source_policy_ocid = str(first.get('policy_ocid') or '')
            source_policy = context.policies_by_ocid.get(source_policy_ocid, {})
            policy_path = resolve_policy_compartment_path(source_policy, context.compartments)
            if not source_policy_ocid or not policy_path:
                for statement in group.statements:
                    skipped.append(
                        SkippedStatement(
                            internal_id=str(statement.get('internal_id') or ''),
                            statement_text=str(statement.get('statement_text') or ''),
                            reason='Source policy compartment path is unavailable for safe policy grouping.',
                        )
                    )
                continue
            try:
                grouped_text = render_grouped_statement(first, group.principals)
            except ValueError as error:
                for statement in group.statements:
                    skipped.append(
                        SkippedStatement(
                            internal_id=str(statement.get('internal_id') or ''),
                            statement_text=str(statement.get('statement_text') or ''),
                            reason=str(error),
                        )
                    )
                continue

            target = TargetPolicySpec(
                compartment_ocid=str(first.get('compartment_ocid') or ''),
                hierarchy_path=policy_path,
                policy_name=f'Consolidated-Grouped-{context.plan_id[:12]}-{index:02d}',
                description='Policy created by consolidation (Group Similar Statements).',
                reuse_existing=False,
            )
            for statement in group.statements:
                internal_id = str(statement.get('internal_id') or '')
                placements.append(
                    StatementPlacement(
                        internal_id=internal_id,
                        source_policy_ocid=str(statement.get('policy_ocid') or ''),
                        target=target,
                    )
                )
                grouped_ids.add(internal_id)
            grouped_texts[target.policy_name] = grouped_text
            grouped_notes[target.policy_name] = (
                f'Policy grouping: combined {len(group.statements)} statements into one {group.subject_type} '
                f'statement with {len(group.principals)} distinct domain-qualified principals.'
            )

        if not placements:
            grouped_or_skipped = {item['internal_id'] for item in skipped}
            for statement in candidate_statements:
                internal_id = str(statement.get('internal_id') or '')
                if internal_id not in grouped_or_skipped:
                    skipped.append(
                        SkippedStatement(
                            internal_id=internal_id,
                            statement_text=str(statement.get('statement_text') or ''),
                            reason=(
                                'No compatible group/dynamic-group statements with identical action, scope, resource, '
                                'conditions, comments, and policy compartment.'
                            ),
                        )
                    )
            return self.finalize_plan(
                context,
                plan_steps=[],
                skipped_statements=skipped,
                candidate_count=len(candidate_ids),
                notes='No compatible group or dynamic-group statements were selected for policy grouping.',
            )

        for statement in candidate_statements:
            internal_id = str(statement.get('internal_id') or '')
            if internal_id not in grouped_ids:
                skipped.append(
                    SkippedStatement(
                        internal_id=internal_id,
                        statement_text=str(statement.get('statement_text') or ''),
                        reason=(
                            'No compatible group/dynamic-group statements with identical action, scope, resource, '
                            'conditions, comments, and policy compartment.'
                        ),
                    )
                )

        steps, skipped = self.materialize_placements(context, PlacementResult(placements, skipped))
        for step in steps:
            if step['action'] != 'add':
                continue
            target_name = step.get('create_policy_name') or ''
            if target_name in grouped_texts:
                step['after_statements'] = [grouped_texts[target_name]]
                step['location_change_notes'] = [grouped_notes[target_name]]
        return self.finalize_plan(
            context,
            plan_steps=steps,
            skipped_statements=skipped,
            candidate_count=len(candidate_ids),
            notes='Creates a new policy for each compatible group; source policies are then modified or deleted.',
        )
