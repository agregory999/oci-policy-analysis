##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# mcp_server.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

# Defensive: ensure sys.stderr exists (PyInstaller edge case)
import inspect  # noqa: E402
import io  # noqa: E402
import sys

# ---- PATCH STDOUT/STDERR FOR UVICORN + PYINSTALLER ----
# This must run before any logging config is loaded by uvicorn.


class DummyStream(io.StringIO):
    def isatty(self):
        return False


# PyInstaller windowed application gives None for stdout/stderr
if sys.stdout is None:
    sys.stdout = DummyStream()

if sys.stderr is None:
    sys.stderr = DummyStream()
# -------------------------------------------------------

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any, Literal  # noqa: E402

from fastmcp import FastMCP  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from uvicorn import Server  # noqa: E402

from oci_policy_analysis.application.context import AppContext  # noqa: E402
from oci_policy_analysis.application.core.models.models_iam import (  # noqa: E402
    DynamicGroupSearch,
    Group,
    GroupSearch,
    User,
    UserSearch,
)
from oci_policy_analysis.application.core.models.models_policy import PolicySearch  # noqa: E402
from oci_policy_analysis.application.core.repo.policy_analysis_repository import (  # noqa: E402
    PolicyAnalysisRepository,
)
from oci_policy_analysis.application.core.support import config  # noqa: E402
from oci_policy_analysis.application.core.support.caching import CacheManager  # noqa: E402
from oci_policy_analysis.application.core.support.logger import get_logger, set_log_level  # noqa: E402
from oci_policy_analysis.application.services.load_service import LoadService  # noqa: E402
from oci_policy_analysis.application.services.mcp_query_service import MCPQueryService  # noqa: E402
from oci_policy_analysis.application.services.tag_based_policy_service import TagBasedPolicyService  # noqa: E402

try:  # usage tracking is optional when running embedded; ignore if unavailable
    from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker  # type: ignore[import]
except Exception:  # pragma: no cover - defensive fallback

    def get_usage_tracker():  # type: ignore[no-redef]
        return None


# Global logger for this module
logger = get_logger(component='mcp_server')

mcp = FastMCP(name='OCI Policy MCP')
app_context: AppContext | None = None

MCP_OUTPUT_LOG_LIMIT = 4000


CONFIDENCE_ORDER = {
    'exact': 5,
    'subject_match_with_conditions': 4,
    'identity_match_with_residual': 3,
    'rule_evidence': 2,
    'broad': 1,
    'ambiguous': 0,
    '': -1,
}

COMPARTMENT_OCID_RE = re.compile(
    r'ocid1\.compartment\.[A-Za-z0-9._-]+',
    re.IGNORECASE,
)


def _build_service_context(log_level: str) -> AppContext:
    """Create the service-backed application context used by standalone MCP."""

    settings = config.load_settings()
    settings['global_log_level'] = log_level
    return AppContext.from_settings(settings)


def _require_service_context() -> AppContext:
    """Return the active service context or raise a MCP tool error."""

    if app_context is None:
        raise ToolError('MCP service context is not initialized.')
    return app_context


def _query_service() -> MCPQueryService:
    """Return a query service bound to the active MCP application context."""

    return MCPQueryService(_require_service_context())


# ===========================================================
# TOOL REGISTRY FOR UI (Embedded MCP Tab)
# ===========================================================

_REGISTERED_TOOLS: list[dict[str, Any]] = []


def _track_mcp_tool(tool_name: str, status: str = 'success', **extra: object) -> None:
    """Best-effort anonymous tracking for MCP tool calls.

    This is only active when the embedded MCP server is running inside the
    main desktop UI with usage tracking enabled. Standalone MCP runs either
    do not import ``get_usage_tracker`` or return ``None`` from it.

    ``status`` is a coarse outcome flag (e.g. ``success`` or ``error``).
    ``extra`` can include non-personal aggregates such as ``count`` for
    batch sizes. No policy text, OCIDs, or identity data should ever be
    passed here.
    """

    try:
        tracker = get_usage_tracker()
        if tracker is None:
            return
        payload: dict[str, object] = {'tool_name': tool_name, 'status': status}
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        tracker.track_operation('mcp_tool', **payload)
    except Exception:
        logger.debug('Usage tracking for mcp_tool.%s (%s) failed', tool_name, status, exc_info=True)


def _json_for_log(payload: object) -> str:
    """Serialize a MCP payload for INFO-level call logging."""

    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def _truncate_log_text(text: str, limit: int = MCP_OUTPUT_LOG_LIMIT) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f'{text[:limit]}... <truncated {omitted} chars>'


def _log_mcp_call_input(tool_name: str, inputs: dict[str, Any]) -> None:
    if logger.isEnabledFor(logging.INFO):
        logger.info('MCP call %s input(full)=%s', tool_name, _json_for_log(inputs))


def _log_mcp_call_output(tool_name: str, output: object) -> object:
    if logger.isEnabledFor(logging.INFO):
        logger.info('MCP call %s output(truncated)=%s', tool_name, _truncate_log_text(_json_for_log(output)))
    return output


def _normalize_policy_statement_for_mcp(stmt: dict) -> dict:
    """Return a MCP-safe copy of a policy statement.

    For any-user/any-group subjects, clear the subject list so that the
    JSON output always uses an array type for ``subject`` even when the
    underlying repository uses a simple string like "any-user".

    Semantics for these special subjects are conveyed via ``subject_type``;
    MCP consumers should rely on that field rather than the ``subject``
    contents. This helper is intentionally scoped to MCP output only and
    does not mutate the underlying repository statements.
    """

    # Shallow copy to avoid mutating repository-backed dicts.
    st = dict(stmt)
    string_fields = (
        'policy_name',
        'policy_ocid',
        'compartment_ocid',
        'compartment_path',
        'statement_text',
        'creation_time',
        'internal_id',
        'action',
        'subject_type',
        'verb',
        'resource',
        'location_type',
        'location',
        'conditions',
        'comments',
        'confidence',
        'match_confidence',
        'match_confidence_reason',
        'effective_compartment_ocid',
        'effective_path',
    )
    list_string_fields = ('permission', 'invalid_reasons', 'parsing_notes', 'principal_keys')

    # Ensure core string fields never carry null values in MCP output.
    for field in string_fields:
        if field in st:
            value = st.get(field)
            st[field] = '' if value is None else str(value)

    # Ensure list[str] fields are consistently string-safe.
    for field in list_string_fields:
        if field in st:
            value = st.get(field)
            if isinstance(value, list):
                st[field] = ['' if item is None else str(item) for item in value]
            elif value is None:
                st[field] = []
            else:
                st[field] = [str(value)]

    # Normalize canonical principals list for strict MCP output validation.
    principals_value = st.get('principals')
    if isinstance(principals_value, list):
        normalized_principals = []
        for principal in principals_value:
            if not isinstance(principal, dict):
                continue
            normalized_principal = dict(principal)
            for key in ('principal_type', 'principal_key', 'domain_name', 'name', 'ocid', 'display_name'):
                if key in normalized_principal:
                    value = normalized_principal.get(key)
                    normalized_principal[key] = '' if value is None else str(value)
            normalized_principals.append(normalized_principal)
        st['principals'] = normalized_principals

    stype = st.get('subject_type')
    if stype in ('any-user', 'any-group'):
        # Ensure JSON schema expecting an array type for "subject" is satisfied
        # regardless of how the repo stored this field internally.
        st['subject'] = []
        logger.debug('_normalize_subject_for_mcp: normalized subject for subject_type=%s', stype)
    elif isinstance(st.get('subject'), list):
        # MCP validates JSON output strictly. Legacy subject tuples may include
        # a None domain marker; principals/principal_keys carry canonical identity
        # semantics, so keep this display-oriented field string-safe.
        normalized_subjects = []
        for entry in st.get('subject', []):
            if isinstance(entry, (list | tuple)):
                normalized_subjects.append(['' if value is None else str(value) for value in entry])
            else:
                normalized_subjects.append('' if entry is None else str(entry))
        st['subject'] = normalized_subjects
    return st


def _as_str_list(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split('|') if part.strip()]
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit if limit is not None else 50)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, 50))


def _principal_key_for_dynamic_group(dynamic_group: dict[str, Any]) -> str:
    domain = str(dynamic_group.get('domain_name') or 'Default').strip() or 'Default'
    name = str(dynamic_group.get('dynamic_group_name') or '').strip()
    return f'dynamic-group:{domain}/{name}' if name else ''


def _current_policy_repo() -> PolicyAnalysisRepository | None:
    """Return the active policy repository if one is available."""
    return getattr(app_context, 'policy_repo', None) if app_context is not None else None


def _normalize_compartment_path(path: object | None) -> str:
    text = str(path or '').replace('\\', '/').strip().strip('/')
    return text


def _compartment_path(compartment: dict[str, Any], repo: PolicyAnalysisRepository | None = None) -> str:
    path = compartment.get('hierarchy_path') or compartment.get('compartment_path') or ''
    if not path and repo is not None and compartment.get('id') == getattr(repo, 'tenancy_ocid', None):
        path = 'ROOT'
    return _normalize_compartment_path(path)


def _compartment_parent_path(
    compartment: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    repo: PolicyAnalysisRepository | None = None,
) -> str:
    parent_id = str(compartment.get('parent_id') or '')
    parent = by_id.get(parent_id)
    return _compartment_path(parent, repo) if parent else ''


def _format_compartment_for_mcp(
    compartment: dict[str, Any],
    *,
    repo: PolicyAnalysisRepository | None = None,
    by_id: dict[str, dict[str, Any]] | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a repository compartment for compact MCP responses."""

    by_id = by_id or {}
    path = _compartment_path(compartment, repo)
    row = {
        'name': str(compartment.get('name') or ''),
        'ocid': str(compartment.get('id') or compartment.get('ocid') or ''),
        'path': path,
        'effective_path': path.casefold() if path else '',
        'parent_ocid': str(compartment.get('parent_id') or ''),
        'parent_path': _compartment_parent_path(compartment, by_id, repo),
        'lifecycle_state': str(compartment.get('lifecycle_state') or ''),
        'description': str(compartment.get('description') or ''),
        'statement_count_direct': int(compartment.get('statement_count_direct') or 0),
        'statement_count_cumulative': int(compartment.get('statement_count_cumulative') or 0),
    }
    if sources:
        row['sources'] = sorted(set(sources))
    return row


def _path_matches(candidate: str, query: str) -> bool:
    candidate_norm = _normalize_compartment_path(candidate).casefold()
    query_norm = _normalize_compartment_path(query).casefold()
    if not candidate_norm or not query_norm:
        return False
    return candidate_norm == query_norm or candidate_norm.endswith(f'/{query_norm}')


def _is_descendant_of(
    compartment: dict[str, Any],
    ancestor_id: str,
    by_id: dict[str, dict[str, Any]],
) -> bool:
    current_id = str(compartment.get('parent_id') or '')
    visited: set[str] = set()
    while current_id and current_id not in visited:
        if current_id == ancestor_id:
            return True
        visited.add(current_id)
        parent = by_id.get(current_id)
        if not parent:
            return False
        current_id = str(parent.get('parent_id') or '')
    return False


def _search_compartments(
    repo: PolicyAnalysisRepository,
    *,
    names: list[str] | None = None,
    ocids: list[str] | None = None,
    paths: list[str] | None = None,
    parent_ocids: list[str] | None = None,
    parent_paths: list[str] | None = None,
    include_children: bool = False,
) -> list[dict[str, Any]]:
    """Search loaded compartments by OCID, name, path, or parent scope."""

    compartments = [dict(comp) for comp in (getattr(repo, 'compartments', []) or []) if isinstance(comp, dict)]
    by_id = {str(comp.get('id') or ''): comp for comp in compartments if comp.get('id')}
    name_terms = {term.casefold() for term in _as_str_list(names)}
    ocid_terms = set(_as_str_list(ocids))
    path_terms = _as_str_list(paths)
    parent_ocid_terms = set(_as_str_list(parent_ocids))
    parent_path_terms = _as_str_list(parent_paths)

    matched: list[dict[str, Any]] = []
    matched_ids: set[str] = set()

    for comp in compartments:
        comp_id = str(comp.get('id') or '')
        comp_name = str(comp.get('name') or '').casefold()
        comp_path = _compartment_path(comp, repo)
        parent_id = str(comp.get('parent_id') or '')
        parent_path = _compartment_parent_path(comp, by_id, repo)

        if name_terms and comp_name not in name_terms:
            continue
        if ocid_terms and comp_id not in ocid_terms:
            continue
        if path_terms and not any(_path_matches(comp_path, term) for term in path_terms):
            continue
        if parent_ocid_terms and parent_id not in parent_ocid_terms:
            continue
        if parent_path_terms and not any(_path_matches(parent_path, term) for term in parent_path_terms):
            continue

        matched.append(comp)
        if comp_id:
            matched_ids.add(comp_id)

    if include_children and matched_ids:
        for comp in compartments:
            comp_id = str(comp.get('id') or '')
            if comp_id in matched_ids:
                continue
            if any(_is_descendant_of(comp, ancestor_id, by_id) for ancestor_id in matched_ids):
                matched.append(comp)
                if comp_id:
                    matched_ids.add(comp_id)

    rows = [_format_compartment_for_mcp(comp, repo=repo, by_id=by_id) for comp in matched]
    rows.sort(
        key=lambda row: (
            str(row.get('path') or '').casefold(),
            str(row.get('name') or '').casefold(),
        )
    )
    return rows


def _extract_compartment_ocids(text: object | None) -> list[str]:
    return sorted(set(COMPARTMENT_OCID_RE.findall(str(text or ''))))


def _add_compartment_ocid_sources(
    sources_by_ocid: dict[str, list[str]],
    value: object | None,
    source: str,
) -> None:
    for ocid in _extract_compartment_ocids(value):
        sources_by_ocid.setdefault(ocid, []).append(source)


def _resolve_statement_principal_compartments(
    statement: dict[str, Any],
    repo: PolicyAnalysisRepository | None,
) -> list[dict[str, Any]]:
    """Resolve compartment OCIDs present in workload-principal evidence."""

    if repo is None:
        return []

    sources_by_ocid: dict[str, list[str]] = {}

    for principal in statement.get('principals') or []:
        if not isinstance(principal, dict):
            continue
        for key in ('compartment_ocid', 'resource_compartment_ocid', 'resource_compartment_id'):
            _add_compartment_ocid_sources(sources_by_ocid, principal.get(key), f'principal.{key}')

    for atom in statement.get('principal_evidence') or []:
        if not isinstance(atom, dict):
            continue
        left = str(atom.get('normalized_left') or atom.get('left') or '').casefold()
        if 'compartment' not in left or 'id' not in left:
            continue
        _add_compartment_ocid_sources(
            sources_by_ocid,
            atom.get('right') or atom.get('value') or atom.get('values'),
            f'principal_evidence.{left or "compartment"}',
        )

    for evidence in statement.get('dynamic_group_rule_evidence') or []:
        if not isinstance(evidence, dict):
            continue
        _add_compartment_ocid_sources(
            sources_by_ocid,
            evidence.get('matching_rule'),
            'dynamic_group_rule_evidence.matching_rule',
        )
        _add_compartment_ocid_sources(
            sources_by_ocid,
            json.dumps(evidence.get('matching_rule_structure') or {}, default=str),
            'dynamic_group_rule_evidence.matching_rule_structure',
        )

    if not sources_by_ocid:
        return []

    compartments = [dict(comp) for comp in (getattr(repo, 'compartments', []) or []) if isinstance(comp, dict)]
    by_id = {str(comp.get('id') or ''): comp for comp in compartments if comp.get('id')}
    rows = []
    for ocid, sources in sorted(sources_by_ocid.items()):
        comp = by_id.get(ocid)
        if comp:
            rows.append(_format_compartment_for_mcp(comp, repo=repo, by_id=by_id, sources=sources))
        else:
            rows.append(
                {
                    'name': '',
                    'ocid': ocid,
                    'path': '',
                    'effective_path': '',
                    'parent_ocid': '',
                    'parent_path': '',
                    'lifecycle_state': '',
                    'description': '',
                    'statement_count_direct': 0,
                    'statement_count_cumulative': 0,
                    'sources': sorted(set(sources)),
                    'resolution_status': 'not_found',
                }
            )
    return rows


def _policy_filters_from_request(filters: dict[str, Any] | None) -> PolicySearch:
    raw = dict(filters or {})
    normalized: dict[str, object] = {}

    passthrough_fields = (
        'action',
        'principal',
        'principals',
        'principal_keys',
        'principal_key',
        'verb',
        'statement_text',
        'policy_name',
        'compartment_path',
        'resource',
        'location',
        'effective_path',
        'subject_type',
        'subject',
        'permission',
        'comments',
        'conditions',
        'tag_access_type',
        'tag_access_semantics',
        'tag_namespace',
        'tag_key',
        'tag_value',
        'tag_operator',
        'condition_atom_terms',
        'policy_tag',
        'policy_defined_tag',
        'policy_freeform_tag',
        'valid',
    )
    for field in passthrough_fields:
        if field in raw:
            normalized[field] = raw[field]

    if 'text' in raw and 'statement_text' not in normalized:
        normalized['statement_text'] = raw.get('text')
    if 'subject_text' in raw and 'subject' not in normalized:
        normalized['subject'] = raw.get('subject_text')
    if 'condition' in raw and 'conditions' not in normalized:
        condition = raw.get('condition')
        condition_terms: list[str] = []
        if isinstance(condition, dict):
            for key in ('condition_text', 'tag_scope', 'tag_namespace', 'tag_key', 'tag_value'):
                condition_terms.extend(_as_str_list(condition.get(key)))
        else:
            condition_terms.extend(_as_str_list(condition))
        if condition_terms:
            normalized['conditions'] = condition_terms

    return PolicySearch(**normalized)


def _statement_identity(statement: dict[str, Any]) -> str:
    for key in ('stable_key', 'internal_id'):
        value = statement.get(key)
        if value:
            return str(value)
    parts = [
        statement.get('policy_name'),
        statement.get('compartment_path'),
        statement.get('statement_text'),
        statement.get('conditions'),
        statement.get('comments'),
    ]
    return '|'.join(str(part or '').strip().casefold() for part in parts)


def _statement_compact(statement: dict[str, Any]) -> dict[str, Any]:
    principals = statement.get('principals')
    principal_summary = ''
    if isinstance(principals, list) and principals:
        principal_summary = ', '.join(
            str(principal.get('display_name') or principal.get('principal_key') or '')
            for principal in principals
            if isinstance(principal, dict)
        )
    return {
        'policy_name': statement.get('policy_name') or '',
        'compartment_path': statement.get('compartment_path') or '',
        'statement_text': statement.get('statement_text') or '',
        'subject_type': statement.get('subject_type') or '',
        'principal_summary': principal_summary,
        'verb': statement.get('verb') or '',
        'resource': statement.get('resource') or '',
        'permission': statement.get('permission') or [],
        'location': statement.get('location') or '',
        'effective_path': statement.get('effective_path') or '',
        'where_clause_text': statement.get('conditions_where_clause') or statement.get('conditions') or '',
        'match_confidence': statement.get('match_confidence') or statement.get('confidence') or '',
    }


def _statement_advanced(
    statement: dict[str, Any],
    *,
    include_full: bool = False,
    repo: PolicyAnalysisRepository | None = None,
) -> dict[str, Any]:
    row = {
        'statement_text': statement.get('statement_text') or '',
        'policy_name': statement.get('policy_name') or '',
        'effective_path': statement.get('effective_path') or '',
        'normalized_principals': statement.get('principals') or [],
        'principal_keys': statement.get('principal_keys') or [],
        'principal_evidence': statement.get('principal_evidence') or [],
        'where_clause': statement.get('where_clause') or statement.get('where_clause_structure') or {},
        'condition_atoms': statement.get('condition_atoms') or [],
        'tag_conditions': statement.get('tag_conditions') or [],
        'tag_context_warnings': statement.get('tag_context_warnings') or [],
        'dynamic_group_rule_evidence': statement.get('dynamic_group_rule_evidence') or [],
        'residual_conditions': statement.get('residual_conditions') or [],
        'match_confidence': statement.get('match_confidence') or statement.get('confidence') or '',
        'match_confidence_reason': statement.get('match_confidence_reason') or '',
    }
    resolved_compartments = _resolve_statement_principal_compartments(statement, repo)
    if resolved_compartments:
        row['resolved_compartments'] = resolved_compartments
    if include_full:
        row['full_statement'] = statement
    return row


def _breakdowns(statements: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counters = {
        'by_policy': Counter(),
        'by_subject_type': Counter(),
        'by_verb': Counter(),
        'by_resource': Counter(),
        'by_confidence': Counter(),
    }
    for statement in statements:
        counters['by_policy'][str(statement.get('policy_name') or 'Unknown')] += 1
        counters['by_subject_type'][str(statement.get('subject_type') or 'Unknown')] += 1
        counters['by_verb'][str(statement.get('verb') or 'Unknown')] += 1
        resource = statement.get('resource') or ','.join(statement.get('permission') or []) or 'Unknown'
        counters['by_resource'][str(resource)] += 1
        confidence = statement.get('match_confidence') or statement.get('confidence') or 'not_scored'
        counters['by_confidence'][str(confidence)] += 1
    return {key: dict(counter) for key, counter in counters.items()}


def _format_policy_search_response(
    statements: list[dict[str, Any]],
    *,
    mode: str = 'simple',
    detail_level: str = 'simple',
    limit: int | None = None,
    warnings: list[str] | None = None,
    repo: PolicyAnalysisRepository | None = None,
) -> dict[str, Any]:
    bounded_limit = _clamp_limit(limit)
    normalized = [_normalize_policy_statement_for_mcp(statement) for statement in statements]
    total_count = len(normalized)
    response_type = 'summary' if detail_level == 'summary' or total_count > bounded_limit else detail_level
    sample = normalized[:bounded_limit]

    if response_type == 'full':
        rows = [
            _statement_advanced(statement, include_full=(mode == 'advanced'), repo=repo)
            if mode == 'advanced'
            else statement
            for statement in sample
        ]
    elif mode == 'advanced':
        rows = [_statement_advanced(statement, include_full=False, repo=repo) for statement in sample]
    else:
        rows = [_statement_compact(statement) for statement in sample]

    return {
        'response_type': response_type,
        'total_count': total_count,
        'returned_count': len(rows),
        'truncated': total_count > len(rows),
        'statements': rows,
        'breakdowns': _breakdowns(normalized),
        'warnings': list(warnings or []),
    }


def _dynamic_group_rule_search_terms(principal: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ('ocid', 'resource_ocid', 'compartment_ocid', 'resource_compartment_ocid'):
        terms.extend(_as_str_list(principal.get(key)))
    resource_type = str(principal.get('resource_type') or '').strip()
    if resource_type and resource_type != 'instance':
        terms.append(resource_type)
    return terms


def _oke_workload_identity_search_terms(principal: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ('workload_namespace', 'workload_service_account', 'workload_cluster_id'):
        terms.extend(_as_str_list(principal.get(key)))
    return terms


def _search_instance_principal_statements(
    filters: PolicySearch,
    principal: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    terms = _dynamic_group_rule_search_terms(principal)
    if not terms:
        return [], ['instance-principal search requires ocid, compartment_ocid, or resource_compartment_ocid']

    dynamic_groups = _query_service().search_dynamic_groups(DynamicGroupSearch(matching_rule=terms))
    principal_keys = [key for dg in dynamic_groups if (key := _principal_key_for_dynamic_group(dg))]
    if not principal_keys:
        return [], ['No dynamic groups matched the instance-principal rule evidence.']

    policy_filters = PolicySearch(**{k: v for k, v in filters.items() if k not in {'principal', 'principals'}})
    existing_keys = list(policy_filters.get('principal_keys') or policy_filters.get('principal_key') or [])
    policy_filters['principal_keys'] = sorted(set(existing_keys + principal_keys))
    statements = _query_service().filter_policy_statements(policy_filters)

    evidence_by_key = {_principal_key_for_dynamic_group(dg): dg for dg in dynamic_groups}
    annotated: list[dict[str, Any]] = []
    for statement in statements:
        row = dict(statement)
        matched_evidence = []
        for key in row.get('principal_keys') or []:
            dynamic_group = evidence_by_key.get(str(key))
            if dynamic_group:
                matched_evidence.append(
                    {
                        'principal_key': key,
                        'dynamic_group_name': dynamic_group.get('dynamic_group_name') or '',
                        'domain_name': dynamic_group.get('domain_name') or '',
                        'matching_rule': dynamic_group.get('matching_rule') or '',
                        'matching_rule_structure': dynamic_group.get('matching_rule_structure') or {},
                    }
                )
        row['dynamic_group_rule_evidence'] = matched_evidence
        row['match_confidence'] = row.get('match_confidence') or 'rule_evidence'
        row['confidence'] = row.get('confidence') or row['match_confidence']
        row['match_confidence_reason'] = row.get('match_confidence_reason') or (
            'Matched policy dynamic-group subject through dynamic group matching-rule evidence.'
        )
        annotated.append(row)
    return annotated, []


def _search_oke_workload_identity_statements(
    filters: PolicySearch,
    principal: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    policy_filters = PolicySearch(**{k: v for k, v in filters.items() if k not in {'principal', 'principals'}})
    policy_filters['subject_type'] = ['any-user', 'any-group']
    policy_filters['principal'] = {
        'principal_type': 'oke-workload-identity',
        **(
            {'workload_namespace': _as_str_list(principal.get('workload_namespace'))[0]}
            if principal.get('workload_namespace')
            else {}
        ),
        **(
            {'workload_service_account': _as_str_list(principal.get('workload_service_account'))[0]}
            if principal.get('workload_service_account')
            else {}
        ),
        **(
            {'workload_cluster_id': _as_str_list(principal.get('workload_cluster_id'))[0]}
            if principal.get('workload_cluster_id')
            else {}
        ),
    }
    statements = _query_service().filter_policy_statements(policy_filters)

    annotated: list[dict[str, Any]] = []
    for statement in statements:
        row = dict(statement)
        row['match_confidence'] = row.get('match_confidence') or 'rule_evidence'
        row['confidence'] = row.get('confidence') or row['match_confidence']
        row['match_confidence_reason'] = row.get('match_confidence_reason') or (
            'Matched policy any-user/any-group subject through OKE workload identity evidence.'
        )
        annotated.append(row)
    return annotated, []


def _run_policy_search_request(
    request: dict[str, Any], *, repo: PolicyAnalysisRepository | None = None
) -> dict[str, Any]:
    mode = str(request.get('mode') or 'simple')
    detail_level = str(request.get('detail_level') or 'simple')
    filters = _policy_filters_from_request(request.get('filters') if isinstance(request.get('filters'), dict) else {})
    warnings: list[str] = []

    principal = filters.get('principal')
    if (
        isinstance(principal, dict)
        and str(principal.get('principal_type') or '') == 'instance-principal'
        and repo is None
    ):
        statements, warnings = _search_instance_principal_statements(filters, principal)
    elif (
        isinstance(principal, dict)
        and str(principal.get('principal_type') or '') in {'oke-workload-identity', 'oke_workload_identity'}
        and repo is None
    ):
        statements, warnings = _search_oke_workload_identity_statements(filters, principal)
    elif repo is not None:
        statements = list(repo.filter_policy_statements(filters=filters))
    else:
        statements = _query_service().filter_policy_statements(filters)

    return _format_policy_search_response(
        statements,
        mode=mode,
        detail_level=detail_level,
        limit=request.get('limit') if isinstance(request.get('limit'), int) else None,
        warnings=warnings,
        repo=repo or _current_policy_repo(),
    )


def _policy_search_set_child_query(item: dict[str, Any]) -> dict[str, Any]:
    """Return the policy-search query payload for a set item."""
    nested = item.get('query')
    if isinstance(nested, dict):
        return nested

    query_fields = {'mode', 'detail_level', 'filters', 'limit'}
    if any(field in item for field in query_fields):
        return {field: item[field] for field in query_fields if field in item}

    return {}


def _confidence_meets(value: str, minimum: str) -> bool:
    return CONFIDENCE_ORDER.get(value or '', -1) >= CONFIDENCE_ORDER.get(minimum or '', -1)


def _summarize_search_set(
    *,
    intent: str,
    product_or_service: str,
    searches: list[dict[str, Any]],
    results: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    required_ids = [
        str(search.get('search_id') or idx)
        for idx, search in enumerate(searches, start=1)
        if bool(search.get('required', True))
    ]
    min_confidence = str(evaluation.get('min_confidence') or 'broad')
    missing_or_ambiguous = []
    matched_required = 0

    for result in results:
        search_id = str(result.get('search_id') or '')
        total = int(result.get('total_count') or 0)
        confidences = [
            str(row.get('match_confidence') or '') for row in result.get('statements') or [] if isinstance(row, dict)
        ]
        confidences = [confidence for confidence in confidences if confidence]
        confidence_ok = not confidences or any(
            _confidence_meets(confidence, min_confidence) for confidence in confidences
        )
        if search_id in required_ids and total > 0 and confidence_ok:
            matched_required += 1
        elif search_id in required_ids:
            missing_or_ambiguous.append(
                {
                    'search_id': search_id,
                    'reason': 'No matches found.'
                    if total == 0
                    else f'Matches below minimum confidence {min_confidence}.',
                }
            )

    missing_required = [item['search_id'] for item in missing_or_ambiguous]
    required_count = len(required_ids)

    def coverage(flag: str, principal_type: str) -> str:
        if not bool(evaluation.get(flag)):
            return 'not_requested'
        for result in results:
            for statement in result.get('statements') or []:
                if not isinstance(statement, dict):
                    continue
                principals = statement.get('normalized_principals') or statement.get('principals') or []
                if any(
                    isinstance(p, dict) and str(p.get('principal_type') or '') == principal_type for p in principals
                ):
                    return 'present'
        return 'missing'

    def workload_coverage() -> str:
        if not bool(evaluation.get('require_workload_principal_coverage')):
            return 'not_requested'
        workload_types = {
            'dynamic-group',
            'dynamic-group-id',
            'resource-principal',
            'resource_principal',
            'workload-principal',
            'workload_principal',
            'oke-workload-identity',
            'oke_workload_identity',
        }
        for result in results:
            for row in result.get('statements') or []:
                if not isinstance(row, dict):
                    continue
                if row.get('match_confidence') in {'exact', 'identity_match_with_residual', 'rule_evidence'}:
                    return 'present'
                principals = row.get('normalized_principals') or row.get('principals') or []
                if any(
                    isinstance(principal, dict) and str(principal.get('principal_type') or '') in workload_types
                    for principal in principals
                ):
                    return 'present'
        return 'missing'

    return {
        'intent': intent,
        'product_or_service': product_or_service,
        'total_searches': len(searches),
        'required_searches': required_count,
        'matched_required_searches': matched_required,
        'missing_required_searches': missing_required,
        'human_principal_coverage': coverage('require_human_principal_coverage', 'group'),
        'workload_principal_coverage': workload_coverage(),
        'service_principal_coverage': coverage('require_service_principal_coverage', 'service'),
        'tag_condition_coverage': 'not_requested'
        if not bool(evaluation.get('require_tag_condition_coverage'))
        else 'ambiguous',
        'missing_or_ambiguous_items': missing_or_ambiguous,
        'likely_ready': True if required_count and matched_required == required_count else 'unknown',
        'confidence': 'high' if required_count and matched_required == required_count else 'medium',
    }


def _cache_entries() -> list[dict[str, Any]]:
    manager = CacheManager()
    entries_path = manager.cache_dir / 'cache_entries.json'
    entries: list[dict[str, Any]] = []
    if not entries_path.exists():
        return entries
    with open(entries_path, encoding='utf-8') as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entry['cache_name'] = f'{entry.get("tenancy_name", "")}_{entry.get("cache_date", "")}'
                entries.append(entry)
    return list(reversed(entries))


def _cache_metadata(cache_name: str) -> dict[str, Any]:
    manager = CacheManager()
    entries = _cache_entries()
    metadata = next((entry for entry in entries if entry.get('cache_name') == cache_name), {})
    cache_file = manager.cache_dir / f'combined_cache_{cache_name}.json'
    if cache_file.exists():
        stat = cache_file.stat()
        metadata = dict(metadata)
        metadata.setdefault('cache_name', cache_name)
        metadata['path'] = str(cache_file)
        metadata['size_bytes'] = stat.st_size
        metadata['modified_at'] = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    return metadata


def _cache_timestamp(cache_name: str, metadata: dict[str, Any] | None = None) -> datetime | None:
    metadata = metadata or _cache_metadata(cache_name)
    for key in ('captured_at', 'data_as_of', 'cache_date'):
        value = metadata.get(key)
        if not value:
            continue
        text = str(value).replace('Z', '+00:00')
        for fmt in (None, '%Y-%m-%d-%H-%M-%S-%Z'):
            try:
                if fmt is None:
                    parsed = datetime.fromisoformat(text)
                else:
                    parsed = datetime.strptime(text, fmt).replace(tzinfo=UTC)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _select_cache_as_of(as_of: str) -> tuple[str, dict[str, Any]]:
    target = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    candidates = []
    for entry in _cache_entries():
        name = str(entry.get('cache_name') or '')
        timestamp = _cache_timestamp(name, entry)
        if timestamp:
            candidates.append((timestamp, name, entry))
    if not candidates:
        raise ToolError('No cache snapshots are available.')
    before = [candidate for candidate in candidates if candidate[0] <= target]
    selected = max(before, key=lambda item: item[0]) if before else min(candidates, key=lambda item: item[0])
    metadata = dict(selected[2])
    metadata['source'] = 'cache'
    metadata['confidence'] = 'high' if selected[0] <= target else 'low'
    return selected[1], metadata


def _repo_from_snapshot(snapshot: dict[str, Any]) -> tuple[PolicyAnalysisRepository, dict[str, Any]]:
    source = str(snapshot.get('source') or 'current')
    ctx = _require_service_context()
    if source == 'current':
        return ctx.policy_repo, {'source': 'current', 'data_as_of': ctx.policy_repo.data_as_of}

    cache_name = str(snapshot.get('cache_name') or '')
    metadata: dict[str, Any] = {'source': source}
    if source == 'as_of':
        cache_name, metadata = _select_cache_as_of(str(snapshot.get('as_of') or ''))
    if not cache_name:
        raise ToolError('Snapshot source cache/as_of requires cache_name or as_of.')

    repo = PolicyAnalysisRepository()
    loaded = CacheManager().load_combined_cache(policy_analysis=repo, named_cache=cache_name)
    metadata.update(_cache_metadata(cache_name))
    metadata['source'] = 'cache'
    metadata['cache_name'] = cache_name
    metadata['loaded'] = loaded
    return repo, metadata


def _run_query_for_history(
    query_type: str, query: dict[str, Any], repo: PolicyAnalysisRepository
) -> list[dict[str, Any]]:
    if query_type == 'set':
        rows: list[dict[str, Any]] = []
        for search in query.get('searches') or []:
            if not isinstance(search, dict):
                continue
            child_query = _policy_search_set_child_query(search)
            response = _run_policy_search_request(child_query, repo=repo)
            rows.extend(response.get('statements') or [])
        return rows
    response = _run_policy_search_request(query, repo=repo)
    return response.get('statements') or []


def _summarize_schema(schema: dict[str, Any] | None) -> str:
    """Return a short description of a JSON schema for display in the MCP tab tools table.

    Preference is to list top-level property names; fall back to schema "type" if present.
    """

    if not schema or not isinstance(schema, dict):
        return ''
    props = schema.get('properties')
    if isinstance(props, dict) and props:
        return ', '.join(str(k) for k in props.keys())
    schema_type = schema.get('type')
    return str(schema_type) if schema_type else ''


def _refresh_registered_tools_from_mcp() -> None:
    """Rebuild the in-process registry from FastMCP's tool definitions.

    This inspects the FastMCP instance to derive tool metadata so the UI
    does not need to duplicate tool definitions.
    """

    global _REGISTERED_TOOLS
    tools: list[dict[str, Any]] = []

    # FastMCP exposes its tools via its tool manager; use the public get_tools() API.
    logger.info(
        '[_refresh_registered_tools_from_mcp] FastMCP instance type=%s, candidate tool-related attributes=%s',
        type(mcp),
        [name for name in dir(mcp) if 'tool' in name.lower()],
    )

    try:
        # FastMCP exposes a get_tools() helper that returns a mapping of tool name -> tool object
        get_tools_fn = getattr(mcp, 'get_tools', None)
        tools_map = get_tools_fn() if callable(get_tools_fn) else None
        if inspect.isawaitable(tools_map):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                tools_map = asyncio.run(tools_map)
            else:
                logger.warning(
                    '[_refresh_registered_tools_from_mcp] Cannot synchronously refresh tools while event loop %s is running',
                    loop,
                )
                tools_map = None
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('[_refresh_registered_tools_from_mcp] mcp.get_tools() failed: %s', exc, exc_info=True)
        tools_map = None

    if isinstance(tools_map, dict):
        tool_iter = list(tools_map.values())
    elif tools_map is None:
        tool_iter = []
    else:
        tool_iter = list(tools_map) if hasattr(tools_map, '__iter__') else []

    if not tool_iter:
        logger.warning(
            '[_refresh_registered_tools_from_mcp] No tools discovered via mcp.get_tools(); UI registry will be empty. '
            'tools_map=%r',
            tools_map,
        )
        _REGISTERED_TOOLS = []
        return

    logger.info(
        '[_refresh_registered_tools_from_mcp] tool_iter length=%d, sample=%r',
        len(tool_iter),
        tool_iter[:2],
    )

    for tool in tool_iter:
        try:
            name = getattr(tool, 'name', '')
            desc = getattr(tool, 'description', '')
            logger.info(
                '[_refresh_registered_tools_from_mcp] inspecting tool name=%r, type=%s, dir_contains_input_schema=%s, dir_contains_output_schema=%s',
                name,
                type(tool),
                'input_schema' in dir(tool),
                'output_schema' in dir(tool),
            )
            # FastMCP exposes JSON-schema-like input/output definitions on the tool;
            # use them if present, otherwise leave blank and let UI show empty strings.
            input_schema = getattr(tool, 'input_schema', None)
            output_schema = getattr(tool, 'output_schema', None)
            tools.append(
                {
                    'name': str(name),
                    'description': str(desc),
                    'inputs': _summarize_schema(input_schema) if input_schema is not None else '',
                    'outputs': _summarize_schema(output_schema) if output_schema is not None else '',
                }
            )
        except Exception as exc:  # defensive; do not break registry build for a single tool
            logger.error('Failed to register MCP tool metadata for UI: %s', exc, exc_info=True)

    _REGISTERED_TOOLS = tools
    logger.info('MCP tool registry built with %d tools for UI display', len(_REGISTERED_TOOLS))


def get_registered_tools() -> list[dict[str, Any]]:
    """Return the list of MCP tools as seen by the FastMCP instance.

    The result is used exclusively by the Embedded MCP tab to display
    name/description/inputs/outputs in a table. It does not require the
    server to be running; it reflects the tools registered on the FastMCP
    instance at import time (or after any explicit refresh).
    """

    # Lazy initialization: always try to refresh once when called from the UI.
    # This ensures that even if FastMCP attaches tools later in import order,
    # the registry is rebuilt the first time the Embedded MCP tab is shown.
    try:
        _refresh_registered_tools_from_mcp()
    except Exception as exc:  # defensive: never break callers due to registry issues
        logger.error('get_registered_tools: failed to refresh registry: %s', exc, exc_info=True)
    return list(_REGISTERED_TOOLS)


# --- Resources and Tools (unchanged) ---
@mcp.custom_route('/health', methods=['GET'])
async def health_check(request):
    # Perform any necessary checks here (e.g., database connection, external service availability)
    return JSONResponse({'status': 'healthy'})


# ---------------------
# --- Tools ---
# ---------------------


@mcp.tool(
    name='policy_search',
    description=(
        'Search OCI IAM policies. Principal filters: use filters.principal for one structured selector '
        '(for example {"principal_type":"group","domain_name":"Default","name":"Admins"} or '
        '{"principal_type":"dynamic-group"}), filters.principals for OR selectors, and filters.principal_keys '
        'for exact canonical keys such as group:Default/Admins. Combine with resource, verb, permission, '
        'effective_path, policy_name, conditions, and statement_text.'
    ),
)
def policy_search(
    mode: Literal['simple', 'advanced'] = 'simple',
    detail_level: Literal['summary', 'simple', 'full'] = 'simple',
    filters: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run one bounded policy search."""

    tool_name = 'policy_search'
    _log_mcp_call_input(tool_name, {'mode': mode, 'detail_level': detail_level, 'filters': filters, 'limit': limit})
    try:
        response = _run_policy_search_request(
            {'mode': mode, 'detail_level': detail_level, 'filters': filters or {}, 'limit': limit}
        )
        _track_mcp_tool(tool_name, status='success', total_statements=response.get('total_count'))
        return _log_mcp_call_output(tool_name, response)
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in policy_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in policy_search: {exc}') from exc


@mcp.tool(
    name='tag_based_policy_search', description='Search parsed tag-based policy conditions with contextual warnings.'
)
def tag_based_policy_search(
    tag_access_type: list[str] | None = None,
    tag_access_semantics: list[str] | None = None,
    tag_namespace: list[str] | None = None,
    tag_key: list[str] | None = None,
    tag_value: list[str] | None = None,
    tag_operator: list[str] | None = None,
    condition_atom_terms: list[str] | None = None,
    policy_tag: list[str] | None = None,
    policy_defined_tag: list[str] | None = None,
    policy_freeform_tag: list[str] | None = None,
    verb: list[str] | None = None,
    resource: list[str] | None = None,
    permission: list[str] | None = None,
    principal_keys: list[str] | None = None,
    effective_path: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run a tag-focused policy search using parsed where-clause data."""

    tool_name = 'tag_based_policy_search'
    filters = {
        key: value
        for key, value in {
            'tag_access_type': tag_access_type,
            'tag_access_semantics': tag_access_semantics,
            'tag_namespace': tag_namespace,
            'tag_key': tag_key,
            'tag_value': tag_value,
            'tag_operator': tag_operator,
            'condition_atom_terms': condition_atom_terms,
            'policy_tag': policy_tag,
            'policy_defined_tag': policy_defined_tag,
            'policy_freeform_tag': policy_freeform_tag,
            'verb': verb,
            'resource': resource,
            'permission': permission,
            'principal_keys': principal_keys,
            'effective_path': effective_path,
        }.items()
        if value
    }
    _log_mcp_call_input(tool_name, {'filters': filters, 'limit': limit})
    try:
        if not any(key.startswith('tag_') or key.startswith('policy_') for key in filters):
            filters['condition_atom_terms'] = condition_atom_terms or ['.tag.']
        response = _run_policy_search_request(
            {'mode': 'advanced', 'detail_level': 'full', 'filters': filters, 'limit': limit}
        )
        repo = _current_policy_repo()
        statements = list(repo.filter_policy_statements(filters=PolicySearch(**filters))) if repo is not None else []
        response['tag_summary'] = TagBasedPolicyService.query(statements, PolicySearch(**filters)).get('summary', {})
        _track_mcp_tool(tool_name, status='success', total_statements=response.get('total_count'))
        return _log_mcp_call_output(tool_name, response)
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in tag_based_policy_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in tag_based_policy_search: {exc}') from exc


@mcp.tool(
    name='oke_workload_identity_search',
    description='Search OCI IAM policies for OKE workload identity coverage with guided namespace and service account filters.',
)
def oke_workload_identity_search(
    workload_namespace: str = '',
    workload_service_account: str = '',
    workload_cluster_id: str = '',
    verb: list[str] | None = None,
    resource: list[str] | None = None,
    permission: list[str] | None = None,
    effective_path: list[str] | None = None,
    condition_atom_terms: list[str] | None = None,
    policy_tag: list[str] | None = None,
    policy_defined_tag: list[str] | None = None,
    policy_freeform_tag: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run a guided OKE workload identity policy search."""

    tool_name = 'oke_workload_identity_search'
    filters = {
        key: value
        for key, value in {
            'principal': {
                'principal_type': 'oke-workload-identity',
                'workload_namespace': workload_namespace,
                'workload_service_account': workload_service_account,
                'workload_cluster_id': workload_cluster_id,
            },
            'verb': verb,
            'resource': resource,
            'permission': permission,
            'effective_path': effective_path,
            'condition_atom_terms': condition_atom_terms,
            'policy_tag': policy_tag,
            'policy_defined_tag': policy_defined_tag,
            'policy_freeform_tag': policy_freeform_tag,
        }.items()
        if value
    }
    _log_mcp_call_input(tool_name, {'filters': filters, 'limit': limit})
    try:
        response = _run_policy_search_request(
            {'mode': 'advanced', 'detail_level': 'full', 'filters': filters, 'limit': limit}
        )
        _track_mcp_tool(tool_name, status='success', total_statements=response.get('total_count'))
        return _log_mcp_call_output(tool_name, response)
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in oke_workload_identity_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in oke_workload_identity_search: {exc}') from exc


@mcp.tool(
    name='policy_search_set',
    description=(
        'Run related policy searches and summarize coverage. Each item in searches may be a direct policy_search '
        'payload with search_id/label/required plus mode/detail_level/limit/filters, or the legacy wrapped form '
        '{"search_id":"id","query":{...}}. For principal filters inside each search, use filters.principal '
        'for one selector, filters.principals for OR selectors, or filters.principal_keys for exact keys.'
    ),
)
def policy_search_set(
    intent: Literal['install_validation', 'access_review', 'workload_analysis', 'custom'] = 'custom',
    product_or_service: str = '',
    searches: list[dict[str, Any]] | None = None,
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run multiple related policy searches and summarize coverage."""

    tool_name = 'policy_search_set'
    _log_mcp_call_input(
        tool_name,
        {
            'intent': intent,
            'product_or_service': product_or_service,
            'searches': searches,
            'evaluation': evaluation,
        },
    )
    try:
        search_items = [item for item in (searches or []) if isinstance(item, dict)]
        eval_config = dict(evaluation or {})
        results = []
        for idx, item in enumerate(search_items, start=1):
            query = _policy_search_set_child_query(item)
            response = _run_policy_search_request(query)
            response['search_id'] = str(item.get('search_id') or idx)
            response['label'] = str(item.get('label') or response['search_id'])
            response['required'] = bool(item.get('required', True))
            results.append(response)

        set_summary = _summarize_search_set(
            intent=intent,
            product_or_service=product_or_service,
            searches=search_items,
            results=results,
            evaluation=eval_config,
        )
        _track_mcp_tool(tool_name, status='success', count=len(results))
        return _log_mcp_call_output(tool_name, {'set_summary': set_summary, 'search_results': results})
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in policy_search_set: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in policy_search_set: {exc}') from exc


@mcp.tool(name='policy_history_search', description='Run a policy search against two snapshots and diff results.')
def policy_history_search(
    query_type: Literal['single', 'set'] = 'single',
    query: dict[str, Any] | None = None,
    left: dict[str, Any] | None = None,
    right: dict[str, Any] | None = None,
    diff_mode: Literal['statement_identity', 'full_fields', 'permissions'] = 'statement_identity',
) -> dict[str, Any]:
    """Compare one search or search set across two data snapshots."""

    tool_name = 'policy_history_search'
    _log_mcp_call_input(
        tool_name,
        {
            'query_type': query_type,
            'query': query,
            'left': left,
            'right': right,
            'diff_mode': diff_mode,
        },
    )
    try:
        left_repo, left_metadata = _repo_from_snapshot(left or {'source': 'current'})
        right_repo, right_metadata = _repo_from_snapshot(right or {'source': 'current'})
        search_query = query or {'mode': 'simple', 'detail_level': 'simple', 'filters': {}}
        left_rows = _run_query_for_history(query_type, search_query, left_repo)
        right_rows = _run_query_for_history(query_type, search_query, right_repo)

        left_by_id = {_statement_identity(row): row for row in left_rows if isinstance(row, dict)}
        right_by_id = {_statement_identity(row): row for row in right_rows if isinstance(row, dict)}
        left_keys = set(left_by_id)
        right_keys = set(right_by_id)
        added_keys = sorted(right_keys - left_keys)
        removed_keys = sorted(left_keys - right_keys)
        shared_keys = sorted(left_keys & right_keys)
        modified_keys = [
            key
            for key in shared_keys
            if diff_mode != 'statement_identity'
            and json.dumps(left_by_id[key], sort_keys=True, default=str)
            != json.dumps(right_by_id[key], sort_keys=True, default=str)
        ]

        response = {
            'query_type': query_type,
            'diff_mode': diff_mode,
            'left_count': len(left_rows),
            'right_count': len(right_rows),
            'added_count': len(added_keys),
            'removed_count': len(removed_keys),
            'modified_count': len(modified_keys),
            'unchanged_count': len(shared_keys) - len(modified_keys),
            'added_statements': [right_by_id[key] for key in added_keys[:25]],
            'removed_statements': [left_by_id[key] for key in removed_keys[:25]],
            'modified_statements': [{'left': left_by_id[key], 'right': right_by_id[key]} for key in modified_keys[:25]],
            'left_snapshot_metadata': left_metadata,
            'right_snapshot_metadata': right_metadata,
        }
        _track_mcp_tool(tool_name, status='success', count=response['right_count'])
        return _log_mcp_call_output(tool_name, response)
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in policy_history_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in policy_history_search: {exc}') from exc


@mcp.tool(name='identity_search', description='Search identities, compartments, and IAM memberships.')
def identity_search(
    operation: Literal['search', 'members_for_group', 'groups_for_user'] = 'search',
    entity_types: list[Literal['user', 'group', 'dynamic-group', 'compartment']] | None = None,
    domain_name: list[str] | None = None,
    name: list[str] | None = None,
    ocid: list[str] | None = None,
    compartment_path: list[str] | None = None,
    parent_ocid: list[str] | None = None,
    parent_path: list[str] | None = None,
    include_children: bool = False,
    matching_rule: list[str] | None = None,
    in_use: bool | None = None,
    principal: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Resolve identities and memberships through one compact MCP tool."""

    tool_name = 'identity_search'
    _log_mcp_call_input(
        tool_name,
        {
            'operation': operation,
            'entity_types': entity_types,
            'domain_name': domain_name,
            'name': name,
            'ocid': ocid,
            'compartment_path': compartment_path,
            'parent_ocid': parent_ocid,
            'parent_path': parent_path,
            'include_children': include_children,
            'matching_rule': matching_rule,
            'in_use': in_use,
            'principal': principal,
            'limit': limit,
        },
    )
    try:
        principal = dict(principal or {})
        domains = domain_name or _as_str_list(principal.get('domain_name'))
        names = name or _as_str_list(principal.get('name') or principal.get('display_name'))
        ocids = ocid or _as_str_list(principal.get('ocid'))
        compartment_ocids = ocid or _as_str_list(
            principal.get('compartment_ocid') or principal.get('resource_compartment_ocid') or principal.get('ocid')
        )
        compartment_paths = compartment_path or _as_str_list(
            principal.get('compartment_path') or principal.get('resource_compartment_path')
        )
        bounded_limit = _clamp_limit(limit)

        if operation == 'groups_for_user':
            user: User = {
                'domain_name': domains[0] if domains else 'Default',
                'user_name': names[0] if names else '',
            }
            if ocids:
                user['user_ocid'] = ocids[0]
            groups = _query_service().get_groups_for_user(user)
            return _log_mcp_call_output(
                tool_name,
                {'operation': operation, 'groups': groups[:bounded_limit], 'total_count': len(groups)},
            )

        if operation == 'members_for_group':
            group: Group = {
                'domain_name': domains[0] if domains else 'Default',
                'group_name': names[0] if names else '',
            }
            if ocids:
                group['group_ocid'] = ocids[0]
            users = _query_service().get_users_for_group(group)
            return _log_mcp_call_output(
                tool_name,
                {'operation': operation, 'users': users[:bounded_limit], 'total_count': len(users)},
            )

        requested_types = set(entity_types or ['user', 'group', 'dynamic-group'])
        response: dict[str, Any] = {'operation': operation, 'entity_types': sorted(requested_types)}
        total = 0
        if 'user' in requested_types:
            users = _query_service().search_users(
                UserSearch(domain_name=domains, search=names, user_ocid=ocids[0] if ocids else '')
            )
            response['users'] = users[:bounded_limit]
            response['total_users'] = len(users)
            total += len(users)
        if 'group' in requested_types:
            groups = _query_service().search_groups(
                GroupSearch(domain_name=domains, group_name=names, group_ocid=ocids)
            )
            response['groups'] = groups[:bounded_limit]
            response['total_groups'] = len(groups)
            total += len(groups)
        if 'dynamic-group' in requested_types:
            dynamic_group_filters: DynamicGroupSearch = DynamicGroupSearch(
                domain_name=domains,
                dynamic_group_name=names,
                dynamic_group_ocid=ocids[0] if ocids else '',
                matching_rule=matching_rule or [],
            )
            if in_use is not None:
                dynamic_group_filters['in_use'] = in_use
            dynamic_groups = _query_service().search_dynamic_groups(dynamic_group_filters)
            response['dynamic_groups'] = dynamic_groups[:bounded_limit]
            response['total_dynamic_groups'] = len(dynamic_groups)
            total += len(dynamic_groups)
        if 'compartment' in requested_types:
            compartments = _search_compartments(
                _require_service_context().policy_repo,
                names=names,
                ocids=compartment_ocids,
                paths=compartment_paths,
                parent_ocids=parent_ocid,
                parent_paths=parent_path,
                include_children=include_children,
            )
            response['compartments'] = compartments[:bounded_limit]
            response['total_compartments'] = len(compartments)
            total += len(compartments)
        response['total_count'] = total
        response['truncated'] = any(
            int(response.get(key, 0)) > bounded_limit
            for key in ('total_users', 'total_groups', 'total_dynamic_groups', 'total_compartments')
        )
        _track_mcp_tool(tool_name, status='success', count=total)
        return _log_mcp_call_output(tool_name, response)
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in identity_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in identity_search: {exc}') from exc


@mcp.tool(name='data_operations', description='Inspect or change MCP data state: status, caches, load cache, reload.')
def data_operations(
    operation: Literal['get_status', 'list_caches', 'cache_metadata', 'load_cache', 'reload'] = 'get_status',
    cache_name: str = '',
    tenancy_name: str = '',
) -> dict[str, Any]:
    """Manage data state and cache visibility."""

    tool_name = 'data_operations'
    _log_mcp_call_input(
        tool_name,
        {'operation': operation, 'cache_name': cache_name, 'tenancy_name': tenancy_name},
    )
    try:
        ctx = _require_service_context()
        repo = ctx.policy_repo
        manager = CacheManager()

        if operation == 'get_status':
            return _log_mcp_call_output(
                tool_name,
                {
                    'operation': operation,
                    'tenancy_name': repo.tenancy_name,
                    'tenancy_ocid': repo.tenancy_ocid,
                    'data_as_of': repo.data_as_of,
                    'regular_statements': len(repo.regular_statements),
                    'cross_tenancy_statements': len(repo.cross_tenancy_statements),
                    'defined_aliases': len(repo.defined_aliases),
                    'users': len(repo.users),
                    'groups': len(repo.groups),
                    'dynamic_groups': len(repo.dynamic_groups),
                    'loaded_from_tenancy': bool(getattr(repo, 'policies_loaded_from_tenancy', False)),
                },
            )

        if operation == 'list_caches':
            cache_names = manager.get_available_cache(tenancy_name or None)
            return _log_mcp_call_output(
                tool_name,
                {
                    'operation': operation,
                    'caches': [_cache_metadata(name) for name in cache_names],
                    'total_count': len(cache_names),
                },
            )

        if operation == 'cache_metadata':
            if not cache_name:
                raise ToolError('cache_metadata requires cache_name.')
            return _log_mcp_call_output(tool_name, {'operation': operation, 'cache': _cache_metadata(cache_name)})

        if operation == 'load_cache':
            if not cache_name:
                raise ToolError('load_cache requires cache_name.')
            loaded = manager.load_combined_cache(policy_analysis=repo, named_cache=cache_name)
            return _log_mcp_call_output(
                tool_name,
                {
                    'operation': operation,
                    'status': 'success',
                    'loaded': loaded,
                    'cache_name': cache_name,
                    'regular_statements': len(repo.regular_statements),
                    'users': len(repo.users),
                    'groups': len(repo.groups),
                    'dynamic_groups': len(repo.dynamic_groups),
                    'data_as_of': repo.data_as_of,
                },
            )

        if operation == 'reload':
            result = _reload_mcp_data()
            result['operation'] = operation
            return _log_mcp_call_output(tool_name, result)

        raise ToolError(f'Unsupported data operation: {operation}')
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in data_operations: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in data_operations: {exc}') from exc


@mcp.tool(name='cross_tenancy_search', description='List aliases or search cross-tenancy policy statements.')
def cross_tenancy_search(
    operation: Literal['list_aliases', 'policies_by_alias', 'search'] = 'list_aliases',
    alias: str = '',
    statement_text: list[str] | None = None,
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Consolidated cross-tenancy alias and statement search."""

    tool_name = 'cross_tenancy_search'
    _log_mcp_call_input(
        tool_name,
        {
            'operation': operation,
            'alias': alias,
            'statement_text': statement_text,
            'principal': principal,
        },
    )
    try:
        service = _query_service()
        if operation == 'list_aliases':
            aliases = [_normalize_policy_statement_for_mcp(stmt) for stmt in service.list_cross_tenancy_aliases()]
            return _log_mcp_call_output(
                tool_name,
                {'operation': operation, 'aliases': aliases, 'total_count': len(aliases)},
            )

        if operation == 'policies_by_alias':
            if not alias:
                raise ToolError('policies_by_alias requires alias.')
            statements = [
                _normalize_policy_statement_for_mcp(stmt)
                for stmt in service.filter_cross_tenancy_policies_by_alias(alias)
            ]
            return _log_mcp_call_output(
                tool_name,
                {'operation': operation, 'statements': statements, 'total_count': len(statements)},
            )

        terms = [term.casefold() for term in _as_str_list(statement_text)]
        principal_terms = [term.casefold() for term in _as_str_list((principal or {}).get('name'))]
        rows = list(getattr(_require_service_context().policy_repo, 'cross_tenancy_statements', []) or [])
        if alias:
            rows = service.filter_cross_tenancy_policies_by_alias(alias)
        if terms:
            rows = [
                row for row in rows if any(term in str(row.get('statement_text') or '').casefold() for term in terms)
            ]
        if principal_terms:
            rows = [
                row
                for row in rows
                if any(term in str(row.get('statement_text') or '').casefold() for term in principal_terms)
            ]
        statements = [_normalize_policy_statement_for_mcp(stmt) for stmt in rows]
        _track_mcp_tool(tool_name, status='success', count=len(statements))
        return _log_mcp_call_output(
            tool_name,
            {'operation': operation, 'statements': statements, 'total_count': len(statements)},
        )
    except ToolError:
        _track_mcp_tool(tool_name, status='error')
        raise
    except Exception as exc:
        _track_mcp_tool(tool_name, status='error')
        logger.error('Unhandled error in cross_tenancy_search: %s', exc, exc_info=True)
        raise ToolError(f'Unhandled error in cross_tenancy_search: {exc}') from exc


def _reload_mcp_data() -> dict[str, Any]:
    """Reload live policy and identity data for the active standalone MCP context."""

    ctx = _require_service_context()
    repo = ctx.policy_repo

    try:
        if not getattr(repo, 'policies_loaded_from_tenancy', False):
            raise ToolError(
                'Data reload is only supported when running with a profile, instance principal, or session token'
            )

        auth_args = globals().get('args')
        if auth_args is None:
            raise ToolError('Reload is only supported for standalone MCP runs.')

        result = LoadService(ctx).load_from_tenancy(
            use_instance_principal=bool(getattr(auth_args, 'instance_principal', False)),
            use_resource_principal=bool(getattr(auth_args, 'resource_principal', False)),
            profile=getattr(auth_args, 'profile', None) or None,
            session_token=getattr(auth_args, 'session_token', None) or None,
            recursive=bool(getattr(auth_args, 'recursive', True)),
            compartment_domain_search_depth=int(getattr(auth_args, 'compartment_domain_search_depth', 1) or 1),
            post_load_profile='minimal',
            save_cache_after_load=True,
        )
        if not result.success:
            raise ToolError(result.message)

        logger.info('Data reloaded successfully')
        return {
            'status': 'success',
            'message': 'Data reloaded successfully',
            'total_policies': len(repo.regular_statements),
            'data_as_of': repo.data_as_of,
        }
    except Exception as e:
        logger.error(f'Failed to reload data: {e}')
        raise ToolError(f'Failed to reload data: {e}') from e


# ============================================================
# EMBEDDED SERVER CONTROL (for Tkinter integration)
# ============================================================

server_thread: threading.Thread | None = None
server_instance: Server | None = None
server_running: bool = False


def start_mcp_server_in_thread(settings: dict):
    """
    Start MCP server in a background thread (for Tkinter integration).

    Args:
        config (dict): MCP server config {host, port, key_path, cert_path, ...}
        log_fn (callable): optional logger callback, e.g. PopupConsole.write_line()
    """
    global server_thread, server_instance, server_running

    # prevent multiple starts
    if server_thread and server_thread.is_alive():
        logger.info('MCP server is already running.')
        return

    # Set the boolean for running status before starting the thread to prevent race conditions in status checks
    server_running = False  # reset

    def _run():
        global server_running
        try:
            logger.info(
                f'Starting FastMCP server on {settings.get("mcp_host", "127.0.0.1")}:{settings.get("mcp_port", 8765)}'
            )
            server_running = True
            mcp.run(
                transport='streamable-http',
                port=settings.get('mcp_port', 8765),
                host=settings.get('mcp_host', '127.0.0.1'),
                show_banner=False,
            )
        except Exception as e:
            logger.exception(f'MCP server crashed: {e}')
        finally:
            logger.info('MCP server thread exited.')
            server_running = False

    # run uvicorn in a daemon thread so Tkinter stays responsive
    server_thread = threading.Thread(target=_run, daemon=True)
    server_thread.start()


def mcp_server_status() -> bool:
    """
    Check if the MCP server is currently running.

    Returns:
        bool: True if the server is running, False otherwise.
    """
    global server_thread
    return bool(server_thread and server_thread.is_alive())


# ============================================================
# Main Entry Point for standalone MCP server run
# ============================================================


def _build_arg_parser():
    parser = argparse.ArgumentParser()
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument('--profile')
    auth.add_argument('--instance-principal', action='store_true')
    auth.add_argument('--resource-principal', action='store_true')
    auth.add_argument('--use-cache', help='provide the combined cache date to use', required=False, default=None)
    auth.add_argument('--session-token', help='OCI session token for instance principal auth', default=None)
    parser.add_argument(
        '--recursive', action='store_true', default=True, help='Recursively load all compartments (default: True)'
    )
    parser.add_argument(
        '--dont-save-cache-after-load', help='Save the combined cache after loading from OCI', action='store_true'
    )
    parser.add_argument('--transport', default='stdio', choices=['stdio', 'streamable-http'])
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument(
        '--compartment-domain-search-depth',
        type=int,
        default=1,
        choices=range(1, 7),
        metavar='[1-6]',
        help='Depth for identity-domain compartment traversal (1=root only, 2=include direct children, max=6).',
    )
    parser.add_argument(
        '--log-level',
        default='WARNING',
        choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'critical', 'error', 'warning', 'info', 'debug'],
        help='Application and MCP framework log level for standalone MCP mode (default: WARNING).',
    )
    return parser


def main():
    """
    Entry point for the OCI Policy Analysis Standalone MCP Server.

    Parses command-line arguments to load, filter, display, or export OCI identity and policy information
    from Oracle Cloud Infrastructure (OCI) using cached or live data.
    """
    logger.info('MCP server module logger initialized.')

    global args
    args = _build_arg_parser().parse_args()
    args.log_level = str(args.log_level).upper()
    set_log_level(args.log_level, announce=False)
    logging.getLogger('mcp').setLevel(args.log_level)
    logging.getLogger('mcp.server').setLevel(args.log_level)
    recursive = args.recursive

    logger.info(
        f'Loading MCP Server using Profile={args.profile or "DEFAULT"}, '
        f'InstancePrincipal={args.instance_principal}, '
        f'ResourcePrincipal={args.resource_principal}, '
        f'Recursive={recursive}, '
        f'CompartmentDomainSearchDepth={args.compartment_domain_search_depth}, '
        f'Transport={args.transport}'
    )

    global app_context
    app_context = _build_service_context(args.log_level)
    load_service = LoadService(app_context)

    try:
        if args.use_cache:
            result = load_service.load_from_cache(args.use_cache, post_load_profile='minimal')
        else:
            result = load_service.load_from_tenancy(
                use_instance_principal=args.instance_principal,
                use_resource_principal=bool(args.resource_principal),
                profile=args.profile or None,
                session_token=args.session_token or None,
                recursive=recursive,
                compartment_domain_search_depth=args.compartment_domain_search_depth,
                post_load_profile='minimal',
                save_cache_after_load=not args.dont_save_cache_after_load,
            )
        if not result.success:
            logger.error('MCP data load failed: %s', result.message)
            sys.exit(2)
    except Exception as e:
        logger.warning(f'Policy and Identity domains load failed: {e}')
        sys.exit(2)

    repo = app_context.policy_repo
    logger.info(
        f'Tenancy loaded ({"from cache" if args.use_cache else "live"}). Policies: {len(repo.regular_statements)} regular, '
        f'{len(repo.cross_tenancy_statements)} cross-tenancy; '
        f'Groups: {len(repo.groups)}; Users: {len(repo.users)}; '
        f'Dynamic Groups: {len(repo.dynamic_groups)}'
    )

    # --- Start MCP Server ---
    if args.transport == 'stdio':
        logger.info(
            'Starting MCP server in stdio mode - if you get errors, please ensure you set environment variable MCP_STDIO_MODE=1'
        )
        mcp.run(transport='stdio', show_banner=False, log_level=args.log_level.lower())
        # mcp.run(transport='stdio', show_banner=False)
    else:
        mcp.run(
            transport='streamable-http',
            port=args.port,
            host=args.host,
            log_level=args.log_level.lower(),
            show_banner=False,
        )


if __name__ == '__main__':
    main()
