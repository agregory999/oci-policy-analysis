# Qt MCP and assistants

The **MCP & assistant** navigation page hosts a query-only FastMCP endpoint over
the currently loaded context, optional native Codex and Claude Code conversations, and
launchers for separately configured Claude Desktop, ChatGPT Desktop, and Codex
Desktop apps. Neither the server nor an embedded assistant starts when the application opens or
when a snapshot loads.

For the desktop navigation and upgrade overview, see the [7.0 guide](release_7_0.md).

## Embedded Claude Code

Set up Claude Code login, billing and model access in a terminal first. Qt uses
that CLI's existing authentication, user provider settings and inherited
environment. It does not select an account type, require a particular billing
method, collect a key, or change the CLI's global configuration. Account and
model availability remain the CLI's responsibility.

Start MCP, then select **Claude Code · embedded chat**. Enter `claude` or browse
to your Claude Code `claude.exe`, and press **Connect Claude**. Connecting checks
the CLI version without inference. Choose **CLI default**, an alias, or enter a
full model ID. **Send** starts model usage and streams the answer into the Qt
conversation. Login, billing and model errors are reported there; resolve those
in the CLI before retrying. Claude Desktop remains a separate external option.

Each question runs a print-mode JSONL child in a temporary working directory,
with only the served snapshot MCP endpoint and its query tools. Built-in tools,
skills, user hooks and unrelated connectors are disabled for that child, and
user or project plugins are rejected. The CLI always lists its built-in plugins,
so those are allowed. Managed organization policy still applies. Claude's reported
tools, MCP server and plugins are checked before displaying assistant output; a
mismatch fails the turn with the specific reason. Questions travel over stdin,
not command arguments. No question is sent until **Send**.

When `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set in the environment
Qt inherits, the CLI uses that for billing rather than its login. Connect shows
which source is active. Qt does not remove these variables, so unset them in the
launching shell to keep API-key billing separate from the CLI login.

Failed turns show the reason inline after `[failed]`, in the status line and
the events log. Failure reasons are written to the application log
(`~/.oci-policy-analysis/logs/app.log`) at WARNING, which the default level keeps.
The probe and each turn's start and outcome (model, question length, answer
length, duration, exit code) are INFO; raise the `qt.claude` component level in
the logging settings to record them. Questions, answers, and tool payloads are
never logged. Only the last sanitized stderr line is included in a failure reason.

Successful question/answer pairs provide follow-up context in memory, capped at
150,000 characters; older exchanges are omitted visibly when needed. Tool traces
are queried again rather than replayed. CLI session persistence is disabled.
**Stop answer** ends the current child and retains configuration for another
question. **Disconnect** clears context; **Stop MCP** and window close also
terminate the child, with a bounded forced-stop fallback.

The adapter follows Anthropic's [programmatic CLI interface](https://code.claude.com/docs/en/headless)
and [CLI flags](https://code.claude.com/docs/en/cli-reference). Offline tests use
a local CLI stub and real snapshot HTTP queries; they do not establish live
account access or make paid inference requests.

## Try it

Install the optional desktop and MCP dependencies, then launch the workbench:

```bash
uv sync --extra qt --extra mcp --extra web
.venv/bin/python -m oci_policy_analysis.presentation.qt --sample
```

1. Load sample data, OCI, a named cache, an exported snapshot, or CIS output.
2. Enable **Advanced mode** on Overview & Settings, then open **MCP & Assistant**. Choose a port or use **Automatic**, then **Start MCP**.
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

The activity tab receives events from the MCP host itself, including calls from
Claude Desktop and other external clients. Dispatched requests show UTC time,
an opaque session label, a request number, tool or protocol method, outcome and
duration. Tool validation failures are included. The host's startup probe also
appears. Arguments, returned policy evidence and raw error payloads are omitted;
the viewer retains the latest 500 text blocks. Embedded assistant events appear
alongside these server events. Provider API traffic made by external apps is not
MCP traffic and is not observed here.

## External desktop assistants

The assistant selector offers **Claude Desktop**, **ChatGPT Desktop**, and
**Codex Desktop**, each labelled **external app**. They open a separate app;
answers and model selection stay there. **Codex · embedded chat** and **Claude
Code · embedded chat** use the Qt conversation viewer. Application paths are kept separately for each desktop
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
transcript is available for the embedded CLI options. Opening Claude Desktop does not verify
its MCP connection, rewrite its settings, or send a question. Check the tools in
Claude itself. Keep the workbench MCP listener running while chatting; stopping
MCP or closing the workbench leaves Claude open but removes this endpoint.
The loaded snapshot remains locked while the listener runs in either mode.

The compact executable field selects the CLI for the chosen embedded assistant.
Codex uses app-server; Claude Code uses print-mode streaming. Entering `claude`
while **Codex** is selected cannot provide embedded Claude chat. See Anthropic's
[programmatic Claude Code documentation](https://code.claude.com/docs/en/headless)
and [Claude Desktop local MCP guidance](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

## Snapshot and server lifecycle

`SnapshotMcpHost` owns a QThread, event loop, bound socket, FastMCP ASGI lifespan,
and Uvicorn server. It captures one successful context for its lifetime. It does
not construct another AppContext or load OCI again. Atomic socket binding reports
occupied ports correctly; status is based on a real MCP handshake rather than
thread liveness.

Loading is locked while MCP starts, runs, or stops, and until its embedded assistant child has
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
| `resource_reference` | Discover policy resource/family names and verb expansions |
| `operation_reference` | Qualified API names, requirements and related checks |
| `permission_reference` | Reverse permission → resource/verb and operation lookup |


There are ten read-only tools: snapshot status and six snapshot queries, plus
three lookups over the bundled reference catalog. Reference results identify
catalog coverage separately from tenancy snapshot coverage. Try “What resource
type represents virtual machines?”, “What does launching an instance require?”
or “Which resource and verb grant INSTANCE_CREATE?”. See [MCP reference tools](mcp.md#reference-discovery-and-reverse-lookup)
for schemas, pagination and empty mappings. Restart MCP and reconnect the
assistant after upgrading so clients refresh their tool catalogs.

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
response deadlines and finite buffers. Raw stderr and account/configuration
payloads are not logged. Failures record the exit code and the last sanitized
stderr line. Startup, account type (`apiKey` or `chatgpt`), turn start and turn
outcome are logged under `qt.codex`, with the same INFO/WARNING split as Claude.

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

## Finding the CLI on macOS and Windows

Both adapters resolve their CLI the same way. A name is searched on the inherited
PATH plus existing install locations: Homebrew and `/usr/local/bin` on macOS,
`~/.local/bin`, `~/.npm-global/bin` and `~/.volta/bin` on both, and `%APPDATA%\npm`
on Windows. This matters because apps started from Finder or the Start menu do
not inherit the terminal's PATH. Node-based shims also need `node` on that PATH,
and the child receives the same augmented PATH.

On Windows, npm installs `codex.cmd`, a script that cannot pass the adapter's
arguments reliably. Qt maps that shim to the native `codex.exe` inside the
`@openai/codex-win32-*` platform package and adds its bundled `codex-path`
helpers to the child PATH. If the native package is absent, Qt reports that the
shim cannot run and asks for the native executable. Claude Code's native
`claude.exe`, installed by its installer under `~/.local/bin`, is used directly;
a Claude npm `.cmd` shim is rejected with the same guidance.

Connect reports any API-key variable found in the environment (`OPENAI_API_KEY`
or `CODEX_API_KEY` for Codex; `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` for
Claude). The Codex account type from `account/read` is the authoritative signal.

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
