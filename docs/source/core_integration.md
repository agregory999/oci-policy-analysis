# Embedding and Integrating OCI Policy Analysis

OCI Policy Analysis can be used as more than a desktop application. Its core
loads, preserves, validates, and analyzes OCI IAM and policy data; the desktop
app, CLI, web application, and MCP server are first-party adapters over that
same runtime.

This guide describes the supported integration model for current data. It does
not define a persistent corpus, a valid-only data store, or a plugin system.

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

## Integration roles

| Role | Responsibility | First-party examples |
| --- | --- | --- |
| Data acquisition | Load live OCI, cache, export JSON, or CIS input into the current snapshot. | `LoadService`, CLI loading modes, MCP startup |
| Core analysis | Query parsed statements, identities, reference data, and derived findings. | application services and engines |
| Interface adapter | Translate a caller's task into core operations and present bounded results. | CLI, web, desktop, MCP |

Keep these responsibilities separate in custom integrations. A loader should
not discard invalid rows, and an interface should not reimplement policy
parsing or permission expansion.

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

Use the current context and services when embedding today. The package does not
yet promise a separate, semantically-versioned plugin SDK. Keep imports and
integration tests close to the released package version, and prefer the
documented services over presentation modules or private helper functions.

### Extension checklist

1. Create a context and load one input source.
2. Run the post-load profile appropriate to the caller (`minimal` for focused
   programmatic analysis; full profiles when their derived overlays are needed).
3. Query through a service or engine, retaining source statements and findings.
4. Return a task-level result plus data-quality and provenance information.
5. Test against valid, invalid, and partial snapshots.

## CLI as a reference adapter

The CLI is a supported adapter for scripts and scheduled jobs. Use it when a
file or terminal result is a better contract than Python objects. It provides
the normal data-loading paths and applies minimal post-load enrichment before
its analysis operations.

The CLI is also a useful reference implementation for custom hosts: load data,
run only the needed enrichment, invoke core analysis, and make failures or
incomplete data visible in output rather than treating them as empty results.
See the [CLI guide](cli.md) for commands and output formats.

## MCP as the first-party agent adapter

The MCP server is supplied by this project. It is not a package-authoring
extension mechanism. It exposes selected core capabilities as bounded,
task-level tools for MCP clients.

The current tool surface covers policy search, tag-policy search, OKE workload
identity search, related search sets, snapshot comparison, identity search,
cross-tenancy search, and data-state operations. It supports standalone STDIO,
streamable HTTP, and an embedded desktop-server mode. Its HTTP health endpoint
is `/health`.

MCP callers should use the published tool schemas rather than construct or
mutate internal repositories. In particular:

- use `policy_search` and `identity_search` for focused queries;
- use `policy_history_search` only with identified current/cache snapshots;
- use `data_operations` to inspect or change the server's loaded data state;
- treat results as bounded evidence, not an OCI authorization decision;
- protect remote HTTP deployments because the tool results can contain IAM and
  policy information.

The current MCP implementation exposes tools and a health route. It does not
register a general MCP resource catalog; documentation and integrations should
not assume one exists.

## Compatibility and change discipline

When adding a core capability, first decide which layer owns it:

- Add it to a service or engine when all adapters can share the behavior.
- Add a CLI option only when it is a command-oriented workflow.
- Add an MCP tool only when an agent needs a narrow, structured task contract.
- Do not make a data snapshot stricter merely to simplify an adapter.

For each change, document input requirements, output shape, validation and
partial-data behavior, permission/reference-data dependencies, and tests. This
keeps the current runtime useful for Functions, scripts, CLI automation, and
MCP clients while leaving persistent corpus design as a separate future
decision.
