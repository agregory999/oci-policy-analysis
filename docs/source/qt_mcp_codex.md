# Qt MCP and assistants

The **MCP & assistant** navigation page hosts a query-only FastMCP endpoint over
the currently loaded context, an optional native Codex conversation, and
launchers for separately configured Claude Desktop, ChatGPT Desktop, and Codex
Desktop apps. Neither server nor Codex starts when the application opens or
when a snapshot loads.

## Try it

Install the optional desktop and MCP dependencies, then launch the workbench:

```bash
uv sync --extra qt --extra mcp --extra web
.venv/bin/python -m oci_policy_analysis.presentation.qt --sample
```

1. Load sample data, OCI, a named cache, an exported snapshot, or CIS output.
2. Open **MCP & assistant**. Choose a port or use **Automatic**, then **Start MCP**.
   The listener always binds to `127.0.0.1`. The verified URL and available tools
   appear only after MCP initialization, tool discovery, and a snapshot-status
   call succeed.
3. Select **Codex · embedded chat** to use Codex. Install Codex CLI and sign in
   with `codex login` in a terminal.
   Enter `codex` or its executable's absolute path, then **Connect Codex**. The
   page reports account/configuration errors and populates a model selector.
4. Select a model and type a question, such as “Which statements reference the
   AppWorkers dynamic group?” Press **Send**. Questions and tool-returned policy
   evidence become input to the selected model. Connecting alone sends no model
   question. Account/model access and inference billing follow the user's Codex
   configuration and account.
5. **Stop answer** interrupts a turn. **Disconnect** ends the Codex child while
   leaving MCP available. **Stop MCP** disconnects Codex and stops the listener.

The upper tabs show tool descriptions and connection/tool activity. The lower
viewer streams plain selectable text, labels completed/failed/interrupted turns,
and retains bounded output. It does not interpret model/source text as HTML.

## External desktop assistants

The assistant selector offers **Claude Desktop**, **ChatGPT Desktop**, and
**Codex Desktop**, each labelled **external app**. They open a separate app;
answers and model selection stay there. Only **Codex · embedded chat** uses the
Qt conversation viewer. Application paths are kept separately for each desktop
choice during the current workbench session.

On macOS, automatic launch asks the OS to open `Claude`, `ChatGPT`, or `Codex`
respectively. If Codex is included in your ChatGPT app rather than installed as
a separate `Codex.app`, select **ChatGPT Desktop**. **Browse…** or a pasted path
can select a particular application bundle or executable. Automatic desktop
discovery never substitutes the `codex` or `claude` CLI commands.

For a Codex session in the ChatGPT desktop app, OpenAI documents shared MCP
configuration with Codex CLI. A separately configured snapshot connection can
use this entry in `~/.codex/config.toml`:

```toml
[mcp_servers.opa_snapshot]
url = "http://127.0.0.1:8765/mcp"
```

This is an optional manual setup example; the launcher does not write global
configuration. Use the actual verified endpoint and check tool availability in
the desktop app before asking a question. A cloud ChatGPT connector has a
different connection path; opening ChatGPT does not configure a local connector.
See [OpenAI's MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### Claude Desktop

Select **Claude Desktop · external app** after starting MCP. For a pre-configured
connection on port 8765, choose that port before startup. **Copy MCP URL** copies
the verified endpoint, such as `http://127.0.0.1:8765/mcp`; the local connection
in Claude Desktop must use the same address, port and `/mcp` path. **Automatic**
port selection may require updating your Claude configuration.

**Open Claude Desktop** launches Claude separately. An empty application field
(or `claude-desktop`) tries common installations. If discovery fails on Windows,
use **Browse…** to select the installed `Claude.exe` or a Windows shortcut
(`.lnk`); you can also paste its full path, including spaces. Store-packaged
installations can be opened from the Start menu if no usable file is available.
On macOS, automatic launch uses the registered Claude application.

Chat, login, model selection and permissions stay in Claude Desktop. The Qt
transcript is available for embedded Codex only. Opening Claude does not verify
its MCP connection, rewrite its settings, or send a question. Check the tools in
Claude itself. Keep the workbench MCP listener running while chatting; stopping
MCP or closing the workbench leaves Claude open but removes this endpoint.
The loaded snapshot remains locked while the listener runs in either mode.

The compact Codex executable field is specifically for Codex CLI, which speaks
the app-server protocol. It is not a general assistant command line. Claude Code
also requires a separate adapter for its own streaming protocol; entering
`claude` in the Codex field does not provide embedded Claude chat. See Anthropic's
[programmatic Claude Code documentation](https://code.claude.com/docs/en/headless)
and [Claude Desktop local MCP guidance](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Snapshot and server lifecycle

`SnapshotMcpHost` owns a QThread, event loop, bound socket, FastMCP ASGI lifespan,
and Uvicorn server. It captures one successful context for its lifetime. It does
not construct another AppContext or load OCI again. Atomic socket binding reports
occupied ports correctly; status is based on a real MCP handshake rather than
thread liveness.

Loading is locked while MCP starts, runs, or stops, and until its Codex child has
exited. The controller enforces the same lock for programmatic requests. A
replacement load also disables server startup, preventing a race where a new
snapshot publishes while an old one begins serving. Logging remains available
while MCP runs. New snapshots clear the previous conversation.

Close requests stop the listener and child asynchronously and close the window
after both exit. HTTP shutdown has a graceful request-drain deadline; Codex is
terminated and, if necessary, killed after a two-second grace period. Worker
objects remain owned until their finished signals arrive. An unresolved worker
cannot be silently destroyed by closing the window.

`mcp_server.create_snapshot_server(context)` creates an independent server using
a request-local ContextVar binding. It does not replace the standalone/Tk
`mcp_server.app_context` global. Existing query functions, schemas, source
validity, conditions, and provenance are retained.

| Available tool | Purpose |
| --- | --- |
| `snapshot_status` | Served tenancy, timestamp, inventory counts and coverage |
| `policy_search` | Existing bounded policy search |
| `policy_search_set` | Related queries and comparisons |
| `tag_based_policy_search` | Parsed tag-condition evidence |
| `oke_workload_identity_search` | OKE identity coverage evidence |
| `identity_search` | Known identities and associations |
| `cross_tenancy_search` | Aliases and cross-tenancy source evidence |

`data_operations`, cache/history loading and reload tools are not registered on
this endpoint. The listener serves snapshot evidence; it does not evaluate
conditions, dynamic membership, or authoritative OCI access decisions. Inventory
limitations remain part of the returned evidence. This initial endpoint is
loopback-only; use the maintained standalone MCP service for separately managed
remote deployments and OAuth configuration.

## Codex adapter

`CodexClient` uses QProcess and JSONL stdio. It initializes once, inspects effective
configuration, reads account state and the model catalog, creates an ephemeral
read-only thread on the first question, verifies its MCP tool connection, and
only then starts a model turn. It supports streamed assistant messages, tool
activity, cancellation, failed turns, process errors, malformed protocol data,
response deadlines and finite buffers. stderr and raw account/configuration
payloads are not copied into the application logs.

All overrides are child-process arguments. The operator's global Codex settings
are not rewritten. Inherited server names are explicitly disabled with valid
transport definitions, and a unique local snapshot server is enabled. Whole-table
replacement alone was insufficient for the installed version's layered
`config/read` results. The adapter verifies that only the snapshot is enabled;
at thread discovery, foreign servers must be explicitly disabled. A cached tool
catalog or a starting connection is not treated as readiness.

Plugins, app integrations, browser tools, shell execution, web search and
multi-agent support are disabled for this child. App integrations require the
`apps` feature to be disabled as well as app configuration overrides. Unexpected
extra active servers prevent sending a question. Additional execution/file-change
approvals, permission grants and elicitation requests are declined with visible
activity messages: this is a snapshot-query view. Unsupported server requests
receive an explicit protocol error rather than being silently approved.

Official OpenAI references: [app-server protocol](https://developers.openai.com/codex/app-server/),
[MCP configuration](https://developers.openai.com/codex/mcp/), and
[configuration reference](https://developers.openai.com/codex/config-reference/).
The transport, account flows, configuration keys, and event names follow these
references and the locally generated schemas for installed `codex-cli 0.162.1`.

## Validation and remaining exploration

Automated checks use synthetic data and a local app-server stub. They cover real
MCP HTTP initialization/query/stop/restart, occupied ports, snapshot isolation,
reload/start races, close during hosting, split UTF-8 JSONL, interleaved events,
turn failure and cancellation, rejected permissions, missing executable/account,
malformed data and timeouts. They do not make paid inference requests.

A manual installed-Codex check on 2026-10-15 verified initialization, effective
configuration, account/model discovery, an ephemeral thread, and seven tools on
the local sample endpoint. It intercepted `turn/start` before transmission and
confirmed both child and listener exited. A real model answer remains an opt-in
check using **Send** in the app.

Remaining exploration includes login widgets, richer tool-result presentation,
request-scoped live snapshot replacement, and packaged Codex executable discovery.
The current prototype uses terminal Codex login and locks loading during hosting.
Frozen distribution must additionally validate FastMCP/Pydantic startup, native
child executable discovery and platform shutdown behavior before release.
