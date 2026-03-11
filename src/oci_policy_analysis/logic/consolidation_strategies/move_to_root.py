##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# move_to_root.py – "Move to Root Compartment" consolidation strategy.
# Creates a new policy at the root compartment with all selected statements
# (location rewritten via effective path); then UPDATE or DELETE source policies.
# OCI limit: max 50 statements per policy; UI should error if >50 selected.
#
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

import re
from dataclasses import dataclass

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy
from oci_policy_analysis.common.models_consolidation import ConsolidationPlan, PlanStep, SkippedStatement
from oci_policy_analysis.logic.consolidation_helpers import (
    effective_path_segments_for_rewrite,
    flatten_defined_tags,
    internal_id_to_statement,
    normalize_compartment_path_segments,
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    rewritten_location_for_target,
)
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

logger = get_logger(component='consolidation_strategies')

# OCI limit: max statements per policy
MAX_STATEMENTS_MOVE_TO_ROOT = 50

# Root compartment path used for location rewrite (effective path preserved)
ROOT_PATH = 'ROOT'


@dataclass(frozen=True)
class MoveToRootCompartment:
    """
    Consolidation strategy: move all selected statements into a newly created
    policy at the root compartment. Uses effective-path location rewrite.
    Source policies are updated (remaining statements) or deleted if empty.
    """

    strategy_id: str = 'move_to_root'
    display_name: str = 'Move to Root Compartment'

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
        """Build a plan: one CREATE at root, then UPDATE/DELETE per source policy."""
        params = params or {}
        tag_key = str(params.get('marker_tag_key') or 'opa_consolidation')

        st_idx = internal_id_to_statement(repo)
        effective_candidates = [
            iid for iid in candidate_internal_ids if iid in st_idx and iid not in protected_internal_ids
        ]
        if not effective_candidates:
            logger.info('build_plan: no effective candidates; returning empty plan')
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name} (empty)',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes='No effective candidates (all protected or not found in repository).',
            )

        if len(effective_candidates) > MAX_STATEMENTS_MOVE_TO_ROOT:
            logger.info(
                'build_plan: %d candidates exceeds max %d; returning empty plan',
                len(effective_candidates),
                MAX_STATEMENTS_MOVE_TO_ROOT,
            )
            reason = f'Exceeds max {MAX_STATEMENTS_MOVE_TO_ROOT} statements for this strategy'
            skipped: list[SkippedStatement] = [
                {
                    'internal_id': iid,
                    'reason': reason,
                    'statement_text': (st_idx.get(iid) or {}).get('statement_text', '')[:200] or iid,
                }
                for iid in effective_candidates
            ]
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name}: max {MAX_STATEMENTS_MOVE_TO_ROOT} statements allowed (selected {len(effective_candidates)})',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes=f'Strategy did not apply any statements: {reason}. Reduce selection to ≤{MAX_STATEMENTS_MOVE_TO_ROOT} or use another strategy.',
                skipped_statements=skipped,
            )

        root_ocid = getattr(repo, 'tenancy_ocid', None) or ''
        if not root_ocid:
            logger.warning('build_plan: no tenancy_ocid on repo; cannot resolve root compartment')
            reason = 'Tenancy root not available'
            skipped: list[SkippedStatement] = [
                {
                    'internal_id': iid,
                    'reason': reason,
                    'statement_text': (st_idx.get(iid) or {}).get('statement_text', '')[:200] or iid,
                }
                for iid in effective_candidates
            ]
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name}: tenancy (root) not available',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes=reason,
                skipped_statements=skipped,
            )

        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        _compartments = getattr(repo, 'compartments', []) or []

        # Rewrite each selected statement for root compartment; collect notes
        rewritten_texts: list[str] = []
        location_change_notes: list[str] = []
        seen_text: set[str] = set()
        for iid in effective_candidates:
            st = st_idx[iid]
            raw = (st.get('statement_text') or '').strip()
            if not raw:
                continue
            eff_segments = effective_path_segments_for_rewrite(st, st.get('location', ''))
            tgt_segments = normalize_compartment_path_segments(ROOT_PATH)
            new_location = rewritten_location_for_target(eff_segments, tgt_segments)
            match = re.search(r'\bin\s+compartment\s+([^\s]+)', raw, re.IGNORECASE)
            if match:
                prefix = raw[: match.start(1)]
                suffix = raw[match.end(1) :]
                rewritten = f'{prefix}{new_location}{suffix}'
            else:
                rewritten = raw
            if rewritten and rewritten not in seen_text:
                seen_text.add(rewritten)
                rewritten_texts.append(rewritten)
            note = f'NOTE: location changed to {new_location} when moved to policy at ROOT.'
            location_change_notes.append(note)

        create_policy_name = f'Consolidated-Root-{plan_id[:16]}' if plan_id else 'Consolidated-Root'
        create_policy_description = (
            'Policy created by consolidation (Move to Root). You may change name and description as desired.'
        )
        plan_tag_val_target = f'{plan_id}:target'

        add_step: PlanStep = {
            'step_id': f'{plan_id}-01-add',
            'action': 'add',
            'policy_ocid': '',
            'before_statements': [],
            'after_statements': rewritten_texts,
            'before_tags': {},
            'after_tags': {tag_key: plan_tag_val_target},
            'plan_tags': {
                'marker_tag_key': tag_key,
                'marker_tag_value': plan_tag_val_target,
                'dataset_version': dataset_version or '',
            },
            'executed': False,
            'execution_status': 'PENDING',
            'compartment_ocid': root_ocid,
            'create_policy_name': create_policy_name,
            'create_policy_description': create_policy_description,
        }
        add_notes: list[str] = [
            'NOTE: You may change the Policy Name and Description as desired; a suitable default is provided.',
        ]
        add_notes.extend(location_change_notes)
        add_step['location_change_notes'] = add_notes
        steps: list[PlanStep] = [add_step]

        # Group candidates by source policy for UPDATE/DELETE
        candidates_by_policy: dict[str, list[str]] = {}
        for iid in effective_candidates:
            pol = st_idx[iid].get('policy_ocid') or ''
            if pol:
                candidates_by_policy.setdefault(pol, []).append(iid)

        step_n = 2
        for src_policy_ocid, src_iids in sorted(candidates_by_policy.items()):
            src_before = policy_statement_texts(repo, src_policy_ocid)
            to_remove = [st_idx[iid].get('statement_text', '').strip() for iid in src_iids]
            to_remove_set = {t for t in to_remove if t}
            src_after = [t for t in src_before if t not in to_remove_set]

            src_policy = policies_by_ocid.get(src_policy_ocid, {})
            ff_s, dd_s = policy_tag_maps(src_policy)
            ff_s_after = dict(ff_s)
            plan_tag_val = f'{plan_id}:s{step_n:02d}'
            ff_s_after[tag_key] = plan_tag_val

            if len(src_after) == 0:
                steps.append(
                    PlanStep(
                        step_id=f'{plan_id}-{step_n:02d}-delete',
                        action='delete',
                        policy_ocid=src_policy_ocid,
                        before_statements=src_before,
                        after_statements=[],
                        before_tags={**ff_s, **flatten_defined_tags(dd_s)},
                        after_tags={},
                        plan_tags={
                            'marker_tag_key': tag_key,
                            'marker_tag_value': plan_tag_val,
                            'dataset_version': dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                        rollback_command='',
                        compartment_ocid=src_policy.get('compartment_ocid', ''),
                        create_policy_name=src_policy.get('policy_name', ''),
                        create_policy_description=src_policy.get('description') or '',
                    )
                )
            else:
                steps.append(
                    PlanStep(
                        step_id=f'{plan_id}-{step_n:02d}-modify',
                        action='modify',
                        policy_ocid=src_policy_ocid,
                        before_statements=src_before,
                        after_statements=src_after,
                        before_tags={**ff_s, **flatten_defined_tags(dd_s)},
                        after_tags={**ff_s_after, **flatten_defined_tags(dd_s)},
                        plan_tags={
                            'marker_tag_key': tag_key,
                            'marker_tag_value': plan_tag_val,
                            'dataset_version': dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                    )
                )
            step_n += 1

        logger.info(
            'build_plan: Move to Root — plan_id=%s, steps=%d (1 add + %d source)',
            plan_id,
            len(steps),
            len(steps) - 1,
        )
        return ConsolidationPlan(
            plan_id=plan_id,
            tenancy_ocid=tenancy_ocid,
            plan_label=f'{self.display_name} ({len(effective_candidates)} statements)',
            created_at=now_iso(),
            plan_steps=steps,
            plan_tags={
                'strategy_id': self.strategy_id,
                'marker_tag_key': tag_key,
                'dataset_version': dataset_version or '',
            },
        )
