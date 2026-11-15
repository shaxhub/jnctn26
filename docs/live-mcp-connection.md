# Connect your agent to the live MCP server

The live Agent Dairy MCP server is for hackathon partners only. You’ll need an account on the live Agent Dairy web app and access to a buyer workspace. Sign in using the web app link shared with you by the hackathon team.

## Create a Bearer key

1. Open the buyer workspace you want your agent to use. Go to **Settings and Tools → Agent integration**.
2. In **Agent name**, enter a name you’ll recognize later, such as `OpenCode on my laptop`.
3. Check **Allow this key to submit orders** for a fully autonomous workflow. Your agent will be able to submit orders on your behalf when **Allow agents to place orders** is also enabled in your buyer workspace settings. Select **Create agent key**.
4. Select **Copy key** while the key is displayed. The web app shows it only once. Store it in your MCP client’s credential settings or in a local environment variable named `AGENT_DAIRY_MCP_TOKEN`. Keep the raw key out of chat and source control.

## Configure your MCP client

Add a server named `agent-dairy-live` using **Streamable HTTP**. Set its URL to `https://agent-dairy.kienlebox.stream/mcp` and configure Bearer authentication using the field your client provides.

| Client field | Value |
| --- | --- |
| **Bearer token** | The raw key from **Copy key** |
| **Bearer token env var** | `AGENT_DAIRY_MCP_TOKEN`, with the raw key stored in that environment variable |
| **Custom header** | Name `Authorization`, value `Bearer <your-key>` |

If you’re using an environment variable, make it available to the process that launches your client and restart the client after setting it. For client-specific steps, use the guide for [ChatGPT Desktop App](mcp-connection.md#chatgpt-desktop-app), [Google Antigravity](mcp-connection.md#google-antigravity), or [OpenCode](mcp-connection.md#opencode). Substitute the live URL for the local URL in those examples.

## Verify the connection

Refresh or restart the client, then ask it to run Agent Dairy’s `get_my_mandate` tool and confirm that the returned buyer workspace is yours. Try a read-only follow-up such as “Find lactose-free milk in Agent Dairy.”

If you get HTTP 401, check that the URL ends in `/mcp`, the client is sending the key, and the key is still active under **Agent integration**. If you lose the key or no longer need it, select **Revoke** beside that key in the web app. Create a new key if you need to reconnect.
