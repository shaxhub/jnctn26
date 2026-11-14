# Agent Dairy — Valio Aimo Trade Gateway

> **Open to any AI agent. On the buyer's terms.**  
> Built for the **Junction 2026 — Valio Aimo "Trusted Trade Agents"** challenge.

**Agent Dairy** is an open, verifiable trade gateway in front of Valio Aimo's catalogue, pricing, and availability APIs. Any buyer's AI purchasing agent (over **MCP** or **REST/OpenAPI**) can search 17,546 products, compare cutoff-aware live offers, plan orders in sales units, receive **Ed25519-signed quotes**, and place orders governed by **gateway-enforced buyer mandates** and **out-of-band human approvals** — with every decision recorded in a **SHA-256 hash-chained audit log**.

---

## Local setup

Install [uv](https://docs.astral.sh/uv/). The app uses Python 3.12, which uv can install if needed.

1. Put the three Valio Aimo challenge files in `external/valio-aimo/` at the repository root.
   - `valio_aimo_junction26_product_data.json`
   - `valio_aimo_junction26_delivery_reliability.csv`
   - `valio_aimo_junction26_carbon_footprint.csv`
2. Copy `app/.env.example` to `app/.env`. Set `VALIO_API_KEY` to your challenge key and `AIMO_ADMIN_API_KEY` to a private random value of at least 32 characters. To generate one with Python, run `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Git ignores the dataset directory and `app/.env`.
3. Run these commands from the repository root.

```sh
cd app
uv sync --locked
uv run python -m gateway.load_catalog
uv run uvicorn gateway.api:app --reload --port 8000
```

Then open:
- **Client workspace** at [localhost:8000](http://localhost:8000/). Pick a demo buyer, check offers, explicitly create a ticket draft, then review and submit.
- **Aimo operations** at [localhost:8000/admin](http://localhost:8000/admin). Sign in with the local `AIMO_ADMIN_API_KEY`. Review pending tickets, filter activity, and switch analytics between month, quarter, year, and all time.
- **OpenAPI docs:** `http://localhost:8000/docs`
- **MCP endpoint (Streamable HTTP):** `http://localhost:8000/mcp` (header `X-API-Key: demo-hotel-key` or `Authorization: Bearer demo-hotel-key`)
- **Quote JWKS public keys:** `http://localhost:8000/.well-known/jwks.json`

Offline verification (no network or API keys required):

```bash
cd app && uv run pytest -q && uv run python evals/run_evals.py
```

---

## Architecture overview

```
  Buyer's AI Agent (Claude / any MCP client / ERP)        Human Approver (Browser)
         |  MCP (/mcp, 9 tools) or REST (/docs)                   |  Web UI / + /approvals
         |  X-API-Key or Authorization: Bearer                    |  Out-of-band approver key
         v                                                        v
  +-----------------------------------------------------------------------------------+
  | FastAPI app (app/gateway/api.py)          auth.py: API key -> Principal -> Mandate |
  |   mcp_server.py (9 tools)   REST routes   ui/index.html   agent.py (LLM/scripted) |
  |                         \         |         /                                     |
  |                      app/gateway/service.py  (one core)                           |
  |     search.py --- offers.py --- planner.py --- quotes.py --- policy.py            |
  |        |             |                         (Ed25519 JWS)  (auto/approval/reject)|
  |   catalog.db    valio_client.py                            store.py / audit.py    |
  |  (SQLite+FTS5)  (retries + TTL cache)                      gateway.db (hash chain)|
  +-----------------------------------------------------------------------------------+
                         |
                         v
            Valio Aimo Mock API (/price, /availability)
```

MCP tools include `ping`, `get_my_mandate`, `search_products`, `check_offers`, `estimate_delivery`, `create_quote`, `place_order`, `get_order_status`, and `get_audit_log`. Call `get_my_mandate` first to discover the actions your credential can perform. `check_offers` can return live Valio-listed alternatives and same-ingredient catalog suggestions for selected produce, with claim and allergen filtering when you set `include_substitutes`, and ranked plans when you supply quantity and unit.

Valio’s [challenge API documentation](https://junction26.valioaimo.fi/docs) describes `GET /api/ping`, `POST /api/price` and `POST /api/availability`. Price and availability requests use the delivery date and at most 1,000 product codes. The challenge catalog and CSVs supply product origin, product-level average carbon intensity, and delivery reliability. Analytics estimate product emissions only when both weight and intensity are known. Inquiry analytics count individual search and offer calls. Product category counts count a category once per call. Travel time uses selected Helsinki-region postal districts from Rautatientori and gives a dispatch-to-door range. Aimo’s rules engine handles routine requests and sends exceptions to the human review queue. Confirmed orders are stored locally for the demo.

The client assistant uses the shared MCP tools for lookup. It extracts structured requests with Anthropic when configured and uses guided parsing otherwise. An explicit request to draft creates a signed quote. The client must submit that draft from the workspace. External agents use their own key. Order-enabled credentials can submit their own signed quotes directly. The demo key `demo-hotel-lookup-key` can inspect offers and permissions without ordering.

---

## Judging criteria mapping

| Criterion | Weight | How Agent Dairy addresses it |
|---|---:|---|
| **Working end-to-end demo** | 30% | Client assistant with ticket drafts, Aimo review queue, searchable activity, analytics, signed quotes and a hash-chained audit timeline, plus `scripts/demo_flow.py` and `scripts/mcp_smoke.py`. |
| **Solving user need** | 20% | Structured `FREE_FROM_*` + `nonAllergen` filtering (avoids cocoa drinks/cooking cream), Synkka + CASE + multipack unit conversions (`L`/`KG`/`PCS`/sales units), `allowedLotSize` rounding, stock splitting, CO2 & delivery reliability scoring, and **10/10** deterministic eval pass rate (`app/evals/cases.jsonl`). |
| **Autonomy & controls** | 20% | Server-side buyer `Mandate` bound to API key (never set via tool args), 12 explicit rules (`auto` / `needs_approval` / `reject`), role separation blocking agents from approving and approvers from ordering, Ed25519/JWS signed quotes (`/.well-known/jwks.json`), and SHA-256 append-only audit chain. |
| **Exception robustness** | 15% | Excludes offers past `closingTime` even when stock API reports availability, routes `no_availability_data` (~18%) to humans, auto-expands Valio's 189 listed substitutes while rejecting forbidden allergens (`CONTAINS`) and flagging trace warnings (`MAY_CONTAIN`), handles limited stock splits, and retries/falls back gracefully on mock API errors. |
| **Openness & path to production** | 15% | Open standards only (MCP Streamable HTTP, OpenAPI 3, JSON Schemas in `app/schemas/`, RFC 7515/8037 JWS/JWKS, GS1 codes), explicit [assumptions](app/ASSUMPTIONS.md), 5 [Architecture Decision Records](docs/adr/), and a phased [production roadmap](docs/roadmap.md). |

---

## Documentation

- [Portal and workflow contract](docs/portals.md)
- [Junction 2026 challenge brief](PROBLEM-STATEMENT.md)
- **Application guide:** [app/README.md](app/README.md)
- **Assumptions & mock-API behaviour:** [app/ASSUMPTIONS.md](app/ASSUMPTIONS.md)
- **Production roadmap:** [docs/roadmap.md](docs/roadmap.md)
- **Architecture Decision Records ([docs/adr/](docs/adr/)):**
  - [0001 REST and MCP over one core](docs/adr/0001-rest-and-mcp-over-one-core.md)
  - [0002 Gateway-enforced mandates](docs/adr/0002-gateway-enforced-mandates.md)
  - [0003 Signed, time-bound quotes](docs/adr/0003-signed-time-bound-quotes.md)
  - [0004 SQLite catalogue index for the prototype](docs/adr/0004-sqlite-catalogue-index.md)
  - [0005 Human approval out-of-band](docs/adr/0005-out-of-band-human-approval.md)
