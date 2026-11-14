# ADR 0001: REST and MCP over one core

**Status:** Accepted · Junction 2026 prototype

## Context
Buyers will connect in two ways. AI agents (Claude, other assistants, custom agents) discover and call tools over the Model Context Protocol. Procurement systems, ERPs and scripts call HTTP APIs. If each interface had its own logic, rules and audit would drift apart, and an agent could pick the weaker door.

## Decision
All business logic (search, offers, planning, quotes, mandate rules, orders, audit) lives in one Python core (`gateway/service.py`). REST (FastAPI, OpenAPI 3) and an MCP server with seven tools are thin adapters over it: `search_products`, `check_offers`, `create_quote`, `place_order`, `get_order_status`, `get_audit_log`, `get_my_mandate`. Both share the same JSON Schemas and the same API-key authentication.

## Consequences
- Same request, same decision, same audit entry, whichever interface is used. Tests run against the core once.
- No proprietary agent SDK is needed; any MCP or HTTP client works.
- Two interfaces to document and version. Both adapters reuse the same request and response models, so a schema change shows up in both.
- Approval is deliberately not exposed over MCP (see ADR 0005), and `create_quote`/`place_order` reject approver keys on both channels.
