"""Contract coverage for the Web consolidation workbench endpoints."""

from __future__ import annotations

from types import SimpleNamespace

from oci_policy_analysis.presentation.web.api import routes_core


class _WorkbenchService:
    """Small service double that records the Web-to-service contract."""

    calls: list[tuple[str, object]] = []

    def __init__(self, _ctx):
        pass

    def get_status(self):
        return {'strategy_names': ['Pack']}

    def get_protection_rows(self):
        return [{'internal_id': 'one'}]

    def get_protected_set(self):
        return {'protected': []}

    def set_protected_set(self, ids):
        self.calls.append(('protect', ids))
        return {'protected': [{'internal_id': item} for item in ids]}

    def get_candidate_rows(self, search=''):
        self.calls.append(('candidates', search))
        return {'rows': [{'internal_id': 'two'}], 'counts': {'protected': 1}}

    def create_proposal(self, candidate_internal_ids, strategy_display_name):
        self.calls.append(('proposal', (candidate_internal_ids, strategy_display_name)))
        return {'plan': {'plan_id': 'E1'}, 'rows': []}

    def get_history(self):
        return []

    def reset_for_tenancy(self):
        self.calls.append(('reset', None))
        return {'cleared_history_records': 1}


def test_web_consolidation_endpoints_delegate_to_workbench_service(monkeypatch) -> None:
    _WorkbenchService.calls = []
    monkeypatch.setattr(routes_core, 'get_context', lambda: SimpleNamespace())
    monkeypatch.setattr(routes_core, 'ConsolidationWorkbenchService', _WorkbenchService)
    monkeypatch.setattr(routes_core, '_track_web_operation', lambda *_args, **_kwargs: None)

    assert routes_core.get_consolidation_status()['status']['strategy_names'] == ['Pack']
    assert routes_core.set_consolidation_protected_set({'internal_ids': ['one']})['success'] is True
    assert routes_core.get_consolidation_candidates('bucket')['rows'] == [{'internal_id': 'two'}]
    assert (
        routes_core.create_consolidation_proposal({'strategy_display_name': 'Pack', 'candidate_internal_ids': ['two']})[
            'plan'
        ]['plan_id']
        == 'E1'
    )
    assert routes_core.reset_consolidation_for_tenancy()['cleared_history_records'] == 1

    assert _WorkbenchService.calls == [
        ('protect', ['one']),
        ('candidates', 'bucket'),
        ('proposal', (['two'], 'Pack')),
        ('reset', None),
    ]
