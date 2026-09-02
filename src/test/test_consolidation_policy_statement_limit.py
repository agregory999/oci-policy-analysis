"""Tests for the OCI per-policy statement limit on consolidation proposals."""

import pytest
from oci_policy_analysis.application.core.engine.consolidation_engine import ConsolidationEngine


def test_plan_rejected_when_modify_step_exceeds_oci_policy_statement_limit() -> None:
    plan = {
        'plan_steps': [
            {
                'action': 'modify',
                'policy_ocid': 'ocid1.policy.oc1..target',
                'after_statements': [
                    f'allow group G to read buckets where target.bucket.name = {i}' for i in range(51)
                ],
            }
        ]
    }

    with pytest.raises(ValueError, match=r'Plan cannot be created.*50 statements.*51 statements'):
        ConsolidationEngine._validate_policy_statement_limit(plan)  # type: ignore[arg-type]


def test_plan_allows_fifty_statements_and_ignores_delete_steps() -> None:
    plan = {
        'plan_steps': [
            {
                'action': 'add',
                'create_policy_name': 'New Policy',
                'after_statements': ['allow group G to read buckets'] * 50,
            },
            {'action': 'delete', 'policy_ocid': 'ocid1.policy.oc1..old', 'after_statements': ['ignored'] * 51},
        ]
    }

    ConsolidationEngine._validate_policy_statement_limit(plan)  # type: ignore[arg-type]
