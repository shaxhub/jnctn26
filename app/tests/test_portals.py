from dataclasses import replace
from datetime import date, datetime

import pytest

from gateway import service, store
from gateway.auth import admin_for_key, principal_for_key
from gateway.models import Offer, OffersRequest, OrderableReason, QuoteRequest


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "settings", replace(store.settings, db_path=tmp_path / "orders.db"))
    monkeypatch.setenv("AIMO_ADMIN_API_KEY", "test-admin-credential")
    store.set_demo_now(datetime.fromisoformat("2026-11-14T10:00:00+02:00"))
    offer = Offer(product_id="milk", sales_unit="ST", unit_price=2, available_qty=2000,
                  category="10400", orderable=True, reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([offer], store.now()))
    yield
    store.set_demo_now(None)


def test_client_draft_requires_matching_client_confirmation(gateway):
    client = principal_for_key("demo-hotel-client-key")
    agent = principal_for_key("demo-hotel-key")
    other = principal_for_key("demo-hospital-client-key")
    quote = service.create_quote(client, QuoteRequest(delivery_date=date(2026, 11, 16),
                                  lines=[{"product_id": "milk", "quantity": 5}]))
    assert not service.list_orders(client)
    for caller in (agent, other):
        with pytest.raises(service.GatewayError):
            service.place_order(caller, quote.quote_id)
    order = service.place_order(client, quote.quote_id)
    assert order.status == "confirmed"
    assert store.verify_chain()["ok"]


def test_aimo_reviews_external_orders_and_upstream_failure_preserves_quote(gateway, monkeypatch):
    agent = principal_for_key("demo-hotel-key")
    buyer_approver = principal_for_key("demo-hotel-approver-key")
    admin = admin_for_key("test-admin-credential")
    quote = service.create_quote(agent, QuoteRequest(delivery_date=date(2026, 11, 16),
                                  lines=[{"product_id": "milk", "quantity": 1000}]))
    with monkeypatch.context() as patch:
        def unavailable(*_, **_options):
            raise RuntimeError("upstream unavailable")
        patch.setattr(service, "get_offers", unavailable)
        with pytest.raises(RuntimeError):
            service.place_order(agent, quote.quote_id)
    assert not service.list_orders(agent)
    order = service.place_order(agent, quote.quote_id)
    assert order.status == "pending_approval"
    with pytest.raises(service.GatewayError):
        service.decide_approval(buyer_approver, order.approval_id, "approve")
    assert service.decide_approval(admin, order.approval_id, "approve").status == "confirmed"
    assert store.verify_chain()["ok"]


def test_live_alternatives_filter_trace_allergens(gateway, monkeypatch):
    buyer = principal_for_key("demo-hotel-key")
    original = Offer(product_id="a", sales_unit="ST", unit_price=2, available_qty=0,
                     orderable=False, reason=OrderableReason.insufficient_stock, substitutes=["b", "c"])
    safe = Offer(product_id="b", sales_unit="ST", unit_price=2, available_qty=10,
                 orderable=True, reason=OrderableReason.ok, claims=["FREE_FROM_GLUTEN"])
    trace = safe.model_copy(update={"product_id": "c", "allergens_may_contain": ["AW"]})
    offers = {"a": original, "b": safe, "c": trace}
    monkeypatch.setattr(service, "get_offers", lambda ids, _, **_options: ([offers[pid] for pid in ids], store.now()))
    result = service.check_offers(buyer, OffersRequest(
        product_ids=["a"], delivery_date=date(2026, 11, 16), quantity=2, unit="ST",
        include_substitutes=True, required_claims=["FREE_FROM_GLUTEN"], exclude_allergens=["gluten"],
        postal_code="00100"))
    assert [offer["product_id"] for offer in result["alternatives"]["a"]] == ["b"]
    assert result["plan"]["plans"][0]["lines"][0]["product_id"] == "b"
    assert result["delivery_estimate"]["travel_minutes_max"] > result["delivery_estimate"]["travel_minutes_min"]


def test_portal_auth_chat_and_analytics(gateway, monkeypatch):
    import asyncio
    from httpx import ASGITransport, AsyncClient
    from gateway.api import app
    from gateway.models import ProductSummary, SearchResult

    monkeypatch.setattr(service, "search", lambda _: SearchResult(results=[
        ProductSummary(id="milk", sales_unit="ST", base_unit="ST", category="10400")
    ], total_matches=1, category_counts={"10400": 1}))
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([Offer(
        product_id="milk", sales_unit="ST", unit_price=2, available_qty=2000, net_weight_kg=1,
        co2_per_kg=2, volume_l=1, claims=["FREE_FROM_LACTOSE"], category="10400",
        orderable=True, reason=OrderableReason.ok)], store.now()))
    buyer = {"X-API-Key": "demo-hotel-client-key"}
    admin = {"X-API-Key": "test-admin-credential"}
    async def verify():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http:
            assert (await http.get("/operations/activity", headers=buyer)).status_code == 401
            assert (await http.post("/demo/reset", headers=buyer)).status_code == 401
            lookup = await http.post("/client/chat", headers=buyer, json={"text": "5 litres of lactose-free milk by Monday"})
            assert lookup.status_code == 200, lookup.text
            assert lookup.json()["draft"] is None
            assert (await http.get("/orders", headers=buyer)).json() == []
            response = await http.post("/client/chat", headers=buyer,
                                 json={"text": "Create a ticket for 5 litres of lactose-free milk by Monday"})
            assert response.status_code == 200, response.text
            draft = response.json()["draft"]
            result = await http.post("/client/tickets/submit", headers=buyer, json={"quote_id": draft["quote_id"]})
            assert result.status_code == 200 and result.json()["status"] == "confirmed", result.text
            replay = await http.post("/client/tickets/submit", headers=buyer, json={"quote_id": draft["quote_id"]})
            assert replay.status_code == 200 and replay.json()["order_id"] == result.json()["order_id"]
            assert len((await http.get("/orders", headers=buyer)).json()) == 1
            analytics = (await http.get("/operations/analytics", headers=admin)).json()
            assert analytics["sectors"]["Hospitality"]["confirmed_orders"] == 1
            assert analytics["estimated_kg_co2e"] == 10
            decisions = (await http.get("/operations/activity?kind=decisions", headers=admin)).json()["events"]
            assert "ORDER_CONFIRMED" in {event["event_type"] for event in decisions}
            assert (await http.get("/operations/activity?kind=inquiries&q=ticket", headers=admin)).json()["events"]

    asyncio.run(verify())


def test_unlisted_ingredient_match_is_live_and_requires_aimo_review(gateway, monkeypatch):
    from gateway import substitutions
    from gateway.models import ProductSummary, SearchResult

    agent = principal_for_key("demo-hotel-key")
    original = Offer(product_id="a", name="peruna 5 kg", category="10400", sales_unit="KG", unit_price=2,
                     orderable=False, reason=OrderableReason.insufficient_stock)
    alternative = original.model_copy(update={"product_id": "b", "available_qty": 20, "net_weight_kg": 1,
                                              "orderable": True, "reason": OrderableReason.ok})
    catalog = {pid: ProductSummary(id=pid, category="10400", sales_unit="KG", base_unit="KG") for pid in ("a", "b")}
    offers = {"a": original, "b": alternative}
    monkeypatch.setattr(substitutions, "search", lambda _: SearchResult(results=list(catalog.values()), total_matches=2))
    monkeypatch.setattr(service, "get_products", lambda ids: {pid: catalog[pid] for pid in ids})
    monkeypatch.setattr(service, "get_offers", lambda ids, _, **_options: ([offers[pid] for pid in ids], store.now()))
    delivery = date(2026, 11, 16)
    response = service.check_offers(agent, OffersRequest(product_ids=["a"], delivery_date=delivery,
                                    include_substitutes=True, quantity=2, unit="KG"))
    assert response["alternatives"]["a"][0]["substitution_source"] == "catalog_ingredient_match"
    quote = service.create_quote(agent, QuoteRequest(delivery_date=delivery, lines=[{"product_id": "b", "quantity": 2}],
        need={"item": "potatoes", "quantity": 2, "unit": "KG", "delivery_date": delivery, "preferred_product_ids": ["a"]}))
    assert quote.policy_preview.decision == "needs_approval"
    assert service.place_order(agent, quote.quote_id).status == "pending_approval"


def test_lookup_only_credential_cannot_order(gateway):
    agent = principal_for_key("demo-hotel-lookup-key")
    with pytest.raises(service.GatewayError, match="workspace key"):
        service.create_quote(agent, QuoteRequest(delivery_date=date(2026, 11, 16),
                                                 lines=[{"product_id": "milk", "quantity": 5}]))
    with pytest.raises(service.GatewayError):
        service.place_order(agent, "any")


def test_unverified_supplier_quantities_need_aimo_review(gateway, monkeypatch):
    buyer = principal_for_key("demo-hotel-key")
    offer = Offer(product_id="milk", sales_unit="ST", unit_price=2, orderable=True, unlimited=True,
                  logistic_model="Terminal", reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([offer], store.now()))
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=date(2026, 11, 16),
                                                    lines=[{"product_id": "milk", "quantity": 5}]))
    assert quote.policy_preview.decision == "needs_approval"
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "pending_approval"
    assert "supplier_stock_unverified" in {rule.rule_id for rule in order.policy.fired_rules}


def test_human_approval_rechecks_stock_before_confirming(gateway, monkeypatch):
    buyer = principal_for_key("demo-hotel-key")
    admin = admin_for_key("test-admin-credential")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=date(2026, 11, 16),
                                                    lines=[{"product_id": "milk", "quantity": 1000}]))
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "pending_approval"

    def new_stock(ids, delivery, *, fresh=False):
        assert fresh
        return [Offer(product_id="milk", sales_unit="ST", unit_price=2, available_qty=1,
                      category="10400", orderable=True, reason=OrderableReason.ok)], store.now()

    monkeypatch.setattr(service, "get_offers", new_stock)
    reviewed = service.decide_approval(admin, order.approval_id, "approve", "Reviewed")
    assert reviewed.status == "rejected"
    assert "insufficient_stock" in service.get_audit_log(admin, order.order_id)["text"]


def test_fresh_valio_reads_bypass_cache_and_propagate_failure(monkeypatch):
    import httpx
    from gateway.valio_client import ValioClient

    client = ValioClient(api_key="test-only")
    calls = []
    def upstream(path, customer, day, ids):
        calls.append(path)
        return {"products": [{"productId": ids[0], "revision": len(calls)}]}

    monkeypatch.setattr(client, "_post", upstream)
    delivery = date(2026, 11, 16)
    try:
        first = client.get_offers_raw(["milk"], delivery)
        assert first == client.get_offers_raw(["milk"], delivery)
        refreshed = client.get_offers_raw(["milk"], delivery, fresh=True)
        assert first.products != refreshed.products
        def down(*args):
            raise httpx.ConnectError("unavailable")
        monkeypatch.setattr(client, "_post", down)
        with pytest.raises(httpx.ConnectError):
            client.get_offers_raw(["milk"], delivery, fresh=True)
    finally:
        client._http.close()
