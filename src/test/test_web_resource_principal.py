"""The container's web auth setting must govern tenancy loads server-side."""

from types import SimpleNamespace

from oci_policy_analysis.presentation.web.api import routes_core


def test_resource_principal_mode_overrides_submitted_identity(monkeypatch) -> None:
    calls = []

    class FakeLoadService:
        def __init__(self, _ctx) -> None:
            pass

        def load_from_tenancy(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(success=True, message='Loaded', summary={})

    monkeypatch.setenv('WEB_RESOURCE_PRINCIPAL_ONLY', 'true')
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(status={}, settings={}))
    monkeypatch.setattr(routes_core, 'LoadService', FakeLoadService)
    monkeypatch.setattr(routes_core, '_track_web_operation', lambda *_args, **_kwargs: None)

    assert routes_core.get_load_auth_mode() == {'resource_principal_only': True}
    assert routes_core.list_profiles() == {'profiles': []}
    result = routes_core.load_tenancy(
        {'profile': 'ADMIN', 'instance_principal': True, 'session_token': 'submitted-token'}
    )

    assert result['success'] is True
    assert calls[0]['use_resource_principal'] is True
    assert calls[0]['use_instance_principal'] is False
    assert calls[0]['profile'] is None
    assert calls[0]['session_token'] is None


def test_default_mode_preserves_profile_and_instance_options(monkeypatch) -> None:
    calls = []

    class FakeLoadService:
        def __init__(self, _ctx) -> None:
            pass

        def load_from_tenancy(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(success=True, message='Loaded', summary={})

    monkeypatch.delenv('WEB_RESOURCE_PRINCIPAL_ONLY', raising=False)
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(status={}, settings={}))
    monkeypatch.setattr(routes_core, 'LoadService', FakeLoadService)
    monkeypatch.setattr(routes_core, '_track_web_operation', lambda *_args, **_kwargs: None)

    assert routes_core.get_load_auth_mode() == {'resource_principal_only': False}
    routes_core.load_tenancy({'profile': 'DEFAULT', 'instance_principal': True})

    assert calls[0]['use_resource_principal'] is False
    assert calls[0]['use_instance_principal'] is True
    assert calls[0]['profile'] == 'DEFAULT'


def test_web_load_uses_configured_depth_unless_request_overrides(monkeypatch):
    calls = []

    class FakeLoadService:
        def __init__(self, _ctx):
            pass

        def load_from_tenancy(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(success=True, message='Loaded', summary={})

    monkeypatch.setattr(
        routes_core,
        'get_context',
        lambda: SimpleNamespace(
            status={}, settings={'domain_compartment_depth': 2, 'recursive': True, 'load_all_users': False}
        ),
    )
    monkeypatch.setattr(routes_core, 'LoadService', FakeLoadService)
    monkeypatch.setattr(routes_core, '_track_web_operation', lambda *_args, **_kwargs: None)
    routes_core.load_tenancy({})
    routes_core.load_tenancy({'compartment_domain_search_depth': 3})
    assert calls[0]['compartment_domain_search_depth'] == 2
    assert calls[0]['recursive'] is True
    assert calls[0]['load_all_users'] is False
    assert calls[1]['compartment_domain_search_depth'] == 3
