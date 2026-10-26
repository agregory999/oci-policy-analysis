(mcp-overview)=
# Model Context Protocol (MCP)

MCP connects an AI assistant to structured tools. OCI Policy Analysis provides
tools for querying policy and identity evidence, plus a reference catalog for
OCI resource types, API operations, and permissions. The model interprets the
question and chooses tool calls; the tools return data from the loaded snapshot
or bundled catalog. MCP is an integration protocol, not an OCI identity or a
source of authorization decisions.

```{toctree}
:hidden:

mcp_examples
```

This works with frontier models through clients such as Claude, ChatGPT, and
Codex. The model and client use the account, configuration, and billing already
set up by the user. See [MCP tool examples](mcp_examples.md), the
[reference catalog](reference_catalog.md), and the
[MCP Assistant guide](mcp_assistant.md).

(mcp-purpose)=
## What the tools can tell you

The tools help an assistant look up names, find policy statements, compare
related checks, resolve identities and compartments, and inspect snapshot
history. Reference tools use the bundled catalog and do not call OCI. Policy
and identity tools query the data available to the connected server.

Results are evidence from a loaded dataset, not an OCI authorization decision.
Conditions, exclusions, provenance, incomplete collection, and unmapped
permissions can affect what a result supports. Preserve those caveats when
summarizing results. See [reference catalog coverage](reference_catalog.md).

(mcp-connection-modes)=
## Choose a connection mode

| Mode | How it connects | Use it for |
| --- | --- | --- |
| Standalone STDIO | The MCP client starts `oci-policy-analysis-mcp` as a local process. | A local assistant connection using a workstation profile, session token, or saved cache. |
| Standalone Streamable HTTP | A client connects to a running MCP endpoint, commonly at `/mcp`. | Local clients connecting to a standalone server, or a secured remote service. |
| Modern desktop MCP Assistant | The desktop app serves the currently loaded snapshot over loopback HTTP. | Interactive local analysis with Claude Code, Codex, or an external desktop client. See the [MCP Assistant guide](mcp_assistant.md). |
| OCI Container Instance | A hosted Streamable HTTP server uses a Resource Principal. | A shared endpoint for clients that can reach the secured service. Follow [Containerized MCP setup](setup.md#containerized-mcp-on-oci-container-instances). |

For direct Python use of `AppContext` and application services, see
[Embedding and Integration](core_integration.md). Python embedding and MCP
deployment are separate integration patterns; the latter does not require a
custom Python wrapper.

(mcp-standalone-server)=
## Run a standalone server

Install the MCP extra and check the command options:

```bash
python -m pip install "oci-policy-analysis[mcp]"
oci-policy-analysis-mcp --help
```

The server requires one data/authentication source. For example, start a
workstation-profile STDIO server with:

```bash
oci-policy-analysis-mcp --profile DEFAULT
```

The default transport is STDIO. A desktop MCP client configuration points its
`command` to `oci-policy-analysis-mcp` and supplies `--profile DEFAULT` in
`args`; use an absolute executable path if the command is not on the client's
PATH. A saved combined cache can be used with `--use-cache CACHE_NAME` instead.
For a local HTTP server, use:

```bash
oci-policy-analysis-mcp --profile DEFAULT --transport streamable-http \
  --host 127.0.0.1 --port 8765
```

The supported sources are a named OCI profile, session token, instance
principal, resource principal, or combined cache. Live loading also requires
the OCI read/inspect permissions described in [Setup](setup.md#permissions-required).
Use `--help` for load depth, cache writing, and logging options.

HTTP deployments reachable beyond the local machine need appropriate network
controls and TLS termination. Optional OCI Identity Domain OAuth is documented
in [MCP OAuth](mcp_oauth.md). For container build and deployment steps, use the
[Containerized MCP setup](setup.md#containerized-mcp-on-oci-container-instances)
and the operations guide for the same Git revision; those procedures are kept
out of this protocol overview.

(mcp-tool-catalog)=
## Tool catalog

The server exposes focused tools with structured inputs and bounded results.
Use [MCP tool examples](mcp_examples.md) for request patterns and response
details.

| Tool | Purpose |
| --- | --- |
| `resource_reference` | Discover OCI policy resource types, families, aliases, and cumulative allow-verb mappings. |
| `operation_reference` | Find API operation names, required permissions, conditions, and unmapped requirements. |
| `permission_reference` | Reverse-map a permission to known resources, verbs, and API operations. |
| `policy_search` | Search policy statements for one question. |
| `policy_search_set` | Run and compare multiple related policy checks in one call. |
| `tag_based_policy_search` | Search parsed tag-based policy conditions. |
| `oke_workload_identity_search` | Inspect OKE workload identity and policy evidence. |
| `identity_search` | Find users, groups, dynamic groups, and compartments; inspect memberships. |
| `policy_history_search` | Compare a policy search across snapshots. |
| `cross_tenancy_search` | List aliases or find cross-tenancy statement references. |
| `data_operations` | Inspect data state, list/load caches, or reload live data when supported by the server mode. |

(reference-discovery-and-reverse-lookup)=
### Reference discovery and reverse lookup

Start with these tools when the wording in a question may not match OCI's
canonical policy type or API operation. For example, `resource_reference` can
resolve everyday wording such as “virtual machines” to catalog identifiers;
`operation_reference` can identify a qualified API operation; and
`permission_reference` can show known resource/verb associations.

The catalog is local reference data, not a complete OCI authorization engine.
Search results include source notes, coverage warnings, and explicit gaps where
no mapping is known. Exact lookup accepts identifiers and declared aliases;
search mode also ranks descriptive terms. Empty mappings do not prove a resource
or permission is absent from OCI. See [reference catalog coverage](reference_catalog.md).

(mcp-qt-assistant)=
## Desktop MCP Assistant

The desktop app can serve its loaded snapshot to MCP clients through an
explicitly started loopback endpoint. This snapshot connection is query-only;
standalone `data_operations` capabilities such as reload are not exposed. For
using the in-app Codex or Claude Code conversations, or connecting a desktop
assistant, see [MCP Assistant](mcp_assistant.md).

(mcp-data-boundaries)=
## Data and privacy boundaries

- The MCP server reads OCI using its configured profile/principal or serves the
  selected cache/snapshot. A client connection does not grant additional OCI
  access.
- A model receives the user's question and the evidence returned by requested
  tools. Review the selected model provider's account and data-handling terms.
- Tool output may contain policy text and identity data from the loaded
  snapshot. Avoid broad requests when a narrower search answers the question.
- A tool result is not a policy-engine decision. Check conditions, exclusions,
  compartment scope, collection coverage, and unmapped requirements before
  drawing conclusions.
