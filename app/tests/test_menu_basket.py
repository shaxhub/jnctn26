import pytest
from gateway import kitchen, service
from gateway.auth import principal_for_key
from gateway.models import Offer, OrderableReason
from test_portals import gateway


def test_draft_basket_aggregates_packs_and_rechecks_stock(gateway, monkeypatch):
    row = {"ingredient": "carrot", "status": "available",
           "sourcing": {"plan": {"lines": [{"product_id": "veg", "quantity": 2}]}}}
    result = {"unresolved_dishes": [], "ingredients": [row, {**row, "ingredient": "root vegetable"}],
              "delivery_date": "2026-11-16"}
    request = kitchen.basket_request(result)
    assert len(request.lines) == 1
    assert request.lines[0].quantity == 4
    offer = Offer(product_id="veg", sales_unit="KG", orderable=True, unit_price=2, available_qty=3,
                  reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *args, **kwargs: ([offer], service.store.now()))
    buyer = principal_for_key("demo-hotel-client-key")
    with pytest.raises(service.GatewayError, match="only 3"):
        service.create_quote(buyer, request)
    assert not service.list_orders(buyer)


def test_menu_requires_every_dish_and_ingredient():
    with pytest.raises(service.GatewayError, match="Resolve every dish"):
        kitchen.basket_request({"unresolved_dishes": ["unknown"], "ingredients": []})
    with pytest.raises(service.GatewayError, match="Resolve sourcing"):
        kitchen.basket_request({"unresolved_dishes": [], "ingredients": [{"ingredient": "carrot", "status": "partial"}]})


def test_stock_recheck_enforces_signed_dietary_requirements(gateway, monkeypatch):
    from gateway.models import QuoteRequest

    buyer = principal_for_key("demo-hotel-client-key")
    request = QuoteRequest(delivery_date="2026-11-16", exclude_allergens=["milk"],
                           lines=[{"product_id": "milk", "quantity": 4}])
    quote = service.create_quote(buyer, request)
    offer = Offer(product_id="milk", sales_unit="ST", orderable=True, unit_price=2, available_qty=20,
                  allergens_may_contain=["AM"], reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *args, **kwargs: ([offer], service.store.now()))
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "rejected" and "dietary_conflict" in " ".join(order.policy.reasons)
