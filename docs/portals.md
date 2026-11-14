# Agent Dairy portal contract

| Surface | Workflow | Acceptance check |
|---|---|---|
| Client workspace | Ask the purchasing assistant for offers and alternatives. Explicitly create a signed ticket draft and submit it after inspecting items, sales units, price, date, and policy preview. | Lookup never writes an order. Submitting a draft requires the client credential that owns it. |
| External MCP | Connect via Streamable HTTP with the agent's own key. Discover permissions and status, search, check offers, request alternatives, and submit a signed quote. | Gateway settings bind identity and order authority to the key. |
| Aimo operations | Filter inquiries, order decisions and pending approvals across demo clients. Inspect an order and its audit trail. Approve or reject from the same workspace. | Aimo admin authentication protects cross-client reads and decisions. |
| Aimo analytics | Browse month, quarter, year, and all-time activity. Compare client sectors, confirmed spend, ranked products, and estimated product emissions. | Totals reconcile with recorded events and confirmed lines. Missing emissions are counted as coverage gaps. |

The rules engine automatically confirms routine requests. Spend, buyer-defined substitutions, trace allergen warnings, incomplete coverage, and uncertain availability can trigger human review. Unlisted catalog suggestions for selected produce require Aimo review when recorded as substitutions. Known hard policy violations and unavailable items are rejected. Pricing and availability come from the mock API. Catalog, label, product-level carbon-factor and reliability data come from the challenge files. Delivery travel time is estimated from Rautatientori for supported postal districts.

Aimo and buyer screens share a cobalt operations shell, with ink #10233c, cobalt #234bd2, glacier #edf3fa, white #ffffff, and green #00745c for positive status. Instrument Sans handles interface labels and data. The buyer screen centers a request composer and keeps ticket review alongside results. The Aimo screen gives most of its width to the queue and detail view. A compact dispatch lane highlights the next actionable state on each surface.


## Offer freshness and ticket lifecycle

- Browsing can show a short outage cache, labeled on offers. Quotes, submission, and human approval make fresh Valio calls.
- A signed quote captures the price and stock snapshot, including the origin and reliability when available. The gateway publishes its verification keys at `/.well-known/jwks.json`.
- A client can retry submission of the same draft and receive the original ticket. Expired pending tickets leave the review queue and stop counting toward reserved weekly spend.
- When Valio reports a later date, `check_offers` with `include_next_delivery` can recheck it and return it as a separate option. It leaves the requested delivery date unchanged.
- An inquiry created in the client workspace is linked to its ticket's audit trail. Older and standalone agent events remain available through the operations activity log.
