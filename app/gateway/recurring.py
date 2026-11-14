"""Detect unusually large changes to products bought on a weekly cadence."""
from __future__ import annotations

import json
from datetime import date, timedelta
from statistics import median

from . import store
from .models import QuoteLine

QUANTITY_LIMIT = .25
PRICE_LIMIT = .15


def compare(buyer_id: str, delivery: date, lines: list[QuoteLine], *, conn=None) -> list[dict]:
    """Compare only same-SKU, same-unit lines and group history by delivery day."""
    if not lines:
        return []
    lookup = (
        "SELECT o.delivery_date, line.value FROM orders o JOIN json_each(o.lines_json) line "
        "WHERE o.buyer_id=? AND o.status='confirmed' AND o.delivery_date>=? AND o.delivery_date<? "
        "AND strftime('%w',o.delivery_date)=strftime('%w',?) "
        "AND json_extract(line.value,'$.product_id') IN (SELECT value FROM json_each(?)) "
        "ORDER BY o.delivery_date DESC"
    )
    params = (buyer_id, (delivery - timedelta(weeks=6)).isoformat(), delivery.isoformat(), delivery.isoformat(),
              json.dumps(sorted({line.product_id for line in lines})))
    rows = store.fetchall(lookup, params) if conn is None else conn.execute(lookup, params)
    history = {}
    for row in rows:
        line = QuoteLine.model_validate_json(row["value"])
        days = history.setdefault((line.product_id, line.sales_unit), {})
        qty, net = days.get(row["delivery_date"], (0.0, 0.0))
        days[row["delivery_date"]] = qty + line.quantity, net + line.line_total
    proposed = {}
    for line in lines:
        key = (line.product_id, line.sales_unit)
        qty, net = proposed.get(key, (0.0, 0.0))
        proposed[key] = qty + line.quantity, net + line.line_total
    results = []
    for (product_id, unit), (quantity, net) in proposed.items():
        days = history.get((product_id, unit), {})
        if len(days) < 3:
            continue
        saved = [(qty, total) for qty, total in days.values() if qty > 0]
        if len(saved) < 3:
            continue
        usual_qty = median(qty for qty, _ in saved)
        usual_price = median(total / qty for qty, total in saved)
        if quantity <= 0:
            continue
        unit_price = net / quantity
        qty_change = (quantity - usual_qty) / usual_qty
        price_change = (unit_price - usual_price) / usual_price if usual_price else None
        changes = []
        if round(abs(qty_change), 10) >= QUANTITY_LIMIT:
            changes.append("quantity")
        if price_change is not None and round(abs(price_change), 10) >= PRICE_LIMIT:
            changes.append("price")
        results.append({"product_id": product_id, "sales_unit": unit, "history_dates": list(days),
                        "baseline_quantity": usual_qty, "baseline_unit_price": round(usual_price, 4),
                        "current_quantity": quantity, "current_unit_price": round(unit_price, 4),
                        "quantity_change_pct": round(qty_change * 100, 2),
                        "price_change_pct": round(price_change * 100, 2) if price_change is not None else None,
                        "changes": changes})
    return results
