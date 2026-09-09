"""Supersession shares manual remediation tracking and tenancy-scoped ignores."""

from types import MethodType, SimpleNamespace

import pytest
from oci_policy_analysis.application.core.engine.recommendation_actions import (
    current_supersession_identities,
    reconcile_cleanup_actions,
    supersession_finding_identity,
)
from oci_policy_analysis.application.core.support.caching import CacheManager
from oci_policy_analysis.application.services.cleanup_progress_service import CleanupProgressService
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab


def _statement(internal_id='1'):
    return {
        'internal_id': internal_id,
        'policy_ocid': 'policy-a',
        'policy_name': 'Example',
        'statement_text': 'allow group G to read buckets in tenancy',
        'compartment_path': 'ROOT',
        'compartment_ocid': 'tenancy-a',
        'effective_path': 'ROOT',
        'valid': True,
    }


def _overlay(internal_id='1'):
    return {'supersessions': [{'statement_internal_id': internal_id, 'classification': 'Complete', 'evidence': []}]}


def _tab(tmp_path):
    repo = SimpleNamespace(tenancy_ocid='tenancy-a', regular_statements=[_statement()], compartments=[])
    tab = SimpleNamespace(
        app=SimpleNamespace(
            policy_compartment_analysis=repo,
            caching=CacheManager(tmp_path),
            policy_intelligence=SimpleNamespace(overlay=_overlay()),
        ),
        policy_repo=repo,
        supersession_compartment_filter='ALL',
        ignored_cleanup_keys=set(),
        _update_supersession_compartment_filter=lambda paths: None,
        supersession_table=SimpleNamespace(update_data=lambda rows: None),
    )
    for name in (
        '_get_supersession_rows',
        '_on_supersession_ignore',
        '_load_ignored_cleanup_keys_from_state',
        '_save_ignored_cleanup_keys_to_state',
        'update_supersession_tab_output',
    ):
        setattr(tab, name, MethodType(getattr(PolicyRecommendationsTab, name), tab))
    return tab


def test_ignore_survives_restart_and_internal_id_change_but_not_tenancy_switch(tmp_path):
    tab = _tab(tmp_path)
    rows = tab._get_supersession_rows()
    assert len(rows) == 1
    tab._on_supersession_ignore(rows)
    assert tab._get_supersession_rows() == []
    assert len(tab._get_supersession_rows(include_ignored=True)) == 1
    restarted = _tab(tmp_path)
    restarted.policy_repo.regular_statements = [_statement('changed')]
    restarted.app.policy_intelligence.overlay = _overlay('changed')
    restarted._load_ignored_cleanup_keys_from_state()
    assert restarted._get_supersession_rows() == []
    restarted.policy_repo.tenancy_ocid = 'tenancy-b'
    restarted._load_ignored_cleanup_keys_from_state()
    assert len(restarted._get_supersession_rows()) == 1


def test_attempt_fix_creates_manual_guidance_with_stable_finding_identity(tmp_path):
    tab = _tab(tmp_path)
    tracked = []
    tab._add_workbench_actions = tracked.extend
    PolicyRecommendationsTab._on_supersession_attempt_fix(tab, tab._get_supersession_rows())
    assert len(tracked) == 1
    assert tracked[0]['finding_identity'] == supersession_finding_identity(_statement())
    assert tracked[0]['tenancy_ocid'] == 'tenancy-a'
    assert tracked[0]['Source'] == 'Supersession'
    assert 'remove only the superseded statement' in tracked[0]['ui_instructions']
    assert 'Reload All' in tracked[0]['ui_instructions']


@pytest.mark.parametrize(
    'present,enabled,status', [(True, None, 'Open'), (False, None, 'Resolved'), (False, ['unused_groups'], 'Open')]
)
def test_supersession_reconciliation_respects_current_findings_and_enabled_checks(present, enabled, status):
    identity = supersession_finding_identity(_statement())
    action = {'tenancy_ocid': 'T', 'Type': 'Superseded Statement', 'finding_identity': list(identity), 'Status': 'Open'}
    current = current_supersession_identities(_overlay('new') if present else {}, [_statement('new')])
    result = reconcile_cleanup_actions([action], 'T', current, enabled=enabled)
    assert result[0]['Status'] == status


def test_live_service_includes_supersession_in_verification(tmp_path):
    tab = _tab(tmp_path)
    tab.policy_repo._cleanup_live_refresh_complete = True
    tab.app.caching.save_cleanup_progress(
        'tenancy-a',
        [
            {
                'tenancy_ocid': 'tenancy-a',
                'Type': 'Superseded Statement',
                'finding_identity': supersession_finding_identity(_statement()),
                'Status': 'Open',
            }
        ],
    )
    context = SimpleNamespace(
        policy_repo=tab.policy_repo, cache=tab.app.caching, intelligence=tab.app.policy_intelligence, settings={}
    )
    CleanupProgressService(context).reconcile()
    assert context.cache.load_cleanup_progress('tenancy-a')[0]['Status'] == 'Open'
    context.intelligence.overlay = {}
    CleanupProgressService(context).reconcile()
    assert context.cache.load_cleanup_progress('tenancy-a')[0]['Status'] == 'Resolved'
