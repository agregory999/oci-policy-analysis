# Actionable Recommendations Context

## Intent

Recommendations should be catalog-backed, readable, and stable across application surfaces. The legacy row fields (`Recommendation`, `Priority`, `Category`, `Notes`, `Action`) remain compatibility fields for older tables and exports. New action guidance is added as structured details (`ActionId`, `ActionDetail`, `ActionSteps`, `Destination`, and optional `Evidence`).

The shared catalog lives in `oci_policy_analysis.application.core.engine.recommendation_actions`. New recommendation families should add catalog entries there rather than embedding unrelated action text in UI code.

## Severity And Category Standards

Use these priority levels consistently:

- `Critical`: immediate risk or hard platform limit.
- `High`: broad access, broken policy validity, or incomplete workload principal guardrails.
- `Medium`: hygiene findings that can widen access or increase operational risk.
- `Low`: informational review items with low direct blast radius.
- `Info`: no action or contextual status.

Categories should be specific enough for filtering, for example `Workload Identity`, `Resource Principal`, `Tag-Based Access`, `Policy Hygiene`, `Access Scope`, `Identity Management`, `Consolidation`, `Limits`, and `General`.

## Current Recommendation Checks

This is the user-facing recommendation/action catalog as of this implementation. Keep this table aligned with `RECOMMENDATION_ACTION_CATALOG` and `PolicyIntelligenceEngine.build_overall_recommendations`.

| Action ID | Trigger | Default Severity | Category | Default Action | Destination |
|---|---|---:|---|---|---|
| `consolidate_policies` | Consolidation engine produces one or more consolidation candidates. | Medium | Consolidation | Plan: Review consolidation opportunities with documentation and local experts | Web consolidation section / desktop consolidation tab |
| `invalid_statements` | Cleanup finds policy statements marked invalid. | High | Policy Hygiene | Plan: Review and remediate invalid policy statements | Cleanup section/tab |
| `unused_groups` | Cleanup finds IAM groups with zero members. | Medium | Identity Management | Plan: Remove or repurpose unused groups | Cleanup section/tab |
| `unused_dynamic_groups` | Cleanup finds dynamic groups not referenced by policy statements. | Medium | Identity Management | Plan: Remove unused dynamic groups | Cleanup section/tab |
| `statements_too_open` | Cleanup finds broad `manage all-resources` grants. | High | Access Scope | Plan: Restrict broad `manage all-resources` statements | Cleanup section/tab |
| `anyuser_no_where` | Cleanup finds `any-user` statements without a where clause. | High | Access Scope | Plan: Add where clauses to any-user statements | Cleanup section/tab |
| `all_domain_users` | A policy references the special `All Domain Users` group. | Low | Identity Management | Review membership assumptions | Recommendation summary |
| `undefined_effective_path` | A policy statement has no resolved effective path. | High | Compartment Resolution | Plan: Review statement locations | Recommendation summary |
| `manage_all_root` | A non-tenant-admin policy grants `manage all-resources` at root without conditions. | Critical | Policy Scope | Plan: Restrict scope for manage all-resources | Risk statement section/tab |
| `limits` | A compartment is near or over the policy statement limit. | Critical | Limits | Review the Limits tab and reduce/consolidate compartment statements as needed. | Limits section/tab |
| `oke_workload_identity_hygiene` | An `any-user` workload policy is missing one or more recommended OKE workload atoms. | High | Workload Identity | Plan: Tighten OKE workload identity conditions | Workload principals page/tab |
| `resource_principal_hygiene` | An `any-user`/`any-group` resource principal policy lacks recommended principal type or compartment constraints. | Medium | Resource Principal | Plan: Tighten resource principal conditions | Workload principals page/tab |
| `tag_based_policy_hygiene` | A statement uses tag-based access conditions. | Medium | Tag-Based Access | Plan: Review tag-based policy condition coverage | Tag namespaces/tag-based access page/tab |
| `no_critical` | No other recommendation is generated. | Info | General | No action needed | Recommendation summary |

The table is intentionally about recommendation rows, not raw lower-level analytics. For example, `invalid_statements`, `unused_groups`, and `anyuser_no_where` are generated from cleanup buckets, while workload/resource/tag hygiene is generated directly from parsed statement condition shape.

## Principal Recommendation Rules

OKE workload identity recommendations are policy-shape checks only. They may flag incomplete `any-user` workload policies that lack one or more of:

- `request.principal.type = 'workload'`
- `request.principal.cluster_id`
- `request.principal.namespace`
- `request.principal.service_account`

Do not claim a Kubernetes namespace, service account, or cluster does not exist unless future live inventory collection is added.

Resource principal recommendations apply to `any-user` or `any-group` policies with `request.principal.*` conditions that are not OKE workload identity policies. Prefer constraints for `request.principal.type` and, where practical, `request.principal.compartment.id`.

## Tag-Based Policy Rules

Tag-based access recommendations are review guidance. They should surface statements with tag conditions and encourage validation of request-principal versus target-resource semantics, defined tag namespace/key alignment, and avoidance of freeform tags for access control decisions.

Invalid namespace/key findings belong in invalid-statement cleanup when the catalog is available. Hygiene recommendations should not duplicate those as hard validation errors.

## UI Expectations

Web recommendations should show summary severity/category counts, filters, richer action detail, and row details. Right-click navigation should use the structured `Destination` value to jump to a local section or related web page.

Desktop recommendations should render the same guidance where practical while preserving existing columns and table behavior.

## Post-Load Processing Expectations

Post-load processing has two intended profiles:

- Full UI profile: desktop and web loads should rebuild effective paths, invalidity state, dynamic-group usage, risk/overlap/cleanup/consolidation overlays, recommendations, permissions report, and simulation state.
- Minimal non-UI profile: CLI and standalone MCP should only run enrichment required for search correctness and cache quality: effective path calculation, invalid statement validation, and dynamic-group in-use analysis.

The minimal profile must not run `PolicyIntelligenceEngine.run_all()` and must not build `overlay['recommendations']`. CLI and MCP do not expose the actionable recommendations workflow, so recommendation calculation there only adds runtime cost and misleading logs.

The web API may still expose `/intelligence/run` and `/analysis/recommendations/dashboard` for the web UI. Those endpoints are UI-facing and may use the full profile or explicitly run intelligence after load.

## Future Customization Design

Users may eventually want to customize recommendation behavior without editing code. The likely shape is a persisted settings object next to the existing `enabled_intelligence_checks` setting in `SettingsTab`:

```json
{
  "recommendation_action_overrides": {
    "oke_workload_identity_hygiene": {
      "enabled": true,
      "priority": "Critical"
    },
    "all_domain_users": {
      "enabled": false
    }
  }
}
```

Recommended behavior:

- Catalog defaults remain the source of truth for action text, destination, and default severity.
- Settings may override `enabled` and `Priority` by `ActionId`.
- Unknown action IDs should be ignored but preserved when saving settings, so downgrades or plugin-style future checks do not destroy user preferences.
- If a recommendation action is disabled, the engine should suppress that specific recommendation row after evidence is computed, while leaving underlying cleanup/risk/tag analytics intact.
- Severity overrides should affect the recommendation row and web summary counts, but should not change raw risk scores.
- Desktop settings can add a small "Recommendation actions" section below the current broad intelligence check toggles. Web settings should use the same saved keys.
- CLI and MCP should not expose this display workflow unless a future explicit recommendations endpoint/tool is added.

## Testing Expectations

Add service or engine tests for new recommendation rules and compatibility tests for legacy fields. Add static web tests for filters, action details, table sizing, and context-menu destinations when behavior is implemented directly in static assets.
