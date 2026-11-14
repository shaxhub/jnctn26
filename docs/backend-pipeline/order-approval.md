# Submit and review an order

```mermaid
flowchart TD
    A["Buyer presses Submit ticket to Aimo<br/>POST /client/tickets/submit"] --> C
    B["External agent calls MCP place_order<br/>Bearer key identifies workspace and agent"] --> C
    C["Validate permissions, quote ownership,<br/>channel, signature and expiry"]
    C -->|Invalid| D["Return error"]
    C -->|Valid| E["Recheck current Aimo availability<br/>and signed dietary requirements"]
    E --> F["Apply buyer mandate and warehouse checks when enabled"]
    F -->|Hard failure| R["Rejected"]
    F -->|Sign-off required| H["Pending Aimo approval"]
    F -->|Eligible for automation| G{"Gemini Decisions enabled<br/>and questions apply?"}
    G -->|Yes| I["Gemini Decision 1 scores relevant questions<br/>Request fit, substitutions, duplicates and other signals"]
    G -->|No, or provider unavailable| J["Use local rules"]
    I -->|Flagged| H
    I -->|No flags| J
    J --> K["Confirmed if final local checks pass"]
    R --> L["Save order status and audit events in one transaction"]
    H --> L
    K --> L
    H --> M["Aimo admin opens review queue"]
    M --> N{"Approve or reject?"}
    N -->|Reject| O["Record rejection and reviewer note"]
    N -->|Approve| P["Recheck expiry, stock, dietary rules,<br/>hard mandate constraints and enabled warehouse checks"]
    P -->|Pass| Q["Confirm locally"]
    P -->|Fail| S["Reject, expire, or keep pending if warehouse evidence needs correction"]
    O --> T["Update order and audit trail"]
    Q --> T
    S --> T
```

Confirmation creates an order record in Agent Dairy. The Aimo challenge API supplies price and availability.

[Order service](../../app/gateway/service.py) · [Aimo admin routes](../../app/gateway/operations.py)
