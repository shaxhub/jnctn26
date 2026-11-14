"""Settings, read once from the environment (and app/.env if present).

Relative paths are resolved against the app/ folder, so commands work from any cwd.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

TZ = ZoneInfo("Europe/Helsinki")


def demo_catalog_enabled() -> bool:
    return os.getenv("OFFLINE_DEMO") == "1"


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (APP_DIR / p).resolve()


@dataclass(frozen=True)
class Settings:
    valio_api_key: str
    valio_base_url: str
    valio_customer_id: str
    data_dir: Path
    catalog_db_path: Path
    db_path: Path
    anthropic_api_key: str
    signing_key_path: Path
    cache_ttl_s: int
    agent_model: str
    demo_now: str = ""


def load_settings() -> Settings:
    return Settings(
        valio_api_key=os.getenv("VALIO_API_KEY", ""),
        valio_base_url=os.getenv("VALIO_BASE_URL", "https://junction26.valioaimo.fi/api").rstrip("/"),
        valio_customer_id=os.getenv("VALIO_CUSTOMER_ID", "123"),
        data_dir=_path(os.getenv("DATA_DIR", "../external/valio-aimo")),
        catalog_db_path=_path(os.getenv("CATALOG_DB_PATH", "data/catalog.db")),
        db_path=_path(os.getenv("DB_PATH", "data/gateway.db")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        signing_key_path=_path(os.getenv("SIGNING_KEY_PATH", "data/quote_signing_key.pem")),
        cache_ttl_s=int(os.getenv("VALIO_CACHE_TTL_S", "60")),
        agent_model=os.getenv("AGENT_MODEL", "claude-opus-5-5"),
        demo_now=os.getenv("DEMO_NOW", ""),
    )


settings = load_settings()

PRODUCT_FILE = "valio_aimo_junction26_product_data.json"
RELIABILITY_FILE = "valio_aimo_junction26_delivery_reliability.csv"
CARBON_FILE = "valio_aimo_junction26_carbon_footprint.csv"
