import json
from datetime import date, timedelta

from gateway import recurring, service, store
from gateway.models import QuoteLine, QuoteRequest
from test_portals import gateway


def test_recurring_drift_uses_same_buyer_weekday_and_sku(gateway):
    from gateway.auth import principal_for_key

    buyer = principal_for_key("demo-hotel-key")
    req = QuoteRequest(delivery_date=date(2026, 11, 16), lines=[{"product_id": "milk", "quantity": 50}])
    quote = service.create_quote(buyer, req)
    baseline = [QuoteLine(product_id="milk", quantity=25, sales_unit="ST", unit_price=2, line_total=50).model_dump()]
    for week in range(1, 4):
        day = req.delivery_date - timedelta(weeks=week)
        store.execute(
            "INSERT INTO orders (order_id,quote_id,buyer_id,status,total_net,currency,delivery_date,lines_json,"
            "policy_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"ord_{week}", f"historical_{week}", buyer.buyer_id, "confirmed", 50, "EUR",
             day.isoformat(), json.dumps(baseline), "{}", day.isoformat(), day.isoformat()))
    assert recurring.compare("hospital", req.delivery_date, quote.lines) == []
    assert recurring.compare("hotel", req.delivery_date + timedelta(days=1), quote.lines) == []
    comparison = service.check_recurring_quote(buyer, quote.quote_id)
    assert comparison["baselines"][0]["quantity_change_pct"] == 100
    renewed = service.create_quote(buyer, req)
    assert "standing_order_drift" in {rule.rule_id for rule in renewed.policy_preview.fired_rules}
    assert service.place_order(buyer, quote.quote_id).status == "pending_approval"
    lower_price = QuoteLine(product_id="milk", quantity=25, sales_unit="ST", unit_price=1.5, line_total=37.5)
    assert recurring.compare("hotel", req.delivery_date, [lower_price])[0]["changes"] == ["price"]
