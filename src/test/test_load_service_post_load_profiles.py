"""Tests for LoadService post-load profile routing."""

from types import SimpleNamespace

from oci_policy_analysis.application.services import load_service as load_service_module
from oci_policy_analysis.application.services.load_service import LoadService


class _Cache:
    def load_combined_cache(self, _repo, *, named_cache: str) -> bool:
        return bool(named_cache)


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        policy_repo=SimpleNamespace(compartments=[], policies=[], regular_statements=[], groups=[], users=[]),
        cache=_Cache(),
        status={},
        set_status=lambda **kwargs: None,
    )


def test_load_service_minimal_profile_runs_minimal_enrichment_only(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        load_service_module,
        'run_minimal_post_load_enrichment',
        lambda *_args, **_kwargs: calls.append('minimal'),
    )
    monkeypatch.setattr(load_service_module, 'run_post_load_pipeline', lambda *_args, **_kwargs: calls.append('full'))

    result = LoadService(_context()).load_from_cache('cache1', post_load_profile='minimal')

    assert result.success is True
    assert calls == ['minimal']


def test_load_service_full_profile_runs_full_pipeline(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        load_service_module,
        'run_minimal_post_load_enrichment',
        lambda *_args, **_kwargs: calls.append('minimal'),
    )
    monkeypatch.setattr(load_service_module, 'run_post_load_pipeline', lambda *_args, **_kwargs: calls.append('full'))

    result = LoadService(_context()).load_from_cache('cache1', post_load_profile='full')

    assert result.success is True
    assert calls == ['full']
