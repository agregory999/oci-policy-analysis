"""Tests for parsed tag-based policy query semantics."""

from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.tag_based_policy_service import TagBasedPolicyService


def _repo() -> PolicyAnalysisRepository:
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {
            'policy_name': 'target-resource-policy',
            'statement_text': "allow group Devs to use instances in tenancy where target.resource.tag.Operations.Env = 'Prod'",
            'subject_type': 'group',
            'subject': [('Default', 'Devs')],
            'verb': 'use',
            'resource': 'instances',
            'permission': ['INSTANCE_UPDATE'],
            'conditions': "target.resource.tag.Operations.Env = 'Prod'",
            'policy_freeform_tags': {'owner': 'platform'},
            'policy_defined_tags': {'Governance': {'CostCenter': '42'}},
            'valid': True,
        },
        {
            'policy_name': 'requestor-policy',
            'statement_text': "allow any-user to inspect buckets in tenancy where request.principal.group.tag.Team.Project != 'Blue'",
            'subject_type': 'any-user',
            'subject': [],
            'verb': 'inspect',
            'resource': 'buckets',
            'permission': ['BUCKET_INSPECT'],
            'conditions': "request.principal.group.tag.Team.Project != 'Blue'",
            'valid': True,
        },
        {
            'policy_name': 'plain-policy',
            'statement_text': 'allow group Devs to read buckets in tenancy',
            'subject_type': 'group',
            'subject': [('Default', 'Devs')],
            'verb': 'read',
            'resource': 'buckets',
            'permission': ['BUCKET_READ'],
            'conditions': '',
            'valid': True,
        },
    ]
    repo.enrich_display_structures()
    return repo


def _names(repo: PolicyAnalysisRepository, filters: dict) -> list[str]:
    return [stmt['policy_name'] for stmt in repo.filter_policy_statements(filters)]


def test_enrichment_classifies_tag_access_semantics_and_warnings() -> None:
    stmt = {
        'conditions': "target.resource.compartment.tag.Operations.Env in ('Prod','Stage')",
    }

    TagBasedPolicyService.enrich_statement(stmt)

    assert stmt['tag_conditions'][0]['access_semantics'] == 'target_compartment_tag'
    assert stmt['tag_conditions'][0]['value_type'] == 'list'
    assert any('nested compartments' in warning for warning in stmt['tag_context_warnings'])


def test_tag_filters_and_with_same_condition_and_other_filters() -> None:
    repo = _repo()

    assert _names(
        repo,
        {
            'tag_namespace': ['Operations'],
            'tag_key': ['Env'],
            'tag_value': ['Prod'],
            'tag_operator': ['='],
            'verb': ['use'],
            'resource': ['instances'],
        },
    ) == ['target-resource-policy']

    assert _names(repo, {'tag_namespace': ['Operations'], 'tag_key': ['Project']}) == []


def test_condition_atom_terms_match_parsed_lhs_rhs_and_legacy_conditions_still_work() -> None:
    repo = _repo()

    assert _names(repo, {'condition_atom_terms': ['Team.Project']}) == ['requestor-policy']
    assert _names(repo, {'conditions': ['target.resource.tag.Operations.Env']}) == ['target-resource-policy']


def test_policy_metadata_tag_filters_return_policy_statements() -> None:
    repo = _repo()

    assert _names(repo, {'policy_tag': ['platform']}) == ['target-resource-policy']
    assert _names(repo, {'policy_defined_tag': ['CostCenter']}) == ['target-resource-policy']
    assert _names(repo, {'policy_freeform_tag': ['owner']}) == ['target-resource-policy']


def test_tag_inventory_is_detached_and_preserves_complete_conditions_and_invalid_sources():
    from copy import deepcopy

    clause = "all { target.resource.tag.Operations.Env = 'Prod', request.operation = 'GetInstance' }"
    sources = [
        {
            'internal_id': 'tagged',
            'policy_ocid': 'policy-1',
            'conditions': clause,
            'valid': False,
            'invalid_reasons': ['Example invalid source'],
            'statement_text': 'allow group Devs to use instances in tenancy where ' + clause,
        },
        {'internal_id': 'unparsed', 'conditions': 'target.resource.tag.Broken', 'valid': False},
        {'internal_id': 'plain', 'conditions': "request.operation = 'ListInstances'"},
    ]
    before = deepcopy(sources)
    result = TagBasedPolicyService.inventory(sources)
    assert sources == before
    assert len(result['statements']) == 2
    assert result['namespace_count'] == 1
    parsed = result['conditions'][0]
    assert parsed['tag_scope'] == 'target_resource_tag'
    assert parsed['tag_namespace'] == 'Operations' and parsed['tag_key'] == 'Env'
    assert parsed['conditions'] == clause and parsed['policy_ocid'] == 'policy-1'
    assert not parsed['valid'] and parsed['invalid_reasons'] == ['Example invalid source']
    assert parsed['tag_expression'] == "target.resource.tag.Operations.Env='Prod'"
    assert result['conditions'][1]['tag_parse_status'].startswith('Unparsed')
    result['statements'][0]['invalid_reasons'].append('detached')
    assert sources == before


def test_tag_inventory_keeps_all_scopes_and_variable_comparisons():
    clauses = [
        "request.principal.group.tag.Team.Project = 'Blue'",
        "request.principal.compartment.tag.Team.Project = 'Blue'",
        'target.resource.tag.Team.Project = request.principal.group.tag.Team.Project',
        "target.resource.compartment.tag.Team.Project = 'Blue'",
    ]
    result = TagBasedPolicyService.inventory([{'conditions': clause} for clause in clauses])
    assert {row['tag_scope'] for row in result['conditions']} == {
        'requestor_group_tag',
        'requestor_compartment_tag',
        'target_resource_tag',
        'target_compartment_tag',
    }
    assert any('request.principal.group.tag' in str(row['tag_value']) for row in result['conditions'])
