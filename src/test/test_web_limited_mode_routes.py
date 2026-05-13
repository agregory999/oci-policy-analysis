from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from oci_policy_analysis.web.api import routes_core
from starlette.requests import Request


class _Req:
    def __init__(self, session: dict[str, Any] | None = None) -> None:
        self.session = session or {}


class _Repo:
    def __init__(self, tenancy_ocid: str, users: list[dict[str, Any]] | None = None) -> None:
        self.tenancy_ocid = tenancy_ocid
        self.users = users or []

    def filter_users(self, user_filter: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self.users)


class _Ctx:
    def __init__(self, repo: _Repo) -> None:
        self.policy_repo = repo


class _AnalysisResult:
    def __init__(self, statements: list[dict[str, Any]]) -> None:
        self.total = len(statements)
        self.matched = len(statements)
        self.statements = statements


class _AnalysisServiceStub:
    def __init__(self, _ctx: Any, statements: list[dict[str, Any]]) -> None:
        self._statements = statements

    def filter_policy_statements(self, *, filters: dict[str, Any]) -> _AnalysisResult:
        _ = filters
        return _AnalysisResult(self._statements)


def _limited_session(key_hash: str, policy_scope_mode: str = 'include_relevant_ancestors') -> dict[str, Any]:
    return {
        'authenticated': True,
        'auth_mode': 'limited',
        'limited_key_hash': key_hash,
        'limited_scope': {
            'profile_id': 'p-test',
            'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
            'compartment_root_paths': ['ROOT/Finance'],
            'policy_scope_mode': policy_scope_mode,
            'allowed_identity_domains': ['Default'],
        },
    }


@pytest.fixture(autouse=True)
def _reset_active_limited_keys() -> None:
    routes_core._ACTIVE_LIMITED_KEYS.clear()


def test_limited_login_rejects_tenancy_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    key = 'limited-key-1'
    key_hash = routes_core._hash_key_material(key)
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p1',
        'tenancy_ocid': 'ocid1.tenancy.oc1..alpha',
        'runtime_key': key,
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'strict_descendants',
        'allowed_identity_domains': ['Default'],
    }

    monkeypatch.setattr(routes_core, 'verify_access_key', lambda submitted: False)
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(_Repo('ocid1.tenancy.oc1..beta')))

    req = _Req()
    result = routes_core.auth_login(cast(Request, req), {'key': key})

    assert result['success'] is False
    assert result['authenticated'] is False
    assert 'currently loaded tenancy' in str(result.get('message', ''))


def test_limited_empty_domain_allowlist_returns_no_users(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-2')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p2',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-2',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'strict_descendants',
        'allowed_identity_domains': [],
    }

    repo = _Repo(
        'ocid1.tenancy.oc1..scope',
        users=[
            {'user_name': 'alice', 'domain_name': 'Default', 'groups': []},
            {'user_name': 'bob', 'domain_name': 'CorpDomainA', 'groups': []},
        ],
    )
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(repo))

    req = _Req(
        {
            'authenticated': True,
            'auth_mode': 'limited',
            'limited_key_hash': key_hash,
            'limited_scope': {
                'profile_id': 'p2',
                'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
                'compartment_root_paths': ['ROOT/Finance'],
                'policy_scope_mode': 'strict_descendants',
                'allowed_identity_domains': [],
            },
        }
    )

    payload = routes_core.list_users(cast(Request, req))
    assert payload['matched'] == 0
    assert payload['users'] == []


def test_limited_mode_blocked_route_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-3')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p3',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope2',
        'runtime_key': 'limited-key-3',
        'compartment_root_paths': ['ROOT'],
        'policy_scope_mode': 'strict_descendants',
        'allowed_identity_domains': ['Default'],
    }
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(_Repo('ocid1.tenancy.oc1..scope2')))

    req = _Req(
        {
            'authenticated': True,
            'auth_mode': 'limited',
            'limited_key_hash': key_hash,
            'limited_scope': {
                'profile_id': 'p3',
                'tenancy_ocid': 'ocid1.tenancy.oc1..scope2',
                'compartment_root_paths': ['ROOT'],
                'policy_scope_mode': 'strict_descendants',
                'allowed_identity_domains': ['Default'],
            },
        }
    )

    with pytest.raises(HTTPException) as exc:
        routes_core.get_status(cast(Request, req))
    assert exc.value.status_code == 403


def test_limited_simulation_requires_include_relevant_ancestors(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-sim-1')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p-sim-1',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-sim-1',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'strict_descendants',
        'allowed_identity_domains': ['Default'],
    }
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(_Repo('ocid1.tenancy.oc1..scope')))

    req = _Req(_limited_session(key_hash, policy_scope_mode='strict_descendants'))
    with pytest.raises(HTTPException) as exc:
        routes_core.get_simulation_context_options(cast(Request, req))
    assert exc.value.status_code == 403
    assert 'include_relevant_ancestors' in str(exc.value.detail)


def test_limited_simulation_statements_reject_out_of_scope_path(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-sim-2')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p-sim-2',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-sim-2',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'include_relevant_ancestors',
        'allowed_identity_domains': ['Default'],
    }

    class _Sim:
        def set_prospective_statements(self, _rows: list[dict[str, Any]]) -> None:
            return None

    class _CtxSim(_Ctx):
        def __init__(self, repo: _Repo) -> None:
            super().__init__(repo)
            self.simulation = _Sim()
            self.cache = object()

    monkeypatch.setattr(routes_core, 'get_context', lambda: _CtxSim(_Repo('ocid1.tenancy.oc1..scope')))

    class _ProspectiveSvc:
        def to_simple_list(self) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(routes_core, '_get_or_init_prospective_service', lambda _ctx: _ProspectiveSvc())

    req = _Req(_limited_session(key_hash, policy_scope_mode='include_relevant_ancestors'))
    with pytest.raises(HTTPException) as exc:
        routes_core.get_simulation_statements(
            cast(Request, req),
            {
                'compartment_path': 'ROOT/Engineering',
                'principal_type': 'user',
                'principal': 'alice',
            },
        )
    assert exc.value.status_code == 403
    assert 'outside your limited scope' in str(exc.value.detail)


def test_limited_simulation_run_rejects_disallowed_principal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-sim-3')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p-sim-3',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-sim-3',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'include_relevant_ancestors',
        'allowed_identity_domains': ['Default'],
    }

    class _Sim:
        def simulate_and_record(self, **_kwargs: Any) -> dict[str, Any]:
            return {'api_call_allowed': True}

        def get_simulation_trace_list(self) -> list[dict[str, Any]]:
            return []

    class _CtxRun(_Ctx):
        def __init__(self, repo: _Repo) -> None:
            super().__init__(repo)
            self.simulation = _Sim()

    monkeypatch.setattr(routes_core, 'get_context', lambda: _CtxRun(_Repo('ocid1.tenancy.oc1..scope')))

    req = _Req(_limited_session(key_hash, policy_scope_mode='include_relevant_ancestors'))
    with pytest.raises(HTTPException) as exc:
        routes_core.run_simulation(
            cast(Request, req),
            {
                'principal_key': 'user:CorpDomainA/alice',
                'compartment_path': 'ROOT/Finance',
                'api_operations': ['ListUsers'],
            },
        )
    assert exc.value.status_code == 403
    assert 'identity-domain scope' in str(exc.value.detail)


def test_limited_filter_policies_applies_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-policy-1')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p-policy-1',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-policy-1',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'include_relevant_ancestors',
        'allowed_identity_domains': ['Default'],
    }

    statements = [
        {'internal_id': 's1', 'effective_path': 'ROOT/Finance', 'statement_text': 'finance stmt'},
        {'internal_id': 's2', 'effective_path': 'ROOT/Engineering', 'statement_text': 'eng stmt'},
    ]

    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(_Repo('ocid1.tenancy.oc1..scope')))
    monkeypatch.setattr(routes_core, 'AnalysisService', lambda ctx: _AnalysisServiceStub(ctx, statements))

    req = _Req(_limited_session(key_hash, policy_scope_mode='include_relevant_ancestors'))
    payload = routes_core.filter_policies(cast(Request, req), {'filters': {}})

    assert payload['matched'] == 1
    returned = cast(list[dict[str, Any]], payload.get('statements') or [])
    assert len(returned) == 1
    assert str(returned[0].get('effective_path') or '') == 'ROOT/Finance'


def test_limited_user_redirected_from_admin_home(monkeypatch: pytest.MonkeyPatch) -> None:
    key_hash = routes_core._hash_key_material('limited-key-home-1')
    routes_core._ACTIVE_LIMITED_KEYS[key_hash] = {
        'profile_id': 'p-home-1',
        'tenancy_ocid': 'ocid1.tenancy.oc1..scope',
        'runtime_key': 'limited-key-home-1',
        'compartment_root_paths': ['ROOT/Finance'],
        'policy_scope_mode': 'include_relevant_ancestors',
        'allowed_identity_domains': ['Default'],
    }
    monkeypatch.setattr(routes_core, 'get_context', lambda: _Ctx(_Repo('ocid1.tenancy.oc1..scope')))

    req = _Req(_limited_session(key_hash, policy_scope_mode='include_relevant_ancestors'))
    response = routes_core.serve_home(cast(Request, req))
    assert isinstance(response, RedirectResponse)
    assert response.headers.get('location') == '/limited-home.html'


def test_admin_user_can_load_index_html(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_core, 'current_key_fingerprint', lambda: 'fp-1')

    req = _Req({'authenticated': True, 'auth_mode': 'admin', 'auth_key_fp': 'fp-1'})
    response = routes_core.serve_index_html(cast(Request, req))
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith('/index.html')


def test_unauthenticated_user_can_load_index_shell() -> None:
    req = _Req({'authenticated': False})
    response = routes_core.serve_home(cast(Request, req))
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith('/index.html')
