from types import SimpleNamespace
from typing import Any, cast

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
