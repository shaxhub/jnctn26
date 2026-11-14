"""Small synthetic catalog for running the demo without Valio data or credentials."""
from datetime import date, datetime, time
import sqlite3

from .config import TZ, settings
from .load_catalog import SCHEMA
from .valio_client import RawOffers

# SKU, Finnish name, English name, category, sales unit, package size, net price, stock.
ITEMS = (
    ("490001", "Laktoositon maito 1 L", "Lactose-free milk", "10400", "ST", 1, 1.25, 500),
    ("490002", "Laktoositon kevytmaito 1 L", "Lactose-free low-fat milk", "10400", "ST", 1, 1.40, 5000),
    ("490003", "Gluteeniton kaurajuoma 1 L", "Gluten-free oat drink", "10400", "ST", 1, 2.10, 300),
    ("490004", "Peruna", "Potato", "17421", "KG", 1, 1.15, 200),
    ("490005", "Porkkana", "Carrot", "17431", "KG", 1, 1.30, 200),
    ("490006", "Tomaatti", "Tomato", "17401", "KG", 1, 2.80, 80),
    ("490007", "Punasipuli", "Red onion", "17405", "KG", 1, 1.90, 50),
    ("490008", "Basilika", "Basil", "17454", "KG", 1, 19.00, 10),
    ("490009", "Rypsiöljy 1 L", "Rapeseed oil", "10530", "ST", 1, 3.10, 200),
    ("490010", "Nauris", "Turnip", "17431", "KG", 1, 1.60, 80),
    ("490011", "Omena", "Apple", "17412", "KG", 1, 1.80, 100),
    ("490012", "Palsternakka", "Parsnip", "17431", "KG", 1, 2.30, 80),
    ("490013", "Punajuuri", "Beetroot", "17431", "KG", 1, 1.40, 80),
)


def build() -> None:
    path = settings.catalog_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.touch(exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(f"A catalog already exists at {path}. Use a new CATALOG_DB_PATH for synthetic data.") from exc
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        for sku, fi, en, category, unit, size, _, _ in ITEMS:
            dairy = sku in {"490001", "490002"}
            claims = " FREE_FROM_LACTOSE " if dairy else " FREE_FROM_GLUTEN VEGAN " if sku == "490003" else " VEGAN "
            substitutes = '["490002"]' if sku == "490001" else "[]"
            db.execute("INSERT INTO products (id,name_fi,name_en,category,country,sales_unit,base_unit,"
                       "allowed_lot_size,base_units_per_sales_unit,volume_l,net_weight_kg,allergens_contains,"
                       "allergens_may_contain,free_from,claims,labels,reliability,co2_per_kg,substitutes) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (sku, fi, en, category, "fi", unit, unit, .01 if unit == "KG" else 1, 1,
                        size if unit == "ST" else None, size if unit == "KG" else None,
                        " AM " if dairy else "", "", "", claims, "", .95, .6, substitutes))
            db.execute("INSERT INTO products_fts (id,name_fi,name_en) VALUES (?,?,?)", (sku, fi, en))
    print(f"Built synthetic catalog with {len(ITEMS)} products.")


def offers(ids: list[str], delivery: date, now: datetime) -> RawOffers:
    products = {}
    for sku, _, _, _, unit, _, price, stock in ITEMS:
        if sku not in ids:
            continue
        closing = datetime.combine(delivery, time(18), TZ)
        products[sku] = {
            "price": {"catalogPrice": {"value": price, "valueWithTax": round(price * 1.135, 2)}},
            "availability": {"logisticModel": "Stock", "closingTime": closing.isoformat(),
                             "scheduleLines": [{"availableDate": delivery.isoformat(), "availableAmount": stock,
                                                "salesUnit": unit}]},
        }
    return RawOffers(now.isoformat(), delivery.isoformat(), products=products)


if __name__ == "__main__":
    build()
