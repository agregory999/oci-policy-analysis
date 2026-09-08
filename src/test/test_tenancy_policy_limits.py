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
