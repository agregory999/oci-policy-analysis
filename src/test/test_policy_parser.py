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
    'stmt',
    [
        # All combinations of quoted/unquoted domain/subject for dynamic-group
        "allow dynamic-group 'cloud-engineering-domain'/agregory-dg to {log_analytics_log_group_upload_logs} in compartment andrew.gregory",
        "allow dynamic-group 'cloud-engineering-domain'/'agregory-dg' to {log_analytics_log_group_upload_logs} in compartment andrew.gregory",
        "allow dynamic-group cloud-engineering-domain/'agregory-dg' to {log_analytics_log_group_upload_logs} in compartment andrew.gregory",
        'allow dynamic-group cloud-engineering-domain/agregory-dg to {log_analytics_log_group_upload_logs} in compartment andrew.gregory',
    ],
)
def test_policy_statements_mixed_quoted_dynamic_group(parser, stmt):
    results, errors = parser.parse(stmt)
    assert results is not None, f'Failed to parse: {stmt}'
    assert isinstance(results, list)
    assert len(results) > 0
    assert not errors, f"Parser returned errors for '{stmt}': {errors}"
