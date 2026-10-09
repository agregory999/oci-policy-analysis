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
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(status={}))
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
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(status={}))
    monkeypatch.setattr(routes_core, 'LoadService', FakeLoadService)
    monkeypatch.setattr(routes_core, '_track_web_operation', lambda *_args, **_kwargs: None)

    assert routes_core.get_load_auth_mode() == {'resource_principal_only': False}
    routes_core.load_tenancy({'profile': 'DEFAULT', 'instance_principal': True})

    assert calls[0]['use_resource_principal'] is False
    assert calls[0]['use_instance_principal'] is True
    assert calls[0]['profile'] == 'DEFAULT'
