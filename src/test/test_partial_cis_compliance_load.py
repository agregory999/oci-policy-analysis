"""Regression coverage for policy-and-compartments-only CIS imports."""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest
from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine
from oci_policy_analysis.application.core.engine.intelligence_strategies.cleanup_unused_groups import UnusedGroupsCheck
from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.core.engine.strategies.move_closer_to_target import MoveCloserToTargetCompartment
from oci_policy_analysis.application.core.engine.strategies.move_down_next_level import MoveDownNextLevel
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.recommendations_service import RecommendationsService
from oci_policy_analysis.application.services.reports_service import ReportsService
from oci_policy_analysis.main import App
from oci_policy_analysis.presentation.desktop.consolidation_workbench_tab import ConsolidationWorkbenchTab
from oci_policy_analysis.presentation.desktop.policy_recommendations_tab import PolicyRecommendationsTab
from oci_policy_analysis.presentation.desktop.workload_principals_tab import WorkloadPrincipalsTab


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_minimum_compliance_export(tmp_path: Path, *, policy_identifier: str | None = None) -> None:
    tenancy_ocid = 'ocid1.tenancy.oc1..partialtest'
    app_compartment_ocid = 'ocid1.compartment.oc1..partialapps'
    _write_csv(
        tmp_path / 'raw_data_identity_compartments.csv',
        ['id', 'name', 'lifecycle_state', 'compartment_id', 'description'],
        [
            {
                'id': tenancy_ocid,
                'name': 'Partial Test Tenancy',
                'lifecycle_state': 'ACTIVE',
                'compartment_id': '',
                'description': '',
            },
            {
                'id': app_compartment_ocid,
                'name': 'Apps',
                'lifecycle_state': 'ACTIVE',
                'compartment_id': tenancy_ocid,
                'description': '',
            },
        ],
    )
    _write_csv(
        tmp_path / 'raw_data_identity_policies.csv',
        ['name', 'id', 'identifier', 'compartment_id', 'description', 'time_created', 'statements'],
        [
            {
                'name': 'Partial Test Policy',
                'id': 'ocid1.policy.oc1..partialtest',
                'identifier': policy_identifier or 'ocid1.policy.oc1..partialtest',
                'compartment_id': app_compartment_ocid,
                'description': '',
                'time_created': '2026-09-03T00:00:00+00:00',
                'statements': (
                    "[\"allow group 'Engineering'/'PlatformOps' to manage buckets in compartment Apps\", "
                    '"allow dynamic-group BuildAgents to read instances in tenancy"]'
                ),
            }
        ],
    )


def test_minimum_cis_export_loads_and_derives_policy_principals(tmp_path: Path) -> None:
    _write_minimum_compliance_export(tmp_path)
    repo = PolicyAnalysisRepository()

    assert repo.load_from_compliance_output_dir(str(tmp_path)) is True
    assert repo.loaded_from_compliance_output is True
    assert repo.groups == []
    assert repo.dynamic_groups == []
    assert repo.users == []
    assert repo.compliance_capabilities == {
        'policy_statements': True,
        'policy_objects': True,
        'compartments': True,
        'compartment_hierarchy': True,
        'group_subject_names': True,
        'dynamic_group_subject_names': True,
        'groups_inventory': False,
        'dynamic_groups_inventory': False,
        'users_inventory': False,
        'group_memberships': False,
        'domains_inventory': False,
        'defined_tag_catalog': False,
        'principal_resolution': False,
    }

    principals = [principal for statement in repo.regular_statements for principal in statement['principals']]
    assert all(
        principals[0][key] == value
        for key, value in {'principal_type': 'group', 'domain_name': 'Engineering', 'name': 'PlatformOps'}.items()
    )
    assert all(
        principals[1][key] == value
        for key, value in {'principal_type': 'dynamic-group', 'domain_name': 'Default', 'name': 'BuildAgents'}.items()
    )

    engine = ConsolidationEngine(
        cache_mgr=SimpleNamespace(),
        reference_data_repo=SimpleNamespace(),
        policy_repo=repo,
    )
    assert engine.get_strategy_display_names() == [
        'Group Similar Statements',
        'Statement Density (Pack Policies)',
        'Move to Root Compartment',
        'Move Down Next Level',
        'Move Closer to Target Compartment',
        'Move Into Target Compartment',
    ]
    plan = engine.generate_plan(
        candidate_internal_ids={repo.regular_statements[0]['internal_id']},
        protected_internal_ids=set(),
        strategy_display_name='Move to Root Compartment',
    )
    assert plan['plan_steps']


def test_cis_policy_statements_use_the_policy_ocid_when_export_identifier_differs(tmp_path: Path) -> None:
    _write_minimum_compliance_export(tmp_path, policy_identifier='cis-export-identifier')
    repo = PolicyAnalysisRepository()

    assert repo.load_from_compliance_output_dir(str(tmp_path)) is True
    policy_ocid = repo.policies[0]['policy_ocid']
    assert policy_ocid == 'ocid1.policy.oc1..partialtest'
    assert {statement['policy_ocid'] for statement in repo.regular_statements} == {policy_ocid}

    inventory = ReportsService(SimpleNamespace(policy_repo=repo)).get_policy_inventory_report()
    policy_inventory = next(
        policy
        for compartment in inventory['findings']
        for policy in compartment['policies']
        if policy['ocid'] == policy_ocid
    )
    assert policy_inventory['statements'] == [
        'allow dynamic-group BuildAgents to read instances in tenancy',
        "allow group 'Engineering'/'PlatformOps' to manage buckets in compartment Apps",
    ]

    policy_risk_rows = RecommendationsService(
        SimpleNamespace(policy_repo=repo, intelligence=SimpleNamespace(overlay={'risk_scores': []}))
    )._policy_risk_rows()
    assert len(policy_risk_rows) == 1
    assert policy_risk_rows[0]['Policy Path'].endswith('/Partial Test Policy')

    class _RiskTable:
        rows: list[dict] = []

        def update_data(self, rows: list[dict]) -> None:
            self.rows = rows

    risk_table = _RiskTable()
    policy_risk_tab = SimpleNamespace(
        policy_repo=repo,
        app=SimpleNamespace(policy_intelligence=SimpleNamespace(overlay={'risk_scores': []})),
        policy_risk_threshold_var=SimpleNamespace(get=lambda: 'Show all'),
        policy_risk_table=risk_table,
        _get_policy_path=lambda *, policy_obj: f"{policy_obj['compartment_path']}/{policy_obj['policy_name']}",
    )
    PolicyRecommendationsTab.update_policy_risk_tab_output(policy_risk_tab)
    assert len(risk_table.rows) == 1
    assert risk_table.rows[0]['Policy Path'].endswith('/Partial Test Policy')


def test_consolidation_strategy_availability_uses_compliance_capabilities() -> None:
    class _IdentityDependentStrategy:
        strategy_id = 'identity_dependent'
        display_name = 'Identity-dependent consolidation'
        required_capabilities = frozenset({'principal_resolution'})

        def build_plan(self, **_kwargs):  # pragma: no cover - gate must reject before this is called
            raise AssertionError('unsupported strategy should not build a plan')

    repo = SimpleNamespace(
        loaded_from_compliance_output=True,
        compliance_capabilities={
            'policy_statements': True,
            'policy_objects': True,
            'compartment_hierarchy': True,
            'principal_resolution': False,
        },
        tenancy_ocid='ocid1.tenancy.oc1..partialtest',
        data_as_of='2026-09-03T00:00:00+00:00',
    )
    engine = ConsolidationEngine(
        cache_mgr=SimpleNamespace(),
        reference_data_repo=SimpleNamespace(),
        policy_repo=repo,
        strategies=[_IdentityDependentStrategy()],
    )

    assert engine.get_strategy_display_names() == []
    with pytest.raises(ValueError, match='missing principal_resolution'):
        engine.generate_plan(
            candidate_internal_ids=set(),
            protected_internal_ids=set(),
            strategy_display_name='Identity-dependent consolidation',
        )


def test_partial_cis_skips_membership_dependent_recommendation_checks(tmp_path: Path) -> None:
    _write_minimum_compliance_export(tmp_path)
    repo = PolicyAnalysisRepository()
    assert repo.load_from_compliance_output_dir(str(tmp_path)) is True

    intelligence = PolicyIntelligenceEngine(repo, strategies=[UnusedGroupsCheck()])
    intelligence.run_all()

    assert 'unused_groups' not in intelligence.overlay.get('cleanup_items', {})
    assert all(statement.get('valid') for statement in repo.regular_statements)


def test_partial_cis_builds_effective_permissions_from_policy_subject_names(tmp_path: Path) -> None:
    _write_minimum_compliance_export(tmp_path)
    repo = PolicyAnalysisRepository()
    assert repo.load_from_compliance_output_dir(str(tmp_path)) is True

    intelligence = PolicyIntelligenceEngine(repo)
    intelligence.build_permissions_report()
    report = ReportsService(SimpleNamespace(policy_repo=repo, intelligence=intelligence)).get_permissions_report()

    grant_rows = report['findings'][0]['grant_rows']
    assert grant_rows
    assert {row['principal_kind'] for row in grant_rows} == {'group', 'dynamic-group'}
    assert any('Engineering/PlatformOps' in row['principal_key'] for row in grant_rows)
    assert report['item_count'] == len(grant_rows)


def test_move_closer_uses_parent_of_deep_common_effective_scope() -> None:
    hierarchy = ['ROOT', 'ROOT/A', 'ROOT/A/B', 'ROOT/A/B/C', 'ROOT/A/B/C/D', 'ROOT/A/B/C/D/E']
    compartment_ids = ['tenancy', 'a', 'b', 'c', 'd', 'e']
    statements = [
        {
            'internal_id': f'statement-{number}',
            'policy_ocid': 'root-policy',
            'compartment_ocid': 'tenancy',
            'compartment_path': 'ROOT',
            'effective_path': 'ROOT/A/B/C/D/E',
            'location': 'A:B:C:D:E',
            'statement_text': (
                'allow group Developers to read buckets in compartment A:B:C:D:E '
                f"where target.bucket.name = '{number}'"
            ),
        }
        for number in range(13)
    ]
    repo = SimpleNamespace(
        tenancy_ocid='tenancy',
        compartments=[
            {'id': identifier, 'compartment_ocid': identifier, 'name': path.rsplit('/', 1)[-1], 'hierarchy_path': path}
            for identifier, path in zip(compartment_ids, hierarchy, strict=True)
        ],
        policies=[
            {
                'policy_ocid': 'root-policy',
                'policy_name': 'Root Policy',
                'compartment_ocid': 'tenancy',
                'compartment_path': 'ROOT',
                'freeform_tags': {},
                'defined_tags': {},
            }
        ],
        regular_statements=statements,
    )

    plan = MoveCloserToTargetCompartment().build_plan(
        repo=repo,
        tenancy_ocid='tenancy',
        dataset_version=None,
        candidate_internal_ids={statement['internal_id'] for statement in statements},
        protected_internal_ids=set(),
        plan_id='deep-common-scope',
    )

    add_step = next(step for step in plan['plan_steps'] if step['action'] == 'add')
    assert add_step['compartment_ocid'] == 'd'
    assert all('in compartment E ' in statement for statement in add_step['after_statements'])


def test_move_down_next_level_moves_only_one_level_and_skips_tenancy_scope() -> None:
    hierarchy = ['ROOT', 'ROOT/A', 'ROOT/A/B', 'ROOT/A/B/C', 'ROOT/A/B/C/D', 'ROOT/A/B/C/D/E']
    compartment_ids = ['tenancy', 'a', 'b', 'c', 'd', 'e']
    movable = {
        'internal_id': 'movable',
        'policy_ocid': 'root-policy',
        'compartment_ocid': 'tenancy',
        'compartment_path': 'ROOT',
        'effective_path': 'ROOT/A/B/C/D/E',
        'location': 'A:B:C:D',
        'statement_text': 'allow group Developers to read buckets in compartment A:B:C:D',
    }
    tenancy_scoped = {
        'internal_id': 'tenancy-scoped',
        'policy_ocid': 'root-policy',
        'compartment_ocid': 'tenancy',
        'compartment_path': 'ROOT',
        'effective_path': 'ROOT',
        'location': 'ROOT',
        'statement_text': 'allow group Developers to inspect tenancies in tenancy',
    }
    already_at_effective_path = {
        'internal_id': 'already-at-effective-path',
        'policy_ocid': 'already-policy',
        'compartment_ocid': 'b',
        'compartment_path': 'ROOT/A/B',
        'effective_path': 'ROOT/A/B',
        'location': 'A:B',
        'statement_text': 'allow group Developers to read buckets in compartment A:B',
    }
    repo = SimpleNamespace(
        tenancy_ocid='tenancy',
        compartments=[
            {'id': identifier, 'compartment_ocid': identifier, 'name': path.rsplit('/', 1)[-1], 'hierarchy_path': path}
            for identifier, path in zip(compartment_ids, hierarchy, strict=True)
        ],
        policies=[
            {
                'policy_ocid': 'root-policy',
                'policy_name': 'Root Policy',
                'compartment_ocid': 'tenancy',
                'compartment_path': 'ROOT',
                'freeform_tags': {},
                'defined_tags': {},
            },
            {
                'policy_ocid': 'already-policy',
                'policy_name': 'Already Scoped Policy',
                'compartment_ocid': 'b',
                'compartment_path': 'ROOT/A/B',
                'freeform_tags': {},
                'defined_tags': {},
            },
        ],
        regular_statements=[movable, tenancy_scoped, already_at_effective_path],
    )

    plan = MoveDownNextLevel().build_plan(
        repo=repo,
        tenancy_ocid='tenancy',
        dataset_version=None,
        candidate_internal_ids={'movable', 'tenancy-scoped', 'already-at-effective-path'},
        protected_internal_ids=set(),
        plan_id='one-level',
    )

    add_step = next(step for step in plan['plan_steps'] if step['action'] == 'add')
    assert add_step['compartment_ocid'] == 'a'
    assert add_step['after_statements'] == ['allow group Developers to read buckets in compartment B:C:D:E']
    assert {item['internal_id'] for item in plan['skipped_statements']} == {
        'tenancy-scoped',
        'already-at-effective-path',
    }
    assert any('location already matches' in item['reason'] for item in plan['skipped_statements'])

    repo.compartments = [repo.compartments[0]]
    missing_child_plan = MoveDownNextLevel().build_plan(
        repo=repo,
        tenancy_ocid='tenancy',
        dataset_version=None,
        candidate_internal_ids={'movable'},
        protected_internal_ids=set(),
        plan_id='missing-child',
    )
    assert missing_child_plan['plan_steps'] == []
    assert 'No next-level compartment exists' in missing_child_plan['skipped_statements'][0]['reason']


def test_move_down_next_level_evaluates_sibling_targets_independently() -> None:
    repo = SimpleNamespace(
        tenancy_ocid='tenancy',
        compartments=[
            {'id': 'tenancy', 'hierarchy_path': 'ROOT'},
            {'id': 'apps', 'hierarchy_path': 'ROOT/Apps'},
            {'id': 'finance', 'hierarchy_path': 'ROOT/Finance'},
        ],
        policies=[{'policy_ocid': 'root-policy', 'policy_name': 'Root Policy', 'compartment_ocid': 'tenancy'}],
        regular_statements=[
            {
                'internal_id': 'apps-statement',
                'policy_ocid': 'root-policy',
                'compartment_path': 'ROOT',
                'effective_path': 'ROOT/Apps',
                'location': 'in tenancy',
                'statement_text': 'allow group Developers to read buckets in compartment Apps',
            },
            {
                'internal_id': 'finance-statement',
                'policy_ocid': 'root-policy',
                'compartment_path': 'ROOT',
                'effective_path': 'ROOT/Finance',
                'location': 'in tenancy',
                'statement_text': 'allow group Finance to read buckets in compartment Finance',
            },
        ],
    )

    plan = MoveDownNextLevel().build_plan(
        repo=repo,
        tenancy_ocid='tenancy',
        dataset_version=None,
        candidate_internal_ids={'apps-statement', 'finance-statement'},
        protected_internal_ids=set(),
        plan_id='independent-targets',
    )

    assert {step['compartment_ocid'] for step in plan['plan_steps'] if step['action'] == 'add'} == {'apps', 'finance'}
    assert not plan.get('skipped_statements')


def test_move_down_next_level_moves_root_statements_toward_a_nested_effective_path() -> None:
    statements = [
        {
            'internal_id': f'root-statement-{index}',
            'policy_ocid': 'root-policy',
            'compartment_path': 'ROOT',
            'effective_path': 'ROOT/A/B',
            'location': 'A:B',
            'statement_text': f'allow group Team{index} to read buckets in compartment A:B',
        }
        for index in (1, 2)
    ]
    repo = SimpleNamespace(
        tenancy_ocid='tenancy',
        compartments=[
            {'id': 'tenancy', 'hierarchy_path': 'ROOT'},
            {'id': 'a', 'hierarchy_path': 'ROOT/A'},
            {'id': 'b', 'hierarchy_path': 'ROOT/A/B'},
        ],
        policies=[{'policy_ocid': 'root-policy', 'policy_name': 'Root Policy', 'compartment_ocid': 'tenancy'}],
        regular_statements=statements,
    )

    plan = MoveDownNextLevel().build_plan(
        repo=repo,
        tenancy_ocid='tenancy',
        dataset_version=None,
        candidate_internal_ids={statement['internal_id'] for statement in statements},
        protected_internal_ids=set(),
        plan_id='root-to-a',
    )

    add_step = next(step for step in plan['plan_steps'] if step['action'] == 'add')
    assert add_step['compartment_ocid'] == 'a'
    assert add_step['after_statements'] == [
        'allow group Team1 to read buckets in compartment B',
        'allow group Team2 to read buckets in compartment B',
    ]
    assert not plan.get('skipped_statements')


def test_policy_placement_findings_are_selectable_consolidation_rows() -> None:
    tab = SimpleNamespace(
        app=SimpleNamespace(
            policy_intelligence=SimpleNamespace(
                overlay={
                    'consolidations': [],
                    'recommendations': [
                        {
                            'Category': 'Policy Placement',
                            'Evidence': [
                                {
                                    'Statement Internal ID': 'statement-1',
                                    'Policy': 'Root Policy',
                                    'Policy OCID': 'root-policy-ocid',
                                    'Policy Compartment Path': 'ROOT',
                                    'Effective Path': 'ROOT/Apps/Dev',
                                    'Levels Below Policy': 2,
                                    'Statement': 'allow group Developers to manage buckets in compartment Dev',
                                }
                            ],
                        }
                    ],
                }
            )
        )
    )

    rows = PolicyRecommendationsTab._get_policy_consolidation_rows(tab)

    assert len(rows) == 1
    assert rows[0]['Statement Internal IDs'] == ['statement-1']
    assert rows[0]['Handoff Mode'] == 'supported'
    assert rows[0]['Summary'].startswith('Move 1 statement(s) from ROOT')


def test_policy_placement_rows_coalesce_only_same_policy_and_effective_path() -> None:
    evidence = [
        {
            'Statement Internal ID': 'statement-1',
            'Policy': 'Root Policy',
            'Policy OCID': 'root-policy-ocid',
            'Policy Compartment Path': 'ROOT',
            'Effective Path': 'ROOT/Apps/Dev',
            'Statement': 'allow group Developers to manage buckets in compartment Dev',
        },
        {
            'Statement Internal ID': 'statement-2',
            'Policy': 'Root Policy',
            'Policy OCID': 'root-policy-ocid',
            'Policy Compartment Path': 'ROOT',
            'Effective Path': 'ROOT/Apps/Dev',
            'Statement': 'allow group Developers to manage objects in compartment Dev',
        },
        {
            'Statement Internal ID': 'statement-3',
            'Policy': 'Root Policy',
            'Policy OCID': 'root-policy-ocid',
            'Policy Compartment Path': 'ROOT',
            'Effective Path': 'ROOT/Apps/Test',
            'Statement': 'allow group Developers to manage buckets in compartment Test',
        },
    ]
    tab = SimpleNamespace(
        app=SimpleNamespace(
            policy_intelligence=SimpleNamespace(
                overlay={
                    'consolidations': [],
                    'recommendations': [{'Category': 'Policy Placement', 'Evidence': evidence}],
                }
            )
        )
    )

    rows = PolicyRecommendationsTab._get_policy_consolidation_rows(tab)

    assert sorted(row['Statements'] for row in rows) == [1, 2]


def test_workbench_handoff_replaces_candidate_selection_with_available_statement_ids() -> None:
    loads: list[bool] = []
    idle_callbacks: list[object] = []
    notebook = _Notebook([])
    tab = SimpleNamespace(
        service=SimpleNamespace(
            get_candidate_rows=lambda: {'rows': [{'internal_id': 'statement-1'}, {'internal_id': 'statement-2'}]}
        ),
        candidate_table_selected_ids={'old-selection'},
        candidate_search_var=_Variable(),
        _load_candidate_statements=lambda: loads.append(True),
        _update_selected_candidates_table=lambda: None,
        after_idle=lambda callback: idle_callbacks.append(callback),
        notebook=notebook,
        logger=SimpleNamespace(info=lambda *_args, **_kwargs: None),
    )
    tab._refresh_candidate_selection_after_handoff = (  # type: ignore[attr-defined]
        lambda: ConsolidationWorkbenchTab._refresh_candidate_selection_after_handoff(tab)
    )

    accepted = ConsolidationWorkbenchTab.select_candidate_statements(tab, {'statement-1', 'protected-statement'})

    assert accepted == {'statement-1'}
    assert tab.candidate_table_selected_ids == {'statement-1'}
    assert tab.candidate_search_var.value == ''
    assert loads == []
    assert notebook.selected == 1

    idle_callbacks.pop()()
    assert loads == [True]


def test_workbench_handoff_refresh_waits_for_outer_tab_mapping() -> None:
    refresh_callbacks: list[object] = []
    loads: list[bool] = []
    mapped = iter([False, True])
    tab = SimpleNamespace(
        winfo_ismapped=lambda: next(mapped),
        _handoff_refresh_attempts=0,
        after=lambda _delay, callback: refresh_callbacks.append(callback),
        _load_candidate_statements=lambda: loads.append(True),
        _update_selected_candidates_table=lambda: loads.append(True),
    )
    tab._refresh_candidate_selection_after_handoff = (  # type: ignore[attr-defined]
        lambda: ConsolidationWorkbenchTab._refresh_candidate_selection_after_handoff(tab)
    )

    ConsolidationWorkbenchTab._refresh_candidate_selection_after_handoff(tab)

    assert loads == []
    refresh_callbacks.pop()()
    assert loads == [True, True]


def test_workload_tab_uses_policy_derived_dynamic_group_names_without_inventory() -> None:
    tab = SimpleNamespace(
        policy_repo=SimpleNamespace(
            compliance_capabilities={'dynamic_groups_inventory': False},
            regular_statements=[
                {
                    'principals': [
                        {
                            'principal_type': 'dynamic-group',
                            'domain_name': 'Engineering',
                            'name': 'BuildAgents',
                        },
                        {
                            'principal_type': 'dynamic-group',
                            'domain_name': 'Engineering',
                            'name': 'BuildAgents',
                        },
                    ]
                }
            ],
        )
    )

    derived = WorkloadPrincipalsTab._policy_derived_dynamic_groups(tab)

    assert len(derived) == 1
    assert all(
        derived[0][key] == value
        for key, value in {
            'domain_name': 'Engineering',
            'dynamic_group_name': 'BuildAgents',
            'description': 'Policy-derived name; dynamic group inventory was not supplied.',
            'in_use': True,
        }.items()
    )


class _Notebook:
    def __init__(self, tabs: list[str]) -> None:
        self._tabs = tuple(tabs)
        self.states: dict[str, str] = {}
        self.selected = None

    def tabs(self) -> tuple[str, ...]:
        return self._tabs

    def tab(self, tab: str, *, state: str) -> None:
        self.states[tab] = state

    def select(self, target) -> None:
        self.selected = target


class _Variable:
    def __init__(self) -> None:
        self.value = ''

    def set(self, value: str) -> None:
        self.value = value


class _Banner:
    def __init__(self) -> None:
        self.mapped = False

    def winfo_ismapped(self) -> bool:
        return self.mapped

    def pack(self, **_kwargs) -> None:
        self.mapped = True

    def pack_forget(self) -> None:
        self.mapped = False


def test_partial_cis_ui_banner_disables_only_visible_unsupported_tabs() -> None:
    users, dynamic_groups, permissions, historical = 'users', 'dynamic-groups', 'permissions', 'historical'
    app = SimpleNamespace(
        policy_compartment_analysis=SimpleNamespace(
            loaded_from_compliance_output=True,
            compliance_capabilities={'principal_resolution': False},
            compartments=[{}, {}],
            policies=[{}],
            regular_statements=[{}, {}],
        ),
        notebook=_Notebook([users, dynamic_groups, permissions, historical]),
        users_tab=users,
        dynamic_groups_tab=dynamic_groups,
        permissions_report_tab=permissions,
        simulation_tab='simulation-hidden',
        tag_based_access_tab='tag-hidden',
        historical_tab=historical,
        compliance_capability_banner_var=_Variable(),
        compliance_capability_banner=_Banner(),
    )

    App._update_compliance_capability_ui(app)

    assert app.notebook.states == {
        users: 'disabled',
        dynamic_groups: 'disabled',
        permissions: 'disabled',
        historical: 'disabled',
    }
    assert app.compliance_capability_banner.mapped is True
    assert 'Partial CIS Compliance dataset' in app.compliance_capability_banner_var.value
    assert (
        'Policy hierarchy, statement moves, consolidation, recommendations'
        in app.compliance_capability_banner_var.value
    )
