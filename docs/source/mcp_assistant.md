# MCP Assistant in the New Desktop App

The new desktop app includes an **MCP & Assistant** page for asking questions
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

## What the answers mean

The assistant searches the snapshot available to the desktop app. It does not
gain additional OCI access through the connection, and its results describe
evidence in that snapshot rather than making an OCI authorization decision.
Conditions, exclusions, compartment scope, collection coverage, and unmapped
permissions can affect what the evidence supports. For transports and other
standalone server options, see the [MCP architecture guide](mcp.md).
