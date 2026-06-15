# MCP and Policy Search Examples

This page shows example requests and expected response shapes for the planned MCP search surface. It starts with simple policy searches and builds toward workload principal analysis, search sets, and historical comparison.

The examples are intentionally verbose for documentation. MCP tool descriptions should stay terse.

## Result Detail Levels

Most policy search examples use:

- `detail_level: summary` for counts, breakdowns, and samples.
- `detail_level: simple` for compact statement rows.
- `detail_level: full` for parsed statement metadata, principal evidence, parsed condition structure, and condition elements.

`limit` controls the maximum number of detailed statement rows returned. The server should evaluate all matches, but return summary output when match count exceeds the limit. MCP-facing calls should cap `limit` at `50` or lower to avoid large protocol payloads.

Each search has three conceptual inputs:

- `mode`: `simple` for common statement and principal lookups, or `advanced` for workload principal, tag, parsed-condition, and evidence-aware lookups.
- `filters`: the searchable fields. `statement_text` and `subject_text` are raw text filters; `principal` is structured identity context.
- `detail_level`: how much metadata to return. `summary` is safest for broad searches, `simple` returns compact rows, and `full` returns parsed metadata and evidence fields.

Common output fields:

- `total_count`: number of matching statements after all filters run.
- `statements`: detailed rows when `total_count <= limit`.
- `summary`: counts and breakdowns when `total_count > limit` or when `detail_level: summary`.
- `conditions_where_clause`: raw policy `where` clause text.
- `conditions_parsed_structure`: display-oriented parse status and shape.
- `condition_atoms`: parsed condition elements such as left side, operator, right side, and evidence kind.

## Principal Keys and Structured Fields

Callers can provide either a canonical `principal_key` or structured fields. They should not provide both in the same principal filter unless the server explicitly validates they are equivalent.

Structured fields are preferred for AI agents and UI forms because the server can compute and log the canonical key. The repository layer should emit the computed or supplied key at `WARNING` while this feature is stabilizing.

Examples:

```json
{
  "principal": {
    "principal_key": "group:Default/Administrators"
  }
}
```

```json
{
  "principal": {
    "principal_type": "resource-principal",
    "resource_type": "containerinstance",
    "compartment_ocid": "ocid1.compartment.oc1..app"
  }
}
```

The second example computes:

```text
resource-principal:containerinstance/compartment:ocid1.compartment.oc1..app
```

## Simple Statement Text Search

Use this when the user asks for policies containing specific text.

Input:

```json
{
  "mode": "simple",
  "detail_level": "simple",
  "filters": {
    "statement_text": ["manage all-resources"],
    "effective_path": ["ROOT/Prod"]
  },
  "limit": 25
}
```

Expected output:

```json
{
  "response_type": "simple",
  "total_count": 2,
  "statements": [
    {
      "policy_name": "ProdAdmins",
      "compartment_path": "ROOT",
      "statement_text": "allow group ProdAdmins to manage all-resources in compartment Prod",
      "subject_text": "group ProdAdmins",
      "verb": "manage",
      "resource": "all-resources",
      "effective_path": "ROOT/Prod",
      "conditions_where_clause": "",
      "conditions_parsed_structure": ""
    }
  ]
}
```

## Human Principal Search

Use structured `principal` when the caller means an identity, not raw subject text.

Input:

```json
{
  "mode": "simple",
  "detail_level": "simple",
  "filters": {
    "principal": {
      "principal_type": "group",
      "domain_name": "Default",
      "name": "Administrators"
    },
    "verb": ["manage"]
  },
  "limit": 50
}
```

Expected behavior:

- Match `group Default/Administrators`.
- Match equivalent `group-id:<ocid>` statements when identity data supports the equivalence.
- Return summary output if more than `limit` statements match.

## Service Principal Search

Use service principals when the OCI service itself is the subject.

Input:

```json
{
  "mode": "simple",
  "detail_level": "simple",
  "filters": {
    "principal": {
      "principal_type": "service",
      "name": "cloudguard"
    },
    "verb": ["read", "use"],
    "resource": ["instances", "instance-family"]
  },
  "limit": 25
}
```

Expected behavior:

- Match statements such as `allow service cloudguard to read instances in tenancy`.
- Keep service principal matching separate from `subject_text` so agents do not confuse service names with policy text search.

## Subject Text Search

Use `subject_text` when the caller wants raw subject matching.

Input:

```json
{
  "mode": "simple",
  "detail_level": "summary",
  "filters": {
    "subject_text": ["any-user"],
    "resource": ["repos"]
  }
}
```

Expected behavior: text-oriented match over statement subjects. This does not prove resource principal identity by itself.

## Resource Principal, Specific Resource

Use this for `any-user` / `any-group` statements constrained by `request.principal.*`.

Input:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "resource-principal",
      "resource_type": "containerinstance",
      "ocid": "ocid1.computecontainerinstance.oc1..example",
      "match_mode": "auto"
    }
  },
  "limit": 25
}
```

Expected behavior:

- Derive principal key `resource-principal:containerinstance/ocid1.computecontainerinstance.oc1..example`.
- Search `any-user` / `any-group` statements.
- Treat `request.principal.type` and `request.principal.id` as identity evidence.
- Return residual conditions separately.
- Return `match_confidence: exact` only when the condition evidence uniquely identifies the principal and no residual condition remains.

Expected output fields:

```json
{
  "conditions_where_clause": "all { request.principal.type = 'containerinstance', request.operation = 'PullImage' }",
  "conditions_parsed_structure": "parsed: ALL { c1, c2 } (2 atoms)",
  "condition_atoms": [
    {
      "id": "c1",
      "left": "request.principal.type",
      "operator": "=",
      "right": "containerinstance",
      "evidence_kind": "resource_principal"
    },
    {
      "id": "c2",
      "left": "request.operation",
      "operator": "=",
      "right": "PullImage",
      "evidence_kind": "condition"
    }
  ],
  "match_confidence": "identity_match_with_residual"
}
```

## Resource Principal, Compartment Scope

Input:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "resource-principal",
      "resource_type": "containerinstance",
      "compartment_ocid": "ocid1.compartment.oc1..app",
      "match_mode": "condition"
    }
  }
}
```

Expected behavior:

- Derive principal key `resource-principal:containerinstance/compartment:ocid1.compartment.oc1..app`.
- Treat `request.principal.type` plus `request.principal.compartment.id` as identity evidence.
- Return `exact` only when no non-identity condition atoms remain.
- Return `identity_match_with_residual` when the statement also includes operations, permissions, tags, time, network, or other conditions.

## Instance Principal, Dynamic Group Rule

Input:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "instance-principal",
      "resource_type": "instance",
      "compartment_ocid": "ocid1.compartment.oc1..app",
      "match_mode": "dynamic_group_rule"
    }
  }
}
```

Expected behavior:

- Derive principal key `instance-principal:instance/compartment:ocid1.compartment.oc1..app`.
- Search dynamic group rules for `instance.compartment.id`.
- Search policies for matching dynamic group subjects.
- Return `rule_evidence` until full rule evaluation is implemented.

Dynamic group display fields:

```json
{
  "matching_rule": "instance.compartment.id = 'ocid1.compartment.oc1..app'",
  "matching_rule_parsed_structure": "parsed: c1 (1 atom)",
  "matching_rule_elements": "c1: instance.compartment.id = ocid1.compartment.oc1..app [instance_principal]"
}
```

## Instance Principal, Specific Instance

Input:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "instance-principal",
      "resource_type": "instance",
      "ocid": "ocid1.instance.oc1..worker",
      "compartment_ocid": "ocid1.compartment.oc1..app"
    }
  },
  "limit": 25
}
```

Expected behavior:

- Derive principal key `instance-principal:instance/ocid1.instance.oc1..worker`.
- Search dynamic group rules for direct instance OCID evidence and compartment evidence.
- Search policies where the matched dynamic groups are policy subjects.
- Return dynamic group rule evidence separately from policy statement condition evidence.

## Tag-Based Condition Search

Input:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "condition": {
      "tag_scope": "request.principal.group",
      "tag_namespace": "Operations",
      "tag_key": "Environment",
      "tag_value": "prod"
    }
  }
}
```

Expected behavior:

- Reuse known tag-condition parsing where reliable.
- Return parsed condition structure and condition atoms.
- Do not require full recursive condition evaluation for initial matching.

## Condition Display Fields

Policies should display condition analysis using condition-oriented names, even when the source OCI syntax uses `where`.

Output:

```json
{
  "conditions_where_clause": "all { request.principal.type = 'containerinstance', target.resource.tag.Operations.Environment = 'prod' }",
  "conditions_parsed_structure": "parsed: ALL { c1, c2 } (2 atoms)",
  "condition_atoms": [
    {
      "id": "c1",
      "left": "request.principal.type",
      "operator": "=",
      "right": "containerinstance",
      "evidence_kind": "resource_principal"
    },
    {
      "id": "c2",
      "left": "target.resource.tag.Operations.Environment",
      "operator": "=",
      "right": "prod",
      "evidence_kind": "tag_condition"
    }
  ]
}
```

The first implementation should parse and display the structure without relying on full recursive evaluation for filtering.

## Search Set: Service Installation Validation

Use a search set when a service/product requires multiple human and workload permissions.

Input:

```json
{
  "intent": "install_validation",
  "product_or_service": "container image pull from OCIR",
  "searches": [
    {
      "search_id": "human-admins",
      "label": "Human admins can manage repos",
      "required": true,
      "query": {
        "mode": "simple",
        "detail_level": "summary",
        "filters": {
          "principal": {
            "principal_type": "group",
            "domain_name": "Default",
            "name": "ContainerAdmins"
          },
          "resource": ["repos"],
          "verb": ["manage"]
        }
      }
    },
    {
      "search_id": "container-runtime",
      "label": "Container instance resource principal can pull images",
      "required": true,
      "query": {
        "mode": "advanced",
        "detail_level": "full",
        "filters": {
          "principal": {
            "principal_type": "resource-principal",
            "resource_type": "containerinstance"
          },
          "resource": ["repos"]
        }
      }
    }
  ],
  "evaluation": {
    "require_human_principal_coverage": true,
    "require_workload_principal_coverage": true,
    "min_confidence": "identity_match_with_residual"
  }
}
```

`set_summary` output:

```json
{
  "set_summary": {
    "intent": "install_validation",
    "product_or_service": "container image pull from OCIR",
    "total_searches": 2,
    "required_searches": 2,
    "matched_required_searches": 1,
    "missing_required_searches": ["container-runtime"],
    "human_principal_coverage": "present",
    "workload_principal_coverage": "ambiguous",
    "service_principal_coverage": "not_requested",
    "tag_condition_coverage": "not_requested",
    "missing_or_ambiguous_items": [
      {
        "search_id": "container-runtime",
        "reason": "Matched resource-principal type, but residual request.operation condition was not evaluated."
      }
    ],
    "likely_ready": "unknown",
    "confidence": "medium"
  }
}
```

`set_summary` fields:

- `total_searches`: count of searches in the set.
- `required_searches`: count of searches marked `required`.
- `matched_required_searches`: required searches with acceptable matches.
- `missing_required_searches`: required search IDs with no acceptable match.
- `human_principal_coverage`: whether user/group requirements appear present.
- `workload_principal_coverage`: whether resource or instance principal requirements appear present.
- `service_principal_coverage`: whether service principal requirements appear present.
- `missing_or_ambiguous_items`: actionable gaps for humans and AI agents.
- `likely_ready`: `yes`, `no`, or `unknown`; this should stay conservative when residual conditions are not fully evaluated.
- `confidence`: high-level confidence for the set result.

## History Search

Use history search to run the same search or search set against two snapshots.

Input:

```json
{
  "query_type": "set",
  "query": {
    "intent": "install_validation",
    "product_or_service": "container image pull from OCIR",
    "searches": [
      {
        "search_id": "container-runtime",
        "label": "Container instance resource principal can pull images",
        "required": true,
        "query": {
          "mode": "advanced",
          "detail_level": "simple",
          "filters": {
            "principal": {
              "principal_type": "resource-principal",
              "resource_type": "containerinstance"
            },
            "resource": ["repos"]
          }
        }
      }
    ]
  },
  "left": {
    "source": "as_of",
    "as_of": "2026-05-15T00:00:00Z"
  },
  "right": {
    "source": "current"
  },
  "diff_mode": "statement_identity"
}
```

Expected output:

```json
{
  "left_count": 11,
  "right_count": 12,
  "added_count": 1,
  "removed_count": 0,
  "modified_count": 0,
  "unchanged_count": 11,
  "added_statements": [
    {
      "policy_name": "OCIRContainerRuntimeAccess",
      "statement_text": "allow any-user to read repos in tenancy where request.principal.type = 'containerinstance'"
    }
  ],
  "left_snapshot_metadata": {
    "source": "cache",
    "cache_name": "tenancy_2026-05-14-23-45-00-UTC",
    "confidence": "high"
  },
  "right_snapshot_metadata": {
    "source": "current"
  }
}
```

## Data Operations

List available caches:

```json
{
  "operation": "list_caches",
  "tenancy_name": "andgre5678"
}
```

Reload data and persist a fresh cache:

```json
{
  "operation": "reload"
}
```

Expected reload output includes status, counts, `data_as_of`, and the cache name when a new cache is saved.

Reliable cache creation options:

- Restart the desktop, web, or MCP process on a scheduled interval.
- Call MCP `reload` externally from a scheduler.
- Use a future reload policy setting at application startup or MCP server startup.

Automatic reload policies are a roadmap item. History search should report the cache selected for `as_of` and the confidence that it represents the requested time.
