"""Regression coverage for immutable policy-only reload caches."""

import json
from types import SimpleNamespace

from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService


def _source_snapshot():
    return {
        'version': 2,
        'schema_version': 3,
        'tenancy_name': 'example',
        'tenancy_ocid': 'ocid1.tenancy.example',
        'data_as_of': '2026-09-09T10:00:00+00:00',
        'policies': [{'policy_ocid': 'policy-1', 'policy_name': 'Original'}],
        'policy_statements': [],
        'defined_tag_namespace_keys': {},
        'defined_aliases': [],
        'cross_tenancy_statements': [],
        'compartments': [],
        'identity_domains': [],
        'groups': [{'group_ocid': 'group-1', 'group_name': 'Retained IAM group'}],
        'users': [],
    }


def test_policy_reload_creates_versioned_snapshot_and_preserves_original(tmp_path):
    manager = CacheManager(cache_dir=tmp_path)
    base_name = 'example_2026-09-09-10-00-00-UTC'
    source_path = tmp_path / f'combined_cache_{base_name}.json'
    source_path.write_text(json.dumps(_source_snapshot()), encoding='utf-8')
    (tmp_path / 'cache_entries.json').write_text('', encoding='utf-8')
    repo = SimpleNamespace(
        tenancy_name='example',
        policies=[{'policy_ocid': 'policy-1', 'policy_name': 'Reloaded'}],
        regular_statements=[],
        defined_tag_namespace_keys={},
        compartments=[],
        defined_aliases=[],
        cross_tenancy_statements=[],
    )

    first = manager.update_policy_section(repo, '2026-09-09T11:00:00+00:00', base_cache_name=base_name)
    second = manager.update_policy_section(repo, '2026-09-09T12:00:00+00:00', base_cache_name=base_name)

    assert first and first.endswith('_reload-01.json')
    assert second and second.endswith('_reload-02.json')
    assert json.loads(source_path.read_text(encoding='utf-8'))['policies'][0]['policy_name'] == 'Original'
    reloaded = json.loads((tmp_path / f'combined_cache_{base_name}_reload-01.json').read_text(encoding='utf-8'))
    assert reloaded['snapshot_kind'] == 'policy_reload'
    assert reloaded['base_cache_name'] == base_name
    assert reloaded['groups'] == _source_snapshot()['groups']
    assert manager.get_available_cache('example') == [
        f'{base_name}_reload-02',
        f'{base_name}_reload-01',
    ]


def test_cache_list_hides_duplicate_legacy_index_entries(tmp_path):
    manager = CacheManager(cache_dir=tmp_path)
    entry = {'tenancy_name': 'example', 'cache_date': '2026-09-09-10-00-00-UTC', 'preserved': False}
    (tmp_path / 'cache_entries.json').write_text(f'{json.dumps(entry)}\n{json.dumps(entry)}\n', encoding='utf-8')

    assert manager.get_available_cache('example') == ['example_2026-09-09-10-00-00-UTC']


def test_historical_comparison_skips_iam_for_policy_reload_snapshot():
    class Caches:
        def load_cache_into_local_json(self, *, cached_tenancy):
            return {
                'snapshot_kind': 'policy_reload' if cached_tenancy == 'reload' else 'full',
                'policies': [],
                'policy_statements': [],
                'defined_aliases': [],
                'cross_tenancy_statements': [],
                'identity_domains': [],
                'groups': [],
                'dynamic_groups': [],
                'users': [],
            }

    result = HistoricalAnalysisService(Caches()).compare_caches(left_cache='full', right_cache='reload')

    assert result.identity_comparable is False
    assert result.identity_sections == []
