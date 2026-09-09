"""Consistent status filenames and compatibility with older cleanup files."""

import hashlib
import json

import pytest
from oci_policy_analysis.application.core.support.caching import CacheManager


def test_state_files_share_readable_tenancy_naming(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    tenancy = 'ocid1.tenancy.oc1..example'
    for category, path in [
        ('cleanup', cache._cleanup_progress_path(tenancy)),
        ('prospects', cache._prospects_path(tenancy)),
        ('consolidation', cache._consolidation_state_path(tenancy)),
    ]:
        assert path == tmp_path / category / f'{category}_{tenancy}.json'


def _legacy_file(cache, tenancy):
    path = cache.cache_dir / 'cleanup' / f'{hashlib.sha256(tenancy.encode()).hexdigest()}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    action = {'tenancy_ocid': tenancy, 'Status': 'Open', 'History': 'Added'}
    path.write_text(json.dumps({'version': 1, 'tenancy_ocid': tenancy, 'actions': [action]}))
    return path, action


def test_legacy_cleanup_migrates_on_save_and_clear_stays_cleared(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    legacy, action = _legacy_file(cache, 'tenancy-a')
    assert cache.load_cleanup_progress('tenancy-a') == [action]
    assert legacy.exists()
    cache.save_cleanup_progress('tenancy-a', [action])
    assert not legacy.exists()
    assert CacheManager(cache_dir=tmp_path).load_cleanup_progress('tenancy-a') == [action]
    # A leftover old file must never override a newer canonical file, even an empty one.
    _legacy_file(cache, 'tenancy-a')
    cache.save_cleanup_progress('tenancy-a', [])
    _legacy_file(cache, 'tenancy-a')
    assert cache.load_cleanup_progress('tenancy-a') == []


def test_failed_migration_preserves_legacy_progress(tmp_path, monkeypatch):
    cache = CacheManager(cache_dir=tmp_path)
    legacy, action = _legacy_file(cache, 'tenancy-a')

    def fail_replace(*args):
        raise OSError('Save failed')

    monkeypatch.setattr('os.replace', fail_replace)
    with pytest.raises(OSError, match='Save failed'):
        cache.save_cleanup_progress('tenancy-a', [])
    assert legacy.exists()
    assert cache.load_cleanup_progress('tenancy-a') == [action]
    assert not list(tmp_path.rglob('*.tmp'))


@pytest.mark.parametrize('tenancy', ['', None, 'unknown', '../outside', 'a/b', 'a\\b'])
def test_invalid_tenancy_cannot_escape_state_directory(tmp_path, tenancy):
    cache = CacheManager(cache_dir=tmp_path)
    for path_builder in (cache._cleanup_progress_path, cache._prospects_path, cache._consolidation_state_path):
        with pytest.raises(ValueError):
            path_builder(tenancy)
