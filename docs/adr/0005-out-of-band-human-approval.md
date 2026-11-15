# ADR 0005: Human approval out-of-band, in a web inbox

**Status:** Accepted · Junction 2026 prototype

## Context
Some orders need a person: over the spend limit, a substitute outside preferences, unknown availability. The person who approves (a head chef, a purchasing manager) is usually not the person running the agent. If approval could happen over MCP, the agent, or someone who compromised it, could approve its own order.

## Decision
`place_order` returns an order with status `pending_approval`, the policy reasons, and an order ID. Aimo staff see the pending ticket in the admin review queue and approve or reject it there. MCP agents use `get_order_status` to follow the decision.

## Consequences
- A compromised or confused agent cannot approve anything.
- Approvals are recorded in the audit log with who approved and when.
- The prototype uses local admin accounts or a private operations key in local demo mode. Production identity and approval notifications are future work.
- Approval latency is now human latency; quotes must outlive it or be re-issued (ADR 0003).
