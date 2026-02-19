##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# consolidation_helpers.py – Shared helpers for consolidation plan building and location rewrite.
# Used by ConsolidationEngine and by strategy implementations (e.g. statement_density, move_to_root).
# Supports Python 3.12 and above
# coding: utf-8
##########################################################################

from __future__ import annotations

import re
from datetime import UTC, datetime

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy, RegularPolicyStatement
from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

logger = get_logger(component='consolidation_helpers')


def now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def flatten_defined_tags(defined_tags: dict | None) -> dict[str, str]:
    """Flatten OCI defined tags into UI-friendly key space 'namespace:key'. Not reversible; display only."""
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


def policy_tag_maps(policy: BasePolicy) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return (freeform_tags, defined_tags) as separate maps. Falls back to empty maps if absent."""
    freeform = policy.get('freeform_tags') or {}
    defined = policy.get('defined_tags') or {}
    if not isinstance(freeform, dict):
        freeform = {}
    if not isinstance(defined, dict):
        defined = {}
    defined2: dict[str, dict[str, str]] = {}
    for ns, val in defined.items():
        if isinstance(val, dict):
            defined2[str(ns)] = {str(k): str(v) for k, v in val.items()}
    return {str(k): str(v) for k, v in freeform.items()}, defined2


def policy_statement_texts(repo: PolicyAnalysisRepository, policy_ocid: str) -> list[str]:
    """Return raw statement_text list for all regular statements in a policy."""
    out: list[str] = []
    for st in getattr(repo, 'regular_statements', []) or []:
        if st.get('policy_ocid') == policy_ocid:
            txt = st.get('statement_text')
            if isinstance(txt, str) and txt.strip():
                out.append(txt.strip())
    return out


def internal_id_to_statement(repo: PolicyAnalysisRepository) -> dict[str, RegularPolicyStatement]:
    """Build a map of statement internal_id -> statement dict for lookups."""
    idx: dict[str, RegularPolicyStatement] = {}
    for st in getattr(repo, 'regular_statements', []) or []:
        iid = st.get('internal_id')
        if isinstance(iid, str) and iid and iid not in idx:
            idx[iid] = st
    return idx


def statement_scope_compartment_ocid(st: RegularPolicyStatement, tenancy_ocid: str) -> str:
    """OCI rule: statement cannot live in a policy below its scope. Returns compartment OCID for this statement's scope."""
    if st.get('location_type') == 'tenancy':
        return tenancy_ocid
    eff = st.get('effective_compartment_ocid')
    if eff:
        return eff
    return st.get('compartment_ocid') or tenancy_ocid


def compartment_ancestors_including_self(compartment_ocid: str, compartments: list[dict]) -> set[str]:
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


def lca_compartment_ocids(ocids: set[str], compartments: list[dict], tenancy_ocid: str) -> str:
    """Least common ancestor of the given compartment OCIDs. Policy containing these scopes must live here or an ancestor."""
    if not ocids:
        logger.debug('lca_compartment_ocids: no ocids, returning tenancy_ocid=%s', tenancy_ocid)
        return tenancy_ocid
    if tenancy_ocid in ocids:
        logger.debug('lca_compartment_ocids: tenancy in scope, returning tenancy_ocid=%s', tenancy_ocid)
        return tenancy_ocid
    by_id = {c.get('id'): c for c in compartments if c.get('id')}
    ancestor_sets = [compartment_ancestors_including_self(ocid, compartments) for ocid in ocids]
    common = ancestor_sets[0]
    for s in ancestor_sets[1:]:
        common &= s
    if not common:
        return tenancy_ocid

    def depth(ocid: str) -> int:
        path = (by_id.get(ocid) or {}).get('hierarchy_path') or ''
        return len(path.split('/'))

    result = max(common, key=depth)
    logger.debug('lca_compartment_ocids: common=%s -> LCA ocid=%s (depth %d)', common, result, depth(result))
    return result


def normalize_compartment_path_segments(path: str) -> list[str]:
    """Split compartment path into segments (e.g. ROOT/A/B -> ['ROOT','A','B']). Preserves case."""
    if not path or not path.strip():
        return []
    return [p.strip() for p in path.replace('\\', '/').split('/') if p.strip()]


def resolve_policy_compartment_path(policy: BasePolicy, compartments: list) -> str:
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


def is_root_path(segments: list[str]) -> bool:
    """True if segments represent tenancy root (empty or single segment ROOT/root)."""
    if not segments:
        return True
    if len(segments) == 1 and segments[0].upper() == 'ROOT':
        return True
    return False


def effective_path_segments_for_rewrite(st: RegularPolicyStatement, old_location: str) -> list[str]:
    """Resolve effective path as segments from the statement. Prefer st.effective_path; else build from compartment_path + location."""
    eff_path = (st.get('effective_path') or '').strip()
    comp_path = (st.get('compartment_path') or '').strip()
    loc = (st.get('location') or '').strip() or old_location
    if eff_path:
        segs = normalize_compartment_path_segments(eff_path)
        logger.debug('[location rewrite] effective_path from st: %r -> segments %s', eff_path, segs)
        return segs
    comp_segments = normalize_compartment_path_segments(comp_path)
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


def rewrite_statement_location_for_target(  # noqa: C901
    statement_text: str,
    st: RegularPolicyStatement,
    target_comp_path: str,
) -> tuple[str, str | None]:
    """
    Rewrite the "in compartment X" part of a statement when it is moved to a policy at target_comp_path.
    Effective path does not change; returns (rewritten_text, note_or_none).
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
    if not statement_text or not statement_text.strip():
        logger.debug('[location rewrite] SKIP: empty statement')
        return statement_text, None
    text_lower = statement_text.lower()
    if 'in tenancy' in text_lower and 'in compartment' not in text_lower:
        logger.debug('[location rewrite] SKIP: statement is tenancy-scoped (no compartment location)')
        return statement_text, None
    target_segments = normalize_compartment_path_segments(target_comp_path or '')
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
    effective_segments = effective_path_segments_for_rewrite(st, old_location)
    if not effective_segments:
        logger.debug('[location rewrite] SKIP: could not resolve effective path segments from statement')
        return statement_text, None

    source_segments = normalize_compartment_path_segments(source_comp_path or '')
    if source_segments == target_segments:
        logger.debug('[location rewrite] SKIP: source and target path identical')
        return statement_text, None

    if is_root_path(target_segments):
        if effective_segments and effective_segments[0].upper() == 'ROOT':
            remainder = effective_segments[1:]
        else:
            remainder = effective_segments
    else:
        tlen = len(target_segments)
        eff_prefix = [s.upper() for s in effective_segments[:tlen]]
        tgt_upper = [s.upper() for s in target_segments]
        if eff_prefix == tgt_upper and len(effective_segments) >= tlen:
            remainder = effective_segments[tlen:]
        else:
            remainder = effective_segments

    new_location = ':'.join(remainder) if remainder else old_location
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


def required_policy_compartment_for_candidates(
    repo: PolicyAnalysisRepository,
    candidate_internal_ids: list[str],
    st_idx: dict[str, RegularPolicyStatement],
) -> str:
    """Highest compartment in the tenancy where a policy can legally contain all candidate statements."""
    tenancy_ocid = getattr(repo, 'tenancy_ocid', None) or ''
    compartments = getattr(repo, 'compartments', []) or []
    scope_ocids: set[str] = set()
    for iid in candidate_internal_ids:
        st = st_idx.get(iid)
        if st:
            scope_ocids.add(statement_scope_compartment_ocid(st, tenancy_ocid))
    logger.debug(
        'required_policy_compartment_for_candidates: %d candidates -> scope_ocids=%s, compartments=%d',
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
        logger.debug('required_policy_compartment_for_candidates: no hierarchy, required_ocid=%s', result)
        return result
    result = lca_compartment_ocids(scope_ocids, compartments, tenancy_ocid)
    logger.info('Required policy compartment (LCA of candidate scopes): %s', result)
    return result
