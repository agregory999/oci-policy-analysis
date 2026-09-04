from types import SimpleNamespace

from oci_policy_analysis.application.core.common.consolidation_opportunities import build_consolidation_opportunities
from oci_policy_analysis.application.core.common.grouping_helpers import find_similar_principal_statement_groups
from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.core.engine.strategies.group_similar_statements import GroupSimilarStatements


def _statement(internal_id, policy_ocid, policy_name, subject, raw, **overrides):
    statement = {
        'internal_id': internal_id,
        'policy_ocid': policy_ocid,
        'policy_name': policy_name,
        'compartment_ocid': 'finance-ocid',
        'effective_path': 'ROOT/Finance',
        'location': 'in compartment Finance',
        'action': 'allow',
        'subject_type': 'group',
        'subject': subject,
        'verb': 'read',
        'resource': 'buckets',
        'permission': [],
        'conditions': "where target.bucket.name = 'reports'",
        'conditions_where_clause': "where target.bucket.name = 'reports'",
        'comments': '',
        'valid': True,
        'statement_text': raw,
    }
    statement.update(overrides)
    return statement


def _repo(statements):
    return SimpleNamespace(
        tenancy_ocid='root-ocid',
        compartments=[
            {'id': 'root-ocid', 'hierarchy_path': 'ROOT'},
            {'id': 'finance-ocid', 'hierarchy_path': 'ROOT/Finance'},
        ],
        policies=[
            {'policy_ocid': 'policy-a', 'policy_name': 'A', 'compartment_ocid': 'finance-ocid'},
            {'policy_ocid': 'policy-b', 'policy_name': 'B', 'compartment_ocid': 'finance-ocid'},
        ],
        regular_statements=statements,
    )


def test_grouping_deduplicates_principals_and_creates_new_policy():
    first = _statement(
        'one',
        'policy-a',
        'A',
        [('Default', 'Developers')],
        "allow group Developers to read buckets in compartment Finance where target.bucket.name = 'reports'",
    )
    second = _statement(
        'two',
        'policy-b',
        'B',
        [('Ops', 'Operators'), ('Default', 'Developers')],
        "allow group 'Ops'/'Operators', 'Default'/'Developers' to read buckets in compartment Finance where target.bucket.name = 'reports'",
    )
    repo = _repo([first, second])

    groups = find_similar_principal_statement_groups(repo.regular_statements)
    assert groups[0].principals == [('Default', 'Developers'), ('Ops', 'Operators')]

    plan = GroupSimilarStatements().build_plan(
        repo=repo,
        tenancy_ocid='root-ocid',
        dataset_version=None,
        candidate_internal_ids={'one', 'two'},
        protected_internal_ids=set(),
        plan_id='GROUP-PLAN',
    )

    additions = [step for step in plan['plan_steps'] if step['action'] == 'add']
    assert len(additions) == 1
    assert additions[0]['create_policy_name'].startswith('Consolidated-Grouped-GROUP-PLAN')
    assert additions[0]['after_statements'] == [
        "allow group 'Default'/'Developers', 'Ops'/'Operators' to read buckets in compartment Finance where target.bucket.name = 'reports'"
    ]
    assert additions[0]['rollback']['action'] == 'delete_created_policy'
    assert additions[0]['location_change_notes'][0].startswith('Policy grouping: combined 2 statements')
    cleanup = [step for step in plan['plan_steps'] if step['action'] == 'delete']
    assert {step['policy_ocid'] for step in cleanup} == {'policy-a', 'policy-b'}
    assert all(step['rollback']['action'] == 'recreate_deleted_policy' for step in cleanup)


def test_grouping_requires_matching_action_and_policy_compartment():
    first = _statement(
        'one',
        'policy-a',
        'A',
        [('Default', 'Developers')],
        'allow group Developers to read buckets in compartment Finance',
        conditions='',
        conditions_where_clause='',
    )
    different_action = _statement(
        'two',
        'policy-b',
        'B',
        [('Default', 'Auditors')],
        'deny group Auditors to read buckets in compartment Finance',
        action='deny',
        conditions='',
        conditions_where_clause='',
    )
    different_compartment = _statement(
        'three',
        'policy-c',
        'C',
        [('Default', 'Operators')],
        'allow group Operators to read buckets in compartment Finance',
        compartment_ocid='other-ocid',
        conditions='',
        conditions_where_clause='',
    )
    repo = _repo([first, different_action, different_compartment])
    repo.policies.append({'policy_ocid': 'policy-c', 'policy_name': 'C', 'compartment_ocid': 'other-ocid'})

    plan = GroupSimilarStatements().build_plan(
        repo=repo,
        tenancy_ocid='root-ocid',
        dataset_version=None,
        candidate_internal_ids={'one', 'two', 'three'},
        protected_internal_ids=set(),
        plan_id='NO-GROUP',
    )

    assert plan['plan_steps'] == []
    assert {item['internal_id'] for item in plan['skipped_statements']} == {'one', 'two', 'three'}


def test_grouping_supports_matching_permission_sets_without_verb_resource():
    first = _statement(
        'one',
        'policy-a',
        'A',
        [('Default', 'Developers')],
        'allow group Developers to manage buckets in compartment Finance',
        verb='',
        resource='',
        permission=['BUCKET_READ'],
        conditions='',
        conditions_where_clause='',
    )
    second = _statement(
        'two',
        'policy-b',
        'B',
        [('Default', 'Auditors')],
        'allow group Auditors to manage buckets in compartment Finance',
        verb='',
        resource='',
        permission=['bucket_read'],
        conditions='',
        conditions_where_clause='',
    )

    assert len(find_similar_principal_statement_groups([first, second])) == 1


def test_grouping_recommendation_has_its_own_category():
    first = _statement(
        'one',
        'policy-a',
        'A',
        [('Default', 'Developers')],
        'allow group Developers to read buckets in compartment Finance',
        conditions='',
        conditions_where_clause='',
    )
    second = _statement(
        'two',
        'policy-b',
        'B',
        [('Default', 'Auditors')],
        'allow group Auditors to read buckets in compartment Finance',
        conditions='',
        conditions_where_clause='',
    )
    engine = PolicyIntelligenceEngine(_repo([first, second]), strategies=[])
    engine.build_policy_consolidation()
    engine.overlay['cleanup_items'] = {}
    engine.build_overall_recommendations()

    finding = next(
        item for item in engine.overlay['consolidations'] if item.get('Strategy ID') == 'group_similar_statements'
    )
    assert "'Default'/'Auditors'" in finding['ActionDetail']
    recommendation = next(item for item in engine.overlay['recommendations'] if item['Category'] == 'Policy Grouping')
    assert recommendation['Recommendation'] == 'Group similar policy statements'


def test_shared_opportunity_builder_keeps_group_members_and_coalesces_placement():
    first = _statement('one', 'policy-a', 'A', [('Default', 'Developers')], 'allow group Developers to read buckets')
    second = _statement('two', 'policy-b', 'B', [('Default', 'Auditors')], 'allow group Auditors to read buckets')
    repo = _repo([first, second])
    overlay = {
        'consolidations': [
            {
                'Consolidation Type': 'Group similar statements',
                'Statement Internal IDs': ['one', 'two'],
                'Policy Name(s)': 'A, B',
                'Compartment': 'ROOT/Finance',
                'Consolidation Reason': 'Only principals differ.',
                'Action': 'Plan: Create a new policy.',
                'ActionDetail': "Proposed statement: allow group 'Default'/'Auditors' to read buckets",
            }
        ],
        'recommendations': [
            {
                'Category': 'Policy Placement',
                'Evidence': [
                    {
                        'Statement Internal ID': 'one',
                        'Policy': 'A',
                        'Policy OCID': 'policy-a',
                        'Policy Compartment Path': 'ROOT',
                        'Effective Path': 'ROOT/Finance',
                        'Statement': first['statement_text'],
                    },
                    {
                        'Statement Internal ID': 'two',
                        'Policy': 'A',
                        'Policy OCID': 'policy-a',
                        'Policy Compartment Path': 'ROOT',
                        'Effective Path': 'ROOT/Finance',
                        'Statement': second['statement_text'],
                    },
                ],
            }
        ],
    }

    opportunities = build_consolidation_opportunities(overlay, repo)

    grouping = next(item for item in opportunities if item['Type'] == 'Group similar statements')
    placement = next(item for item in opportunities if item['Type'] == 'Policy placement')
    assert grouping['Statement Internal IDs'] == ['one', 'two']
    assert grouping['Handoff Mode'] == 'supported'
    assert len(grouping['Evidence']['members']) == 2
    assert placement['Statements'] == 2
