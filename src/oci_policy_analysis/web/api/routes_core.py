"""Core FastAPI routes for cache load and intelligence."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from oci_policy_analysis.application.services.analysis_service import AnalysisService
from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService
from oci_policy_analysis.application.services.consolidation_workbench_service import (
    ConsolidationWorkbenchService,
)
from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService
from oci_policy_analysis.application.services.intelligence_service import IntelligenceService
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.application.services.permissions_report_service import PermissionsReportService
from oci_policy_analysis.application.services.policy_browser_service import PolicyBrowserService
from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService
from oci_policy_analysis.application.services.prospective_builder_service import ProspectiveBuilderService
from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict
from oci_policy_analysis.common import config
from oci_policy_analysis.common.helpers import (
    for_display_dynamic_group,
    for_display_group,
    for_display_policy,
    for_display_user,
)
from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import (
    DynamicGroup,
    DynamicGroupSearch,
    Group,
    GroupSearch,
    PolicySearch,
    User,
    UserSearch,
)
from oci_policy_analysis.logic.prospective_statements_service import ProspectiveStatementsService
from oci_policy_analysis.web.dependencies import get_context, get_settings

logger = get_logger(component='web_routes')
router = APIRouter()
condition_tester_service = ConditionTesterService()


def _get_or_init_prospective_service(ctx) -> ProspectiveStatementsService:
    """Return a tenancy-scoped prospective service for the current web context."""

    existing = getattr(ctx, '_prospective_service', None)
    tenancy_ocid = str(getattr(ctx.policy_repo, 'tenancy_ocid', '') or '').strip()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')

    if isinstance(existing, ProspectiveStatementsService) and existing.tenancy_ocid == tenancy_ocid:
        return existing

    service = ProspectiveStatementsService(
        cache_manager=ctx.cache,
        policy_repo=ctx.policy_repo,
        tenancy_ocid=tenancy_ocid,
    )
    ctx._prospective_service = service
    return service


def _split_pipe(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split('|') if part.strip()]


def _build_stage_collector() -> tuple[list[dict[str, str]], Any]:
    stages: list[dict[str, str]] = []

    def on_stage(stage: str, detail: str, state: str) -> None:
        stages.append(
            {
                'stage': stage,
                'detail': detail,
                'state': state,
                'timestamp': datetime.now(UTC).isoformat(),
            }
        )

    return stages, on_stage


def _normalize_statement_text_for_key(statement_text: str) -> str:
    """Normalize statement text for stable key generation."""
    return re.sub(r'\s+', ' ', statement_text.strip()).casefold()


def _build_cross_tenancy_stable_key(policy_ocid: str, statement_text: str) -> str:
    """Build parser-independent stable key for cross-tenancy statement rows."""
    payload = f'{policy_ocid}|{_normalize_statement_text_for_key(statement_text)}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _build_engine_principal_value(principal_type: str, principal_display: str) -> object:
    """Convert web principal display into engine principal payload."""

    ptype = (principal_type or '').strip()
    display = (principal_display or '').strip()

    if ptype in ('any-user', 'any-group', 'service'):
        return display or ptype

    if '/' in display:
        domain, name = display.split('/', 1)
        return (domain if domain != '' else None, name)

    if display:
        return (None, display)

    return ''


def _simulation_context_options(ctx) -> dict[str, object]:
    """Build context dropdown options for simulation workbench."""

    repo = ctx.policy_repo
    sim = ctx.simulation

    compartments: set[str] = set()
    for comp in getattr(repo, 'compartments', []) or []:
        if isinstance(comp, dict):
            path = str(comp.get('hierarchy_path') or '').strip()
        else:
            path = str(getattr(comp, 'hierarchy_path', '') or '').strip()
        if path:
            compartments.add(path)
    if not compartments:
        compartments.add('ROOT')

    principals_by_type: dict[str, set[tuple[str | None, str]]] = {}
    principal_types: set[str] = set()
    for stmt in getattr(repo, 'regular_statements', []) or []:
        subject_type = str(stmt.get('subject_type') or '').strip()
        subjects = stmt.get('subject') or []
        if not subject_type or not isinstance(subjects, list):
            continue
        principal_types.add(subject_type)
        principals_by_type.setdefault(subject_type, set())
        for subj in subjects:
            if isinstance(subj, (list | tuple)) and len(subj) == 2:
                domain, name = subj
                if isinstance(name, str) and name.strip():
                    dom = None if str(domain).lower() == 'default' else (str(domain) if domain else None)
                    principals_by_type[subject_type].add((dom, name.strip()))
            elif isinstance(subj, str) and subj.strip():
                principals_by_type[subject_type].add((None, subj.strip()))

    users = getattr(repo, 'users', []) or []
    if users:
        principal_types.add('user')
        principals_by_type.setdefault('user', set())
        for entry in users:
            domain = entry.get('domain_name') if isinstance(entry, dict) else None
            name = entry.get('user_name') if isinstance(entry, dict) else None
            if isinstance(name, str) and name.strip():
                dom = None if str(domain).lower() == 'default' else (str(domain) if domain else None)
                principals_by_type['user'].add((dom, name.strip()))

    principal_display_map: dict[str, list[str]] = {}
    for ptype in sorted(principal_types):
        tuples = sorted(principals_by_type.get(ptype, set()), key=lambda t: ((t[0] or ''), t[1]))
        principal_display_map[ptype] = [f'{d}/{n}' if d else n for (d, n) in tuples]

    api_operations = sim.get_api_operations('') if sim else []
    return {
        'compartments': sorted(compartments),
        'principal_types': sorted(principal_types),
        'principals_by_type': principal_display_map,
        'api_operations': api_operations,
    }


def _statement_to_web_row(stmt: dict[str, Any]) -> dict[str, Any]:
    """Normalize statement payload for simulation workbench table/inspector."""

    action = str(stmt.get('action') or 'allow').lower()
    return {
        'internal_id': str(stmt.get('internal_id') or ''),
        'policy_name': str(stmt.get('policy_name') or stmt.get('description') or ''),
        'policy_path': str(stmt.get('compartment_path') or ''),
        'effective_path': str(stmt.get('effective_path') or ''),
        'statement_text': str(stmt.get('statement_text') or ''),
        'action': action,
        'subject_type': stmt.get('subject_type'),
        'subject': stmt.get('subject'),
        'principals': stmt.get('principals'),
        'verb': stmt.get('verb'),
        'resource': stmt.get('resource'),
        'permission': stmt.get('permission'),
        'conditions': stmt.get('conditions'),
        'valid': stmt.get('valid'),
        'parsed': stmt.get('parsed'),
        'is_prospective': bool(stmt.get('is_prospective')),
    }


@router.get('/health')
def health() -> dict[str, str]:
    logger.info('GET /health')
    return {'status': 'ok'}


@router.get('/caches')
def list_caches() -> dict[str, list[str]]:
    logger.info('GET /caches')
    ctx = get_context()
    caches = ctx.cache.get_available_cache(tenancy_name=None)
    return {'caches': caches}


@router.get('/caches/details')
def list_cache_details() -> dict[str, list[dict[str, object]]]:
    """Return cache details for management views."""
    logger.info('GET /caches/details')
    ctx = get_context()
    cache_names = ctx.cache_service.list_caches(tenancy_name=None)
    preserved = ctx.cache_service.get_preserved_cache_set()
    details: list[dict[str, object]] = []
    for cache_name in cache_names:
        file_path = ctx.cache.cache_dir / f'combined_cache_{cache_name}.json'
        size_bytes = file_path.stat().st_size if file_path.exists() else 0
        details.append(
            {
                'name': cache_name,
                'preserved': cache_name in preserved,
                'size_bytes': size_bytes,
            }
        )
    return {'caches': details}


@router.post('/caches/rename')
def rename_cache(payload: dict[str, object]) -> dict[str, object]:
    logger.info('POST /caches/rename')
    ctx = get_context()
    old_name = str(payload.get('old_name') or '').strip()
    new_name = str(payload.get('new_name') or '').strip()
    if not old_name or not new_name:
        return {'success': False, 'message': 'Both old_name and new_name are required.'}
    ok = ctx.cache_service.rename_cache(old_name, new_name)
    return {
        'success': ok,
        'message': 'Cache renamed.' if ok else 'Unable to rename cache. Check duplicate names and format.',
    }


@router.post('/caches/delete')
def delete_cache(payload: dict[str, object]) -> dict[str, object]:
    logger.info('POST /caches/delete')
    ctx = get_context()
    cache_name = str(payload.get('name') or '').strip()
    if not cache_name:
        return {'success': False, 'message': 'Cache name is required.'}
    ok = ctx.cache_service.remove_cache(cache_name)
    return {'success': ok, 'message': 'Cache deleted.' if ok else 'Unable to delete cache.'}


@router.get('/caches/download/{cache_name}')
def download_cache(cache_name: str, export_name: str | None = None) -> FileResponse:
    logger.info('GET /caches/download/%s', cache_name)
    ctx = get_context()
    file_path = ctx.cache.cache_dir / f'combined_cache_{cache_name}.json'
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='Cache file not found.')
    safe_name = (export_name or cache_name).strip() or cache_name
    download_name = f'{safe_name}.json'
    return FileResponse(path=file_path, media_type='application/json', filename=download_name)


@router.get('/settings')
def get_settings_api() -> dict[str, object]:
    """Return persisted settings used by the web app."""
    logger.info('GET /settings')
    settings = get_settings()
    return {'settings': settings}


@router.post('/settings')
def update_settings_api(payload: dict[str, object]) -> dict[str, object]:
    """Update settings and persist to disk."""
    logger.info('POST /settings')
    settings = get_settings()
    updates = payload.get('settings') if isinstance(payload, dict) else None
    if isinstance(updates, dict):
        settings.update(updates)
    config.save_settings(settings)
    return {'settings': settings}


@router.post('/load/cache/{cache_name}')
def load_cache(cache_name: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    logger.info('POST /load/cache/%s', cache_name)
    ctx = get_context()
    service = LoadService(ctx)
    stages, on_stage = _build_stage_collector()
    body = payload or {}
    run_post_load_intelligence = body.get('run_post_load_intelligence')
    result = service.load_from_cache(
        cache_name=cache_name,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }


@router.post('/intelligence/run')
def run_intelligence() -> dict[str, object]:
    logger.info('POST /intelligence/run')
    ctx = get_context()
    service = IntelligenceService(ctx)
    result = service.run_all()
    return {'overlay': result.overlay}


@router.get('/intelligence/strategies')
def list_intelligence_strategies() -> dict[str, object]:
    """Return intelligence strategy metadata for settings pages.

    Returns:
        dict[str, object]: List of configured strategy IDs and display metadata.
    """
    logger.info('GET /intelligence/strategies')
    ctx = get_context()
    engine = ctx.intelligence
    strategies = []
    for sid, display_name, category in engine.get_strategies_for_settings():
        strategies.append({'strategy_id': sid, 'display_name': display_name, 'category': category})
    return {'strategies': strategies}


@router.post('/analysis/historical-compare')
def historical_compare(payload: dict[str, object]) -> dict[str, object]:
    """Compare two named caches and return normalized sectioned diff results."""
    logger.info('POST /analysis/historical-compare')
    left_cache = str(payload.get('left_cache') or '').strip()
    right_cache = str(payload.get('right_cache') or '').strip()
    if not left_cache or not right_cache:
        raise HTTPException(status_code=400, detail='left_cache and right_cache are required.')

    ctx = get_context()
    service = HistoricalAnalysisService(ctx.cache)
    result = service.compare_caches(left_cache=left_cache, right_cache=right_cache)

    def _section_to_dict(section) -> dict[str, object]:
        return {
            'section': section.section,
            'key': section.key,
            'added': section.added,
            'removed': section.removed,
            'modified': section.modified,
            'items': [
                {
                    'action': item.action,
                    'section': item.section,
                    'stable_key': item.stable_key,
                    'title': item.title,
                    'old_value': item.old_value,
                    'new_value': item.new_value,
                    'changed_fields': item.changed_fields,
                }
                for item in section.items
            ],
        }

    return {
        'left_cache': result.left_cache,
        'right_cache': result.right_cache,
        'policy_sections': [_section_to_dict(s) for s in result.policy_sections],
        'identity_sections': [_section_to_dict(s) for s in result.identity_sections],
    }


@router.post('/filter/policies')
def filter_policies(payload: dict[str, object]) -> dict[str, object]:
    logger.info('POST /filter/policies')
    ctx = get_context()
    service = AnalysisService(ctx)
    raw_filters = payload.get('filters') or {}
    sort_by = str(payload.get('sort_by') or '').strip()
    sort_dir = str(payload.get('sort_dir') or 'asc').strip().lower()
    filters = build_policy_search_from_dict(raw_filters if isinstance(raw_filters, dict) else {})
    result = service.filter_policy_statements(filters=filters)

    statements = list(result.statements or [])

    def _lookup(statement: dict[str, Any], key: str) -> str:
        if key in statement:
            return str(statement.get(key) or '')
        title_key = key.replace('_', ' ').title()
        if title_key in statement:
            return str(statement.get(title_key) or '')
        return ''

    if sort_by:
        reverse = sort_dir == 'desc'
        statements.sort(key=lambda row: _lookup(cast(dict[str, Any], row), sort_by).casefold(), reverse=reverse)

    return {
        'total': result.total,
        'matched': result.matched,
        'statements': statements,
    }


@router.get('/entities/groups')
def list_groups(search: str = '') -> dict[str, object]:
    """Return groups for User/Group analysis with optional pipe-delimited search."""
    logger.info('GET /entities/groups')
    ctx = get_context()
    repo = ctx.policy_repo
    group_filter: GroupSearch = GroupSearch(group_name=_split_pipe(search))
    groups: list[Group] = repo.filter_groups(group_filter=group_filter)
    output = []
    for g in groups:
        row = for_display_group(g)
        row['User Count'] = len(repo.get_users_for_group(g))
        output.append(row)
    return {
        'total': len(getattr(repo, 'groups', []) or []),
        'matched': len(output),
        'groups': output,
    }


@router.get('/entities/users')
def list_users(search: str = '') -> dict[str, object]:
    """Return users for User/Group analysis with optional pipe-delimited search."""
    logger.info('GET /entities/users')
    ctx = get_context()
    repo = ctx.policy_repo
    user_filter: UserSearch = UserSearch(search=_split_pipe(search))
    users: list[User] = repo.filter_users(user_filter=user_filter)
    output = []
    for u in users:
        row = for_display_user(u)
        # Expose raw membership/details so web pages can reliably derive
        # selected-user -> deduped-group filters without parsing display strings.
        row['groups'] = list(u.get('groups') or [])
        row['domain_name'] = str(u.get('domain_name') or 'Default')
        row['user_name'] = str(u.get('user_name') or '')
        output.append(row)
    return {
        'total': len(getattr(repo, 'users', []) or []),
        'matched': len(output),
        'users': output,
    }


@router.get('/entities/dynamic-groups')
def list_dynamic_groups(
    domain: str = '', name: str = '', matching_rule: str = '', dynamic_group_ocid: str = ''
) -> dict[str, object]:
    """Return dynamic groups with optional filters (pipe-delimited OR semantics)."""
    logger.info('GET /entities/dynamic-groups')
    ctx = get_context()
    repo = ctx.policy_repo
    filters: DynamicGroupSearch = cast(
        DynamicGroupSearch,
        {
            'domain_name': _split_pipe(domain),
            'dynamic_group_name': _split_pipe(name),
            'matching_rule': _split_pipe(matching_rule),
            'dynamic_group_ocid': _split_pipe(dynamic_group_ocid),
        },
    )
    dynamic_groups: list[DynamicGroup] = repo.filter_dynamic_groups(filters)
    output = [for_display_dynamic_group(dg) for dg in dynamic_groups]
    return {
        'total': len(getattr(repo, 'dynamic_groups', []) or []),
        'matched': len(output),
        'dynamic_groups': output,
    }


@router.get('/metadata/resource-types')
def list_resource_types() -> dict[str, list[str]]:
    """Return dynamically discovered Resource Type values for RP filtering."""
    logger.info('GET /metadata/resource-types')
    ctx = get_context()
    principal_service = PrincipalAnalysisService(ctx)
    return {'resource_types': principal_service.get_resource_types()}


@router.post('/filter/policies/by-subjects')
def filter_policies_by_subjects(payload: dict[str, object]) -> dict[str, object]:  # noqa: C901
    """Filter policies by exact selected groups/users/dynamic groups and optional any-user/group expansion."""
    logger.info('POST /filter/policies/by-subjects')
    ctx = get_context()
    repo = ctx.policy_repo

    exact_groups_payload = payload.get('exact_groups')
    exact_users_payload = payload.get('exact_users')
    exact_dynamic_groups_payload = payload.get('exact_dynamic_groups')
    include_any_subjects = bool(payload.get('include_any_subjects'))
    subject_type_filter = _split_pipe(str(payload.get('subject_type') or ''))
    subject_filter_terms = _split_pipe(str(payload.get('subject') or ''))
    principal_filter_terms = _split_pipe(str(payload.get('principal') or ''))

    exact_groups: list[Group] = []
    if isinstance(exact_groups_payload, list):
        for item in exact_groups_payload:
            if isinstance(item, dict):
                domain_name = str(item.get('domain_name') or 'Default')
                group_name = str(item.get('group_name') or '')
                if group_name:
                    exact_groups.append({'domain_name': domain_name, 'group_name': group_name})

    exact_users: list[User] = []
    if isinstance(exact_users_payload, list):
        for item in exact_users_payload:
            if isinstance(item, dict):
                domain_name = str(item.get('domain_name') or 'Default')
                user_name = str(item.get('user_name') or '')
                if user_name:
                    exact_users.append({'domain_name': domain_name, 'user_name': user_name})

    exact_dynamic_groups: list[DynamicGroup] = []
    if isinstance(exact_dynamic_groups_payload, list):
        for item in exact_dynamic_groups_payload:
            if isinstance(item, dict):
                domain_name = str(item.get('domain_name') or 'Default')
                dynamic_group_name = str(item.get('dynamic_group_name') or '')
                dynamic_group_ocid = str(item.get('dynamic_group_ocid') or '')
                if dynamic_group_name or dynamic_group_ocid:
                    exact_dynamic_groups.append(
                        {
                            'domain_name': domain_name,
                            'dynamic_group_name': dynamic_group_name,
                            'dynamic_group_ocid': dynamic_group_ocid,
                        }
                    )

    logger.debug(
        '[by-subjects] payload summary: exact_groups=%d exact_users=%d exact_dynamic_groups=%d include_any_subjects=%s subject_type_terms=%d subject_terms=%d principal_terms=%d',
        len(exact_groups),
        len(exact_users),
        len(exact_dynamic_groups),
        include_any_subjects,
        len(subject_type_filter),
        len(subject_filter_terms),
        len(principal_filter_terms),
    )
    logger.debug('[by-subjects] exact_groups=%s', exact_groups)
    if exact_users:
        logger.debug('[by-subjects] exact_users=%s', exact_users)
    if exact_dynamic_groups:
        logger.debug('[by-subjects] exact_dynamic_groups=%s', exact_dynamic_groups)

    policy_filter: PolicySearch = {}
    if exact_groups:
        policy_filter['exact_groups'] = exact_groups
    if exact_users:
        policy_filter['exact_users'] = exact_users
    if exact_dynamic_groups:
        policy_filter['exact_dynamic_groups'] = exact_dynamic_groups

    logger.debug('[by-subjects] derived policy_filter=%s', policy_filter)

    statements = repo.filter_policy_statements(filters=policy_filter)
    logger.debug('[by-subjects] base matched count=%d', len(statements))

    if include_any_subjects:
        extra = repo.filter_policy_statements(filters=PolicySearch(subject=['any-user', 'any-group']))
        logger.debug('[by-subjects] include_any_subjects extra candidates=%d', len(extra))
        seen = {st.get('internal_id') or st.get('statement_text') for st in statements}
        for st in extra:
            key = st.get('internal_id') or st.get('statement_text')
            if key not in seen:
                statements.append(st)
                seen.add(key)
        logger.debug('[by-subjects] count after include_any_subjects merge=%d', len(statements))

    # Optional secondary narrowing by subject_type/subject/principal details.
    if subject_type_filter or subject_filter_terms or principal_filter_terms:
        subject_type_filter_cf = [s.casefold() for s in subject_type_filter]
        subject_filter_cf = [s.casefold() for s in subject_filter_terms]
        principal_filter_cf = [s.casefold() for s in principal_filter_terms]

        def _matches_terms(value: str, terms: list[str]) -> bool:
            val = value.casefold()
            return any(term in val for term in terms)

        filtered_statements = []
        for st in statements:
            st_subject_type = str(st.get('subject_type') or '').casefold()
            st_subject = st.get('subject')
            st_principals = st.get('principals')

            if subject_type_filter_cf and st_subject_type not in subject_type_filter_cf:
                continue

            if subject_filter_cf:
                if isinstance(st_subject, list):
                    subject_values = [str(v) for v in st_subject]
                else:
                    subject_values = [str(st_subject or '')]
                if not any(_matches_terms(v, subject_filter_cf) for v in subject_values):
                    continue

            if principal_filter_cf:
                principal_values: list[str] = []
                if isinstance(st_principals, list):
                    for p in st_principals:
                        if isinstance(p, dict):
                            principal_values.extend(
                                [
                                    str(p.get('display_name') or ''),
                                    str(p.get('principal_name') or ''),
                                    str(p.get('principal_key') or ''),
                                    str(p.get('principal_type') or ''),
                                ]
                            )
                if not any(_matches_terms(v, principal_filter_cf) for v in principal_values):
                    continue

            filtered_statements.append(st)

        statements = filtered_statements
        logger.debug('[by-subjects] count after subject/principal narrowing=%d', len(statements))

    selected_groups: list[dict[str, str]] = []
    if exact_groups:
        selected_groups = [
            {'Domain': g.get('domain_name') or 'Default', 'Group': g.get('group_name') or ''} for g in exact_groups
        ]
    elif exact_users:
        for u in exact_users:
            groups_for_user = repo.get_groups_for_user(u)
            for g in groups_for_user:
                selected_groups.append(
                    {
                        'Domain': g.get('domain_name') or 'Default',
                        'Group': g.get('group_name') or '',
                    }
                )

    selected_groups_unique = []
    seen_groups: set[tuple[str, str]] = set()
    for g in selected_groups:
        key = (g.get('Domain', 'Default'), g.get('Group', ''))
        if key not in seen_groups:
            seen_groups.add(key)
            selected_groups_unique.append(g)

    logger.debug(
        '[by-subjects] selected_groups_unique=%d final_matched=%d total_regular=%d',
        len(selected_groups_unique),
        len(statements),
        len(getattr(repo, 'regular_statements', []) or []),
    )
    logger.debug('[by-subjects] selected_groups_unique=%s', selected_groups_unique)

    return {
        'total': len(getattr(repo, 'regular_statements', []) or []),
        'matched': len(statements),
        'statements': [for_display_policy(st) for st in statements],
        'selected_groups': selected_groups_unique,
    }


@router.get('/analysis/cross-tenancy')
def get_cross_tenancy_basic() -> dict[str, object]:
    """Return basic cross-tenancy rows for web display with stable keys."""
    logger.info('GET /analysis/cross-tenancy')
    ctx = get_context()
    repo = ctx.policy_repo

    defines_raw = list(getattr(repo, 'defined_aliases', []) or [])
    ct_raw = list(getattr(repo, 'cross_tenancy_statements', []) or [])

    define_rows: list[dict[str, str]] = []
    for item in defines_raw:
        define_rows.append(
            {
                'policy_name': str(item.get('policy_name') or ''),
                'defined_type': str(item.get('defined_type') or ''),
                'defined_name': str(item.get('defined_name') or ''),
                'ocid_alias': str(item.get('ocid_alias') or ''),
                'statement_text': str(item.get('statement_text') or ''),
                'creation_time': str(item.get('creation_time') or ''),
            }
        )

    admit_rows: list[dict[str, object]] = []
    endorse_rows: list[dict[str, object]] = []
    unknown_rows: list[dict[str, object]] = []

    for item in ct_raw:
        statement_text = str(item.get('statement_text') or '')
        text_cf = statement_text.casefold()
        policy_ocid = str(item.get('policy_ocid') or '')
        parsed_fields = {
            str(k): v
            for k, v in dict(item).items()
            if str(k)
            not in {
                'policy_name',
                'policy_ocid',
                'statement_text',
                'creation_time',
                'parsed',
            }
        }
        row: dict[str, object] = {
            'policy_name': str(item.get('policy_name') or ''),
            'policy_ocid': policy_ocid,
            'statement_text': statement_text,
            'creation_time': str(item.get('creation_time') or ''),
            'parsed': bool(item.get('parsed', False)),
            'parsed_fields': parsed_fields,
            'stable_key': _build_cross_tenancy_stable_key(policy_ocid, statement_text),
        }
        if text_cf.startswith('admit') or text_cf.startswith('deny admit'):
            admit_rows.append(row)
        elif text_cf.startswith('endorse') or text_cf.startswith('deny endorse'):
            endorse_rows.append(row)
        else:
            unknown_rows.append(row)

    return {
        'defines': define_rows,
        'admit_statements_basic': admit_rows,
        'endorse_statements_basic': endorse_rows,
        'unknown_statements_basic': unknown_rows,
        'counts': {
            'defines': len(define_rows),
            'admit': len(admit_rows),
            'endorse': len(endorse_rows),
            'unknown': len(unknown_rows),
        },
    }


@router.get('/analysis/permissions-report/tree')
def get_permissions_report_tree(
    show_inherited_principals: bool = False,
    principal_query: str = '',
) -> dict[str, object]:
    """Return permissions report tree rows grouped by effective path.

    Args:
        show_inherited_principals: Include ancestor-path principals not explicitly
            present in the selected path.
        principal_query: Optional principal-key free-text query.

    Returns:
        dict[str, object]: Tree payload with sorted path and subject rows.
    """
    logger.info('GET /analysis/permissions-report/tree')
    ctx = get_context()
    service = PermissionsReportService(ctx)
    return service.get_tree(
        show_inherited_principals=show_inherited_principals,
        principal_query=principal_query,
    )


@router.get('/analysis/permissions-report/details')
def get_permissions_report_details(
    path: str = '',
    subject_key: str = '',
    permission_query: str = '',
    principal_query: str = '',
) -> dict[str, object]:
    """Return allow/deny detail rows for one path and principal key.

    Args:
        path: Effective compartment path.
        subject_key: Principal key for the selected subject row.
        permission_query: Optional permission free-text query.
        principal_query: Optional principal-key query (validation guard).

    Returns:
        dict[str, object]: Details payload with allow and deny row lists.

    Raises:
        HTTPException: When path or subject_key is missing, or principal query does
            not match the selected subject.
    """
    logger.info('GET /analysis/permissions-report/details')
    path_key = str(path or '').strip()
    selected_subject_key = str(subject_key or '').strip()
    if not path_key or not selected_subject_key:
        raise HTTPException(status_code=400, detail='path and subject_key are required.')

    principal_terms = [term.casefold() for term in str(principal_query or '').split() if term.strip()]
    if principal_terms:
        selected_cf = selected_subject_key.casefold()
        if not all(term in selected_cf for term in principal_terms):
            raise HTTPException(status_code=400, detail='subject_key does not match principal_query.')

    ctx = get_context()
    service = PermissionsReportService(ctx)
    return service.get_details(
        path_key=path_key,
        subject_key=selected_subject_key,
        permission_query=permission_query,
    )


@router.get('/analysis/permissions-report/export')
def get_permissions_report_export() -> dict[str, object]:
    """Return raw permissions report payload for export workflows.

    Returns:
        dict[str, object]: Current permissions report payload.
    """
    logger.info('GET /analysis/permissions-report/export')
    ctx = get_context()
    service = PermissionsReportService(ctx)
    return service.get_export_payload()


@router.get('/analysis/recommendations/dashboard')
def get_recommendations_dashboard() -> dict[str, object]:
    """Return recommendations dashboard payload for web display.

    Returns:
        dict[str, object]: Read-only recommendations data sections.
    """
    logger.info('GET /analysis/recommendations/dashboard')
    ctx = get_context()
    service = RecommendationsService(ctx)
    return service.get_dashboard_payload()


@router.get('/reference/resources')
def list_reference_resources() -> dict[str, list[str]]:
    """Return available reference data resources."""
    logger.info('GET /reference/resources')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    return {'resources': service.list_resources()}


@router.get('/reference/families')
def list_reference_families() -> dict[str, list[str]]:
    """Return available reference data families."""
    logger.info('GET /reference/families')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    return {'families': service.list_families()}


@router.post('/reference/permissions')
def get_reference_permissions(payload: dict[str, object]) -> dict[str, object]:
    """Return permissions for a resource/family + verb/action."""
    logger.info('POST /reference/permissions')
    entity = payload.get('entity', '') if isinstance(payload, dict) else ''
    verb = payload.get('verb', '') if isinstance(payload, dict) else ''
    action = payload.get('action', 'allow') if isinstance(payload, dict) else 'allow'
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    permissions = service.get_permissions(str(entity), str(verb), str(action))
    return {'permissions': permissions}


@router.post('/reference/source')
def get_reference_source(payload: dict[str, object]) -> dict[str, object]:
    """Return the source URL for a resource or family."""
    logger.info('POST /reference/source')
    entity = payload.get('entity', '') if isinstance(payload, dict) else ''
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    return {'source': service.get_source(str(entity))}


@router.post('/reference/overlap')
def get_reference_overlap(payload: dict[str, object]) -> dict[str, object]:
    """Return overlapping permissions between two statement-style selectors."""
    logger.info('POST /reference/overlap')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    entity1 = str(payload.get('entity1', '') if isinstance(payload, dict) else '')
    verb1 = str(payload.get('verb1', '') if isinstance(payload, dict) else '')
    action1 = str(payload.get('action1', 'allow') if isinstance(payload, dict) else 'allow')
    entity2 = str(payload.get('entity2', '') if isinstance(payload, dict) else '')
    verb2 = str(payload.get('verb2', '') if isinstance(payload, dict) else '')
    action2 = str(payload.get('action2', 'allow') if isinstance(payload, dict) else 'allow')
    overlap = service.check_overlap(entity1, verb1, action1, entity2, verb2, action2)
    return {'overlap': overlap}


@router.get('/utilities/tag-namespaces')
def list_tag_namespaces() -> dict[str, object]:
    """Return tag namespace/key/value rows for utility browsing."""
    logger.info('GET /utilities/tag-namespaces')
    ctx = get_context()
    service = PolicyBrowserService(ctx)
    return service.list_tag_namespaces()


@router.get('/utilities/compartment-hierarchy')
def list_compartment_hierarchy() -> dict[str, object]:
    """Return compartment hierarchy rows with policy statement limits metadata."""
    logger.info('GET /utilities/compartment-hierarchy')
    ctx = get_context()
    service = PolicyBrowserService(ctx)
    return service.list_compartment_hierarchy()


@router.post('/utilities/condition-tester/format')
def format_condition_clause(payload: dict[str, object]) -> dict[str, str]:
    """Format a condition clause for readability.

    Args:
        payload: JSON body that may include ``clause``.

    Returns:
        Dict with normalized ``clause`` string.
    """
    clause = str(payload.get('clause') or '').strip()
    return {'clause': condition_tester_service.format_clause(clause)}


@router.post('/utilities/condition-tester/variables')
def extract_condition_variables(payload: dict[str, object]) -> dict[str, object]:
    """Extract variable names referenced by a condition clause.

    Args:
        payload: JSON body that may include ``clause``.

    Returns:
        Dict with sorted ``variables`` and input ``examples`` map.
    """
    clause = str(payload.get('clause') or '').strip()
    variables = condition_tester_service.extract_variables(clause)
    examples = {
        'request.utc-timestamp': 'e.g. 2026-01-05T12:34:56Z',
        'request.utc-timestamp.time-of-day': 'e.g. 13:27:00Z',
    }
    return {'variables': variables, 'examples': examples}


@router.post('/utilities/condition-tester/evaluate')
def evaluate_condition_clause(payload: dict[str, object]) -> dict[str, object]:
    """Evaluate condition clause against provided simulated variables.

    Args:
        payload: JSON body with ``clause`` and optional ``variables`` map.

    Returns:
        Structured evaluation response including condition string, policy
        result, boolean ``granted`` flag, and comparison log entries.
    """
    clause = str(payload.get('clause') or '').strip()
    vars_payload = payload.get('variables')
    variables = vars_payload if isinstance(vars_payload, dict) else {}
    evaluated = condition_tester_service.evaluate(clause, variables)
    return {
        'condition_string': evaluated.condition_string,
        'policy_result': evaluated.policy_result,
        'granted': evaluated.granted,
        'log': evaluated.log,
        'timestamp': datetime.now(UTC).isoformat(),
    }


@router.get('/logging')
def get_logging_settings() -> dict[str, object]:
    """Return logging settings."""
    logger.info('GET /logging')
    ctx = get_context()
    service = LoggingService(ctx.settings)
    return {'logging': service.get_log_settings()}


@router.post('/logging')
def update_logging_settings(payload: dict[str, object]) -> dict[str, object]:
    """Update logging settings and persist to disk."""
    logger.info('POST /logging')
    ctx = get_context()
    service = LoggingService(ctx.settings)
    updates = payload.get('logging') if isinstance(payload, dict) else None
    updates = updates if isinstance(updates, dict) else {}
    logging_settings = service.update_log_settings(updates)
    config.save_settings(ctx.settings)
    return {'logging': logging_settings}


@router.get('/logging/logs')
def get_logging_logs(lines: int = 300) -> dict[str, object]:
    """Return the latest log lines from the rotating log file."""
    log_dir = Path('~/.oci-policy-analysis/logs').expanduser()
    log_path = log_dir / 'app.log'
    if not log_path.exists():
        return {
            'lines': [
                'Log file not found yet.',
                f'Expected path: {log_path}',
            ]
        }
    try:
        content = log_path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        return {
            'lines': [
                'Unable to read log file.',
                f'Error: {exc}',
            ]
        }
    raw_lines = content.splitlines()
    trimmed_lines = raw_lines[-max(1, min(int(lines), 2000)) :]
    return {'lines': trimmed_lines}


@router.get('/profiles')
def list_profiles() -> dict[str, list[str]]:
    """Return available OCI CLI profiles from ~/.oci/config."""
    config_path = Path('~/.oci/config').expanduser()
    profiles: list[str] = []
    if config_path.exists():
        for line in config_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                profiles.append(line[1:-1])
    return {'profiles': profiles}


@router.post('/load/tenancy')
def load_tenancy(payload: dict[str, object]) -> dict[str, object]:
    """Load tenancy data using profile or instance principal."""
    ctx = get_context()
    service = LoadService(ctx)
    use_instance_principal = bool(payload.get('instance_principal'))
    profile = payload.get('profile')
    profile = profile if isinstance(profile, str) else None
    session_token = payload.get('session_token')
    session_token = session_token if isinstance(session_token, str) else None
    recursive = bool(payload.get('recursive'))
    load_all_users = payload.get('load_all_users')
    depth_raw = payload.get('compartment_domain_search_depth', 1)
    try:
        depth = max(1, min(int(depth_raw) if isinstance(depth_raw, (int | str)) else 1, 6))
    except (TypeError, ValueError):
        depth = 1

    stages, on_stage = _build_stage_collector()
    result = service.load_from_tenancy(
        use_instance_principal=use_instance_principal,
        profile=profile,
        session_token=session_token,
        recursive=recursive,
        load_all_users=bool(load_all_users) if load_all_users is not None else True,
        compartment_domain_search_depth=depth,
        on_stage=on_stage,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }


@router.get('/status')
def get_status() -> dict[str, object]:
    """Return latest load status summary for the web UI."""
    ctx = get_context()
    repo = ctx.policy_repo
    summary = {
        'tenancy_ocid': getattr(repo, 'tenancy_ocid', None),
        'tenancy_name': getattr(repo, 'tenancy_name', None),
        'data_as_of': getattr(repo, 'data_as_of', None),
        'loaded_from_compliance_output': getattr(repo, 'loaded_from_compliance_output', False),
        'policies_loaded_from_tenancy': getattr(repo, 'policies_loaded_from_tenancy', False),
        'policy_data_reloaded': getattr(repo, 'policy_data_reloaded', None),
        'load_all_users': getattr(repo, 'load_all_users', None),
        'entity_counts': {
            'compartments': len(getattr(repo, 'compartments', []) or []),
            'policies': len(getattr(repo, 'policies', []) or []),
            'statements': len(getattr(repo, 'regular_statements', []) or []),
            'groups': len(getattr(repo, 'groups', []) or []),
            'users': len(getattr(repo, 'users', []) or []),
        },
    }
    return {
        'stage': ctx.status.get('stage', 'Idle'),
        'detail': ctx.status.get('detail', ''),
        'state': ctx.status.get('state', 'idle'),
        'updated_at': ctx.status.get('updated_at', ''),
        'summary': summary,
    }


@router.get('/prospective/statements')
def get_prospective_statements() -> dict[str, object]:
    """Return tenancy-scoped prospective statement records."""
    logger.info('GET /prospective/statements')
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)
    rows = []
    for rec in service.list_all():
        rows.append(
            {
                'id': rec.id,
                'tenancy_ocid': rec.tenancy_ocid,
                'compartment_path': rec.compartment_path,
                'effective_path': rec.effective_path,
                'description': rec.description,
                'statement_text': rec.statement_text,
                'parsed': rec.parsed,
                'valid': rec.valid,
                'invalid_reasons': list(rec.invalid_reasons or []),
                'normalized': rec.normalized if isinstance(rec.normalized, dict) else None,
            }
        )
    return {'rows': rows}


@router.post('/prospective/statements/validate')
def validate_prospective_statement(payload: dict[str, object]) -> dict[str, object]:
    """Validate one prospective statement text for Parse action semantics."""
    logger.info('POST /prospective/statements/validate')
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)

    record_id = str(payload.get('id') or '').strip()
    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    description = str(payload.get('description') or '').strip()
    statement_text = str(payload.get('statement_text') or '').strip()

    if not record_id:
        rec = service.create(compartment_path=compartment_path, description=description, statement_text=statement_text)
        record_id = rec.id

    existing = service.get(record_id)
    if existing is None:
        rec = service.create(compartment_path=compartment_path, description=description, statement_text=statement_text)
        record_id = rec.id
        existing = rec

    existing.compartment_path = compartment_path
    existing.description = description
    updated = service.validate_and_update_text(record_id, statement_text)

    return {
        'row': {
            'id': updated.id,
            'tenancy_ocid': updated.tenancy_ocid,
            'compartment_path': updated.compartment_path,
            'effective_path': updated.effective_path,
            'description': updated.description,
            'statement_text': updated.statement_text,
            'parsed': updated.parsed,
            'valid': updated.valid,
            'invalid_reasons': list(updated.invalid_reasons or []),
            'normalized': updated.normalized if isinstance(updated.normalized, dict) else None,
        }
    }


@router.post('/prospective/statements/replace')
def replace_prospective_statements(payload: dict[str, object]) -> dict[str, object]:
    """Replace all prospective statements (deferred save-and-close semantics)."""
    logger.info('POST /prospective/statements/replace')
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)

    rows = payload.get('rows')
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail='rows must be a list')

    simple_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get('statement_text') or '').strip()
        if not text:
            continue
        simple_entry: dict[str, Any] = {
            'compartment_path': str(row.get('compartment_path') or 'ROOT').strip() or 'ROOT',
            'description': str(row.get('description') or '').strip(),
            'statement_text': text,
        }
        if row.get('id'):
            simple_entry['id'] = str(row.get('id'))
        simple_rows.append(simple_entry)

    service.replace_all_from_simple_list(simple_rows)
    service.persist_and_push_to_engine()
    return {'success': True, 'count': len(simple_rows)}


@router.get('/prospective/builder/metadata')
def get_prospective_builder_metadata() -> dict[str, object]:
    """Return builder dropdown metadata for prospective statement authoring."""
    logger.info('GET /prospective/builder/metadata')
    ctx = get_context()
    svc = ProspectiveBuilderService(
        policy_repo=ctx.policy_repo,
        reference_repo=ctx.reference_data,
        simulation_engine=ctx.simulation,
    )
    return svc.get_builder_metadata()


@router.post('/prospective/builder/preview')
def get_prospective_builder_preview(payload: dict[str, object]) -> dict[str, object]:
    """Return generated statement preview for current builder state."""
    logger.info('POST /prospective/builder/preview')
    ctx = get_context()
    svc = ProspectiveBuilderService(
        policy_repo=ctx.policy_repo,
        reference_repo=ctx.reference_data,
        simulation_engine=ctx.simulation,
    )
    result = svc.build_preview(payload if isinstance(payload, dict) else {})
    return {
        'subject_phrase': result.subject_phrase,
        'location_clause': result.location_clause,
        'condition_snippet': result.condition_snippet,
        'statement_text': result.statement_text,
        'description_suggestion': result.description_suggestion,
        'effective_path': result.effective_path,
        'warnings': result.warnings,
    }


@router.get('/simulation/context-options')
def get_simulation_context_options() -> dict[str, object]:
    """Return compartments/principals/API ops for simulation context step."""

    logger.info('GET /simulation/context-options')
    ctx = get_context()
    return _simulation_context_options(ctx)


@router.post('/simulation/statements')
def get_simulation_statements(payload: dict[str, object]) -> dict[str, object]:
    """Return statements for selected simulation context."""

    logger.info('POST /simulation/statements')
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)
    try:
        ctx.simulation.set_prospective_statements(service.to_simple_list())
    except Exception:
        logger.warning('Unable to sync prospective statements to simulation engine', exc_info=True)

    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    principal_type = str(payload.get('principal_type') or '').strip()
    principal_display = str(payload.get('principal') or '').strip()
    if not principal_type:
        raise HTTPException(status_code=400, detail='principal_type is required')

    principal = _build_engine_principal_value(principal_type, principal_display)
    principal_key, statements = ctx.simulation.get_statements_for_context(compartment_path, principal_type, principal)
    return {
        'principal_key': principal_key,
        'statements': [_statement_to_web_row(s) for s in statements],
    }


@router.post('/simulation/variables')
def get_simulation_variables(payload: dict[str, object]) -> dict[str, object]:
    """Extract where-clause variables from selected simulation statements."""

    logger.info('POST /simulation/variables')
    ctx = get_context()
    statements_obj = payload.get('statements')
    statements_raw = cast(list[object], statements_obj) if isinstance(statements_obj, list) else []
    statements: list[dict[str, object]] = [cast(dict[str, object], s) for s in statements_raw if isinstance(s, dict)]
    selected_obj = payload.get('selected_statement_ids')
    selected_raw = cast(list[object], selected_obj) if isinstance(selected_obj, list) else []
    selected: list[str] = [str(x) for x in selected_raw]
    selected_ids = {str(x) for x in selected}

    all_vars: set[str] = set()
    for stmt in statements:
        sid = str(stmt.get('internal_id') or '')
        if selected_ids and sid not in selected_ids:
            continue
        cond = stmt.get('conditions')
        if not cond:
            continue
        all_vars.update(ctx.simulation.extract_variable_names(str(cond)))

    variables = sorted(all_vars)
    hints = {
        'request.utc-timestamp': 'e.g. 2026-01-05T12:34:56Z',
        'request.utc-timestamp.time-of-day': 'e.g. 13:27:00Z',
    }
    return {
        'variables': variables,
        'hints': {v: hints.get(v, '') for v in variables},
    }


@router.post('/simulation/run')
def run_simulation(payload: dict[str, object]) -> dict[str, object]:
    """Run one-or-many API operation simulations for selected context."""

    logger.info('POST /simulation/run')
    ctx = get_context()
    principal_key = str(payload.get('principal_key') or '').strip()
    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    scenario_internal_id = str(payload.get('scenario_internal_id') or '').strip()
    scenario_name = str(payload.get('scenario_name') or '').strip()
    simulation_name = str(payload.get('simulation_name') or '').strip()
    where_context_raw = payload.get('where_context')
    where_context = where_context_raw if isinstance(where_context_raw, dict) else {}
    checked_statement_ids_raw = payload.get('checked_statement_ids')
    checked_statement_ids = (
        [str(x) for x in checked_statement_ids_raw] if isinstance(checked_statement_ids_raw, list) else None
    )
    api_operations_raw = payload.get('api_operations')
    if isinstance(api_operations_raw, list):
        api_operations = [str(x).strip() for x in api_operations_raw if str(x).strip()]
    else:
        one = str(payload.get('api_operation') or '').strip()
        api_operations = [one] if one else []

    if not principal_key:
        raise HTTPException(status_code=400, detail='principal_key is required')
    if not api_operations:
        raise HTTPException(status_code=400, detail='At least one api_operation is required')

    results: list[dict[str, Any]] = []
    for op in api_operations:
        if scenario_name and simulation_name:
            trace_name = f'{scenario_name} | {simulation_name} | {op}'
        elif scenario_name:
            trace_name = f'{scenario_name} | {op}'
        elif simulation_name:
            trace_name = f'{simulation_name} | {op}'
        else:
            trace_name = op
        result = ctx.simulation.simulate_and_record(
            principal_key=principal_key,
            effective_path=compartment_path,
            api_operation=op,
            where_context=where_context,
            checked_statement_ids=checked_statement_ids,
            trace_name=trace_name,
            scenario_internal_id=scenario_internal_id,
            scenario_name=scenario_name,
            simulation_name=simulation_name,
        )
        row = dict(result)
        row['api_operation'] = op
        results.append(row)

    return {
        'results': results,
        'history': ctx.simulation.get_simulation_trace_list(),
    }


@router.get('/simulation/history')
def get_simulation_history() -> dict[str, object]:
    """Return simulation history list for web workbench history step."""

    logger.info('GET /simulation/history')
    ctx = get_context()
    return {'history': ctx.simulation.get_simulation_trace_list()}


@router.get('/simulation/history/{idx}')
def get_simulation_history_entry(idx: int) -> dict[str, object]:
    """Return simulation history detail by index."""

    logger.info('GET /simulation/history/%s', idx)
    ctx = get_context()
    trace = ctx.simulation.get_simulation_trace_by_index(idx)
    if trace is None:
        raise HTTPException(status_code=404, detail='Simulation history entry not found')
    return {'trace': trace}


@router.get('/consolidation/status')
def get_consolidation_status() -> dict[str, object]:
    """Return consolidation workbench status metadata for the active dataset."""

    logger.info('GET /consolidation/status')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    return {'status': svc.get_status()}


@router.get('/consolidation/strategies')
def get_consolidation_strategies() -> dict[str, object]:
    """Return available consolidation strategy display names."""

    logger.info('GET /consolidation/strategies')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    return {'strategies': svc.get_status().get('strategy_names', [])}


@router.get('/consolidation/protection/statements')
def get_consolidation_protection_statements() -> dict[str, object]:
    """Return protection tab statement rows."""

    logger.info('GET /consolidation/protection/statements')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    return {'rows': svc.get_protection_rows()}


@router.get('/consolidation/protection/set')
def get_consolidation_protected_set() -> dict[str, object]:
    """Return protected statement set for active tenancy."""

    logger.info('GET /consolidation/protection/set')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    return {'protected_set': svc.get_protected_set()}


@router.post('/consolidation/protection/set')
def set_consolidation_protected_set(payload: dict[str, object]) -> dict[str, object]:
    """Persist protected statement IDs for active tenancy."""

    logger.info('POST /consolidation/protection/set')
    internal_ids_raw = payload.get('internal_ids') if isinstance(payload, dict) else []
    internal_ids = [str(x).strip() for x in internal_ids_raw] if isinstance(internal_ids_raw, list) else []
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    try:
        protected_set = svc.set_protected_set(internal_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'success': True, 'protected_set': protected_set}


@router.get('/consolidation/candidates')
def get_consolidation_candidates(search: str = '') -> dict[str, object]:
    """Return candidate rows and exclusion counts for consolidation step."""

    logger.info('GET /consolidation/candidates')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    data = svc.get_candidate_rows(search=search)
    return {'rows': data.get('rows', []), 'counts': data.get('counts', {})}


@router.post('/consolidation/proposals')
def create_consolidation_proposal(payload: dict[str, object]) -> dict[str, object]:
    """Generate and persist a consolidation proposal."""

    logger.info('POST /consolidation/proposals')
    strategy_display_name = str(payload.get('strategy_display_name') or '').strip()
    candidate_ids_raw = payload.get('candidate_internal_ids') if isinstance(payload, dict) else []
    candidate_internal_ids = [str(x).strip() for x in candidate_ids_raw] if isinstance(candidate_ids_raw, list) else []
    if not strategy_display_name:
        raise HTTPException(status_code=400, detail='strategy_display_name is required')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    try:
        result = svc.create_proposal(
            candidate_internal_ids=candidate_internal_ids, strategy_display_name=strategy_display_name
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get('/consolidation/history')
def get_consolidation_history() -> dict[str, object]:
    """Return consolidation plan history rows for active tenancy."""

    logger.info('GET /consolidation/history')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    return {'history': svc.get_history()}


@router.get('/consolidation/history/{effort_id}')
def get_consolidation_history_run(effort_id: str) -> dict[str, object]:
    """Return one consolidation history run record by effort ID."""

    logger.info('GET /consolidation/history/%s', effort_id)
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    detail = svc.get_history_run_detail(effort_id)
    if detail is None:
        raise HTTPException(status_code=404, detail='Consolidation run not found')
    return detail


@router.delete('/consolidation/history/{effort_id}')
def delete_consolidation_history_run(effort_id: str) -> dict[str, object]:
    """Delete one consolidation run from history for active tenancy."""

    logger.info('DELETE /consolidation/history/%s', effort_id)
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    ok = svc.delete_history_run(effort_id)
    if not ok:
        raise HTTPException(status_code=404, detail='Consolidation run not found or could not be deleted')
    return {'success': True, 'deleted_effort_id': effort_id}


@router.post('/consolidation/history/{effort_id}/notes')
def save_consolidation_notes(effort_id: str, payload: dict[str, object]) -> dict[str, object]:
    """Save notes for a consolidation run plan."""

    logger.info('POST /consolidation/history/%s/notes', effort_id)
    notes = str(payload.get('notes') or '').strip()
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    ok = svc.save_plan_notes(effort_id=effort_id, notes=notes)
    if not ok:
        raise HTTPException(status_code=404, detail='Consolidation run not found or not writable')
    return {'success': True}


@router.get('/consolidation/history/{effort_id}/script')
def get_consolidation_script(effort_id: str, fmt: str = 'cli', section: str = 'execution') -> dict[str, object]:
    """Render consolidation script text for a specific run."""

    logger.info('GET /consolidation/history/%s/script', effort_id)
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    txt = svc.render_script(effort_id=effort_id, fmt=fmt.strip().lower(), section=section.strip().lower())
    return {'script': txt}


@router.post('/consolidation/history/{effort_id}/check-progress')
def check_consolidation_progress(effort_id: str) -> dict[str, object]:
    """Check execution progress for a consolidation run."""

    logger.info('POST /consolidation/history/%s/check-progress', effort_id)
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    try:
        result = svc.check_progress(effort_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post('/consolidation/reset')
def reset_consolidation_for_tenancy() -> dict[str, object]:
    """Reset consolidation state (protection set + history) for active tenancy."""

    logger.info('POST /consolidation/reset')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    try:
        result = svc.reset_for_tenancy()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'success': True, **result}


@router.post('/load/compliance')
def load_compliance(payload: dict[str, object]) -> dict[str, object]:
    """Load compliance output data from a local directory."""
    ctx = get_context()
    service = LoadService(ctx)
    dir_path_raw = payload.get('dir_path')
    dir_path = dir_path_raw if isinstance(dir_path_raw, str) else ''
    load_all_users = payload.get('load_all_users')
    run_post_load_intelligence = payload.get('run_post_load_intelligence')
    if not dir_path:
        return {'success': False, 'message': 'Directory path is required.', 'summary': {}}

    stages, on_stage = _build_stage_collector()
    result = service.load_from_compliance_output(
        dir_path,
        load_all_users=bool(load_all_users) if load_all_users is not None else True,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }


@router.post('/load/export')
def load_export(payload: dict[str, object]) -> dict[str, object]:
    """Load policy data from an exported cache JSON file path."""
    ctx = get_context()
    service = LoadService(ctx)
    file_path_raw = payload.get('file_path')
    file_path = file_path_raw if isinstance(file_path_raw, str) else ''
    run_post_load_intelligence = payload.get('run_post_load_intelligence')
    if not file_path:
        return {'success': False, 'message': 'Export file path is required.', 'summary': {}}

    stages, on_stage = _build_stage_collector()
    result = service.load_from_export_json(
        file_path,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }
