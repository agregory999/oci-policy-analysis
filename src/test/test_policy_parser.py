import pytest
from oci_policy_analysis.logic.policy_statement_normalizer import PolicyStatementParser


@pytest.fixture
def parser():
    return PolicyStatementParser()


def test_policy_statement_with_after_before(parser):
    sample_statement = (
        'allow group policyanalysisusers to read objects in tenancy '
        "where all {request.utc-timestamp after '2025-12-11t00:00:00z', request.utc-timestamp before '2026-01-12t00:00:00z'}"
    )
    results, errors = parser.parse(sample_statement)
    assert results is not None, 'Parser returned None for valid input.'
    assert isinstance(results, list)
    assert len(results) > 0, 'No policy statements parsed.'
    assert not errors, f'Parser returned errors: {errors}'
    statement = results[0]
    assert 'condition' in statement
    where_clause = statement.get('condition', '')
    assert 'after' in where_clause.lower()
    assert 'before' in where_clause.lower()


@pytest.mark.parametrize(
    'stmt',
    [
        'allow group Admins to manage instances in tenancy',
        'deny group Blocked to read all-resources in tenancy',
        "deny dynamic-group MyDG to use object-family in compartment Foo where request.user.id = 'xyz'",
        "admit group non-default/sales to read buckets in tenancy where request.network.source = '0.0.0.0/0'",
    ],
)
def test_basic_policy_statements(parser, stmt):
    results, errors = parser.parse(stmt)
    assert results is not None, f'Failed to parse: {stmt}'
    assert isinstance(results, list)
    assert len(results) > 0
    assert not errors, f"Parser returned errors for '{stmt}': {errors}"


@pytest.mark.parametrize(
    'stmt',
    [
        'endorse dynamic-group DGS to associate instance in any-tenancy',
        'define group G1 as ocid1.xx.yy.zzz',
        "define group 'svcops' as ocid1.xx.yy.zzz",
        'define tenancy t1 as ocid1.tenancy.yy.zzz',
        'deny admit dynamic-group DG1 of tenancy Foo to use buckets in tenancy',
        'deny endorse group G1 to read all-resources in tenancy Bar',
        'endorse group DatabaseToolsConnectionManagers to associate database-tools-connections in tenancy ConnectionTenancy with database-tools-private-endpoints in tenancy PrivateEndpointTenancy',
        'deny endorse group DatabaseToolsConnectionManagers to associate database-tools-connections in tenancy ConnectionTenancy with database-tools-private-endpoints in tenancy PrivateEndpointTenancy',
    ],
)
def test_complex_policy_statements(parser, stmt):
    results, errors = parser.parse(stmt)
    assert results is not None, f'Failed to parse: {stmt}'
    assert isinstance(results, list)
    assert len(results) > 0
    assert not errors, f"Parser returned errors for '{stmt}': {errors}"


@pytest.mark.parametrize(
    'stmt',
    [
        # Fails due to quoted compartment name
        "allow any-user to read secret-family in compartment 'jason.zormeier' where all {target.secret.id = 'ocid1.vaultsecret.oc1.phx.amaaaaaabv6267iahq6a2abc66lvjgodpunhas2z52uf6nub5xvgjmoawr2q',request.principal.type = 'dbmgmtmanageddatabase'}",
    ],
)
def test_policy_statements_with_quoted_compartments(parser, stmt):
    results, errors = parser.parse(stmt)
    assert results is not None, f'Failed to parse: {stmt}'
    assert isinstance(results, list)
    assert len(results) > 0
    assert not errors, f"Parser returned errors for '{stmt}': {errors}"


@pytest.mark.parametrize(
    'statement,expected_location_type,expected_location',
    [
        (
            "allow any-user to manage objects in compartment id ocid1.compartment.oc1..aaaaaaaamaywlaznovmvdwk3uqx2sedfavssagba5cxufe6wyllqgwzcq43a where all {request.principal.type = 'serviceconnector', target.bucket.name = 'hammer_reports', request.principal.compartment.id = 'ocid1.compartment.oc1..aaaaaaaapfv3jno5r6qz6oeszde4uh4ksfox66zkj4i3crnxdy752beciq2q'}",
            'compartment id',
            'ocid1.compartment.oc1..aaaaaaaamaywlaznovmvdwk3uqx2sedfavssagba5cxufe6wyllqgwzcq43a',
        ),
    ],
)
def test_policy_statement_compartment_id_location(parser, statement, expected_location_type, expected_location):
    results, errors = parser.parse(statement)
    assert results is not None, 'Parser returned None for valid input.'
    assert not errors, f'Parser returned errors: {errors}'
    assert isinstance(results, list)
    assert len(results) > 0
    statement_data = results[0]
    # Try common field names: location_type/location/resource_scope/etc.
    assert (
        'location_type' in statement_data or 'resource_scope' in statement_data
    ), f'Parsed statement missing location_type/resource_scope field: {statement_data!r}'
    # Accept different naming for the field, try both
    location_type = statement_data.get('location_type') or statement_data.get('resource_scope')
    assert (
        location_type and expected_location_type in location_type
    ), f"Expected location_type/resource_scope '{expected_location_type}', got '{location_type}'"
    # Now check the specific location/ocid is present in the parsed fields somewhere (location or similar field)
    found_location = (
        statement_data.get('location')
        or statement_data.get('location_id')
        or statement_data.get('resource_scope_id')
        or ''
    )
    assert expected_location in str(
        found_location
    ), f"Expected compartment OCID '{expected_location}' in result, got '{found_location}'"


@pytest.mark.parametrize(
    'statement,expected_subject_type,expected_subject',
    [
        # OCID group (single)
        (
            'allow group id ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq to inspect instances in tenancy',
            'group',
            ['ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq'],
        ),
        # OCID group (multiple)
        (
            'allow group id ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq, id ocid1.group.oc1..aaaaaaaaibpusflrktrlqmoojx5qrgyh3vtpwwzssakzijrbvpspkuynyv7q to inspect instances in tenancy',
            'group',
            [
                'ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq',
                'ocid1.group.oc1..aaaaaaaaibpusflrktrlqmoojx5qrgyh3vtpwwzssakzijrbvpspkuynyv7q',
            ],
        ),
        # OCID dynamic-group (single)
        (
            'allow dynamic-group id ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq to inspect instances in tenancy',
            'dynamic-group',
            ['ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq'],
        ),
        # any-group
        ('allow any-group to read buckets in tenancy', 'any-group', ['any-group']),
        # Mixed OCID/named (should return as text fallback)
        (
            'allow group id ocid1.bad.ocid, id ocid1.group.oc1..aaaaaaaaibpusflrktrlqmoojx5qrgyh3vtpwwzssakzijrbvpspkuynyv7q to inspect instances in tenancy',
            'group',
            ['ocid1.bad.ocid', 'ocid1.group.oc1..aaaaaaaaibpusflrktrlqmoojx5qrgyh3vtpwwzssakzijrbvpspkuynyv7q'],
        ),
    ],
)
def test_any_group_and_ocid_subjects(parser, statement, expected_subject_type, expected_subject):
    results, errors = parser.parse(statement)
    assert not errors, f'Unexpected parse errors: {errors!r}'
    assert isinstance(results, list) and len(results) > 0
    result = results[0]
    assert result.get('subject_type') == expected_subject_type
    subjects = result.get('subject')
    # If full id-based group/dynamic-group, expect list of ocid strings; if any-group, expect ['any-group'].
    # If mixed, may get as fallback names/text depending on parsing.
    if expected_subject_type in ('group', 'dynamic-group') and all(x.startswith('ocid1.') for x in expected_subject):
        assert subjects == expected_subject
    elif expected_subject_type == 'any-group':
        assert subjects == ['any-group']
    else:
        # For mixed cases, check that all expected parts are present in subject
        for s in expected_subject:
            assert s in subjects
