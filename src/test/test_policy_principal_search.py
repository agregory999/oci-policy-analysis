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
