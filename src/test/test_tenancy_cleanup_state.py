"""Tenancy isolation and durable cleanup tracking across loads/restarts."""

import json
from types import MethodType, SimpleNamespace

import pytest
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.presentation.desktop.consolidation_workbench_tab import ConsolidationWorkbenchTab
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab


def _action(tenancy, dg='dg-1'):
    return {
        '#': 1,
        'wb_id': 'wb-1',
        'tenancy_ocid': tenancy,
        'Type': 'Unused Dynamic Group',
        'finding_identity': ['Unused Dynamic Group', dg, ''],
        'Status': 'Open',
        'History': 'Added',
    }


def test_cleanup_persistence_is_tenancy_scoped_and_clear_does_not_erase_other_tenancies(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    cache.save_cleanup_progress('tenancy-a', [_action('tenancy-a'), _action('tenancy-b')])
    cache.save_cleanup_progress('tenancy-b', [_action('tenancy-b')])
    assert cache.load_cleanup_progress('tenancy-a') == [_action('tenancy-a')]
    assert cache.load_cleanup_progress('tenancy-b') == [_action('tenancy-b')]
    assert cache.load_cleanup_progress('tenancy-c') == []
    cache.save_cleanup_progress('tenancy-a', [])
    assert cache.load_cleanup_progress('tenancy-a') == []
    assert cache.load_cleanup_progress('tenancy-b') == [_action('tenancy-b')]
    assert not list(tmp_path.rglob('*.tmp'))


def test_cleanup_state_rejects_wrong_tenancy_envelope(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    cache.save_cleanup_progress('tenancy-a', [])
    cache._cleanup_progress_path('tenancy-a').write_text(json.dumps({'tenancy_ocid': 'tenancy-b', 'actions': []}))
    with pytest.raises(ValueError, match='requested tenancy'):
        cache.load_cleanup_progress('tenancy-a')


def test_switch_away_and_back_restores_progress_and_reconciles_json_identity(tmp_path):
    cache = CacheManager(cache_dir=tmp_path)
    cache.save_cleanup_progress('tenancy-a', [_action('tenancy-a')])
    repo = SimpleNamespace(tenancy_ocid='tenancy-a')
    tab = SimpleNamespace(
        app=SimpleNamespace(policy_compartment_analysis=repo, caching=cache, settings={}),
        _refresh_workbench_table=lambda: None,
        _on_workbench_row_selected=lambda rows: None,
        _refresh_workbench_script=lambda **kwargs: None,
        _get_cleanup_issues=lambda **kwargs: [],
    )
    for name in ('_activate_cleanup_tenancy', '_save_cleanup_progress', '_reconcile_cleanup_progress'):
        setattr(tab, name, MethodType(getattr(PolicyRecommendationsTab, name), tab))
    tab._activate_cleanup_tenancy()
    assert tab._workbench_actions == [_action('tenancy-a')]
    repo.tenancy_ocid = 'tenancy-b'
    tab._activate_cleanup_tenancy()
    assert tab._workbench_actions == []
    assert tab._cleanup_payload_by_key == {}
    assert tab.ignored_cleanup_keys == set()
    repo.tenancy_ocid = 'tenancy-a'
    tab._activate_cleanup_tenancy()
    assert tab._workbench_actions[0]['Status'] == 'Open'  # Restore alone is not verification.
    tab._reconcile_cleanup_progress()
    saved = CacheManager(cache_dir=tmp_path).load_cleanup_progress('tenancy-a')
    assert saved[0]['Status'] == 'Resolved'
    assert 'Reload' in saved[0]['History']
    assert cache.load_cleanup_progress('tenancy-b') == []


def test_failed_load_clears_previous_intelligence_simulation_and_prospective_service():
    repo = PolicyAnalysisRepository()
    repo.tenancy_ocid = 'tenancy-a'
    repo.regular_statements = [{'internal_id': 'same-id'}]
    old_intel = SimpleNamespace(overlay={'cleanup_items': {'unused_dynamic_groups': ['old']}})
    old_simulation = SimpleNamespace()
    events = []
    context = SimpleNamespace(
        policy_repo=repo,
        reference_data=None,
        intelligence=old_intel,
        simulation=old_simulation,
        _prospective_service=object(),
        cache=SimpleNamespace(load_combined_cache=lambda *args, **kw: False),
        on_data_reset=lambda: events.append('reset'),
    )
    result = LoadService(context).load_from_cache('missing', run_post_load_intelligence=False)
    assert not result.success
    assert context.intelligence is not old_intel
    assert context.simulation is not old_simulation
    assert context._prospective_service is None
    assert repo.tenancy_ocid is None
    assert repo.regular_statements == []
    assert context.data_generation == 1
    assert events == ['reset']


def test_consolidation_uses_repository_tenancy_and_clears_transient_ids():
    values = []
    text = SimpleNamespace(configure=lambda **kw: None, delete=lambda *args: values.append('cleared'))
    tab = SimpleNamespace(
        app=SimpleNamespace(tenancy_ocid='old', policy_compartment_analysis=SimpleNamespace(tenancy_ocid='new')),
        protected_statement_ids={'same-id'},
        candidate_table_selected_ids={'same-id'},
        script_text=text,
        plan_notes_text=text,
        plan_history_detail_text=text,
        plan_history_dropdown={},
        plan_status_label=SimpleNamespace(configure=lambda **kw: None),
        _set_plan_notes_and_skipped_from_plan=lambda plan: None,
    )
    assert ConsolidationWorkbenchTab._get_tenancy_ocid(tab) == 'new'
    ConsolidationWorkbenchTab.clear_tenancy_selection(tab)
    assert tab.candidate_table_selected_ids == set()
    assert tab.protected_statement_ids == set()
    assert tab._last_plan_for_script is None
    assert tab.plan_history_id_lookup == {}
    assert len(values) == 3


@pytest.mark.parametrize('fresh', [False, True])
def test_shared_live_load_verifies_persisted_progress_but_cached_load_does_not(tmp_path, fresh):
    from oci_policy_analysis.application.services.cleanup_progress_service import CleanupProgressService

    cache = CacheManager(cache_dir=tmp_path)
    cache.save_cleanup_progress('tenancy-a', [_action('tenancy-a')])
    context = SimpleNamespace(
        cache=cache,
        settings={},
        policy_repo=SimpleNamespace(tenancy_ocid='tenancy-a', _cleanup_live_refresh_complete=fresh),
        intelligence=SimpleNamespace(overlay={'cleanup_items': {'unused_dynamic_groups': []}}),
    )
    CleanupProgressService(context).reconcile()
    assert cache.load_cleanup_progress('tenancy-a')[0]['Status'] == ('Resolved' if fresh else 'Open')


def test_settings_live_load_reconciles_saved_progress_after_intelligence(tmp_path, monkeypatch):
    cache = CacheManager(cache_dir=tmp_path)
    cache.save_cleanup_progress('tenancy-a', [_action('tenancy-a')])
    repo = PolicyAnalysisRepository()

    def initialize(**kwargs):
        repo.tenancy_ocid = 'tenancy-a'
        return True

    monkeypatch.setattr(repo, 'initialize_client', initialize)
    monkeypatch.setattr(repo, 'load_compartments_only', lambda: True)
    monkeypatch.setattr(repo, 'load_complete_identity_domains', lambda **kwargs: True)
    monkeypatch.setattr(repo, 'load_policies_only', lambda: True)
    context = SimpleNamespace(policy_repo=repo, cache=cache, settings={})
    service = LoadService(context)

    def analyze(**kwargs):
        context.intelligence.overlay = {'cleanup_items': {'unused_dynamic_groups': []}}

    monkeypatch.setattr(service, '_run_post_load_with_stage', analyze)
    result = service.load_from_tenancy(use_instance_principal=False, profile='example', save_cache_after_load=False)
    assert result.success
    assert cache.load_cleanup_progress('tenancy-a')[0]['Status'] == 'Resolved'
