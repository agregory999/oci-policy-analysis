from oci_policy_analysis.application.services.search_builders import build_policy_search_from_dict


def test_build_policy_search_from_dict_preserves_singular_principal_filter() -> None:
    principal = {
        'principal_type': 'resource-principal',
        'resource_type': 'computecontainerinstance',
    }

    filters = build_policy_search_from_dict({'principal': principal})

    assert filters['principal'] == principal


def test_build_policy_search_from_dict_preserves_structured_principal_lists_and_keys() -> None:
    principal = {
        'principal_type': 'group',
        'domain_name': 'Default',
        'name': 'Admins',
    }

    filters = build_policy_search_from_dict(
        {
            'principals': [principal],
            'principal_keys': ['group:Default/Admins'],
            'principal_key': 'group-id:ocid1.group.oc1..admins',
        }
    )

    assert filters['principals'] == [principal]
    assert filters['principal_keys'] == ['group:Default/Admins']
    assert filters['principal_key'] == ['group-id:ocid1.group.oc1..admins']


def test_exact_subject_type_union_preserves_fuzzy_search_compatibility():
    from copy import deepcopy

    from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository

    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {'internal_id': 'human', 'subject_type': 'group', 'action': 'allow'},
        {'internal_id': 'dynamic', 'subject_type': 'dynamic-group', 'action': 'allow'},
        {'internal_id': 'opaque', 'subject_type': 'group-id', 'action': 'deny', 'valid': False},
        {'internal_id': 'wildcard', 'subject_type': 'any-group', 'action': 'allow'},
        {'internal_id': 'missing', 'action': 'unknown'},
    ]
    original = deepcopy(repo.regular_statements)
    for raw in [['group', 'group-id'], 'group|group-id']:
        filters = build_policy_search_from_dict({'exact_subject_types': raw})
        assert {row['internal_id'] for row in repo.filter_policy_statements(filters)} == {'human', 'opaque'}
    filters = build_policy_search_from_dict({'exact_subject_types': 'GROUP'})
    assert [row['internal_id'] for row in repo.filter_policy_statements(filters)] == ['human']
    assert len(repo.filter_policy_statements({'subject_type': ['group']})) == 4
    assert len(repo.filter_policy_statements({'exact_subject_types': []})) == 5
    assert repo.regular_statements == original
