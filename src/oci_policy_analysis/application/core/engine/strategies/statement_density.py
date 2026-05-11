##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# statement_density.py – "Statement Density (Pack Policies)" consolidation strategy.
# Packs candidate statements into a single target policy (most candidates in required compartment or above).
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

from dataclasses import dataclass

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    compartment_ancestors_including_self,
    flatten_defined_tags,
    internal_id_to_statement,
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    required_policy_compartment_for_candidates,
    resolve_policy_compartment_path,
    trace_and_rewrite_candidate_statement_location,
)
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy
from oci_policy_analysis.common.models_consolidation import ConsolidationPlan, PlanStep

logger = get_logger(component='core.engine.strategies.consolidation')


@dataclass(frozen=True)
class PackPoliciesByStatementDensity:
    """
    First implemented strategy: pack candidate statements into a single target policy
    (chosen as the policy with most selected candidates in the required compartment or above),
    then modify/delete source policies accordingly. Uses location rewrite for statements
    moved to a different compartment.
    """

    strategy_id: str = 'statement_density_pack'
    display_name: str = 'Statement Density (Pack Policies)'

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
        """Build a pack-by-statement-density consolidation plan."""
        params = params or {}
        tag_key = str(params.get('marker_tag_key') or 'opa_consolidation')

        st_idx = internal_id_to_statement(repo)
        effective_candidates = [
            iid for iid in candidate_internal_ids if iid in st_idx and iid not in protected_internal_ids
        ]
        if not effective_candidates:
            logger.info('build_plan: no effective candidates (after excluding protected); returning empty plan')
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name} (empty)',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes='No effective candidates (all protected or not found in repository).',
            )

        required_compartment_ocid = required_policy_compartment_for_candidates(repo, effective_candidates, st_idx)
        logger.info(
            'build_plan: required_compartment_ocid=%s for %d effective candidates',
            required_compartment_ocid,
            len(effective_candidates),
        )
        compartments = getattr(repo, 'compartments', []) or []
        valid_compartment_ocids = compartment_ancestors_including_self(required_compartment_ocid, compartments)

        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        valid_policy_ocids = {
            ocid
            for ocid, pol in policies_by_ocid.items()
            if (pol.get('compartment_ocid') or '') in valid_compartment_ocids
        }

        counts: dict[str, int] = {}
        for iid in effective_candidates:
            pol = st_idx[iid].get('policy_ocid') or ''
            if pol and pol in valid_policy_ocids:
                counts[pol] = counts.get(pol, 0) + 1

        if not counts:
            tenancy_ocid_val = getattr(repo, 'tenancy_ocid', '') or ''
            root_note = ' (tenancy root)' if required_compartment_ocid == tenancy_ocid_val else ''
            logger.info(
                'build_plan: no valid policy in required compartment %s; returning empty plan with explanatory label',
                required_compartment_ocid,
            )
            return ConsolidationPlan(
                plan_id=plan_id,
                tenancy_ocid=tenancy_ocid,
                plan_label=f'{self.display_name}: no policy in required compartment{root_note} — move statements to a policy at or above scope',
                created_at=now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
                notes='No policy in required compartment scope; move statements to a policy at or above scope first.',
            )

        target_policy_ocid = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]
        target_candidate_count = counts[target_policy_ocid]
        logger.info(
            'build_plan: target_policy_ocid=%s chosen (%d candidates); counts=%s',
            target_policy_ocid,
            target_candidate_count,
            dict(counts),
        )

        candidates_by_policy: dict[str, list[str]] = {}
        for iid in effective_candidates:
            pol = st_idx[iid].get('policy_ocid') or ''
            if not pol:
                continue
            candidates_by_policy.setdefault(pol, []).append(iid)

        steps: list[PlanStep] = []
        plan_tag_val_target = f'{plan_id}:target'
        target_policy = policies_by_ocid.get(target_policy_ocid, {})
        target_comp_path = resolve_policy_compartment_path(target_policy, compartments)

        target_before = policy_statement_texts(repo, target_policy_ocid)
        location_change_notes: list[str] = []
        moved_texts: list[str] = []
        for pol, ids in candidates_by_policy.items():
            if pol == target_policy_ocid:
                continue
            for iid in ids:
                st = st_idx[iid]
                raw = (st.get('statement_text') or '').strip()
                if not raw:
                    continue
                rewritten, note, _eff, _tgt, _new_location = trace_and_rewrite_candidate_statement_location(
                    strategy_id=self.strategy_id,
                    internal_id=iid,
                    statement=st,
                    statement_text=raw,
                    target_policy_path=target_comp_path,
                )
                moved_texts.append(rewritten)
                location_change_notes.append(note)
        seen = set()
        moved_texts_dedup: list[str] = []
        for t in moved_texts:
            if t and t not in seen:
                seen.add(t)
                moved_texts_dedup.append(t)

        target_after = list(target_before)
        for t in moved_texts_dedup:
            if t and t not in target_after:
                target_after.append(t)

        ff, dd = policy_tag_maps(target_policy)
        ff_after = dict(ff)
        ff_after[tag_key] = plan_tag_val_target

        step_id = f'{plan_id}-01-target'
        step_payload: PlanStep = {
            'step_id': step_id,
            'action': 'modify',
            'policy_ocid': target_policy_ocid,
            'before_statements': target_before,
            'after_statements': target_after,
            'before_tags': {**ff, **flatten_defined_tags(dd)},
            'after_tags': {**ff_after, **flatten_defined_tags(dd)},
            'plan_tags': {
                'marker_tag_key': tag_key,
                'marker_tag_value': plan_tag_val_target,
                'dataset_version': dataset_version or '',
            },
            'executed': False,
            'execution_status': 'PENDING',
        }
        if location_change_notes:
            step_payload['location_change_notes'] = location_change_notes
        steps.append(step_payload)

        step_n = 2
        for src_policy_ocid, src_iids in sorted(candidates_by_policy.items()):
            if src_policy_ocid == target_policy_ocid:
                continue
            src_before = policy_statement_texts(repo, src_policy_ocid)
            to_remove = []
            for iid in src_iids:
                txt = st_idx[iid].get('statement_text', '').strip()
                if txt:
                    to_remove.append(txt)
            src_after = [t for t in src_before if t not in set(to_remove)]

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
            'build_plan: complete — plan_id=%s, steps=%d (1 target + %d source steps)',
            plan_id,
            len(steps),
            len(steps) - 1,
        )
        return ConsolidationPlan(
            plan_id=plan_id,
            tenancy_ocid=tenancy_ocid,
            plan_label=f'{self.display_name} ({len(effective_candidates)} candidates)',
            created_at=now_iso(),
            plan_steps=steps,
            plan_tags={
                'strategy_id': self.strategy_id,
                'marker_tag_key': tag_key,
                'dataset_version': dataset_version or '',
            },
        )
