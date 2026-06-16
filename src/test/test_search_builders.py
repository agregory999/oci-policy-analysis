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
