##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# move_closer_to_target.py – "Move Closer to Target Compartment" consolidation strategy.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    find_compartment_by_hierarchy_path,
    flatten_defined_tags,
    internal_id_to_statement,
    lca_path,
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    trace_and_rewrite_candidate_statement_location,
)
from oci_policy_analysis.application.core.models.models import BasePolicy
from oci_policy_analysis.application.core.models.models_consolidation import (
    ConsolidationPlan,
    PlanStep,
    SkippedStatement,
)
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='core.engine.strategies.consolidation')


# lca_path is now imported from consolidation_helpers
@dataclass(frozen=True)
class MoveCloserToTargetCompartment:
    """
    Consolidation strategy: move selected statements from ROOT downward toward
    the closest permissible compartment for each policy group, preserving the
    original policy name and grouping by the lowest shared compartment.
    Produces ADD/MODIFY actions for the new/target policy, and MODIFY/DELETE for the source.
    """

    strategy_id: str = 'move_closer_to_target'
    display_name: str = 'Move Closer to Target Compartment'

    def build_plan(  # noqa: C901
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
        """
        For each source policy, group all selected statements, find their deepest shared (LCA) effective path,
        and propose a new/modified policy at that compartment and with the original name. Location rewrites are applied.
        """
        params = params or {}
        tag_key = str(params.get('marker_tag_key') or 'opa_consolidation')

        st_idx = internal_id_to_statement(repo)
        effective_candidates = [
            iid for iid in candidate_internal_ids if iid in st_idx and iid not in protected_internal_ids
        ]
        if not effective_candidates:
            logger.info('build_plan: no effective candidates (all protected or not found in repository)')
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name} (empty)',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes='No effective candidates (all protected or not found in repository).',
            )

        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        compartments = getattr(repo, 'compartments', []) or []
        root_ocid = getattr(repo, 'tenancy_ocid', None) or ''
        ROOT_PATH = 'ROOT'

        # find_compartment_by_hierarchy_path is now imported from consolidation_helpers
        # Group by source policy_ocid; will process each policy independently
        group_by_policy: dict[str, list[str]] = defaultdict(list)
        for iid in effective_candidates:
            st = st_idx[iid]
            pol = st.get('policy_ocid', '')
            if pol:
                group_by_policy[pol].append(iid)

        plan_steps: list[PlanStep] = []
        skipped_statements: list[SkippedStatement] = []
        location_change_notes: list[str] = []
        step_n = 1

        logger.info(
            f'Begin MoveCloserToTargetCompartment for {len(group_by_policy)} source policies (plan_id={plan_id})'
        )

        for src_policy_ocid, iids in sorted(group_by_policy.items()):
            src_policy = policies_by_ocid.get(src_policy_ocid, {})
            orig_policy_name = src_policy.get('policy_name') or f'Consolidated-{src_policy_ocid[:8]}'
            logger.info(
                f"Processing policy '{orig_policy_name}' (OCID: {src_policy_ocid}), {len(iids)} statements selected."
            )

            # Enhanced Debug: List all statements considered for LCA with their info
            logger.info(f'  Selected statement IDs for LCA: {iids}')
            paths: list[list[str]] = []
            for iid in iids:
                statement = st_idx[iid]
                eff_path_raw = statement.get('effective_path') or ''
                eff_path_split = [s for s in eff_path_raw.split('/') if s.strip()]
                logger.info(
                    f"    Statement {iid} (policy_ocid={statement.get('policy_ocid','')}) "
                    f"statement_text='{statement.get('statement_text', '')[:100]}' "
                    f"effective_path='{eff_path_raw}' parsed={eff_path_split}"
                )
                if len(eff_path_split) == 1 and eff_path_split[0].strip().upper() == ROOT_PATH:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=statement.get('statement_text', ''),
                            reason='Statement effective path is ROOT/tenancy; cannot move away from root.',
                        )
                    )
                    logger.info(f'      SKIPPED: statement {iid} effective_path is root (ROOT) and cannot be moved.')
                elif eff_path_split and eff_path_split[0].lower() == ROOT_PATH.lower():
                    paths.append(eff_path_split)
                else:
                    logger.info(
                        f"      Skipped statement {iid}: effective_path missing or doesn't start with 'root' (got '{eff_path_raw}')"
                    )
            if not paths or len(paths) < 1:
                logger.info(
                    f'  No valid, non-root effective_paths found among selected statements in {orig_policy_name} '
                    f'(total checked: {len(iids)})'
                )
                continue
            lca = lca_path(paths)
            logger.info(f'  LCA (lowest shared compartment path) for {orig_policy_name}: {lca}')

            # Revised logic: second segment after root is the compartment to target
            if len(lca) < 2:
                logger.info(f'  LCA is root or shallower (lca={lca}), no move for {orig_policy_name}')
                for iid in iids:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason='LCA is root or shallower',
                        )
                    )
                    logger.info(
                        f"  SKIPPED: {iid} ({st_idx[iid].get('statement_text','')[:80]}) - LCA is root or shallower"
                    )
                continue

            # Build the desired compartment path by hierarchy_path, e.g. 'ROOT/cloud-engineering-shared'
            lca_comp_path = '/'.join(lca[:2]) if len(lca) > 1 else 'ROOT'
            target_comp = find_compartment_by_hierarchy_path(lca_comp_path, compartments)
            if not target_comp:
                logger.info(
                    f"  LCA compartment for path '{lca_comp_path}' not found for {orig_policy_name} (hierarchy_path case-insensitive match attempted)"
                )
                for iid in iids:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason=f"compartment for path '{lca_comp_path}' not found",
                        )
                    )
                    logger.info(
                        f"  SKIPPED: {iid} ({st_idx[iid].get('statement_text','')[:80]}) - compartment for path '{lca_comp_path}' not found"
                    )
                continue

            target_comp_ocid = target_comp.get('compartment_ocid') or target_comp.get('id')
            target_comp_name = target_comp.get('name') or ''
            # Skip if the policy already resides in the target compartment
            src_comp_ocid = src_policy.get('compartment_ocid', '')
            if src_comp_ocid and target_comp_ocid and src_comp_ocid == target_comp_ocid:
                logger.info(
                    f"  SKIPPED: Policy '{orig_policy_name}' already in compartment '{target_comp_name}'; no move needed."
                )
                for iid in iids:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason='Statement already resides in its target compartment; no move performed.',
                        )
                    )
                continue
            if not target_comp_ocid or target_comp_ocid == root_ocid:
                logger.info(f'  Target compartment is root or missing; no move from {orig_policy_name}')
                for iid in iids:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason='target compartment is root or missing',
                        )
                    )
                    logger.info(
                        f"  SKIPPED: {iid} ({st_idx[iid].get('statement_text','')[:80]}) - target compartment is root or missing"
                    )
                continue

            # Only move statements not destined to be skipped
            move_iids = []
            for iid in iids:
                st = st_idx[iid]
                orig_comp_ocid = st.get('compartment_ocid', '')
                if orig_comp_ocid and target_comp_ocid and orig_comp_ocid == target_comp_ocid:
                    # Already skipped above
                    continue
                move_iids.append(iid)
            if not move_iids:
                continue

            # Find if policy already exists in target compartment with this name
            existing_policy = None
            for p in policies_by_ocid.values():
                if p.get('policy_name') == orig_policy_name and p.get('compartment_ocid') == target_comp_ocid:
                    existing_policy = p
                    break
            policy_ocid = existing_policy.get('policy_ocid') or '' if existing_policy else ''

            before_statements = policy_statement_texts(repo, policy_ocid) if policy_ocid else []
            rewritten_texts: list[str] = list(before_statements)

            # When consolidating, set statement target location to the leaf segment (last LCA part)
            _statement_leaf_location = lca[-1] if len(lca) > 2 else lca[1]
            for iid in move_iids:
                st = st_idx[iid]
                raw = (st.get('statement_text', '') or '').strip()
                if not raw:
                    continue
                (
                    rewritten,
                    note,
                    eff_segments,
                    tgt_segments,
                    new_location,
                ) = trace_and_rewrite_candidate_statement_location(
                    strategy_id=self.strategy_id,
                    internal_id=iid,
                    statement=st,
                    statement_text=raw,
                    target_policy_path=lca_comp_path,
                )
                logger.info(
                    f'    Statement {iid}: effective_segments={eff_segments}, target_segments={tgt_segments}, new_location={new_location}'
                )
                if rewritten and rewritten not in rewritten_texts:
                    rewritten_texts.append(rewritten)
                logger.info(f'      Location rewrite note: {note}')
                location_change_notes.append(note)

            plan_tag_val = f'{plan_id}:t{step_n:02d}'
            tags = {tag_key: plan_tag_val}

            if existing_policy:
                logger.info(f"  MODIFY: existing policy '{orig_policy_name}' in compartment '{target_comp_name}'")
                ff, dd = policy_tag_maps(existing_policy)
                ff_after = dict(ff)
                ff_after.update(tags)
                plan_steps.append(
                    PlanStep(
                        step_id=f'{plan_id}-{step_n:02d}-modify',
                        action='modify',
                        policy_ocid=policy_ocid,
                        before_statements=before_statements,
                        after_statements=rewritten_texts,
                        before_tags={**ff, **flatten_defined_tags(dd)},
                        after_tags={**ff_after, **flatten_defined_tags(dd)},
                        plan_tags={
                            'marker_tag_key': tag_key,
                            'marker_tag_value': plan_tag_val,
                            'dataset_version': dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                    )
                )
            else:
                logger.info(
                    f"  ADD: new policy '{orig_policy_name}' in compartment '{target_comp_name}' (OCID {target_comp_ocid}) with {len(rewritten_texts)} statements"
                )
                plan_steps.append(
                    PlanStep(
                        step_id=f'{plan_id}-{step_n:02d}-add',
                        action='add',
                        policy_ocid='',
                        before_statements=[],
                        after_statements=rewritten_texts,
                        before_tags={},
                        after_tags=tags,
                        plan_tags={
                            'marker_tag_key': tag_key,
                            'marker_tag_value': plan_tag_val,
                            'dataset_version': dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                        compartment_ocid=target_comp_ocid,
                        create_policy_name=orig_policy_name,
                        create_policy_description=(
                            'Policy created by consolidation (Move Closer to Target). You may change name and description as desired.'
                        ),
                    )
                )
            step_n += 1

            # Remove or modify statement(s) from the original source ROOT policy
            if move_iids:
                st_texts = policy_statement_texts(repo, src_policy_ocid)
                to_remove = [st_idx[iid].get('statement_text', '').strip() for iid in move_iids]
                final_stmts = [text for text in st_texts if text not in set(to_remove)]

                ff, dd = policy_tag_maps(src_policy)
                ff_after = dict(ff)
                ff_after[tag_key] = f'{plan_id}:root{step_n:02d}'

                if len(final_stmts) < len(st_texts):
                    # Only add step if something is actually being removed
                    if final_stmts:
                        logger.info(
                            f"  MODIFY source ROOT policy '{orig_policy_name}': {len(final_stmts)} statements remain."
                        )
                        plan_steps.append(
                            PlanStep(
                                step_id=f'{plan_id}-{step_n:02d}-modify',
                                action='modify',
                                policy_ocid=src_policy_ocid,
                                before_statements=st_texts,
                                after_statements=final_stmts,
                                before_tags={**ff, **flatten_defined_tags(dd)},
                                after_tags={**ff_after, **flatten_defined_tags(dd)},
                                plan_tags={
                                    'marker_tag_key': tag_key,
                                    'marker_tag_value': ff_after[tag_key],
                                    'dataset_version': dataset_version or '',
                                },
                                executed=False,
                                execution_status='PENDING',
                            )
                        )
                    else:
                        logger.info(f"  DELETE source ROOT policy '{orig_policy_name}' (now empty).")
                        plan_steps.append(
                            PlanStep(
                                step_id=f'{plan_id}-{step_n:02d}-delete',
                                action='delete',
                                policy_ocid=src_policy_ocid,
                                before_statements=st_texts,
                                after_statements=[],
                                before_tags={**ff, **flatten_defined_tags(dd)},
                                after_tags={},
                                plan_tags={
                                    'marker_tag_key': tag_key,
                                    'marker_tag_value': ff_after[tag_key],
                                    'dataset_version': dataset_version or '',
                                },
                                executed=False,
                                execution_status='PENDING',
                                rollback_command='',
                                compartment_ocid=src_policy.get('compartment_ocid') or '',
                                create_policy_name=src_policy.get('policy_name', ''),
                                create_policy_description=src_policy.get('description') or '',
                            )
                        )
                    step_n += 1

        logger.info(
            'build_plan: Move Closer to Target — plan_id=%s, steps=%d',
            plan_id,
            len(plan_steps),
        )
        return ConsolidationPlan(
            plan_id=plan_id,
            tenancy_ocid=tenancy_ocid,
            plan_label=f'{self.display_name} ({len(effective_candidates)} statements)',
            created_at=now_iso(),
            plan_steps=plan_steps,
            skipped_statements=skipped_statements,
            plan_tags={
                'strategy_id': self.strategy_id,
                'marker_tag_key': tag_key,
                'dataset_version': dataset_version or '',
            },
            notes='See step location_change_notes for details on how each statement was moved.',
        )
