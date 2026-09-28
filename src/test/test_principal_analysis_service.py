from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.principal_analysis_service import PrincipalAnalysisService


def _build_service(statements: list[dict]) -> PrincipalAnalysisService:
    context = cast(Any, SimpleNamespace(policy_repo=SimpleNamespace(regular_statements=statements)))
    return PrincipalAnalysisService(context)


def test_get_resource_types_extracts_and_sorts_unique_values():
    svc = _build_service(
        [
            {'conditions': "all { request.principal.type = 'serviceconnector' }"},
            {'conditions': "all {request.principal.type='autonomousdatabase', request.operation='x'}"},
            {'conditions': 'all { request.principal.type = "FnFunc" }'},
            {'conditions': "all { request.principal.id = 'ocid1.x' }"},
            {'conditions': ''},
        ]
    )

    assert svc.get_resource_types() == ['Any', 'autonomousdatabase', 'fnfunc', 'serviceconnector']


def test_get_resource_types_dedupes_case_insensitive_matches():
    svc = _build_service(
        [
            {'conditions': "all { request.principal.type = 'dbmgmt' }"},
            {'conditions': "all { request.principal.type = 'DBMGMT' }"},
            {'conditions': "all { request.principal.type='dbmgmt' }"},
        ]
    )

    assert svc.get_resource_types() == ['Any', 'dbmgmt']


def test_by_subject_types_applies_resource_type_filter_via_conditions():
    svc = _build_service([])
    captured_filters = {}

    class _AnalysisStub:
        @staticmethod
        def filter_policy_statements(*, filters):
            captured_filters.update(filters)
            assert filters.get('subject_type') == ['any-user']
            return SimpleNamespace(statements=[{'policy_name': 'matched'}])

    svc.analysis = cast(Any, _AnalysisStub())
    result = svc.by_subject_types(subject_types=['any-user'], resource_type='serviceconnector')

    assert len(result.statements) == 1
    assert captured_filters['principal'] == {
        'principal_type': 'resource-principal',
        'resource_type': 'serviceconnector',
    }


def test_by_subject_types_applies_resource_compartment_ocid_filter_via_principal_selector():
    svc = _build_service([])
    captured_filters = {}

    class _AnalysisStub:
        @staticmethod
        def filter_policy_statements(*, filters):
            captured_filters.update(filters)
            assert filters.get('subject_type') == ['any-group']
            return SimpleNamespace(statements=[{'policy_name': 'matched'}])

    svc.analysis = cast(Any, _AnalysisStub())
    result = svc.by_subject_types(
        subject_types=['any-group'],
        resource_type='computecontainerinstance',
        resource_compartment_ocid='ocid1.compartment.oc1..app',
    )

    assert len(result.statements) == 1
    assert captured_filters['principal'] == {
        'principal_type': 'resource-principal',
        'resource_type': 'computecontainerinstance',
        'resource_compartment_ocid': 'ocid1.compartment.oc1..app',
    }


def test_by_exact_dynamic_groups_matches_legacy_named_and_ocid_subject_rows():
    """Dynamic Group UI selections must work with cache rows lacking principals."""
    repo = PolicyAnalysisRepository()
    repo.dynamic_groups = [
        {
            'domain_name': 'Default',
            'dynamic_group_name': 'Builders',
            'dynamic_group_ocid': 'ocid1.dynamicgroup.oc1..builders',
        }
    ]
    repo.regular_statements = [
        {
            'policy_name': 'named-dynamic-group',
            'statement_text': 'allow dynamic-group Builders to read buckets in tenancy',
            'subject_type': 'dynamic-group',
            'subject': [('Default', 'Builders')],
            'valid': True,
        },
        {
            'policy_name': 'ocid-dynamic-group',
            'statement_text': 'allow dynamic-group id ocid1.dynamicgroup.oc1..builders to read buckets in tenancy',
            'subject_type': 'dynamic-group-id',
            'subject': [(None, 'ocid1.dynamicgroup.oc1..builders')],
            'valid': True,
        },
    ]
    service = PrincipalAnalysisService(cast(Any, SimpleNamespace(policy_repo=repo)))

    result = service.by_exact_dynamic_groups(
        [
            {
                'domain_name': 'Default',
                'dynamic_group_name': 'Builders',
                'dynamic_group_ocid': 'ocid1.dynamicgroup.oc1..builders',
            }
        ]
    )

    assert [statement['policy_name'] for statement in result.statements] == [
        'named-dynamic-group',
        'ocid-dynamic-group',
    ]


def test_dynamic_groups_tab_uses_weighted_rows_for_inventory_and_statements():
    """A large inventory must not obscure the matching-statements table."""
    source = Path('src/oci_policy_analysis/presentation/desktop/dynamic_group_tab.py').read_text()

    assert 'tables_frame.grid_rowconfigure(0, weight=1)' in source
    assert 'tables_frame.grid_rowconfigure(1, weight=1)' in source
    assert "label_frm_dynamicgroups.grid(row=0, column=0, sticky='nsew'" in source
    assert "label_frm_policies.grid(row=1, column=0, sticky='nsew'" in source
