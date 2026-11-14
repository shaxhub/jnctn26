# ADR 0005: Human approval out-of-band, in a web inbox

**Status:** Accepted · Junction 2026 prototype

## Context
Some orders need a person: over the spend limit, a substitute outside preferences, unknown availability. The person who approves (a head chef, a purchasing manager) is usually not the person running the agent. If approval could happen over MCP, the agent, or someone who compromised it, could approve its own order.

## Decision
`place_order` returns `needs_approval` with the rule that fired and an order ID. The approver sees it in a separate web inbox, with the signed quote, the reason and the agent's explanation, and approves or declines there. There is no MCP tool to approve. The agent can only poll `get_order_status`.

## Consequences
- A compromised or confused agent cannot approve anything.
- Approvals are recorded in the audit log with who approved and when.
- In the prototype, the approver's login is mocked. Production needs real identity (OAuth/SSO) and notifications (e-mail, Teams, mobile push).
- Approval latency is now human latency; quotes must outlive it or be re-issued (ADR 0003).
