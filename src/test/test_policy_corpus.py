"""Tests for valid-only policy corpus compilation."""

from types import SimpleNamespace

from oci_policy_analysis.application.core.policy_corpus import (
    CorpusProvenance,
    PolicyCorpus,
    PolicyCorpusBuilder,
    PolicyCorpusFact,
    permissions_report_projection,
)


def test_corpus_expands_principal_permission_facts_and_preserves_provenance():
    repo = SimpleNamespace(
        regular_statements=[
            {
                'internal_id': 'statement-1',
                'valid': True,
                'principal_keys': ['group:Default/Operators', 'any-user:None/any-user'],
                'effective_path': 'ROOT/Production',
                'permission': ['bucket_read', 'object_get'],
                'action': 'allow',
                'where_clause': "request.region = 'us-ashburn-1'",
                'policy_name': 'OperatorsPolicy',
                'policy_ocid': 'ocid1.policy.oc1..example',
                'statement_text': 'allow group Operators to read buckets in compartment Production',
            }
        ]
    )

    corpus = PolicyCorpusBuilder().build(repo)

    assert len(corpus.facts) == 4
    assert {(fact.principal_key, fact.permission) for fact in corpus.facts} == {
        ('group:default/operators', 'BUCKET_READ'),
        ('group:default/operators', 'OBJECT_GET'),
        ('any-user:none/any-user', 'BUCKET_READ'),
        ('any-user:none/any-user', 'OBJECT_GET'),
    }
    assert all(fact.conditional for fact in corpus.facts)
    assert all(fact.provenance.statement_id == 'statement-1' for fact in corpus.facts)
    assert corpus.to_dict()['facts'][0]['provenance']['statement_id'] == 'statement-1'


def test_corpus_excludes_invalid_or_non_evaluable_source_statements():
    repo = SimpleNamespace(
        regular_statements=[
            {'internal_id': 'invalid', 'valid': False},
            {
                'internal_id': 'no-path',
                'valid': True,
                'principal_keys': ['group:Default/Operators'],
                'permission': ['BUCKET_READ'],
                'action': 'allow',
            },
        ]
    )

    corpus = PolicyCorpusBuilder().build(repo)

    assert corpus.facts == ()
    assert [(item.statement_id, item.reason) for item in corpus.exclusions] == [
        ('invalid', 'statement is not valid'),
        ('no-path', 'effective path is unavailable'),
    ]
    assert corpus.exclusions[0].category == 'invalid_statement'
    assert corpus.exclusions[0].policy_name == ''


def test_corpus_tracks_inherited_facts_and_feeds_permissions_projection():
    repo = SimpleNamespace(
        regular_statements=[
            {
                'internal_id': 'root-grant',
                'valid': True,
                'principal_keys': ['group:Default/Operators'],
                'effective_path': 'ROOT',
                'permission': ['BUCKET_READ'],
                'action': 'allow',
                'policy_name': 'RootOperators',
                'statement_text': 'allow group Operators to read buckets in tenancy',
            }
        ],
        compartments=[
            {'hierarchy_path': 'ROOT'},
            {'hierarchy_path': 'ROOT/Production'},
        ],
    )

    corpus = PolicyCorpusBuilder().build(repo)
    projection = permissions_report_projection(corpus)

    assert len(corpus.facts) == 1
    assert [(fact.effective_path, fact.inherited_from) for fact in corpus.effective_facts] == [
        ('ROOT', ''),
        ('ROOT/Production', 'ROOT'),
    ]
    assert projection['report']['ROOT']['group:default/operators']['allow'] == ['BUCKET_READ']
    inherited_rows = [row for row in projection['grant_rows'] if row['effective_path'] == 'ROOT/Production']
    assert len(inherited_rows) == 1
    assert inherited_rows[0]['inherited'] is True
    assert inherited_rows[0]['inherited_from'] == 'ROOT'


def test_large_corpus_inspection_returns_bounded_pages() -> None:
    provenance = CorpusProvenance(
        'Policy', 'ocid1.policy.test', 'statement-1', 'allow group X to read buckets in tenancy'
    )
    facts = tuple(
        PolicyCorpusFact('group:X', 'ROOT', 'ROOT', f'PERMISSION_{index}', 'allow', '', provenance)
        for index in range(1200)
    )
    corpus = PolicyCorpus(schema_version=1, built_at='now', facts=facts, effective_facts=facts)

    first = corpus.inspect_page('effective_facts')
    last = corpus.inspect_page('effective_facts', page=11)
    matching = corpus.inspect_page('facts', query='PERMISSION_1199')

    assert first['total'] == 1200
    assert len(first['records']) == len(last['records']) == 100
    assert first['has_more'] is True
    assert last['has_more'] is False
    assert first['records'][0]['permission'] == 'PERMISSION_0'
    assert last['records'][-1]['permission'] == 'PERMISSION_1199'
    assert [row['permission'] for row in matching['records']] == ['PERMISSION_1199']
