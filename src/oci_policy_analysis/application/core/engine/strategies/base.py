##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
##########################################################################
"""Shared contract and planning primitives for consolidation strategies.

The package deliberately separates *placement* from *materialization*:

    strategy rule -> StatementPlacement -> common plan steps -> rollback data

New strategies should decide where eligible statements belong, return placements,
and reuse :class:`BaseConsolidationStrategy` for policy lookup, statement
rewriting, source cleanup, and plan metadata. This keeps the OCI execution and
rollback contract consistent without turning placement rules into a generic DSL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    flatten_defined_tags,
    internal_id_to_statement,
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    trace_and_rewrite_candidate_statement_location,
)
from oci_policy_analysis.application.core.models.models import BasePolicy
from oci_policy_analysis.application.core.models.models_consolidation import (
    ConsolidationPlan,
    PlanStep,
    RollbackStep,
    SkippedStatement,
)
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository


@dataclass(frozen=True)
class PlanningContext:
    """Read-only inputs shared by a strategy during one plan build."""

    repo: PolicyAnalysisRepository
    tenancy_ocid: str
    dataset_version: str | None
    plan_id: str
    tag_key: str
    statements_by_id: dict
    policies_by_ocid: dict[str, BasePolicy]
    policies_by_location_and_name: dict[tuple[str, str], BasePolicy]
    compartments: list[dict]
    root_ocid: str


@dataclass(frozen=True)
class TargetPolicySpec:
    """Identity and creation details of a policy receiving moved statements."""

    compartment_ocid: str
    hierarchy_path: str
    policy_name: str
    description: str
    reuse_existing: bool = True


@dataclass(frozen=True)
class StatementPlacement:
    """One selected statement and the target policy chosen by a strategy rule."""

    internal_id: str
    source_policy_ocid: str
    target: TargetPolicySpec


@dataclass(frozen=True)
class PlacementResult:
    """Strategy output before shared OCI-plan materialization."""

    placements: list[StatementPlacement]
    skipped_statements: list[SkippedStatement]


class Strategy(Protocol):
    """Protocol for pluggable consolidation strategies."""

    strategy_id: str
    display_name: str
    required_capabilities: frozenset[str]

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
        """Build a consolidation plan for the given candidates and context."""
        ...


class BaseConsolidationStrategy:
    """Shared mechanics for strategy implementations.

    Existing strategies can migrate incrementally by using these helpers. New
    strategies should start with ``planning_context`` and express their policy
    decision as :class:`StatementPlacement` values. The base class also creates
    complete rollback metadata from the same before/after snapshots used by the
    renderer, making rollback a durable part of the plan contract.
    """

    strategy_id: str
    display_name: str
    required_capabilities: frozenset[str]

    def planning_context(
        self,
        *,
        repo: PolicyAnalysisRepository,
        tenancy_ocid: str,
        dataset_version: str | None,
        plan_id: str,
        params: dict[str, object] | None,
    ) -> PlanningContext:
        """Build stable indexes once, rather than in every strategy branch."""
        policies_by_ocid = {
            policy.get('policy_ocid'): policy
            for policy in (getattr(repo, 'policies', []) or [])
            if policy.get('policy_ocid')
        }
        policies_by_location_and_name = {
            ((policy.get('compartment_ocid') or ''), (policy.get('policy_name') or '')): policy
            for policy in policies_by_ocid.values()
        }
        return PlanningContext(
            repo=repo,
            tenancy_ocid=tenancy_ocid,
            dataset_version=dataset_version,
            plan_id=plan_id,
            tag_key=str((params or {}).get('marker_tag_key') or 'opa_consolidation'),
            statements_by_id=internal_id_to_statement(repo),
            policies_by_ocid=policies_by_ocid,
            policies_by_location_and_name=policies_by_location_and_name,
            compartments=getattr(repo, 'compartments', []) or [],
            root_ocid=getattr(repo, 'tenancy_ocid', None) or '',
        )

    def effective_candidates(
        self, context: PlanningContext, candidate_ids: set[str], protected_ids: set[str]
    ) -> list[str]:
        """Return deterministic, resolvable candidates which are not protected."""
        return sorted(
            candidate_id
            for candidate_id in candidate_ids
            if candidate_id in context.statements_by_id and candidate_id not in protected_ids
        )

    def empty_plan(self, context: PlanningContext, *, reason: str) -> ConsolidationPlan:
        """Return the standard empty-plan representation used by all strategies."""
        return ConsolidationPlan(
            plan_id=context.plan_id,
            tenancy_ocid=context.tenancy_ocid,
            plan_label=f'{self.display_name} (empty)',
            created_at=now_iso(),
            plan_steps=[],
            plan_tags={'strategy_id': self.strategy_id},
            notes=reason,
        )

    def existing_target(self, context: PlanningContext, target: TargetPolicySpec) -> BasePolicy | None:
        """Find a same-name policy in the selected compartment, if one exists."""
        if not target.reuse_existing:
            return None
        return context.policies_by_location_and_name.get((target.compartment_ocid, target.policy_name))

    def materialize_placements(
        self, context: PlanningContext, result: PlacementResult
    ) -> tuple[list[PlanStep], list[SkippedStatement]]:
        """Turn explicit placements into target and source-cleanup plan steps.

        A new strategy normally calls this after it has made its placement
        decisions. This method owns the risky mechanical details: rewriting a
        statement relative to the selected target, reusing a matching policy,
        and only removing a source statement once a target step contains it.
        """
        grouped: dict[TargetPolicySpec, list[StatementPlacement]] = {}
        for placement in result.placements:
            grouped.setdefault(placement.target, []).append(placement)

        steps: list[PlanStep] = []
        skipped = list(result.skipped_statements)
        moved_by_source: dict[str, set[str]] = {}
        step_number = 1
        for target, placements in sorted(
            grouped.items(), key=lambda item: (item[0].hierarchy_path, item[0].policy_name)
        ):
            existing = self.existing_target(context, target)
            policy_ocid = (existing or {}).get('policy_ocid') or ''
            before_statements = policy_statement_texts(context.repo, policy_ocid) if policy_ocid else []
            after_statements = list(before_statements)
            location_notes: list[str] = []
            moved_placements: list[StatementPlacement] = []
            for placement in placements:
                statement = context.statements_by_id[placement.internal_id]
                raw_statement = (statement.get('statement_text') or '').strip()
                if not raw_statement:
                    skipped.append(
                        SkippedStatement(
                            internal_id=placement.internal_id,
                            statement_text='',
                            reason='Statement text is empty and cannot be moved.',
                        )
                    )
                    continue
                rewritten, note, _effective, _target, _new_location = trace_and_rewrite_candidate_statement_location(
                    strategy_id=self.strategy_id,
                    internal_id=placement.internal_id,
                    statement=statement,
                    statement_text=raw_statement,
                    target_policy_path=target.hierarchy_path,
                )
                if not rewritten:
                    skipped.append(
                        SkippedStatement(
                            internal_id=placement.internal_id,
                            statement_text=raw_statement,
                            reason='Statement could not be rewritten for the selected target policy.',
                        )
                    )
                    continue
                if rewritten not in after_statements:
                    after_statements.append(rewritten)
                location_notes.append(note)
                moved_placements.append(placement)

            if not moved_placements:
                continue
            marker_value = f'{context.plan_id}:t{step_number:02d}'
            if existing:
                freeform, defined = policy_tag_maps(existing)
                after_freeform = dict(freeform)
                after_freeform[context.tag_key] = marker_value
                steps.append(
                    PlanStep(
                        step_id=f'{context.plan_id}-{step_number:02d}-modify',
                        action='modify',
                        policy_ocid=policy_ocid,
                        before_statements=before_statements,
                        after_statements=after_statements,
                        before_tags={**freeform, **flatten_defined_tags(defined)},
                        after_tags={**after_freeform, **flatten_defined_tags(defined)},
                        plan_tags={
                            'marker_tag_key': context.tag_key,
                            'marker_tag_value': marker_value,
                            'dataset_version': context.dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                        location_change_notes=location_notes,
                    )
                )
            else:
                steps.append(
                    PlanStep(
                        step_id=f'{context.plan_id}-{step_number:02d}-add',
                        action='add',
                        policy_ocid='',
                        before_statements=[],
                        after_statements=after_statements,
                        before_tags={},
                        after_tags={context.tag_key: marker_value},
                        plan_tags={
                            'marker_tag_key': context.tag_key,
                            'marker_tag_value': marker_value,
                            'dataset_version': context.dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                        compartment_ocid=target.compartment_ocid,
                        create_policy_name=target.policy_name,
                        create_policy_description=target.description,
                        location_change_notes=location_notes,
                    )
                )
            for placement in moved_placements:
                moved_by_source.setdefault(placement.source_policy_ocid, set()).add(placement.internal_id)
            step_number += 1

        for source_policy_ocid, internal_ids in sorted(moved_by_source.items()):
            before_statements = policy_statement_texts(context.repo, source_policy_ocid)
            source = context.policies_by_ocid.get(source_policy_ocid, {})
            source_texts = {
                (context.statements_by_id[internal_id].get('statement_text') or '').strip()
                for internal_id in internal_ids
            }
            after_statements = [statement for statement in before_statements if statement not in source_texts]
            freeform, defined = policy_tag_maps(source)
            marker_value = f'{context.plan_id}:s{step_number:02d}'
            after_freeform = dict(freeform)
            after_freeform[context.tag_key] = marker_value
            common = {
                'policy_ocid': source_policy_ocid,
                'before_statements': before_statements,
                'before_tags': {**freeform, **flatten_defined_tags(defined)},
                'plan_tags': {
                    'marker_tag_key': context.tag_key,
                    'marker_tag_value': marker_value,
                    'dataset_version': context.dataset_version or '',
                },
                'executed': False,
                'execution_status': 'PENDING',
            }
            if after_statements:
                steps.append(
                    PlanStep(
                        **common,
                        step_id=f'{context.plan_id}-{step_number:02d}-modify',
                        action='modify',
                        after_statements=after_statements,
                        after_tags={**after_freeform, **flatten_defined_tags(defined)},
                    )
                )
            else:
                steps.append(
                    PlanStep(
                        **common,
                        step_id=f'{context.plan_id}-{step_number:02d}-delete',
                        action='delete',
                        after_statements=[],
                        after_tags={},
                        rollback_command='',
                        compartment_ocid=source.get('compartment_ocid', ''),
                        create_policy_name=source.get('policy_name', ''),
                        create_policy_description=source.get('description') or '',
                    )
                )
            step_number += 1
        return steps, skipped

    def finalize_plan(
        self,
        context: PlanningContext,
        *,
        plan_steps: list[PlanStep],
        skipped_statements: list[SkippedStatement] | None = None,
        notes: str | None = None,
        candidate_count: int | None = None,
    ) -> ConsolidationPlan:
        """Attach rollback snapshots and shared metadata to a completed plan.

        Rollback remains data, not an imperative action: callers can render it,
        persist it, or later execute it through a controlled workflow.
        """
        for step in plan_steps:
            step.setdefault('rollback', self.rollback_for_step(context, step))
        suffix = f' ({candidate_count} statements)' if candidate_count is not None else ''
        plan: ConsolidationPlan = {
            'plan_id': context.plan_id,
            'tenancy_ocid': context.tenancy_ocid,
            'plan_label': f'{self.display_name}{suffix}',
            'created_at': now_iso(),
            'plan_steps': plan_steps,
            'plan_tags': {
                'strategy_id': self.strategy_id,
                'marker_tag_key': context.tag_key,
                'dataset_version': context.dataset_version or '',
            },
        }
        if skipped_statements:
            plan['skipped_statements'] = skipped_statements
        if notes:
            plan['notes'] = notes
        return plan

    @staticmethod
    def rollback_for_step(context: PlanningContext, step: PlanStep) -> RollbackStep:
        """Capture the inverse operation from the immutable pre-plan snapshot."""
        action = step['action']
        if action == 'add':
            return {'action': 'delete_created_policy', 'policy_ocid': '', 'requires_created_policy_id': True}
        if action == 'delete':
            policy = context.policies_by_ocid.get(step.get('policy_ocid', ''), {})
            freeform_tags, defined_tags = policy_tag_maps(policy)
            return {
                'action': 'recreate_deleted_policy',
                'policy_ocid': step.get('policy_ocid', ''),
                'compartment_ocid': step.get('compartment_ocid', ''),
                'policy_name': step.get('create_policy_name', ''),
                'policy_description': step.get('create_policy_description', ''),
                'statements': list(step.get('before_statements') or []),
                'freeform_tags': dict(freeform_tags),
                'defined_tags': dict(defined_tags),
            }
        policy = context.policies_by_ocid.get(step.get('policy_ocid', ''), {})
        freeform_tags, defined_tags = policy_tag_maps(policy)
        return {
            'action': 'restore_policy',
            'policy_ocid': step.get('policy_ocid', ''),
            'statements': list(step.get('before_statements') or []),
            'freeform_tags': dict(freeform_tags),
            'defined_tags': dict(defined_tags),
        }
