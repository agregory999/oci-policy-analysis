from oci_policy_analysis.application.core.engine.policy_simulation_engine import PolicySimulationEngine
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.search_builders import build_policy_search_from_filters


def test_repo_filter_policy_statements_principal_key_is_exact_for_service() -> None:
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'svc-policy',
            'policy_ocid': 'ocid1.policy.oc1..svc',
            'compartment_ocid': 'ocid1.compartment.oc1..finance',
            'compartment_path': 'ROOT/Finance',
            'statement_text': 'allow service database to read buckets in tenancy',
            'creation_time': '',
            'internal_id': 'stmt-svc',
            'parsed': True,
            'subject_type': 'service',
            'subject': 'database',
            'principal_keys': ['service:None/database'],
            'effective_path': 'ROOT/Finance',
            'valid': True,
        },
        {
            'policy_name': 'group-policy',
            'policy_ocid': 'ocid1.policy.oc1..group',
            'compartment_ocid': 'ocid1.compartment.oc1..finance',
            'compartment_path': 'ROOT/Finance',
            'statement_text': 'allow group DatabaseAdmins to read buckets in tenancy',
            'creation_time': '',
            'internal_id': 'stmt-group',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'DatabaseAdmins')],
            'principal_keys': ['group:Default/DatabaseAdmins'],
            'effective_path': 'ROOT/Finance',
            'valid': True,
        },
    ]

    rows = repo.filter_policy_statements(
        {
            'principal_key': ['service:None/database'],
            'effective_path': ['ROOT/Finance'],
        }
    )

    assert [r.get('policy_name') for r in rows] == ['svc-policy']


def test_simulation_engine_principal_key_filter_mapping_uses_principal_key() -> None:
    engine = PolicySimulationEngine(policy_repo=None, ref_data_repo=None)
    mapped = engine._principal_key_to_policy_search_filter('service:None/database')
    assert mapped == {'principal_key': ['service:None/database']}


def test_repo_filter_policy_statements_effective_path_supports_multi_value_or() -> None:
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'root-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..root',
            'compartment_ocid': 'ocid1.compartment.oc1..root',
            'compartment_path': 'ROOT',
            'statement_text': 'allow group A to inspect all-resources in tenancy',
            'creation_time': '',
            'internal_id': 'stmt-root',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT',
            'valid': True,
        },
        {
            'policy_name': 'network-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..net',
            'compartment_ocid': 'ocid1.compartment.oc1..lz1',
            'compartment_path': 'ROOT/LZ1-Top',
            'statement_text': 'allow group A to use vnics in compartment network-cmp',
            'creation_time': '',
            'internal_id': 'stmt-network',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT/LZ1-Top/network-cmp',
            'valid': True,
        },
        {
            'policy_name': 'other-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..other',
            'compartment_ocid': 'ocid1.compartment.oc1..other',
            'compartment_path': 'ROOT/Other',
            'statement_text': 'allow group A to manage buckets in compartment other-cmp',
            'creation_time': '',
            'internal_id': 'stmt-other',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT/Other/other-cmp',
            'valid': True,
        },
    ]

    rows = repo.filter_policy_statements(
        {
            'effective_path': ['ROOT/LZ1-Top/application-cmp', 'ROOT/LZ1-Top/network-cmp'],
        }
    )

    assert sorted([str(r.get('internal_id')) for r in rows]) == ['stmt-network', 'stmt-root']


def test_pipe_delimited_effective_path_filters_split_and_apply_or() -> None:
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'root-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..root',
            'compartment_ocid': 'ocid1.compartment.oc1..root',
            'compartment_path': 'ROOT',
            'statement_text': 'allow group A to inspect all-resources in tenancy',
            'creation_time': '',
            'internal_id': 'stmt-root',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT',
            'valid': True,
        },
        {
            'policy_name': 'network-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..net',
            'compartment_ocid': 'ocid1.compartment.oc1..lz1',
            'compartment_path': 'ROOT/LZ1-Top',
            'statement_text': 'allow group A to use vnics in compartment network-cmp',
            'creation_time': '',
            'internal_id': 'stmt-network',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT/LZ1-Top/network-cmp',
            'valid': True,
        },
        {
            'policy_name': 'other-policy',
            'action': 'allow',
            'policy_ocid': 'ocid1.policy.oc1..other',
            'compartment_ocid': 'ocid1.compartment.oc1..other',
            'compartment_path': 'ROOT/Other',
            'statement_text': 'allow group A to manage buckets in compartment other-cmp',
            'creation_time': '',
            'internal_id': 'stmt-other',
            'parsed': True,
            'subject_type': 'group',
            'subject': [('Default', 'A')],
            'principal_keys': ['group:Default/A'],
            'effective_path': 'ROOT/Other/other-cmp',
            'valid': True,
        },
    ]

    filters = build_policy_search_from_filters(effective_path='ROOT/LZ1-Top/application-cmp|ROOT/LZ1-Top/network-cmp')
    rows = repo.filter_policy_statements(filters)

    assert filters.get('effective_path') == ['ROOT/LZ1-Top/application-cmp', 'ROOT/LZ1-Top/network-cmp']
    assert sorted([str(r.get('internal_id')) for r in rows]) == ['stmt-network', 'stmt-root']


def test_get_applicable_statements_matches_dynamic_group_tuple_subject_by_principal_key() -> None:
    repo = PolicyAnalysisRepository()
    repo.regular_statements = []
    engine = PolicySimulationEngine(policy_repo=repo, ref_data_repo=None)
    engine._prospective_statements = [
        {
            'internal_id': 'prospective-1',
            'policy_name': 'Prospective DG',
            'statement_text': "allow dynamic-group 'Federated'/'container-instances' to read repos in compartment ROOT/Apps",
            'subject_type': 'dynamic-group',
            'subject': [('Federated', 'container-instances')],
            'effective_path': 'ROOT/Apps',
            'parsed': True,
            'valid': True,
            'is_prospective': True,
        }
    ]

    rows = engine.get_applicable_statements('dynamic-group:Federated/container-instances', 'ROOT/Apps')

    assert len(rows) == 1
    assert rows[0].get('internal_id') == 'prospective-1'
