# ADR 0002: Mandates are enforced by the gateway, not the agent

**Status:** Accepted · Junction 2026 prototype

## Context
A buyer's AI agent is software neither Valio Aimo nor, often, the buyer fully controls. It can misread a request, propose an unsafe substitute, or be manipulated by injected text. Rules placed in the agent's prompt are advice, not control.

## Decision
Each buyer organisation has a mandate stored server-side and bound to its API key: per-order and weekly spend limits, forbidden allergens, substitution preferences, and how to treat unknown availability. The gateway evaluates every quote and order against it and returns exactly one decision: `auto`, `needs_approval` or `reject`, with the rule that fired. Forbidden allergens are always `reject` with no override. No tool argument or prompt text can change the mandate or raise authority.

## Consequences
- Guardrails hold for any agent, including ones we've never seen.
- Every decision is explainable: the rule name and inputs go to the audit log.
- Buyers must write down their rules. Onboarding needs a simple mandate editor (roadmap).
- The agent still adds value (understanding requests, explaining choices) but carries no authority.
