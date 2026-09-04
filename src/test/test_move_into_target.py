import pytest
from oci_policy_analysis.application.core.engine.strategies.base import (
    BaseConsolidationStrategy,
    PlacementResult,
    StatementPlacement,
    TargetPolicySpec,
)
from oci_policy_analysis.application.core.engine.strategies.move_into_target import MoveIntoTargetCompartment


class PlacementTestStrategy(BaseConsolidationStrategy):
    strategy_id = 'placement-test'
    display_name = 'Placement test'
    required_capabilities = frozenset()


@pytest.fixture
def minimal_repo():
    # Minimal compartments, policies, and statements to test the move_into_target logic
    compartments = [
        {'id': 'root_ocid', 'compartment_ocid': 'root_ocid', 'hierarchy_path': 'ROOT', 'name': 'tenancy'},
        {'id': 'comp1_ocid', 'compartment_ocid': 'comp1_ocid', 'hierarchy_path': 'ROOT/Comp1', 'name': 'Comp1'},
        {'id': 'db_ocid', 'compartment_ocid': 'db_ocid', 'hierarchy_path': 'ROOT/LZ1-Top/App/DB', 'name': 'DB'},
    ]
    policies = [
        {'policy_ocid': 'policyA', 'policy_name': 'AppPolicy', 'compartment_ocid': 'root_ocid'},
        {'policy_ocid': 'policyB', 'policy_name': 'AppPolicy', 'compartment_ocid': 'db_ocid'},
    ]
    regular_statements = [
        {
            'internal_id': 'S1',
            'policy_ocid': 'policyA',
            'statement_text': 'allow group G to manage db in compartment Comp1',
            'effective_path': 'ROOT/Comp1',
        },
        {
            'internal_id': 'S2',
            'policy_ocid': 'policyA',
            'statement_text': 'allow group G to manage db in compartment DB',
            'effective_path': 'ROOT/LZ1-Top/App/DB',
        },
        {
            'internal_id': 'S3',
            'policy_ocid': 'policyA',
            'statement_text': 'allow group G to manage db in compartment ROOT',
            'effective_path': 'ROOT',
        },
    ]

    class DummyRepo:
        def __init__(self):
            self.compartments = compartments
            self.policies = policies
            self.regular_statements = regular_statements
            self.tenancy_ocid = 'root_ocid'

    return DummyRepo()


def test_move_into_target_plan(minimal_repo):
    # Only S1 and S2 are move candidates; S3 is at root and should be skipped
    candidates = {'S1', 'S2', 'S3'}
    protected = set()
    plan = MoveIntoTargetCompartment().build_plan(
        repo=minimal_repo,
        tenancy_ocid='root_ocid',
        dataset_version=None,
        candidate_internal_ids=candidates,
        protected_internal_ids=protected,
        plan_id='PLAN123',
    )

    # 2 statements (S1, S2) should be planned for move (skips S3)
    # Check that plan steps include moving S1 -> Comp1 and S2 -> DB
    add_or_modify_targets = [step for step in plan['plan_steps'] if step['action'] in ('add', 'modify')]
    _target_comp_names = [step.get('create_policy_name') or '' for step in add_or_modify_targets]
    afters = [after for step in add_or_modify_targets for after in step['after_statements']]
    # Check correct after_statements and locations present
    assert any('Comp1' in after for after in afters)
    assert any('DB' in after for after in afters)
    # Confirm a delete or modify step exists for the source policy
    cleanup_steps = [step for step in plan['plan_steps'] if step['policy_ocid'] == 'policyA']
    assert cleanup_steps
    # Skipped statements list should have entry for S3
    skipped_ids = (
        [s.internal_id for s in getattr(plan, 'skipped_statements', [])]
        if hasattr(plan, 'skipped_statements')
        else [s['internal_id'] for s in plan.get('skipped_statements', [])]
    )
    assert 'S3' in skipped_ids


def test_move_into_target_plan_captures_structured_rollback(minimal_repo):
    plan = MoveIntoTargetCompartment().build_plan(
        repo=minimal_repo,
        tenancy_ocid='root_ocid',
        dataset_version=None,
        candidate_internal_ids={'S1'},
        protected_internal_ids=set(),
        plan_id='PLAN-ROLLBACK',
    )

    rollbacks = [step['rollback'] for step in plan['plan_steps']]
    assert rollbacks
    assert any(rollback['action'] == 'delete_created_policy' for rollback in rollbacks)
    assert any(
        rollback['action'] in {'restore_policy', 'recreate_deleted_policy'} and rollback.get('statements')
        for rollback in rollbacks
    )


def test_base_strategy_materializes_placements_and_source_cleanup(minimal_repo):
    strategy = PlacementTestStrategy()
    context = strategy.planning_context(
        repo=minimal_repo,
        tenancy_ocid='root_ocid',
        dataset_version=None,
        plan_id='PLACEMENT-PLAN',
        params=None,
    )
    result = PlacementResult(
        placements=[
            StatementPlacement(
                internal_id='S1',
                source_policy_ocid='policyA',
                target=TargetPolicySpec(
                    compartment_ocid='comp1_ocid',
                    hierarchy_path='ROOT/Comp1',
                    policy_name='AppPolicy',
                    description='Created by placement test.',
                ),
            )
        ],
        skipped_statements=[],
    )

    steps, skipped = strategy.materialize_placements(context, result)
    plan = strategy.finalize_plan(context, plan_steps=steps, skipped_statements=skipped, candidate_count=1)

    assert [step['action'] for step in plan['plan_steps']] == ['add', 'modify']
    assert plan['plan_steps'][0]['create_policy_name'] == 'AppPolicy'
    assert plan['plan_steps'][1]['rollback']['action'] == 'restore_policy'
