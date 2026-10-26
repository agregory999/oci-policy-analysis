"""Cross-tenancy snapshots preserve occurrences and UI selection provenance."""

from types import SimpleNamespace

import pytest

from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpusBuilder
from oci_policy_analysis.application.core.engine.intelligence_strategies.cross_tenancy_findings import (
    CrossTenancyFindingsStrategy,
)
from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.services.cross_tenancy_analysis_service import CrossTenancyAnalysisService
from oci_policy_analysis.presentation.tk.cross_tenancy_tab import selected_rows


def _repo():
    return SimpleNamespace(
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
                'defined_name': 'Unused',
                'ocid_alias': 'ocid1.group.unused',
                'policy_ocid': 'policy-1',
                'statement_text': 'Define group Unused as ocid1.group.unused',
            },
        ],
        cross_tenancy_statements=[
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Admit group Admins of tenancy Partner to read buckets in tenancy',
                'tenancy_aliases': ['Partner'],
                'parsed': True,
            },
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Admit group Admins of tenancy Partner to read buckets in tenancy',
                'tenancy_aliases': ['Partner'],
                'parsed': True,
            },
            {
                'policy_ocid': 'policy-1',
                'statement_text': 'Endorse group Ops to read objects in any-tenancy',
                'tenancy_aliases': ['any-tenancy'],
                'parsed': False,
            },
        ],
    )


def test_occurrences_and_graph_selection_match() -> None:
    repo = _repo()
    corpus = CrossTenancyCorpusBuilder().build(repo)
    payload = corpus.project()
    admit = payload['admit_statements']
    assert len({row['stable_key'] for row in admit}) == 2
    assert [row['stable_key'] for row in admit] == [
        CrossTenancyCorpusBuilder().build(repo).project()['admit_statements'][index]['stable_key'] for index in range(2)
    ]
    link = next(link for link in payload['relationship_graph']['links'] if link['alias'] == 'Partner')
    assert set(link['statement_keys']) == {row['stable_key'] for row in admit}
    assert len(selected_rows(payload, set(link['statement_keys']))) == 2
    assert len(selected_rows(payload, set(link['statement_keys']), 'Admins')) == 2
    assert selected_rows(payload, set(link['statement_keys']), 'Ops') == []
    assert payload['relationship_graph']['tenancies'][0]['id'].startswith('tenancy:')
    assert corpus.to_dict('diagnostics')[0]['type'] == 'parse_uncertainty'
    assert corpus.summary()['statements'] == 3


def test_snapshot_is_isolated_and_rebuild_replaces_data() -> None:
    repo = _repo()
    original = CrossTenancyCorpusBuilder().build(repo)
    original_key = original.project()['admit_statements'][0]['stable_key']
    repo.cross_tenancy_statements.clear()
    rebuilt = CrossTenancyCorpusBuilder().build(repo)
    assert original.summary()['statements'] == 3
    assert original.project()['admit_statements'][0]['stable_key'] == original_key
    assert rebuilt.summary()['statements'] == 0
    assert rebuilt.project()['relationship_graph']['links'] == []


def test_admitted_principal_identity_includes_remote_tenancy_scope() -> None:
    repo = _repo()
    repo.cross_tenancy_statements[0].update(
        {
            'admitted_principal_type': 'group',
            'admitted_principal': 'Default/Admins',
            'admitted_tenancy': 'Partner',
            'principal_keys': ['group:Default/Admins'],
        }
    )
    corpus = CrossTenancyCorpusBuilder().build(repo)
    row = corpus.project()['admit_statements'][0]
    assert row['principal_keys'] == ['group:default/admins']
    assert row['principal_identity'] == {
        'type': 'group',
        'name': 'Default/Admins',
        'tenancy_alias': 'Partner',
        'tenancy_ocid': 'ocid1.tenancy.partner',
        'tenancy_status': 'resolved',
    }
    assert corpus.to_dict('statements')[0]['principal_identity'] == row['principal_identity']
    tenancy_define = next(item for item in corpus.project()['defines'] if item['defined_type'] == 'tenancy')
    assert tenancy_define['tenancy_associations'][0]['basis'] == 'Explicit tenancy define'


def test_ambiguous_alias_is_invalid_and_any_tenancy_is_special() -> None:
    repo = _repo()
    repo.defined_aliases.append(
        {
            'defined_type': 'tenancy',
            'defined_name': 'partner',
            'ocid_alias': 'ocid1.tenancy.other',
            'statement_text': 'Define tenancy partner as ocid1.tenancy.other',
        }
    )
    engine = PolicyIntelligenceEngine(repo)
    engine.resolve_cross_tenancy_aliases()
    assert repo.cross_tenancy_statements[0]['resolved_aliases']['Partner']['status'] == 'ambiguous'
    assert repo.cross_tenancy_statements[0]['valid'] is False
    assert repo.cross_tenancy_statements[2]['resolved_aliases']['any-tenancy']['status'] == 'special'
    assert repo.cross_tenancy_statements[2]['aliases_resolved'] is True
    corpus = CrossTenancyCorpusBuilder().build(repo)
    assert corpus.project()['admit_statements'][0]['external_tenancies'][0]['status'] == 'ambiguous'


def test_duplicate_finding_preserves_both_source_occurrences() -> None:
    repo = _repo()
    for row in repo.cross_tenancy_statements[:2]:
        row.update(
            {
                'action_type': 'admit',
                'admitted_principal_type': 'group',
                'admitted_principal': 'Admins',
                'admit_action': 'read',
                'admit_resource': 'buckets',
            }
        )
    overlay = {}
    CrossTenancyFindingsStrategy().run(repo, overlay)
    corpus = CrossTenancyCorpusBuilder().build(repo, overlay['cross_tenancy_findings'])
    duplicate = next(row for row in corpus.project()['findings'] if row['Type'] == 'Duplicate Admit Statement')
    assert len(duplicate['source_ids']) == 2
    assert len(set(duplicate['source_ids'])) == 2
    assert {ref['source_id'] for ref in duplicate['related_statements']} == set(duplicate['source_ids'])
    assert CrossTenancyAnalysisService(repo, corpus=corpus).get_analysis_payload() == corpus.project()


@pytest.mark.parametrize(
    'cached_association',
    [None, [{'resource': 'objects', 'scope': ''}, {'resource': 'objects', 'scope': 'compartment SharedData'}]],
)
def test_legacy_association_cache_rebuilds_endpoint_structure_without_mutating_source(cached_association):
    import copy

    repo = _repo()
    statement = {
        'policy_ocid': 'policy-1',
        'internal_id': 'legacy-associate',
        'statement_text': 'Endorse group Operators to associate objects in tenancy Partner with objects in compartment SharedData',
        'parsed': True,
        'valid': True,
        'endorse_action': 'associate',
        'endorse_resource': 'objects',
        'endorse_tenancy': 'Partner',
        'endorse_associate_with_resource': 'objects',
        'endorse_associate_with_tenancy': 'compartment SharedData',
        'tenancy_aliases': ['Partner'],
    }
    repo.cross_tenancy_statements = [statement]
    if cached_association is not None:
        statement['association'] = cached_association
    original = copy.deepcopy(statement)
    corpus = CrossTenancyCorpusBuilder().build(repo)
    compiled = corpus.to_dict('statements')[0]
    assert len(compiled['association']) == 2
    assert compiled['association'][0]['scope'] == 'tenancy Partner'
    assert compiled['association'][1]['scope'] == 'compartment SharedData'
    graph = corpus.project()['relationship_graph']
    assert graph['tenancies'][0]['association_count'] == 1
    assert all(link['association'] for link in graph['links'])
    assert statement == original


def test_legacy_admit_association_preserves_validation_findings():
    repo = _repo()
    row = {
        'statement_text': 'Admit group Admins of tenancy Partner to associate objects in tenancy with objects in compartment SharedData',
        'parsed': True,
        'valid': False,
        'invalid_reasons': ['Retained validation finding'],
        'admitted_tenancy': 'Partner',
        'admit_action': 'associate',
        'tenancy_aliases': ['Partner'],
    }
    repo.cross_tenancy_statements = [row]
    compiled = CrossTenancyCorpusBuilder().build(repo).to_dict('statements')[0]
    assert compiled['association'] == [
        {'resource': 'objects', 'scope': 'tenancy'},
        {'resource': 'objects', 'scope': 'compartment SharedData'},
    ]
    assert compiled['admitted_tenancy'] == 'Partner'
    assert compiled['valid'] is False
    assert compiled['invalid_reasons'] == ['Retained validation finding']
    assert 'association' not in row
