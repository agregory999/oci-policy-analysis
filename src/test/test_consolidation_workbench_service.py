from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine
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

    def get_or_create_consolidation_state(self, _tenancy_ocid):
        return {'protected_set': {'protected': [{'internal_id': 'protected'}]}, 'history': [self._run_record]}

    def save_consolidation_state(self, tenancy_ocid, state):
        self.last_update = (tenancy_ocid, state)


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

    ui_txt = svc.render_script('E2', fmt='ui', section='both')
    assert '# Consolidation Plan Summary' in ui_txt
    assert 'UI INSTRUCTIONS (all)' in ui_txt


def test_reset_for_tenancy_clears_protection_and_history_state() -> None:
    """Reset delegates the whole-tenancy state replacement to the cache."""
    svc, cache = _build_service({'consolidation_effort_id': 'E3'}, live=False)

    result = svc.reset_for_tenancy()

    assert result['cleared_history_records'] == 1
    assert cache.last_update == (
        'ocid1.tenancy.oc1..example',
        {'protected_set': {}, 'history': []},
    )


def test_history_detail_rebuilds_rows_when_legacy_run_has_no_cached_results() -> None:
    run = {
        'consolidation_effort_id': 'E3',
        'status': 'completed',
        'plan': {
            'plan_id': 'E3',
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
        'step_status': {'progress': {'s1': {'executed': True}}},
    }
    svc, _cache = _build_service(run, live=False)

    detail = svc.get_history_run_detail('E3')

    assert detail is not None
    assert detail['proposal_rows'][0]['action'] == 'MODIFY'
    assert detail['proposal_rows'][0]['status'] == 'Executed'


def test_protection_and_candidates_share_canonical_service_filters() -> None:
    """The same service contract used by Web is suitable for the Tk workbench."""

    repo = SimpleNamespace(
        tenancy_ocid='ocid1.tenancy.oc1..example',
        policies=[],
        compartments=[],
        regular_statements=[
            {'internal_id': 'keep', 'policy_name': 'Policy A', 'statement_text': 'allow group a to read buckets'},
            {
                'internal_id': 'invalid',
                'policy_name': 'Policy A',
                'statement_text': 'allow group b to read buckets',
                'invalid_reasons': ['invalid syntax'],
            },
            {
                'internal_id': 'system',
                'policy_name': 'Tenant Admin Policy',
                'statement_text': 'allow group admins to manage all-resources',
            },
            {'internal_id': 'candidate', 'policy_name': 'Policy B', 'statement_text': 'allow group c to use buckets'},
        ],
        policies_loaded_from_tenancy=False,
        loaded_from_compliance_output=False,
    )

    class Cache:
        def __init__(self):
            self.protected = {}

        def get_protected_set(self, _tenancy):
            return self.protected

        def set_protected_set(self, _tenancy, value):
            self.protected = value

    ctx = SimpleNamespace(policy_repo=repo, cache=Cache(), reference_data=SimpleNamespace())
    svc = ConsolidationWorkbenchService(cast(Any, ctx))

    saved = svc.set_protected_set(['keep', 'unknown'])
    assert [row['internal_id'] for row in saved['protected']] == ['keep']

    candidates = svc.get_candidate_rows()
    assert [row['internal_id'] for row in candidates['rows']] == ['candidate']
    assert candidates['counts'] == {'protected': 1, 'invalid': 1, 'system': 1}


def test_plan_rendering_uses_the_add_step_target_compartment() -> None:
    """Add-step guidance must agree with its non-root compartment ID."""

    repo = SimpleNamespace(
        tenancy_ocid='root-ocid',
        compartments=[
            {'id': 'root-ocid', 'hierarchy_path': 'ROOT'},
            {'id': 'finance-ocid', 'hierarchy_path': 'ROOT/Finance'},
        ],
        policies=[],
        regular_statements=[],
    )
    engine = ConsolidationEngine(
        cache_mgr=cast(Any, SimpleNamespace()),
        reference_data_repo=cast(Any, SimpleNamespace()),
        policy_repo=cast(Any, repo),
        strategies=[],
    )
    plan = {
        'plan_id': 'finance-plan',
        'tenancy_ocid': 'root-ocid',
        'plan_steps': [
            {
                'step_id': 'add-finance-policy',
                'action': 'add',
                'compartment_ocid': 'finance-ocid',
                'create_policy_name': 'Finance-Consolidated',
                'after_statements': ['allow group Finance to read buckets'],
            }
        ],
    }

    commands = engine.render_plan_commands(cast(Any, plan))
    instructions = engine.render_plan_ui_instructions(cast(Any, plan), section='all')
    rollback = engine.render_plan_rollback_commands(cast(Any, plan))

    assert '--compartment-id finance-ocid' in commands
    assert 'target compartment' in commands
    assert 'root compartment' not in commands
    assert 'Navigate to compartment: ROOT / Finance' in instructions
    assert 'Create a new policy in this compartment.' in instructions
    assert 'root compartment' not in instructions
    assert 'target compartment' in rollback
    assert 'root compartment' not in rollback


def test_proposal_compartments_display_paths_without_changing_execution_ocids() -> None:
    from copy import deepcopy

    svc, _ = _build_service({})
    target = 'ocid1.compartment.oc1..target'
    svc.repo.compartments = [{'id': target, 'hierarchy_path': 'ROOT/A/B'}]
    svc.repo.policies = [{'policy_ocid': 'p1', 'compartment_ocid': target, 'policy_name': 'Existing'}]
    plan = {
        'plan_steps': [
            {'action': 'add', 'compartment_ocid': target, 'create_policy_name': 'New'},
            {'action': 'add', 'compartment_ocid': svc.repo.tenancy_ocid},
            {'action': 'modify', 'policy_ocid': 'p1', 'compartment_ocid': target},
            {'action': 'delete', 'policy_ocid': 'p1', 'compartment_ocid': target},
        ]
    }
    original = deepcopy(plan)
    rows = svc.get_proposal_rows(cast(Any, plan))
    assert [row['Policy Compartment'] for row in rows] == ['ROOT/A/B', 'ROOT', 'ROOT/A/B', 'ROOT/A/B']
    assert all(row['policy_compartment'] == row['Policy Compartment'] for row in rows)
    assert rows[0]['compartment_ocid'] == target
    assert plan == original


def test_saved_proposal_compartments_resolve_ids_and_preserve_existing_paths() -> None:
    svc, _ = _build_service({})
    target = 'ocid1.compartment.oc1..target'
    svc.repo.compartments = [{'id': target, 'hierarchy_path': 'ROOT/A/B'}]
    rows = svc.get_proposal_rows(
        None,
        results_fallback=[
            {'Policy Compartment': target},
            {'policy_compartment': 'ROOT/C'},
            {'policy_compartment': 'ocid1.compartment.oc1..unknown'},
        ],
    )
    assert [row['Policy Compartment'] for row in rows] == ['ROOT/A/B', 'ROOT/C', 'ocid1.compartment.oc1..unknown']
