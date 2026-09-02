"""Coverage for complete policy supersession analysis."""

from types import SimpleNamespace

from oci_policy_analysis.application.core.analysis import SupersessionAnalyzer
from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine


def _statement(
    internal_id: str,
    path: str,
    permissions: list[str],
    *,
    conditions: str = '',
) -> dict:
    """Build a compact parsed statement fixture."""
    return {
        'internal_id': internal_id,
        'policy_name': f'Policy-{internal_id}',
        'statement_text': f'allow group Devs to read buckets in compartment {path}',
        'action': 'allow',
        'valid': True,
        'subject_type': 'group',
        'subject': [('Default', 'Devs')],
        'effective_path': path,
        'permission': permissions,
        'conditions': conditions,
    }


def test_finds_single_unconditional_ancestor_that_fully_covers_descendant() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('ancestor', 'ROOT/A', ['BUCKET_INSPECT', 'BUCKET_READ']),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_INSPECT']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    assert len(findings) == 1
    assert findings[0]['statement_internal_id'] == 'candidate'
    assert findings[0]['classification'] == 'Single Statement'
    assert findings[0]['evidence'][0]['internal_id'] == 'ancestor'


def test_unconditional_ancestor_supersedes_conditional_descendant_with_note() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('ancestor', 'ROOT/A', ['BUCKET_READ']),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ'], conditions="target.bucket.name = 'logs'"),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    assert len(findings) == 1
    assert 'where clause' in findings[0]['notes']


def test_conditional_ancestor_is_not_automatic_coverage_evidence() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('ancestor', 'ROOT/A', ['BUCKET_READ'], conditions="target.bucket.name = 'logs'"),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ']),
        ]
    )

    assert SupersessionAnalyzer().analyze(repo) == []


def test_does_not_combine_partial_permission_evidence_into_supersession() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('read', 'ROOT/A', ['BUCKET_READ']),
            _statement('inspect', 'ROOT/A', ['BUCKET_INSPECT']),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ', 'BUCKET_INSPECT']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    assert findings == []


def test_same_scope_unconditional_statement_supersedes_candidate() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('manage', 'ROOT/A', ['BUCKET_INSPECT', 'BUCKET_READ']),
            _statement('use', 'ROOT/A', ['BUCKET_INSPECT']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    finding = next(item for item in findings if item['statement_internal_id'] == 'use')
    assert finding['classification'] == 'Single Statement'
    assert finding['evidence'][0]['relationship'] == 'Same scope'


def test_retains_each_independently_complete_unconditional_evidence_statement() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('ancestor-one', 'ROOT/A', ['BUCKET_READ']),
            _statement('ancestor-two', 'ROOT/A', ['BUCKET_READ']),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    finding = next(item for item in findings if item['statement_internal_id'] == 'candidate')
    assert finding['classification'] == 'Multiple Complete Statements'
    assert {item['internal_id'] for item in finding['evidence']} == {'ancestor-one', 'ancestor-two'}


def test_partial_same_scope_overlap_is_not_shown_as_supersession_evidence() -> None:
    """A use grant is superseded by manage, but cannot supersede manage itself."""
    repo = SimpleNamespace(
        regular_statements=[
            _statement('tenancy-manage', 'ROOT', ['REPO_READ', 'REPO_USE', 'REPO_MANAGE']),
            _statement('compartment-manage', 'ROOT/Engineering', ['REPO_READ', 'REPO_USE', 'REPO_MANAGE']),
            _statement('compartment-use', 'ROOT/Engineering', ['REPO_READ', 'REPO_USE']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)
    by_candidate = {finding['statement_internal_id']: finding for finding in findings}

    assert set(by_candidate) == {'compartment-manage', 'compartment-use'}
    assert {item['internal_id'] for item in by_candidate['compartment-manage']['evidence']} == {'tenancy-manage'}
    assert {item['internal_id'] for item in by_candidate['compartment-use']['evidence']} == {
        'compartment-manage',
        'tenancy-manage',
    }


def test_conditional_coverage_marks_an_otherwise_complete_result_for_review() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('unconditional', 'ROOT/A', ['BUCKET_READ', 'BUCKET_INSPECT']),
            _statement('conditional', 'ROOT/A', ['BUCKET_INSPECT'], conditions="target.bucket.name = 'logs'"),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ', 'BUCKET_INSPECT']),
        ]
    )

    findings = SupersessionAnalyzer().analyze(repo)

    finding = next(item for item in findings if item['statement_internal_id'] == 'candidate')
    assert finding['classification'] == 'Single Statement (Review)'
    assert finding['evidence'][-1]['conditional'] is True


def test_default_intelligence_strategy_populates_supersession_overlay() -> None:
    repo = SimpleNamespace(
        regular_statements=[
            _statement('ancestor', 'ROOT/A', ['BUCKET_READ']),
            _statement('candidate', 'ROOT/A/B', ['BUCKET_READ']),
        ],
        compartments=[],
        dynamic_groups=[],
        groups=[{'domain_name': 'Default', 'group_name': 'Devs'}],
        defined_aliases=[],
        cross_tenancy_statements=[],
        defined_tag_namespace_keys={},
    )

    engine = PolicyIntelligenceEngine(repo)
    engine.run_all(enabled_strategy_ids=['supersession'])

    assert [finding['statement_internal_id'] for finding in engine.overlay['supersessions']] == ['candidate']
