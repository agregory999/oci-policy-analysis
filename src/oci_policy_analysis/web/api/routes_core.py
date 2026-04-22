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
from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService
from oci_policy_analysis.application.services.intelligence_service import IntelligenceService
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.application.services.logging_service import LoggingService
from oci_policy_analysis.application.services.policy_browser_service import PolicyBrowserService
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
from oci_policy_analysis.web.dependencies import get_context, get_settings

logger = get_logger(component='web_routes')
router = APIRouter()


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
    output = [for_display_user(u) for u in users]
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

    policy_filter: PolicySearch = {}
    if exact_groups:
        policy_filter['exact_groups'] = exact_groups
    if exact_users:
        policy_filter['exact_users'] = exact_users
    if exact_dynamic_groups:
        policy_filter['exact_dynamic_groups'] = exact_dynamic_groups
    statements = repo.filter_policy_statements(filters=policy_filter)

    if include_any_subjects:
        extra = repo.filter_policy_statements(filters=PolicySearch(subject=['any-user', 'any-group']))
        seen = {st.get('internal_id') or st.get('statement_text') for st in statements}
        for st in extra:
            key = st.get('internal_id') or st.get('statement_text')
            if key not in seen:
                statements.append(st)
                seen.add(key)

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
            }
        )

    admit_rows: list[dict[str, object]] = []
    endorse_rows: list[dict[str, object]] = []
    unknown_rows: list[dict[str, object]] = []

    for item in ct_raw:
        statement_text = str(item.get('statement_text') or '')
        text_cf = statement_text.casefold()
        policy_ocid = str(item.get('policy_ocid') or '')
        row: dict[str, object] = {
            'policy_name': str(item.get('policy_name') or ''),
            'policy_ocid': policy_ocid,
            'statement_text': statement_text,
            'creation_time': str(item.get('creation_time') or ''),
            'parsed': bool(item.get('parsed', False)),
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
    }
    return {
        'stage': ctx.status.get('stage', 'Idle'),
        'detail': ctx.status.get('detail', ''),
        'state': ctx.status.get('state', 'idle'),
        'updated_at': ctx.status.get('updated_at', ''),
        'summary': summary,
    }


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
