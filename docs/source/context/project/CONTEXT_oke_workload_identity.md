# OKE Workload Identity Policy Search

Status: deferred. This plan is parked here while tag-based policy query follow-up work continues.

Oracle reference:

- https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contenggrantingworkloadaccesstoresources.htm

## Summary

Add first-class search support for OKE workload identity policies. Per Oracle's OKE workload identity docs, these are `any-user` IAM policies constrained by `request.principal.type = 'workload'`, plus namespace, service account, and cluster OCID conditions.

Recommendation: implement both paths:

- Extend existing advanced `policy_search`, because OKE workload identity is a workload-principal variant.
- Add a guided `oke_workload_identity_search` MCP/API wrapper, because users should not need to remember the exact OCI condition variable names.

## Key Condition Variables

- `request.principal.type = 'workload'`
- `request.principal.namespace`
- `request.principal.service_account`
- `request.principal.cluster_id`

## Planned Search Shape

Extend structured principal selectors with:

```json
{
  "principal": {
    "principal_type": "oke-workload-identity",
    "workload_namespace": "finance",
    "workload_service_account": "financeserviceaccount",
    "workload_cluster_id": "ocid1.cluster..."
  }
}
```

Matching rules:

- Match only policy statements with subject `any-user` or `any-group`.
- Require parsed evidence for `request.principal.type = 'workload'`.
- When supplied, AND namespace, service account, and cluster ID filters.
- Missing namespace/service account/cluster ID means "do not constrain by that field."
- Preserve existing `resource-principal` behavior unchanged.

## Planned MCP Tool

Add `oke_workload_identity_search`.

Inputs:

- `workload_namespace`
- `workload_service_account`
- `workload_cluster_id`
- optional `verb`
- optional `resource`
- optional `permission`
- optional `effective_path`
- optional `limit`

Implementation: build an equivalent `policy_search` request using `principal_type: "oke-workload-identity"` and return the same advanced evidence fields:

- `principal_evidence`
- `condition_atoms`
- `residual_conditions`
- `match_confidence`
- `match_confidence_reason`

## Planned UI/API Touchpoints

Desktop:

- Extend `Workload Principals Analysis`.
- Add principal style option: `OKE Workload Identity`.
- Add filters for namespace, service account, and cluster OCID.
- Do not show the dynamic group table in OKE mode.

Web:

- Extend `workload-principals-analysis.html`.
- Add the same OKE mode and filters.
- Send fields to `/filter/policies/by-subjects`.
- Map fields into the structured principal selector in the route.

Discovery:

- Extract discovered namespaces, service accounts, and cluster IDs from parsed condition atoms where `request.principal.type = 'workload'`.
- Use discovered values for dropdown/autocomplete where practical, while keeping text entry supported.

## Test Plan

Repository filtering:

- Match an OKE workload identity policy by namespace, service account, and cluster ID.
- Match by namespace only.
- Match by namespace plus service account.
- Reject when namespace matches but service account does not.
- Reject regular resource-principal policies where `request.principal.type != 'workload'`.
- Preserve existing `resource-principal` tests.

MCP:

- `policy_search` accepts `principal_type: "oke-workload-identity"`.
- Advanced/full responses include principal evidence for all matched OKE fields.
- `oke_workload_identity_search` returns the same statements as equivalent `policy_search`.
- Packaged MCP tool catalog includes the new guided tool.

Web/API:

- `/filter/policies/by-subjects` maps OKE fields into the structured principal selector.
- Existing resource-principal compartment/resource-type behavior remains unchanged.

UI smoke checks:

- Desktop OKE mode shows only policy results, not dynamic group results.
- Web OKE mode sends namespace/service account/cluster ID filters.
- Text filter still narrows returned statement rows.

## Assumptions

- v1 only detects IAM policy coverage for OKE workload identities; it does not query Kubernetes clusters or validate live namespaces/service accounts.
- Enhanced OKE clusters are required per Oracle documentation, but v1 only documents this requirement.
- `request.principal.type = 'workload'` is required for an OKE workload identity match.
- Existing `workload-principal` alias remains supported, but the new documented selector is `oke-workload-identity`.
