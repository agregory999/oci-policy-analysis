# Embedding and Integrating OCI Policy Analysis

## Deploy web or MCP directly on OCI

OCI Policy Analysis supports a ready-to-run **web application, MCP server, or
combined web/MCP deployment on OCI Container Instances using Resource Principal**.
Choose this first when you want a hosted interface or agent endpoint over tenancy
data: no custom Python wrapper or user API key in the running container is needed.
Grant the workload the required read/inspect permissions and configure networking
for the clients and OCI APIs it must reach.

Follow [Setup](setup.md#containerized-mcp-on-oci-container-instances) for workload
permissions and MCP configuration. The canonical
[run and deployment guide](https://github.com/agregory999/oci-policy-analysis/blob/main/run/README.md#container-instances)
covers web, MCP, and combined deployments, source versus published-release images,
health checks, and explicit replacement/rollback. Use the operations guide from
the same Git revision as your deployment. Deployment scripts manage the named
Container Instance; IAM, registry, network, Load Balancer, and backends are
configured separately. Image or runtime changes use delete/create replacement
with downtime.

### Choose deployment or embedding

| Pattern | What you run | Authentication | What you supply |
| --- | --- | --- | --- |
| Hosted web or MCP | Packaged application on OCI Container Instances | Resource Principal | Workload IAM, runtime settings, networking and durable retention if required |
| Custom OCI Function | Python core and focused services inside your own function image | Function Resource Principal | Function handler, schedule, capacity/timeout validation, output storage and delivery |
| Scheduled job on an OCI VM | CLI or Python core, optionally alongside a standalone MCP process | Instance Principal | Scheduler, job locking, snapshot retention and report delivery |
| Offline integration | Python core over saved combined-cache JSON | No OCI authentication for offline loads | Input snapshots, analysis options and output handling |

The Function and scheduled-job patterns below are integration recipes, not
packaged function deployments or a built-in scheduling service. Oracle documents
[Function resource-principal access](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsaccessingociresources.htm)
and [recurring Function invocation through Resource Scheduler](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionsschedulingfunctions-about.htm).
A Function starts a bounded analysis job; a web/MCP container keeps a service
available between requests. Size the job for actual tenancy collection and
analysis time; use a VM or other worker when that exceeds the function's limits.

## The current analysis snapshot

The in-memory repository and its cache/export representation are analysis
snapshots. They are intentionally allowed to contain incomplete, unresolved,
or invalid data. For example, a policy can be retained with validation findings
so a caller can find and correct it rather than silently losing it during load.

An integration must therefore preserve the distinction between:

- a successful load and a complete load;
- no matching policy and an indeterminate result caused by incomplete data;
- a normalized statement and an OCI-authoritative authorization decision.

See [reference catalog coverage](reference_catalog.md) for resources without
published mappings, conditional API requirements and reviewed corrections.

Treat validation findings, load warnings, collection timestamp, source mode,
and any scope limits as output that belongs beside the requested result.

## Saved snapshot compatibility in 7.0

The combined-cache format is unchanged from 6.5.7: `version: 2`, with current
writers using `schema_version: 3`. The existing `policies` and `policy_statements`
sections remain required. Optional inventory and metadata fields retain their
existing defaults, so older snapshots using the supported structure can load
without a fresh OCI collection. This does not add support for formats that 6.5.7
already rejected.

Regular and cross-tenancy corpora, intelligence overlays, and the permissions
report are rebuilt at runtime; they are not added to the combined-cache payload.
Statement records can contain updated derived fields, including canonical
principal keys and structured association endpoints. Original statement text
remains available. For old cross-tenancy association records without complete endpoint
structure, corpus construction reparses the source text on a detached copy;
it does not rewrite the cache file.

The breaking change is the removal of the former `common` and `logic` Python
import packages (and the legacy top-level `web` aliases), not a requirement to discard saved tenancy data. Callers should
migrate imports and run the appropriate post-load profile after loading. Changes
in validation, permission mappings, and analysis can legitimately change derived
results when the same snapshot is processed by a newer version.

## Python embedding

The [application core API reference](api/oci_policy_analysis.application_core.rst)
documents the context, load, query, report and historical-analysis services used here.

Constructing `AppContext` loads bundled reference data but does not authenticate,
collect tenancy data, or compile a corpus. `LoadService` replaces the active
snapshot and derived engines/corpora. Read those from the current context after
each load; serialize loads, queries, and mutable analysis operations rather than
sharing a context across concurrent jobs. A fresh context per scheduled run is
the simplest boundary.

| Post-load profile | Use when | Result |
| --- | --- | --- |
| `minimal` | Focused queries, inventory reports, MCP | Query foundations and regular/cross-tenancy corpora; no full recommendation or permissions report |
| `full` | Recommendations, permissions reports, simulation workflows | Full post-load intelligence, corpora, permissions report and simulation preparation |
| `none` | Collection-only workflows | Skips enrichment; derived analysis must be prepared before use |


`AppContext` is the reusable application wiring used by non-desktop consumers.
Construct it from settings, load data through `LoadService`, then use a focused
service for the task. The service boundary is preferable to reaching directly
into UI code.

```python
from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support import config
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.application.services.mcp_query_service import MCPQueryService
from oci_policy_analysis.application.core.models.models_policy import PolicySearch

context = AppContext.from_settings(config.load_settings())
loaded = LoadService(context).load_from_cache('my-tenancy-cache', post_load_profile='minimal')
if not loaded.success:
    raise RuntimeError(loaded.message)

statements = MCPQueryService(context).filter_policy_statements(PolicySearch(resource=['buckets'], verb=['read']))
```

Use the current context and services rather than presentation modules or
private helpers. The former top-level `oci_policy_analysis.common` and
`oci_policy_analysis.logic` compatibility packages are removed in 7.0; import
models, repositories, and support helpers from `application.core` instead.
The top-level `oci_policy_analysis.web` aliases are also removed; ASGI integrations
should import `oci_policy_analysis.presentation.web.main:app`. The published
`oci-policy-analysis-web` command name is unchanged.
Keep integration tests close to the package version you run;
there is not yet a separately versioned plugin SDK.

### Choosing live policy discovery

Live loads support two policy discovery methods through the same detail fetch and
normalization pipeline:

```python
result = LoadService(context).load_from_tenancy(
    use_instance_principal=False,
    profile='DEFAULT',
    recursive=True,
    policy_load_method='compartment',
    post_load_profile='minimal',
)
```

`resource_search` is the default. It follows all Resource Search pages, then fetches
full policy details. `compartment` lists active policies in each loaded compartment
and fetches the same details, bypassing the policy search index. With `recursive=False`,
only the tenancy root is listed; otherwise the root and all discovered accessible
compartments are included. Identity-domain depth does not limit policy recursion.

An explicit argument overrides `settings['policy_load_method']`. When the argument
and setting are absent, older callers continue to use Resource Search. Unsupported
values raise `ValueError` before the current context is reset. The chosen method is
retained for subsequent policy-only refreshes of that live repository and cleared
when the snapshot is reset. Compartment listings and detail fetches use bounded
workers; parsing updates the repository serially. Individual failures remain in
collection diagnostics; total discovery/fetch failure is rejected rather than
accepted as an empty inventory. Success still does not establish complete coverage.
The independent defined-tag namespace catalog continues to use Resource Search.

Qt exposes **Policy loading** in **Overview & Settings → Live tenancy** only in
Advanced mode. The choice is saved locally, restored at startup, and continues to
apply if Advanced mode is hidden. The loaded snapshot coverage panel identifies
the method used. Cache/export payloads remain version 2/schema 3: this option is a
local load preference, not a new stored snapshot field, so no cache migration is
needed and offline queries never rewrite source files.

### Desktop app

The new desktop app is a modern interface around the same services used by the
original desktop app, CLI, web app, and MCP server. See the
[7.0 guide](release_7_0.md) for what's new, the
[new desktop usage guide](usage.md) for loading and evidence inspection, and
[MCP Assistant guide](mcp_assistant.md) for the managed snapshot endpoint.
The original Tkinter app remains available through
`oci-policy-analysis-legacy-ui`. Neither desktop app is required for embedding.

## Scheduled reporting and retained history

### Weekly dynamic-group review

A custom weekly job can collect IAM/policy data, find dynamic groups with no known
policy references, and write a review artifact. After the cache-load example
above, the same context supports:

```python
from oci_policy_analysis.application.core.models.models_iam import DynamicGroupSearch
from oci_policy_analysis.application.services.reports_service import ReportsService

unreferenced = MCPQueryService(context).search_dynamic_groups(DynamicGroupSearch(in_use=False))
reports = ReportsService(context)
inventory = reports.get_report('policy-inventory')
artifacts = reports.export_formats(inventory)  # json, markdown, html strings
```

`unreferenced` is input to your own report; it is not a built-in report ID.
The loaded `in_use` field means known policy-reference status, not recent use by
resources or OCI Audit activity. Missing inventory, unresolved references, or
collection failures can make absence inconclusive. Include collection scope,
load warnings, source timestamp and matching rules in the review; do not turn
this list into automatic deletion instructions. See [Reports](reports.md) for
built-in reports and their enrichment prerequisites.

For a live Function-based job, replace the offline load with:

```python
loaded = LoadService(context).load_from_tenancy(
    use_instance_principal=False,
    use_resource_principal=True,
    recursive=True,
    compartment_domain_search_depth=2,
    post_load_profile='minimal',
    save_cache_after_load=False,
)
if not loaded.success:
    raise RuntimeError(loaded.message)
```

This is the core call inside a handler you provide, not a complete Function
handler or deployment. Create the context with explicit job settings, configure
writable application storage/logging, and store outputs in your chosen durable
location. Use `full` if the requested reports require full enrichment. Domain
depth 2 covers root plus immediate children; increase deliberately for deeper
identity-domain coverage. It is independent of recursive policy loading.
On an OCI VM use `use_instance_principal=True` and
`use_resource_principal=False` instead.

### Weekly refresh with historical comparisons

1. Keep a dated baseline combined-cache export in durable storage, with the
   collection scope, timestamp, diagnostics and application version.
2. Run a scheduled collection with the same intended scope. A core/CLI job can
   save/export the new snapshot. Alternatively, an authenticated MCP client can
   request `data_operations(operation='reload')` from a **live standalone MCP
   server**. When OAuth update scopes are configured, the caller needs that scope.
3. Retain the resulting combined-cache snapshot under a new dated identity and
   check that the expected sections were actually collected. A successful reload
   and the server's current snapshot are not, by themselves, a retention policy.
4. Compare baseline and target through `HistoricalAnalysisService.compare_snapshots`
   or Qt **Historical Comparison**. Store the comparison alongside both inputs,
   then deliver the report through your own workflow.

The standalone reload path saves a cache after loading; arranging durable storage,
export/backup, unique retention names, retries and scheduling remains your job.
Container replacement or Function termination must not remove the only copy of
history. For example, an integration can explicitly upload snapshots and reports
to Object Storage, with separate write permissions for that output location.
MCP status/reload responses are summaries, not downloadable snapshot artifacts.
Serialize refreshes and readers at your orchestration boundary; the shared context
is not an automatic concurrency boundary.

Qt's embedded MCP endpoint is query-only and pins the loaded snapshot. It exposes
neither `data_operations` nor reload/history tools; stop it before loading another
snapshot. Use the standalone service or a separate collection job for unattended
refresh. See [MCP](mcp.md) and [historical analysis](usage.md#review-findings-and-plan-changes).

Once your job has read the two combined-cache JSON objects, compare them without
loading either into the active context:

```python
from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService

comparison = HistoricalAnalysisService(context.cache).compare_snapshots(
    baseline_snapshot,
    target_snapshot,
    left_name='Previous week',
    right_name='This week',
    meaningful_only=True,
)
```

Historical comparisons show differences between collected evidence, not a complete
OCI change log. Known different tenancy OCIDs are rejected; incomplete sections
remain qualified or unavailable. Meaningful mode ignores ephemeral identifiers
while retaining source changes: comment-only statement edits are modifications;
grant or condition changes appear as removal/addition. No source snapshot is
rewritten by comparison.

## Extension checklist

1. Create a context and load one input source.
2. Run the post-load profile appropriate to the caller (`minimal` for focused
   programmatic analysis; full profiles when their derived overlays are needed).
3. Query through a service or engine, retaining source statements and findings.
4. Return a task-level result plus data-quality and provenance information.
5. Test against valid, invalid, and partial snapshots.

For scripts and scheduled jobs, use the [CLI guide](cli.md). For agent-facing
queries, use the documented [MCP tools](mcp.md) instead of constructing or
mutating internal repositories. Both return analysis evidence, not an
OCI-authoritative allow/deny decision.


### Explain a run and draft scoped what-if candidates

After loading a context, use the shared workbench service for the same request
evidence shown by Qt. An explicit empty checked-ID list means no statements.
Execution appends runtime history; candidate generation does not save prospects
or change OCI. Serialize these calls with loads and prospective mutation.

```python
from oci_policy_analysis.application.services.simulation_service import SimulationService
from oci_policy_analysis.application.services.simulation_workbench_service import SimulationWorkbenchService

selection = SimulationService(context).statement_candidates(
    compartment_path='ROOT/Applications',
    principal_type='group',
    principal=('Default', 'AppDevelopers'),
)
workbench = SimulationWorkbenchService(context)
report = workbench.execute(
    {
        'principal_type': 'group',
        'principal': ('Default', 'AppDevelopers'),
        'principal_key': selection['principal_key'],
        'compartment_path': 'ROOT/Applications',
        'api_operation': 'objectstorage:CreateBucket',
        'checked_statement_ids': [row['internal_id'] for row in selection['statements'] if row['checkable']],
        'where_context': {},
    }
)
drafts = workbench.policy_candidates(
    report,
    principal_key=selection['principal_key'],
    granularity='permission',  # also resource or family
    policy_path='ROOT',
    effective_path='ROOT/Applications',
    where_clause="request.operation = 'CreateBucket'",
)
# Review drafts["candidates"], additional permissions, unmapped permissions
# and scoped corpus examples before explicitly saving through prospects.
original_runs = workbench.history()
related_choices = report['related_scenarios']
```

Use actual inventory paths/principals and catalog operation labels. History and
reports are detached copies with original inputs; runtime snapshot IDs reject
candidate generation after replacing the engine. A related operation requires a
new compartment selection, preparation and explicit run, not reuse of primary
checked IDs. Matching denies, conditions and inventory/reference coverage remain
constraints after any suggested allow. The current reverse mapping uses greedy
catalog coverage rather than proving globally minimal privilege.

## 7.0 integration changes and tag inventory

`AppContext.ai` and the desktop OCI Generative AI backend were removed in 7.0; callers
should remove AI repository/model setup. Existing saved AI settings are inert. This does
not change combined-cache version 2/schema 3 or require snapshot migration.

`TagBasedPolicyService.inventory(context.policy_repo.regular_statements)` returns detached
`statements`, `conditions` and `namespace_count` data. Predicate rows retain the full condition
and provenance; a matching atom does not establish that the complete condition passes.
No cache, source record or OCI resource is modified. Rebuild the projection after reload.

Qt desktop live loading supports config profiles (including session tokens) and Instance
Principal. A saved Resource Principal selection falls back to profile authentication; explicit
Resource Principal worker requests are rejected. Resource Principal remains supported for
container-based web/MCP and shared service callers.
