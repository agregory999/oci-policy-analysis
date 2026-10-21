"""Regression coverage for tenancy-specific policy limit metadata."""

from types import SimpleNamespace

import pytest

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support.caching import CacheManager


def test_user_supplied_limits_are_validated_and_snapshot_scoped() -> None:
    repo = PolicyAnalysisRepository()

    limits = repo.set_user_supplied_tenancy_policy_limits('100', '500')

    assert limits['policies_count'] == 100
    assert limits['policy_statements_per_compartment_chain_count'] == 500
    assert limits['source'] == 'user-supplied'


def test_user_supplied_limits_reject_missing_or_nonpositive_values() -> None:
    repo = PolicyAnalysisRepository()

    with pytest.raises(ValueError, match='positive whole numbers'):
        repo.set_user_supplied_tenancy_policy_limits('0', '500')


def test_live_fetch_uses_policy_object_and_compartment_chain_limit_names() -> None:
    repo = PolicyAnalysisRepository()
    repo.tenancy_ocid = 'ocid1.tenancy.oc1..example'
    repo.limits_client = SimpleNamespace(list_limit_values=object())
    repo._api_call_with_logging = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
        data=[
            SimpleNamespace(name='policies-count', value=125),
            SimpleNamespace(name='policy-statements-per-compartment-chain-count', value=600),
            SimpleNamespace(name='statements-count', value=50),
        ]
    )

    assert repo.fetch_tenancy_policy_statement_limits() == (125, 600)
    assert repo.tenancy_policy_limits['policy_statements_per_compartment_chain_count'] == 600


def test_old_cache_without_limit_metadata_loads_normally(tmp_path) -> None:
    cache = CacheManager(cache_dir=tmp_path)
    cache_name = 'example_2026-09-03'
    cache_file = tmp_path / f'combined_cache_{cache_name}.json'
    cache_file.write_text(
        '{"policies": [], "policy_statements": [], "tenancy_name": "example", "compartments": []}',
        encoding='utf-8',
    )
    repo = PolicyAnalysisRepository()

    result = cache.load_combined_cache(repo, cache_name)

    assert result == str(cache_file)
    assert repo.tenancy_policy_limits == {}
    assert repo.current_cache_name == cache_name


def test_cache_limit_update_is_optional_and_local_to_one_cache(tmp_path) -> None:
    cache = CacheManager(cache_dir=tmp_path)
    cache_name = 'example_2026-09-03'
    cache_file = tmp_path / f'combined_cache_{cache_name}.json'
    cache_file.write_text('{"policies": [], "policy_statements": []}', encoding='utf-8')
    limits = {'policies_count': 100, 'policy_statements_per_compartment_chain_count': 500}

    assert cache.update_tenancy_policy_limits(cache_name, limits) is True
    assert cache.load_cache_into_local_json(cache_name)['tenancy_policy_limits'] == limits


@pytest.mark.parametrize(
    'live,cache_name,compliance,expected',
    [
        (True, '', False, True),
        (False, '', False, False),
        (True, 'active_cache', False, False),
        (True, '', True, False),
    ],
)
def test_policy_limits_eligibility_requires_live_source(live, cache_name, compliance, expected):
    from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService

    repo = SimpleNamespace(
        policies_loaded_from_tenancy=live,
        current_cache_name=cache_name,
        loaded_from_compliance_output=compliance,
        limits_client=object(),
    )
    service = PolicyLimitsService(SimpleNamespace(policy_repo=repo))
    assert service.is_live_loaded is expected
    assert service.can_fetch_live is expected
    repo.limits_client = None
    assert not service.can_fetch_live


def test_manual_limits_service_preserves_cache_format_and_other_metadata(tmp_path):
    import json

    from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService

    cache = CacheManager(tmp_path)
    cache_name = 'example_2026-10-21'
    path = tmp_path / f'combined_cache_{cache_name}.json'
    payload = {
        'version': 2,
        'schema_version': 3,
        'policies': [],
        'policy_statements': [],
        'tenancy_name': 'Example',
        'custom_evidence': {'keep': True},
    }
    path.write_text(json.dumps(payload))
    repo = PolicyAnalysisRepository()
    repo.current_cache_name = cache_name
    service = PolicyLimitsService(SimpleNamespace(policy_repo=repo, cache=cache))
    limits = service.apply_manual('1200', '900')
    saved = json.loads(path.read_text())
    assert saved.pop('tenancy_policy_limits') == limits
    assert saved == payload
    assert repo.tenancy_policy_statement_limit == (1200, 900)


def test_manual_limits_failure_restores_both_snapshot_representations(monkeypatch):
    from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService

    repo = PolicyAnalysisRepository()
    original = repo.set_user_supplied_tenancy_policy_limits('1000', '900')
    repo.current_cache_name = 'missing_cache'
    cache = SimpleNamespace(update_tenancy_policy_limits=lambda *args: False)
    service = PolicyLimitsService(SimpleNamespace(policy_repo=repo, cache=cache))
    with pytest.raises(OSError, match='Could not save'):
        service.apply_manual('1200', '950')
    assert repo.tenancy_policy_limits == original
    assert repo.tenancy_policy_statement_limit == (1000, 900)
    with pytest.raises(ValueError, match='positive whole numbers'):
        service.apply_manual('0', '950')
    assert repo.tenancy_policy_limits == original
    assert repo.tenancy_policy_statement_limit == (1000, 900)
    repo.current_cache_name = ''
    repo.policies_loaded_from_tenancy = True
    with pytest.raises(ValueError, match='live-loaded'):
        service.apply_manual('1200', '950')


def test_export_manual_limits_do_not_write_source_files_or_preferences():
    from oci_policy_analysis.application.services.policy_limits_service import PolicyLimitsService

    repo = PolicyAnalysisRepository()
    context = SimpleNamespace(policy_repo=repo, settings={'keep': True})
    limits = PolicyLimitsService(context).apply_manual('1000', '900')
    assert limits['source'] == 'user-supplied'
    assert context.settings == {'keep': True}


@pytest.mark.parametrize('profile', ['full', 'minimal', 'none'])
def test_live_load_collects_limits_before_enrichment_and_cache_save(monkeypatch, profile):
    from oci.response import Response

    from oci_policy_analysis.application.services.load_service import LoadService

    repo = PolicyAnalysisRepository()
    repo.current_cache_name = 'old_cache'
    repo.set_user_supplied_tenancy_policy_limits('100', '500')
    calls = []

    def list_limits(**kwargs):
        calls.append(kwargs)
        if not kwargs.get('page'):
            return Response(
                200, {'opc-next-page': 'second'}, [SimpleNamespace(name='policies-count', value=1200)], None
            )
        return Response(
            200, {}, [SimpleNamespace(name='policy-statements-per-compartment-chain-count', value=900)], None
        )

    def initialize(**kwargs):
        assert repo.current_cache_name == '' and repo.tenancy_policy_limits == {}
        repo.tenancy_ocid = 'new-tenancy'
        repo.limits_client = SimpleNamespace(list_limit_values=list_limits)
        return True

    monkeypatch.setattr(repo, 'initialize_client', initialize)
    for method in ('load_compartments_only', 'load_complete_identity_domains', 'load_policies_only'):
        monkeypatch.setattr(repo, method, lambda **kwargs: True)
    observed = []
    context = SimpleNamespace(
        policy_repo=repo,
        settings={},
        cache_service=SimpleNamespace(
            save_cache=lambda current: observed.append(('cache', dict(current.tenancy_policy_limits)))
        ),
    )
    loader = LoadService(context)
    monkeypatch.setattr(
        loader,
        '_run_post_load_with_stage',
        lambda **kwargs: observed.append(('enrichment', dict(repo.tenancy_policy_limits))),
    )
    stages = []
    result = loader.load_from_tenancy(
        use_instance_principal=False, post_load_profile=profile, on_stage=lambda *args: stages.append(args)
    )
    assert result.success
    assert [step for step, _ in observed] == ['enrichment', 'cache']
    assert all(limits['policy_statements_per_compartment_chain_count'] == 900 for _, limits in observed)
    assert all(limits['source'] == 'live OCI' for _, limits in observed)
    assert len(calls) == 2 and calls[1]['page'] == 'second'
    assert all(call['compartment_id'] == 'new-tenancy' for call in calls)
    assert any(stage == 'Loading Policy Limits' for stage, *_ in stages)


def test_live_load_limit_failure_is_nonfatal_and_reports_warning(monkeypatch):
    from oci.exceptions import ServiceError

    from oci_policy_analysis.application.services.load_service import LoadService

    repo = PolicyAnalysisRepository()

    def forbidden(**kwargs):
        raise ServiceError(403, 'NotAuthorized', {}, 'Limits permission denied')

    def initialize(**kwargs):
        repo.tenancy_ocid = 'T'
        repo.limits_client = SimpleNamespace(list_limit_values=forbidden)
        return True

    monkeypatch.setattr(repo, 'initialize_client', initialize)
    for method in ('load_compartments_only', 'load_complete_identity_domains', 'load_policies_only'):
        monkeypatch.setattr(repo, method, lambda **kwargs: True)
    context = SimpleNamespace(policy_repo=repo, settings={})
    stages = []
    result = LoadService(context).load_from_tenancy(
        use_instance_principal=False,
        run_post_load_intelligence=False,
        save_cache_after_load=False,
        on_stage=lambda *args: stages.append(args),
    )
    assert result.success
    assert repo.tenancy_policy_limits == {}
    assert repo._cleanup_reload_api_errors == ['LimitsClient.list_limit_values (identity)']
    assert any(stage == 'Policy Limits Unavailable' and state == 'warning' for stage, _, state in stages)
