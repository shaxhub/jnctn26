# Agent Dairy — Valio Aimo Trade Gateway (Junction 2026, "Trusted Trade Agents")

A gateway that lets an external AI purchasing agent **search** Valio Aimo products, get **live price and
availability**, get a **signed fixed-price quote** and **place an order**. A buyer-specific **mandate**
decides whether the order is auto-approved, needs a human's approval or is rejected. Every step goes to a
**hash-chained, human-readable audit log**.

The same core is exposed three ways: an **MCP server** (`/mcp`, 14 tools for compatible clients), a **REST API** (`/docs`),
and a build-free **web UI** with the client workspace (`/`) and Aimo operations (`/admin`). A reference
**buyer agent** (Claude, `claude-opus-5-5`, via the Anthropic SDK tool runner) and a deterministic **scripted** mode
are included.

See also the root [README.md](../README.md), [ASSUMPTIONS.md](ASSUMPTIONS.md),
[Architecture Decision Records](../docs/adr/), and the [production roadmap](../docs/roadmap.md).

## Architecture

```
   buyer's AI agent                         human approver (browser)
 (Claude / any MCP client)                          |
        |  MCP Streamable HTTP  /mcp                |  UI /  +  REST /approvals, /audit
        |  X-API-Key or Bearer                      |
        v                                           v
 +-----------------------------------------------------------------------+
 |  FastAPI app  (gateway/api.py)     auth.py: key -> buyer -> mandate   |
 |    mcp_server.py (14 tools)   REST endpoints   ui/index.html  agent.py |
 |                         \        |        /                           |
 |                          service.py  (one core for every channel)     |
 |   search.py --- offers.py --- planner.py --- quotes.py --- policy.py  |
 |      |            |           (mandate+subs)  (Ed25519 JWS) (mandate) |
 |  catalog.db   valio_client.py               store.py / audit.py       |
 |  (SQLite+FTS5) (retries, cache)             gateway.db: quotes,orders,|
 |      ^            v                         approvals, audit_events   |
 | load_catalog  Valio mock API                (append-only hash chain;  |
 | (JSON + CSVs) /price /availability           DEMO_NOW + /demo/reset)  |
 +-----------------------------------------------------------------------+
```

MCP tools include `ping`, `search_products`, `check_offers`, `estimate_delivery`, `create_quote`,
`place_order`, `get_order_status`, `get_audit_log`, `get_my_mandate`, `get_kitchen_capabilities`, `compile_ingredients`, `source_ingredients`, `discover_seasonal_products`, and `check_recurring_quote`.

Flow: `search_products` → `check_offers` (+ Mandate-aware ranked plans in sales units, auto-expanding Valio's
listed substitutes when preferred products are unorderable) → `create_quote` (signed Ed25519 JWS, expires at the
earliest of price `validTo` and line order cutoffs with a 2 h cap when cutoff is unknown, includes policy preview) →
`place_order` (re-checks availability, evaluates the mandate) → `confirmed` | `pending_approval` | `rejected` →
human approves/rejects → `confirmed` | `rejected` | `expired`.

## Local setup

Follow the [local setup in the root README](../README.md#local-setup) to configure the Valio key, import the challenge catalog, and start the app. Set `ANTHROPIC_API_KEY` in `.env` to enable the reference LLM agent, or set `DEMO_NOW` to fix the demo clock.

Endpoints when running:
- **Client workspace:** `http://localhost:8000/`
- **Aimo operations:** `http://localhost:8000/admin` (uses the private `AIMO_ADMIN_API_KEY`)
- **OpenAPI:** `http://localhost:8000/docs`
- **MCP:** `http://localhost:8000/mcp` (header `X-API-Key: demo-hotel-key` or `Authorization: Bearer demo-hotel-key`)
- **JWKS:** `http://localhost:8000/.well-known/jwks.json`

Additional checks and CLI workflows (from `app/`):

```bash
uv run python scripts/demo_flow.py --reset        # reset gateway.db + end-to-end demo without LLM against live mock API
uv run python scripts/mcp_smoke.py                # MCP initialize + tools/list + search_products (server must be running)
uv run pytest -q                                  # unit tests (offline)
uv run python evals/run_evals.py                  # deterministic evals (10 fixture cases); --live ; --agent
uv run python -m gateway.agent "I need 1,000 litres of lactose-free milk by Monday" --buyer hotel [--mode scripted]
uv run python -m gateway.models                   # re-export JSON Schemas to schemas/
```

The challenge data stays in `../external/valio-aimo` (set `DATA_DIR`). **Never copy it into `app/` or commit it**:
the terms limit it to this challenge. `external/`, `data/`, `*.db`, and `.env` are gitignored.

Demo credentials in `buyers.json` include `demo-hotel-key` and `demo-hospital-key` for external MCP clients, plus corresponding `-client-key` values for the client workspace. The Aimo operations key is separate. New exceptions require that key to resolve. Signed quotes from earlier versions retain their original buyer-approval behavior.

`POST /demo/reset` requires the operations key. It clears gateway state and can set a fixed `demo_now` timestamp for demos.

Connect an MCP client, e.g. Claude Code:
`claude mcp add --transport http agent-dairy http://localhost:8000/mcp --header "Authorization: Bearer demo-hotel-key"`.

## Policy rule ids (mandate engine, `gateway/policy.py`)

| rule id | effect | when |
|---|---|---|
| `per_order_limit` | needs_approval | net total > `max_order_total` |
| `weekly_limit` | needs_approval | this ISO week's confirmed + pending + this order > `max_weekly_total` |
| `hard_cap` | **reject** | total > `hard_cap_order_total` (default 5 × per-order limit), quantity > `max_quantity_multiple` × requested, or category outside `allowed_categories` ("manipulated agent" guard) |
| `forbidden_allergen` | **reject** | a line CONTAINS a forbidden allergen |
| `may_contain_allergen` | per mandate | trace warning (MAY_CONTAIN) of a forbidden allergen |
| `substitution_preference` | needs_approval | substitute outside the buyer's preference (`same_category` / `always_approval`) |
| `unknown_availability` | per mandate | Valio returned no availability data |
| `need_mismatch` | needs_approval | a line lacks a requested claim, violates `need.exclude_allergens` / `exclude_terms`, or fails unit conversion |
| `partial_coverage` | needs_approval | quote covers less than requested |
| `mandate_not_valid` | **reject** | outside the mandate's validity dates |
| `unknown_product` | **reject** | quote line has no offer data |
| `quote_invalid` | refused / **reject** | quote unknown, reused, tampered, expired, or stock/orderability changed since quoting |

## Who owns what

| Owner | Area | Files |
|---|---|---|
| **A** data / gateway | catalog, Valio client, offers, quotes, store, audit | `config.py`, `models.py`, `load_catalog.py`, `search.py`, `valio_client.py`, `offers.py`, `quotes.py`, `store.py`, `audit.py` |
| **B** planner / policy / evals | plans, mandate rules, core service, unit tests, evals | `planner.py`, `policy.py`, `service.py`, `mandates/`, `buyers.json`, `tests/`, `evals/` |
| **C** agent / MCP / REST / UI / docs | buyer agent, MCP, FastAPI, web UI, scripts, docs | `agent.py`, `mcp_server.py`, `api.py`, `auth.py`, `ui/index.html`, `scripts/`, `README.md`, `ASSUMPTIONS.md` |

## Remaining roadmap & open items

- **A (data/gateway):** validate catalog content-per-sales-unit against the price API across all 17,546 products; key rotation for quote signing (KMS); external anchoring of the audit chain head; Postgres + OpenSearch in production ([ADR 0004](../docs/adr/0004-sqlite-catalogue-index.md)).
- **B (planner/policy/evals):** multi-pack integer-programming optimization (avoiding tiny remainder lines), delivery-date fallback (probing next valid delivery date), price-change tolerance vs last order, per-category budgets, approver routing.
- **C (UI/auth/deploy):** OAuth 2.1 client credentials + approver SSO, email/Teams/Slack approval notifications, Finnish UI labels, hosted deployment with `allowed_hosts`/`allowed_origins` enabled.

## What is real and what is stubbed

**Real:** catalog search over all **17,546** products (including `nonAllergen` `FREE_FROM` claims, `oats`/`PN`/plural allergen expansion, and 4,425 reliability + 11,033 CO2 CSV rows); live price and availability from the Valio mock API with retries and stale-cache fallback; cutoff, stock, and unknown-availability handling; Mandate-aware plans in sales units with stock splitting, CO2/reliability scoring, and automatic expansion of Valio's **189** listed substitutes; Ed25519-signed quotes with `/.well-known/jwks.json`; 12 mandate rules; strict agent/approver role separation; append-only SHA-256 hash-chained audit log; 14-tool MCP server, REST API, client workspace, and Aimo operations; **10** deterministic eval cases.

**Stubbed/simplified:** there is no Valio order API (confirmed orders are recorded locally in `gateway.db`); plaintext demo API keys in `buyers.json` instead of OAuth 2.1; heuristic planner; deterministic scripted agent mode when `ANTHROPIC_API_KEY` is unset (the LLM path is implemented for `claude-opus-5-5` and includes a hosted MCP connector option).

**Open standards:** MCP (Streamable HTTP), OpenAPI 3 (`/docs`), JSON Schema (`schemas/`), JWS/JWK (RFC 7515/7517, EdDSA per RFC 8037), GS1 GTINs and GS1 allergen codes from the dataset, ISO 8601 timestamps.


## Kitchen planning

- For a menu, pass `dishes: ["Salmon soup", "Roasted potatoes"]` and `servings: 20` to `compile_ingredients`. Recognized dishes use demo ingredient estimates. Other dish names are returned in `unresolved_dishes`.
- For an exact recipe, pass `recipes: [{"name": "Tomato salad", "servings": 4, "ingredients": [{"name": "tomato", "amount": 500, "unit": "g"}]}]`. The tool scales the ingredient list to the requested servings and combines matching ingredient units. A supplied recipe replaces a template with the same dish name.
- Use `source_ingredients` with a delivery date to check the compiled ingredients. `exclude_allergens` applies alongside the buyer mandate. `unavailable_ingredients: ["potato"]` asks the planner to skip potatoes and look for replacements. Cross-ingredient swaps are returned with their compatible dishes and culinary trade-offs.
- In the portal, enter one dish per line or use recipe blocks headed by `Dish name (servings)`, with lines such as `500 g tomato`. Separate recipes with a blank line.

Planning calls create an audit event and leave purchasing to the existing quote and ticket flow. The current kitchen planner checks ingredients independently, so buyers should review combined stock and culinary substitutions before ordering.


### Seasonal and repeat purchasing

Use Seasonal produce in the client workspace or call `discover_seasonal_products` in MCP. Suggestions use a labeled Finnish demo calendar and check origin, current offers, and buyer constraints.

Open a confirmed ticket to create a repeat draft for a new delivery date. The gateway recalculates current price and stock. The recurring-order comparison uses the prior six weeks and requires three confirmed same-weekday delivery dates for the same SKU and sales unit. Changes of at least 25% in quantity or 15% in unit price route to human review. MCP clients can inspect a signed quote with `check_recurring_quote`.

A fully sourced menu can be turned into one client ticket draft. Agent Dairy checks combined quantities and dietary constraints against fresh offers before signing. The buyer reviews and submits the draft.
