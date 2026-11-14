# Aimo approval backend

Browser submissions, REST orders, and MCP orders use the same service. The client first accepts a signed quote. The gateway rechecks stock and dietary requirements, applies the buyer mandate, and verifies that the warehouse can fulfill the order. The order decision and audit events are committed together.

| Outcome | When it applies |
| --- | --- |
| `confirmed` | The mandate permits automation and verified warehouse evidence supports the order. |
| `pending_approval` | Spend exceeds the normal threshold, a substitution needs consent, supplier quantities are unverified, a recurring order deviates, warehouse evidence is missing, capacity or handling needs confirmation, the timing buffer is below 15 minutes, or Gemini flags a combination of risks. |
| `rejected` | A hard mandate rule fails, stock or signed dietary requirements no longer match, too few warehouse lots meet the required shelf life, or preparation and transit miss a deadline. |
| `expired` | A pending order reached its signed quote expiry. The buyer needs a fresh quote. |

The warehouse check adds setup, quantity-based picking, and loading time across all lines. It schedules preparation in order of stock readiness and waits for inbound stock or a later picking slot when the snapshot supplies `ready_to_pick_at`. It uses the longest transit estimate, earliest dispatch and delivery deadlines, and a 15-minute review buffer. A warehouse snapshot must match the sales unit and remain current. Dated lots must meet the stated minimum days remaining on delivery. Record undated stock explicitly with `date_mark: "none"` and a zero minimum to count it. The demo uses synthetic warehouse evidence. Each check subtracts the quantity that other confirmed or pending orders for the same SKU, sales unit, and delivery date already hold from the eligible lot quantity. This netting is recomputed from orders on every check. It does not allocate specific lots, and confirmation does not dispatch a vehicle.

`AIMO_FULFILLMENT_CHECKS` controls the warehouse check. When it is unset, the check runs with `OFFLINE_DEMO=1` and is off in live mode, because live mode has no automatic evidence feed. Set `AIMO_FULFILLMENT_CHECKS=1` in live mode only when warehouse evidence is recorded through the admin endpoint below. Without recorded evidence every order waits in `pending_approval` and cannot be approved. `AIMO_FULFILLMENT_CHECKS=0` turns the check off in either mode.

## Gemini configuration

The server selects `gemini-4-hydrogen` with `thinking_level: "medium"` via Google's [Interactions API](https://aistudio.google.com/docs/interactions-overview). Configure `GEMINI_API_KEY` in `app/.env` and restart the services. The Aimo Gemini review runs after local checks pass and can flag an exception. It receives structured warehouse facts without customer identifiers, addresses, buyer prompts, or credentials. If the provider is unavailable, the decision uses verified local rules and the audit records that fallback. Existing rules still run when the key is absent. [Hydrogen documentation](https://aistudio.google.com/docs/models/gemini-4-hydrogen)

## Warehouse evidence API

`PUT /operations/fulfillment-evidence/{delivery_date}/{product_id}` requires an Aimo admin account. It upserts one warehouse snapshot per SKU and Helsinki delivery date into the existing gateway SQLite database. Timestamps must include an offset. Older replacements, malformed snapshots, and an `observed_at` later than the gateway clock return `422`. The gateway clock is `DEMO_NOW` when that is set, and the error states its current value. Success returns `204`. Challenge JSON and CSV source files still feed the separate SQLite catalog during import.

```json
{
  "unit": "ST",
  "observed_at": "2026-11-14T09:30:00+02:00",
  "valid_until": "2026-11-14T11:00:00+02:00",
  "dispatch_by": "2026-11-16T10:00:00+02:00",
  "deliver_by": "2026-11-16T11:00:00+02:00",
  "ready_to_pick_at": "2026-11-16T08:00:00+02:00",
  "pick_setup_minutes": 10,
  "pick_units_per_minute": 50,
  "load_minutes": 15,
  "transit_minutes": 30,
  "route_capacity_available": true,
  "handling": "chilled",
  "handling_ready": true,
  "minimum_shelf_life_days": 2,
  "lots": [{"lot_id": "warehouse-lot-1", "quantity": 2000, "date_mark": "best_before", "marked_date": "2026-11-20"}]
}
```

Use actual warehouse and routing records for this endpoint in live mode. `OFFLINE_DEMO=1` generates its own snapshots. The existing admin approval endpoint rechecks stock and warehouse facts. A failing warehouse recheck never rejects the order at approval. For missing evidence, mismatched units, unconfirmed capacity or handling, too little eligible stock, or a missed deadline, it returns `409` naming the failing rules. The reviewer can record corrected evidence and retry, or reject the order. A hard mandate, stock, or dietary failure found at approval still rejects the order.

## Frontend handoff

- Delete the Models selector and omit `model` from `POST /client/chat`. Older payloads that still send the field work because the server ignores it. `GET /client/models` reports Hydrogen availability for existing clients.
- Fetch `GET /client/requests/{order_id}/audit` on the buyer portal. Aimo can read the full audit under `audit` in `GET /operations/orders/{order_id}`. External agents already have `GET /audit?order_id=…` and the MCP `get_audit_log` tool; for buyer keys these keep summaries, the plain-text rendering, and the hash-chain result, but omit the warehouse evidence payload and show Aimo operators as `admin`.
- The buyer endpoint returns a reduced view. Each entry in `events[]` has `event_type`, `ts`, an `actor` role such as `admin` or `gateway`, and `data` with `decision`, `status`, and `rules` (rule names) where they apply. It omits warehouse evidence, operator usernames, summaries, and the hash-chain result. The Aimo view keeps `events[].summary`, the plain-text rendering, and the hash-chain result. Include `AIMO_APPROVAL_EVALUATED` and `AIMO_APPROVAL_RECHECKED` in the Aimo decision view. Order audit explains an individual decision. Analytics aggregates across orders.

## Trust protocol ideas

- Publish a signed offer per buyer, SKU or GTIN, unit, quantity, and delivery window. Include net price, currency, tax and validity, stock quantity or an explicit unknown, and country of origin with its evidence source. Give every claim an observation time. Distinguish supplier declarations from lot-level warehouse records.
- Reuse Ed25519 JWS and a published JWKS with key IDs and rotation. Let agents verify signature, audience, and validity before using an offer. For a firm stock promise, pair the signed offer with a short reservation and return a signed, idempotent order receipt at commitment.
- Publish signed audit checkpoints to an independent location. This would let a buyer verify that its receipt was included without exposing another buyer's transactions.
