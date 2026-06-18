"""Tests for principal-aware policy search matching."""

import pytest
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.common.models import PolicySearch


def _statement(policy_name: str, principal_type: str, principal_key: str, **principal_fields: str) -> dict:
    return {
        'policy_name': policy_name,
        'statement_text': f'allow {principal_type} to manage all-resources in tenancy',
        'subject_type': principal_type,
        'subject': [(principal_fields.get('domain_name'), principal_fields.get('name'))]
        if principal_fields.get('name')
        else [principal_fields.get('ocid', principal_key)],
        'principals': [
            {
                'principal_type': principal_type,
                'principal_key': principal_key,
                **principal_fields,
            }
        ],
        'principal_keys': [principal_key],
        'verb': 'manage',
        'resource': 'all-resources',
        'location': 'tenancy',
        'valid': True,
    }


def _repo_with_principals() -> PolicyAnalysisRepository:
    repo = PolicyAnalysisRepository()
    repo.groups = [
        {
            'domain_name': 'Default',
            'group_name': 'Admins',
            'group_ocid': 'ocid1.group.oc1..admins',
        },
        {
            'domain_name': 'DomainA',
            'group_name': 'Operators',
            'group_ocid': 'ocid1.group.oc1..operators',
        },
    ]
    repo.dynamic_groups = [
        {
            'domain_name': 'Default',
            'dynamic_group_name': 'Builders',
            'dynamic_group_ocid': 'ocid1.dynamicgroup.oc1..builders',
        }
    ]
    repo.users = [
        {
            'domain_name': 'Default',
            'user_name': 'Alice',
            'user_ocid': 'ocid1.user.oc1..alice',
            'groups': ['ocid1.group.oc1..admins'],
        }
    ]
    repo.regular_statements = [
        _statement(
            'group-name-policy',
            'group',
            'group:Default/Admins',
            domain_name='Default',
            name='Admins',
            display_name='Default/Admins',
        ),
        _statement(
            'group-id-policy',
            'group-id',
            'group-id:ocid1.group.oc1..admins',
            ocid='ocid1.group.oc1..admins',
            display_name='ocid1.group.oc1..admins',
        ),
        _statement(
            'operators-policy',
            'group',
            'group:DomainA/Operators',
            domain_name='DomainA',
            name='Operators',
            display_name='DomainA/Operators',
        ),
        _statement(
            'dynamic-group-name-policy',
            'dynamic-group',
            'dynamic-group:Default/Builders',
            domain_name='Default',
            name='Builders',
            display_name='Default/Builders',
        ),
        _statement(
            'dynamic-group-id-policy',
            'dynamic-group-id',
            'dynamic-group-id:ocid1.dynamicgroup.oc1..builders',
            ocid='ocid1.dynamicgroup.oc1..builders',
            display_name='ocid1.dynamicgroup.oc1..builders',
        ),
    ]
    return repo


def _policy_names(repo: PolicyAnalysisRepository, filters: PolicySearch) -> list[str]:
    return [statement['policy_name'] for statement in repo.filter_policy_statements(filters)]


@pytest.mark.parametrize(
    ('filters', 'expected_names'),
    [
        (
            {'principal_keys': ['group:Default/Admins']},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principal_keys': ['group-id:ocid1.group.oc1..admins']},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'group', 'domain_name': 'Default', 'name': 'Admins'}]},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'group-id', 'ocid': 'ocid1.group.oc1..admins'}]},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principal_keys': ['dynamic-group:Default/Builders']},
            ['dynamic-group-name-policy', 'dynamic-group-id-policy'],
        ),
        (
            {'principal_keys': ['dynamic-group-id:ocid1.dynamicgroup.oc1..builders']},
            ['dynamic-group-name-policy', 'dynamic-group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'dynamic-group', 'domain_name': 'Default', 'name': 'Builders'}]},
            ['dynamic-group-name-policy', 'dynamic-group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'dynamic-group-id', 'ocid': 'ocid1.dynamicgroup.oc1..builders'}]},
            ['dynamic-group-name-policy', 'dynamic-group-id-policy'],
        ),
        (
            {'principal_keys': ['user:Default/Alice']},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principal_keys': ['user-id:ocid1.user.oc1..alice']},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'user', 'domain_name': 'Default', 'name': 'Alice'}]},
            ['group-name-policy', 'group-id-policy'],
        ),
        (
            {'principals': [{'principal_type': 'user-id', 'ocid': 'ocid1.user.oc1..alice'}]},
            ['group-name-policy', 'group-id-policy'],
        ),
    ],
)
def test_policy_search_matches_principal_name_and_id_equivalents(
    filters: PolicySearch,
    expected_names: list[str],
) -> None:
    """Verify principal searches include both name-based and ID-based statements."""
    repo = _repo_with_principals()

    assert _policy_names(repo, filters) == expected_names


def test_policy_search_principal_equivalence_does_not_match_unrelated_principals() -> None:
    """Verify principal equivalence does not broaden matches to unrelated identities."""
    repo = _repo_with_principals()

    assert _policy_names(repo, {'principal_keys': ['group:DomainA/Operators']}) == ['operators-policy']
    assert _policy_names(repo, {'principal_keys': ['group:Default/Missing']}) == []


def test_policy_search_matches_singular_resource_principal_by_condition_evidence() -> None:
    """Verify resource-principal filters match any-user statements through request.principal evidence."""
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'container-policy',
            'statement_text': 'allow any-user to read repos in tenancy',
            'subject_type': 'any-user',
            'subject': ['any-user'],
            'principals': [
                {
                    'principal_type': 'any-user',
                    'principal_key': 'any-user:None/any-user',
                    'display_name': 'any-user',
                }
            ],
            'principal_keys': ['any-user:None/any-user'],
            'conditions': (
                "all { request.principal.type = 'computecontainerinstance', " "request.operation = 'PullImage' }"
            ),
        },
        {
            'policy_name': 'database-policy',
            'statement_text': 'allow any-user to read buckets in tenancy',
            'subject_type': 'any-user',
            'subject': ['any-user'],
            'principal_keys': ['any-user:None/any-user'],
            'conditions': "all { request.principal.type = 'autonomousdatabase' }",
        },
        _statement(
            'group-policy',
            'group',
            'group:Default/Admins',
            domain_name='Default',
            name='Admins',
        ),
    ]

    results = repo.filter_policy_statements(
        {
            'principal': {
                'principal_type': 'resource-principal',
                'resource_type': 'computecontainerinstance',
            }
        }
    )

    assert [statement['policy_name'] for statement in results] == ['container-policy']
    assert results[0]['match_confidence'] == 'identity_match_with_residual'
    assert results[0]['confidence'] == 'identity_match_with_residual'
    assert [atom['left'] for atom in results[0]['principal_evidence']] == ['request.principal.type']
    assert [atom['left'] for atom in results[0]['residual_conditions']] == ['request.operation']
    assert 'residual' in results[0]['match_confidence_reason']


def test_policy_search_matches_resource_principal_by_compartment_ocid() -> None:
    """Verify resource-principal compartment filters use request.principal.compartment.id."""
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'container-compartment-policy',
            'statement_text': 'allow any-group to use objects in tenancy',
            'subject_type': 'any-group',
            'subject': ['any-group'],
            'principal_keys': ['any-group:None/any-group'],
            'conditions': (
                "all { request.principal.type = 'computecontainerinstance', "
                "request.principal.compartment.id = 'ocid1.compartment.oc1..app' }"
            ),
        }
    ]

    results = repo.filter_policy_statements(
        {
            'principal': {
                'principal_type': 'resource-principal',
                'resource_type': 'computecontainerinstance',
                'compartment_ocid': 'ocid1.compartment.oc1..app',
            }
        }
    )

    assert [statement['policy_name'] for statement in results] == ['container-compartment-policy']
    assert results[0]['match_confidence'] == 'exact'
    assert [atom['left'] for atom in results[0]['principal_evidence']] == [
        'request.principal.type',
        'request.principal.compartment.id',
    ]
    assert results[0]['residual_conditions'] == []


def test_policy_search_matches_oke_workload_identity_by_namespace_service_account_and_cluster() -> None:
    """Verify OKE workload identity filters match workload evidence and preserve residual conditions."""
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'oke-workload-policy',
            'statement_text': 'allow any-user to use buckets in tenancy',
            'subject_type': 'any-user',
            'subject': ['any-user'],
            'principal_keys': ['any-user:None/any-user'],
            'conditions': (
                "all { request.principal.type = 'workload', "
                "request.principal.namespace = 'finance', "
                "request.principal.service_account = 'financesa', "
                "request.principal.cluster_id = 'ocid1.cluster.oc1..oke1', "
                "request.operation = 'GetObject' }"
            ),
        }
    ]

    results = repo.filter_policy_statements(
        {
            'principal': {
                'principal_type': 'oke-workload-identity',
                'workload_namespace': 'finance',
                'workload_service_account': 'financesa',
                'workload_cluster_id': 'ocid1.cluster.oc1..oke1',
            }
        }
    )

    assert [statement['policy_name'] for statement in results] == ['oke-workload-policy']
    assert results[0]['match_confidence'] == 'identity_match_with_residual'
    assert [atom['left'] for atom in results[0]['principal_evidence']] == [
        'request.principal.type',
        'request.principal.namespace',
        'request.principal.service_account',
        'request.principal.cluster_id',
    ]
    assert [atom['left'] for atom in results[0]['residual_conditions']] == ['request.operation']


def test_policy_search_rejects_oke_workload_identity_when_namespace_does_not_match() -> None:
    """Verify OKE workload identity matching remains strict across namespace/service account values."""
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'oke-workload-policy',
            'statement_text': 'allow any-user to use buckets in tenancy',
            'subject_type': 'any-user',
            'subject': ['any-user'],
            'principal_keys': ['any-user:None/any-user'],
            'conditions': (
                "all { request.principal.type = 'workload', "
                "request.principal.namespace = 'finance', "
                "request.principal.service_account = 'financesa', "
                "request.principal.cluster_id = 'ocid1.cluster.oc1..oke1' }"
            ),
        }
    ]

    results = repo.filter_policy_statements(
        {
            'principal': {
                'principal_type': 'oke-workload-identity',
                'workload_namespace': 'finance',
                'workload_service_account': 'other-sa',
                'workload_cluster_id': 'ocid1.cluster.oc1..oke1',
            }
        }
    )

    assert results == []
