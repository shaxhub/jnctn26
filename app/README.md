# Agent Dairy developer guide

Start with the [root quickstart](../README.md#run-locally), [user guide](../docs/user-guide.md) and [architecture](../docs/architecture.md). Run commands from `app/`.

## Start and stop

From this directory, run `uv run --locked python scripts/run_local.py` to start the shared portal on port 8000, with the admin panel at `/admin/`. Press **Ctrl+C** in the same terminal to stop the server. See the [root README](../README.md#start-and-stop) for alternate ports.

## Developer commands

```sh
uv sync --locked
uv run --locked python -m gateway.load_catalog
uv run --locked pytest -q
uv run --locked python evals/run_evals.py
```

The test suite and default evaluations can run offline. The challenge catalog loader needs the organizer files. For a synthetic catalog, use `python -m gateway.demo_catalog` with the [offline settings](../README.md#offline-demo).

Use the [read-only MCP check](../docs/mcp-verification-findings.md) to verify a client connection. To exercise the purchasing workflow, run the demo flow.

```sh
uv run --locked python scripts/demo_flow.py
```

The demo flow exercises the mock API and can write simulated orders to the configured gateway database. Its optional `--reset` clears the demo order state. Use a disposable database for that command. The separate reference buyer agent is available through `python -m gateway.agent` and `/agent/run`, with scripted and optional Anthropic modes.

## Seed a populated demo

Run `uv run --locked python -m gateway.seed_demo` with the same `DB_PATH`, `CATALOG_DB_PATH`, and `SIGNING_KEY_PATH` as the running server. It backs up the database and adds labelled **[Demo]** orders for both kitchens, delivery history, messages, drafts, pending substitutions, and an allergen rejection. Existing accounts and records stay intact; rerunning skips samples already present.

The seed uses current catalog products and checked offer prices to illustrate historical activity. New drafts and pending approvals keep normal quote expiry, so use them soon after seeding.

## MCP integration

Connect to `http://127.0.0.1:8000/mcp` using Streamable HTTP and `Authorization: Bearer <key>`. Get a key in **Settings and Tools → Agent integration**. See the [MCP connection guide](../docs/mcp-connection.md) for setup in ChatGPT Desktop App, Antigravity, and OpenCode.

Start with `get_my_mandate` to read the effective permissions. A lookup key can read catalog, offer, order, and conversation data for its buyer. Writing an order or posting to a request thread requires an order-enabled key and workspace permission.

| Workflow | Tools |
| --- | --- |
| Connection and authority | `ping`, `get_my_mandate` |
| Products, stock, and delivery | `search_products`, `check_offers`, `estimate_delivery`, `discover_seasonal_products` |
| Kitchen sourcing | `get_kitchen_capabilities`, `compile_ingredients`, `source_ingredients` |
| Quotes and orders | `create_quote`, `repeat_quote`, `check_recurring_quote`, `place_order`, `get_order_status` |
| Conversation and audit | `get_request_thread`, `post_request_message`, `get_audit_log` |

A typical external agent discovers authority, searches for products, checks offers for the requested delivery date, creates a signed quote, and places the order by quote ID. Quote lines use **sales units**. Check order status and request history to track registration and fulfillment. Inspect current tool argument schemas with MCP discovery rather than hard-coding schemas from this guide.

An order requires address text and a five-digit Finnish postcode. Pass `"delivery_address": "Testikuja"` and `"postal_code": "00580"` to `place_order`, or supply both in `delivery_address`. Keep the postcode as a string to preserve its leading zero. Omitting both fields uses the saved workspace address and postcode. An incomplete address leaves the quote available for retry. `get_order_status` returns the delivery address recorded at submission.

For `compile_ingredients`, pass `servings: 20` and `dishes: ["Salmon soup", "Roasted potatoes"]`. Known dish names use estimated templates. To use your own amounts, pass a recipe such as `{"name":"Tomato salad","servings":4,"ingredients":[{"name":"tomato","amount":500,"unit":"g"}]}` in `recipes`. Use `source_ingredients` with a `delivery_date` for live offers. The optional `unavailable_ingredients` list supports culinary alternatives where the planner knows one.

## Configuration and contracts

Use the [environment template](.env.example) and [local account and key setup](../README.md#local-accounts-and-keys). Relative paths resolve from `app/`. Environment variables inherited by the process take precedence over `app/.env`. Restart the server after changing its configuration.

| Setting | Purpose |
| --- | --- |
| `OFFLINE_DEMO` | Set to `1` for synthetic offers. Build the synthetic catalog once and use separate demo data and signing paths. |
| `REQUIRE_PORTAL_LOGIN` | Set to `1` to require password accounts. In demo mode, the operations API also accepts the private admin key. |
| `DATA_DIR`, `CATALOG_DB_PATH` | Challenge import location and rebuildable SQLite search catalog. |
| `DB_PATH`, `SIGNING_KEY_PATH` | Gateway state and Ed25519 private key. A missing key is generated on first use. Keep both files across restarts so existing quotes remain verifiable. |
| `VALIO_BASE_URL`, `VALIO_CUSTOMER_ID`, `VALIO_CACHE_TTL_S` | Mock API endpoint, customer field and offer cache lifetime. Leave the challenge defaults unless you have a different mock setup. |
| `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `AGENT_MODEL` | Optional model integrations. The Anthropic model setting applies to the reference agent. |
| `DEMO_NOW` | Optional fixed Helsinki timestamp for reproducing availability, cutoffs, and mandate dates. |
| `AIMO_FULFILLMENT_CHECKS` | Unset enables synthetic warehouse checks in offline mode and leaves them off in challenge mode. When enabled with challenge data, the gateway needs recorded [warehouse evidence](../docs/aimo-approval.md). |
| `MCP_ALLOWED_ORIGINS` | Comma-separated origins for browser-based MCP clients. Add a local browser client's origin if it differs from the defaults. |

- [Mandates](mandates/) define demo buyer policy. [Model definitions](gateway/models.py) and [JSON Schemas](schemas/) describe exported core contracts. Regenerate those schemas with `uv run --locked python -m gateway.models`.
- The shared FastAPI app publishes buyer and operations routes in `/docs`. The gateway publishes its quote public key at `/.well-known/jwks.json`.
- [Mock API assumptions](ASSUMPTIONS.md) explain the challenge input, unit conversion, carbon and stock data. [Architecture and decisions](../docs/architecture.md) describe where those checks run.
