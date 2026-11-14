"""Structured product search over the SQLite catalog (static data only, no API calls).

Search narrows the catalog first; prices and availability are fetched only for the shortlist
(the challenge API asks for exactly that).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from .config import settings
from .models import ProductSummary, SearchRequest, SearchResult, expand_allergens

_CLAIM_ALIASES = {
    "lactose": "FREE_FROM_LACTOSE", "lactose-free": "FREE_FROM_LACTOSE", "laktoositon": "FREE_FROM_LACTOSE",
    "gluten": "FREE_FROM_GLUTEN", "gluten-free": "FREE_FROM_GLUTEN", "gluteeniton": "FREE_FROM_GLUTEN",
    "vegan": "VEGAN", "vegetarian": "VEGETARIAN", "egg": "FREE_FROM_EGGS", "soy": "FREE_FROM_SOY",
}


_CLAIM_TO_FREE_FROM: dict[str, tuple[str, ...]] = {
    "FREE_FROM_LACTOSE": ("ML",),
    "FREE_FROM_GLUTEN": ("AW", "UW"),
    "FREE_FROM_EGGS": ("AE",),
    "FREE_FROM_SOY": ("AY",),
    "FREE_FROM_MILK": ("AM",),
}


def normalize_claims(items: list[str]) -> list[str]:
    return sorted({_CLAIM_ALIASES.get(x.lower(), x.upper()) for x in items})


@lru_cache(maxsize=1)
def _catalog_path() -> str:
    path = settings.catalog_db_path
    if not path.exists():
        raise RuntimeError(f"Catalog not found at {path}. Run: uv run python -m gateway.load_catalog")
    return str(path)


@contextmanager
def catalog_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(f"file:{_catalog_path()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _split(codes: str | None) -> list[str]:
    return (codes or "").split()


def row_to_summary(r: sqlite3.Row) -> ProductSummary:
    return ProductSummary(
        id=r["id"], name_fi=r["name_fi"], name_en=r["name_en"], brand=r["brand"], vendor=r["vendor"],
        country=r["country"], category=r["category"], sales_unit=r["sales_unit"], base_unit=r["base_unit"],
        base_units_per_sales_unit=r["base_units_per_sales_unit"] or 1.0,
        volume_l=r["volume_l"], net_weight_kg=r["net_weight_kg"], allowed_lot_size=r["allowed_lot_size"],
        allergens_contains=_split(r["allergens_contains"]), allergens_may_contain=_split(r["allergens_may_contain"]),
        claims=_split(r["claims"]), labels=_split(r["labels"]), reliability=r["reliability"],
        co2_per_kg=r["co2_per_kg"], substitutes=json.loads(r["substitutes"] or "[]"),
    )


def get_products(ids: list[str]) -> dict[str, ProductSummary]:
    if not ids:
        return {}
    unique = list(dict.fromkeys(ids))
    with catalog_conn() as conn:
        rows = conn.execute(f"SELECT * FROM products WHERE id IN ({','.join('?' * len(unique))})", unique).fetchall()
    by_id = {r["id"]: row_to_summary(r) for r in rows}
    return {pid: by_id[pid] for pid in unique if pid in by_id}


def _fts_query(text: str) -> str | None:
    # trigram tokenizer: every word of 3+ chars must appear as a substring (AND)
    words = list(dict.fromkeys(w for w in re.sub(r"[^\w\s]", " ", text).split() if len(w) >= 3))[:24]
    return " AND ".join(f'"{w}"' for w in words) or None


def search(req: SearchRequest) -> SearchResult:
    where, params = [], []
    fts = _fts_query(req.text)
    if fts:
        where.append("p.id IN (SELECT id FROM products_fts WHERE products_fts MATCH ?)")
        params.append(fts)
    for claim in normalize_claims(req.free_from):
        ff_codes = _CLAIM_TO_FREE_FROM.get(claim, ())
        if ff_codes:
            ff_clauses = " OR ".join("p.free_from LIKE ?" for _ in ff_codes)
            where.append(f"(p.claims LIKE ? OR {ff_clauses})")
            params.append(f"% {claim} %")
            params.extend(f"% {c} %" for c in ff_codes)
        else:
            where.append("p.claims LIKE ?")
            params.append(f"% {claim} %")
    for code in expand_allergens(req.exclude_allergens):
        where.append("p.allergens_contains NOT LIKE ?")
        params.append(f"% {code} %")
    for label in req.labels:
        where.append("p.labels LIKE ?")
        params.append(f"% {label} %")
    if req.category:
        where.append("p.category LIKE ?")
        params.append(req.category + "%")
    for term in req.exclude_terms:
        where.append("lower(coalesce(p.name_fi,'') || ' ' || coalesce(p.name_en,'')) NOT LIKE ?")
        params.append(f"%{term.lower()}%")
    sql = "SELECT p.* FROM products p" + (" WHERE " + " AND ".join(where) if where else "")
    try:
        with catalog_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError("Invalid search query") from exc
    rows.sort(key=lambda r: (
        r["category"] != req.category if req.category else False,
        -(r["reliability"] if r["reliability"] is not None else 0.95),
        len(r["name_fi"] or ""),
    ))
    cats = Counter(r["category"] for r in rows)
    return SearchResult(results=[row_to_summary(r) for r in rows[: req.limit]], total_matches=len(rows),
                        category_counts=dict(cats.most_common(10)))
