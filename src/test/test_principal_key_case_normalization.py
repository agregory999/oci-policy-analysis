"""Named principal identity ignores case while policy evidence keeps its source text."""

from types import SimpleNamespace

import pytest

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.parser.policy_statement_normalizer import PolicyStatementNormalizer
from oci_policy_analysis.application.core.policy_corpus import PolicyCorpusBuilder
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.policy_graph_service import PolicyGraphService


@pytest.mark.parametrize('kind', ['group', 'dynamic-group', 'user'])
def test_named_principal_keys_merge_domain_and_name_casing(kind):
    assert calculate_principal_key(kind, 'LZ092026', 'OpsTeam') == calculate_principal_key(kind, 'lz092026', 'opsteam')
    assert calculate_principal_key(kind, 'LZ092026', 'OpsTeam') == f'{kind}:lz092026/opsteam'


def test_parser_keeps_statement_text_and_display_spelling():
    text = "Allow group 'LZ092026'/'OpsTeam' to read buckets in tenancy"
    statement = PolicyStatementNormalizer().normalize(
        text, 'allow', {'internal_id': 'case-test', 'statement_text': text}
    )
    assert statement['principal_keys'] == ['group:lz092026/opsteam']
    assert statement['statement_text'] == text
    assert statement['subject'] == [('LZ092026', 'OpsTeam')]


def test_legacy_keys_produce_one_corpus_and_graph_principal_without_losing_sources():
    texts = [
        "Allow group 'LZ092026'/'OpsTeam' to read buckets in tenancy",
        "Allow group 'lz092026'/'OpsTeam' to read buckets in tenancy",
    ]
    statements = [
        {
            'internal_id': str(index),
            'valid': True,
            'principal_keys': [key],
            'effective_path': 'ROOT',
            'permission': ['BUCKET_READ'],
            'action': 'allow',
            'resource': 'buckets',
            'statement_text': text,
        }
        for index, (key, text) in enumerate(
            zip(['group:LZ092026/OpsTeam', 'group:lz092026/OpsTeam'], texts, strict=True)
        )
    ]
    corpus = PolicyCorpusBuilder().build(SimpleNamespace(regular_statements=statements, compartments=[]))
    assert {fact.principal_key for fact in corpus.facts} == {'group:lz092026/opsteam'}
    grants = PolicyGraphService(corpus).get_page(principal='LZ092026/OPSTEAM')['grants']
    assert len(grants) == 2
    assert {grant['principal'] for grant in grants} == {'group:lz092026/opsteam'}
    assert {grant['statement_text'] for grant in grants} == set(texts)


def test_mixed_case_filter_matches_both_legacy_keys():
    repo = PolicyAnalysisRepository()
    repo.regular_statements = [
        {'policy_name': str(i), 'principal_keys': [key], 'subject_type': 'group', 'valid': True}
        for i, key in enumerate(['group:LZ092026/OpsTeam', 'group:lz092026/opsteam'])
    ]
    for key in ['group:LZ092026/OpsTeam', 'group:lz092026/opsteam']:
        for field in ('principal_key', 'principal_keys'):
            assert len(repo.filter_policy_statements(filters={field: [key]})) == 2


def test_opaque_resource_and_id_payloads_are_not_case_folded():
    from oci_policy_analysis.application.core.common.policy_helpers import canonicalize_principal_key

    assert canonicalize_principal_key('GROUP-ID:ocid1.group.TestIdentifier') == 'group-id:ocid1.group.TestIdentifier'
    assert (
        calculate_principal_key('resource', None, 'bucket/CaseSensitiveObject')
        == 'resource:None/bucket/CaseSensitiveObject'
    )
