"""Core FastAPI routes for cache load and intelligence."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from oci_policy_analysis._version import get_app_version
from oci_policy_analysis.application.core.models.models import (
    DynamicGroup,
    DynamicGroupSearch,
    Group,
    GroupSearch,
    PolicySearch,
    RegularPolicyStatement,
    User,
    UserSearch,
)
from oci_policy_analysis.application.core.parser.condition_structure import format_condition_structure_summary
from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.core.support.helpers import (
    for_display_dynamic_group,
    for_display_group,
    for_display_policy,
    for_display_user,
)
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.core.support.usage_tracking import get_usage_tracker, init_usage_tracker
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
from oci_policy_analysis.application.services.prospective_statements_service import ProspectiveStatementsService
from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict
from oci_policy_analysis.application.services.tag_based_policy_service import TagBasedPolicyService
from oci_policy_analysis.presentation.web.auth import current_key_fingerprint, verify_access_key
from oci_policy_analysis.presentation.web.dependencies import get_context, get_settings

logger = get_logger(component='web_routes')
router = APIRouter()
condition_tester_service = ConditionTesterService()
SERVER_STARTED_AT = datetime.now(UTC).isoformat()

_LIMITED_ACCESS_BY_TENANCY_KEY = 'limited_access_by_tenancy'
_ACTIVE_LIMITED_KEYS: dict[str, dict[str, object]] = {}


def _hash_key_material(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _get_current_tenancy_ocid() -> str:
    ctx = get_context()
    return str(getattr(ctx.policy_repo, 'tenancy_ocid', '') or '').strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_limited_profiles_for_tenancy(tenancy_ocid: str) -> list[dict[str, object]]:
    settings = get_settings()
    by_tenancy = settings.get(_LIMITED_ACCESS_BY_TENANCY_KEY)
    if not isinstance(by_tenancy, dict):
        return []
    tenant_blob = by_tenancy.get(tenancy_ocid)
    if not isinstance(tenant_blob, dict):
        return []
    profiles = tenant_blob.get('profiles')
    if not isinstance(profiles, list):
        return []
    return [p for p in profiles if isinstance(p, dict)]


def _set_limited_profiles_for_tenancy(tenancy_ocid: str, profiles: list[dict[str, object]]) -> None:
    settings = get_settings()
    by_tenancy = settings.get(_LIMITED_ACCESS_BY_TENANCY_KEY)
    if not isinstance(by_tenancy, dict):
        by_tenancy = {}
    tenant_blob = by_tenancy.get(tenancy_ocid)
    if not isinstance(tenant_blob, dict):
        tenant_blob = {}
    tenant_blob['profiles'] = profiles
    by_tenancy[tenancy_ocid] = tenant_blob
    settings[_LIMITED_ACCESS_BY_TENANCY_KEY] = by_tenancy
    config.save_settings(settings)


def _get_session_auth_mode(request: Request) -> str | None:
    mode = str(request.session.get('auth_mode') or '').strip().lower()
    return mode if mode in {'admin', 'limited'} else None


def _is_authenticated(request: Request) -> bool:
    """Return whether this browser session is authenticated for active auth mode."""
    session = request.session
    if not bool(session.get('authenticated')):
        return False

    auth_mode = _get_session_auth_mode(request)
    if auth_mode == 'admin':
        return session.get('auth_key_fp') == current_key_fingerprint()
    if auth_mode == 'limited':
        limited_key_hash = str(session.get('limited_key_hash') or '').strip()
        if not limited_key_hash:
            return False
        active = _ACTIVE_LIMITED_KEYS.get(limited_key_hash)
        if not isinstance(active, dict):
            return False
        current_tenancy_ocid = _get_current_tenancy_ocid()
        active_tenancy_ocid = str(active.get('tenancy_ocid') or '').strip()
        return not (current_tenancy_ocid and active_tenancy_ocid and current_tenancy_ocid != active_tenancy_ocid)
    return False


def _require_authenticated(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail='Not authenticated.')


def _is_limited_session(request: Request) -> bool:
    return _is_authenticated(request) and _get_session_auth_mode(request) == 'limited'


def _require_not_limited(request: Request) -> None:
    _require_authenticated(request)
    if _is_limited_session(request):
        raise HTTPException(status_code=403, detail='Limited mode does not allow this operation.')


def _require_admin(request: Request) -> None:
    _require_authenticated(request)
    if _get_session_auth_mode(request) != 'admin':
        raise HTTPException(status_code=403, detail='Admin access required.')


def _limited_scope(request: Request) -> dict[str, object]:
    scope = request.session.get('limited_scope')
    return dict(scope) if isinstance(scope, dict) else {}


def _path_match(root: str, candidate: str, *, include_relevant_ancestors: bool) -> bool:
    r = (root or '').strip().strip('/').strip(':').casefold()
    c = (candidate or '').strip().strip('/').strip(':').casefold()
    if not r:
        return True
    if not c:
        return False
    if c == r or c.startswith(r + '/') or c.startswith(r + ':'):
        return True
    if include_relevant_ancestors and (r.startswith(c + '/') or r.startswith(c + ':')):
        return True
    return False


def _statement_effective_path(statement: dict[str, Any]) -> str:
    for key in (
        'effective_path',
        'Effective Path',
        'effective path',
        'compartment_path',
        'Compartment Path',
        'policy_path',
        'Policy Path',
    ):
        value = statement.get(key)
        if value:
            return str(value)
    return ''


def _apply_policy_scope(request: Request, statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_limited_session(request):
        return statements
    scope = _limited_scope(request)
    roots_raw = scope.get('compartment_root_paths')
    roots = [str(x).strip() for x in roots_raw if str(x).strip()] if isinstance(roots_raw, list) else []
    include_ancestors = str(scope.get('policy_scope_mode') or '').strip() == 'include_relevant_ancestors'
    if not roots:
        return statements
    return [
        s
        for s in statements
        if any(
            _path_match(root, _statement_effective_path(s), include_relevant_ancestors=include_ancestors)
            for root in roots
        )
    ]


def _domain_allowed_for_limited(request: Request, domain_name: str | None) -> bool:
    if not _is_limited_session(request):
        return True
    allowed_raw = _limited_scope(request).get('allowed_identity_domains')
    if not isinstance(allowed_raw, list) or not allowed_raw:
        return False
    allowed = {str(x).strip().casefold() for x in allowed_raw if str(x).strip()}
    return str(domain_name or 'Default').strip().casefold() in allowed


def _require_simulation_access(request: Request) -> None:
    _require_authenticated(request)
    if not _is_limited_session(request):
        return
    mode = str(_limited_scope(request).get('policy_scope_mode') or '').strip()
    if mode != 'include_relevant_ancestors':
        raise HTTPException(status_code=403, detail='Limited simulation requires include_relevant_ancestors.')


@router.get('/auth/status')
def auth_status(request: Request) -> dict[str, object]:
    """Return lightweight auth status for current browser session."""
    authenticated = _is_authenticated(request)
    mode = _get_session_auth_mode(request) if authenticated else None
    return {'authenticated': authenticated, 'auth_mode': mode, 'limited_scope': request.session.get('limited_scope')}


@router.get('/metadata/app')
def app_metadata() -> dict[str, str]:
    """Return lightweight app metadata for shared web UI chrome.

    Returns:
        dict[str, str]: Application metadata including version and server start time.
    """

    return {'version': get_app_version(), 'server_started_at': SERVER_STARTED_AT}


@router.post('/auth/login')
def auth_login(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Validate startup admin key or active limited key and mark browser session authenticated."""
    submitted_key = str(payload.get('key') or '').strip()
    if verify_access_key(submitted_key):
        request.session.clear()
        request.session['authenticated'] = True
        request.session['auth_mode'] = 'admin'
        request.session['auth_key_fp'] = current_key_fingerprint()
        _track_web_operation('/auth/login', status='success')
        return {'success': True, 'authenticated': True, 'auth_mode': 'admin'}

    limited_key_hash = _hash_key_material(submitted_key)
    active = _ACTIVE_LIMITED_KEYS.get(limited_key_hash)
    if not active:
        request.session.clear()
        _track_web_operation('/auth/login', status='error')
        return {'success': False, 'authenticated': False, 'message': 'Invalid access key.'}
    current_tenancy_ocid = _get_current_tenancy_ocid()
    if current_tenancy_ocid and str(active.get('tenancy_ocid') or '').strip() != current_tenancy_ocid:
        request.session.clear()
        _track_web_operation('/auth/login', status='error')
        return {
            'success': False,
            'authenticated': False,
            'message': 'Limited key is not valid for the currently loaded tenancy.',
        }
    request.session.clear()
    request.session['authenticated'] = True
    request.session['auth_mode'] = 'limited'
    request.session['limited_key_hash'] = limited_key_hash
    request.session['limited_scope'] = {
        'profile_id': active.get('profile_id'),
        'tenancy_ocid': active.get('tenancy_ocid'),
        'compartment_root_paths': active.get('compartment_root_paths') or [],
        'policy_scope_mode': active.get('policy_scope_mode'),
        'allowed_identity_domains': active.get('allowed_identity_domains') or [],
    }
    _track_web_operation('/auth/login', status='success')
    return {'success': True, 'authenticated': True, 'auth_mode': 'limited'}


@router.post('/auth/logout')
def auth_logout(request: Request) -> dict[str, bool]:
    """Clear lightweight auth state for current browser session."""
    request.session.clear()
    return {'success': True, 'authenticated': False}


@router.get('/auth/limited/profiles')
def list_limited_profiles(request: Request) -> dict[str, object]:
    """List limited-mode profiles for the currently loaded tenancy."""
    _require_admin(request)
    tenancy_ocid = _get_current_tenancy_ocid()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')
    profiles = _get_limited_profiles_for_tenancy(tenancy_ocid)
    active_profile_ids = {
        str(v.get('profile_id') or '')
        for v in _ACTIVE_LIMITED_KEYS.values()
        if str(v.get('tenancy_ocid') or '') == tenancy_ocid
    }
    response_profiles = []
    for profile in profiles:
        p = dict(profile)
        p.pop('key_hash', None)
        is_active = str(p.get('profile_id') or '') in active_profile_ids
        p['active'] = is_active
        if is_active:
            for row in _ACTIVE_LIMITED_KEYS.values():
                if str(row.get('tenancy_ocid') or '') == tenancy_ocid and str(row.get('profile_id') or '') == str(
                    p.get('profile_id') or ''
                ):
                    p['active_runtime_key'] = str(row.get('runtime_key') or '')
                    break
        response_profiles.append(p)
    return {'tenancy_ocid': tenancy_ocid, 'profiles': response_profiles}


@router.get('/auth/limited/options')
def list_limited_options(request: Request) -> dict[str, object]:
    """Return compartment and identity-domain choices for limited profiles."""
    _require_admin(request)
    ctx = get_context()
    repo = ctx.policy_repo
    tenancy_ocid = str(getattr(repo, 'tenancy_ocid', '') or '').strip()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')

    compartment_paths: set[str] = set()
    for comp in getattr(repo, 'compartments', []) or []:
        if isinstance(comp, dict):
            path = str(comp.get('hierarchy_path') or '').strip()
        else:
            path = str(getattr(comp, 'hierarchy_path', '') or '').strip()
        if path:
            compartment_paths.add(path)
    if not compartment_paths:
        compartment_paths.add('ROOT')

    domains: set[str] = set()
    for collection_name in ('users', 'groups', 'dynamic_groups'):
        for entry in getattr(repo, collection_name, []) or []:
            if isinstance(entry, dict):
                domains.add(str(entry.get('domain_name') or 'Default').strip() or 'Default')
    domains.add('Default')

    return {
        'tenancy_ocid': tenancy_ocid,
        'compartment_paths': sorted(compartment_paths),
        'identity_domains': sorted(domains),
    }


@router.post('/auth/limited/profiles/upsert')
def upsert_limited_profile(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Create or update a limited-mode access profile."""
    _require_admin(request)
    tenancy_ocid = _get_current_tenancy_ocid()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')

    profile_id = str(payload.get('profile_id') or '').strip() or str(uuid4())
    label = str(payload.get('label') or '').strip() or f'Limited Profile {profile_id[:8]}'
    roots_raw = payload.get('compartment_root_paths')
    if isinstance(roots_raw, list):
        compartment_root_paths = sorted({str(x).strip() for x in roots_raw if str(x).strip()})
    else:
        single_root = str(payload.get('compartment_root_path') or '').strip()
        compartment_root_paths = [single_root] if single_root else []
    if not compartment_root_paths:
        raise HTTPException(status_code=400, detail='At least one compartment root path is required.')
    policy_scope_mode = str(payload.get('policy_scope_mode') or 'strict_descendants').strip()
    if policy_scope_mode not in {'strict_descendants', 'include_relevant_ancestors'}:
        policy_scope_mode = 'strict_descendants'
    allowed_domains_raw = payload.get('allowed_identity_domains')
    if isinstance(allowed_domains_raw, list):
        allowed_identity_domains = sorted(
            {str(x).strip() for x in allowed_domains_raw if isinstance(x, str) and str(x).strip()}
        )
    else:
        allowed_identity_domains = []
    enabled = bool(payload.get('enabled', True))

    profiles = _get_limited_profiles_for_tenancy(tenancy_ocid)
    now = _utc_now_iso()
    existing = next((p for p in profiles if str(p.get('profile_id') or '') == profile_id), None)
    if existing is not None:
        existing['label'] = label
        existing['compartment_root_paths'] = compartment_root_paths
        existing['policy_scope_mode'] = policy_scope_mode
        existing['allowed_identity_domains'] = allowed_identity_domains
        existing['enabled'] = enabled
        existing['updated_at'] = now
    else:
        profiles.append(
            {
                'profile_id': profile_id,
                'label': label,
                'enabled': enabled,
                'compartment_root_paths': compartment_root_paths,
                'policy_scope_mode': policy_scope_mode,
                'allowed_identity_domains': allowed_identity_domains,
                'created_at': now,
                'updated_at': now,
            }
        )

    _set_limited_profiles_for_tenancy(tenancy_ocid, profiles)
    return {'success': True, 'profile_id': profile_id}


@router.post('/auth/limited/profiles/delete')
def delete_limited_profile(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Delete a limited-mode profile and revoke its active keys."""
    _require_admin(request)
    tenancy_ocid = _get_current_tenancy_ocid()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')
    profile_id = str(payload.get('profile_id') or '').strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail='profile_id is required.')
    profiles = _get_limited_profiles_for_tenancy(tenancy_ocid)
    filtered = [p for p in profiles if str(p.get('profile_id') or '') != profile_id]
    _set_limited_profiles_for_tenancy(tenancy_ocid, filtered)
    for key_hash, row in list(_ACTIVE_LIMITED_KEYS.items()):
        if str(row.get('tenancy_ocid') or '') == tenancy_ocid and str(row.get('profile_id') or '') == profile_id:
            _ACTIVE_LIMITED_KEYS.pop(key_hash, None)
    return {'success': True}


@router.post('/auth/limited/profiles/activate')
def activate_limited_profile(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Activate a limited profile and return its runtime access key."""
    _require_admin(request)
    tenancy_ocid = _get_current_tenancy_ocid()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')
    profile_id = str(payload.get('profile_id') or '').strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail='profile_id is required.')
    profiles = _get_limited_profiles_for_tenancy(tenancy_ocid)
    profile = next((p for p in profiles if str(p.get('profile_id') or '') == profile_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail='Profile not found for current tenancy.')
    if not bool(profile.get('enabled', True)):
        raise HTTPException(status_code=400, detail='Profile is disabled.')
    runtime_key = str(uuid4())
    key_hash = _hash_key_material(runtime_key)
    _ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': profile_id,
        'tenancy_ocid': tenancy_ocid,
        'runtime_key': runtime_key,
        'compartment_root_paths': list(profile.get('compartment_root_paths') or []),
        'policy_scope_mode': str(profile.get('policy_scope_mode') or 'strict_descendants'),
        'allowed_identity_domains': list(profile.get('allowed_identity_domains') or []),
        'activated_at': _utc_now_iso(),
    }
    return {'success': True, 'profile_id': profile_id, 'runtime_key': runtime_key, 'active': True}


@router.post('/auth/limited/profiles/deactivate')
def deactivate_limited_profile(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Deactivate all active runtime keys for a limited profile."""
    _require_admin(request)
    tenancy_ocid = _get_current_tenancy_ocid()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')
    profile_id = str(payload.get('profile_id') or '').strip()
    if not profile_id:
        raise HTTPException(status_code=400, detail='profile_id is required.')
    removed = False
    for key_hash, row in list(_ACTIVE_LIMITED_KEYS.items()):
        if str(row.get('tenancy_ocid') or '') == tenancy_ocid and str(row.get('profile_id') or '') == profile_id:
            _ACTIVE_LIMITED_KEYS.pop(key_hash, None)
            removed = True
    return {'success': True, 'active': False, 'deactivated': removed}


def _get_or_init_prospective_service(ctx) -> ProspectiveStatementsService:
    """Return a tenancy-scoped prospective service for the current web context."""

    existing = getattr(ctx, '_prospective_service', None)
    tenancy_ocid = str(getattr(ctx.policy_repo, 'tenancy_ocid', '') or '').strip()
    if not tenancy_ocid:
        raise HTTPException(status_code=400, detail='No tenancy is currently loaded.')

    if isinstance(existing, ProspectiveStatementsService) and existing.tenancy_ocid == tenancy_ocid:
        # Ensure legacy instances created without simulation_engine wiring
        # are refreshed so Parse/Validate can use engine-backed validation.
        if getattr(existing, '_simulation_engine', None) is not None:
            return existing

    service = ProspectiveStatementsService(
        cache_manager=ctx.cache,
        policy_repo=ctx.policy_repo,
        tenancy_ocid=tenancy_ocid,
        simulation_engine=ctx.simulation,
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


def _get_tenancy_ocid_hash(ctx: object | None) -> str | None:
    """Return a SHA-256 hash of active tenancy OCID, if available.

    Privacy note: this helper never returns the raw tenancy OCID.
    """

    if ctx is None:
        return None
    try:
        repo = getattr(ctx, 'policy_repo', None)
        tenancy_ocid = str(getattr(repo, 'tenancy_ocid', '') or '').strip()
        if not tenancy_ocid:
            return None
        return hashlib.sha256(tenancy_ocid.encode('utf-8')).hexdigest()
    except Exception:
        return None


def _get_tenancy_suffix(ctx: object | None) -> str | None:
    """Return last-6 tenancy OCID suffix for tracker object partitioning."""

    if ctx is None:
        return None
    try:
        repo = getattr(ctx, 'policy_repo', None)
        tenancy_ocid = str(getattr(repo, 'tenancy_ocid', '') or '').strip()
        if not tenancy_ocid:
            return None
        return tenancy_ocid[-6:]
    except Exception:
        return None


def _infer_page_from_route(route: str) -> str:
    """Map API route to a coarse web page/feature bucket for analytics."""

    r = (route or '').strip().lower()
    if r.startswith('/filter/policies'):
        return 'policy_analysis'
    if r.startswith('/entities/'):
        return 'user_group_analysis'
    if r.startswith('/analysis/permissions-report'):
        return 'permissions_report'
    if r.startswith('/analysis/recommendations'):
        return 'recommendations'
    if r.startswith('/simulation/'):
        return 'simulation'
    if r.startswith('/consolidation/'):
        return 'consolidation'
    if r.startswith('/prospective/'):
        return 'prospective'
    if r.startswith('/load/'):
        return 'load'
    if r.startswith('/auth/'):
        return 'auth'
    if r.startswith('/reference/'):
        return 'reference'
    if r.startswith('/utilities/'):
        return 'utilities'
    return 'other'


def _track_web_operation(
    route: str,
    *,
    status: str,
    ctx: object | None = None,
    source: str | None = None,
    count: int | None = None,
    duration_ms: float | None = None,
) -> None:
    """Best-effort anonymous tracking for high-value web operations.

    Records only non-personal metadata. No usernames, no client/IP values,
    and no raw tenancy OCID are ever recorded.
    """

    try:
        tracker = get_usage_tracker()
        if tracker is None:
            logger.info('Web usage tracking skipped: tracker not initialized route=%s status=%s', route, status)
            return
        tenancy_suffix = _get_tenancy_suffix(ctx)
        if tenancy_suffix:
            tracker.set_tenancy_suffix(tenancy_suffix)
        payload: dict[str, object] = {
            'channel': 'web',
            'route': route,
            'status': status,
            'page': _infer_page_from_route(route),
        }
        tenancy_ocid_hash = _get_tenancy_ocid_hash(ctx)
        if tenancy_ocid_hash:
            payload['tenancy_ocid_hash'] = tenancy_ocid_hash
        if source:
            payload['source'] = source
        if count is not None:
            payload['count'] = int(count)
        if duration_ms is not None:
            payload['duration_ms'] = float(duration_ms)
        logger.info(
            'Web usage tracking: route=%s status=%s source=%s has_tenancy_hash=%s count=%s',
            route,
            status,
            source or '',
            bool(payload.get('tenancy_ocid_hash')),
            payload.get('count', ''),
        )
        tracker.track_operation('web_operation', **payload)
        # Flush web operations promptly so analytics PAR refresh can see them
        # without waiting for process exit, then rotate tracker for next op.
        tracker.flush()
        init_usage_tracker(get_settings(), get_app_version())
    except Exception:
        logger.debug('Usage tracking failed for web route %s', route, exc_info=True)


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


def _simulation_context_options(ctx, request: Request | None = None) -> dict[str, object]:
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
        if request is not None and _is_limited_session(request) and ptype in {'user', 'group', 'dynamic-group'}:
            tuples = [t for t in tuples if _domain_allowed_for_limited(request, t[0] or 'Default')]
        principal_display_map[ptype] = [f'{d}/{n}' if d else n for (d, n) in tuples]

    if request is not None and _is_limited_session(request):
        scope = _limited_scope(request)
        roots_raw = scope.get('compartment_root_paths')
        roots = [str(x).strip() for x in roots_raw if str(x).strip()] if isinstance(roots_raw, list) else []
        include_ancestors = str(scope.get('policy_scope_mode') or '').strip() == 'include_relevant_ancestors'
        if roots:
            compartments = {
                c
                for c in compartments
                if any(_path_match(root, c, include_relevant_ancestors=include_ancestors) for root in roots)
            }

    api_operations = sim.get_api_operations('') if sim else []
    return {
        'compartments': sorted(compartments),
        'principal_types': sorted(principal_types),
        'principals_by_type': principal_display_map,
        'api_operations': api_operations,
    }


def _statement_to_web_row(stmt: dict[str, Any]) -> dict[str, Any]:
    """Normalize statement payload for simulation workbench table/inspector."""

    def _policy_tags_to_web_rows() -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        freeform = stmt.get('policy_freeform_tags') or stmt.get('freeform_tags') or {}
        if isinstance(freeform, dict):
            for key, value in sorted(freeform.items(), key=lambda item: str(item[0]).casefold()):
                rows.append(
                    {
                        'kind': 'Freeform',
                        'namespace': '',
                        'key': str(key),
                        'value': '' if value is None else str(value),
                    }
                )
        defined = stmt.get('policy_defined_tags') or stmt.get('defined_tags') or {}
        if isinstance(defined, dict):
            for namespace, tags in sorted(defined.items(), key=lambda item: str(item[0]).casefold()):
                if not isinstance(tags, dict):
                    continue
                for key, value in sorted(tags.items(), key=lambda item: str(item[0]).casefold()):
                    rows.append(
                        {
                            'kind': 'Defined',
                            'namespace': str(namespace),
                            'key': str(key),
                            'value': '' if value is None else str(value),
                        }
                    )
        return rows

    action = str(stmt.get('action') or 'allow').lower()
    conditions = stmt.get('conditions')
    condition_structure = stmt.get('where_clause_structure') or stmt.get('where_clause') or {}
    condition_atoms = stmt.get('condition_atoms')
    if not isinstance(condition_atoms, list) and isinstance(condition_structure, dict):
        condition_atoms = condition_structure.get('atoms', [])
    condition_summary = stmt.get('conditions_parsed_structure')
    if not condition_summary and isinstance(condition_structure, dict):
        condition_summary = format_condition_structure_summary(condition_structure)
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
        'conditions': conditions,
        'conditions_where_clause': stmt.get('conditions_where_clause') or conditions,
        'conditions_parsed_structure': condition_summary or '',
        'condition_atoms': condition_atoms if isinstance(condition_atoms, list) else [],
        'policy_tags': _policy_tags_to_web_rows(),
        'tag_conditions': stmt.get('tag_conditions') if isinstance(stmt.get('tag_conditions'), list) else [],
        'tag_context_warnings': stmt.get('tag_context_warnings')
        if isinstance(stmt.get('tag_context_warnings'), list)
        else [],
        'valid': stmt.get('valid'),
        'parsed': stmt.get('parsed'),
        'is_prospective': bool(stmt.get('is_prospective')),
    }


def _index_html_file() -> FileResponse:
    index_path = files('oci_policy_analysis.presentation.web').joinpath('static').joinpath('index.html')
    return FileResponse(path=str(index_path), media_type='text/html')


@router.get('/')
def serve_home(request: Request):
    """Serve public index shell; redirect authenticated limited users to limited home."""
    if _is_authenticated(request) and _get_session_auth_mode(request) != 'admin':
        return RedirectResponse(url='/limited-home.html', status_code=307)
    return _index_html_file()


@router.get('/index.html')
def serve_index_html(request: Request):
    """Serve public index shell; redirect authenticated limited users to limited home."""
    if _is_authenticated(request) and _get_session_auth_mode(request) != 'admin':
        return RedirectResponse(url='/limited-home.html', status_code=307)
    return _index_html_file()


@router.get('/health')
def health() -> dict[str, str]:
    """Return the web application's health status."""
    logger.info('GET /health')
    return {'status': 'ok'}


@router.get('/caches')
def list_caches() -> dict[str, list[str]]:
    """Return available tenancy cache names."""
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
    """Rename a persisted cache and report the operation result."""
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
    """Delete a persisted cache and report the operation result."""
    logger.info('POST /caches/delete')
    ctx = get_context()
    cache_name = str(payload.get('name') or '').strip()
    if not cache_name:
        return {'success': False, 'message': 'Cache name is required.'}
    ok = ctx.cache_service.remove_cache(cache_name)
    return {'success': ok, 'message': 'Cache deleted.' if ok else 'Unable to delete cache.'}


@router.get('/caches/download/{cache_name}')
def download_cache(cache_name: str, export_name: str | None = None) -> FileResponse:
    """Download a named cache as a JSON file."""
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
    """Load a cache and return progress, status, and summary information."""
    logger.info('POST /load/cache/%s', cache_name)
    ctx = get_context()
    service = LoadService(ctx)
    stages, on_stage = _build_stage_collector()
    body = payload or {}
    run_post_load_intelligence = body.get('run_post_load_intelligence')
    started = time.perf_counter()
    result = service.load_from_cache(
        cache_name=cache_name,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    _track_web_operation(
        '/load/cache',
        status='success' if bool(result.success) else 'error',
        ctx=ctx,
        source='cache',
        duration_ms=(time.perf_counter() - started) * 1000.0,
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
    """Run configured intelligence strategies for the loaded dataset."""
    logger.info('POST /intelligence/run')
    ctx = get_context()
    service = IntelligenceService(ctx)
    started = time.perf_counter()
    result = service.run_all()
    _track_web_operation(
        '/intelligence/run',
        status='success',
        ctx=ctx,
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )
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
def filter_policies(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Filter loaded policy statements using the web search payload."""
    logger.info('POST /filter/policies')
    _require_authenticated(request)
    ctx = get_context()
    service = AnalysisService(ctx)
    started = time.perf_counter()
    raw_filters = payload.get('filters') or {}
    sort_by = str(payload.get('sort_by') or '').strip()
    sort_dir = str(payload.get('sort_dir') or 'asc').strip().lower()
    filters = build_policy_search_from_dict(raw_filters if isinstance(raw_filters, dict) else {})
    result = service.filter_policy_statements(filters=filters)

    statements = list(result.statements or [])
    statements = _apply_policy_scope(request, statements)

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

    _track_web_operation(
        '/filter/policies',
        status='success',
        ctx=ctx,
        count=int(result.matched or 0),
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )

    return {
        'total': result.total,
        'matched': len(statements),
        'statements': statements,
    }


@router.post('/filter/policies/tag-based')
def filter_tag_based_policies(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Return tag-focused policy search results using parsed conditions."""

    logger.info('POST /filter/policies/tag-based')
    _require_authenticated(request)
    ctx = get_context()
    raw_filters = payload.get('filters') or {}
    filters = build_policy_search_from_dict(raw_filters if isinstance(raw_filters, dict) else {})
    statements = ctx.policy_repo.filter_policy_statements(filters=filters)
    statements = _apply_policy_scope(request, list(statements))
    tag_result = TagBasedPolicyService.query(cast(list[RegularPolicyStatement], statements), filters)
    rows = [_statement_to_web_row(cast(dict[str, Any], statement)) for statement in tag_result['statements']]
    return {
        'total': len(getattr(ctx.policy_repo, 'regular_statements', []) or []),
        'matched': len(rows),
        'statements': rows,
        'summary': tag_result.get('summary', {}),
    }


@router.get('/entities/groups')
def list_groups(request: Request, search: str = '') -> dict[str, object]:
    """Return groups for User/Group analysis with optional pipe-delimited search."""
    logger.info('GET /entities/groups')
    ctx = get_context()
    repo = ctx.policy_repo
    group_filter: GroupSearch = GroupSearch(group_name=_split_pipe(search))
    groups: list[Group] = repo.filter_groups(group_filter=group_filter)
    output = []
    for g in groups:
        if not _domain_allowed_for_limited(request, str(g.get('domain_name') or 'Default')):
            continue
        row = for_display_group(g)
        row['User Count'] = len(repo.get_users_for_group(g))
        output.append(row)
    return {
        'total': len(getattr(repo, 'groups', []) or []),
        'matched': len(output),
        'groups': output,
    }


@router.get('/entities/users')
def list_users(request: Request, search: str = '') -> dict[str, object]:
    """Return users for User/Group analysis with optional pipe-delimited search."""
    logger.info('GET /entities/users')
    ctx = get_context()
    repo = ctx.policy_repo
    user_filter: UserSearch = UserSearch(search=_split_pipe(search))
    users: list[User] = repo.filter_users(user_filter=user_filter)
    output = []
    for u in users:
        if not _domain_allowed_for_limited(request, str(u.get('domain_name') or 'Default')):
            continue
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
    request: Request, domain: str = '', name: str = '', matching_rule: str = '', dynamic_group_ocid: str = ''
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
    output = [
        for_display_dynamic_group(dg)
        for dg in dynamic_groups
        if _domain_allowed_for_limited(request, str(dg.get('domain_name') or 'Default'))
    ]
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


@router.get('/metadata/workload-identity-values')
def list_workload_identity_values() -> dict[str, list[str]]:
    """Return discovered OKE workload identity selector values."""
    logger.info('GET /metadata/workload-identity-values')
    ctx = get_context()
    principal_service = PrincipalAnalysisService(ctx)
    return principal_service.get_workload_identity_values()


@router.post('/filter/policies/by-subjects')
def filter_policies_by_subjects(payload: dict[str, object]) -> dict[str, object]:  # noqa: C901
    """Filter policies by exact selected groups/users/dynamic groups and optional any-user/group expansion."""
    logger.info('POST /filter/policies/by-subjects')
    ctx = get_context()
    started = time.perf_counter()
    repo = ctx.policy_repo

    exact_groups_payload = payload.get('exact_groups')
    exact_users_payload = payload.get('exact_users')
    exact_dynamic_groups_payload = payload.get('exact_dynamic_groups')
    principal_keys_payload = payload.get('principal_keys')
    principal_style = str(payload.get('principal_style') or '').strip()
    include_any_subjects = bool(payload.get('include_any_subjects'))
    subject_type_filter = _split_pipe(str(payload.get('subject_type') or ''))
    subject_filter_terms = _split_pipe(str(payload.get('subject') or ''))
    principal_filter_terms = _split_pipe(str(payload.get('principal') or ''))
    conditions_filter_terms = _split_pipe(str(payload.get('conditions') or ''))
    resource_type_terms = [term for term in _split_pipe(str(payload.get('resource_type') or '')) if term != 'Any']
    resource_compartment_ocid_terms = _split_pipe(str(payload.get('resource_compartment_ocid') or ''))
    workload_namespace_terms = _split_pipe(str(payload.get('workload_namespace') or ''))
    workload_service_account_terms = _split_pipe(str(payload.get('workload_service_account') or ''))
    workload_cluster_id_terms = _split_pipe(str(payload.get('workload_cluster_id') or ''))
    workload_subject_terms = [term for term in subject_filter_terms if term.casefold() in {'any-user', 'any-group'}]
    use_workload_principal_filter = bool(
        workload_subject_terms and (resource_type_terms or resource_compartment_ocid_terms)
    )
    use_oke_principal_filter = bool(
        principal_style.casefold() == 'oke workload identity'
        or principal_style.casefold() == 'oke-workload-identity'
        or workload_namespace_terms
        or workload_service_account_terms
        or workload_cluster_id_terms
    )

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

    principal_keys: list[str] = []
    if isinstance(principal_keys_payload, list):
        principal_keys = [str(v).strip() for v in principal_keys_payload if str(v).strip()]

    logger.debug(
        '[by-subjects] payload summary: exact_groups=%d exact_users=%d exact_dynamic_groups=%d principal_keys=%d include_any_subjects=%s subject_type_terms=%d subject_terms=%d principal_terms=%d conditions_terms=%d resource_type_terms=%d resource_compartment_ocid_terms=%d workload_namespace_terms=%d workload_service_account_terms=%d workload_cluster_id_terms=%d principal_style=%s',
        len(exact_groups),
        len(exact_users),
        len(exact_dynamic_groups),
        len(principal_keys),
        include_any_subjects,
        len(subject_type_filter),
        len(subject_filter_terms),
        len(principal_filter_terms),
        len(conditions_filter_terms),
        len(resource_type_terms),
        len(resource_compartment_ocid_terms),
        len(workload_namespace_terms),
        len(workload_service_account_terms),
        len(workload_cluster_id_terms),
        principal_style,
    )
    logger.debug('[by-subjects] exact_groups=%s', exact_groups)
    if exact_users:
        logger.debug('[by-subjects] exact_users=%s', exact_users)
    if exact_dynamic_groups:
        logger.debug('[by-subjects] exact_dynamic_groups=%s', exact_dynamic_groups)
    if principal_keys:
        logger.debug('[by-subjects] principal_keys=%s', principal_keys)

    resolved_principal_keys: list[str] = list(principal_keys)
    if principal_keys:
        users_by_key: dict[str, User] = {}
        for u in getattr(repo, 'users', []) or []:
            if not isinstance(u, dict):
                continue
            domain = str(u.get('domain_name') or 'Default').strip() or 'Default'
            name = str(u.get('user_name') or '').strip()
            if name:
                users_by_key[f'user:{domain}/{name}'] = {'domain_name': domain, 'user_name': name}

        expanded_group_keys: set[str] = set()
        passthrough_keys: set[str] = set()
        for key in principal_keys:
            ptype = key.split(':', 1)[0] if ':' in key else ''
            if ptype == 'user':
                user = users_by_key.get(key)
                if user is None:
                    continue
                for group in repo.get_groups_for_user(user):
                    domain = str(group.get('domain_name') or 'Default').strip() or 'Default'
                    name = str(group.get('group_name') or '').strip()
                    if name:
                        expanded_group_keys.add(f'group:{domain}/{name}')
            else:
                passthrough_keys.add(key)
        if expanded_group_keys:
            resolved_principal_keys = sorted(passthrough_keys | expanded_group_keys)
        else:
            resolved_principal_keys = sorted(passthrough_keys)

    policy_filter: PolicySearch = {}
    if resolved_principal_keys:
        policy_filter['principal_key'] = resolved_principal_keys
    if exact_groups:
        policy_filter['exact_groups'] = exact_groups
    if exact_users:
        policy_filter['exact_users'] = exact_users
    if exact_dynamic_groups:
        policy_filter['exact_dynamic_groups'] = exact_dynamic_groups
    if use_workload_principal_filter:
        policy_filter['subject_type'] = workload_subject_terms
        principal_selector: dict[str, object] = {'principal_type': 'resource-principal'}
        if resource_type_terms:
            principal_selector['resource_type'] = resource_type_terms[0]
        if resource_compartment_ocid_terms:
            principal_selector['resource_compartment_ocid'] = resource_compartment_ocid_terms[0]
        policy_filter['principal'] = principal_selector
    elif use_oke_principal_filter:
        policy_filter['subject_type'] = workload_subject_terms or ['any-user', 'any-group']
        principal_selector = {'principal_type': 'oke-workload-identity'}
        if workload_namespace_terms:
            principal_selector['workload_namespace'] = workload_namespace_terms[0]
        if workload_service_account_terms:
            principal_selector['workload_service_account'] = workload_service_account_terms[0]
        if workload_cluster_id_terms:
            principal_selector['workload_cluster_id'] = workload_cluster_id_terms[0]
        policy_filter['principal'] = principal_selector
    elif subject_filter_terms:
        policy_filter['subject'] = subject_filter_terms
    condition_filter_terms = list(conditions_filter_terms)
    if resource_compartment_ocid_terms and not use_workload_principal_filter:
        condition_filter_terms.extend(resource_compartment_ocid_terms)
    if condition_filter_terms:
        policy_filter['conditions'] = condition_filter_terms

    logger.debug('[by-subjects] derived policy_filter=%s', policy_filter)

    has_subject_selector = bool(
        resolved_principal_keys or exact_groups or exact_users or exact_dynamic_groups or subject_filter_terms
    )
    if not has_subject_selector:
        logger.debug('[by-subjects] empty subject selector payload; returning no statements')
        _track_web_operation(
            '/filter/policies/by-subjects',
            status='success',
            ctx=ctx,
            count=0,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
        return {
            'total': len(getattr(repo, 'regular_statements', []) or []),
            'matched': 0,
            'statements': [],
            'selected_groups': [],
        }

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
    if resolved_principal_keys:
        for key in resolved_principal_keys:
            if not key.startswith('group:'):
                continue
            val = key.split(':', 1)[1] if ':' in key else ''
            domain, group = (val.split('/', 1) + [''])[:2] if '/' in val else ('Default', val)
            selected_groups.append({'Domain': domain or 'Default', 'Group': group})
    elif exact_groups:
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

    _track_web_operation(
        '/filter/policies/by-subjects',
        status='success',
        ctx=ctx,
        count=len(statements),
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )

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


@router.get('/reference/resource-helper-options')
def get_reference_resource_helper_options() -> dict[str, object]:
    """Return resource/family option sets used by policy filter helper dropdowns."""
    logger.info('GET /reference/resource-helper-options')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    return {
        'resources': service.list_resources_with_family(),
        'families': service.list_families_with_resources(),
    }


@router.get('/reference/permission-helper-options')
def get_reference_permission_helper_options() -> dict[str, object]:
    """Return option data for permission lookup helper UI."""
    logger.info('GET /reference/permission-helper-options')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    return {
        'operations': service.list_operations_with_permissions(),
        'resources': service.list_resources(),
        'families': service.list_families(),
        'verbs': ['inspect', 'read', 'use', 'manage'],
        'actions': ['allow', 'deny'],
    }


@router.post('/reference/build-resource-filter')
def build_reference_resource_filter(payload: dict[str, object]) -> dict[str, object]:
    """Build a canonical resource filter string from selected resource/family helper inputs."""
    logger.info('POST /reference/build-resource-filter')
    ctx = get_context()
    service = ReferenceDataService(ctx.reference_data)
    include_all_resources = bool(payload.get('include_all_resources')) if isinstance(payload, dict) else False

    mode = str(payload.get('mode', '') if isinstance(payload, dict) else '').strip()
    if mode == 'from_resource':
        resource = str(payload.get('resource', '') if isinstance(payload, dict) else '').strip()
        expanded, warnings = service.build_resource_filter_from_resource(
            resource,
            include_all_resources=include_all_resources,
        )
        return {'expanded_resource_filter': expanded, 'warnings': warnings}

    if mode == 'from_family':
        family = str(payload.get('family', '') if isinstance(payload, dict) else '').strip()
        expanded, warnings = service.build_resource_filter_from_family(
            family,
            include_all_resources=include_all_resources,
        )
        return {'expanded_resource_filter': expanded, 'warnings': warnings}

    raise HTTPException(status_code=400, detail='mode must be from_resource or from_family')


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
    started = time.perf_counter()
    result = service.load_from_tenancy(
        use_instance_principal=use_instance_principal,
        profile=profile,
        session_token=session_token,
        recursive=recursive,
        load_all_users=bool(load_all_users) if load_all_users is not None else True,
        compartment_domain_search_depth=depth,
        on_stage=on_stage,
    )
    _track_web_operation(
        '/load/tenancy',
        status='success' if bool(result.success) else 'error',
        ctx=ctx,
        source='live',
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }


@router.get('/status')
def get_status(request: Request) -> dict[str, object]:
    """Return latest load status summary for the web UI."""
    _require_not_limited(request)
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
def get_prospective_statements(request: Request) -> dict[str, object]:
    """Return tenancy-scoped prospective statement records."""
    logger.info('GET /prospective/statements')
    _require_authenticated(request)
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)
    scope_roots: list[str] = []
    include_ancestors = False
    if _is_limited_session(request):
        scope = _limited_scope(request)
        roots_raw = scope.get('compartment_root_paths')
        scope_roots = [str(x).strip() for x in roots_raw if str(x).strip()] if isinstance(roots_raw, list) else []
        include_ancestors = str(scope.get('policy_scope_mode') or '').strip() == 'include_relevant_ancestors'

    rows = []
    for rec in service.list_all():
        if scope_roots:
            candidate_path = str(rec.effective_path or rec.compartment_path or '').strip()
            if not any(
                _path_match(root, candidate_path, include_relevant_ancestors=include_ancestors) for root in scope_roots
            ):
                continue
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
def validate_prospective_statement(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Validate one prospective statement text for Parse action semantics."""
    logger.info('POST /prospective/statements/validate')
    _require_admin(request)
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
def replace_prospective_statements(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Replace all prospective statements (deferred save-and-close semantics)."""
    logger.info('POST /prospective/statements/replace')
    _require_admin(request)
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)

    rows = payload.get('rows')
    if not isinstance(rows, list):
        _track_web_operation('/prospective/statements/replace', status='error', ctx=ctx)
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
    _track_web_operation('/prospective/statements/replace', status='success', ctx=ctx, count=len(simple_rows))
    return {'success': True, 'count': len(simple_rows)}


@router.get('/prospective/builder/metadata')
def get_prospective_builder_metadata(request: Request) -> dict[str, object]:
    """Return builder dropdown metadata for prospective statement authoring."""
    logger.info('GET /prospective/builder/metadata')
    _require_admin(request)
    ctx = get_context()
    svc = ProspectiveBuilderService(
        policy_repo=ctx.policy_repo,
        reference_repo=ctx.reference_data,
        simulation_engine=ctx.simulation,
    )
    return svc.get_builder_metadata()


@router.post('/prospective/builder/preview')
def get_prospective_builder_preview(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Return generated statement preview for current builder state."""
    logger.info('POST /prospective/builder/preview')
    _require_admin(request)
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
def get_simulation_context_options(request: Request) -> dict[str, object]:
    """Return compartments/principals/API ops for simulation context step."""
    _require_simulation_access(request)
    logger.info('GET /simulation/context-options')
    ctx = get_context()
    return _simulation_context_options(ctx, request=request)


@router.post('/simulation/statements')
def get_simulation_statements(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Return statements for selected simulation context."""
    _require_simulation_access(request)
    logger.info('POST /simulation/statements')
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)
    try:
        ctx.simulation.set_prospective_statements(service.to_simple_list())
    except Exception:
        logger.warning('Unable to sync prospective statements to simulation engine', exc_info=True)

    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    if not _apply_policy_scope(request, [{'effective_path': compartment_path}]):
        raise HTTPException(status_code=403, detail='Selected compartment path is outside your limited scope.')
    principal_type = str(payload.get('principal_type') or '').strip()
    principal_display = str(payload.get('principal') or '').strip()
    if not principal_type:
        raise HTTPException(status_code=400, detail='principal_type is required')

    if _is_limited_session(request) and principal_type in {'user', 'group', 'dynamic-group'}:
        domain_name = principal_display.split('/', 1)[0] if '/' in principal_display else 'Default'
        if not _domain_allowed_for_limited(request, domain_name):
            raise HTTPException(
                status_code=403, detail='Selected principal is outside your limited identity-domain scope.'
            )

    principal = _build_engine_principal_value(principal_type, principal_display)
    principal_key, statements_raw = ctx.simulation.get_statements_for_context(
        compartment_path, principal_type, principal
    )
    prospective_raw = sum(1 for s in statements_raw if bool(cast(dict[str, Any], s).get('is_prospective')))
    statements = _apply_policy_scope(request, statements_raw)
    prospective_scoped = sum(1 for s in statements if bool(cast(dict[str, Any], s).get('is_prospective')))
    logger.info(
        'simulation/statements: principal_key=%s compartment=%s total_raw=%d prospective_raw=%d total_scoped=%d prospective_scoped=%d limited=%s',
        principal_key,
        compartment_path,
        len(statements_raw),
        prospective_raw,
        len(statements),
        prospective_scoped,
        _is_limited_session(request),
    )
    return {
        'principal_key': principal_key,
        'statements': [_statement_to_web_row(s) for s in statements],
    }


@router.post('/simulation/prospective-preview')
def get_simulation_prospective_preview(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Return scoped prospective-only statements for current simulation context."""
    _require_simulation_access(request)
    ctx = get_context()
    service = _get_or_init_prospective_service(ctx)
    try:
        ctx.simulation.set_prospective_statements(service.to_simple_list())
    except Exception:
        logger.warning('Unable to sync prospective statements to simulation engine for preview', exc_info=True)

    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    principal_type = str(payload.get('principal_type') or '').strip()
    principal_display = str(payload.get('principal') or '').strip()
    if not principal_type:
        return {'principal_key': '', 'rows': []}

    principal = _build_engine_principal_value(principal_type, principal_display)
    principal_key, statements_raw = ctx.simulation.get_statements_for_context(
        compartment_path, principal_type, principal
    )
    statements_scoped = _apply_policy_scope(request, statements_raw)
    prospective_rows = [s for s in statements_scoped if bool(cast(dict[str, Any], s).get('is_prospective'))]
    logger.info(
        'simulation/prospective-preview: principal_key=%s compartment=%s raw=%d scoped=%d prospective=%d',
        principal_key,
        compartment_path,
        len(statements_raw),
        len(statements_scoped),
        len(prospective_rows),
    )
    return {'principal_key': principal_key, 'rows': [_statement_to_web_row(s) for s in prospective_rows]}


@router.post('/simulation/variables')
def get_simulation_variables(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Extract where-clause variables from selected simulation statements."""
    _require_simulation_access(request)

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
def run_simulation(request: Request, payload: dict[str, object]) -> dict[str, object]:
    """Run one-or-many API operation simulations for selected context."""
    _require_simulation_access(request)
    logger.info('POST /simulation/run')
    ctx = get_context()
    principal_key = str(payload.get('principal_key') or '').strip()
    compartment_path = str(payload.get('compartment_path') or 'ROOT').strip() or 'ROOT'
    if not _apply_policy_scope(request, [{'effective_path': compartment_path}]):
        _track_web_operation('/simulation/run', status='error', ctx=ctx)
        raise HTTPException(status_code=403, detail='Selected compartment path is outside your limited scope.')
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
        _track_web_operation('/simulation/run', status='error', ctx=ctx)
        raise HTTPException(status_code=400, detail='principal_key is required')
    if _is_limited_session(request):
        pval = principal_key.split(':', 1)[1] if ':' in principal_key else ''
        pdomain = pval.split('/', 1)[0] if '/' in pval else 'Default'
        ptype = principal_key.split(':', 1)[0] if ':' in principal_key else ''
        if ptype in {'user', 'group', 'dynamic-group'} and not _domain_allowed_for_limited(request, pdomain):
            _track_web_operation('/simulation/run', status='error', ctx=ctx)
            raise HTTPException(
                status_code=403, detail='Selected principal is outside your limited identity-domain scope.'
            )
    if not api_operations:
        _track_web_operation('/simulation/run', status='error', ctx=ctx)
        raise HTTPException(status_code=400, detail='At least one api_operation is required')

    started = time.perf_counter()
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

    _track_web_operation(
        '/simulation/run',
        status='success',
        ctx=ctx,
        count=len(results),
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )

    return {
        'results': results,
        'history': ctx.simulation.get_simulation_trace_list(),
    }


@router.get('/simulation/history')
def get_simulation_history(request: Request) -> dict[str, object]:
    """Return simulation history list for web workbench history step."""
    _require_simulation_access(request)

    logger.info('GET /simulation/history')
    ctx = get_context()
    return {'history': ctx.simulation.get_simulation_trace_list()}


@router.get('/simulation/history/{idx}')
def get_simulation_history_entry(request: Request, idx: int) -> dict[str, object]:
    """Return simulation history detail by index."""
    _require_simulation_access(request)

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
        _track_web_operation('/consolidation/proposals', status='error')
        raise HTTPException(status_code=400, detail='strategy_display_name is required')
    ctx = get_context()
    svc = ConsolidationWorkbenchService(ctx)
    started = time.perf_counter()
    try:
        result = svc.create_proposal(
            candidate_internal_ids=candidate_internal_ids, strategy_display_name=strategy_display_name
        )
    except (ValueError, RuntimeError) as exc:
        _track_web_operation('/consolidation/proposals', status='error', ctx=ctx)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _track_web_operation(
        '/consolidation/proposals',
        status='success',
        ctx=ctx,
        count=len(candidate_internal_ids),
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )
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
        _track_web_operation('/load/compliance', status='error', ctx=ctx, source='compliance')
        return {'success': False, 'message': 'Directory path is required.', 'summary': {}}

    stages, on_stage = _build_stage_collector()
    started = time.perf_counter()
    result = service.load_from_compliance_output(
        dir_path,
        load_all_users=bool(load_all_users) if load_all_users is not None else True,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    _track_web_operation(
        '/load/compliance',
        status='success' if bool(result.success) else 'error',
        ctx=ctx,
        source='compliance',
        duration_ms=(time.perf_counter() - started) * 1000.0,
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
        _track_web_operation('/load/export', status='error', ctx=ctx, source='json_file')
        return {'success': False, 'message': 'Export file path is required.', 'summary': {}}

    stages, on_stage = _build_stage_collector()
    started = time.perf_counter()
    result = service.load_from_export_json(
        file_path,
        run_post_load_intelligence=(
            bool(run_post_load_intelligence) if run_post_load_intelligence is not None else True
        ),
        on_stage=on_stage,
    )
    _track_web_operation(
        '/load/export',
        status='success' if bool(result.success) else 'error',
        ctx=ctx,
        source='json_file',
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )
    return {
        'success': result.success,
        'message': result.message,
        'summary': result.summary or {},
        'stages': stages,
        'status': ctx.status,
    }
