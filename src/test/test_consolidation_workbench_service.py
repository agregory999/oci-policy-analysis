from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from oci_policy_analysis.application.services.consolidation_workbench_service import (
    ConsolidationWorkbenchService,
)


class _FakeEngine:
    def __init__(self) -> None:
        self._progress = {}

    def get_strategy_display_names(self):  # pragma: no cover - trivial
        return ['Statement Density (Pack Policies)']

    def check_plan_progress(self, _plan):
        return self._progress

    def render_plan_ui_instructions(self, _plan, section='all'):
        return f'UI INSTRUCTIONS ({section})'

    def render_plan_commands(self, _plan):
        return 'CLI EXECUTION BLOCK'

    def render_plan_rollback_commands(self, _plan):
        return 'CLI ROLLBACK BLOCK'


class _FakeCache:
    def __init__(self, run_record):
        self._run_record = run_record
        self.last_update = None

    def get_history(self, _tenancy_ocid):
        return [self._run_record]

    def update_run_record(self, tenancy_ocid, effort_id, updates):
        self.last_update = (tenancy_ocid, effort_id, updates)
        self._run_record = {**self._run_record, **updates}
        return True


def _build_service(run_record, *, live=False):
    repo = SimpleNamespace(
        tenancy_ocid='ocid1.tenancy.oc1..example',
        regular_statements=[],
        policies=[],
        compartments=[],
        policies_loaded_from_tenancy=live,
        loaded_from_compliance_output=False,
    )
    cache = _FakeCache(run_record)
    ctx = SimpleNamespace(
        policy_repo=repo,
        cache=cache,
        reference_data=SimpleNamespace(),
    )
    svc = ConsolidationWorkbenchService(cast(Any, ctx))
    svc.engine = cast(Any, _FakeEngine())
    return svc, cache


def test_check_progress_noop_uses_persisted_progress_counts() -> None:
    run = {
        'consolidation_effort_id': 'E1',
        'plan': {
            'plan_id': 'E1',
            'plan_tags': {'strategy_id': 'statement_density_pack'},
            'plan_steps': [
                {
                    'step_id': 's1',
                    'action': 'modify',
                    'policy_ocid': 'p1',
                    'before_statements': [],
                    'after_statements': [],
                },
                {
                    'step_id': 's2',
                    'action': 'delete',
                    'policy_ocid': 'p2',
                    'before_statements': [],
                    'after_statements': [],
                },
            ],
        },
        'step_status': {
            'progress': {
                's1': {'executed': True},
                's2': {'executed': False},
            }
        },
    }
    svc, _cache = _build_service(run, live=False)

    result = svc.check_progress('E1')

    assert result['reload_status'] == 'noop'
    assert result['executed'] == 1
    assert result['total'] == 2
    assert result['completed'] is False
    assert isinstance(result['progress'], dict)


def test_render_script_includes_summary_header_and_body() -> None:
    run = {
        'consolidation_effort_id': 'E2',
        'plan': {
            'plan_id': 'E2',
            'plan_tags': {'strategy_id': 'statement_density_pack'},
            'plan_steps': [
                {
                    'step_id': 's1',
                    'action': 'modify',
                    'policy_ocid': 'p1',
                    'before_statements': ['a'],
                    'after_statements': ['a', 'b'],
                }
            ],
        },
    }
    svc, _cache = _build_service(run, live=False)

    txt = svc.render_script('E2', fmt='cli', section='execution')

    assert '# Consolidation Plan Summary' in txt
    assert '# Effort ID: E2' in txt
    assert '# Step Outline:' in txt
    assert 'CLI EXECUTION BLOCK' in txt
