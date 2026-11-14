# ADR 0003: Signed, time-bound quotes

**Status:** Accepted · Junction 2026 prototype

## Context
Prices and stock change. Between the agent's lookup, a human approval and the order, the price can move, and an agent (or anything between agent and gateway) could relay a different number than the gateway offered. The approver must approve exactly what will be ordered.

## Decision
`create_quote` returns a quote with fixed lines, prices, total and an expiry, signed by the gateway with Ed25519 as a JWS (RFC 7515, RFC 8037). `place_order` accepts only a valid, unexpired quote signed by the gateway. The public key is published at `/.well-known/jwks.json` so buyers' systems can verify quotes independently.

## Consequences
- The price shown to the human approver is the price ordered. Tampered or expired quotes are rejected.
- Quotes are verifiable without trusting the agent.
- Expiry must be long enough for a human approval and short enough to be honest about stock. Prototype value: earliest of price `validTo` and line order cutoffs (2 h cap when cutoff is unknown); production needs a rule for re-quoting after an approval outlives the quote.
- Key management (rotation, storage in a KMS) is needed for production.
