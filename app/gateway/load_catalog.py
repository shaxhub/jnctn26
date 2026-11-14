"""Build the SQLite catalog (products + FTS5 index) from the challenge files.

    uv run python -m gateway.load_catalog            # uses DATA_DIR and CATALOG_DB_PATH
    uv run python -m gateway.load_catalog --data-dir ../external/valio-aimo --db data/catalog.db

The product JSON is parsed once with json.load (about 1 GB of RAM for a few seconds).
Lists of codes (allergens, claims, labels) are stored as space-padded strings like " AM AW "
so a filter is a simple `LIKE '% AM %'`.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from pathlib import Path

from .config import CARBON_FILE, PRODUCT_FILE, RELIABILITY_FILE, settings

SCHEMA = """
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS products_fts;
CREATE TABLE products (
    id TEXT PRIMARY KEY,
    name_fi TEXT, name_en TEXT, name_sv TEXT,
    category TEXT, vendor TEXT, brand TEXT, country TEXT,
    sales_unit TEXT, base_unit TEXT, allowed_lot_size REAL, temperature_condition INTEGER,
    units_json TEXT,                    -- [{unitId, sizeInBaseUnits, gtin}]
    base_units_per_sales_unit REAL,     -- units[salesUnit].sizeInBaseUnits
    volume_l REAL,                      -- litres per SALES unit, if derivable
    net_weight_kg REAL,                 -- kg per SALES unit, if derivable
    content_source TEXT,                -- 'synkka' | 'name' | 'base_unit' | NULL
    allergens_contains TEXT,            -- ' AM AW '
    allergens_may_contain TEXT,
    free_from TEXT,                     -- nonAllergen FREE_FROM codes
    claims TEXT,                        -- nutritionalClaim ids, e.g. ' FREE_FROM_LACTOSE VEGAN '
    labels TEXT,                        -- packagingMarkedLabel ids
    reliability REAL,                   -- 0..1 from delivery reliability CSV
    co2_per_kg REAL,                    -- product average kg CO2e/kg from carbon CSV
    substitutes TEXT,                   -- JSON list of product ids
    key_ingredients_fi TEXT
);
CREATE INDEX idx_products_category ON products(category);
-- trigram tokenizer = substring search, which matters for Finnish compounds (kevytmaito, täysmaito)
CREATE VIRTUAL TABLE products_fts USING fts5(
    id UNINDEXED, name_fi, name_en, name_sv, brand, tokenize='trigram'
);
"""

# number + unit inside a product name, e.g. "1 l", "2,5 dl", "100x2 cl", "5 kg", "400 g"
_SIZE = r"(\d+(?:[.,]\d+)?)\s*(l|dl|cl|ml|kg|g)\b"
_MULTI_RE = re.compile(r"(\d+)\s*[x×]\s*" + _SIZE, re.I)
_KPL_BEFORE_RE = re.compile(r"(\d+)\s*(?:kpl|st|pcs)\s*[x×/]?\s*" + _SIZE, re.I)
_KPL_AFTER_RE = re.compile(
    _SIZE + r"\s*[x×/]\s*(\d+)(?![.,]\d)(?!\s*(?:l|dl|cl|ml|kg|g|cm|mm|m)\b)\s*(?:kpl|st|pcs)?\b",
    re.I,
)
_SINGLE_RE = re.compile(_SIZE, re.I)
_TO_BASE = {"l": ("L", 1.0), "dl": ("L", 0.1), "cl": ("L", 0.01), "ml": ("L", 0.001),
            "kg": ("KG", 1.0), "g": ("KG", 0.001)}
_VOL_FACTORS = {"LTR": 1.0, "MLT": 0.001, "CLT": 0.01}
_CASE_SALES_UNITS = ("KI", "CS", "BX", "LTK", "KLE", "KRT", "SK")
_CASE_DIVISOR_UNITS = ("KI", "CS", "KLE", "KRT")
_NON_ALLERGEN_TO_CLAIM = {
    "ML": "FREE_FROM_LACTOSE",
    "AW": "FREE_FROM_GLUTEN",
    "UW": "FREE_FROM_GLUTEN",
    "AE": "FREE_FROM_EGGS",
    "AY": "FREE_FROM_SOY",
    "AM": "FREE_FROM_MILK",
}


def _name(names: list[dict], lang: str) -> str | None:
    return next((n["value"] for n in names if n.get("language") == lang), None)


def _codes(values) -> str:
    return " " + " ".join(sorted(set(values))) + " " if values else ""


def parse_size_from_name(name: str) -> tuple[float | None, str | None, int | None]:
    """Return (size per consumer item, 'L'|'KG', multipack count) parsed from a product name."""
    if not name:
        return None, None, None
    for pat in (_MULTI_RE, _KPL_BEFORE_RE):
        m = pat.search(name)
        if m:
            unit, f = _TO_BASE[m.group(3).lower()]
            return float(m.group(2).replace(",", ".")) * f, unit, int(m.group(1))
    m = _KPL_AFTER_RE.search(name)
    if m:
        unit, f = _TO_BASE[m.group(2).lower()]
        return float(m.group(1).replace(",", ".")) * f, unit, int(m.group(3))
    m = _SINGLE_RE.search(name)
    if m:
        unit, f = _TO_BASE[m.group(2).lower()]
        return float(m.group(1).replace(",", ".")) * f, unit, None
    return None, None, None


def _extract_uc_measures(uc: dict) -> tuple[float | None, float | None]:
    """Extract (volume_l, net_weight_kg) from a synkka unitConversion entry."""
    vol, nw = uc.get("volume"), uc.get("netWeight")
    # volume.unit is sometimes GRM or H87 (pieces) in this data set: only trust real volume units
    v_val = (vol["value"] * _VOL_FACTORS[vol["unit"]]
             if vol and vol.get("unit") in _VOL_FACTORS and vol.get("value") is not None else None)
    k_val = (nw["value"] * (0.001 if nw["unit"] == "GRM" else 1.0)
             if nw and nw.get("unit") in ("GRM", "KGM") and nw.get("value") is not None else None)
    return v_val, k_val


def derive_content(p: dict, name_fi: str | None) -> tuple[float | None, float | None, str | None, float]:
    """Litres and kg per SALES unit. Returns (volume_l, net_weight_kg, source, base_units_per_sales_unit)."""
    units = {u["unitId"]: u.get("sizeInBaseUnits") or 1.0 for u in p.get("units", [])}
    per_sales = float(units.get(p["salesUnit"], 1.0))

    base_vol = base_kg = case_vol = case_kg = None
    for uc in p.get("synkkaData", {}).get("unitConversions", []):
        pt = uc.get("synkkaPackagingType")
        if pt not in ("BASE_UNIT_OR_EACH", "CASE"):
            continue
        v_val, k_val = _extract_uc_measures(uc)
        if pt == "BASE_UNIT_OR_EACH":
            if v_val is not None:
                base_vol = v_val
            if k_val is not None:
                base_kg = k_val
        else:
            if v_val is not None:
                case_vol = v_val
            if k_val is not None:
                case_kg = k_val

    if p["baseUnit"] == "KG":
        vol_l = base_vol * per_sales if base_vol is not None else None
        return vol_l, per_sales, "base_unit", per_sales

    if base_vol is not None or base_kg is not None:
        return (base_vol * per_sales if base_vol is not None else None,
                base_kg * per_sales if base_kg is not None else None, "synkka", per_sales)

    if case_vol is not None or case_kg is not None:
        if p["salesUnit"] in _CASE_SALES_UNITS:
            scale = 1.0
        else:
            case_factor = next((units[uid] for uid in _CASE_DIVISOR_UNITS if uid in units and units[uid] > 1), None)
            scale = per_sales / float(case_factor) if case_factor else 1.0
        return (case_vol * scale if case_vol is not None else None,
                case_kg * scale if case_kg is not None else None, "synkka", per_sales)

    size, unit, count = parse_size_from_name(name_fi or "")
    if size is None:
        return None, None, None, per_sales
    if count and (p["salesUnit"] == p["baseUnit"] or (per_sales == 1.0 and count > 1)):
        total = size * count            # "100x2 cl" sold as one box or multipack with per_sales=1
    else:
        total = size * per_sales        # "12 x ... 1 L" sold as KI of 12 ST, or "1 l" sold as KI of 5
    return (total, None, "name", per_sales) if unit == "L" else (None, total, "name", per_sales)


def _read_csv(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            if len(row) >= 2 and row[1]:
                out[row[0].strip()] = float(row[1])
    return out


def build(data_dir: Path, db_path: Path) -> dict:
    t0 = time.time()
    products = json.loads((data_dir / PRODUCT_FILE).read_text(encoding="utf-8"))
    reliability = _read_csv(data_dir / RELIABILITY_FILE)
    co2 = _read_csv(data_dir / CARBON_FILE)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    rows, fts = [], []
    for p in products:
        if p.get("deleted"):
            continue
        s = p.get("synkkaData", {})
        names = s.get("names", [])
        name_fi, name_en, name_sv = _name(names, "fi"), _name(names, "en"), _name(names, "sv")
        contains, may, free_from, claims, labels = [], [], [], [], []
        for c in s.get("classifications", []):
            for v in c.get("values", []):
                if c["name"] == "allergen":
                    (contains if v.get("unit") == "CONTAINS" else may if v.get("unit") == "MAY_CONTAIN" else []).append(v["id"])
                elif c["name"] == "nonAllergen" and v.get("unit") == "FREE_FROM":
                    free_from.append(v["id"])
                    if v["id"] in _NON_ALLERGEN_TO_CLAIM:
                        claims.append(_NON_ALLERGEN_TO_CLAIM[v["id"]])
                elif c["name"] == "nutritionalClaim":
                    claims.append(v["id"])
                elif c["name"] == "packagingMarkedLabel":
                    labels.append(v["id"])
        vol, kg, src, per_sales = derive_content(p, name_fi)
        subs = [x["substituteProduct"] for x in p.get("substitutions") or [] if x.get("product") == p["id"]]
        rows.append((
            p["id"], name_fi, name_en, name_sv, p.get("category"), p.get("vendorName"), s.get("brand"),
            p.get("countryOfOrigin"), p["salesUnit"], p["baseUnit"], p.get("allowedLotSize"),
            p.get("temperatureCondition"), json.dumps(p.get("units", [])), per_sales, vol, kg, src,
            _codes(contains), _codes(may), _codes(free_from), _codes(claims), _codes(labels),
            reliability.get(p["id"]), co2.get(p["id"]), json.dumps(subs),
            _name(s.get("keyIngredients", []), "fi"),
        ))
        fts.append((p["id"], name_fi or "", name_en or "", name_sv or "", s.get("brand") or ""))
    if rows:
        conn.executemany(f"INSERT INTO products VALUES ({','.join('?' * len(rows[0]))})", rows)
        conn.executemany("INSERT INTO products_fts VALUES (?,?,?,?,?)", fts)
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    return {"products": len(rows), "seconds": round(time.time() - t0, 1),
            "db_path": str(db_path), "db_mb": round(db_path.stat().st_size / 1e6, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=settings.data_dir)
    ap.add_argument("--db", type=Path, default=settings.catalog_db_path)
    a = ap.parse_args()
    print(json.dumps(build(a.data_dir, a.db), indent=2))


if __name__ == "__main__":
    main()
