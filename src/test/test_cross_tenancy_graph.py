"""Relationship graph data keeps cross-tenancy direction and definitions explicit."""

from types import SimpleNamespace

import pytest

from oci_policy_analysis.application.core.engine.intelligence_strategies.cross_tenancy_findings import (
    CrossTenancyFindingsStrategy,
)
from oci_policy_analysis.application.services.cross_tenancy_analysis_service import CrossTenancyAnalysisService


def test_generate_single_policy_orders_valid_resolved_statements_and_reports_omissions() -> None:
    payload = {
        'defines': [
            {
                'valid': True,
                'defined_type': 'tenancy',
                'definition_status': 'resolved',
                'policy_name': 'Definitions',
                'statement_text': 'Define tenancy Partner as ocid1.tenancy.partner',
            },
            {'valid': False, 'policy_name': 'Bad', 'statement_text': 'invalid define'},
        ],
        'admit_statements': [
            {
                'valid': True,
                'policy_name': 'Admissions',
                'statement_text': 'Admit group Admins of tenancy Partner to manage all-resources in tenancy',
                'external_tenancies': [{'status': 'resolved'}],
            },
            {
                'valid': True,
                'policy_name': 'Unresolved',
                'statement_text': 'Admit group Unknown of tenancy Missing to manage all-resources in tenancy',
                'external_tenancies': [{'status': 'unresolved'}],
            },
        ],
        'endorse_statements': [
            {
                'valid': True,
                'policy_name': 'Endorsements',
                'statement_text': 'Endorse group Admins to manage all-resources in tenancy Partner',
                'external_tenancies': [{'status': 'resolved'}],
            }
        ],
        'unknown_statements': [{'statement_text': 'Other cross-tenancy statement'}],
    }

    generated = CrossTenancyAnalysisService.generate_single_policy(payload)

    lines = generated['text'].splitlines()
    assert len(lines) == 3
    assert lines[0].startswith('Define tenancy Partner')
    assert lines[0].endswith('// Define · source policy: Definitions')
    assert lines[1].startswith('Admit group Admins')
    assert lines[2].startswith('Endorse group Admins')
    assert generated['included'] == 3
    assert generated['invalid_or_unparsed'] == 1
    assert generated['unresolved_or_ambiguous'] == 1
    assert generated['unclassified'] == 1
    assert generated['policies'][0]['text'].splitlines() == lines


@pytest.mark.parametrize('relation_count', [49, 50, 51, 97])
def test_generated_policies_stay_within_statement_limit_and_repeat_relevant_defines(relation_count) -> None:
    payload = {
        'defines': [
            {
                'valid': True,
                'defined_type': kind,
                'defined_name': name,
                'statement_text': f'Define {kind} {name} as ocid1.{kind}.{name.casefold()}',
                'policy_name': 'Definitions',
            }
            for kind, name in (('tenancy', 'Partner'), ('group', 'RemoteAdmins'))
        ],
        'admit_statements': [
            {
                'valid': True,
                'parsed': True,
                'policy_name': 'Admissions',
                'statement_text': f'Admit group RemoteAdmins of tenancy Partner to read buckets in tenancy /* {n} */',
                'external_tenancies': [{'status': 'resolved'}],
            }
            for n in range(relation_count)
        ],
        'endorse_statements': [],
    }

    generated = CrossTenancyAnalysisService.generate_single_policy(payload)

    assert len(generated['policies']) > 1
    assert all(policy['included'] <= 50 for policy in generated['policies'])
    assert all('Define tenancy Partner' in policy['text'] for policy in generated['policies'])
    assert all('Define group RemoteAdmins' in policy['text'] for policy in generated['policies'])
    for policy in generated['policies']:
        lines = policy['text'].splitlines()
        assert lines[0].startswith('Define tenancy Partner')
        assert lines[1].startswith('Define group RemoteAdmins')
        assert all(line.startswith('Admit ') for line in lines[2:])
    assert sum(policy['included'] - 2 for policy in generated['policies']) == relation_count


@pytest.mark.parametrize('kind', ['group', 'dynamic-group', 'compartment'])
@pytest.mark.parametrize('status', ['resolved', 'ambiguous'])
def test_generated_policy_omits_conflicting_scoped_aliases_and_dependent_relations(kind, status):
    definitions = [
        {
            'valid': True,
            'defined_type': kind,
            'defined_name': 'Shared',
            'ocid_alias': f'ocid1.{kind}.{source}',
            'definition_status': status,
            'policy_name': source,
            'statement_text': f'Define {kind} Shared as ocid1.{kind}.{source}',
        }
        for source in ('Alpha', 'Beta')
    ]
    relation = (
        'Admit group Shared of tenancy Partner to read buckets in tenancy'
        if kind != 'compartment'
        else 'Admit group Admins of tenancy Partner to read buckets in compartment Shared'
    )
    safe = 'Admit any-user of tenancy Partner to read buckets in tenancy'
    payload = {
        'defines': definitions,
        'admit_statements': [
            {
                'valid': True,
                'parsed': True,
                'policy_name': source,
                'statement_text': relation,
                'external_tenancies': [{'status': 'resolved'}],
            }
            for source in ('Alpha', 'Beta')
        ]
        + [{'valid': True, 'statement_text': safe, 'external_tenancies': [{'status': 'resolved'}]}],
    }
    generated = CrossTenancyAnalysisService.generate_single_policy(payload)

    assert generated['included'] == 1
    assert generated['unresolved_or_ambiguous'] == 4
    assert len(generated['omission_reasons']) == 4
    assert all('shared' in row['reason'] for row in generated['omission_reasons'])
    assert generated['policies'][0]['text'].startswith(safe)
    assert 'Shared' not in '\n'.join(line for line in generated['text'].splitlines() if not line.startswith('//'))
    assert '// Not included:' in generated['policies'][0]['text']
    assert 'Conflicting alias definitions' in generated['policies'][0]['text']


def test_generated_policy_omits_relation_whose_dependencies_cannot_fit_one_policy():
    definitions = [
        {
            'valid': True,
            'defined_type': 'group',
            'defined_name': f'Group{index}',
            'ocid_alias': f'ocid1.group.{index}',
            'statement_text': f'Define group Group{index} as ocid1.group.{index}',
        }
        for index in range(50)
    ]
    text = 'Admit group ' + ', '.join(f'Group{index}' for index in range(50))
    text += ' of tenancy Partner to read buckets in tenancy'
    generated = CrossTenancyAnalysisService.generate_single_policy(
        {
            'defines': definitions,
            'admit_statements': [
                {'valid': True, 'statement_text': text, 'external_tenancies': [{'status': 'resolved'}]}
            ],
        }
    )

    assert generated['included_by_kind']['Admit'] == 0
    assert generated['included'] == 50
    assert generated['unresolved_or_ambiguous'] == 1
    assert generated['omission_reasons'][0]['statement_text'] == text
    assert '50-statement policy limit' in generated['omission_reasons'][0]['reason']
    assert text not in '\n'.join(line for line in generated['text'].splitlines() if not line.startswith('//'))
    assert all(policy['included'] <= 50 for policy in generated['policies'])
    assert '50-statement policy limit' in generated['policies'][0]['text']


def test_graph_has_incoming_outgoing_and_association_links() -> None:
    repo = SimpleNamespace(
        tenancy_name='Home',
        tenancy_ocid='ocid1.tenancy.home',
        defined_aliases=[
            {
                'defined_type': 'tenancy',
                'defined_name': 'Partner',
                'ocid_alias': 'ocid1.tenancy.partner',
                'policy_ocid': 'policy-1',
                'statement_text': 'Define tenancy Partner as ocid1.tenancy.partner',
            },
            {
                'defined_type': 'group',
                'defined_name': 'RemoteAdmins',
                'ocid_alias': 'ocid1.group.remote',
                'policy_ocid': 'policy-1',
                'statement_text': 'Define group RemoteAdmins as ocid1.group.remote',
            },
            {
                'defined_type': 'compartment',
                'defined_name': 'SharedData',
                'ocid_alias': 'ocid1.compartment.shared',
                'policy_ocid': 'policy-1',
                'statement_text': 'Define compartment SharedData as ocid1.compartment.shared',
            },
        ],
        cross_tenancy_statements=[
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Admit group RemoteAdmins of tenancy Partner to read buckets in tenancy',
                'tenancy_aliases': ['Partner'],
            },
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Endorse group Operators to read objects in tenancy Partner',
                'tenancy_aliases': ['Partner'],
            },
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Endorse group Operators to associate objects in tenancy Partner with objects in compartment SharedData',
                'tenancy_aliases': ['Partner'],
                'association': [{'scope': 'Partner', 'resource': 'objects'}],
            },
        ],
    )

    payload = CrossTenancyAnalysisService(repo).get_analysis_payload()
    graph = payload['relationship_graph']
    tenancy = graph['tenancies'][0]

    assert tenancy['alias'] == 'Partner'
    assert tenancy['ocid'] == 'ocid1.tenancy.partner'
    assert tenancy['incoming_count'] == 1
    assert tenancy['outgoing_count'] == 1
    assert tenancy['association_count'] == 1
    assert len(tenancy['statement_keys']) == 4  # Define plus three relationship statements.
    assert {(link['direction'], link['association']) for link in graph['links']} == {
        ('incoming', False),
        ('outgoing', False),
        ('incoming', True),
        ('outgoing', True),
    }
    entities = {item['defined_name']: item for item in graph['defined_entities']}
    assert entities['RemoteAdmins']['defined_type'] == 'group'
    assert len(entities['RemoteAdmins']['statement_keys']) == 2
    assert not entities['RemoteAdmins']['orphan']
    assert entities['SharedData']['defined_type'] == 'compartment'
    assert len(entities['SharedData']['statement_keys']) == 2
    assert not entities['SharedData']['orphan']
    assert any(
        node['kind'] == 'group' and node['name'] == 'RemoteAdmins' and node['tenancy_alias'] == 'Partner'
        for node in graph['subnodes']
    )
    assert any(
        node['kind'] == 'compartment' and node['name'] == 'SharedData' and node['tenancy_alias'] == ''
        for node in graph['subnodes']
    )
    assert all(row['kind'] == 'Define' and row['stable_key'] for row in payload['defines'])
    associations = {row['defined_name']: row['tenancy_associations'] for row in payload['defines']}
    assert associations['Partner'][0]['name'] == 'Partner'
    assert associations['RemoteAdmins'][0]['name'] == 'Partner'
    assert associations['SharedData'] == []


def test_legacy_fallback_does_not_turn_compartment_scope_into_a_tenancy() -> None:
    aliases = CrossTenancyAnalysisService._fallback_aliases(
        {
            'admitted_tenancy': 'Partner',
            'association': [{'scope': 'tenancy Partner'}, {'scope': 'compartment SharedData'}],
        },
        'Admit',
    )

    assert aliases == ['Partner']


def test_graph_places_defined_entities_and_admitted_any_user() -> None:
    repo = SimpleNamespace(
        tenancy_name='Home',
        tenancy_ocid='ocid1.tenancy.home',
        defined_aliases=[
            {
                'defined_type': 'tenancy',
                'defined_name': 'Ske',
                'ocid_alias': 'ocid1.tenancy.ske',
                'statement_text': 'Define tenancy Ske as ocid1.tenancy.ske',
            },
            {
                'defined_type': 'compartment',
                'defined_name': 'ske_compartment',
                'ocid_alias': 'ocid1.compartment.ske',
                'statement_text': 'Define compartment ske_compartment as ocid1.compartment.ske',
            },
            {
                'defined_type': 'dynamic-group',
                'defined_name': 'RemoteWorkers',
                'ocid_alias': 'ocid1.dynamicgroup.ske',
                'statement_text': 'Define dynamic-group RemoteWorkers as ocid1.dynamicgroup.ske',
            },
            {
                'defined_type': 'group',
                'defined_name': 'UnusedGroup',
                'ocid_alias': 'ocid1.group.unused',
                'statement_text': 'Define group UnusedGroup as ocid1.group.unused',
            },
        ],
        cross_tenancy_statements=[
            {
                'statement_text': 'Endorse group Operators to read objects in compartment ske_compartment of tenancy Ske',
                'tenancy_aliases': ['Ske'],
            },
            {
                'statement_text': 'Admit dynamic-group RemoteWorkers of tenancy Ske to read buckets in tenancy',
                'tenancy_aliases': ['Ske'],
                'admitted_principal_type': 'dynamic-group',
                'admitted_principal': 'RemoteWorkers',
                'admitted_tenancy': 'Ske',
            },
            {
                'statement_text': 'Admit any-user of tenancy Ske to read buckets in tenancy',
                'tenancy_aliases': ['Ske'],
                'admitted_principal_type': 'any-user',
                'admitted_principal': 'any-user',
                'admitted_tenancy': 'Ske',
            },
        ],
    )

    graph = CrossTenancyAnalysisService(repo).get_analysis_payload()['relationship_graph']
    placed = {(node['kind'], node['name'], node['tenancy_alias']) for node in graph['subnodes']}
    assert ('compartment', 'ske_compartment', 'Ske') in placed
    assert ('dynamic-group', 'RemoteWorkers', 'Ske') in placed
    assert ('any-user', 'any-user', 'Ske') in placed
    entities = {item['defined_name']: item for item in graph['defined_entities']}
    assert not entities['ske_compartment']['orphan']
    assert not entities['RemoteWorkers']['orphan']
    assert entities['UnusedGroup']['orphan']
    associations = {
        row['defined_name']: row['tenancy_associations']
        for row in CrossTenancyAnalysisService(repo).get_analysis_payload()['defines']
    }
    assert associations['ske_compartment'][0]['name'] == 'Ske'
    assert associations['UnusedGroup'] == []


def test_conflicting_definitions_are_findings_and_tenancy_stays_unresolved() -> None:
    repo = SimpleNamespace(
        tenancy_name='Home',
        tenancy_ocid='ocid1.tenancy.home',
        defined_aliases=[
            {
                'defined_type': 'tenancy',
                'defined_name': 'Partner',
                'ocid_alias': 'ocid1.tenancy.a',
                'policy_name': 'Policy A',
                'statement_text': 'Define tenancy Partner as ocid1.tenancy.a',
            },
            {
                'defined_type': 'tenancy',
                'defined_name': 'partner',
                'ocid_alias': 'ocid1.tenancy.b',
                'policy_name': 'Policy B',
                'statement_text': 'Define tenancy partner as ocid1.tenancy.b',
            },
            {
                'defined_type': 'group',
                'defined_name': 'Admins',
                'ocid_alias': 'ocid1.group.a',
                'statement_text': 'Define group Admins as ocid1.group.a',
            },
            {
                'defined_type': 'group',
                'defined_name': 'admins',
                'ocid_alias': 'ocid1.group.b',
                'statement_text': 'Define group admins as ocid1.group.b',
            },
        ],
        cross_tenancy_statements=[
            {
                'statement_text': 'Admit group Admins of tenancy Partner to read buckets in tenancy',
                'policy_name': 'Policy A',
                'tenancy_aliases': ['Partner'],
                'resolved_aliases': {'Partner': {'resolved': True, 'ocid': 'ocid1.tenancy.b'}},
                'parsed': True,
            },
        ],
    )
    overlay = {}
    CrossTenancyFindingsStrategy().run(repo, overlay)
    findings = overlay['cross_tenancy_findings']
    ambiguous = [item for item in findings if item['Type'] == 'Ambiguous Define']
    assert {(item['Alias'].casefold(), item['Severity']) for item in ambiguous} == {
        ('partner', 'Error'),
        ('admins', 'Error'),
    }
    assert any(
        item['Type'] == 'Unresolved Tenancy Define' and item['Issue'] == 'Conflicting tenancy defines'
        for item in findings
    )
    assert all(item['related_statements'] for item in findings)

    payload = CrossTenancyAnalysisService(repo, findings).get_analysis_payload()
    assert not payload['relationship_graph']['tenancies'][0]['resolved']
    assert payload['relationship_graph']['tenancies'][0]['ocid'] == ''
    assert payload['counts']['ambiguous'] == 2


def test_any_tenancy_is_a_clickable_special_scope_in_both_directions() -> None:
    repo = SimpleNamespace(
        tenancy_name='Home',
        tenancy_ocid='ocid1.tenancy.home',
        defined_aliases=[],
        cross_tenancy_statements=[
            {
                'statement_text': 'Endorse group Operators to read objects in any-tenancy',
                'tenancy_aliases': [],
                'endorse_tenancy': 'any-tenancy',
                'parsed': True,
            },
            {
                'statement_text': 'Admit group Visitors of any-tenancy to read buckets in tenancy',
                'tenancy_aliases': ['any-tenancy'],
                'parsed': True,
            },
        ],
    )
    payload = CrossTenancyAnalysisService(repo).get_analysis_payload()
    graph = payload['relationship_graph']

    assert len(graph['tenancies']) == 1
    assert graph['tenancies'][0]['alias'] == 'any-tenancy'
    assert graph['tenancies'][0]['special'] is True
    assert graph['tenancies'][0]['ocid'] == ''
    assert {(link['direction'], link['count']) for link in graph['links']} == {
        ('incoming', 1),
        ('outgoing', 1),
    }
    assert payload['admit_statements'][0]['external_tenancies'][0]['special'] is True
    assert payload['endorse_statements'][0]['external_tenancies'][0]['special'] is True

    overlay = {}
    CrossTenancyFindingsStrategy().run(repo, overlay)
    assert not any(item['Type'] == 'Unresolved Tenancy Define' for item in overlay['cross_tenancy_findings'])
