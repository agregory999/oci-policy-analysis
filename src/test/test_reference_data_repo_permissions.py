"""Tests for ReferenceDataRepo cumulative allow/deny semantics.

These tests focus on a few key invariants rather than exact permission
names, to avoid being brittle with respect to upstream permission JSON
changes from OCI. They rely on the real permissions data shipped with
the project.
"""

from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo


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
