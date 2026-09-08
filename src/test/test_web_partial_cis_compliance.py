"""Contracts for partial CIS Compliance availability in the web workspace."""

from pathlib import Path
from types import SimpleNamespace

from oci_policy_analysis.presentation.web.api import routes_core

STATIC_DIR = Path('src/oci_policy_analysis/presentation/web/static')


def test_status_exposes_partial_compliance_capabilities(monkeypatch) -> None:
    repo = SimpleNamespace(
        tenancy_ocid='ocid1.tenancy.oc1..partial',
        tenancy_name='Partial Test',
        data_as_of='2026-09-03T00:00:00+00:00',
        loaded_from_compliance_output=True,
        policies_loaded_from_tenancy=False,
        policy_data_reloaded=None,
        load_all_users=True,
        compartments=[{}, {}],
        policies=[{}],
        regular_statements=[{}, {}],
        groups=[],
        users=[],
        compliance_capabilities={
            'policy_statements': True,
            'principal_resolution': False,
            'dynamic_groups_inventory': False,
            'defined_tag_catalog': False,
        },
        compliance_artifact_counts={'compartments': 2, 'policies': 1, 'statements': 2},
    )
    monkeypatch.setattr(routes_core, '_require_not_limited', lambda _request: None)
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace(policy_repo=repo, status={}))

    payload = routes_core.get_status(object())

    summary = payload['summary']
    assert summary['is_partial_compliance'] is True
    assert summary['compliance_capabilities']['policy_statements'] is True
    assert summary['compliance_capabilities']['principal_resolution'] is False
    assert summary['compliance_artifact_counts'] == {'compartments': 2, 'policies': 1, 'statements': 2}


def test_web_shared_auth_gate_renders_partial_compliance_banner_and_gates() -> None:
    auth_gate = (STATIC_DIR / 'auth-gate.js').read_text(encoding='utf-8')
    stylesheet = (STATIC_DIR / 'app.css').read_text(encoding='utf-8')

    assert 'Partial CIS Compliance dataset' in auth_gate
    assert 'compliance_capabilities' in auth_gate
    assert '/users-groups-analysis.html' in auth_gate
    assert '/dynamic-group-analysis.html' in auth_gate
    assert '/simulation.html' in auth_gate
    assert '/permissions-report.html' in auth_gate
    assert '/tag-namespaces.html' in auth_gate
    assert '/historical-analysis.html' in auth_gate
    assert 'capability-disabled' in auth_gate
    assert '.compliance-capability-banner' in stylesheet
    assert '.icon-button.capability-disabled' in stylesheet


def test_web_home_refreshes_capability_ui_after_a_successful_load() -> None:
    home = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')

    assert 'ociPolicyAnalysisRefreshComplianceCapabilities' in home
    assert home.count('await refreshTenancyDataStatus();') >= 3
