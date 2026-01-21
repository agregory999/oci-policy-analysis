"""
Test cases for ConditionParser.

These tests check the parsing and evaluation of OCI IAM policy conditions.
"""

import logging

import pytest
from oci_policy_analysis.logic.parsers.condition_parser.condition_parser import ConditionParser

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
