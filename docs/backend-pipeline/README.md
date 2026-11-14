# Agent Dairy backend diagrams

- [Build shopping list](prompt-to-draft.md)
- [Build or edit a basket](basket-and-draft.md)
- [Submit and review an order](order-approval.md)

## Other portal actions

| Action | Backend effect |
| --- | --- |
| Open Draft Tickets | Loads the buyer’s open signed quotes, names, and policy previews from SQLite. |
| Repeat a confirmed order | Creates a fresh draft from the original items and checks prices and availability for the new date. |
| Open Submitted Requests | Loads the order, fulfillment timeline, messages, and buyer-visible audit events. |
| Send a message or advance delivery | Checks permissions and records the change in the audit trail. |
| Open Dashboard or Analytics | Aggregates saved drafts, orders, and recorded offer checks. |
| Create or revoke an MCP key | Stores or revokes a hashed workspace credential. Authenticated requests log the buyer and agent identity. |
