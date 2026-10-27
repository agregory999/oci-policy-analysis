# MCP Assistant in the New Desktop App

The new desktop app (7.0+) includes an **MCP & Assistant** page for asking questions
about the snapshot currently loaded in the app. It can connect the snapshot to
MCP clients, run a conversation inside the app with Codex CLI or Claude Code, or
open a separately configured desktop assistant.

## Before you start

Load the tenancy data or sample snapshot you want to explore, then turn on
**Advanced mode** and open **MCP & Assistant**. Start the MCP service when you
are ready to use an assistant. Starting the service is explicit; it does not
start when the app opens or when data loads.

The service listens on your computer and exposes the loaded snapshot for
read-only queries. The snapshot stays fixed while the service is running, and
the app prevents data changes until you stop the service. Stopping MCP or
closing the app ends the connection.

## Use Codex CLI or Claude Code in the app

Install the command-line tool you want to use and complete its sign-in before
connecting it from the desktop app:

- **Codex:** Install Codex CLI and sign in to your Codex account.
- **Claude Code:** Install Claude Code CLI and sign in to your Claude account.

In **MCP & Assistant**, connect the selected tool, choose an available model,
and submit a question. For Codex, enter the question and select **Send**;
connecting does not send a prompt by itself. Claude Code is also available as
an in-app conversation.

The assistant uses the account and model access already configured for its
CLI. When you submit a question, its text and the policy evidence returned to
answer it are sent to that assistant. Review the provider's account and data
handling terms before sending sensitive information.

## Use a desktop assistant

Claude Desktop, ChatGPT Desktop, and Codex Desktop can connect to the endpoint
shown on the page. Install and sign in to the desktop application, then
configure its MCP connection using the endpoint and instructions shown by the
workbench. The **Open** action launches the separate application; it does not
install, sign in, or configure its MCP connection for you.

### Desktop Assistant configuration

These examples use `http://127.0.0.1:8765/mcp`. Start the embedded MCP service
first and copy the endpoint shown in **MCP & Assistant** if it differs. Use a
fixed port for a saved configuration; **Automatic** can select a different port
each time. Keep OCI Policy Analysis open with the service running while you chat.

#### Codex Desktop

Add this table to `~/.codex/config.toml` (on Windows,
`%USERPROFILE%\.codex\config.toml`):

```toml
[mcp_servers.oci_policy_analysis]
url = "http://127.0.0.1:8765/mcp"
enabled = true
```

Restart Codex Desktop after saving, then start a conversation with this MCP
server enabled. Codex connects directly over HTTP; no bridge process is needed.
See the [Codex MCP configuration guide](https://developers.openai.com/codex/mcp).

#### Claude Desktop

Install Node.js LTS so `npx` is available. In Claude Desktop, open
**Settings → Developer → Edit Config**. Add this entry to the existing
`mcpServers` object in `claude_desktop_config.json`, preserving your other servers:

```json
{
  "mcpServers": {
    "oci_policy_analysis": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://127.0.0.1:8765/mcp",
        "--transport",
        "http-only",
        "--allow-http"
      ]
    }
  }
}
```

This uses [mcp-remote](https://github.com/punkpeye/mcp-remote) to bridge Claude's
local server connection to the embedded HTTP endpoint. On Windows, use
`"command": "npx.cmd"`. If Claude cannot find it, use the full path to that
executable. Completely quit and reopen Claude Desktop after saving.
The [Claude Desktop setup guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
also lists the configuration file locations.

#### Check the connection

Start a new conversation and ask: “Use oci_policy_analysis to describe the loaded
snapshot and its coverage limits.” Check the MCP activity tab in OCI Policy
Analysis for incoming calls. If connection fails, confirm that the service is
running and the configured port matches the displayed endpoint. Neither example
needs OCI credentials or an MCP token for the embedded service.

## What the answers mean

The assistant searches the snapshot available to the desktop app. It does not
gain additional OCI access through the connection, and its results describe
evidence in that snapshot rather than making an OCI authorization decision.
Conditions, exclusions, compartment scope, collection coverage, and unmapped
permissions can affect what the evidence supports. For transports and other
standalone server options, see the [MCP architecture guide](mcp.md).
