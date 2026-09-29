import csv
import json

from oci_policy_analysis.application.core.parser.condition_structure import parse_condition_structure
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository


def test_parsing_diagnostics_capture_policy_condition_and_dynamic_group_results(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / 'parsing-diagnostics.csv'
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV', str(output_path))
    repo = PolicyAnalysisRepository()
    condition_text = "request.operation = 'CreateVcn'"
    dynamic_group_rule = "instance.id = 'ocid1.instance.oc1..example'"
    repo.regular_statements = [
        {
            'internal_id': 'statement-1',
            'policy_name': 'Network policy',
            'policy_ocid': 'ocid1.policy.oc1..example',
            'compartment_ocid': 'ocid1.compartment.oc1..example',
            'compartment_path': 'ROOT/Network',
            'statement_text': f'Allow group NetworkAdmins to manage virtual-network-family in tenancy where {condition_text}',
            'parsed': True,
            'valid': True,
            'action': 'allow',
            'subject_type': 'group',
            'verb': 'manage',
            'resource': 'virtual-network-family',
            'conditions': condition_text,
            'where_clause_structure': parse_condition_structure(condition_text),
            'parsing_notes': ['Example parsing note'],
        }
    ]
    repo.cross_tenancy_statements = [
        {
            'internal_id': 'statement-2',
            'policy_name': 'Cross-tenancy policy',
            'statement_text': 'Admit group invalid',
            'parsed': False,
            'valid': False,
            'invalid_reasons': ['ANTLR syntax error'],
        }
    ]
    repo.defined_aliases = []
    repo.dynamic_groups = [
        {
            'dynamic_group_id': 'dynamic-group-1',
            'dynamic_group_ocid': 'ocid1.dynamicgroup.oc1..example',
            'dynamic_group_name': 'BuildAgents',
            'domain_name': 'Default',
            'domain_ocid': 'ocid1.domain.oc1..example',
            'matching_rule': dynamic_group_rule,
            'matching_rule_structure': parse_condition_structure(dynamic_group_rule),
        }
    ]

    repo._record_loaded_parsing_diagnostics('test_fixture')

    with output_path.open(encoding='utf-8', newline='') as file_object:
        rows = list(csv.DictReader(file_object))
    assert [(row['parse_type'], row['record_id']) for row in rows] == [
        ('policy_statement', 'statement-1'),
        ('where_clause', 'statement-1'),
        ('policy_statement', 'statement-2'),
        ('dynamic_group_rule', 'dynamic-group-1'),
    ]
    statement_row, condition_row, invalid_row, dynamic_group_row = rows
    assert statement_row['parse_status'] == 'parsed'
    assert statement_row['parsing_notes'] == json.dumps(['Example parsing note'])
    assert condition_row['parse_status'] == 'parsed'
    assert condition_row['parse_text'] == condition_text
    assert condition_row['parent_statement_text'] == statement_row['parse_text']
    assert invalid_row['parse_status'] == 'failed'
    assert json.loads(invalid_row['errors']) == ['ANTLR syntax error']
    assert dynamic_group_row['domain_name'] == 'Default'
    assert dynamic_group_row['parse_text'] == dynamic_group_rule


def test_parsing_diagnostics_are_disabled_without_environment_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv('OCI_POLICY_ANALYSIS_PARSING_DIAGNOSTICS_CSV', raising=False)
    repo = PolicyAnalysisRepository()
    repo._record_loaded_parsing_diagnostics('test_fixture')

    assert not list(tmp_path.iterdir())
