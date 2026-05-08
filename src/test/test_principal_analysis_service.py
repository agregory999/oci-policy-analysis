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

    class _AnalysisStub:
        @staticmethod
        def filter_policy_statements(*, filters):
            assert filters.get('subject_type') == ['any-user']
            return SimpleNamespace(
                statements=[
                    {
                        'subject_type': 'any-user',
                        'statement_text': 'allow any-user to manage all-resources in tenancy',
                        'conditions': "all { request.principal.type = 'serviceconnector' }",
                    },
                    {
                        'subject_type': 'any-user',
                        'statement_text': 'allow any-user to use object-family in tenancy',
                        'conditions': "all { request.principal.type = 'autonomousdatabase' }",
                    },
                ]
            )

    svc.analysis = cast(Any, _AnalysisStub())
    result = svc.by_subject_types(subject_types=['any-user'], resource_type='serviceconnector')

    assert len(result.statements) == 1
    assert 'serviceconnector' in str(result.statements[0].get('conditions') or '').casefold()
