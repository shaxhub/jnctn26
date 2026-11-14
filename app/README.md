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

The test suite and default evaluations can run offline. The catalog loader needs the three challenge files. These commands exercise the running app or live mock API.

```sh
uv run --locked python scripts/mcp_smoke.py
uv run --locked python scripts/demo_flow.py
```

The smoke script needs the client gateway on port 8000. The demo flow can submit simulated orders into the configured local gateway database. Its optional `--reset` clears that database’s demo order state. The separate reference buyer agent is available through `python -m gateway.agent` and `/agent/run`. It has scripted and optional Anthropic modes. Gemini 4 Hydrogen with Medium thinking handles the client assistant. Gemini Decision 1 handles the Aimo approval review.

## Seed a populated judging demo

Run `uv run --locked python -m gateway.seed_demo` with the same `DB_PATH`, `CATALOG_DB_PATH`, and `SIGNING_KEY_PATH` as the running server. It backs up the database and adds labelled **[Demo]** orders for both kitchens, delivery history, messages, drafts, pending substitutions, and an allergen rejection. Existing accounts and records stay intact; rerunning skips samples already present.

The seed uses current catalog products and checked offer prices to illustrate historical activity. New drafts and pending approvals keep normal quote expiry, so use them soon after seeding.

## MCP integration

The endpoint is `http://127.0.0.1:8000/mcp` using Streamable HTTP. Send an `X-API-Key` header or `Authorization: Bearer <key>`. For a local test, use the demo agent keys in [buyers.json](buyers.json). Connect your agent from the client workspace for a copyable command.

```sh
claude mcp add --transport http agent-dairy http://127.0.0.1:8000/mcp --header "Authorization: Bearer demo-hotel-key"
```

Start with `get_my_mandate` to read the effective permissions. A buyer can disable agent ordering in Settings. Lookup credentials still have buyer-scoped conversation access. Order-making tools require an order-enabled agent credential.

| Workflow | Tools |
| --- | --- |
| Connection and authority | `ping`, `get_my_mandate` |
| Products, stock, and delivery | `search_products`, `check_offers`, `estimate_delivery`, `discover_seasonal_products` |
| Kitchen sourcing | `get_kitchen_capabilities`, `compile_ingredients`, `source_ingredients` |
| Quotes and orders | `create_quote`, `repeat_quote`, `check_recurring_quote`, `place_order`, `get_order_status` |
| Conversation and audit | `get_request_thread`, `post_request_message`, `get_audit_log` |

A typical external agent discovers authority, searches for products, checks offers for the requested delivery date, creates a signed quote, and places the order by quote ID. Quote lines use **sales units**. Check order status and request history to track registration and fulfillment. Inspect current tool argument schemas with MCP discovery rather than hard-coding schemas from this guide.

For `compile_ingredients`, pass `servings: 20` and `dishes: ["Salmon soup", "Roasted potatoes"]`. Known dish names use estimated templates. To use your own amounts, pass a recipe such as `{"name":"Tomato salad","servings":4,"ingredients":[{"name":"tomato","amount":500,"unit":"g"}]}` in `recipes`. Use `source_ingredients` with a `delivery_date` for live offers. The optional `unavailable_ingredients` list supports culinary alternatives where the planner knows one.

## Configuration and contracts

- [Environment template](.env.example) lists credentials, the Valio base URL, database paths, MCP browser origins, and the optional demo clock. Relative paths resolve from `app/`.
- [Mandates](mandates/) define demo buyer policy. [Model definitions](gateway/models.py) and [JSON Schemas](schemas/) describe exported core contracts. Regenerate those schemas with `uv run --locked python -m gateway.models`.
- The shared FastAPI app publishes buyer and operations routes in `/docs`. The gateway publishes its quote public key at `/.well-known/jwks.json`.
- [Mock API assumptions](ASSUMPTIONS.md) explain the challenge input, unit conversion, carbon and stock data. [Architecture and decisions](../docs/architecture.md) describe where those checks run.
