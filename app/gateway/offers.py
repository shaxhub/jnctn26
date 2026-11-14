"""Turn raw price + availability into Offer objects with an explicit orderable flag and reason.

Rules (see ASSUMPTIONS.md):
- closingTime is the order cutoff for the requested delivery date. If it is at or before "now"
  (the later of the API's timeNow and our clock), the product is NOT orderable for that date,
  even if scheduleLines still show stock.
- No closingTime / no logisticModel / empty scheduleLines -> unknown -> not orderable.
- availableAmount >= 999999 -> effectively unlimited (Terminal products always report 999999).
- availableAmount == 0 -> insufficient_stock. A limited positive amount stays orderable; the planner
  caps the quantity and splits the rest across other products.
- availableDate later than the requested date -> later_date (not orderable for that date).
"""
from __future__ import annotations

from datetime import date, datetime

from . import store
from .config import TZ, demo_catalog_enabled, settings
from .models import UNLIMITED_THRESHOLD, Offer, OrderableReason, ProductSummary
from .search import get_products
from .valio_client import RawOffers, get_client


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    # API uses +0200 style offsets; fromisoformat handles them on 3.11+
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ)
    except ValueError:
        return None


def _content_from_price(price: dict | None) -> tuple[float | None, str | None]:
    """catalogPrice / comparisonPrice = litres (or kg) per sales unit, according to Valio's own pricing."""
    if not price or price.get("error"):
        return None, None
    cat, cmp_ = price.get("catalogPrice") or {}, price.get("comparisonPrice") or {}
    unit = price.get("comparisonUnit")
    if cat.get("value") and cmp_.get("value") and unit in ("L", "KG"):
        return round(cat["value"] / cmp_["value"], 4), unit
    return None, None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_offer(p: ProductSummary, raw: dict, delivery_date: date, now: datetime) -> Offer:
    price, avail = raw.get("price"), raw.get("availability")

    # --- content per sales unit: catalog value, cross-checked against the price API ratio
    # (catalogPrice / comparisonPrice). The ratio is noisy (prices are rounded to cents), so the
    # catalog wins when both agree within 5 %; the ratio wins when they disagree or catalog is empty.
    api_content, api_unit = _content_from_price(price)
    if api_unit == "L" and p.volume_l:
        cat_content, cat_unit = p.volume_l, "L"
    elif api_unit == "KG" and p.net_weight_kg:
        cat_content, cat_unit = p.net_weight_kg, "KG"
    else:
        cat_content, cat_unit = (p.volume_l, "L") if p.volume_l else (p.net_weight_kg, "KG") if p.net_weight_kg else (None, None)
    if cat_content and (api_content is None or (api_unit == cat_unit and abs(api_content / cat_content - 1) <= 0.05)):
        content, content_unit, source = cat_content, cat_unit, "catalog" + ("+price_api" if api_content else "")
    elif api_content:
        content, content_unit, source = api_content, api_unit, "price_api" + ("(catalog_mismatch)" if cat_content else "")
    else:
        content, content_unit, source = None, None, None

    has_price = bool(price and not price.get("error"))
    cat = (price.get("catalogPrice") or {}) if has_price else {}
    unit_price = cat.get("value")
    unit_price_tax = cat.get("valueWithTax")
    tax_rate = ((price.get("tax") or {}).get("taxRate")) if has_price else None
    net_price_found = price.get("netPriceFound") if has_price else None
    valid_to = parse_ts(cat.get("validTo"))

    # --- availability
    closing = parse_ts((avail or {}).get("closingTime"))
    lines = (avail or {}).get("scheduleLines") or []
    line = lines[0] if lines else None
    amount = line.get("availableAmount") if line else None
    unlimited = amount is not None and amount >= UNLIMITED_THRESHOLD
    avail_date = _parse_date(line.get("availableDate")) if line else None
    blocked = bool((avail or {}).get("salesBlock")) or bool(line and line.get("salesBlock"))

    if unit_price is None or (valid_to is not None and valid_to <= now):
        reason = OrderableReason.no_price
    elif blocked:
        reason = OrderableReason.sales_block
    elif not avail or closing is None or not (avail or {}).get("logisticModel"):
        reason = OrderableReason.no_availability_data
    elif line is None:
        reason = OrderableReason.insufficient_stock
    elif closing <= now:
        reason = OrderableReason.cutoff_passed
    elif not unlimited and (amount or 0) <= 0:
        reason = OrderableReason.insufficient_stock
    elif avail_date and avail_date > delivery_date:
        reason = OrderableReason.later_date
    else:
        reason = OrderableReason.ok

    return Offer(
        product_id=p.id, name=p.name_fi or p.name_en, brand=p.brand, country=p.country, category=p.category,
        sales_unit=p.sales_unit, base_unit=p.base_unit, allowed_lot_size=p.allowed_lot_size,
        base_units_per_sales_unit=p.base_units_per_sales_unit, content_per_sales_unit=content, content_unit=content_unit, content_source=source,
        volume_l=p.volume_l, net_weight_kg=p.net_weight_kg,
        unit_price=unit_price, unit_price_with_tax=unit_price_tax,
        tax_rate=tax_rate,
        price_per_content_unit=round(unit_price / content, 4) if unit_price is not None and content else None,
        currency=cat.get("currency") or "EUR", price_valid_to=valid_to,
        net_price_found=net_price_found,
        available_qty=None if unlimited or amount is None else float(amount), unlimited=unlimited,
        available_date=avail_date, closing_time=closing, logistic_model=(avail or {}).get("logisticModel"),
        orderable=reason == OrderableReason.ok, reason=reason,
        reliability=p.reliability, co2_per_kg=p.co2_per_kg,
        allergens_contains=p.allergens_contains, allergens_may_contain=p.allergens_may_contain,
        claims=p.claims, labels=p.labels, substitutes=p.substitutes,
    )


def effective_now(raw: RawOffers) -> datetime:
    current = store.now()
    if store.get_demo_now() is not None or settings.demo_now:
        return current
    server = parse_ts(raw.time_now)
    return max(server, current) if server else current


def get_offers(product_ids: list[str], delivery_date: date, *, fresh: bool = False) -> tuple[list[Offer], datetime]:
    products = get_products(product_ids)
    if demo_catalog_enabled():
        from .demo_catalog import offers as synthetic_offers
        raw = synthetic_offers(list(products), delivery_date, store.now())
    else:
        raw = get_client().get_offers_raw(list(products), delivery_date, fresh=fresh)
    now = effective_now(raw)
    offers = [build_offer(products[pid], raw.products.get(pid, {}), delivery_date, now) for pid in products]
    if raw.stale:
        for offer in offers:
            offer.stale = True
    return offers, now
