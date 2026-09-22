import logging

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


def test_parse_condition_structure_captures_lexer_errors_without_stderr(capsys, caplog):
    text = 'request.operation = ‘CreateVcn’'

    with caplog.at_level(logging.WARNING, logger='oci-policy-analysis.condition_structure'):
        parsed = parse_condition_structure(text)

    captured = capsys.readouterr()
    assert captured.err == ''
    assert parsed['parse_status'] == 'unsupported'
    assert len(parsed['warnings']) == 2
    assert all('token recognition error' in warning for warning in parsed['warnings'])
    assert text in caplog.text
