# Roadmap: from prototype to production

For Valio Aimo business and IT. Timings are our estimates, not commitments; they assume one small team on Valio Aimo's side plus an integration partner.

## Where we are (Junction prototype)

- Gateway with search over **17,546** products, live price and availability from the mock APIs (with retries and stale-cache fallback), cutoff-aware offers, a Mandate-aware planner (sales units, stock-limited splits, auto-expanded substitutes, CO2 and delivery reliability scoring), Ed25519-signed quotes (`/.well-known/jwks.json`), 12 mandate rules, out-of-band approvals, and a SHA-256 hash-chained audit log.
- REST (OpenAPI 3) and **7-tool MCP** (`search_products`, `check_offers`, `create_quote`, `place_order`, `get_order_status`, `get_audit_log`, `get_my_mandate`) over one Python core. Claude buyer agent (`claude-opus-5-5`) plus deterministic scripted fallback.
- **Mocked:** buyer identity (plaintext API keys in `buyers.json`), approver login, order system (orders stay in `gateway.db`), and configurable demo clock (`DEMO_NOW`).
- Eval suite: **10 / 10 pass** (`100%` deterministic and scripted-agent modes).

## Phase 1: Pilot-ready (estimate: 0–3 months)

| Step | What | Why |
|------|------|-----|
| Managed identity | Scoped, short-lived agent credentials and organization sign-in for approvers. | Supports buyers who run multiple purchasing agents and need managed access. |
| Real data, read-only | Connect to real price, stock, cutoff and delivery-route data. Keep the order path mocked. | Prove offer accuracy on real data before anyone can place an order. |
| Mandate editor | A simple page where a buyer's purchasing manager sets limits, forbidden allergens, preferred products and approvers. | Buyers won't write JSON. The mandate is the product. |
| Production storage | Postgres for orders, mandates and audit (plus external audit-head anchoring); OpenSearch for catalogue search with Finnish and Swedish analysis. | SQLite was the right prototype choice (ADR 0004), not the right production one. |

## Phase 2: Pilot with 1–2 customers (estimate: 3–6 months)

- One hotel or restaurant group and one public-sector kitchen (hospital, school, care home): different rules, same gateway.
- Integrate with the real order system for these customers only, behind a feature flag. Every agent order also visible to Valio Aimo's customer service.
- Approvals by e-mail or Teams notification, not only the inbox, plus approver routing by rule type (spend vs allergen).
- Measure: orders needing manual correction, approval turnaround, rejected attempts, customer-service contacts per order. Compare with the same customers' web-shop orders.

## Phase 3: Production (estimate: 6–12 months)

- **Verifiable credentials for certificates and labels:** organic, Finnish origin, allergen statements issued as signed credentials (W3C Verifiable Credentials) by the supplier or certifier, so an agent can check a claim instead of trusting a text field. Start with the 700 suppliers' most-ordered products.
- **Carbon mandates and multi-pack optimisation:** promote CO2 per product from tie-breaker to hard/soft mandate rules ("prefer the lower-footprint option within 5% of price") and solve multi-pack combinations to avoid tiny remainders.
- Publish the API and MCP tool definitions as an open specification, versioned, with a public sandbox.
- Rate limits, monitoring and fraud detection per agent and per buyer.

## Phase 4: Agent to agent (12 months +)

- **Valio Aimo's own sales agent joins:** proposes alternatives, bulk deals or near-expiry offers back to the buyer's agent, inside the same mandate rules and audit log. The buyer's rules still decide.
- Other wholesalers or suppliers could implement the same open specification. That is the point: the interface belongs to the industry, not to one platform.

## Honest risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Buyers don't define mandates | Everything goes to approval, no time saved | Start with customers that already have written purchasing rules; offer templates by segment (hotel, hospital, school). |
| Data quality | ~18% of products return no availability; only **189** have an official substitute; claims/allergens occasionally contradict | Unknown availability always goes to a human; gateway trusts GS1 allergen flags over claims. Improve substitute data with category managers; this pays off for the web shop too. |
| Agent vendors move faster than standards | MCP and agent auth are still evolving | Keep the core independent of the interface (ADR 0001); add new protocols as adapters. |
| Liability for a wrong order | Who pays if an agent orders the wrong thing? | Signed quotes plus audit log show exactly what was approved and by whom. Contract terms for agent orders must be agreed before Phase 2. |
| Prompt injection and compromised agents | Unwanted orders | Mandates enforced by the gateway (ADR 0002), approvals out-of-band (ADR 0005), per-agent revocation. |
| Internal adoption | Sales and customer service see agents as a threat | Agent orders flow into the same order system and are visible to account managers; Phase 4 gives sales its own agent. |
| Cost of the planner on real data | Splits and substitutes need many live lookups | Short-lived cache of price and stock; batch lookups where the backend allows it. |
