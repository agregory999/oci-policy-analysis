"""
Test cases for ConditionParser.

These tests check the parsing and evaluation of OCI IAM policy conditions.
"""

import logging

import pytest
from oci_policy_analysis.logic.parsers.condition_parser.condition_parser import ConditionParser
from oci_policy_analysis.logic.parsers.condition_parser.TagConditionCollector import (
    collect_tag_conditions,
)

# --- Ensure logs are output to console during tests
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('oci-policy-analysis').setLevel(logging.DEBUG)
logging.getLogger('oci-policy-analysis.where_clause_evaluator').setLevel(logging.DEBUG)


# === Custom tests for 'in' operator with patterns ===
# @pytest.mark.parametrize(
#     'statement,simvars,expected',
#     [
#         (
#             "request.networkSource.name in ('MyOfficeNetwork', 'GuestNetwork')",
#             {'request.networkSource.name': 'GuestNetwork'},
#             True,  # Should match pattern in IN-list
#         ),
#         (
#             "request.networkSource.name in ('MyOfficeNetwork', 'XNet')",
#             {'request.networkSource.name': 'MyOfficeNetwork'},
#             True,  # Should match pattern in IN-list
#         ),
#         (
#             "request.networkSource.name in ('Abc', 'Def')",
#             {'request.networkSource.name': 'GuestNetwork'},
#             False,  # Should not match any entry
#         ),
#     ],
# )
# def test_in_operator_with_patterns(statement, simvars, expected):
#     parser = ConditionParser(simvars)
#     result = parser.parse(statement)
#     # Assume parse returns {'result': bool or 'GRANTED'/'DENIED', 'log': ...}
#     if isinstance(result['result'], str):
#         # Convert GRANTED/DENIED to bool
#         is_true = result['result'] in ('GRANTED', True)
#     else:
#         is_true = bool(result['result'])
#     assert is_true == expected


COND_STATEMENTS = [
    "request.networkSource.name = 'MyOfficeNetwork'",
    "request.networkSource.name = 'HomeNetwork'",
    "target.tag.Operations.Project = 'Alpha'",
    "request.isLoggedIn = 'true'",
    "all {request.networkSource.name = 'MyOfficeNetwork', target.tag.Operations.Project = 'Alpha'}",
    "all {request.networkSource.name = 'MyOfficeNetwork', target.tag.Operations.Project = 'Beta'}",
    "any {request.networkSource.name = 'MyOfficeNetwork', target.tag.Operations.Project = 'Beta'}",
    "all {request.networkSource.name = 'MyOfficeNetwork', any {target.tag.Operations.Project = 'Beta', target.compartment.name = 'Production'}}",
    "all {request.networkSource.name = 'MyOfficeNetwork', all {request.principal.type = 'fnfunc', request.principal.id = 'ocid.xx.yy.zzz'}}",
    "request.networkSource.name != 'IllegalNetwork'",
    "request.networkSource.name in ('OfficeNetwork','GuestNetwork')'",
    "request.networkSource.name in ('OfficeNetwork2','MyOfficeNetwork2','GuestNetwork')",
    "all {request.utc-timestamp after '2025-12-11T00:00:00Z', request.utc-timestamp before '2025-12-12T00:00:00Z'}",
    "any {request.utc-timestamp.day-of-week in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')}",
]

SIM_VARS = {
    'request.networkSource.name': 'OfficeNetwork',
    'request.utc-timestamp': '2025-12-11T14:00:00Z',
    'target.tag.Operations.Project': 'Alpha',
    'target.compartment.name': 'Production',
    'request.principal.type': 'fnfunc',
    'request.principal.id': 'ocid.xx.yy.zzz',
    'request.utc-timestamp.time-of-day': '20:00:00Z',
    'request.utc-timestamp.day-of-week': 'wednesday',
    'request.isLoggedIn': 'true',
}


@pytest.mark.parametrize('statement', COND_STATEMENTS)
def test_condition_parser_print_results(statement):
    parser = ConditionParser(SIM_VARS)
    result = parser.parse(statement)
    print(f"Parsed condition: {result['condition']}")
    print(f"Access Result: {result['result']}")
    print('  --- Comparison Log ---')
    for entry in result['log']:
        res = 'PASS' if entry.get('result') else 'FAIL'
        sim = entry.get('sim_value')
        op = entry.get('operator')
        exp = entry.get('expected')
        var = entry.get('variable')
        print(f'    [{res}] {sim} {op} {exp} (variable: {var})')
    assert result['result'] in ('GRANTED', 'DENIED', 'SYNTAX ERROR')


@pytest.mark.parametrize(
    'statement, simvars, expected',
    [
        # --- Pattern list with slashes ---
        # Value matches first pattern /*sample/ (e.g., contains "sample")
        (
            'request.principal.group.tag.MyTagNamespace.MyTag in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'mysamplevalue'},
            False,
        ),
        # Value matches second pattern /sample1*/
        (
            'request.principal.group.tag.MyTagNamespace.MyTag in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'sample123'},
            True,
        ),
        # Value matches neither pattern
        (
            'request.principal.group.tag.MyTagNamespace.MyTag in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'other'},
            False,
        ),
        # NOT IN with patterns: invert logic
        (
            'request.principal.group.tag.MyTagNamespace.MyTag not in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'mysamplevalue'},
            True,
        ),
        (
            'request.principal.group.tag.MyTagNamespace.MyTag not in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'other'},
            True,
        ),
        (
            'request.principal.group.tag.MyTagNamespace.MyTag not in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'mysample'},
            False,
        ),
        (
            'request.principal.group.tag.MyTagNamespace.MyTag not in (/*sample/, /sample1*/)',
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'sample123'},
            False,
        ),
        # --- Simple strings / '*' wildcard (no slashes) ---
        # Interpret '*' as wildcard: sample* should match sample123
        (
            "request.principal.group.tag.MyTagNamespace.MyTag in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'sample123'},
            True,
        ),
        (
            "request.principal.group.tag.MyTagNamespace.MyTag in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'sample'},
            True,
        ),  # No match for sample* or other
        (
            "request.principal.group.tag.MyTagNamespace.MyTag in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'foo'},
            False,
        ),
        # NOT IN with '*' wildcard
        (
            "request.principal.group.tag.MyTagNamespace.MyTag not in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'sample123'},
            False,
        ),
        (
            "request.principal.group.tag.MyTagNamespace.MyTag not in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'other'},
            False,
        ),
        (
            "request.principal.group.tag.MyTagNamespace.MyTag not in ('sample*', 'other')",
            {'request.principal.group.tag.MyTagNamespace.MyTag': 'foo'},
            True,
        ),
    ],
)
def test_tag_based_in_not_in_with_patterns_and_wildcards(statement, simvars, expected):
    parser = ConditionParser(simvars)
    result = parser.parse(statement)
    # parse() returns 'GRANTED' / 'DENIED' / 'SYNTAX ERROR'
    is_true = result['result'] == 'GRANTED'
    assert is_true == expected


# === Tests for TagConditionCollector structure + tag-only extraction ===


@pytest.mark.parametrize(
    'condition_str, expected_structure, expected_tag_ids',
    [
        # Simple LHS tag comparison should yield a single tc1 and structure "tc1"
        (
            "target.resource.compartment.tag.Oracle-Tags.AllowCompartmentCreation = 'true'",
            'tc1',
            ['tc1'],
        ),
        # Tag-based clause inside ALL/ANY – structure should show tcN for the tag leaf
        (
            "all { target.resource.compartment.tag.Oracle-Tags.AllowCompartmentCreation = 'true',\n"
            "      any { request.permission = 'BUCKET_DELETE',\n"
            "            request.permission = 'PAR_MANAGE',\n"
            "            request.permission = 'RETENTION_RULE_LOCK',\n"
            "            request.permission = 'RETENTION_RULE_MANAGE' } }",
            'ALL { tc1, ANY { c2, c3, c4, c5 } }',
            ['tc1'],
        ),
    ],
)
def test_collect_tag_conditions_structure_and_ids(condition_str, expected_structure, expected_tag_ids):
    """Verify TagConditionCollector structure strings and tag IDs.

    - The structure string should use tcN identifiers for tag-based
      leaves and cN for non-tag conditions.
    - The returned TagCondition list should only contain tcN IDs.
    """

    structure, conditions = collect_tag_conditions(condition_str)

    # Normalize whitespace to make tests resilient to minor spacing
    norm_actual = ' '.join(structure.split())
    norm_expected = ' '.join(expected_structure.split())
    assert norm_actual == norm_expected

    ids = [c.condition_id for c in conditions]
    assert ids == expected_tag_ids
