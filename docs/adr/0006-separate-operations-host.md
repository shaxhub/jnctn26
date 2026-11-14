# ADR 0006: Serve Aimo operations on a separate host

**Status:** Accepted · Junction 2026 prototype

## Context

Kitchen staff and Aimo reviewers have different interfaces and permissions. Aimo staff need an authenticated inbox for exceptions and fulfillment, while buyers and their agents need a product, draft, and order interface. Putting both web apps behind the same FastAPI entry point exposed Aimo navigation and assets on the buyer host.

## Decision

Run the client gateway and Aimo operations as separate FastAPI apps. The client serves its own assets, buyer APIs, and external MCP. The operations app serves its own assets and authenticated operations routes. Both use the same purchasing service and local data for valid cross-side workflows such as tracking and conversation.

ADR 0001 remains the basis for sharing purchasing logic across interfaces. This updates the approval boundary in ADR 0005. New exceptions go to Aimo staff through operations credentials. Legacy orders retain the earlier buyer-approver compatibility path where applicable.

## Consequences

- Two local processes start on ports 8000 and 8001. The same database configuration lets both see a consistent order history.
- Policy and state transitions remain in shared code. The host split does not substitute for role checks or tenant scoping.
- Gateway and operations deployment need separate routing and credentials. A production split across machines needs shared durable storage and managed signing keys.
