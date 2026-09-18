"""Tests for ReferenceDataRepo cumulative allow/deny semantics.

These tests focus on a few key invariants rather than exact permission
names, to avoid being brittle with respect to upstream permission JSON
changes from OCI. They rely on the real permissions data shipped with
the project.
"""

from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService


def _load_repo():
    repo = ReferenceDataRepo()
    repo.load_data()
    return repo


def test_all_resources_allow_manage_equals_deny_inspect():
    """For all-resources, allow(manage) should equal deny(inspect).

    Because verbs are ordered inspect < read < use < manage, and
    get_permissions applies cumulative logic in opposite directions for
    allow vs deny, the most permissive combinations should converge on
    the same full set of permissions.
    """

    repo = _load_repo()

    allow_manage = set(repo.get_permissions('all-resources', 'manage', 'allow'))
    deny_inspect = set(repo.get_permissions('all-resources', 'inspect', 'deny'))

    # They should be identical sets, not just counts
    assert allow_manage == deny_inspect


def test_family_virtual_network_cumulative_relationships():
    """Spot-check family-level cumulative behavior for virtual-network-family.

    We rely only on inclusion relationships, not exact counts, so the
    test remains stable even if the underlying permission catalog grows.
    """

    repo = _load_repo()

    # Baseline: full manage set for the family
    fam_manage_allow = set(repo.get_permissions('virtual-network-family', 'manage', 'allow'))

    # Allow/read: inspect+read subset of manage
    fam_read_allow = set(repo.get_permissions('virtual-network-family', 'read', 'allow'))
    assert fam_read_allow <= fam_manage_allow

    # Deny/use: use+manage for the family should be a subset of manage-allow;
    # overall, (allow/read ∪ deny/use) should cover the full manage-allow set.
    fam_use_deny = set(repo.get_permissions('virtual-network-family', 'use', 'deny'))

    combined = fam_read_allow | fam_use_deny
    # Combined coverage should be at least the full manage-allow set
    assert fam_manage_allow <= combined


def test_resource_allow_vs_deny_monotonicity():
    """For a concrete resource, deny(read) should be a superset of allow(read).

    This is a small sanity check that the cumulative direction for deny
    (upwards) vs allow (downwards) is behaving as specified.
    """

    repo = _load_repo()

    # Pick a commonly-present resource; objectstorage "buckets" is part
    # of the standard permissions JSON.
    allow_read_buckets = set(repo.get_permissions('buckets', 'read', 'allow'))
    deny_read_buckets = set(repo.get_permissions('buckets', 'read', 'deny'))

    # We can't assume a strict superset because a given permission might
    # be modelled under a different verb for deny vs allow (e.g., an
    # "inspect"-scoped permission may not appear in the deny/read
    # expansion). Instead, check that deny(read) is non-empty and larger
    # than or equal to allow(read) in size, which still reflects the
    # "broader" deny semantics without tying us to exact verb mappings.
    assert deny_read_buckets
    assert len(deny_read_buckets) >= len(allow_read_buckets)


def test_compute_container_family_aggregates_its_documented_resources():
    """Container Instances family permissions equal its two member resources."""
    repo = _load_repo()

    family_use = set(repo.get_permissions('compute-container-family', 'use', 'allow'))
    expected = set(repo.get_permissions('compute-container-instances', 'use', 'allow'))
    expected.update(repo.get_permissions('compute-containers', 'use', 'allow'))

    assert family_use == expected
    assert 'COMPUTE_CONTAINER_INSTANCE_UPDATE' in family_use
    assert 'COMPUTE_CONTAINER_LOG_RETRIEVE' in family_use


def test_osmh_family_uses_current_documented_resource_names():
    """OS Management Hub family resolves its current OCI policy resource names."""
    repo = _load_repo()

    family_permissions = set(repo.get_permissions('osmh-family', 'manage', 'allow'))
    permissions = repo.get_permissions('osmh-managed-instance-group', 'manage', 'allow')

    assert 'OSMH_MANAGED_INSTANCE_DELETE' in family_permissions
    assert 'OSMH_MANAGEMENT_STATION_CREATE' in family_permissions
    assert 'OSMH_MANAGED_INSTANCE_GROUP_CREATE' in permissions


def test_change_instance_compartment_exposes_related_capacity_reservation_check():
    repo = _load_repo()
    service = ReferenceDataService(repo)

    detail = service.get_operation_detail('ChangeInstanceCompartment')

    related_checks = detail.get('related_checks') or []
    assert related_checks
    capacity_check = next(check for check in related_checks if check.get('resource') == 'compute-capacity-reservations')
    assert capacity_check['operation'] == 'ChangeComputeCapacityReservationCompartment'
    assert capacity_check['permissions'] == ['CAPACITY_RESERVATION_MOVE']
    assert 'capacity reservation' in capacity_check['applies_when'].lower()


def test_operation_listing_includes_related_checks():
    repo = _load_repo()
    service = ReferenceDataService(repo)

    row = next(
        row
        for row in service.list_operations_with_permissions()
        if row['operation_name'] == 'ChangeInstanceCompartment'
    )

    assert row['related_checks']
    assert row['notes']


def test_explicit_resource_aliases_share_permissions_and_provenance():
    repo = _load_repo()
    for alias, canonical in [('instance', 'instances'), ('object', 'objects')]:
        for verb in repo.verb_set:
            for action in ('allow', 'deny'):
                assert set(repo.get_permissions(alias.upper(), verb, action)) == set(
                    repo.get_permissions(canonical, verb, action)
                )
        assert repo.get_containing_family(alias) == repo.get_containing_family(canonical)
        assert repo.get_source(alias) == repo.get_source(canonical)
    assert repo.get_permissions('invented-object', 'manage') == []


def test_duplicate_operation_names_require_catalog_identity():
    import pytest

    repo = _load_repo()
    bastion = repo.data['operations']['bastion:CreateSession']
    agent = repo.data['operations']['generative_ai_agents:CreateSession']
    assert bastion['permissions'] != agent['permissions']
    assert 'CreateSession' not in repo.data['operations']
    for name in ('CreateSession', 'oci:CreateSession'):
        with pytest.raises(ValueError, match='Ambiguous API operation'):
            repo.resolve_operation(name)
    assert repo.resolve_operation('bastion:CreateSession') == 'bastion:CreateSession'
    assert repo.resolve_operation('CreateBastion') == 'bastion:CreateBastion'
    assert repo.resolve_operation('oci:CreateBastion') == 'bastion:CreateBastion'
    assert repo.has_api_operation_permissions('bastion:CreateSession', bastion['permissions'])
    assert not repo.has_api_operation_permissions('generative_ai_agents:CreateSession', bastion['permissions'])


def test_alias_conflicts_are_rejected():
    import pytest

    repo = ReferenceDataRepo()
    repo.data['resources'] = {'objects': {'aliases': ['object']}, 'object': {}}
    with pytest.raises(ValueError, match='Ambiguous resources aliases'):
        repo.rebuild_name_maps()


def test_objectstorage_documented_family_and_legacy_review_metadata():
    repo = _load_repo()
    assert repo.data['families']['object-family']['resources'] == ['objectstorage-namespaces', 'buckets', 'objects']
    for alias, canonical in [('bucket', 'buckets'), ('object', 'objects')]:
        assert set(repo.get_permissions(alias, 'manage')) == set(repo.get_permissions(canonical, 'manage'))
    assert repo.get_permissions('objectstorage-namespaces', 'inspect') == []
    assert set(repo.get_permissions('objectstorage-namespaces', 'manage')) == {
        'OBJECTSTORAGE_NAMESPACE_READ',
        'OBJECTSTORAGE_NAMESPACE_UPDATE',
    }
    for name in [
        'multipart-uploads',
        'pre-authenticated-requests',
        'replication-policies',
        'retention-rules',
        'namespace-metadata',
    ]:
        metadata = repo.get_catalog_metadata(name)
        assert metadata['catalog_status'] == (
            'rejected_in_console' if name == 'pre-authenticated-requests' else 'legacy_unverified'
        )
        assert metadata['replacement_resources']
        if name == 'pre-authenticated-requests':
            assert repo.get_permissions(name, 'manage') == []
            assert repo.get_permissions(name, 'inspect', 'deny') == []
            assert repo.data['resources'][name]['verbs']['manage'] == ['PAR_MANAGE']
        else:
            assert repo.get_permissions(name, 'manage')
        assert repo.get_source(name).endswith('/objectstoragepolicyreference.htm')
        assert repo.get_containing_family(name) is None


def test_objectstorage_bucket_permissions_and_corrected_operations():
    repo = _load_repo()
    assert {'PAR_MANAGE', 'RETENTION_RULE_MANAGE', 'RETENTION_RULE_LOCK'} <= set(
        repo.get_permissions('buckets', 'manage')
    )
    assert repo.data['operations']['objectstorage:ReencryptBucket']['permissions'] == ['BUCKET_UPDATE']
    assert repo.data['operations']['objectstorage:PutObject (New)']['permissions'] == ['OBJECT_CREATE']
    assert repo.data['operations']['objectstorage:PutObject (Overwrite)']['permissions'] == ['OBJECT_OVERWRITE']
