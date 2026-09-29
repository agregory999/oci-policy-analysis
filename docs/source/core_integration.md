# Embedding and Integrating OCI Policy Analysis

OCI Policy Analysis can be used as more than a desktop application. Its core
loads, preserves, validates, and analyzes OCI IAM and policy data; the desktop
app, CLI, web application, and MCP server are first-party adapters over that
same runtime.

This guide covers the small, supported Python embedding surface for the current
analysis snapshot. It does not define a persistent corpus, plugin SDK, or OCI
authorization decision service.

## The current analysis snapshot

The in-memory repository and its cache/export representation are analysis
snapshots. They are intentionally allowed to contain incomplete, unresolved,
or invalid data. For example, a policy can be retained with validation findings
so a caller can find and correct it rather than silently losing it during load.

An integration must therefore preserve the distinction between:

- a successful load and a complete load;
- no matching policy and an indeterminate result caused by incomplete data;
- a normalized statement and an OCI-authoritative authorization decision.

Treat validation findings, load warnings, collection timestamp, source mode,
and any scope limits as output that belongs beside the requested result.

## Python embedding

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
loaded = LoadService(context).load_from_cache("my-tenancy-cache", post_load_profile="minimal")
if not loaded.success:
    raise RuntimeError(loaded.message)

statements = MCPQueryService(context).filter_policy_statements(
    PolicySearch(resource=["buckets"], verb=["read"])
)
```

Use the current context and services rather than presentation modules or
private helpers. Keep integration tests close to the package version you run;
there is not yet a separately versioned plugin SDK.

### Extension checklist

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
