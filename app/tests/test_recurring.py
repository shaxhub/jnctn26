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


def test_repeat_preserves_dietary_constraints_and_checks_ownership(gateway):
    import pytest
    from gateway import quotes
    from gateway.auth import principal_for_key

    buyer = principal_for_key("demo-hotel-key")
    other = principal_for_key("demo-hospital-key")
    read_only = principal_for_key("demo-hotel-lookup-key")
    first_day = date(2026, 11, 16)
    first_quote = service.create_quote(buyer, QuoteRequest(delivery_date=first_day,
        lines=[{"product_id": "milk", "quantity": 10}], exclude_allergens=["nuts"]))
    original = service.place_order(buyer, first_quote.quote_id)
    next_day = first_day + timedelta(days=7)
    with pytest.raises(service.GatewayError, match="not found"):
        service.repeat_quote(other, original.order_id, next_day)
    with pytest.raises(service.GatewayError, match="workspace key"):
        service.repeat_quote(read_only, original.order_id, next_day)
    repeat = service.repeat_quote(buyer, original.order_id, next_day)
    assert repeat.delivery_date == next_day
    assert quotes.verify(repeat.signature)["exclude_allergens"] == ["nuts"]
    assert len(service.list_orders(buyer)) == 1
