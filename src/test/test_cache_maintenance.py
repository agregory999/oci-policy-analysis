"""Cache maintenance preserves payloads and protects locked snapshots."""

import json
from pathlib import Path

import pytest

from oci_policy_analysis.application.core.support.caching import CacheManager


@pytest.fixture
def saved(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    name = 'tenant_original'
    path = tmp_path / f'combined_cache_{name}.json'
    path.write_bytes(b'{"policies":[],"policy_statements":[],"version":2}')
    (tmp_path / 'cache_entries.json').write_text(
        json.dumps({'tenancy_name': 'tenant', 'cache_date': 'original', 'preserved': False}) + '\n',
        encoding='utf-8',
    )
    return cache, name, path


def test_lock_rename_unlock_delete_retains_payload_and_metadata(saved):
    cache, name, path = saved
    original = path.read_bytes()
    assert cache.preserve_cache_entry(name)
    assert not cache.remove_cache_entry(name)
    assert cache.rename_cache_entry(name, 'tenant_baseline')
    renamed = path.with_name('combined_cache_tenant_baseline.json')
    assert renamed.read_bytes() == original and not path.exists()
    assert cache.get_preserved_cache_set() == {'tenant_baseline'}
    cache._cull_old_caches('tenant')
    assert cache.get_available_cache(None) == ['tenant_baseline']
    assert not cache.remove_cache_entry('tenant_baseline')
    assert cache.preserve_cache_entry('tenant_baseline', False)
    assert cache.remove_cache_entry('tenant_baseline')
    assert not renamed.exists() and not cache.get_available_cache(None)


@pytest.mark.parametrize(
    'invalid',
    ['../escape', 'tenant_../escape', 'tenant_bad:name', 'tenant_bad\\name', '', 'missingseparator', 'tenant_bad.'],
)
def test_invalid_cache_names_are_rejected_without_modification(saved, invalid):
    cache, name, path = saved
    index = (cache.cache_dir / 'cache_entries.json').read_bytes()
    assert not cache.rename_cache_entry(name, invalid)
    assert not cache.remove_cache_entry(invalid)
    assert not cache.preserve_cache_entry(invalid)
    assert path.exists() and (cache.cache_dir / 'cache_entries.json').read_bytes() == index


def test_rename_collision_never_overwrites_unindexed_file(saved):
    cache, name, path = saved
    target = cache.cache_dir / 'combined_cache_tenant_collision.json'
    target.write_bytes(b'other snapshot')
    assert not cache.rename_cache_entry(name, 'tenant_collision')
    assert path.exists() and target.read_bytes() == b'other snapshot'
    assert cache.get_available_cache(None) == [name]


def test_index_failure_retains_original_and_removes_temporary_target(saved, monkeypatch):
    cache, name, path = saved

    def fail(_lines):
        raise OSError('index unavailable')

    monkeypatch.setattr(cache, '_write_cache_index', fail)
    assert not cache.rename_cache_entry(name, 'tenant_new')
    assert not cache.remove_cache_entry(name)
    assert not cache.preserve_cache_entry(name)
    assert path.exists() and not (cache.cache_dir / 'combined_cache_tenant_new.json').exists()


@pytest.mark.parametrize('action', ['rename', 'delete'])
def test_unlink_failure_restores_index_and_source(saved, monkeypatch, action):
    cache, name, path = saved
    original_unlink = Path.unlink

    def fail_source(self, *args, **kwargs):
        if self == path:
            raise OSError('source busy')
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', fail_source)
    success = cache.rename_cache_entry(name, 'tenant_new') if action == 'rename' else cache.remove_cache_entry(name)
    assert not success
    assert path.exists() and cache.get_available_cache(None) == [name]
    assert not (cache.cache_dir / 'combined_cache_tenant_new.json').exists()


def test_renamed_cache_survives_cleanup_after_many_newer_entries(saved):
    cache, name, path = saved
    assert cache.rename_cache_entry(name, 'tenant_baseline')
    with (cache.cache_dir / 'cache_entries.json').open('a') as stream:
        for number in range(15):
            date = f'2026-10-17-12-00-{number:02d}-UTC'
            (cache.cache_dir / f'combined_cache_tenant_{date}.json').write_text('{}')
            stream.write(json.dumps({'tenancy_name': 'tenant', 'cache_date': date}) + '\n')
    cache._cull_old_caches('tenant')
    assert 'tenant_baseline' in cache.get_available_cache(None)
    assert len(cache.get_available_cache(None)) == 11
