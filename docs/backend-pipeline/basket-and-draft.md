# Build or edit a basket

```mermaid
flowchart LR
    A["Add, remove or change quantity in Product Search"] --> B["Browser updates basket"]
    B --> C["Save draft<br/>POST /client/basket"]
    D["Suggest edit<br/>POST /client/drafts/{id}/help"] --> E["AI proposes changes<br/>Buyer reviews proposed fields"]
    E --> F["Save revised draft<br/>POST /client/drafts/{id}/edit"]
    C --> G["Verify product IDs, quantities and draft ownership"]
    F --> G
    G --> H["Recheck price, stock and dietary constraints"]
    H --> I{"Valid basket?"}
    I -->|No| J["Return error and keep existing draft"]
    I -->|Yes| K["Sign a fresh quote with the selected postcode when available<br/>Supersede the prior draft when editing"]
```

Renaming updates the ticket label without changing the signed quote. Deleting marks the draft as deleted. A submitted request inherits the draft name.

[Draft and basket routes](../../app/gateway/workspace.py)
