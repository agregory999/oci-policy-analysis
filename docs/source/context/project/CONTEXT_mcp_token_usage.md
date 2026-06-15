# Context: MCP Token Usage and Policy Search Revamp

Date: 2026-06-15

This document is the planning brief for the `feature/mcp-token-usage` branch. The branch started as a token-usage reduction effort for MCP tools, but the design has expanded into a broader search revamp:

- keep MCP tool definitions concise enough for AI agents to use reliably
- replace many narrow tools with a small number of meta-tools
- make policy search understand both human and workload principals
- support grouped searches for OCI service/product installation validation
- compare policy search results across historical cache snapshots
- keep desktop, web, and MCP backed by the same service tier

No implementation should start from this plan until the examples and contracts below are reviewed and accepted.

## 1. Design Principles

- **One search model, multiple surfaces.** Desktop, web, and MCP should call the same application service layer. MCP may use compact request/response schemas, but behavior should be shared.
- **Small MCP schema, rich service model.** MCP tool definitions should route the AI agent. Detailed examples belong in docs, not long tool descriptions.
- **`subject` means text.** `subject_text` should be raw/string search over statement subject text. It should not carry normalized identity semantics.
- **`Principal` means understood context.** A `Principal` selector should represent human users/groups, service principals, dynamic groups, resource principals, and instance principals.
- **Workload principal matching must expose confidence.** Dynamic group rules and `any-user` where clauses often provide evidence rather than proof. Results must distinguish exact matches, identity matches with residual conditions, broad matches, and ambiguous matches.
- **Search sets are first-class.** OCI service installation and operation usually require a mix of human and workload principals. Validation needs a set of related searches, not only one search call.
- **History compares search results.** Historical search should run the same `policy_search` or `policy_search_set` request against two snapshots and diff the resulting statement sets.
- **This is a breaking change.** It is acceptable to change models and UI flow as long as the change is intentional, tested, documented, and migration/compatibility choices are explicit.

## 2. Token Baseline

The current registered MCP tools live in [`src/oci_policy_analysis/mcp_server.py`](../../../src/oci_policy_analysis/mcp_server.py). For FastMCP 2.12.5, client-visible input schema is exposed by the tool object's `parameters` field and output schema by `output_schema`.

Token counts below reflect the current branch state, not the proposed future meta-tool set. Counts use `tiktoken` 0.13.0. `o200k_base` is the primary baseline; `cl100k_base` was effectively the same for these schemas.

| Snapshot | Encoding | Tools | Total | Avg/tool | Max/tool | Description | Input schema | Output schema |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current branch | `o200k_base` | 9 | 1,594 | 177.1 | 542 | 181 | 1,153 | 260 |
| Current branch | `cl100k_base` | 9 | 1,597 | 177.4 | 543 | 183 | 1,154 | 260 |

Current optimization choices already applied on this branch:

- MCP tool descriptions were reduced to routing-level text.
- MCP output annotations were loosened to generic `dict` / `list[dict]` shapes so FastMCP does not emit full response-model schemas.
- `filter_policy_statements` uses a compact MCP-only input model instead of the broad `PolicySearch`.
- Common model class docstrings and annotations were made terse.

The next phase should preserve this budget discipline while replacing narrow tools with higher-value meta-tools.

Target after the final meta-tool design:

- total registered tool-definition budget <= 4,000 `o200k_base` tokens
- no single tool > 1,200 `o200k_base` tokens
- tool descriptions short enough that an AI agent can decide routing quickly

## 3. Proposed MCP Tool Set

Replace the current collection of narrow tools with a smaller set of meta-tools. This branch is allowed to make breaking MCP changes, and the next pip release should replace the existing MCP tools rather than carry legacy wrappers.

Implementation note (2026-06-15): the MCP server now advertises only the six compact tools below. Legacy tool function bodies remain in `mcp_server.py` as internal compatibility helpers, but they are no longer registered with FastMCP. The regenerated packaged `mcp_tools.json` is about 1,775 `o200k_base` tokens.

| Tool | Purpose | Agent routing cue |
| --- | --- | --- |
| `policy_search` | Run one policy search in simple or advanced mode. | "Find/show/list policies", "what policies allow..." |
| `policy_search_set` | Run multiple related searches and summarize coverage. | "validate", "install", "configured correctly", "troubleshoot service setup" |
| `policy_history_search` | Run a search or search set against two snapshots and diff results. | "changed since", "compare to last month", "what is new/removed" |
| `identity_search` | Resolve users, groups, dynamic groups, and membership. | "find user/group/dynamic group", "who is in group", "groups for user" |
| `data_operations` | Data status, cache listing, cache metadata, load cache, reload. | "reload", "current data", "list caches", "what snapshot" |
| `cross_tenancy_search` | Alias listing and alias-related cross-tenancy policy search. | "define/admit/endorse", "cross-tenancy alias" |

Why this set:

- It reduces schema/token overhead by avoiding many small overlapping tools.
- It gives the AI agent clear routing categories.
- It maps to the likely user workflow: resolve identities, search policies, validate a set, compare history, manage data.

Search-set templates are a good follow-on feature, but not required for the first implementation. Future templates could mimic OCI Console policy wizards, while improving on them by checking existing statements instead of only generating a fresh set of suggested policies.

## 4. Core Search Concepts

### 4.1 Subject vs Principal

`subject_text` is a simple text search over the policy subject/raw statement.

`principal` is a structured selector with normalized intent. It should support:

```text
principal_type:
  user
  user-id
  group
  group-id
  dynamic-group
  dynamic-group-id
  service
  any-user
  any-group
  resource-principal
  instance-principal

principal_key: optional canonical key
domain_name: optional identity domain
name: optional display/name value
ocid: optional OCID for id-based principals or resource identity
display_name: optional label
resource_type: optional request.principal.type or resource kind
compartment_ocid: optional principal/resource compartment OCID
dynamic_group_name: optional dynamic group name for workload searches
dynamic_group_ocid: optional dynamic group OCID for workload searches
match_mode: auto | subject | condition | dynamic_group_rule
```

Canonical key examples:

```text
group:Default/Administrators
group-id:ocid1.group.oc1..aaaa
dynamic-group:Default/MyInstances
dynamic-group-id:ocid1.dynamicgroup.oc1..aaaa
service:None/objectstorage
resource-principal:containerinstance/ocid1.computecontainerinstance...
resource-principal:containerinstance/compartment:ocid1.compartment...
instance-principal:instance/ocid1.instance...
instance-principal:instance/compartment:ocid1.compartment...
```

For workload principals, the part before `/` is the resource or principal type being constrained. The part after `/` is the match scope:

- raw OCID: a specific resource principal or instance
- `compartment:<ocid>`: principals of that type in a compartment
- `*`: all principals of that type, useful only when the caller intentionally wants a broad search

The canonical key should encode only principal type plus one primary match scope. It should not try to encode arbitrary compound where clauses. Additional fields such as `compartment_ocid`, tag values, or operation constraints should remain on the `Principal` selector or in condition evidence.

Examples:

```text
resource-principal:containerinstance/compartment:ocid1.compartment...
```

means any container instance resource principal in that compartment, normally represented in policy by `request.principal.type = 'containerinstance'` plus `request.principal.compartment.id = '<compartment_ocid>'`.

```text
instance-principal:instance/compartment:ocid1.compartment...
```

means instances in that compartment, normally represented by a dynamic group rule using `instance.compartment.id`.

When both a specific resource OCID and a compartment OCID are known, prefer the specific-resource canonical key and keep `compartment_ocid` as supporting context:

```json
{
  "principal_type": "instance-principal",
  "resource_type": "instance",
  "ocid": "ocid1.instance.oc1..example",
  "compartment_ocid": "ocid1.compartment.oc1..app"
}
```

Normalization derives:

```text
instance-principal:instance/ocid1.instance.oc1..example
```

### 4.2 Principal Key Derivation, Validation, and Logging

Callers should not have to construct `principal_key` for normal structured workload searches. The API should accept either:

- a canonical `principal_key`
- structured fields such as `principal_type`, `resource_type`, `ocid`, and `compartment_ocid`

Normal UI and agent examples should prefer structured fields. A caller may provide both a key and fields for debugging or compatibility, but the normalizer must parse the key and verify the fields agree. Conflicts should be validation errors, not fuzzy matches.

Initial derivation rules:

- `resource-principal` requires `resource_type` and exactly one primary scope: `ocid`, `compartment_ocid`, or `principal_key`.
- `instance-principal` defaults `resource_type` to `instance` when omitted and requires exactly one primary scope: `ocid`, `compartment_ocid`, or `principal_key`.
- If both `ocid` and `compartment_ocid` are provided without `principal_key`, the specific OCID is the primary scope and `compartment_ocid` remains supporting context.
- If `principal_key` is supplied with `ocid` or `compartment_ocid`, the key scope must match those fields.
- Broad workload searches should require an explicit broad key such as `resource-principal:containerinstance/*`; missing OCID fields should not imply broad scope.
- Canonical keys should not encode multiple where-clause atoms. Extra request, tag, operation, or target-resource constraints remain residual condition evidence.

Recommended logging point:

- The shared repository path is the right checkpoint because MCP, web, desktop, and future consumers may validate inputs differently.
- `filter_policy_statements` in `src/oci_policy_analysis/application/core/repo/policy_analysis_repository.py`, or a helper it calls, should log the final normalized principal search plan after model validation and key derivation, before statement matching begins.
- For now, emit this at `WARNING` so test and external MCP runs clearly show what is being searched. Once INFO/DEBUG logging is cleaned up, downgrade this to `INFO`.
- Log only the safe normalized plan: search id when present, principal type, derived or supplied `principal_key`, resource type, primary scope, match mode, and expected evidence source. Avoid logging full statement payloads or raw recursive where-clause text as part of this warning.

Example log shape:

```python
logger.warning("Policy search principal plan: %s", safe_principal_plan)
```

For `policy_search_set`, log one normalized plan per child search so a multi-search service installation check can be traced without guessing which principal key was used.

### 4.3 Workload Principal Styles

OCI workload access appears in two major styles:

- **Dynamic group style:** policy subject is `dynamic-group` or `dynamic-group-id`; the dynamic group matching rule determines whether a resource is a member.
- **Any-user/resource-principal style:** policy subject is `any-user` or `any-group`; the where clause constrains `request.principal.*`.

Both can have additional where-clause conditions. For example:

```text
allow dynamic-group MyInstances to use objects in compartment App
  where request.operation = 'GetObject'
```

```text
allow any-user to use repos in tenancy
  where all {
    request.principal.type = 'containerinstance',
    request.principal.id = 'ocid1.computecontainerinstance...',
    request.operation = 'PullImage'
  }
```

The search service should separate:

- identity evidence: `request.principal.type`, `request.principal.id`, `request.principal.compartment.id`, dynamic group rule evidence
- residual conditions: operation, target resource, network source, tags, time, unsupported recursive clauses, or any condition not proven as principal identity

### 4.4 Match Confidence

Every advanced principal/workload result should carry confidence:

| Confidence | Meaning |
| --- | --- |
| `exact` | Principal identity matched and no residual conditions remain. |
| `subject_match_with_conditions` | Subject principal matched, but statement has extra where-clause constraints. |
| `identity_match_with_residual` | `request.principal.*` identity evidence matched, but other where-clause constraints remain. |
| `rule_evidence` | Dynamic group rule appears compatible, but full rule evaluation was not performed. |
| `broad` | `any-user` / `any-group` match lacks enough principal constraints. |
| `ambiguous` | Condition structure or dynamic fields are too complex for current extraction. |

Initial implementation should use shallow condition extraction. It should not claim full recursive where-clause evaluation. Existing tag-based condition parsing can be reused later or selectively where it is already reliable.

### 4.5 Parsed Condition and Rule Structures

The first implementation should start storing parsed structure before depending on that structure for search correctness.

For policy statements, add a top-level where-clause structure to statement JSON:

```text
where_clause:
  raw_text
  parse_status: parsed | partial | unsupported | absent
  structure: optional parsed tree
  atoms:
    left
    operator
    right
    normalized_left
    value_type
    evidence_kind
  residual_text
  warnings
```

This should reuse the existing tag-condition parsing knowledge where practical, especially left-hand/right-hand extraction and recognized condition kinds. The first pass should expose this in JSON and UI for observation, not make advanced searches depend on it.

For dynamic groups, follow the same pattern. Store a parsed matching-rule structure in the dynamic group JSON:

```text
matching_rule:
  raw_text
  parse_status: parsed | partial | unsupported | absent
  structure: optional parsed tree
  atoms:
    left
    operator
    right
    normalized_left
    value_type
    evidence_kind
  warnings
```

The first pass should display this structure and use only conservative evidence. Full dynamic group rule evaluation and filtering against arbitrary rule structure should be a later step after the parsed data has been exercised in the UI.

## 5. Tool Contract: `policy_search`

Purpose: run one policy search. `simple` mode is for common lookup. `advanced` mode adds principal evidence, workload identity handling, tag/condition evidence, and confidence.

Input shape:

```text
mode: simple | advanced
detail_level: summary | simple | full
filters:
  text: optional list[str]
  statement_text: optional list[str]
  policy_name: optional list[str]
  verb: optional list[inspect | read | use | manage]
  resource: optional list[str]
  permission: optional list[str]
  effective_path: optional list[str]
  compartment_path: optional list[str]
  subject_text: optional list[str]
  principal: optional Principal
  principals: optional list[Principal]
  condition: optional ConditionSearch
limit: optional int
```

`limit` semantics:

- `limit` is the maximum number of detailed statement rows returned, not the maximum number of statements evaluated.
- Default should be 50.
- Server should clamp values above 50 to 50 until protocol/payload testing proves a larger safe value.
- If total matches are less than or equal to `limit`, return requested detail level.
- If total matches exceed `limit`, return summary/breakdowns plus bounded sample rows.
- `detail_level: full` still respects `limit`; it should not stream unbounded full statement payloads.

Simple result shape:

```text
response_type: summary | simple | full
total_count: int
statements:
  policy_name
  compartment_path
  statement_text
  subject_text
  principal_summary
  verb
  resource
  effective_path
  where_clause_text
  match_confidence
breakdowns:
  by_policy
  by_subject_type
  by_verb
  by_resource
warnings: list[str]
```

Advanced result shape:

```text
response_type: summary | simple | full
total_count: int
statements:
  statement_text
  full_statement optional
  normalized_principals
  principal_evidence
  where_clause
  condition_atoms
  tag_conditions
  dynamic_group_rule_evidence
  residual_conditions
  match_confidence
warnings: list[str]
```

### Example: Statement Text Search

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

Expected behavior: text-focused search. It does not require identity interpretation.

### Example: Human Principal Search

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
  }
}
```

Expected behavior: match policies for the group and equivalent group-id references where identity data supports equivalence.

### Example: Resource Principal, Any-User Style

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
  }
}
```

Expected behavior:

- search `any-user` / `any-group` statements
- derive `resource-principal:containerinstance/ocid1.computecontainerinstance.oc1..example`
- extract `request.principal.type = 'containerinstance'`
- extract `request.principal.id` if present
- return residual where-clause conditions separately
- confidence is `exact` only when all conditions are identity conditions and they match

### Example: Resource Principal, Compartment Scope

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

- search `any-user` / `any-group` statements
- derive `resource-principal:containerinstance/compartment:ocid1.compartment.oc1..app`
- treat `request.principal.type = 'containerinstance'` and `request.principal.compartment.id = '<compartment_ocid>'` as identity evidence
- return `exact` only if no non-identity where-clause atoms remain
- return `identity_match_with_residual` if other conditions, such as `request.operation`, remain

### Example: Instance Principal, Dynamic Group Style

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "principal": {
      "principal_type": "instance-principal",
      "resource_type": "instance",
      "ocid": "ocid1.instance.oc1..example",
      "compartment_ocid": "ocid1.compartment.oc1..app",
      "match_mode": "auto"
    }
  }
}
```

Expected behavior:

- derive `instance-principal:instance/ocid1.instance.oc1..example`
- search dynamic groups whose matching rules mention `instance.id`, `instance.compartment.id`, or related resource principal evidence
- search statements for matching dynamic group subjects
- separately evaluate the statement where clause for residual conditions
- confidence is usually `rule_evidence` unless the dynamic group rule is fully evaluated

### Example: Instance Principal, Compartment Scope

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

- derive `instance-principal:instance/compartment:ocid1.compartment.oc1..app`
- search dynamic groups whose matching rules mention `instance.compartment.id = '<compartment_ocid>'`
- search policies for those dynamic groups
- keep statement where-clause conditions separate from dynamic group membership evidence
- return `rule_evidence` unless dynamic group rule evaluation is implemented for the matched pattern

### Example: Tag-Based Advanced Search

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

Expected behavior: reuse existing tag-condition parsing where available. Return parsed tag evidence and residual conditions. Do not require full recursive condition support in the first implementation.

## 6. Tool Contract: `policy_search_set`

Purpose: run a named set of related policy searches and summarize coverage. This supports the reality that OCI services/products often need human principals, service principals, workload principals, dynamic groups, and tag/condition constraints to work together.

Input shape:

```text
intent: install_validation | access_review | workload_analysis | custom
product_or_service: optional string
searches:
  search_id: string
  label: string
  required: bool
  query: PolicySearchRequest
evaluation:
  require_human_principal_coverage: bool
  require_workload_principal_coverage: bool
  require_service_principal_coverage: bool
  require_tag_condition_coverage: bool
  min_confidence: exact | identity_match_with_residual | rule_evidence | broad
```

`set_summary` fields:

```text
intent
product_or_service
total_searches
required_searches
matched_required_searches
missing_required_searches
human_principal_coverage: present | missing | not_requested | ambiguous
workload_principal_coverage: present | missing | not_requested | ambiguous
service_principal_coverage: present | missing | not_requested | ambiguous
tag_condition_coverage: present | missing | not_requested | ambiguous
added_warnings: list[str]
missing_or_ambiguous_items: list[dict]
likely_ready: true | false | unknown
confidence: high | medium | low
```

Example:

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
            "resource_type": "containerinstance",
            "ocid": "ocid1.computecontainerinstance.oc1..example"
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

Example response summary:

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

## 7. Tool Contract: `policy_history_search`

Purpose: run the same search or search set against two data snapshots and compare results.

Input shape:

```text
query_type: single | set
query: PolicySearchRequest | PolicySearchSetRequest
left:
  source: current | cache | as_of
  cache_name: optional string
  as_of: optional datetime
right:
  source: current | cache | as_of
  cache_name: optional string
  as_of: optional datetime
diff_mode: statement_identity | full_fields | permissions
```

Cache matching rules for `as_of`:

- prefer cache `captured_at`
- fall back to cache `data_as_of`
- fall back to timestamp embedded in `combined_cache_<tenancy>_<date>.json`
- choose the latest cache at or before `as_of`
- if no prior cache exists, choose the earliest after snapshot with low confidence
- return bracketing cache metadata so users know the estimate window

Example:

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

Example response summary:

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

Diff identity rules:

1. Prefer `stable_key`.
2. Fall back to `internal_id`.
3. Fall back to normalized statement identity: policy, compartment, principal/subject, location, conditions, comments.
4. Compare fields to classify shared identities as `modified`.

## 8. Tool Contract: `data_operations`

Purpose: manage data state and cache visibility without mixing that concern into policy semantics.

Input shape:

```text
operation:
  get_status
  list_caches
  cache_metadata
  load_cache
  reload
cache_name: optional string
tenancy_name: optional string
```

Example: list caches

```json
{
  "operation": "list_caches",
  "tenancy_name": "andgre5678"
}
```

Example response:

```json
{
  "operation": "list_caches",
  "caches": [
    {
      "cache_name": "andgre5678_2026-06-14-23-45-00-UTC",
      "tenancy_name": "andgre5678",
      "captured_at": "2026-06-14T23:45:00Z",
      "data_as_of": "2026-06-14T23:44:51Z",
      "preserved": false,
      "approximate_age_days": 1
    }
  ]
}
```

Example: reload

```json
{
  "operation": "reload"
}
```

Response should include status, counts, `data_as_of`, and saved cache name when reload persists a new cache.

Reliable history depends on regularly creating cache snapshots. Supported approaches should be documented:

- restart the program on a known interval when startup loads and persists fresh data
- call `data_operations` with `operation: reload` from an external scheduler such as cron, launchd, systemd timer, or an orchestration job
- run the MCP server in an environment where an external scheduler can call the reload operation and archive the resulting cache metadata

A built-in reload policy is a roadmap item. It could be configured from desktop UI, web startup, or MCP server startup to reload nightly, weekly, or at another interval, but this should come after the explicit reload/cache listing/history search behavior is stable.

## 9. Identity and Cross-Tenancy Consolidation

### `identity_search`

Consolidate:

- `search_users`
- `search_groups`
- `search_dynamic_groups`
- `get_groups_for_user`
- `get_users_for_group`

Input shape:

```text
operation: search | members_for_group | groups_for_user
entity_types: optional list[user | group | dynamic-group]
domain_name: optional list[str]
name: optional list[str]
ocid: optional list[str]
matching_rule: optional list[str]
in_use: optional bool
principal: optional Principal
```

### `cross_tenancy_search`

Consolidate:

- `cross-tenancy-alias-list`
- `cross-tenancy-policies-by-alias`

Input shape:

```text
operation: list_aliases | policies_by_alias | search
alias: optional str
statement_text: optional list[str]
principal: optional Principal
```

## 10. Application Architecture Plan

Implementation should proceed in this order:

0. **Package Structure Cleanup**
   - Finish moving domain/application code into `oci_policy_analysis.application`.
   - Treat this as preparatory work before the search/MCP model split, because otherwise the new models and services will be added to packages that are already slated to move.
   - Keep the moves mechanical first: preserve behavior, update imports, run focused tests, and avoid mixing package moves with feature changes.

   Proposed target layout:

   ```text
   oci_policy_analysis/
     application/
       core/
         models/          # current common models
         repo/            # repositories
         engine/          # analysis/simulation/intelligence engines
         parser/          # policy and condition parsers
         resources/       # permissions JSON, mcp tool fixtures, parser assets
         support/         # logger, config, cache, usage tracking, helpers
       services/          # application services used by CLI/MCP/web/desktop
       context.py
       post_load.py
     presentation/
       formatters.py
       desktop/           # current ui package
       web/               # current web package
     analytics/
     cli.py
     main.py              # desktop entrypoint shim
     mcp_server.py        # MCP entrypoint shim
   ```

   Specific package decisions:

   - Move `common/models*.py` under `application/core/models`.
   - Move `common/logger.py`, `config.py`, `caching.py`, `usage_tracking.py`, and remaining helper utilities under `application/core/support` or another clearly named support package.
   - Fold remaining `logic` package assets into `application/core/resources`; update `pyproject.toml` package-data paths and all `importlib.resources` callers.
   - Remove `consumers` unless the sample apps are still useful as docs examples. If retained, move them outside the importable package or into docs/examples.
   - Move current `presentation/formatters.py` under `application/presentation` or keep `presentation` top-level as the UI boundary, but do not leave formatter code importing back through `common`.
   - Move current `ui` under `presentation/desktop`.
   - Move current `web` under `presentation/web`.
   - Keep top-level console-script entrypoints as thin compatibility shims so pip commands do not expose the internal package layout.

   Migration order:

   1. Move packaged resources and update `pyproject.toml`.
   2. Move models and add temporary import shims if needed.
   3. Move support utilities and update internal imports.
   4. Move presentation packages (`ui`, `web`, formatters).
   5. Remove `consumers` or move examples out of package.
   6. Update docs/API references and packaging tests.
   7. Remove compatibility shims once tests and external entrypoints are stable.

   This is also a breaking-change branch, so internal imports can change aggressively. Public console scripts should remain stable.

1. **Models**
   - Expand `Principal` into a normalized selector/context model.
   - Add canonical principal-key derivation and compatibility validation for structured workload principal selectors.
   - Add request/result models for `PolicySearchRequest`, `PolicySearchSetRequest`, `PolicyHistorySearchRequest`, and data operations.
   - Add evidence/result models for principal evidence, condition atoms, residual conditions, dynamic group rule evidence, and match confidence.
   - Add serialized where-clause and dynamic-group matching-rule structures for JSON output, even before those structures drive filters.

2. **Parsing and Evidence Extraction**
   - Add shallow `request.principal.*` atom extraction.
   - Add statement where-clause structure extraction using existing tag parser knowledge where safe and bounded.
   - Add dynamic group matching-rule structure extraction and conservative evidence extraction.
   - Preserve raw where clause text and residual conditions.
   - Do not require full recursive where-clause or dynamic-group rule evaluation in the first implementation.

3. **Service Tier**
   - Create or extend a policy search service with `simple_search`, `advanced_search`, `search_set`, and `history_search`.
   - Keep repository filtering focused and avoid duplicating web/desktop/MCP logic.
   - Ensure the final normalized principal plan is logged at `WARNING` in the repository filtering path before matching begins.
   - Add cache metadata and cache selection helpers for history search.

4. **Desktop UI Consolidation**
   - Consolidate instance principal, resource principal, and tag-based access workflows into a Workload Principals/Search surface.
   - Show identity evidence, tag evidence, parsed where-clause structure, parsed dynamic-group rule structure, residual where clause, confidence, and raw statement text.

5. **Web UI Consolidation**
   - Add equivalent Workload Principals/Search page.
   - Reuse service endpoints and result shapes used by desktop.

6. **MCP Surface**
   - Surface compact meta-tools after the service tier is stable.
   - Keep tool descriptions terse and route-focused.
   - Keep detailed examples in `docs/source/mcp.md`.
   - Replace the old MCP tools in the next pip release rather than preserving wrappers.

7. **Documentation**
   - Update MCP docs with final tool contracts and examples.
   - Update historical-analysis docs to explain search-result diffs.
   - Update UI docs for consolidated workload principal search.

8. **Packaging and External Validation**
   - After tests pass, commit the branch.
   - Build/install into the local virtual environment and package for pip.
   - Test from external MCP clients using the packaged install, not only in-process imports.

## 11. Testing Plan

Required test coverage:

- token-budget measurement for live MCP tools or saved tools/list artifact
- model validation for expanded `Principal`
- principal-key derivation from structured resource-principal and instance-principal selectors
- validation failure when supplied `principal_key` conflicts with structured fields
- repository warning log includes final normalized principal key/search plan before matching
- simple policy search with statement text and subject text
- human principal search with name and id equivalence
- service principal search
- resource-principal any-user style with:
  - exact identity-only where clause
  - identity plus residual condition
  - broad any-user without principal constraints
  - ambiguous or unsupported condition structure
- instance-principal dynamic group style with:
  - instance OCID rule evidence
  - compartment OCID rule evidence
  - dynamic group subject plus statement where clause
- serialized where-clause structure is present on statement JSON when parsing succeeds or partially succeeds
- serialized dynamic-group matching-rule structure is present on dynamic group JSON when parsing succeeds or partially succeeds
- tag-condition search using existing parser behavior
- search set summaries and missing coverage
- history search added/removed/modified/unchanged behavior
- cache metadata and cache bracketing for `as_of`
- explicit reload creates or reports a fresh cache snapshot with metadata
- desktop/web API route coverage for consolidated pages
- MCP schema budget stays within target
- MCP tool routing examples remain accurate

## 12. Decisions and Roadmap

Resolved decisions for this branch:

- This is a breaking MCP change. Replace the current MCP tools with the new compact meta-tools in the next pip release.
- `policy_search_set` should initially accept caller-provided searches. Predefined templates are useful, but should be a future iteration.
- Where-clause parsing should move toward a shared statement JSON structure. The first pass should parse/store/display the structure and atoms, not rely on it for complex filters yet.
- Dynamic group matching-rule parsing should follow the same path: parse/store/display structure and atoms first, then evaluate richer search/filter behavior later.
- Historical comparison depends on reliable cache snapshots. The first pass should document explicit reload and cache-listing operations, plus operational ways to invoke reload on an interval.

Roadmap items:

- Add `policy_search_set` templates for common OCI services/products.
- Consider templates that mimic OCI Console policy wizards, while also checking existing statements so users know what is already present.
- In workload-principal UI result tables, avoid blank confidence cells when broad `any-user`/`any-group` browsing has not run a specific workload-principal match scorer; show `Not scored` or hide the confidence column until a workload selector is active.
- Add full or bounded recursive where-clause evaluation once the parsed statement JSON has been tested in the UI.
- Add full or bounded dynamic group rule evaluation once parsed dynamic group JSON has been tested in the UI.
- Add a configurable reload policy from desktop UI, web startup, or MCP server startup for nightly, weekly, or custom-interval cache creation.
