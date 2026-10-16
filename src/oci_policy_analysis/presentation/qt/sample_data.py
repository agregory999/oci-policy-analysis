"""Fictional landing-zone inventory reconstructed from anonymized policy patterns."""

import json
from importlib.resources import files


def sample_snapshot() -> dict:
    """Read a fresh sample without contacting OCI or accessing operator caches.

    Returns:
        dict: Version-2/schema-3 snapshot with 100 policies, 325 statements,
        25 groups, 50 users, 12 dynamic groups and 22 compartments. Names,
        identifiers, memberships and inventory are fictional. Policy language
        follows anonymized CIS landing-zone patterns, with additional resource
        and OKE workload examples and three intentionally invalid records.

    Notes:
        This is demonstration evidence, not a deployable CIS policy template.
        Each call returns detached data; enrichment cannot mutate the artifact.
    """
    resource = files('oci_policy_analysis.presentation.qt').joinpath('data/sample_snapshot.json')
    return json.loads(resource.read_text(encoding='utf-8'))
