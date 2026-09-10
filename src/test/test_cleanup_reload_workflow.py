"""Live cleanup verification must refresh IAM and never resolve from failed loads."""

from types import SimpleNamespace

import pytest
from oci_policy_analysis.application.core.engine.recommendation_actions import cleanup_finding_identity
from oci_policy_analysis.main import App
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab


@pytest.mark.parametrize('failure', [None, 'load', 'wrong_tenancy', 'partial'])
def test_full_cleanup_reload_uses_live_load_settings_and_restores_failed_inventory(monkeypatch, failure):
    calls = []
    repo = SimpleNamespace(tenancy_ocid='tenancy-1', policies_loaded_from_tenancy=True, dynamic_groups=['old'])
    options = {'use_instance_principal': False, 'profile': 'live-profile', 'recursive': True, 'load_all_users': True}

    def load(**kwargs):
        calls.append(('load', kwargs))
        repo.dynamic_groups = ['fresh']
        repo.tenancy_ocid = 'other' if failure == 'wrong_tenancy' else 'tenancy-1'
        if failure == 'partial':
            repo._cleanup_reload_api_errors.append('IdentityDomainsClient.list_dynamic_resource_groups')
        return SimpleNamespace(success=failure != 'load', message='load failed')

    callbacks = []
    app = SimpleNamespace(
        policy_compartment_analysis=repo,
        _live_tenancy_load_options=options,
        _tenancy_load_in_progress=False,
        _policy_reload_in_progress=False,
        load_service=SimpleNamespace(load_from_tenancy=load),
        cache_service=SimpleNamespace(save_cache=lambda r: calls.append(('cache', list(r.dynamic_groups)))),
        after=lambda delay, fn: fn(),
        _set_policy_reload_progress_message=lambda msg: None,
        _close_policy_reload_progress_dialog=lambda: None,
        _post_load_create_intelligence=lambda: calls.append(('intelligence', list(repo.dynamic_groups))),
        _post_load_update_ui=lambda: calls.append(('ui', None)),
        update_status_bar=lambda: None,
        _build_data_load_summary=lambda: '',
    )
    monkeypatch.setattr(
        'oci_policy_analysis.main.threading.Thread', lambda target, daemon: SimpleNamespace(start=target)
    )
    App.reload_policies_and_compartments_and_update_cache_async(
        app,
        callback={'complete': lambda *args: callbacks.append(args)},
        show_popup=False,
        reload_iam=True,
    )
    assert calls[0][1]['profile'] == 'live-profile'
    assert calls[0][1]['load_all_users'] is True
    assert calls[0][1]['run_post_load_intelligence'] is False
    assert app._policy_reload_in_progress is False
    if failure:
        assert repo.dynamic_groups == ['old']
        assert repo.tenancy_ocid == 'tenancy-1'
        assert callbacks[0][0] is False
        assert [c[0] for c in calls] == ['load', 'ui']  # Redisplay the restored inventory.
    else:
        assert [c[0] for c in calls] == ['load', 'intelligence', 'cache', 'ui']
        assert callbacks[0][0] is True
        assert repo.dynamic_groups == ['fresh']


@pytest.mark.parametrize(
    'still_present,enabled,expected',
    [(False, None, 'Resolved'), (True, None, 'Open'), (False, ['invalid_statements'], 'Open')],
)
def test_cleanup_resolution_tracks_identity_and_does_not_treat_disabled_checks_as_fixed(
    still_present, enabled, expected
):
    row = {'Type': 'Unused Dynamic Group', 'Name': 'Default/Example', 'action_key': 'new-key'}
    payload = {'dynamic_group_ocid': 'dg-1'}
    action = {
        'verification_scope': {'recursive': False, 'compartment_domain_search_depth': 1},
        'Type': row['Type'],
        'finding_identity': cleanup_finding_identity(row, payload),
        'tenancy_ocid': 'tenancy-1',
        'Status': 'Open',
        'History': 'Added',
    }
    other_tenancy = {**action, 'tenancy_ocid': 'other'}
    app = SimpleNamespace(
        policy_compartment_analysis=SimpleNamespace(
            tenancy_ocid='tenancy-1', recursive=False, compartment_domain_search_depth=1
        ),
        settings={'enabled_intelligence_checks': enabled},
    )

    def findings(*, include_ignored):
        assert include_ignored is True
        return [row] if still_present else []

    tab = SimpleNamespace(
        app=app,
        _workbench_actions=[action, other_tenancy],
        _get_cleanup_issues=findings,
        _cleanup_payload_by_key={'new-key': payload},
        _refresh_workbench_table=lambda: None,
        _refresh_workbench_script=lambda **kw: None,
        _on_workbench_row_selected=lambda rows: None,
        _save_cleanup_progress=lambda: None,
    )
    PolicyRecommendationsTab._reconcile_cleanup_progress(tab)
    action = tab._workbench_actions[0]
    assert action['Status'] == expected
    assert 'Reload' in action['History']
    assert other_tenancy['History'] == 'Added'


@pytest.mark.parametrize('success', [True, False])
def test_cleanup_reload_only_reconciles_on_success(monkeypatch, success):
    callbacks = {}
    reconciled = []
    errors = []
    monkeypatch.setattr('tkinter.messagebox.showerror', lambda *args: errors.append(args))
    app = SimpleNamespace(
        policy_compartment_analysis=SimpleNamespace(policies_loaded_from_tenancy=True),
        _live_tenancy_load_options={'profile': 'live'},
    )

    def reload(**kwargs):
        assert kwargs['reload_iam'] is True
        callbacks.update(kwargs['callback'])

    app.reload_policies_and_compartments_and_update_cache_async = reload
    tab = SimpleNamespace(
        app=app,
        reload_all_btn={},
        _reconcile_cleanup_progress=lambda: reconciled.append(True),
        after=lambda delay, fn: fn(),
    )
    tab._update_reload_all_button_state = lambda: PolicyRecommendationsTab._update_reload_all_button_state(tab)
    PolicyRecommendationsTab._on_reload_all(tab)
    assert tab.reload_all_btn['state'] == 'disabled'
    callbacks['complete'](success, 'Result', not success)
    assert reconciled == ([True] if success else [])
    assert bool(errors) is not success
    assert tab.reload_all_btn['state'] == 'normal'


@pytest.mark.parametrize(
    'live,options,busy,expected',
    [
        (False, True, False, 'disabled'),
        (True, False, False, 'disabled'),
        (True, True, True, 'disabled'),
        (True, True, False, 'normal'),
    ],
)
def test_cleanup_reload_button_requires_live_source_and_settings(live, options, busy, expected):
    tab = SimpleNamespace(
        app=SimpleNamespace(
            policy_compartment_analysis=SimpleNamespace(policies_loaded_from_tenancy=live),
            _live_tenancy_load_options={'profile': 'live'} if options else None,
            _tenancy_load_in_progress=busy,
        ),
        reload_all_btn={},
    )
    PolicyRecommendationsTab._update_reload_all_button_state(tab)
    assert tab.reload_all_btn['state'] == expected


def test_partial_inventory_api_error_is_recorded_even_if_caller_catches_it():
    from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository

    repo = PolicyAnalysisRepository()
    repo._cleanup_reload_api_errors = []

    def failed_request():
        raise RuntimeError('Inventory unavailable')

    with pytest.raises(RuntimeError):
        repo._api_call_with_logging('IdentityDomainsClient.list_groups', failed_request)
    assert repo._cleanup_reload_api_errors == ['IdentityDomainsClient.list_groups']
