##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# move_into_target.py – "Move Each Statement Into Its Containing Compartment" strategy.
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
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    trace_and_rewrite_candidate_statement_location,
)
from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy
from oci_policy_analysis.common.models_consolidation import ConsolidationPlan, PlanStep, SkippedStatement

logger = get_logger(component='core.engine.strategies.consolidation')


@dataclass(frozen=True)
class MoveIntoTargetCompartment:
    """
    Consolidation strategy: move each selected statement directly into its own
    effective target compartment, rather than grouping by shared ancestor.
    Each compartment gets its own target policy (created or modified).
    """

    strategy_id: str = 'move_into_target'
    display_name: str = 'Move Into Target Compartment'

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
        For each selected statement, move it directly into a policy in its containing
        compartment (from its effective path), creating or updating a policy
        with the same name as original as needed.
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

        # Map: (target_compartment_path, policy_name) -> list of (internal_id, origin_policy_ocid)
        target_statements: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        skipped_statements: list[SkippedStatement] = []
        step_n = 1

        # Index the source for removal steps later
        origin_policy_statements: dict[str, set[str]] = defaultdict(set)
        for iid in effective_candidates:
            st = st_idx[iid]
            eff_path_raw = st.get('effective_path') or ''
            eff_path_split = [s for s in eff_path_raw.split('/') if s.strip()]
            if len(eff_path_split) == 1 and eff_path_split[0].strip().upper() == ROOT_PATH:
                # Do not move statements that are already at tenancy root
                skipped_statements.append(
                    SkippedStatement(
                        internal_id=iid,
                        statement_text=st.get('statement_text', ''),
                        reason='Statement effective path is ROOT/tenancy; cannot move away from root.',
                    )
                )
                continue
            if not eff_path_split or eff_path_split[0].lower() != ROOT_PATH.lower():
                skipped_statements.append(
                    SkippedStatement(
                        internal_id=iid,
                        statement_text=st.get('statement_text', ''),
                        reason="Effective path missing or doesn't start with ROOT",
                    )
                )
                continue
            # Use compartment path up to containing compartment (all segments except the leaf if >1, else just the path)
            target_comp_path = '/'.join(eff_path_split)
            orig_policy_ocid = st.get('policy_ocid', '')
            orig_policy_name = (policies_by_ocid.get(orig_policy_ocid, {}) or {}).get(
                'policy_name'
            ) or f'Consolidated-{orig_policy_ocid[:8]}'
            target_statements[(target_comp_path, orig_policy_name)].append((iid, orig_policy_ocid))
            # Do not add to origin_policy_statements unless it will be moved
            # We will do this in the filtered move entries logic below instead

        # Step: For each compartment_path/policy_name target, create or update the target policy
        plan_steps: list[PlanStep] = []
        location_change_notes: list[str] = []

        for (target_comp_path, orig_policy_name), entries in sorted(target_statements.items()):
            target_comp = find_compartment_by_hierarchy_path(target_comp_path, compartments)
            if not target_comp:
                for iid, _origin_policy_ocid in entries:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason=f"compartment for path '{target_comp_path}' not found",
                        )
                    )
                continue

            target_comp_ocid = target_comp.get('compartment_ocid') or target_comp.get('id')
            _target_comp_name = target_comp.get('name') or ''
            move_entries = []
            for iid, _origin_policy_ocid in entries:
                st = st_idx[iid]
                orig_comp_ocid = st.get('compartment_ocid', '')
                if orig_comp_ocid and target_comp_ocid and orig_comp_ocid == target_comp_ocid:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st.get('statement_text', ''),
                            reason='Statement already resides in its target compartment; no move performed.',
                        )
                    )
                else:
                    move_entries.append((iid, _origin_policy_ocid))
                    # Only add entries that will be truly moved
                    origin_policy_statements[_origin_policy_ocid].add(iid)
            if not move_entries:
                continue
            entries = move_entries

            if not target_comp_ocid or target_comp_ocid == root_ocid:
                for iid, _origin_policy_ocid in entries:
                    skipped_statements.append(
                        SkippedStatement(
                            internal_id=iid,
                            statement_text=st_idx[iid].get('statement_text', ''),
                            reason='target compartment is root or missing',
                        )
                    )
                continue

            # See if a policy with the original name exists in the target compartment
            existing_policy = None
            for p in policies_by_ocid.values():
                if p.get('policy_name') == orig_policy_name and p.get('compartment_ocid') == target_comp_ocid:
                    existing_policy = p
                    break
            policy_ocid = (existing_policy.get('policy_ocid') or '') if existing_policy else ''

            # Collect current and new statements for that policy
            before_statements = policy_statement_texts(repo, policy_ocid) if policy_ocid else []
            rewritten_texts: list[str] = list(before_statements)

            for iid, _origin_policy_ocid in entries:
                st = st_idx[iid]
                raw = (st.get('statement_text', '') or '').strip()
                if not raw:
                    continue
                rewritten, note, _eff, _tgt, _new_location = trace_and_rewrite_candidate_statement_location(
                    strategy_id=self.strategy_id,
                    internal_id=iid,
                    statement=st,
                    statement_text=raw,
                    target_policy_path=target_comp_path,
                )
                if rewritten and rewritten not in rewritten_texts:
                    rewritten_texts.append(rewritten)
                location_change_notes.append(note)

            plan_tag_val = f'{plan_id}:t{step_n:02d}'
            tags = {tag_key: plan_tag_val}

            if existing_policy:
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
                        location_change_notes=location_change_notes[-len(entries) :],
                    )
                )
            else:
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
                            'Policy created by consolidation (Move Into Target Compartment). You may change name and description as desired.'
                        ),
                        location_change_notes=location_change_notes[-len(entries) :],
                    )
                )
            step_n += 1

        # Remove/modify source policies accordingly
        for origin_policy_ocid, iids in origin_policy_statements.items():
            if not iids:
                continue
            st_texts = policy_statement_texts(repo, origin_policy_ocid)
            to_remove = [st_idx[iid].get('statement_text', '').strip() for iid in iids]
            final_stmts = [text for text in st_texts if text not in set(to_remove)]

            src_policy = policies_by_ocid.get(origin_policy_ocid, {})
            ff, dd = policy_tag_maps(src_policy)
            ff_after = dict(ff)
            ff_after[tag_key] = f'{plan_id}:src{step_n:02d}'

            if len(final_stmts) < len(st_texts):
                # Only add step if something is actually being removed
                if final_stmts:
                    plan_steps.append(
                        PlanStep(
                            step_id=f'{plan_id}-{step_n:02d}-modify',
                            action='modify',
                            policy_ocid=origin_policy_ocid,
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
                    plan_steps.append(
                        PlanStep(
                            step_id=f'{plan_id}-{step_n:02d}-delete',
                            action='delete',
                            policy_ocid=origin_policy_ocid,
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
            'build_plan: Move Into Target Compartment — plan_id=%s, steps=%d',
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
            notes='Each statement moved directly into the compartment from its effective_path; see step location_change_notes for rewrite details.',
        )
