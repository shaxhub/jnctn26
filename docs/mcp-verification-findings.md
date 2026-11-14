# Preliminary MCP Server Verification & QA Findings

**Target**: `app/gateway/mcp_server.py` (mounted at `/mcp` via Streamable HTTP in `app/gateway/api.py`)
**Tested against**: Ephemeral `uvicorn` instances on `127.0.0.1` backed by isolated temporary `DB_PATH` SQLite databases, based on `feature/new-FE-BFE-1804` (`b4e1816`).
**Date**: 2026-11-14

## 1. Baseline Verification

- **Unit test suite**: `pytest -q` in `app/tests` passed (`74 passed in 1.73s`). Note: the existing suite only exercises REST/core helpers; none of the 74 tests invoke `/mcp` over the MCP protocol.
- **Official smoke script** (`app/scripts/mcp_smoke.py`, `--key demo-hotel-key`):
  - `initialize` succeeded (`valio-aimo-gateway` / `Agent Dairy — Valio Aimo Trade Gateway` `0.1.0`).
  - `tools/list` returned all 17 tools (`ping`, `discover_seasonal_products`, `get_kitchen_capabilities`, `compile_ingredients`, `source_ingredients`, `estimate_delivery`, `get_my_mandate`, `search_products`, `check_offers`, `create_quote`, `place_order`, `repeat_quote`, `check_recurring_quote`, `get_order_status`, `get_audit_log`, `get_request_thread`, `post_request_message`).
  - `get_my_mandate` returned `hotel` / `mandate-hotel-2026-11`.
  - `search_products` (`text="maito"`, `free_from=["FREE_FROM_LACTOSE"]`, `category="10400"`) returned `31` matches.
- **End-to-end purchasing flow** (`demo-hotel-key`, isolated temp DB):
  - `ping` → `{"status": "ok", "valio": "ok", ...}` (live Valio mock API reachable).
  - `source_ingredients` (`dishes=["Salmon soup"]`, `servings=10`, `delivery_date="2026-11-16"`) → 5 ingredients (`salmon 1.2 KG`, `potato 1.7 KG`, `leek 0.35 KG`, `cream 0.45 L`, all `available`).
  - `search_products` + `check_offers` (`quantity=10`, `unit="L"`, `delivery_date="2026-11-16"`) → `best` plan selected `464237` (`10.0 ST`, `total_net: 13.0`).
  - `create_quote` → signed EdDSA quote (`total_net: 13.0`, `total_gross: 14.8`, `policy_preview.decision: auto`).
  - `place_order` → `status: confirmed`, `total_net: 13.0`.
  - `get_order_status` + `get_audit_log` → `confirmed`, 7 order audit events, hash chain `ok: true`.

---

## 2. Issues Found During Adversarial Probing

### 1. Unhandled `OverflowError` crash in `check_offers`
- **Locations**: `app/gateway/models.py` (`OffersRequest.quantity`, line 172), `app/gateway/planner.py` (`round_qty`, line 45), `app/gateway/mcp_server.py` (`_run`, lines 66–74)
- **Reproduction**: Send raw JSON with `"quantity": 1e309` (overflows IEEE-754 float to `inf`) in `check_offers`.
- **Observed behavior**: `OffersRequest.quantity` only validates `gt=0` (missing `allow_inf_nan=False` and an upper bound `le=...`). `round_qty` raises `OverflowError: cannot convert float infinity to integer` inside `math.ceil`. `_run` does not catch `OverflowError`, so FastMCP surfaces an `UnexpectedToolError` (`Error executing tool check_offers`) with a traceback in server logs.
- **Suggested fix**: Add `allow_inf_nan=False` and a sensible upper bound (e.g. `le=1_000_000`) to `OffersRequest.quantity` and `Need.quantity`, and catch/guard non-finite or overflowing values cleanly.

### 2. Invalid JSON (`Infinity`) signed and returned by `create_quote` / `place_order`
- **Locations**: `app/gateway/models.py` (`LineRequest.quantity`, line 257), `app/gateway/service.py` (`create_quote`, lines 253, 264–265)
- **Reproduction**: Call `create_quote` with `lines: [{"product_id": "464237", "quantity": 1.7e308}]` (`unit_price: 1.3`), then call `place_order`.
- **Observed behavior**: `LineRequest.quantity` specifies `allow_inf_nan=False` but has no upper bound (unlike `DraftEdit.quantities` in `app/gateway/workspace.py`, line 32, which caps at `le=1_000_000`). Multiplying `1.7e308 * 1.3` overflows to `float('inf')`. `create_quote` signs and stores `Infinity` in `line_total`, `total_net`, and `total_gross`, and `place_order` returns literal `"total_net": Infinity` in its JSON text response—invalid RFC 8259 JSON that breaks strict `JSON.parse()` clients. *(Mandate evaluation still rejects the order via `hard_cap`.)*
- **Suggested fix**: Add an upper bound (e.g. `le=1_000_000`) to `LineRequest.quantity` and enforce `allow_nan=False` when serializing signed quote payloads.

### 3. Tiny recipe scaling underflows to `0.0` and fails `Need` validation in `source_ingredients`
- **Locations**: `app/gateway/kitchen.py` (`compile_ingredients`, line 116; `_pick`, line 159)
- **Reproduction**: Call `source_ingredients` with `servings=1`, `delivery_date="2026-11-16"`, `recipes=[{"name": "Micro", "servings": 5000, "ingredients": [{"name": "potato", "amount": 0.001, "unit": "g"}]}]`.
- **Observed behavior**: `compile_ingredients` computes `2e-10` kg and rounds to 9 decimals (`0.0`). `source_ingredients` then passes `quantity=0.0` into `Need(..., quantity=row["quantity"], ...)`, raising a Pydantic `ValidationError` (`Input should be greater than 0`) from `Need`.
- **Suggested fix**: Enforce a positive minimum scaled ingredient quantity (or return a clear validation error / skip sub-threshold quantities before constructing `Need`).

### 4. `source_ingredients` accepts past delivery dates
- **Locations**: `app/gateway/kitchen.py` (`SourceRequest`, line 60; `source_ingredients`, line 169)
- **Reproduction**: Call `source_ingredients` with `delivery_date="2020-01-01"`.
- **Observed behavior**: Succeeds and queries offers for `2020-01-01`, whereas `discover_seasonal_products` (`app/gateway/seasonal.py`, lines 21–22) and `repeat_quote` (`app/gateway/service.py`, lines 316–317) explicitly reject dates earlier than `store.now().date()` with `"Choose today or a future delivery date"`.
- **Suggested fix**: Reject `request.delivery_date < store.now().date()` in `source_ingredients` for consistency.

---

## 3. Controls That Held Up Under Testing

- **Concurrency (`place_order` race)**: 5 concurrent `place_order` calls on the same `quote_id` cleanly resulted in `1` order created and `4` rejected with `quote_invalid: quote ... was already used` (no SQLite lock errors).
- **Cross-buyer isolation (IDOR)**: `demo-hospital-key` was rejected (`not found for this buyer`) when targeting `hotel`'s `order_id`/`quote_id` via `get_order_status`, `get_audit_log`, `get_request_thread`, `post_request_message`, `repeat_quote`, and `check_recurring_quote`.
- **Auth, origin & live preferences**:
  - Missing key or empty `Authorization: Bearer` → `401` (`McpAuthMiddleware`).
  - Approver key (`demo-hotel-approver-key`) → `401` on `/mcp`.
  - Disallowed or `null` `Origin` header → `403 Origin forbidden`.
  - Lookup key (`demo-hotel-lookup-key`) → `get_my_mandate` omits write tools, `create_quote` fails with `ToolError`.
  - Toggling `agent_self_order=false` via `POST /client/settings` immediately blocked `create_quote` over `/mcp`.
- **Mandate caps & malformed inputs**: `10,000` units (`€13,000` > `€5,000` hard cap) returned `rejected`; malformed JSON (`400`), SQLi-like `order_id` (`not found`), empty `product_ids`, unknown units (`unit_mismatch`), Unicode/6-digit postal codes, duplicate-alias recipes, blank allergen entries, and whitespace-only messages all failed cleanly.

---

## 4. Antigravity Integration Note

- In this environment, `/Users/shax/.gemini/config/mcp_config.json` is empty (0 bytes) and no local gateway server is running on port `8000` by default.
- Because `McpAuthMiddleware` requires `X-API-Key` or `Authorization: Bearer <key>` on `/mcp`, clients that natively support custom HTTP headers (e.g. `claude mcp add --transport http ... --header "Authorization: Bearer ..."`) can connect directly, while clients configured only with a `url` in `mcp_config.json` require header support or a local stdio bridge (such as `mcp-remote`).

## Resolution on feature/mcp-fixes

1. Offer, need, and quote line quantities must be finite and at most 1,000,000. MCP returns a tool error for numeric overflow.
2. Quote creation rejects non-finite totals before saving and JWS signing uses strict JSON.
3. Ingredient amounts that round to zero return a validation error identifying the ingredient.
4. Ingredient sourcing rejects dates before the gateway’s Helsinki date before looking up offers.

The [MCP HTTP regression test](../app/tests/test_mcp_transport.py) covers initialization, authentication, tool discovery, and all four input-validation cases. A separate signing test covers strict JSON serialization.

For hosted clients, create a named key in **Settings → Agent integration**. Configure **Streamable HTTP** with `Authorization: Bearer <key>` and the Funnel URL `https://kienlebox.tail80aa1e.ts.net/agent-dairy/mcp`. Use the custom MCP hostname after it has been configured in Cloudflare. For clients that only accept a URL, use a bridge that can supply the authorization header. Keep credentials in the client’s private configuration. The Antigravity installation noted above was outside the scope of this branch.
