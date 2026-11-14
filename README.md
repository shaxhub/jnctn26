# Agent Dairy

Agent Dairy is a Junction 2026 prototype for the Valio Aimo Trusted Trade Agents challenge. Kitchen staff use a client workspace to find products, turn recipes into ingredient lists, and review order drafts. External agents use MCP or REST. Aimo staff use a separate operations app to review exceptions, track fulfillment, and respond to clients.

## Run locally

1. Install [uv](https://docs.astral.sh/uv/). The workspace selects Python 3.12.
2. Put the three organizer-provided files under `external/valio-aimo/` at the repository root.

   - `valio_aimo_junction26_product_data.json`
   - `valio_aimo_junction26_delivery_reliability.csv`
   - `valio_aimo_junction26_carbon_footprint.csv`

3. Copy [app/.env.example](app/.env.example) to `app/.env`. Set `VALIO_API_KEY` for live offers and a private `AIMO_ADMIN_API_KEY` for the operations app. To generate an operations key, run `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Add `GEMINI_API_KEY` to enable Gemini 4 Hydrogen with Medium thinking for the assistant and Gemini Decision 1 for the Aimo order review. Without a key, the assistant uses guided search and Aimo applies the mandate rules, and the warehouse rules where `AIMO_FULFILLMENT_CHECKS` enables them, locally.
4. From the repository root, install dependencies and build the catalog.

   ```sh
   cd app
   uv sync --locked
   uv run --locked python -m gateway.load_catalog
   ```

## Start and stop both apps

After setup, run this from the repository root in **PowerShell (Windows)** or a **terminal (macOS or Linux)**.

```sh
uv run --locked --project app python app/scripts/run_local.py
```

Wait for both Uvicorn startup messages, then open the two links below. Press **Ctrl+C in that terminal** to stop both servers. If one server exits during startup or while running, the launcher stops the other and exits with an error.

If a default port is already taken, choose a different pair.

```sh
uv run --locked --project app python app/scripts/run_local.py --client-port 8010 --admin-port 8011
```

If you use a browser-based MCP client, add its origin to `MCP_ALLOWED_ORIGINS` in `app/.env` when it differs from the defaults.

### Connect an external AI

In the client portal, open **Settings → Agent integration** and copy the MCP server URL. For a client that supports custom headers, choose **Streamable HTTP**, create a key, and paste it into the client's bearer token field. If the client asks for a custom header, set the header name to `Authorization` and its value to `Bearer <your-key>`. Copy the key when it is created. Each key can be revoked from Settings, and ordering requires permission on both the key and the buyer workspace.

For ChatGPT, use the same URL and select **OAuth** with **Client ID Metadata Document** registration. Sign in to Agent Dairy when prompted and confirm the connection. ChatGPT can read catalog and request data for the linked buyer. Disconnect it from Agent Dairy Settings at any time. See [hosting and OAuth setup](docs/mcp-connection.md).

Keep challenge data, local databases, signing keys, and `app/.env` out of Git. The default paths are ignored.

| Surface | Local entry point |
| --- | --- |
| Client workspace | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Aimo operations | [http://127.0.0.1:8001/](http://127.0.0.1:8001/) |
| Client and gateway REST | [OpenAPI on port 8000](http://127.0.0.1:8000/docs) |
| Operations REST | [OpenAPI on port 8001](http://127.0.0.1:8001/docs) |
| Streamable HTTP MCP | `http://127.0.0.1:8000/mcp` |
| Quote verification keys | [Gateway JWKS](http://127.0.0.1:8000/.well-known/jwks.json) |

## Documentation

- [Client and Aimo user guide](docs/user-guide.md)
- [Technology, architecture, and design decisions](docs/architecture.md)
- [Developer commands and MCP tools](app/README.md)
- [Challenge brief](PROBLEM-STATEMENT.md)
- [Valio mock API and data assumptions](app/ASSUMPTIONS.md)
- [Enterprise plan](docs/enterprise-plan.md) and [production roadmap](docs/roadmap.md)
- [Architecture Decision Records](docs/adr/)
- [Aimo approval backend and frontend handoff](docs/aimo-approval.md)

## Private Linux demo without API keys

Use the [private deployment script](app/scripts/deploy_private.sh) on a Linux host with uv and persistent systemd user services. From `app/`, run:

```sh
bash scripts/deploy_private.sh PRIVATE_BIND_IP
```

The script runs the client on port 8000 and Aimo operations on 8001 at that address. It uses a synthetic catalog and a separate local database, requires login on both portals, and uses no Valio or Gemini credentials. Use a private network address where traffic is encrypted, or terminate HTTPS before broader access.

Create accounts on the host from `app/`:

```sh
DB_PATH=data/hosted-gateway.db .venv/bin/python -m gateway.manage_accounts kitchen client --buyer hotel
DB_PATH=data/hosted-gateway.db .venv/bin/python -m gateway.manage_accounts aimo admin
```

These commands prompt for passwords. Running the command again with the same account role and buyer changes its password and revokes existing sessions. Check status with `systemctl --user status agent-dairy-client agent-dairy-admin` and stop both with `systemctl --user stop agent-dairy-client agent-dairy-admin`.

In Ask Agent Dairy, try `I need 20 litres of lactose-free milk` and choose a future delivery date. Create and submit a draft from the result. Repeat with 1,000 litres to exercise the Aimo approval queue. You can also paste a recipe with a quantity and ingredient on each line, such as `2 kg tomato` and `1 kg red onion`.

### Public HTTPS demo with Tailscale Funnel

To add the demo to a host that already uses Funnel on ports 443 and 8443, start the two loopback services and add path routes on those public ports. Check that both paths are free and use ports that already have public Funnel enabled. Path routes share a browser origin with other apps on the same HTTPS port, so use only origins where you trust the other apps.

```sh
FUNNEL_PORTALS=1 bash scripts/deploy_private.sh PRIVATE_BIND_IP
tailscale funnel --bg --https=443 --set-path=/agent-dairy http://127.0.0.1:18200
tailscale funnel --bg --https=8443 --set-path=/agent-dairy-admin http://127.0.0.1:18201
```

Open `/agent-dairy/` on port 443 for the client and `/agent-dairy-admin/` on 8443 for Aimo operations. Both use the same accounts and synthetic orders as the private deployment. Remove either route by running the same Funnel command with `off` at the end.
