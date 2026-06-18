# OKE Workload Identity Querying

This page explains how to find OCI IAM policies for OKE workload identities.

It is **not MCP-only**. The same underlying search path is available from:

- `policy_search` in MCP, using a structured `principal` selector
- `oke_workload_identity_search` in MCP, which is a guided wrapper
- the desktop **Workload Principals** tab in `OKE Workload Identity` mode
- the web **Workload Principals Analysis** page, which maps the same advanced filters into the shared search path

## What It Looks For

OKE workload identity policies are usually `any-user` statements with a `where` clause that includes:

- `request.principal.type = 'workload'`
- `request.principal.namespace = '<namespace>'`
- `request.principal.service_account = '<service_account>'`
- `request.principal.cluster_id = '<cluster_ocid>'`

The search treats the namespace, service account, and cluster OCID as optional filters.
If you provide only one field, it matches on that field and shows the other condition atoms in the returned statement.

When a statement has extra conditions beyond the principal identity, advanced mode reports that as residual evidence through:

- `principal_evidence`
- `condition_atoms`
- `residual_conditions`
- `match_confidence`
- `match_confidence_reason`

## How To Query It

### MCP: Guided OKE Search

Use this when you want the shortest request shape:

```json
{
  "workload_namespace": "finance",
  "workload_service_account": "oke-rp-smoke",
  "workload_cluster_id": "ocid1.cluster.oc1.iad.example",
  "limit": 20
}
```

That call routes through `oke_workload_identity_search`, which builds the structured `policy_search` request for you.

### MCP: Advanced `policy_search`

Use this when you want one canonical search surface:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "oke-workload-identity",
      "workload_namespace": "finance"
    }
  },
  "limit": 20
}
```

Add `workload_service_account` and/or `workload_cluster_id` to narrow the match.

### Web UI

In **Workload Principals Analysis**, choose `OKE Workload Identity` and fill in any of:

- OKE Namespace
- OKE Service Account
- OKE Cluster OCID

The page sends those values into the same shared advanced search path used by MCP.

## Examples

### 1. Namespace Only

Use this when you want to find every OKE workload policy in a namespace:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "oke-workload-identity",
      "workload_namespace": "finance"
    }
  },
  "limit": 20
}
```

Expected behavior:

- returns all matching OKE workload policies in `finance`
- shows `request.principal.type = 'workload'`
- shows `request.principal.namespace = 'finance'`
- leaves `service_account` and `cluster_id` unconstrained

### 2. Namespace + Service Account

Use this when you want to isolate a single workload identity within a namespace:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "oke-workload-identity",
      "workload_namespace": "accounting",
      "workload_service_account": "oke-rp-smoke"
    }
  },
  "limit": 20
}
```

Expected behavior:

- returns the isolated policy for that namespace/service-account pair
- reports `match_confidence: exact` when no extra conditions remain

### 3. Service Account Only

Use this when the same service account is reused across namespaces:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "oke-workload-identity",
      "workload_service_account": "oke-rp-smoke"
    }
  },
  "limit": 20
}
```

Expected behavior:

- returns every OKE workload policy that uses that service account
- may span multiple namespaces
- is useful for discovering reuse or drift

## Smoke Test Validation

We validated the implementation with a real smoke workload identity pattern in the tenancy:

- namespace `finance`
- service account `oke-rp-smoke`
- cluster OCID constrained in the policy statement

Observed results after reload:

- `namespace=finance` returned the smoke policy plus another policy in the same namespace
- `service_account=oke-rp-smoke` returned both the `finance` and `accounting` policies
- `namespace=accounting` plus `service_account=oke-rp-smoke` isolated the `accounting` policy

The smoke policy also demonstrated residual-condition handling because one version included an extra non-principal condition. In advanced mode, that surfaced as `identity_match_with_residual` with the residual atom preserved in `residual_conditions`.

## Practical Notes

- If you want the narrowest search, specify namespace, service account, and cluster OCID together.
- If you want discovery, start with namespace only or service account only.
- Advanced mode is the right choice when you want evidence and confidence fields, not just matching row counts.
- This search pattern does not validate a live Kubernetes cluster. It only inspects IAM policy statements and parsed condition evidence.
