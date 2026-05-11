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

from oci_policy_analysis.application.core.repo import PolicyAnalysisRepository
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import BasePolicy, RegularPolicyStatement

logger = get_logger(component='core.engine.consolidation_helpers')


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


def lca_path(paths: list[list[str]]) -> list[str]:
    """
    Find the longest common ancestor path among a list of path lists.
    For example, [['ROOT','A','B'], ['ROOT','A','C']] => ['ROOT','A']
    Returns the shared prefix as a list; returns empty list if none.
    Logs info about all paths and details of the comparison at each level.
    """
    logger.info('lca_path: INPUT paths:')
    for idx, p in enumerate(paths):
        logger.info('  path[%d] = %r', idx, p)
    if not paths:
        logger.info('lca_path: received empty list of paths, returning [].')
        return []
    min_len = min(len(p) for p in paths)
    res = []
    for i in range(min_len):
        ith_elements = [p[i] for p in paths]
        unique = set(ith_elements)
        logger.info('  lca_path: at index %d, values=%r', i, ith_elements)
        if len(unique) == 1:
            res.append(list(unique)[0])
            logger.info('    All values matched (%r), appended to result.', list(unique)[0])
        else:
            logger.info('    Divergence at index %d, found differing values %r; stopping.', i, unique)
            break
    logger.info('lca_path: FINAL result=%r', res)
    return res


def find_compartment_by_hierarchy_path(path: str, compartments: list[dict]) -> dict | None:
    """
    Looks up a compartment dict by case-insensitive match on hierarchy_path string.
    Example: path='ROOT/department/foo'
    Returns the compartment dict if found, else None.
    """
    for c in compartments:
        hpath = c.get('hierarchy_path') or ''
        if hpath and hpath.lower() == path.lower():
            logger.debug('find_compartment_by_hierarchy_path: found %r for path=%r', c.get('id'), path)
            return c
    logger.debug('find_compartment_by_hierarchy_path: not found for path=%r', path)
    return None


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
    comp_segments = normalize_compartment_path_segments(comp_path)

    def _merge_compartment_and_location_segments(comp: list[str], location: str) -> list[str]:
        if not location:
            return list(comp)
        loc_segments = [p.strip() for p in location.split(':') if p.strip()]
        if not loc_segments:
            return list(comp)
        # Avoid duplicated boundary segments: ROOT/X/Y + location Y:Z -> ROOT/X/Y/Z
        max_overlap = min(len(comp), len(loc_segments))
        overlap = 0
        for k in range(max_overlap, 0, -1):
            if comp[-k:] == loc_segments[:k]:
                overlap = k
                break
        return list(comp) + loc_segments[overlap:]

    if eff_path:
        segs = normalize_compartment_path_segments(eff_path)
        logger.debug('[location rewrite] effective_path from st: %r -> segments %s', eff_path, segs)
        # If effective_path is less specific than compartment_path + location,
        # prefer derived segments so move-to-root keeps full location detail.
        derived = _merge_compartment_and_location_segments(comp_segments, loc)
        if len(derived) > len(segs) and (not segs or derived[: len(segs)] == segs):
            logger.info(
                '[location rewrite] effective_path=%r was less specific; using derived path from compartment_path=%r + location=%r -> %s',
                eff_path,
                comp_path or '(empty)',
                loc or '(empty)',
                derived,
            )
            return derived
        return segs
    if not comp_segments and not loc:
        logger.debug('[location rewrite] no effective_path, compartment_path, or location on statement')
        return []
    segs = _merge_compartment_and_location_segments(comp_segments, loc)
    logger.debug(
        '[location rewrite] effective_path derived from st.compartment_path=%r + location=%r -> segments %s',
        comp_path or '(empty)',
        loc or '(empty)',
        segs,
    )
    return segs


def rewritten_location_for_target(effective_path: list[str], target_comp_path: list[str]) -> str:
    """
    Computes new location for a policy statement when moving to a new policy compartment.

    Args:
        effective_path: List of strings, segments of the full effective path of the statement (e.g. ['ROOT','LZ1-Top','app']).
        target_comp_path: List of strings, segments of the target policy's compartment path (e.g. ['ROOT','LZ1-Top'])

    Returns:
        A string representing the new location (the remainder after removing target_comp_path from effective_path, joined with :)

    Notes:
    - No regex, no parsing of statement text is used.
    - If target_comp_path does not match the prefix of effective_path, returns original effective_path joined by ':'.
    """
    logger.info(
        'rewritten_location_for_target: effective_path=%r, target_comp_path=%r', effective_path, target_comp_path
    )
    eff_norm = [s.casefold() for s in effective_path]
    tgt_norm = [s.casefold() for s in target_comp_path]
    if eff_norm == tgt_norm:
        # If the only segment is ROOT or the path is empty, return ""
        if not effective_path or (len(effective_path) == 1 and effective_path[0].upper() == 'ROOT'):
            logger.info('  Paths exactly match ROOT or empty; returning empty string.')
            return ''
        logger.info('  Paths are an exact match (not ROOT); returning last segment: %r', effective_path[-1])
        return effective_path[-1]
    elif len(target_comp_path) <= len(effective_path) and eff_norm[: len(target_comp_path)] == tgt_norm:
        remainder = effective_path[len(target_comp_path) :]
        logger.info('  Remainder segments after stripping target prefix: %r', remainder)
        return ':'.join(remainder)
    logger.info('  Target compartment path does not match prefix; returning empty string.')
    return ''


def rewrite_statement_location_clause(
    statement_text: str,
    new_location: str,
    *,
    target_policy_path: str,
) -> tuple[str, str]:
    """Rewrite `in compartment <...>` clause and return rewritten text + audit note.

    If no location clause is found, the original text is returned unchanged while the
    note still documents the intended location rewrite.
    """
    raw = (statement_text or '').strip()
    if not raw:
        note = f'NOTE: location changed to {new_location} when moved to policy at {target_policy_path}.'
        return '', note

    match = re.search(r'\bin\s+compartment\s+([^\s]+)', raw, re.IGNORECASE)
    if match:
        prefix = raw[: match.start(1)]
        suffix = raw[match.end(1) :]
        rewritten = f'{prefix}{new_location}{suffix}'
    else:
        rewritten = raw

    note = f'NOTE: location changed to {new_location} when moved to policy at {target_policy_path}.'
    return rewritten, note


def trace_and_rewrite_candidate_statement_location(
    *,
    strategy_id: str,
    internal_id: str,
    statement: RegularPolicyStatement,
    statement_text: str,
    target_policy_path: str,
) -> tuple[str, str, list[str], list[str], str]:
    """Trace location derivation for one candidate and return rewrite artifacts.

    Returns:
        tuple: (rewritten_text, note, effective_segments, target_segments, new_location)
    """
    raw = (statement_text or '').strip()
    eff_segments = effective_path_segments_for_rewrite(statement, statement.get('location', ''))
    tgt_segments = normalize_compartment_path_segments(target_policy_path)
    new_location = rewritten_location_for_target(eff_segments, tgt_segments)
    rewritten, note = rewrite_statement_location_clause(
        raw,
        new_location,
        target_policy_path=target_policy_path,
    )
    logger.info(
        '[%s] candidate=%s | policy_compartment=%r | location=%r | effective_path=%r | target_policy_path=%r | new_location=%r',
        strategy_id,
        internal_id,
        statement.get('compartment_path', ''),
        statement.get('location', ''),
        statement.get('effective_path', ''),
        target_policy_path,
        new_location,
    )
    logger.debug(
        '[%s] candidate=%s details: effective_segments=%s target_segments=%s rewritten=%r note=%r',
        strategy_id,
        internal_id,
        eff_segments,
        tgt_segments,
        rewritten,
        note,
    )
    return rewritten, note, eff_segments, tgt_segments, new_location


# For maximum clarity, callers should compose/replace the location in the statement using this function.
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
