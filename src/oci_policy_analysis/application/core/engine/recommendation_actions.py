"""Shared action guidance for policy recommendations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

RECOMMENDATION_PRIORITY_CRITICAL = 'Critical'
RECOMMENDATION_PRIORITY_HIGH = 'High'
RECOMMENDATION_PRIORITY_MEDIUM = 'Medium'
RECOMMENDATION_PRIORITY_LOW = 'Low'
RECOMMENDATION_PRIORITY_INFO = 'Info'
RECOMMENDATION_SEVERITIES = (
    RECOMMENDATION_PRIORITY_CRITICAL,
    RECOMMENDATION_PRIORITY_HIGH,
    RECOMMENDATION_PRIORITY_MEDIUM,
    RECOMMENDATION_PRIORITY_LOW,
    RECOMMENDATION_PRIORITY_INFO,
)


def overly_broad_statement_guidance(statement: dict[str, Any]) -> dict[str, str]:
    """Return cleanup guidance appropriate to an overly broad statement."""
    is_deny = str(statement.get('action') or '').strip().casefold() == 'deny'
    has_conditions = bool(str(statement.get('conditions') or '').strip())
    verb = str(statement.get('verb') or 'manage').strip().casefold()

    reason_verb = 'Revokes' if is_deny else 'Grants'
    action = 'Review the effective path and target resources; ensure the statement scope is appropriate.'
    if has_conditions:
        action += ' Review and test the conditions to confirm they are accurate and effective.'

    return {
        'Reason': f"{reason_verb} '{verb} all-resources' {'from' if is_deny else 'to'} a principal outside root/admin.",
        'Action': action,
    }


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
        'ActionSteps': [
            'Read the validation reason and compare the statement with the loaded inventory.',
            'For missing groups or dynamic groups, check the identity domain, group name, spelling, and any OCID reference. Quotes around names are allowed.',
            'Check compartment, alias, or tag references when named in the validation reason.',
            'Correct the reference, or remove the statement if its access is no longer required. Reload analysis after changes.',
        ],
        'Destination': '#cardCleanup',
    },
    'unused_groups': {
        'Action': 'Plan: Remove or repurpose unused groups',
        'ActionDetail': 'Review business need for empty groups and remove them unless ownership documentation justifies keeping them.',
        'ActionSteps': [
            'Confirm that the membership inventory is complete. Zero members does not mean zero policy references.',
            'Check policy references, automation dependencies, ownership, and planned use.',
            'Assign members if the group is needed. Delete the group only if it is truly unused and has no planned purpose; review its policy references too.',
            'Document the owner and intended use if the group is retained.',
        ],
        'Destination': '#cardCleanup',
    },
    'unused_dynamic_groups': {
        'Action': 'Plan: Remove unused dynamic groups',
        'ActionDetail': 'Delete or repurpose dynamic groups that are not referenced by policy statements.',
        'ActionSteps': [
            'Confirm the policy inventory is complete and search for references by domain/name and OCID.',
            'Check domain and group-name spelling in any expected policy references.',
            'Confirm the matching rule, workload owner, automation dependencies, and planned use.',
            'Correct or add a policy reference if access is intended. Delete the dynamic group only if it is truly unused and has no planned purpose; otherwise document why it is retained.',
        ],
        'Destination': '#cardCleanup',
    },
    'statements_too_open': {
        'Action': "Plan: Review broad 'all-resources' statements",
        'ActionDetail': 'Review effective paths, target resources, and any conditions before narrowing the statement scope.',
        'ActionSteps': [
            'Review the effective path and target resources.',
            'Ask the administrator whether tighter permissions are required for the intended operations.',
            'Replace all-resources with specific resource types or families, and reduce the verb or compartment scope where appropriate.',
            'For deny statements, review the intended restriction and the effect of narrowing or removing it.',
            'Test any conditions to confirm they are accurate and effective.',
        ],
        'Destination': '#cardCleanup',
    },
    'anyuser_no_where': {
        'Action': 'Plan: Add where clauses to any-user statements',
        'ActionDetail': 'Any-user policies should be constrained with concise principal conditions before they are trusted.',
        'ActionSteps': [
            'Identify which principals should have access, then add a limiting where clause.',
            "For an Autonomous Database resource principal, an example is: where all {request.principal.type = 'autonomousdatabase'}",
            'A type condition alone applies to that principal type; add identity or compartment constraints when access should be limited to particular resources.',
            'Constrain compartment, cluster, namespace, or tags as appropriate.',
            'Test both intended access and requests that should be rejected.',
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
    'deep_effective_paths': {
        'Action': 'Plan: Review policy placement and move statements closer to their effective scope',
        'ActionDetail': (
            'Review these statements in the Policy Analysis and Consolidation workbenches. '
            'Move a statement only after confirming that its resulting effective access remains unchanged.'
        ),
        'ActionSteps': [
            'Review the policy compartment and effective path for each example.',
            'Confirm the statement does not intentionally apply to intervening compartments.',
            'Use a move or consolidation plan to place the statement closer to its effective scope.',
        ],
        'Destination': '#cardConsolidation',
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


CLEANUP_ACTION_IDS = {
    'Invalid Statement': 'invalid_statements',
    'Group w/ No Users': 'unused_groups',
    'Unused Dynamic Group': 'unused_dynamic_groups',
    'Overly Broad Statement': 'statements_too_open',
    'Any-user Without Where': 'anyuser_no_where',
}


def cleanup_finding_identity(row: dict, payload: dict) -> tuple[str, str, str]:
    """Identify findings across reloads without transient statement IDs or truncated labels."""
    identity = payload.get('dynamic_group_ocid') or payload.get('group_ocid') or payload.get('policy_ocid') or ''
    subject = (
        ''
        if payload.get('dynamic_group_ocid') or payload.get('group_ocid')
        else (payload.get('statement_text') or row.get('Name') or '')
    )
    return str(row.get('Type') or ''), str(identity), str(subject).strip()


def cleanup_detail_sections(row: dict, payload: dict | None = None) -> list[tuple[str, list[str]]]:
    """Build read-only cleanup details from the shared action catalog and original row data."""
    payload = payload or {}
    action_id = CLEANUP_ACTION_IDS.get(row.get('Type', ''))
    guidance = catalog_guidance(action_id) if action_id else {}
    item = [str(payload.get('statement_text') or row.get('Name') or 'Unknown item')]
    if payload.get('policy_name'):
        item.insert(0, f'Policy: {payload["policy_name"]}')
    steps = guidance.get('ActionSteps') or [row.get('Action') or 'Review this finding with the resource owner.']
    return [
        ('Item', item),
        ('Why this was flagged', [str(row.get('Reason') or 'Review the validation findings.')]),
        ('Potential actions', [f'{index}. {step}' for index, step in enumerate(steps, start=1)]),
    ]


ATTEMPT_FIX_HELP = (
    'Add selected findings to Cleanup In Progress for tracking and guidance. '
    'You make the changes in OCI; this button does not change policies or identities. '
    'After making changes, use Reload All from a live tenancy load to check whether the findings are resolved.'
)


def supersession_finding_identity(statement: dict) -> tuple[str, str, str]:
    """Keep supersession tracking stable when analysis assigns new internal IDs."""
    return (
        'Superseded Statement',
        str(statement.get('policy_ocid') or ''),
        str(statement.get('statement_text') or '').strip(),
    )


def current_supersession_identities(overlay: dict, statements: list[dict]) -> set[tuple]:
    """Collect all current supersession findings independently of display filters and ignores."""
    by_id = {str(statement.get('internal_id') or ''): statement for statement in statements}
    return {
        supersession_finding_identity(by_id[str(finding.get('statement_internal_id') or '')])
        for finding in overlay.get('supersessions', []) or []
        if str(finding.get('statement_internal_id') or '') in by_id
    }


def cleanup_verification_scope(repo) -> dict:
    """Identify inventory scope so omitted findings are not mistaken for resolved ones."""
    return {key: getattr(repo, key, None) for key in ('recursive', 'compartment_domain_search_depth')}


def reconcile_cleanup_actions(
    actions: list[dict], tenancy: str, current: set[tuple], *, enabled=None, users_loaded=True, verification_scope=None
) -> list[dict]:
    """Record verification against a complete live analysis; callers must establish freshness."""
    from datetime import UTC, datetime

    result = deepcopy(actions)
    stamp = datetime.now(UTC).isoformat(timespec='seconds')
    for action in result:
        if action.get('tenancy_ocid') != tenancy:
            continue
        identity = action.get('finding_identity')
        check_id = (
            'supersession'
            if action.get('Type') == 'Superseded Statement'
            else CLEANUP_ACTION_IDS.get(action.get('Type'))
        )
        if not identity or not check_id or (enabled and check_id not in enabled):
            outcome = 'Not checked (recommendation check disabled or identity unavailable)'
        elif check_id == 'unused_groups' and not users_loaded:
            outcome = 'Not checked (user membership data was not loaded)'
        elif (
            tuple(identity) not in current
            and verification_scope is not None
            and (
                not action.get('verification_scope')
                or any(value is None for value in verification_scope.values())
                or action['verification_scope'] != verification_scope
            )
        ):
            outcome = 'Not checked (inventory scope differs or the original scope is unknown)'
        else:
            action['Status'] = 'Open' if tuple(identity) in current else 'Resolved'
            if tuple(identity) in current and verification_scope is not None:
                action['verification_scope'] = dict(verification_scope)
            outcome = action['Status']
        action['History'] = f'{action.get("History", "")}\nReload {stamp}: {outcome}'.strip()
    return result
