"""Shared action guidance for policy recommendations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

RECOMMENDATION_SEVERITIES = ('Critical', 'High', 'Medium', 'Low', 'Info')

RECOMMENDATION_ACTION_CATALOG: dict[str, dict[str, Any]] = {
    'consolidate_policies': {
        'Action': 'Plan: Review consolidation opportunities with documentation and local experts',
        'ActionDetail': 'Review consolidation candidates, then design a staged consolidation plan with owners.',
        'ActionSteps': [
            'Review candidate statements and policy ownership.',
            'Choose a consolidation strategy that preserves existing access.',
            'Stage changes through the consolidation workbench or change process.',
        ],
        'Destination': '#cardConsolidation',
    },
    'invalid_statements': {
        'Action': 'Plan: Review and remediate invalid policy statements',
        'ActionDetail': 'Examine policies with invalid statements and resolve identity, compartment, alias, or tag references.',
        'ActionSteps': ['Open cleanup rows.', 'Fix the policy text or referenced identity data.', 'Reload analysis.'],
        'Destination': '#cardCleanup',
    },
    'unused_groups': {
        'Action': 'Plan: Remove or repurpose unused groups',
        'ActionDetail': 'Review business need for empty groups and remove them unless ownership documentation justifies keeping them.',
        'ActionSteps': [
            'Confirm no external process depends on the group.',
            'Remove or assign members.',
            'Document exceptions.',
        ],
        'Destination': '#cardCleanup',
    },
    'unused_dynamic_groups': {
        'Action': 'Plan: Remove unused dynamic groups',
        'ActionDetail': 'Delete or repurpose dynamic groups that are not referenced by policy statements.',
        'ActionSteps': [
            'Confirm the dynamic group is not used by automation.',
            'Delete it or add an appropriate policy reference.',
        ],
        'Destination': '#cardCleanup',
    },
    'statements_too_open': {
        'Action': "Plan: Restrict broad 'manage all-resources' statements",
        'ActionDetail': 'Replace broad grants with least privilege verbs, resources, compartments, and conditions.',
        'ActionSteps': [
            'Identify the required permissions.',
            'Reduce verb/resource scope.',
            'Move policy closer to the target compartment.',
        ],
        'Destination': '#cardCleanup',
    },
    'anyuser_no_where': {
        'Action': 'Plan: Add where clauses to any-user statements',
        'ActionDetail': 'Any-user policies should be constrained with concise principal conditions before they are trusted.',
        'ActionSteps': [
            'Add request.principal.type or workload identity conditions.',
            'Constrain compartment, cluster, namespace, or tags as appropriate.',
        ],
        'Destination': '#cardCleanup',
    },
    'all_domain_users': {
        'Action': 'Review membership assumptions',
        'ActionDetail': 'Informational only. The All Domain Users group cannot be deleted and may appear in each Identity Domain.',
        'ActionSteps': ['Confirm the broad membership is intended.', 'Prefer smaller groups for sensitive grants.'],
        'Destination': '#cardSummary',
    },
    'undefined_effective_path': {
        'Action': 'Plan: Review statement locations',
        'ActionDetail': 'Check statement location and compartment inventory so effective path resolution can complete.',
        'ActionSteps': ['Verify compartment names or OCIDs.', 'Reload compartments.', 'Rerun intelligence.'],
        'Destination': '#cardSummary',
    },
    'manage_all_root': {
        'Action': 'Plan: Restrict scope for manage all-resources',
        'ActionDetail': 'Work with compartment admins to replace root-wide manage all-resources with least privilege.',
        'ActionSteps': [
            'Confirm owner.',
            'Reduce compartment scope.',
            'Replace all-resources with specific resources.',
        ],
        'Destination': '#cardRiskStatement',
    },
    'limits': {
        'Action': 'Review the Limits tab and reduce/consolidate compartment statements as needed.',
        'ActionDetail': 'Review, consolidate, or delete policy statements in affected compartments.',
        'ActionSteps': [
            'Open Limits.',
            'Find compartments near or over limit.',
            'Consolidate or delete low-value statements.',
        ],
        'Destination': '#cardLimits',
    },
    'oke_workload_identity_hygiene': {
        'Action': 'Plan: Tighten OKE workload identity conditions',
        'ActionDetail': 'OKE workload policies should include request.principal.type, cluster_id, namespace, and service_account constraints. This check does not assert Kubernetes namespace existence.',
        'ActionSteps': [
            'Add missing workload identity atoms.',
            'Keep resource and operation conditions separate and explicit.',
            'Validate with workload owners.',
        ],
        'Destination': '/workload-principals-analysis.html',
    },
    'resource_principal_hygiene': {
        'Action': 'Plan: Tighten resource principal conditions',
        'ActionDetail': 'Resource-principal policies should constrain request.principal.type and, where possible, compartment identity before granting access to any-user or any-group.',
        'ActionSteps': [
            'Add request.principal.type.',
            'Add request.principal.compartment.id where practical.',
            'Review residual operation/resource conditions.',
        ],
        'Destination': '/workload-principals-analysis.html',
    },
    'tag_based_policy_hygiene': {
        'Action': 'Plan: Review tag-based policy condition coverage',
        'ActionDetail': 'Tag-based policies should use defined tag namespaces/keys intentionally and make whether access is based on request principal tags or target resource tags obvious.',
        'ActionSteps': [
            'Review tag namespaces and keys.',
            'Confirm request versus target tag semantics.',
            'Prefer defined tags for access control decisions.',
        ],
        'Destination': '/tag-namespaces.html',
    },
    'no_critical': {
        'Action': 'No action needed',
        'ActionDetail': 'No action is required at this time.',
        'ActionSteps': ['Continue periodic review after data refreshes.'],
        'Destination': '#cardSummary',
    },
}


def catalog_guidance(action_id: str, **overrides: Any) -> dict[str, Any]:
    """Return catalog guidance merged with row-specific overrides."""

    guidance = deepcopy(RECOMMENDATION_ACTION_CATALOG[action_id])
    guidance['ActionId'] = action_id
    guidance.update({key: value for key, value in overrides.items() if value is not None})
    return guidance
