# Agent Dairy

Agent Dairy is a Junction 2026 prototype for the Valio Aimo Trusted Trade Agents challenge. It gives kitchens a purchasing workspace, lets external AI agents connect over MCP, and gives Aimo staff an admin panel for reviewing and tracking orders. Orders are recorded in the local gateway. The Valio challenge API provides prices and availability.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these commands from the repository root. uv can install the project's pinned Python 3.12 automatically.

```sh
cd app
uv sync --locked
cp .env.example .env
```

On Windows PowerShell, you can use `Copy-Item .env.example .env`. Edit `app/.env` in your editor. Keep that file, the challenge dataset, local databases, and signing keys private and out of Git.

### Offline demo

Use this option to try the app without provider credentials or challenge files. Set these values in `app/.env`.

```dotenv
OFFLINE_DEMO=1
CATALOG_DB_PATH=data/synthetic.db
DB_PATH=data/demo-gateway.db
SIGNING_KEY_PATH=data/demo-signing.pem
REQUIRE_PORTAL_LOGIN=0
DEMO_NOW=2026-11-14T10:00:00+02:00
```

Leave the Valio, Gemini, and Anthropic keys empty for a fully local demo. The fixed Helsinki clock makes the sample dates reproducible and keeps them inside the included buyer mandates' validity windows. From `app/`, build the synthetic catalog once.

```sh
uv run --locked python -m gateway.demo_catalog
```

For a populated workspace, optionally run `uv run --locked python -m gateway.seed_demo`. It adds labeled sample drafts, orders, deliveries, messages, and approval cases to the configured demo database. See the [developer guide](app/README.md#seed-a-populated-demo).

### Valio challenge data and mock API

Get the dataset and `VALIO_API_KEY` from the challenge organizers. Under the repository root, put these files in `external/valio-aimo/`.

- `valio_aimo_junction26_product_data.json`
- `valio_aimo_junction26_delivery_reliability.csv`
- `valio_aimo_junction26_carbon_footprint.csv`

Set `OFFLINE_DEMO=0` and `VALIO_API_KEY` in `app/.env`. Use the default `CATALOG_DB_PATH=data/catalog.db` and `DB_PATH=data/gateway.db` for challenge data. Leave `DEMO_NOW` blank to use the current clock. The sample mandates in `app/mandates/` have fixed validity dates. For a new local test period, update the dates in those files.

```sh
uv run --locked python -m gateway.load_catalog
```

### Start and stop

Run the shared server from `app/`.

```sh
uv run --locked python scripts/run_local.py
```

Use **Ctrl+C** to stop the server. To run on a different local port, add `--port 8010` and use the same port in the browser and MCP URL.

| Surface | Local address |
| --- | --- |
| Buyer workspace | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) |
| Aimo admin panel | [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) |
| REST API and interactive OpenAPI | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| Streamable HTTP MCP | `http://127.0.0.1:8000/mcp` |
| Health and quote verification keys | [/health](http://127.0.0.1:8000/health), [/.well-known/jwks.json](http://127.0.0.1:8000/.well-known/jwks.json) |

## Local accounts and keys

With `REQUIRE_PORTAL_LOGIN=0`, the buyer workspace opens with the **Hotel kitchen** and **Hospital kitchen** demo identities. The local API fixtures in [buyers.json](app/buyers.json) include `demo-hotel-lookup-key` for read-only MCP and `demo-hotel-key` for Hotel kitchen purchasing. Open `/admin/` and enter `AIMO_ADMIN_API_KEY` to try operations in this mode.

For separate password accounts, set `REQUIRE_PORTAL_LOGIN=1`. From `app/`, provision the accounts using the same `DB_PATH` as the server.

```sh
uv run --locked python -m gateway.manage_accounts hotel-kitchen client --buyer hotel
uv run --locked python -m gateway.manage_accounts hospital-kitchen client --buyer hospital
uv run --locked python -m gateway.manage_accounts aimo admin
```

Each command prompts for a password of 12–128 characters. Use `--generate` to print a generated password once. Rerun the same command to reset the password for that account. With password login required, sign in at `/`. Admins can switch buyer workspaces and open **Admin panel** in the same session. Buyer accounts stay in their assigned workspace, and the built-in demo keys are disabled.

| Credential | How to get it | What it does |
| --- | --- | --- |
| `AIMO_ADMIN_API_KEY` | Generate it locally with the command below and save the result in `app/.env`. | Opens the operations page and authenticates the operations API when password login is optional. |
| Agent Dairy MCP Bearer key | In a buyer workspace, open **Settings and Tools → Agent integration → Create agent key**. | Connects an AI client to that buyer. Ordering requires permission on the key and in the workspace. |
| `VALIO_API_KEY` | Request it from the Valio Aimo challenge organizers. | Retrieves prices and availability from the challenge mock API. |
| `GEMINI_API_KEY` | Create a key in Google AI Studio with access to the models used by Agent Dairy. See [Google's API key guide](https://ai.google.dev/gemini-api/docs/api-key). | Optional. Enables the AI-assisted buyer features and eligible order reviews. Guided parsing and local rules work with the key blank. |
| `ANTHROPIC_API_KEY` | Create a key in the Claude Console. See [Anthropic's API key guide](https://platform.claude.com/docs/en/get-api-key). | Optional. Enables LLM mode for the separate reference buyer agent. Scripted mode works with the key blank. |

Generate the local operations key from `app/`.

```sh
uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"
```

See the [environment template](app/.env.example) and [configuration reference](app/README.md#configuration-and-contracts) for paths, cache settings, signing, the demo clock, and warehouse checks.

## Connect your AI to Agent Dairy

1. In the buyer portal, open **Settings and Tools → Agent integration**. Copy the MCP URL and create a read-only agent key for your first lookup.
2. In your AI client, add a **Streamable HTTP** MCP server at `http://127.0.0.1:8000/mcp`. Use Bearer authentication and store the key in the client's credential settings or a local environment variable.
3. Ask the AI to run `get_my_mandate` and confirm the kitchen it is connected to.

The [MCP setup guide](docs/mcp-connection.md) covers **ChatGPT Desktop App**, **Antigravity**, and **OpenCode**, with configuration examples and a copyable setup prompt.

## What you can do

| Surface | Features |
| --- | --- |
| Buyer workspace | Search by product or SKU, build a shopping list or recipe basket, browse seasonal produce, and compare date-specific offers and substitutes. Check pack sizes, allergens, claims, stock, price, reliability, carbon estimates, and approximate postcode travel time where available. |
| Draft Tickets | Save, edit, rename, and review signed drafts. Use AI Helper to propose changes, then check the separate delivery address and postcode before submission. |
| Dashboard and Submitted Requests | Follow active deliveries on the dashboard, inspect order decisions and audit history, message Aimo, and create repeat drafts with recurring-order comparisons. |
| Analytics and Settings | Review purchase, stock, and fulfillment metrics. Manage theme, language, delivery defaults, invoice preferences, reminders, and agent keys. |
| Aimo operations | Filter the review queue by client, status, delivery dates, and net total. Inspect the order, review exceptions, update fulfillment, message buyers, and browse activity and analytics across kitchens. |
| External integrations | Use MCP for catalog, sourcing, offers, quotes, orders, tracking, and audit tools. Use the REST API for scripted integrations. The gateway applies buyer mandates and sends eligible exceptions to Aimo review. |

See the [buyer and admin user guide](docs/user-guide.md) for complete workflows and example inputs.

## How the stack fits together

FastAPI serves the buyer workspace, admin panel, REST API, and MCP endpoint from one Uvicorn process. The frontend uses HTML, CSS, and native JavaScript modules. SQLite stores the rebuildable search catalog separately from quotes, orders, approvals, preferences, and audit events. Gateway rules enforce buyer scope, quote validity, dietary constraints, and spend limits on every order. The gateway signs quotes with Ed25519 and records decisions in a hash-chained audit log.

- [Architecture and data boundaries](docs/architecture.md)
- [Developer commands, environment reference, and MCP tool index](app/README.md)
- [Backend workflow diagrams](docs/backend-pipeline/README.md) and [Aimo approval logic](docs/aimo-approval.md)
- [Challenge brief](PROBLEM-STATEMENT.md), [Valio data assumptions](app/ASSUMPTIONS.md), and [production roadmap](docs/roadmap.md)
- [Architecture decision records](docs/adr/) and [dependency installation alternatives](requirements/README.md)
