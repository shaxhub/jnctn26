# Install dependencies

Use the [root quickstart](../README.md#run-locally) to choose an offline demo or a Valio challenge setup, configure `app/.env`, and start the shared server. Both buyer and Admin pages use port 8000 by default.

## Install with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and run the following from the repository root. The project selects Python 3.12 and uses `app/uv.lock` to pin dependencies.

```sh
cd app
uv sync --locked
```

## Install with pip

Use Python 3.12 to create a virtual environment from `app/`.

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` in Bash or `.\.venv\Scripts\Activate.ps1` in PowerShell, then install the runtime dependencies.

```sh
python -m pip install -r ../requirements/requirements.txt
```

To run the tests, install `../requirements/requirements-dev.txt` instead. Follow the root quickstart with the virtual environment active and replace `uv run --locked python` with `python` in the commands.

## Regenerate the requirements files

These files are exports from `app/uv.lock`. Run the following from `app/` whenever the lockfile changes.

```sh
uv export --locked --format requirements-txt --no-hashes --no-emit-project --no-dev -o ../requirements/requirements.txt
uv export --locked --format requirements-txt --no-hashes --no-emit-project -o ../requirements/requirements-dev.txt
```
