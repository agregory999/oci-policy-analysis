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
    'statement,expected_subject_type,expected_subject,expected_location_type,expected_location',
    [
        ('allow group Admins to manage instances in tenancy', 'group', [('default', 'Admins')], 'tenancy', 'tenancy'),
        (
            'allow group Admins1, Admins2 to manage instances in tenancy',
            'group',
            [('default', 'Admins1'), ('default', 'Admins2')],
            'tenancy',
            'tenancy',
        ),
        (
            "allow group 'Default'/'Admins' to manage instances in tenancy",
            'group',
            [('Default', 'Admins')],
            'tenancy',
            'tenancy',
        ),
        (
            "allow group 'D2'/'Admins', Admins2 to manage instances in tenancy",
            'group',
            [('D2', 'Admins'), ('default', 'Admins2')],
            'tenancy',
            'tenancy',
        ),
        (
            'deny group Blocked to read all-resources in compartment MyComp',
            'group',
            [('default', 'Blocked')],
            'compartment',
            'MyComp',
        ),
        (
            "deny dynamic-group MyDG to use object-family in compartment Foo where request.user.id = 'xyz'",
            'dynamic-group',
            [('default', 'MyDG')],
            'compartment',
            'Foo',
        ),
        ('allow any-group to read buckets in tenancy', 'any-group', ['any-group'], 'tenancy', 'tenancy'),
        # Add more as needed for real-world coverage
    ],
)
def test_policy_subject_and_location_fields(
    parser, statement, expected_subject_type, expected_subject, expected_location_type, expected_location
):
    results, errors = parser.parse(statement)
    assert not errors, f'Errors: {errors} for {statement}'
    assert isinstance(results, list) and len(results) > 0
    result = results[0]
    assert (
        result.get('subject_type') == expected_subject_type
    ), f"Expected subject_type '{expected_subject_type}', got '{result.get('subject_type')}' for: {statement}"
    assert (
        result.get('subject') == expected_subject
    ), f"Expected subject {expected_subject}, got {result.get('subject')} for: {statement}"
    lt = result.get('location_type')
    loc = result.get('location')
    assert (
        lt == expected_location_type
    ), f"Expected location_type '{expected_location_type}', got '{lt}' for: {statement}"
    assert loc == expected_location, f"Expected location '{expected_location}', got '{loc}' for: {statement}"


@pytest.mark.parametrize(
    'statement,expected_subject_type,expected_subject',
    [
        # Single group id
        (
            'allow group id ocid1.group.oc1..aaaaaaaamv7bmi3t6zg5wf4labjg4izs4pdf5il3q3d7hecdauuypizqpd4a to inspect instances in tenancy',
            'group-id',
            [(None, 'ocid1.group.oc1..aaaaaaaamv7bmi3t6zg5wf4labjg4izs4pdf5il3q3d7hecdauuypizqpd4a')],
        ),
        # Single dynamic-group id
        (
            'allow dynamic-group id ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq to inspect instances in tenancy',
            'dynamic-group-id',
            [(None, 'ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq')],
        ),
        # Multiple dynamic-group ids in a comma-separated list
        (
            'allow dynamic-group id ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq, id ocid1.dynamicgroup.oc1..aaaaaaaakogqqbmqbjn3fqal5szls3kinmr3lvrcecucqyrptvvmp3gbhs4a to inspect instances in tenancy',
            'dynamic-group-id',
            [
                (None, 'ocid1.dynamicgroup.oc1..aaaaaaaaql2cpeiqddwfd4a5uinrqawuxuubzftrekicjzdahebl5rtfpcvq'),
                (None, 'ocid1.dynamicgroup.oc1..aaaaaaaakogqqbmqbjn3fqal5szls3kinmr3lvrcecucqyrptvvmp3gbhs4a'),
            ],
        ),
        # Multiple group ids in a comma-separated list
        (
            'allow group id ocid1.group.oc1..aaaaa11111111111111111111111111111, id ocid1.group.oc1..bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb to manage buckets in tenancy',
            'group-id',
            [
                (None, 'ocid1.group.oc1..aaaaa11111111111111111111111111111'),
                (None, 'ocid1.group.oc1..bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'),
            ],
        ),
    ],
)
def test_policy_subject_id_variants(parser, statement, expected_subject_type, expected_subject):
    """
    Test that policies with subject using group/dynamic-group by id (single and list) provide correct subject_type and a list of (None, OCID) tuples.
    """
    results, errors = parser.parse(statement)
    assert not errors, f'Errors: {errors} for {statement}'
    assert isinstance(results, list) and len(results) > 0
    result = results[0]
    assert (
        result.get('subject_type') == expected_subject_type
    ), f"Expected subject_type '{expected_subject_type}', got '{result.get('subject_type')}'"
    subj = result.get('subject')
    assert isinstance(subj, list), f'Subject is not a list: {subj!r}'
    assert subj == expected_subject, f'Expected subject {expected_subject}, got {subj}'


def test_policy_statement_with_pattern_list(parser):
    statement = (
        "allow group 'PolicyAnalysisUsers' to use bastion in compartment LZ1-Top:application-cmp "
        "where request.principal.group.tag.aaa.aaa IN ('c','d',/e*/)"
    )
    results, errors = parser.parse(statement)
    assert results is not None, 'Parser returned None for valid input.'
    assert isinstance(results, list) and len(results) > 0
    assert not errors, f'Parser returned errors: {errors}'


def test_policy_statement_with_tag_pattern_and_trailing_comment(parser):
    statement = (
        "allow group 'Default'/'Administrators' to manage all-resources in tenancy "
        'where request.principal.group.tag.MyTagNamespace.MyTag !=/*sample/ //Testing tags'
    )
    results, errors = parser.parse(statement)
    assert results is not None, 'Parser returned None for valid input.'
    assert isinstance(results, list) and len(results) > 0
    assert not errors, f'Parser returned errors: {errors}'

    parsed = results[0]
    assert parsed.get('condition'), f'Expected a parsed condition but got: {parsed}'
    assert 'request.principal.group.tag.MyTagNamespace.MyTag' in parsed.get('condition', '')


def test_policy_statement_with_not_in_pattern_list(parser):
    statement = (
        'Allow dynamic-group Federated/container-instances to read repos '
        'in compartment lz1-top:application-cmp '
        "where request.principal.group.tag.aaa.aaa NOT IN ('c','d',/e*/)"
    )
    results, errors = parser.parse(statement)
    assert results is not None, 'Parser returned None for valid input.'
    assert isinstance(results, list) and len(results) > 0
    assert not errors, f'Parser returned errors: {errors}'

    parsed = results[0]
    condition = parsed.get('condition', '')
    assert 'NOT IN' in condition.upper()
