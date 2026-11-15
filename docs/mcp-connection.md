# Connect your AI to Agent Dairy

Start the [local server](../README.md#run-locally) before configuring your client. Agent Dairy uses **Streamable HTTP** MCP with Bearer authentication. The team has connected it from the ChatGPT Desktop App, Google Antigravity, and OpenCode.

## Get your URL and key

1. Open the buyer workspace and select **Settings and Tools → Agent integration**.
2. Select **Copy MCP URL**. The default local URL is `http://127.0.0.1:8000/mcp`. Use the port shown by your local server.
3. Enter an agent name and select **Create agent key**. Leave **Allow this key to submit orders** clear for your first lookup. Select **Copy key** while the key is displayed.

Put the key in the client's credential settings or a local environment variable. A **Bearer token** field takes the raw key. A custom header takes the name `Authorization` and the value `Bearer <your-key>`. A **Bearer token env var** field takes the name of your environment variable, such as `AGENT_DAIRY_MCP_TOKEN`.

Each key belongs to its buyer workspace and can be revoked in **Agent integration**. To enable ordering, use an order-enabled key and turn on **Allow agents to place orders** for the workspace.

## ChatGPT Desktop App

1. Store your raw agent key in a local environment variable named `AGENT_DAIRY_MCP_TOKEN`. On Windows, open **Edit environment variables for your account** and add it under **User variables**. On macOS or Linux, make the variable available to the process that launches the app.
2. Open **Settings → MCP servers → Add server**. Name it `agent-dairy`, choose **Streamable HTTP**, and paste your MCP URL.
3. Enter `AGENT_DAIRY_MCP_TOKEN` in **Bearer token env var**, save, and restart the app so it picks up the variable. Use `/mcp` in the composer to check the connection.

If you use the Codex CLI with the same local host, you can also register the server from a terminal. Replace the URL if you use a different deployment.

```sh
codex mcp add agent-dairy --url http://127.0.0.1:8000/mcp --bearer-token-env-var AGENT_DAIRY_MCP_TOKEN
```

[ChatGPT Desktop MCP settings](https://learn.chatgpt.com/docs/extend/mcp?surface=desktop#configure-in-the-chatgpt-desktop-app)

## Google Antigravity

In the Antigravity App, go to **Customizations → Installed → MCP Servers** and select **Copy Config File Path**. In Antigravity IDE, open the agent panel menu and choose **MCP Servers → Manage MCP Servers → View raw config**.

Add `agent-dairy` to the existing `mcpServers` map. Replace the URL if needed and replace `<your-key>` privately in your local config. If the file is new, you can use the whole example.

```json
{
  "mcpServers": {
    "agent-dairy": {
      "serverUrl": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer <your-key>"
      }
    }
  }
}
```

Save the file and reload the connection. Keep a config containing a raw key outside version control. [Antigravity MCP configuration](https://antigravity.google/docs/mcp?hl=en#mcp-configuration-structure)

## OpenCode

Set `AGENT_DAIRY_MCP_TOKEN` to the raw key in the environment that launches OpenCode. For OpenCode **v1**, add the server under `mcp` in your project's `opencode.json`, or in `~/.config/opencode/opencode.json` to use it across projects. Merge the entry with any existing servers.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-dairy": {
      "type": "remote",
      "url": "http://127.0.0.1:8000/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:AGENT_DAIRY_MCP_TOKEN}"
      }
    }
  }
}
```

For OpenCode **v2**, put the same `agent-dairy` entry under `mcp.servers`. Run `opencode --version` if you're unsure which layout to use. Restart OpenCode and run `opencode mcp list` to check the connection. [OpenCode v1 MCP setup](https://opencode.ai/v1/docs/mcp-servers/) · [OpenCode v2 MCP setup](https://opencode.ai/docs/mcp-servers)

## Ask your AI to help with setup

Paste this prompt into your AI's chat, replacing the client name and URL. Enter the key separately where your client reads credentials.

> Configure `[client name]` to connect to Agent Dairy at `[MCP URL]` using Streamable HTTP. Use bearer authentication and reference the local `AGENT_DAIRY_MCP_TOKEN` environment variable if the client supports it. Otherwise, show me where to enter the bearer key in the client's settings or private local configuration. After setup, run Agent Dairy's `get_my_mandate` tool and tell me which buyer workspace it returns.

Once it connects, try: “Use Agent Dairy to find lactose-free milk and check availability for my requested delivery date.” If the client reports HTTP 401, check the URL, that the key is active, and that the app can read the configured credential. If a tool is missing, refresh the MCP connection and check the key's permissions.
