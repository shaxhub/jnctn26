# Agent Dairy MCP connection

## Hosted setup

1. Deploy [the Cloudflare Worker](mcp-custom-domain-worker.js) with the custom domain `agent-dairy-mcp.kienlebox.stream`. It forwards the MCP, discovery, and OAuth endpoints to the existing client Funnel. Keep the Worker upstream aligned with the client's Funnel path.
2. Set the client gateway environment as shown below and restart it. Set these values for both the portal and Funnel processes when they run separately. Both processes need to use the same gateway database.

   ```dotenv
   REQUIRE_PORTAL_LOGIN=1
   MCP_PUBLIC_URL=https://agent-dairy-mcp.kienlebox.stream/mcp
   MCP_OAUTH_ENABLED=1
   MCP_ALLOWED_ORIGINS=https://chatgpt.com
   ```

3. Verify that the public MCP endpoint returns HTTP 401 without credentials and includes a `WWW-Authenticate` challenge with the public metadata URL. Both discovery URLs should return 200. The protected resource must match the public MCP URL exactly.

   ```sh
   curl -i https://agent-dairy-mcp.kienlebox.stream/mcp
   curl -fsS https://agent-dairy-mcp.kienlebox.stream/.well-known/oauth-protected-resource/mcp
   curl -fsS https://agent-dairy-mcp.kienlebox.stream/.well-known/oauth-protected-resource
   curl -fsS https://agent-dairy-mcp.kienlebox.stream/.well-known/oauth-authorization-server
   ```

4. Create the custom MCP app in ChatGPT using that server URL. Choose OAuth and Client ID Metadata Document registration. Agent Dairy recognizes the stable ChatGPT client ID and callback documented by OpenAI. Connect a buyer account and test a product lookup across two separate buyer accounts before sharing it. [OpenAI MCP authentication guide](https://developers.openai.com/plugins/build/auth)

If ChatGPT only offers manual client registration, select **Use your own OAuth client credentials** if the form accepts a public client. Use client ID `https://chatgpt.com/oauth/client.json`, authentication method `None`, and an empty secret. The callback must be `https://chatgpt.com/connector_platform_oauth_redirect`. If the form requires a secret or shows a different callback, this public client registration is incompatible with that form.

The existing Tailscale Funnel can also host OAuth directly. Set `MCP_PUBLIC_URL=https://kienlebox.tail80aa1e.ts.net/agent-dairy/mcp`. The existing `/agent-dairy` mount serves MCP, login and token exchange. A Tailscale operator must add the two exact discovery routes below. Then set `MCP_OAUTH_ENABLED=1` on both client services and restart them.

```sh
sudo tailscale funnel --bg --set-path /.well-known/oauth-protected-resource/agent-dairy/mcp http://127.0.0.1:18200/oauth-protected-resource/agent-dairy/mcp
sudo tailscale funnel --bg --set-path /.well-known/oauth-authorization-server/agent-dairy http://127.0.0.1:18200/oauth-authorization-server/agent-dairy
curl -fsS https://kienlebox.tail80aa1e.ts.net/.well-known/oauth-protected-resource/agent-dairy/mcp
curl -fsS https://kienlebox.tail80aa1e.ts.net/.well-known/oauth-authorization-server/agent-dairy
```

## Credentials

- **Bearer keys** are issued in Settings. The MCP gateway resolves the buyer and applies the key and workspace permissions on each request.
- **ChatGPT OAuth** uses the existing Agent Dairy client login, S256 PKCE, and single-use authorization codes. Tokens are restricted to the configured MCP resource and the signed-in buyer's read-only tools. Access tokens expire after one hour. Refresh tokens rotate and expire after 30 days of inactivity. Disconnecting the grant in Settings or changing the account password invalidates its credentials.
- Audit entries record the connection ID and buyer. SQLite stores hashes of agent keys, OAuth codes and tokens. The admin portal does not serve MCP or the OAuth routes.
