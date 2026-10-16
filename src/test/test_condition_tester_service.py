"""Condition tester contracts and examples harvested from checked-in tests."""

import json
from pathlib import Path

import pytest

from oci_policy_analysis.application.services.condition_tester_service import ConditionTesterService

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'condition_tester_clauses.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['source'])
@pytest.mark.parametrize('context_mode', ['absent', 'null', 'supplied'])
def test_harvested_clause_structure_variables_and_formatting_preserve_evaluation(case, context_mode):
    service = ConditionTesterService()
    parsed = service.parse_clause(case['clause'])
    assert parsed['structure']['parse_status'] == case['status']
    assert parsed['variables'] == case['variables']
    if case['status'] != 'parsed':
        assert parsed['structure']['warnings']
        return
    assert parsed['structure']['atoms']
    assert {atom['left'] for atom in parsed['structure']['atoms']} <= set(parsed['variables'])
    values = (
        {}
        if context_mode == 'absent'
        else dict.fromkeys(parsed['variables'], None if context_mode == 'null' else 'fixture-value')
    )
    formatted = service.format_clause(parsed['clause'])
    again = service.parse_clause(formatted)
    assert again['structure']['parse_status'] == 'parsed'
    assert again['variables'] == parsed['variables']
    original = service.evaluate(parsed['clause'], values)
    pretty = service.evaluate(formatted, values)
    assert original.granted == pretty.granted
    assert original.log  # Every parsed predicate is accounted for, even in nested branches.
    assert [entry['result'] for entry in original.log] == [entry['result'] for entry in pretty.log]
    assert not any(entry.get('type') == 'Exception' for entry in original.log)


@pytest.mark.parametrize(
    'clause,variables,expected',
    [
        ('request.a = target.b', {'request.a': 'same', 'target.b': 'same'}, True),
        ('request.a = target.b', {'request.a': 'same', 'target.b': 'other'}, False),
        ('request.a != target.b', {'request.a': 'same', 'target.b': 'other'}, True),
        ('request.a != target.b', {'request.a': 'same'}, False),
        ('request.a != target.b', {'request.a': 'same', 'target.b': None}, False),
        ('request.a != target.b', {'request.a': 'same', 'target.b': ''}, False),
        ('request.a != target.b', {'target.b': 'same'}, False),
        ('!request.a', {}, True),
        ('!request.a', {'request.a': None}, True),
        ('!request.a', {'request.a': ''}, True),
        ('!request.a', {'request.a': 'false'}, False),
        ("request.a != 'x'", {}, False),
        ('request.a in (target.b, target.c)', {'request.a': 'match', 'target.b': 'other', 'target.c': 'match'}, True),
        ('request.a not in (target.b)', {'request.a': 'match', 'target.b': 'other'}, True),
        ('request.a not in (target.b)', {'request.a': 'match'}, False),
        ("all { request.a = 'x', any { !target.b, target.b = 'z' } }", {'request.a': 'x'}, True),
        ("all { request.a = 'x', any { !target.b, target.b = 'z' } }", {'request.a': 'x', 'target.b': 'q'}, False),
        ("request.a in ('x', /pre*/)", {'request.a': 'prefix'}, True),
        ("request.a not in ('x', /pre*/)", {'request.a': 'prefix'}, False),
        ("request.a ! = 'x'", {'request.a': 'y'}, True),
        ("request.utc-timestamp after '2026-01-01T00:00:00Z'", {'request.utc-timestamp': '2026-01-02T00:00:00Z'}, True),
        (
            "request.utc-timestamp.time-of-day between '09:00:00Z' and '17:00:00Z'",
            {'request.utc-timestamp.time-of-day': '12:00:00Z'},
            True,
        ),
    ],
)
def test_condition_semantics_have_explicit_expected_results(clause, variables, expected):
    service = ConditionTesterService()
    assert service.parse_clause(clause)['structure']['parse_status'] == 'parsed'
    assert service.evaluate(clause, variables).granted is expected


def test_parse_handoff_discovers_rhs_and_preserves_quoted_literals():
    service = ConditionTesterService()
    parsed = service.parse_clause(
        "Allow group 'where' to read buckets in tenancy where all { request.a = target.b, request.c = 'target.literal', !request.d }"
    )
    assert parsed['variables'] == ['request.a', 'request.c', 'request.d', 'target.b']
    assert parsed['structure']['atoms'][-1]['operator'] == '!'
    assert service.parse_clause('where request.a = target.b')['variables'] == ['request.a', 'target.b']


@pytest.mark.parametrize('text', ['', "request.a = 'x' @", "request.a = 'x' trailing", "all { request.a = 'x'"])
def test_invalid_or_absent_clause_does_not_generate_partial_inputs(text):
    parsed = ConditionTesterService().parse_clause(text)
    assert parsed['structure']['parse_status'] != 'parsed'
    assert parsed['variables'] == []
