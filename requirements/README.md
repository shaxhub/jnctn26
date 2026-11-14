# Requirements

Everything you need to run **Agent Dairy** locally.

## 1. System prerequisites

| Requirement | Notes |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Recommended installer. Can also download Python for you. |
| Python **3.12+** | `app/.python-version` pins 3.12. uv installs it automatically if missing. |
| Valio Aimo challenge data | Place in `external/valio-aimo/` at the repo root (see below). |
| Valio API key | Set `VALIO_API_KEY` in `app/.env`. |
| `AIMO_ADMIN_API_KEY` | Any private random string of 32+ characters, set in `app/.env`. |

Optional:

- `GEMINI_API_KEY` enables Gemini 4 Carbon in the client workspace. The client uses guided parsing with an empty key.
- `ANTHROPIC_API_KEY` enables LLM mode for the separate reference buyer agent.
- `DEMO_NOW` pins the demo clock.

## 2. Challenge dataset

Copy these three files into `external/valio-aimo/` at the repository root:

```
external/valio-aimo/valio_aimo_junction26_product_data.json
external/valio-aimo/valio_aimo_junction26_delivery_reliability.csv
external/valio-aimo/valio_aimo_junction26_carbon_footprint.csv
```

This directory is gitignored and must not be committed.

## 3. Python dependencies

Recommended (uses `uv.lock`, reproducible):

```bash
cd app
uv sync --locked
```

With `pip` instead:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r ../requirements/requirements.txt
```

Use `requirements/requirements-dev.txt` to also install the test tooling (`pytest`).

- `requirements.txt` — runtime dependencies only.
- `requirements-dev.txt` — runtime + development dependencies.

Both files are generated from `app/uv.lock`:

```bash
cd app
uv export --locked --format requirements-txt --no-hashes --no-emit-project --no-dev -o ../requirements/requirements.txt
uv export --locked --format requirements-txt --no-hashes --no-emit-project -o ../requirements/requirements-dev.txt
```

Do not edit them by hand.

## 4. First run

Copy `app/.env.example` to `app/.env` and fill in the keys. From `app/`, build the catalog and start both portals.

```sh
uv run --locked python -m gateway.load_catalog
uv run --locked python scripts/run_local.py
```

The client uses port 8000 and Aimo operations uses port 8001. Press **Ctrl+C** to stop both. If you installed with pip, run the same Python commands from `app/` with the virtual environment active.

```sh
python -m gateway.load_catalog
python scripts/run_local.py
```

See the [root README](../README.md#run-locally) for setup and alternate ports. Configure `DEMO_NOW` in `.env` if you want a fixed demo clock.

## 5. Verify the install

```bash
cd app
uv run pytest -q
uv run python evals/run_evals.py
```

Tests and default evaluations run offline. Importing the catalog requires the challenge files, and live offers require the Valio API key.
