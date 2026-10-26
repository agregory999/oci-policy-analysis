"""Fictional landing-zone inventory reconstructed from anonymized policy patterns."""

import json
from importlib.resources import files


def sample_snapshot() -> dict:
    """Read a fresh sample without contacting OCI or accessing operator caches.

    Returns:
        dict: Version-2/schema-3 snapshot with 105 policies, 335 statements,
        26 groups, 50 users, 12 dynamic groups and 24 compartments. Names,
        identifiers, memberships and inventory are fictional. Policy language
        follows anonymized CIS landing-zone patterns, with additional resource
        and OKE workload examples and three intentionally invalid records.

    Notes:
        The deny-policy example requires OCI IAM deny policies to be enabled.
        This is demonstration evidence, not a deployable CIS policy template.
        Each call returns detached data; enrichment cannot mutate the artifact.
    """
    resource = files('oci_policy_analysis.presentation.qt').joinpath('data/sample_snapshot.json')
    return json.loads(resource.read_text(encoding='utf-8'))
