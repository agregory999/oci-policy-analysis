from oci_policy_analysis.application.core.parser.condition_structure import (
    format_condition_structure_summary,
    parse_condition_structure,
)


def test_parse_condition_structure_extracts_resource_principal_atoms():
    parsed = parse_condition_structure(
        "all { request.principal.type = 'containerinstance', request.principal.compartment.id = 'ocid1.compartment.oc1..app' }"
    )

    assert parsed['parse_status'] == 'parsed'
    assert parsed['structure'] == 'ALL { c1, c2 }'
    assert [atom['left'] for atom in parsed['atoms']] == [
        'request.principal.type',
        'request.principal.compartment.id',
    ]
    assert {atom['evidence_kind'] for atom in parsed['atoms']} == {'resource_principal'}
    assert format_condition_structure_summary(parsed) == 'parsed: ALL { c1, c2 } (2 atoms)'


def test_parse_condition_structure_extracts_dynamic_group_rule_atoms():
    parsed = parse_condition_structure("any { instance.compartment.id = 'ocid1.compartment.oc1..app' }")

    assert parsed['parse_status'] == 'parsed'
    assert parsed['structure'] == 'ANY { c1 }'
    assert parsed['atoms'][0]['left'] == 'instance.compartment.id'
    assert parsed['atoms'][0]['evidence_kind'] == 'instance_principal'


def test_parse_condition_structure_handles_absent_text():
    parsed = parse_condition_structure('')

    assert parsed['parse_status'] == 'absent'
    assert parsed['atoms'] == []
    assert format_condition_structure_summary(parsed) == ''
