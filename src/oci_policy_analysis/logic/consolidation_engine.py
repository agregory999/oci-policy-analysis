##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_engine.py
#
# Middle tier for the Consolidation Workbench:
# - Owns session/plan state (per-corpus/tenancy)
# - Generates consolidation plans using pluggable strategies
# - Renders execution + rollback command text for administrators
# - Validates execution progress after reload by inspecting policy tags / policy presence
#
# @author: Andrew Gregory
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from oci_policy_analysis.common.caching import CacheManager
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy, RegularPolicyStatement
from oci_policy_analysis.common.models_consolidation import ConsolidationPlan, PlanStep
from oci_policy_analysis.logic.consolidation_strategies import Strategy
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository
from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo

logger = get_logger(component='consolidation_engine')

SourceType = Literal['live', 'cache', 'compliance', 'unknown']


def _now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _json_compact(obj: object) -> str:
    """Safe JSON dump for CLI snippets."""
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), default=str)


def _shell_escape_single_quoted(s: str) -> str:
    """
    Escape a string for use inside a single-quoted shell literal.
    In single-quoted bash, the only escape is '' (end quote, escaped single quote, new quote).
    """
    return s.replace("'", "'\"'\"'")


def _shell_escape_double_quoted(s: str) -> str:
    """
    Escape a string for use inside a double-quoted shell argument.
    Escapes backslash, double quote, and single quote so statements like
    allow group 'Federated'/'group' and JSON structure are safe.
    """
    return s.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")


def _statements_cli_value(statements: list) -> str:
    """
    JSON array of statement strings, escaped for embedding in a double-quoted
    shell argument. Caller wraps result in double quotes: --statements \"...\"
    """
    raw = _json_compact(statements if statements is not None else [])
    return _shell_escape_double_quoted(raw)


def _flatten_defined_tags(defined_tags: dict | None) -> dict[str, str]:
    """
    Flatten OCI defined tags into UI-friendly key space "namespace:key".
    This is NOT a reversible transform; it is used only for display.
    """
    if not defined_tags or not isinstance(defined_tags, dict):
        return {}
    out: dict[str, str] = {}
    for ns, val in defined_tags.items():
        if isinstance(val, dict):
            for k, v in val.items():
                out[f'{ns}:{k}'] = str(v)
        else:
            out[str(ns)] = str(val)
    return out


def _policy_tag_maps(policy: BasePolicy) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """
    Return (freeform_tags, defined_tags) as separate maps.
    Falls back to empty maps if absent.
    """
    freeform = policy.get('freeform_tags') or {}
    defined = policy.get('defined_tags') or {}
    if not isinstance(freeform, dict):
        freeform = {}
    if not isinstance(defined, dict):
        defined = {}
    # Ensure defined is dict[str, dict[str,str]] best-effort
    defined2: dict[str, dict[str, str]] = {}
    for ns, val in defined.items():
        if isinstance(val, dict):
            defined2[str(ns)] = {str(k): str(v) for k, v in val.items()}
    return {str(k): str(v) for k, v in freeform.items()}, defined2


def _policy_statement_texts(repo: PolicyAnalysisRepository, policy_ocid: str) -> list[str]:
    """Return raw statement_text list for all regular statements in a policy."""
    out: list[str] = []
    for st in getattr(repo, 'regular_statements', []) or []:
        if st.get('policy_ocid') == policy_ocid:
            txt = st.get('statement_text')
            if isinstance(txt, str) and txt.strip():
                out.append(txt.strip())
    return out


def _internal_id_to_statement(repo: PolicyAnalysisRepository) -> dict[str, RegularPolicyStatement]:
    """Build a map of statement internal_id -> statement dict for lookups."""
    idx: dict[str, RegularPolicyStatement] = {}
    for st in getattr(repo, 'regular_statements', []) or []:
        iid = st.get('internal_id')
        if isinstance(iid, str) and iid and iid not in idx:
            idx[iid] = st
    return idx


def _statement_scope_compartment_ocid(st: RegularPolicyStatement, tenancy_ocid: str) -> str:
    """
    OCI rule: a statement cannot live in a policy below its scope in the hierarchy.
    Returns the compartment OCID that represents this statement's scope (tenancy root or effective compartment).
    """
    if st.get('location_type') == 'tenancy':
        return tenancy_ocid
    eff = st.get('effective_compartment_ocid')
    if eff:
        return eff
    return st.get('compartment_ocid') or tenancy_ocid


def _compartment_ancestors_including_self(compartment_ocid: str, compartments: list[dict]) -> set[str]:
    """Return set of compartment OCIDs: the given compartment and all ancestors up to root."""
    by_id = {c.get('id'): c for c in compartments if c.get('id')}
    result: set[str] = set()
    current = compartment_ocid
    while current and current not in result:
        result.add(current)
        parent = by_id.get(current, {}).get('parent_id')
        if not parent or parent == current:
            break
        current = parent
    return result


def _lca_compartment_ocids(ocids: set[str], compartments: list[dict], tenancy_ocid: str) -> str:
    """
    Least common ancestor of the given compartment OCIDs. A policy containing statements
    with these scopes must live in this compartment or an ancestor. If any scope is tenancy, returns tenancy_ocid.
    """
    if not ocids:
        logger.debug('_lca_compartment_ocids: no ocids, returning tenancy_ocid=%s', tenancy_ocid)
        return tenancy_ocid
    if tenancy_ocid in ocids:
        logger.debug('_lca_compartment_ocids: tenancy in scope, returning tenancy_ocid=%s', tenancy_ocid)
        return tenancy_ocid
    by_id = {c.get('id'): c for c in compartments if c.get('id')}
    ancestor_sets = [_compartment_ancestors_including_self(ocid, compartments) for ocid in ocids]
    common = ancestor_sets[0]
    for s in ancestor_sets[1:]:
        common &= s
    if not common:
        return tenancy_ocid

    # Choose the deepest (most specific) common ancestor: max by path length
    def depth(ocid: str) -> int:
        """Return path depth (segment count) for LCA comparison."""
        path = (by_id.get(ocid) or {}).get('hierarchy_path') or ''
        return len(path.split('/'))

    result = max(common, key=depth)
    logger.debug('_lca_compartment_ocids: common=%s -> LCA ocid=%s (depth %d)', common, result, depth(result))
    return result


def _normalize_compartment_path_segments(path: str) -> list[str]:
    """Split compartment path into segments (e.g. ROOT/A/B -> ['ROOT','A','B']). Preserves case."""
    if not path or not path.strip():
        return []
    return [p.strip() for p in path.replace('\\', '/').split('/') if p.strip()]


def _resolve_policy_compartment_path(policy: BasePolicy, compartments: list) -> str:
    """Return compartment hierarchy path for a policy: from policy.compartment_path or lookup by compartment_ocid."""
    path = (policy.get('compartment_path') or '').strip()
    if path:
        return path
    comp_ocid = (policy.get('compartment_ocid') or '').strip()
    if not comp_ocid or not compartments:
        return ''
    for c in compartments:
        if c.get('id') == comp_ocid:
            return (c.get('hierarchy_path') or '').strip()
    return ''


def _is_root_path(segments: list[str]) -> bool:
    """True if segments represent tenancy root (empty or single segment ROOT/root)."""
    if not segments:
        return True
    if len(segments) == 1 and segments[0].upper() == 'ROOT':
        return True
    return False


def _effective_path_segments_for_rewrite(st: RegularPolicyStatement, old_location: str) -> list[str]:
    """
    Resolve effective path as segments from the statement. Effective path does not change when moving.
    Prefer st.effective_path; else build from st.compartment_path + st.location or old_location.
    """
    eff_path = (st.get('effective_path') or '').strip()
    comp_path = (st.get('compartment_path') or '').strip()
    loc = (st.get('location') or '').strip() or old_location
    if eff_path:
        segs = _normalize_compartment_path_segments(eff_path)
        logger.debug(
            '[location rewrite] effective_path from st: %r -> segments %s',
            eff_path,
            segs,
        )
        return segs
    comp_segments = _normalize_compartment_path_segments(comp_path)
    if not comp_segments and not loc:
        logger.debug('[location rewrite] no effective_path, compartment_path, or location on statement')
        return []
    if ':' in loc:
        segs = comp_segments + [p.strip() for p in loc.split(':') if p.strip()]
    else:
        segs = comp_segments + [loc] if loc else comp_segments
    logger.debug(
        '[location rewrite] effective_path derived from st.compartment_path=%r + location=%r -> segments %s',
        comp_path or '(empty)',
        loc or '(empty)',
        segs,
    )
    return segs


def _rewrite_statement_location_for_target(  # noqa: C901
    statement_text: str,
    st: RegularPolicyStatement,
    target_comp_path: str,
) -> tuple[str, str | None]:
    """
    Rewrite the "in compartment X" part of a statement when it is moved to a policy at target_comp_path.
    Effective path does not change; we compute the location string that yields the same effective_path
    when the policy lives at target_comp_path (OCI colon-delimited location = path from target to scope).
    Uses st.compartment_path, st.effective_path, and st.location from the incoming statement.
    Returns (rewritten_text, note_or_none).
    """
    source_comp_path = (st.get('compartment_path') or '').strip()
    eff_path = (st.get('effective_path') or '').strip()
    st_location = (st.get('location') or '').strip()
    logger.debug(
        '[location rewrite] ENTRY: st.compartment_path=%r, st.effective_path=%r, st.location=%r, target_comp_path=%r',
        source_comp_path or '(empty)',
        eff_path or '(empty)',
        st_location or '(empty)',
        target_comp_path or '(empty)',
    )
    logger.debug(
        '[location rewrite] statement_text=%r',
        (statement_text[:120] + '...' if statement_text and len(statement_text) > 120 else statement_text),
    )
    if not statement_text or not statement_text.strip():
        logger.debug('[location rewrite] SKIP: empty statement')
        return statement_text, None
    text_lower = statement_text.lower()
    if 'in tenancy' in text_lower and 'in compartment' not in text_lower:
        logger.debug('[location rewrite] SKIP: statement is tenancy-scoped (no compartment location)')
        return statement_text, None
    target_segments = _normalize_compartment_path_segments(target_comp_path or '')
    if not target_comp_path and not target_segments:
        logger.debug('[location rewrite] SKIP: target_comp_path is empty (cannot compute new location)')
        return statement_text, None

    match = re.search(r'\bin\s+compartment\s+([^\s]+)', statement_text, re.IGNORECASE)
    if not match:
        logger.debug("[location rewrite] SKIP: no 'in compartment X' found in statement")
        return statement_text, None

    old_location = match.group(1).strip()
    prefix = statement_text[: match.start(1)]
    suffix = statement_text[match.end(1) :]
    logger.debug('[location rewrite] matched old_location=%r', old_location)

    effective_segments = _effective_path_segments_for_rewrite(st, old_location)
    if not effective_segments:
        logger.debug('[location rewrite] SKIP: could not resolve effective path segments from statement')
        return statement_text, None

    source_segments = _normalize_compartment_path_segments(source_comp_path or '')
    if source_segments == target_segments:
        logger.debug('[location rewrite] SKIP: source and target path identical')
        return statement_text, None

    # Remainder = path from target to scope (colon-delimited = new location per OCI). Effective path unchanged.
    if _is_root_path(target_segments):
        if effective_segments and effective_segments[0].upper() == 'ROOT':
            remainder = effective_segments[1:]
            logger.debug(
                '[location rewrite] target is ROOT; remainder = effective_segments[1:] = %s (dropped root)',
                remainder,
            )
        else:
            remainder = effective_segments
            logger.debug('[location rewrite] target is ROOT; effective has no leading ROOT, remainder=%s', remainder)
    else:
        tlen = len(target_segments)
        eff_prefix = [s.upper() for s in effective_segments[:tlen]]
        tgt_upper = [s.upper() for s in target_segments]
        if eff_prefix == tgt_upper and len(effective_segments) >= tlen:
            remainder = effective_segments[tlen:]
            logger.debug(
                '[location rewrite] target is prefix of effective; remainder = effective_segments[%d:] = %s',
                tlen,
                remainder,
            )
        else:
            remainder = effective_segments
            logger.debug(
                '[location rewrite] target is not prefix of effective; remainder = full effective_segments = %s',
                remainder,
            )

    new_location = ':'.join(remainder) if remainder else old_location
    logger.debug(
        '[location rewrite] new_location=%r (from remainder %s); old_location=%r; effective_path unchanged',
        new_location,
        remainder,
        old_location,
    )
    if new_location == old_location:
        logger.debug('[location rewrite] SKIP: new_location same as old (no change needed)')
        return statement_text, None

    rewritten = f'{prefix}{new_location}{suffix}'
    note = (
        f"NOTE: compartment referenced changes from {old_location} to {new_location} because the "
        f"policy statement moved from {source_comp_path or '(unknown)'} to {target_comp_path or '(unknown)'}."
    )
    logger.info(
        '[location rewrite] rewritten %r -> %r (policy moved to %s)',
        old_location,
        new_location,
        target_comp_path or '(root)',
    )
    return rewritten, note


def _required_policy_compartment_for_candidates(
    repo: PolicyAnalysisRepository,
    candidate_internal_ids: list[str],
    st_idx: dict[str, RegularPolicyStatement],
) -> str:
    """
    Highest compartment in the tenancy where a policy can legally contain all candidate statements.
    (You cannot put a tenancy-scoped statement in a policy below root; cannot put a statement in a policy below its scope.)
    """
    tenancy_ocid = getattr(repo, 'tenancy_ocid', None) or ''
    compartments = getattr(repo, 'compartments', []) or []
    scope_ocids: set[str] = set()
    for iid in candidate_internal_ids:
        st = st_idx.get(iid)
        if st:
            scope_ocids.add(_statement_scope_compartment_ocid(st, tenancy_ocid))
    logger.debug(
        '_required_policy_compartment_for_candidates: %d candidates -> scope_ocids=%s, compartments=%d',
        len(candidate_internal_ids),
        scope_ocids,
        len(compartments),
    )
    if not compartments:
        result = (
            tenancy_ocid
            if tenancy_ocid in scope_ocids or len(scope_ocids) > 1
            else (scope_ocids.pop() if scope_ocids else tenancy_ocid)
        )
        logger.debug('_required_policy_compartment_for_candidates: no hierarchy, required_ocid=%s', result)
        return result
    result = _lca_compartment_ocids(scope_ocids, compartments, tenancy_ocid)
    logger.info('Required policy compartment (LCA of candidate scopes): %s', result)
    return result


@dataclass(frozen=True)
class PackPoliciesByStatementDensity:
    """
    First implemented strategy.

    Goal:
    - "Pack" candidate statements into a single target policy (chosen as the policy with most selected candidates),
      then modify/delete source policies accordingly.

    Compartment hierarchy:
    - A statement cannot live in a policy below its scope (e.g. tenancy-scoped statements must be in root).
    - The target policy is chosen only from policies in the required compartment or above: the highest
      compartment that can legally hold all candidate statements (LCA of their scopes).
    - If no such policy exists, the plan is empty with an explanatory label.

    Notes:
    - This does not attempt semantic equivalence; it is a mechanical statement-move plan.
    - It relies on policy tags for execution marking (freeform tag marker).
    """

    strategy_id: str = 'statement_density_pack'
    display_name: str = 'Statement Density (Pack Policies)'

    def build_plan(  # noqa: C901
        self,
        *,
        repo: PolicyAnalysisRepository,
        corpus_id: str,
        dataset_version: str | None,
        candidate_internal_ids: set[str],
        protected_internal_ids: set[str],
        plan_id: str,
        params: dict[str, object] | None = None,
    ) -> ConsolidationPlan:
        """Build a pack-by-statement-density consolidation plan.

        Packs candidate statements into a single target policy (the one with most candidates
        in the required compartment or above). Rewrites statement locations when moving
        to a different compartment (e.g. root/A + location B -> root, location becomes A:B).
        Source policies are modified or deleted as needed.

        Args:
            repo: Policy repository with policies, compartments, and regular_statements.
            corpus_id: Tenancy or corpus id for the plan.
            dataset_version: Optional dataset version label.
            candidate_internal_ids: Set of statement internal_ids to consolidate.
            protected_internal_ids: Set of statement internal_ids to exclude.
            plan_id: Unique plan identifier.
            params: Optional dict; marker_tag_key used for execution marking.

        Returns:
            ConsolidationPlan with plan_steps (one target modify + zero or more source modify/delete).
        """
        params = params or {}
        tag_key = str(params.get('marker_tag_key') or 'opa_consolidation')

        # Resolve candidates -> statements, exclude protected
        st_idx = _internal_id_to_statement(repo)
        effective_candidates = [
            iid for iid in candidate_internal_ids if iid in st_idx and iid not in protected_internal_ids
        ]
        if not effective_candidates:
            logger.info('build_plan: no effective candidates (after excluding protected); returning empty plan')
            return ConsolidationPlan(
                plan_id=plan_id,
                corpus_id=corpus_id,
                plan_label=f'{self.display_name} (empty)',
                created_at=_now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
            )

        # Required compartment: cannot put a statement in a policy below its scope (e.g. tenancy-scoped must be in root)
        required_compartment_ocid = _required_policy_compartment_for_candidates(repo, effective_candidates, st_idx)
        logger.info(
            'build_plan: required_compartment_ocid=%s for %d effective candidates',
            required_compartment_ocid,
            len(effective_candidates),
        )
        compartments = getattr(repo, 'compartments', []) or []
        valid_compartment_ocids = _compartment_ancestors_including_self(required_compartment_ocid, compartments)
        logger.info(
            'build_plan: valid_compartment_ocids (required or ancestors) count=%d',
            len(valid_compartment_ocids),
        )

        # Precompute policy metadata
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        # Only policies in the required compartment or an ancestor can hold these statements
        valid_policy_ocids = {
            ocid
            for ocid, pol in policies_by_ocid.items()
            if (pol.get('compartment_ocid') or '') in valid_compartment_ocids
        }
        logger.info(
            'build_plan: valid_policy_ocids count=%d (policies in required compartment or above)',
            len(valid_policy_ocids),
        )

        # Count candidates per policy (only for valid policies)
        counts: dict[str, int] = {}
        for iid in effective_candidates:
            pol = st_idx[iid].get('policy_ocid') or ''
            if pol and pol in valid_policy_ocids:
                counts[pol] = counts.get(pol, 0) + 1

        if not counts:
            tenancy_ocid = getattr(repo, 'tenancy_ocid', '') or ''
            root_note = ' (tenancy root)' if required_compartment_ocid == tenancy_ocid else ''
            logger.info(
                'build_plan: no valid policy in required compartment %s; returning empty plan with explanatory label',
                required_compartment_ocid,
            )
            return ConsolidationPlan(
                plan_id=plan_id,
                corpus_id=corpus_id,
                plan_label=f'{self.display_name}: no policy in required compartment{root_note} — move statements to a policy at or above scope',
                created_at=_now_iso(),
                plan_steps=[],
                plan_tags={'strategy_id': self.strategy_id},
            )

        # Pick target policy as the one with most candidates among valid policies
        target_policy_ocid = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]
        target_candidate_count = counts[target_policy_ocid]
        logger.info(
            'build_plan: target_policy_ocid=%s chosen (%d candidates); counts=%s',
            target_policy_ocid,
            target_candidate_count,
            dict(counts),
        )

        # Group candidates by source policy
        candidates_by_policy: dict[str, list[str]] = {}
        for iid in effective_candidates:
            pol = st_idx[iid].get('policy_ocid') or ''
            if not pol:
                continue
            candidates_by_policy.setdefault(pol, []).append(iid)

        # Build plan steps: modify target + modify/delete sources
        steps: list[PlanStep] = []
        plan_tag_val_target = f'{plan_id}:target'
        target_policy = policies_by_ocid.get(target_policy_ocid, {})
        target_comp_path = _resolve_policy_compartment_path(target_policy, compartments)
        logger.debug(
            'build_plan: target_comp_path=%r (resolved from target policy)',
            target_comp_path or '(empty)',
        )

        # Target before/after statements; rewrite location when moving to a different compartment
        target_before = _policy_statement_texts(repo, target_policy_ocid)
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
                rewritten, note = _rewrite_statement_location_for_target(raw, st, target_comp_path)
                moved_texts.append(rewritten)
                if note:
                    location_change_notes.append(note)
        # De-dup moved statements while preserving order (keep first occurrence and its notes are already collected)
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

        # Tags: preserve existing tag maps, add marker
        ff, dd = _policy_tag_maps(target_policy)
        ff_after = dict(ff)
        ff_after[tag_key] = plan_tag_val_target

        step_id = f'{plan_id}-01-target'
        step_payload: PlanStep = {
            'step_id': step_id,
            'action': 'modify',
            'policy_ocid': target_policy_ocid,
            'before_statements': target_before,
            'after_statements': target_after,
            'before_tags': {**ff, **_flatten_defined_tags(dd)},
            'after_tags': {**ff_after, **_flatten_defined_tags(dd)},
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
            logger.debug(
                'build_plan: target step has %d location_change_notes (statement location rewrites)',
                len(location_change_notes),
            )
        steps.append(step_payload)

        # Source policies: remove moved statements; if empty -> delete
        step_n = 2
        for src_policy_ocid, src_iids in sorted(candidates_by_policy.items()):
            if src_policy_ocid == target_policy_ocid:
                continue
            src_before = _policy_statement_texts(repo, src_policy_ocid)
            to_remove = []
            for iid in src_iids:
                txt = st_idx[iid].get('statement_text', '').strip()
                if txt:
                    to_remove.append(txt)
            src_after = [t for t in src_before if t not in set(to_remove)]

            src_policy = policies_by_ocid.get(src_policy_ocid, {})
            ff_s, dd_s = _policy_tag_maps(src_policy)
            ff_s_after = dict(ff_s)
            plan_tag_val = f'{plan_id}:s{step_n:02d}'
            ff_s_after[tag_key] = plan_tag_val

            if len(src_after) == 0:
                # Delete policy step (proof of execution is policy absence)
                steps.append(
                    PlanStep(
                        step_id=f'{plan_id}-{step_n:02d}-delete',
                        action='delete',
                        policy_ocid=src_policy_ocid,
                        before_statements=src_before,
                        after_statements=[],
                        before_tags={**ff_s, **_flatten_defined_tags(dd_s)},
                        after_tags={},
                        plan_tags={
                            'marker_tag_key': tag_key,
                            'marker_tag_value': plan_tag_val,
                            'dataset_version': dataset_version or '',
                        },
                        executed=False,
                        execution_status='PENDING',
                        rollback_command='',
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
                        before_tags={**ff_s, **_flatten_defined_tags(dd_s)},
                        after_tags={**ff_s_after, **_flatten_defined_tags(dd_s)},
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
            corpus_id=corpus_id,
            plan_label=f'{self.display_name} ({len(effective_candidates)} candidates)',
            created_at=_now_iso(),
            plan_steps=steps,
            plan_tags={
                'strategy_id': self.strategy_id,
                'marker_tag_key': tag_key,
                'dataset_version': dataset_version or '',
            },
        )


class ConsolidationEngine:
    """
    Middle-tier consolidation engine.

    Instantiated early (UI startup) with cache and reference data. A PolicyAnalysisRepository
    is bound via :meth:`bind_policy_repo` once the App creates it; the repository is populated
    later via tenancy load or cache load.
    """

    def __init__(
        self,
        *,
        cache_mgr: CacheManager,
        reference_data_repo: ReferenceDataRepo,
        policy_repo: PolicyAnalysisRepository | None = None,
        strategies: list[Strategy] | None = None,
    ):
        """Initialize the consolidation engine.

        Args:
            cache_mgr: Cache manager for plan history and protected sets.
            reference_data_repo: Reference data repository (e.g. for strategy lookups).
            policy_repo: Optional policy repository; can be bound later with bind_policy_repo.
            strategies: Optional list of Strategy implementations. If None, uses built-in default(s).
        """
        self.cache_mgr = cache_mgr
        self.reference_data_repo = reference_data_repo
        self.policy_repo = policy_repo

        # Pluggable strategies: use provided list or default built-in(s).
        strategies = strategies if strategies is not None else [PackPoliciesByStatementDensity()]
        self._strategies: dict[str, Strategy] = {}
        self._strategies_by_id: dict[str, Strategy] = {}
        for s in strategies:
            self._strategies[s.display_name] = s
            self._strategies_by_id[s.strategy_id] = s
        logger.info(
            'ConsolidationEngine initialized with strategies: %s',
            list(self._strategies.keys()),
        )

    def register_strategy(self, strategy: Strategy) -> None:
        """Register a single consolidation strategy (pluggable).

        Args:
            strategy: Strategy instance implementing the Strategy protocol.
        """
        self._strategies[strategy.display_name] = strategy
        self._strategies_by_id[strategy.strategy_id] = strategy
        logger.debug('Registered consolidation strategy: %s', strategy.display_name)

    def register_strategies(self, strategies: list[Strategy]) -> None:
        """Register multiple consolidation strategies.

        Args:
            strategies: List of Strategy instances.
        """
        for s in strategies:
            self.register_strategy(s)

    def get_strategy_display_names(self) -> list[str]:
        """Return display names of all registered strategies (for UI dropdown, etc.).

        Returns:
            List of display_name strings in registration order (insertion order).
        """
        # Preserve order; dict is insertion-ordered in Python 3.7+
        return list(self._strategies.keys())

    def bind_policy_repo(self, repo: PolicyAnalysisRepository) -> None:
        """Attach the policy repository used for plan generation and rendering.

        Args:
            repo: The policy/compartment repository (e.g. policy_compartment_analysis).
        """
        self.policy_repo = repo

    def detect_source_type(self) -> SourceType:
        """Detect whether repo data is from live tenancy, cache, or compliance output.

        Returns:
            One of "live", "cache", "compliance", or "unknown".
        """
        repo = self.policy_repo
        if not repo:
            return 'unknown'
        if getattr(repo, 'loaded_from_compliance_output', False):
            return 'compliance'
        if getattr(repo, 'policies_loaded_from_tenancy', False) and getattr(
            repo, 'identity_loaded_from_tenancy', False
        ):
            return 'live'
        # cache loads tend to set data_as_of and tenancy_ocid but not the *_loaded_from_tenancy flags
        if getattr(repo, 'data_as_of', None):
            return 'cache'
        return 'unknown'

    def corpus_id(self) -> str | None:
        """Return tenancy or corpus id from the bound repo.

        Returns:
            Tenancy OCID string if repo is bound and has tenancy_ocid, else None.
        """
        repo = self.policy_repo
        if repo and getattr(repo, 'tenancy_ocid', None):
            return str(repo.tenancy_ocid)
        return None

    def dataset_version(self) -> str | None:
        """Return dataset version or data_as_of from the bound repo.

        Returns:
            Version string (e.g. timestamp) if repo has data_as_of, else None.
        """
        repo = self.policy_repo
        if repo and getattr(repo, 'data_as_of', None):
            return str(repo.data_as_of)
        return None

    # ---- Plan Generation ----

    def generate_plan(
        self,
        *,
        candidate_internal_ids: set[str],
        protected_internal_ids: set[str],
        strategy_display_name: str,
        params: dict[str, object] | None = None,
    ) -> ConsolidationPlan:
        """Build a consolidation plan for the given candidates and strategy.

        Args:
            candidate_internal_ids: Set of statement internal_ids to consolidate.
            protected_internal_ids: Set of statement internal_ids to exclude from consolidation.
            strategy_display_name: Display name of the strategy (e.g. "Statement Density (Pack Policies)").
            params: Optional strategy params (e.g. marker_tag_key).

        Returns:
            A ConsolidationPlan with plan_id, plan_steps, and plan_tags.

        Raises:
            RuntimeError: If policy repo is not bound or corpus_id is missing.
            ValueError: If strategy_display_name does not match any registered strategy.
        """
        if not self.policy_repo:
            raise RuntimeError('Policy repository not bound.')
        corpus_id = self.corpus_id()
        if not corpus_id:
            raise RuntimeError('No corpus_id/tenancy_ocid available.')
        source_type = self.detect_source_type()
        plan_id = self._new_plan_id(corpus_id, candidate_internal_ids, strategy_display_name)

        logger.info(
            'Generating consolidation plan: corpus_id=%s, source_type=%s, strategy=%s, candidates=%d, protected=%d, plan_id=%s',
            corpus_id,
            source_type,
            strategy_display_name,
            len(candidate_internal_ids),
            len(protected_internal_ids),
            plan_id,
        )

        # Resolve strategy name in a robust way:
        strat = self._strategies.get(strategy_display_name)
        if not strat:
            # Match by internal id or prefix (e.g. "Statement Density")
            strat = self._strategies_by_id.get(strategy_display_name)
        if not strat:
            for candidate in self._strategies.values():
                base_label = candidate.display_name.split(' (', 1)[0].strip().lower()
                if strategy_display_name.strip().lower().startswith(base_label):
                    strat = candidate
                    logger.info(
                        "Resolved strategy display name '%s' to '%s' (id=%s)",
                        strategy_display_name,
                        candidate.display_name,
                        candidate.strategy_id,
                    )
                    break
        if not strat:
            logger.warning(
                "Unknown strategy '%s'. Available display names: %s",
                strategy_display_name,
                list(self._strategies.keys()),
            )
            raise ValueError(f'Unknown strategy: {strategy_display_name}')

        plan = strat.build_plan(
            repo=self.policy_repo,
            corpus_id=corpus_id,
            dataset_version=self.dataset_version(),
            candidate_internal_ids=set(candidate_internal_ids),
            protected_internal_ids=set(protected_internal_ids),
            plan_id=plan_id,
            params=params,
        )
        logger.info(
            'generate_plan: strategy returned plan_id=%s, steps=%d, label=%s',
            plan.get('plan_id'),
            len(plan.get('plan_steps', [])),
            plan.get('plan_label', ''),
        )
        return plan

    def _new_plan_id(self, corpus_id: str, candidate_ids: set[str], strategy: str) -> str:
        """Generate a stable-ish plan id from corpus suffix, timestamp, and strategy hash."""
        ts = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        return f'{corpus_id[-6:]}-{ts}-{abs(hash(strategy)) % 10000:04d}'

    # ---- Rendering (execution + rollback) ----

    def render_plan_commands(self, plan: ConsolidationPlan) -> str:
        """Render CLI-oriented execution steps for the plan (no rollback hints).

        Produces shell commands (oci iam policy update/delete) for administrators to run
        manually. Rollback hints for delete steps appear only in the rollback section
        (see render_plan_rollback_commands). The tool does not execute these commands.

        Args:
            plan: The consolidation plan to render.

        Returns:
            Multiline string of commented and executable CLI lines, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        lines: list[str] = []
        lines.append(f"# Consolidation plan: {plan.get('plan_id')} | {plan.get('plan_label')}")
        lines.append(
            f"# Corpus: {plan.get('corpus_id')} | Dataset: {self.dataset_version() or 'n/a'} | Source: {self.detect_source_type()}"
        )
        version_date = datetime.now(UTC).strftime('%Y-%m-%d')
        lines.append('#')
        for step in plan.get('plan_steps', []):
            pol = policies_by_ocid.get(step.get('policy_ocid', ''), {})
            pol_name = pol.get('policy_name', '(unknown)')
            marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
            marker_val = (step.get('plan_tags') or {}).get('marker_tag_value', '')

            lines.append(
                f"## {step.get('step_id')} | {step.get('action').upper()} | {pol_name} ({step.get('policy_ocid')})"
            )
            for loc_note in step.get('location_change_notes') or []:
                lines.append(f'# {loc_note}')
            if step.get('action') == 'modify':
                ff, dd = _policy_tag_maps(pol)
                ff2 = dict(ff)
                if marker_val:
                    ff2[str(marker_key)] = str(marker_val)
                lines.append('# Update policy statements and mark step via freeform tag.')
                lines.append('# NOTE: OCI CLI updates replace the full statements list; this is intentional.')
                stmt_val = _statements_cli_value(step.get('after_statements', []))
                ff2_val = _shell_escape_single_quoted(_json_compact(ff2))
                lines.append('oci iam policy update \\')
                lines.append(f"  --policy-id {step.get('policy_ocid')} \\")
                lines.append(f'  --statements "{stmt_val}" \\')
                lines.append(f'  --version-date {version_date} \\')
                lines.append(f"  --freeform-tags '{ff2_val}' \\")
                if dd:
                    dd_val = _shell_escape_single_quoted(_json_compact(dd))
                    lines.append(f"  --defined-tags '{dd_val}' \\")
                lines.append('  --force')
            elif step.get('action') == 'delete':
                lines.append('# Delete policy. Execution proof is policy absence on reload.')
                lines.append(f"oci iam policy delete --policy-id {step.get('policy_ocid')} --force")
                # Rollback (re-create policy) appears only in Rollback / Both section, not in Execution-only output.
            else:
                lines.append('# (unsupported action)')
            lines.append('')
        return '\n'.join(lines).strip()

    def render_plan_ui_instructions(  # noqa: C901
        self, plan: ConsolidationPlan, section: Literal['all', 'execution', 'rollback'] = 'all'
    ) -> str:
        """Render step-by-step UI instructions for the OCI Console.

        Produces human-readable steps for Identity & Security > Identity > Policies,
        including compartment navigation and location-change notes. Rollback block
        is included when section is "all" or "rollback".

        Args:
            plan: The consolidation plan to render.
            section: "execution" (steps only), "rollback" (rollback only), or "all" (both). Default "all".

        Returns:
            Multiline string of instructions, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        def _compartment_nav_path(comp_path: str | None) -> str:
            if not comp_path or not comp_path.strip():
                return ''
            return ' / '.join(comp_path.strip().split('/'))

        lines: list[str] = []
        lines.append(f"Consolidation plan: {plan.get('plan_id')} | {plan.get('plan_label')}")
        lines.append(f"Corpus: {plan.get('corpus_id')} | Source: {self.detect_source_type()}")
        lines.append('')

        if section in ('all', 'execution'):
            lines.append('--- EXECUTION STEPS (OCI Console) ---')
            for i, step in enumerate(plan.get('plan_steps', []), 1):
                pol = policies_by_ocid.get(step.get('policy_ocid', ''), {})
                pol_name = pol.get('policy_name', '(unknown)')
                comp_path = pol.get('compartment_path') or ''
                nav_path = _compartment_nav_path(comp_path)
                marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
                marker_val = (step.get('plan_tags') or {}).get('marker_tag_value', '')

                lines.append(f"Step {i} [{step.get('step_id')}] — {step.get('action').upper()}: {pol_name}")
                for loc_note in step.get('location_change_notes') or []:
                    lines.append(f'  • {loc_note}')
                if nav_path:
                    lines.append(f'  • Navigate to compartment: {nav_path}')
                lines.append('  • In OCI Console: Identity & Security > Identity > Policies.')
                if step.get('action') == 'modify':
                    lines.append(f"  • Locate policy: {pol_name} (OCID: {step.get('policy_ocid')}).")
                    lines.append('  • Edit policy: set Statements to the following list (replace existing):')
                    for st in step.get('after_statements', [])[:20]:
                        lines.append(f'    - {st}')
                    if len(step.get('after_statements', [])) > 20:
                        lines.append(f"    ... and {len(step.get('after_statements', [])) - 20} more.")
                    lines.append(f'  • Add freeform tag: {marker_key} = {marker_val} (to mark step as executed).')
                    lines.append('  • Save the policy.')
                elif step.get('action') == 'delete':
                    lines.append(f"  • Locate policy: {pol_name} (OCID: {step.get('policy_ocid')}).")
                    lines.append(
                        '  • Delete the policy. Execution is confirmed when the policy no longer appears after reload.'
                    )
                lines.append('')

        if section in ('all', 'rollback'):
            lines.append(
                '--- ROLLBACK (if needed, reverse order) — statements and policy creation below are permanent ---'
            )
            for i, step in enumerate(reversed(plan.get('plan_steps', [])), 1):
                pol = policies_by_ocid.get(step.get('policy_ocid', ''), {})
                pol_name = pol.get('policy_name', '(unknown)')
                pol_comp = pol.get('compartment_ocid', '')
                comp_path = pol.get('compartment_path') or ''
                nav_path = _compartment_nav_path(comp_path)
                r_marker_key = (step.get('plan_tags') or {}).get('marker_tag_key', 'opa_consolidation')
                lines.append(f"Rollback step {i}: {step.get('action').upper()} — {pol_name}")
                if nav_path:
                    lines.append(f'  • Navigate to compartment: {nav_path}')
                if step.get('action') == 'modify':
                    lines.append(
                        f"  • Edit policy {pol_name} (OCID: {step.get('policy_ocid')}) and restore the original statements below; remove freeform tag {r_marker_key}."
                    )
                    lines.append(f"  • Original statements to restore ({len(step.get('before_statements', []))}):")
                    for st in step.get('before_statements', []):
                        lines.append(f'    - {st}')
                elif step.get('action') == 'delete':
                    lines.append(
                        f"  • Re-create policy in compartment {pol_comp or '(unknown)'} (path: {nav_path or 'n/a'}) with name: {pol_name}"
                    )
                    lines.append(f"  • Statements to set ({len(step.get('before_statements', []))}):")
                    for st in step.get('before_statements', []):
                        lines.append(f'    - {st}')
                    if pol.get('description'):
                        lines.append(f"  • Description: {pol.get('description')}")
                lines.append('')
        return '\n'.join(lines).strip()

    def render_plan_rollback_commands(self, plan: ConsolidationPlan) -> str:
        """Render CLI rollback commands for the plan (reverse order; re-create for deletes).

        Produces oci iam policy update/create commands to undo the plan. Shown in the
        Proposed Script area when the user selects "Rollback" or "Both". Execution-only
        view does not include these.

        Args:
            plan: The consolidation plan to render rollback for.

        Returns:
            Multiline string of commented and executable CLI lines, or "(no repo bound)" if repo not set.
        """
        if not self.policy_repo:
            return '(no repo bound)'
        repo = self.policy_repo
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        lines: list[str] = []
        version_date = datetime.now(UTC).strftime('%Y-%m-%d')
        lines.append(f"# Rollback commands for plan: {plan.get('plan_id')}")
        lines.append('# WARNING: Only safe if no newer plan has executed.')
        lines.append('')
        # Reverse order is typically safer
        for step in reversed(plan.get('plan_steps', [])):
            pol = policies_by_ocid.get(step.get('policy_ocid', ''), {})
            pol_name = pol.get('policy_name', '(unknown)')
            pol_comp = pol.get('compartment_ocid', '')

            lines.append(
                f"## ROLLBACK {step.get('step_id')} | {step.get('action').upper()} | {pol_name} ({step.get('policy_ocid')})"
            )
            if step.get('action') == 'modify':
                ff, dd = _policy_tag_maps(pol)
                stmt_val = _statements_cli_value(step.get('before_statements', []))
                lines.append('oci iam policy update \\')
                lines.append(f"  --policy-id {step.get('policy_ocid')} \\")
                lines.append(f'  --statements "{stmt_val}" \\')
                lines.append(f'  --version-date {version_date} \\')
                if ff:
                    lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff))}' \\")
                if dd:
                    lines.append(f"  --defined-tags '{_shell_escape_single_quoted(_json_compact(dd))}' \\")
                lines.append('  --force')
            elif step.get('action') == 'delete':
                # rollback is recreate
                if pol_comp and pol_name:
                    ff, dd = _policy_tag_maps(pol)
                    stmt_val = _statements_cli_value(step.get('before_statements', []))
                    name_esc = _shell_escape_single_quoted(pol_name)
                    desc_esc = _shell_escape_single_quoted(pol.get('description') or '')
                    lines.append('oci iam policy create \\')
                    lines.append(f'  --compartment-id {pol_comp} \\')
                    lines.append(f"  --name '{name_esc}' \\")
                    lines.append(f"  --description '{desc_esc}' \\")
                    lines.append(f'  --statements "{stmt_val}" \\')
                    if ff:
                        lines.append(f"  --freeform-tags '{_shell_escape_single_quoted(_json_compact(ff))}' \\")
                    if dd:
                        lines.append(f"  --defined-tags '{_shell_escape_single_quoted(_json_compact(dd))}' \\")
                    lines.append('  --force')
                else:
                    lines.append('# Cannot rollback delete: missing policy compartment/name metadata.')
            lines.append('')
        return '\n'.join(lines).strip()

    # ---- Execution Check (after reload) ----

    def check_plan_progress(self, plan: ConsolidationPlan) -> dict[str, dict[str, object]]:
        """Inspect current repo state to estimate execution progress per step.

        Uses policy presence (for delete steps) and marker tag presence (for modify steps)
        to determine which steps have been applied. Call after reloading policy data.

        Args:
            plan: The consolidation plan to check.

        Returns:
            Dict mapping step_id to a dict with keys such as executed (bool), notes (str),
            policy_ocid, action, checked_at.

        Raises:
            RuntimeError: If policy repository is not bound.
        """
        if not self.policy_repo:
            raise RuntimeError('Policy repository not bound.')

        repo = self.policy_repo
        current_policy_ocids = {
            p.get('policy_ocid') for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }
        policies_by_ocid: dict[str, BasePolicy] = {
            p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
        }

        results: dict[str, dict[str, object]] = {}
        for step in plan.get('plan_steps', []):
            step_id = step.get('step_id', '')
            pol_ocid = step.get('policy_ocid', '')
            action = step.get('action', '')
            plan_tags = step.get('plan_tags') or {}
            marker_key = str(plan_tags.get('marker_tag_key') or 'opa_consolidation')
            marker_val = str(plan_tags.get('marker_tag_value') or '')

            executed = False
            notes = ''
            if action == 'delete':
                executed = pol_ocid not in current_policy_ocids
                notes = 'policy missing' if executed else 'policy still present'
            elif action == 'modify':
                pol = policies_by_ocid.get(pol_ocid, {})
                ff, _dd = _policy_tag_maps(pol)
                if marker_val and ff.get(marker_key) == marker_val:
                    executed = True
                    notes = f'marker tag present ({marker_key}={marker_val})'
                else:
                    notes = f'marker tag missing or mismatch ({marker_key})'
            else:
                notes = 'unsupported action'

            results[step_id] = {
                'policy_ocid': pol_ocid,
                'action': action,
                'executed': executed,
                'notes': notes,
                'checked_at': _now_iso(),
            }
        return results

    def get_plan_tag_conflicts(
        self,
        plan: ConsolidationPlan,
        policies_by_ocid: dict[str, BasePolicy] | None = None,
    ) -> list[dict[str, str]]:
        """
        Check if any policy in this plan has an opa_consolidation (marker) tag from a different plan.

        When multiple plans exist, a policy may already be tagged by another plan. If so, this plan
        is considered invalid/conflicted for execution until the situation is resolved. Works with
        any data source (live, cache, compliance); for static sources the result reflects the
        snapshot.

        Args:
            plan: The consolidation plan to check.
            policies_by_ocid: Optional map policy_ocid -> policy; if None, built from bound repo.

        Returns:
            List of dicts with keys policy_ocid, current_tag_value, conflicting_plan_id.
            Empty if no conflicts.
        """
        repo = self.policy_repo
        if not repo:
            return []
        if policies_by_ocid is None:
            policies_by_ocid = {
                p.get('policy_ocid'): p for p in (getattr(repo, 'policies', []) or []) if p.get('policy_ocid')
            }
        plan_id = (plan.get('plan_id') or '').strip()
        plan_tags = plan.get('plan_tags') or {}
        marker_key = str(plan_tags.get('marker_tag_key') or 'opa_consolidation')
        conflicts: list[dict[str, str]] = []
        for step in plan.get('plan_steps', []):
            pol_ocid = (step.get('policy_ocid') or '').strip()
            if not pol_ocid:
                continue
            step_plan_tags = step.get('plan_tags') or {}
            step_marker_key = str(step_plan_tags.get('marker_tag_key') or marker_key)
            pol = policies_by_ocid.get(pol_ocid, {})
            ff, _ = _policy_tag_maps(pol)
            current_val = (ff.get(step_marker_key) or '').strip()
            if not current_val:
                continue
            # Value is "plan_id:target" or "plan_id:s02"; prefix is the plan that set it
            prefix = current_val.split(':')[0].strip() if ':' in current_val else current_val
            if prefix and prefix != plan_id:
                conflicts.append(
                    {
                        'policy_ocid': pol_ocid,
                        'current_tag_value': current_val,
                        'conflicting_plan_id': prefix,
                    }
                )
        return conflicts
