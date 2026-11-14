# Agent Dairy

Agent Dairy is a Junction 2026 prototype for the Valio Aimo Trusted Trade Agents challenge. Kitchen staff use a client workspace to find products, turn recipes into ingredient lists, and review order drafts. External agents use MCP or REST. Aimo staff use a separate operations app to review exceptions, track fulfillment, and respond to clients.

## Run locally

1. Install [uv](https://docs.astral.sh/uv/). The workspace selects Python 3.12.
2. Put the three organizer-provided files under `external/valio-aimo/` at the repository root.

   - `valio_aimo_junction26_product_data.json`
   - `valio_aimo_junction26_delivery_reliability.csv`
   - `valio_aimo_junction26_carbon_footprint.csv`

3. Copy [app/.env.example](app/.env.example) to `app/.env`. Set `VALIO_API_KEY` for live offers and a private `AIMO_ADMIN_API_KEY` for the operations app. To generate an operations key, run `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Add `GEMINI_API_KEY` to enable Gemini 4 Carbon. The app uses guided search and metric recipe parsing with an empty Gemini key.
4. From the repository root, install dependencies and build the catalog.

   ```sh
   cd app
   uv sync --locked
   uv run --locked python -m gateway.load_catalog
   ```

5. From `app/`, run each server in its own terminal. Both read the same configuration and local databases.

   ```sh
   uv run --locked uvicorn gateway.api:app --host 127.0.0.1 --port 8000
   ```

   ```sh
   uv run --locked uvicorn gateway.admin_app:app --host 127.0.0.1 --port 8001
   ```

Keep challenge data, local databases, signing keys, and `app/.env` out of Git. The default paths are ignored.

| Surface | Local entry point |
| --- | --- |
| Client workspace | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Aimo operations | [http://127.0.0.1:8001/](http://127.0.0.1:8001/) |
| Client and gateway REST | [OpenAPI on port 8000](http://127.0.0.1:8000/docs) |
| Operations REST | [OpenAPI on port 8001](http://127.0.0.1:8001/docs) |
| Streamable HTTP MCP | `http://127.0.0.1:8000/mcp` |
| Quote verification keys | [Gateway JWKS](http://127.0.0.1:8000/.well-known/jwks.json) |

## Documentation

- [Client and Aimo user guide](docs/user-guide.md)
- [Technology, architecture, and design decisions](docs/architecture.md)
- [Developer commands and MCP tools](app/README.md)
- [Challenge brief](PROBLEM-STATEMENT.md)
- [Valio mock API and data assumptions](app/ASSUMPTIONS.md)
- [Enterprise plan](docs/enterprise-plan.md) and [production roadmap](docs/roadmap.md)
- [Architecture Decision Records](docs/adr/)
