"""Desktop post-load display refresh must not execute intelligence a second time."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from oci_policy_analysis.presentation.tk.policy_recommendations_tab import PolicyRecommendationsTab


def _tab():
    tab = object.__new__(PolicyRecommendationsTab)
    tab.app = SimpleNamespace(
        policy_intelligence=SimpleNamespace(run_all=MagicMock()),
        policy_compartment_analysis=SimpleNamespace(limits_client=None, _cleanup_live_refresh_complete=False),
        settings={},
    )
    tab.logger = MagicMock()
    tab.timed_step = lambda _label, operation: operation()
    for name in (
        '_activate_cleanup_tenancy',
        '_update_reload_all_button_state',
        '_load_ignored_cleanup_keys_from_state',
        'update_limits_tab_output',
        'update_risk_tab_output',
        'update_policy_risk_tab_output',
        'update_supersession_tab_output',
        'update_cross_tenancy_tab_output',
        'update_consolidation_tab_output',
        'update_cleanup_tab_output',
        'after',
    ):
        setattr(tab, name, MagicMock())
    tab._get_recommendation_summary = lambda: []
    tab._tenancy_limits_summary = lambda: 'No limits'
    tab.recommendation_table = MagicMock()
    return tab


def test_post_load_population_reuses_existing_intelligence(monkeypatch):
    monkeypatch.setattr('threading.Thread', lambda target, daemon: SimpleNamespace(start=target))
    tab = _tab()
    tab.app.policy_intelligence.run_all()  # The completed post-load analysis.
    tab.populate_data()
    assert tab.app.policy_intelligence.run_all.call_count == 1
    tab.update_risk_tab_output.assert_called_once()
    tab.update_cleanup_tab_output.assert_called_once()
    tab.recommendation_table.update_data.assert_called_once_with([])


def test_explicit_analytics_recalculation_still_runs_intelligence():
    tab = _tab()
    tab.reload_all_analytics()
    tab.app.policy_intelligence.run_all.assert_called_once()
    tab.update_risk_tab_output.assert_called_once()


def test_first_desktop_intelligence_pass_honors_saved_settings(monkeypatch):
    from oci_policy_analysis.main import App

    engine = SimpleNamespace(
        calculate_all_effective_compartments=MagicMock(),
        run_all=MagicMock(),
        build_permissions_report=MagicMock(),
        overlay={'cross_tenancy_findings': []},
    )
    monkeypatch.setattr('oci_policy_analysis.main.PolicyIntelligenceEngine', lambda _repo: engine)
    monkeypatch.setattr('oci_policy_analysis.main.PolicyCorpusBuilder', lambda: MagicMock())
    monkeypatch.setattr('oci_policy_analysis.main.CrossTenancyCorpusBuilder', lambda: MagicMock())
    monkeypatch.setattr('oci_policy_analysis.main.PolicySimulationEngine', lambda *args, **kwargs: MagicMock())
    desktop = SimpleNamespace(
        settings={
            'enabled_intelligence_checks': ['risk_scores'],
            'risk_where_clause_reduction_pct': 0,
            'risk_service_principal_reduction_pct': 75,
        },
        policy_compartment_analysis=SimpleNamespace(tenancy_ocid=None),
        reference_data_repo=object(),
        app_context=SimpleNamespace(),
        consolidation_engine=SimpleNamespace(get_strategy_display_names=lambda: ['Move Down']),
    )
    App._post_load_create_intelligence(desktop)
    engine.run_all.assert_called_once()
    arguments = engine.run_all.call_args.kwargs
    assert arguments['enabled_strategy_ids'] == ['risk_scores']
    assert arguments['params'] == {
        'where_clause_reduction_pct': 0,
        'service_principal_reduction_pct': 75,
        'consolidation_strategy_names': ['Move Down'],
    }
