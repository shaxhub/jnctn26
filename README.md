# Open Counter — Valio Aimo Trade Gateway

> **Open to any AI agent. On the buyer's terms.**  
> Built for the **Junction 2026 — Valio Aimo "Trusted Trade Agents"** challenge.

**Open Counter** is an open, verifiable trade gateway in front of Valio Aimo's catalogue, pricing, and availability APIs. Any buyer's AI purchasing agent (over **MCP** or **REST/OpenAPI**) can search 17,546 products, compare cutoff-aware live offers, plan orders in sales units, receive **Ed25519-signed quotes**, and place orders governed by **gateway-enforced buyer mandates** and **out-of-band human approvals** — with every decision recorded in a **SHA-256 hash-chained audit log**.

---

## 3-command quickstart

Prerequisite: put your `VALIO_API_KEY` in `app/.env` and ensure the challenge dataset (`valio_aimo_junction26_product_data.json` and the two CSVs) is in `external/valio-aimo/` (gitignored; never commit challenge data).

```bash
cd app && cp .env.example .env && uv sync
uv run python -m gateway.load_catalog
uv run uvicorn gateway.api:app --reload --port 8000
```

Then open:
- **Web UI:** `http://localhost:8000/` (Request, Approvals, and Audit tabs + Connect via MCP panel)
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
         |  MCP (/mcp, 7 tools) or REST (/docs)                   |  Web UI / + /approvals
         |  X-API-Key or Authorization: Bearer                    |  Out-of-band approver key
         v                                                        v
  +-----------------------------------------------------------------------------------+
  | FastAPI app (app/gateway/api.py)          auth.py: API key -> Principal -> Mandate |
  |   mcp_server.py (7 tools)   REST routes   ui/index.html   agent.py (LLM/scripted) |
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

**7 MCP tools** (thin wrappers over `gateway/service.py`, matching the REST core):
`search_products`, `check_offers`, `create_quote`, `place_order`, `get_order_status`, `get_audit_log`, `get_my_mandate`.

---

## Judging criteria mapping

| Criterion | Weight | How Open Counter addresses it |
|---|---:|---|
| **Working end-to-end demo** | 30% | Web UI with 4 interactive scenarios (hotel 1,000 L approval, hotel 200 L auto, hospital gluten stock-out reject, manipulated 10,000 L prompt injection), `Reset demo state`, live tool trace, signed quote card, out-of-band Approvals tab, hash-chained Audit timeline, plus `scripts/demo_flow.py` and `scripts/mcp_smoke.py`. |
| **Solving user need** | 20% | Structured `FREE_FROM_*` + `nonAllergen` filtering (avoids cocoa drinks/cooking cream), Synkka + CASE + multipack unit conversions (`L`/`KG`/`PCS`/sales units), `allowedLotSize` rounding, stock splitting, CO2 & delivery reliability scoring, and **10/10** deterministic eval pass rate (`app/evals/cases.jsonl`). |
| **Autonomy & controls** | 20% | Server-side buyer `Mandate` bound to API key (never set via tool args), 12 explicit rules (`auto` / `needs_approval` / `reject`), role separation blocking agents from approving and approvers from ordering, Ed25519/JWS signed quotes (`/.well-known/jwks.json`), and SHA-256 append-only audit chain. |
| **Exception robustness** | 15% | Excludes offers past `closingTime` even when stock API reports availability, routes `no_availability_data` (~18%) to humans, auto-expands Valio's 189 listed substitutes while rejecting forbidden allergens (`CONTAINS`) and flagging trace warnings (`MAY_CONTAIN`), handles limited stock splits, and retries/falls back gracefully on mock API errors. |
| **Openness & path to production** | 15% | Open standards only (MCP Streamable HTTP, OpenAPI 3, JSON Schemas in `app/schemas/`, RFC 7515/8037 JWS/JWKS, GS1 codes), explicit [assumptions](app/ASSUMPTIONS.md), 5 [Architecture Decision Records](docs/adr/), and a phased [production roadmap](docs/roadmap.md). |

---

## Documentation

- **Application guide:** [app/README.md](app/README.md)
- **Assumptions & mock-API behaviour:** [app/ASSUMPTIONS.md](app/ASSUMPTIONS.md)
- **Production roadmap:** [docs/roadmap.md](docs/roadmap.md)
- **Architecture Decision Records ([docs/adr/](docs/adr/)):**
  - [0001 REST and MCP over one core](docs/adr/0001-rest-and-mcp-over-one-core.md)
  - [0002 Gateway-enforced mandates](docs/adr/0002-gateway-enforced-mandates.md)
  - [0003 Signed, time-bound quotes](docs/adr/0003-signed-time-bound-quotes.md)
  - [0004 SQLite catalogue index for the prototype](docs/adr/0004-sqlite-catalogue-index.md)
  - [0005 Human approval out-of-band](docs/adr/0005-out-of-band-human-approval.md)
