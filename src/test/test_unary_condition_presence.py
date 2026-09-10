"""Regression coverage for OCI unary variable-presence conditions."""

from oci_policy_analysis.application.core.parser import extract_variable_names
from oci_policy_analysis.application.core.parser.condition_structure import parse_condition_structure
from oci_policy_analysis.application.core.parser.policy_statement_normalizer import PolicyStatementParser
from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService

FULL_POLICY = (
    'deny any-user to { POLICY_UPDATE, POLICY_DELETE } in tenancy where all { '
    "target.policy.type = 'deny', "
    "target.resource.tag.orcl-assurance.managed-resource = 'true', "
    "any { !request.principal.type, request.principal.type != 'assurance-governance', "
    "!request.principal.serviceType, request.principal.serviceType != 'Assurance', "
    '!request.principal.governingTenancyId, '
    "request.principal.governingTenancyId != 'ocid1.tenancy.oc1..example' } }"
)


def test_policy_parser_accepts_oci_unary_presence_conditions():
    parsed, errors = PolicyStatementParser().parse(FULL_POLICY)

    assert errors == []
    assert parsed and parsed[0]['condition'].count('!request.principal.') == 3


def test_condition_tester_treats_blank_input_as_explicit_null_for_presence_checks():
    service = ConditionTesterService()

    absent = service.evaluate('!request.principal.type', {})
    explicit_null = service.evaluate('!request.principal.type', {'request.principal.type': None})
    blank_ui_value = service.evaluate('!request.principal.type', {'request.principal.type': ''})
    supplied = service.evaluate('!request.principal.type', {'request.principal.type': 'workload'})

    assert absent.granted is True
    assert explicit_null.granted is True
    assert blank_ui_value.granted is True
    assert supplied.granted is False
    assert blank_ui_value.log[0]['type'] == 'Unary presence check'
    assert blank_ui_value.log[0]['sim_value'] == 'MISSING'


def test_condition_tester_grants_when_unary_request_fields_are_absent():
    clause = (
        "all { target.resource.tag.orcl-assurance.managed-resource = 'true', "
        "any { target.security-zone.manageType = 'ASSURANCE', "
        "target.security-recipe.manageType = 'ASSURANCE' }, "
        "any { !request.principal.type, request.principal.type != 'assurance-governance', "
        "!request.principal.serviceType, request.principal.serviceType != 'Assurance', "
        '!request.principal.governingTenancyId, '
        "request.principal.governingTenancyId != 'ocid1.tenancy.oc1..example' } }"
    )

    result = ConditionTesterService().evaluate(
        clause,
        {
            'target.resource.tag.orcl-assurance.managed-resource': 'true',
            'target.security-zone.manageType': 'ASSURANCE',
        },
    )

    assert result.granted is True
    presence_checks = [entry for entry in result.log if entry.get('operator') == '!']
    assert len(presence_checks) == 3
    assert all(entry['result'] is True and entry['sim_value'] == 'MISSING' for entry in presence_checks)


def test_unary_presence_condition_is_discovered_and_structured_without_mangling_variable_name():
    clause = "all { target.policy.type = 'deny', any { !request.principal.type, request.principal.type != 'x' } }"

    assert extract_variable_names(clause) == {'target.policy.type', 'request.principal.type'}
    structure = parse_condition_structure(clause)

    assert structure['parse_status'] == 'parsed'
    unary_atom = next(atom for atom in structure['atoms'] if atom['operator'] == '!')
    assert unary_atom['left'] == 'request.principal.type'
    assert unary_atom['right'] == 'not supplied'
