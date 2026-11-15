from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from gateway import service, store
from gateway.auth import admin_for_key, principal_for_key
from gateway.models import Offer, OffersRequest, OrderableReason, QuoteRequest
from gateway.preferences import Preferences
from gateway.workspace import save_settings


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(store, "settings", replace(store.settings, db_path=tmp_path / "orders.db"))
    monkeypatch.setenv("AIMO_ADMIN_API_KEY", "test-admin-credential")
    for buyer in ("hotel", "hospital"):
        save_settings(Preferences(address="Testikatu 1, 00100 Helsinki"),
                      principal_for_key(f"demo-{buyer}-client-key"))
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
    from gateway.admin_app import app as admin_app
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
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as http,
            AsyncClient(transport=ASGITransport(app=admin_app), base_url='http://admin') as ops,
        ):
            assert (await ops.get("/operations/activity", headers=buyer)).status_code == 401
            assert (await ops.post("/demo/reset", headers=buyer)).status_code == 401
            lookup = await http.post("/client/chat", headers=buyer, json={"text": "5 litres of lactose-free milk by Monday"})
            assert lookup.status_code == 200, lookup.text
            assert lookup.json()["draft"] is None
            shopping = await http.post("/client/chat", headers=buyer,
                                       json={"text": "5 litres of lactose-free milk by Monday, postcode 00100", "action": "shop"})
            assert shopping.status_code == 200 and shopping.json()["draft"]
            missing_delivery = await http.post("/client/chat", headers=buyer,
                                              json={"text": "5 litres of lactose-free milk", "action": "shop"})
            assert missing_delivery.status_code == 422
            assert "delivery date and five-digit delivery postcode" in missing_delivery.json()["detail"]
            assert (await http.get("/orders", headers=buyer)).json() == []
            response = await http.post("/client/chat", headers=buyer,
                                 json={"text": "Create a ticket for 5 litres of lactose-free milk by Monday"})
            assert response.status_code == 200, response.text
            draft = response.json()["draft"]
            from gateway.quotes import verify
            signed = verify(draft["signature"])
            assert signed["lines"][0]["availability_checked_at"]
            assert signed["lines"][0]["available_sales_units"] == 2000
            changed = await http.post("/client/chat", headers=buyer, json={
                "text": "5 litres of lactose-free milk by Monday", "action": "draft",
                "plan_lines": [["milk", 99]]})
            assert changed.status_code == 200 and changed.json()["draft"] is None
            incomplete = await http.post("/client/chat", headers=buyer,
                json={"text": "Create a ticket for lactose-free milk by Monday"})
            assert incomplete.status_code == 200 and incomplete.json()["draft"] is None
            assert "quantity and unit" in incomplete.json()["message"]
            unrelated = await http.post("/client/chat", headers=buyer, json={"text": "Unrelated milk lookup"})
            assert unrelated.status_code == 200
            for address in ("Testikatu 1", "00100", "FI-00100"):
                incomplete_address = await http.post("/client/tickets/submit", headers=buyer, json={
                    "quote_id": draft["quote_id"], "delivery_address": address})
                assert incomplete_address.status_code == 422, incomplete_address.text
                assert "street address" in incomplete_address.json()["detail"]
            assert (await http.get("/orders", headers=buyer)).json() == []
            result = await http.post("/client/tickets/submit", headers=buyer, json={
                "quote_id": draft["quote_id"], "delivery_address": "Hotel kitchen, Testikatu, 00100 Helsinki"})
            assert result.status_code == 200 and result.json()["status"] == "confirmed", result.text
            assert result.json()["delivery_address"] == "Hotel kitchen, Testikatu, 00100 Helsinki"
            listed = (await ops.get("/operations/orders?q=testikatu", headers=admin)).json()["orders"]
            assert [order["delivery_address"] for order in listed] == [result.json()["delivery_address"]]
            replay = await http.post("/client/tickets/submit", headers=buyer, json={"quote_id": draft["quote_id"]})
            assert replay.status_code == 200 and replay.json()["order_id"] == result.json()["order_id"]
            assert len((await http.get("/orders", headers=buyer)).json()) == 1
            analytics = (await ops.get("/operations/analytics", headers=admin)).json()
            assert analytics["sectors"]["Hospitality"]["confirmed_orders"] == 1
            assert analytics["estimated_kg_co2e"] == 10
            assert analytics["inquiries"] == 6
            detail = (await ops.get("/operations/orders/" + result.json()["order_id"], headers=admin)).json()
            history = detail["audit"]["events"]
            assert [event["data"]["text"] for event in history if event["event_type"] == "CLIENT_INQUIRY"] == [
                "Create a ticket for 5 litres of lactose-free milk by Monday"]
            assert sum(event["event_type"] == "OFFERS_CHECKED" for event in history) == 1
            decisions = (await ops.get("/operations/activity?kind=decisions", headers=admin)).json()["events"]
            assert "ORDER_CONFIRMED" in {event["event_type"] for event in decisions}
            assert (await ops.get("/operations/activity?kind=inquiries&q=ticket", headers=admin)).json()["events"]

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
        client._cache = {key: (expiry - 61, data) for key, (expiry, data) in client._cache.items()}
        assert client.get_offers_raw(["milk"], delivery).stale
        client._cache = {key: (expiry - 301, data) for key, (expiry, data) in client._cache.items()}
        with pytest.raises(httpx.ConnectError):
            client.get_offers_raw(["milk"], delivery)
    finally:
        client._http.close()


def test_expired_pending_order_leaves_queue_and_releases_spend(gateway):
    buyer = principal_for_key("demo-hotel-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=date(2026, 11, 16),
                                                    lines=[{"product_id": "milk", "quantity": 1000}]))
    order = service.place_order(buyer, quote.quote_id)
    assert service.weekly_spent(buyer.buyer_id) == 2000
    store.set_demo_now(quote.expires_at + timedelta(seconds=1))
    assert service.weekly_spent(buyer.buyer_id) == 0
    assert service.list_approvals(buyer) == []
    assert service.get_order(buyer, order.order_id).status == "expired"
    timeline = service.get_audit_log(buyer, order.order_id)
    assert sum(event["event_type"] == "ORDER_EXPIRED" for event in timeline["events"]) == 1


def test_offer_lookup_checks_later_dates_only_when_requested(gateway, monkeypatch):
    buyer = principal_for_key("demo-hotel-key")
    monday = date(2026, 11, 16)
    tuesday = date(2026, 11, 17)
    dates = []
    def offers(ids, day):
        dates.append(day)
        return [Offer(product_id=ids[0], sales_unit="ST", unit_price=2, available_date=tuesday,
                      available_qty=20, orderable=day == tuesday,
                      reason=OrderableReason.ok if day == tuesday else OrderableReason.later_date)], store.now()
    monkeypatch.setattr(service, "get_offers", offers)
    lookup = OffersRequest(product_ids=["milk"], delivery_date=monday)
    assert "next_delivery_options" not in service.check_offers(buyer, lookup)
    assert dates == [monday]
    result = service.check_offers(buyer, lookup.model_copy(update={"include_next_delivery": True}))
    assert result["delivery_date"] == monday.isoformat()
    assert result["next_delivery_options"][0]["delivery_date"] == tuesday.isoformat()
    assert dates == [monday, monday, tuesday]


def test_later_delivery_does_not_suggest_an_excluded_allergen(gateway, monkeypatch):
    buyer = principal_for_key("demo-hospital-key")
    later = date(2026, 11, 17)
    def lookup(ids, day):
        return [Offer(product_id="milk", sales_unit="ST", unit_price=2, available_date=later,
                      allergens_contains=["AM"], orderable=day == later,
                      reason=OrderableReason.ok if day == later else OrderableReason.later_date)], store.now()
    monkeypatch.setattr(service, "get_offers", lookup)
    request = OffersRequest(product_ids=["milk"], delivery_date=date(2026, 11, 16), include_next_delivery=True)
    assert service.check_offers(buyer, request)["next_delivery_options"] == []


def test_concurrent_submissions_reserve_weekly_limit_atomically(gateway):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    agent = principal_for_key("demo-hotel-key")
    buyer = replace(agent, mandate=agent.mandate.model_copy(update={"max_weekly_total": 1000}))
    delivery = date(2026, 11, 16)
    request = QuoteRequest(delivery_date=delivery, lines=[{"product_id": "milk", "quantity": 300}])
    quotes = [service.create_quote(buyer, request) for _ in range(2)]
    barrier = Barrier(2, timeout=5)

    def submit(quote):
        barrier.wait()
        return service.place_order(buyer, quote.quote_id).status

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(submit, quotes)) == ["confirmed", "pending_approval"]
    assert store.verify_chain()["ok"]

def test_approval_rejects_newly_reported_forbidden_allergen(gateway, monkeypatch):
    buyer = principal_for_key("demo-hospital-key")
    admin = admin_for_key("test-admin-credential")
    offer = Offer(product_id="milk", sales_unit="ST", unit_price=2, available_qty=2000,
                  category="10400", orderable=True, reason=OrderableReason.ok, logistic_model="Terminal",
                  unlimited=True)
    monkeypatch.setattr(service, "get_offers", lambda *args, **kwargs: ([offer], store.now()))
    request = QuoteRequest(delivery_date=date(2026, 11, 16), lines=[{"product_id": "milk", "quantity": 5}])
    order = service.place_order(buyer, service.create_quote(buyer, request).quote_id)
    assert order.status == "pending_approval"
    offer.allergens_contains = ["AM"]
    reviewed = service.decide_approval(admin, order.approval_id, "approve")
    assert reviewed.status == "rejected"
    assert "forbidden allergen" in service.get_audit_log(admin, reviewed.order_id)["text"]


def test_signing_key_creation_reuses_the_winner(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from gateway import quotes

    destination = tmp_path / "signing.pem"
    monkeypatch.setattr(quotes, "settings", replace(quotes.settings, signing_key_path=destination))
    winner = Ed25519PrivateKey.generate()
    pem = winner.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())

    def publish_other_key(candidate, path):
        assert candidate.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")
        path.write_bytes(pem)
        raise FileExistsError

    monkeypatch.setattr(quotes.os, "link", publish_other_key)
    quotes.private_key.cache_clear()
    try:
        assert quotes.public_key().public_bytes_raw() == winner.public_key().public_bytes_raw()
        assert list(tmp_path.iterdir()) == [destination]
    finally:
        quotes.private_key.cache_clear()


def test_invalid_quantities_huge_budgets_and_gateway_clock_header(gateway, monkeypatch):
    import asyncio
    import anthropic
    import httpx
    from httpx import ASGITransport, AsyncClient
    from gateway import accounts, agent as agent_mod, api as api_mod
    from gateway.api import app

    client_headers = {"X-API-Key": "demo-hotel-client-key"}
    agent_headers = {"X-API-Key": "demo-hotel-key"}

    async def verify():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://client.test") as http:
            health = await http.get("/health")
            assert health.status_code == 200
            assert health.headers["X-Gateway-Now"] == store.now().isoformat()

            for bad_text in ("0 litres of milk by Monday", "2,000,000 litres of milk by Monday",
                             "9" * 400 + " litres of milk by Monday"):
                chat_res = await http.post("/client/chat", headers=client_headers, json={"text": bad_text})
                assert chat_res.status_code == 422, chat_res.text
                assert "1,000,000" in chat_res.json()["detail"]
                assert chat_res.headers["X-Gateway-Now"] == store.now().isoformat()

                agent_res = await http.post("/agent/run", headers=agent_headers,
                                            json={"text": bad_text, "mode": "scripted"})
                assert agent_res.status_code == 422, agent_res.text
                assert "1,000,000" in agent_res.json()["detail"]

            huge_budget = (
                "Feed 200 schoolchildren on Wednesday. Hard budget is " + ("9" * 400) + " euros."
            )
            meal_res = await http.post("/client/chat", headers=client_headers, json={"text": huge_budget})
            assert meal_res.status_code == 422, meal_res.text
            assert "budget" in meal_res.json()["detail"].lower()

            # LLM agent API errors map to 502 JSON instead of crashing with 500
            with monkeypatch.context() as patch:
                with_key = replace(agent_mod.settings, anthropic_api_key="test-key")
                patch.setattr(agent_mod, "settings", with_key)
                patch.setattr(api_mod, "settings", with_key)
                req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

                def fail_llm(*_a, **_kw):
                    raise anthropic.APIConnectionError(request=req)

                patch.setattr(agent_mod, "parse_need_llm", fail_llm)
                llm_res = await http.post("/agent/run", headers=agent_headers,
                                          json={"text": "10 litres of milk by Monday", "mode": "llm"})
                assert llm_res.status_code == 502
                assert "temporarily unavailable" in llm_res.json()["detail"]

            # Hosted mode blocks buyer-side /approvals/{id} with a clear 403 message
            with monkeypatch.context() as patch:
                patch.setenv("REQUIRE_PORTAL_LOGIN", "1")
                accounts.provision("hotel-user", "client", "hotel", "a-local-test-only-password")
                login = await http.post("/session/login", headers={"Origin": "https://client.test"},
                                        json={"username": "hotel-user", "password": "a-local-test-only-password"})
                assert login.status_code == 200
                decide_res = await http.post("/approvals/apr_any", headers={"Origin": "https://client.test"},
                                             json={"decision": "approve"})
                assert decide_res.status_code == 403
                assert "Aimo operations portal" in decide_res.json()["detail"]

    asyncio.run(verify())


def test_live_mode_stock_reservation_prevents_double_spend(gateway, monkeypatch):
    offer = Offer(product_id="milk", sales_unit="ST", unit_price=2, available_qty=10,
                  category="10400", orderable=True, reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([offer], store.now()))
    buyer = principal_for_key("demo-hotel-client-key")
    agent = principal_for_key("demo-hotel-key")
    admin = admin_for_key("test-admin-credential")
    delivery = date(2026, 11, 16)

    # Two pre-created quotes before any order is placed: second place_order must reject when stock is exhausted
    q1 = service.create_quote(buyer, QuoteRequest(delivery_date=delivery, lines=[{"product_id": "milk", "quantity": 6}]))
    q2 = service.create_quote(buyer, QuoteRequest(delivery_date=delivery, lines=[{"product_id": "milk", "quantity": 6}]))
    first = service.place_order(buyer, q1.quote_id)
    assert first.status == "confirmed"
    second = service.place_order(buyer, q2.quote_id)
    assert second.status == "rejected"
    assert "milk:insufficient_stock" in " ".join(second.policy.reasons)

    # Subsequent create_quote also sees only 4 remaining ST on that delivery date
    with pytest.raises(service.GatewayError, match="only 4 ST available"):
        service.create_quote(buyer, QuoteRequest(delivery_date=delivery, lines=[{"product_id": "milk", "quantity": 5}]))
    q3 = service.create_quote(buyer, QuoteRequest(delivery_date=delivery, lines=[{"product_id": "milk", "quantity": 4}]))
    assert service.place_order(buyer, q3.quote_id).status == "confirmed"

    # Approval recheck also accounts for committed stock on another day without counting the order against itself
    next_day = date(2026, 11, 17)
    big_offer = Offer(product_id="milk", sales_unit="ST", unit_price=200, available_qty=10,
                      category="10400", orderable=True, reason=OrderableReason.ok)
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([big_offer], store.now()))
    q_pending = service.create_quote(agent, QuoteRequest(delivery_date=next_day, lines=[{"product_id": "milk", "quantity": 7}]))
    q_small = service.create_quote(buyer, QuoteRequest(delivery_date=next_day, lines=[{"product_id": "milk", "quantity": 4}]))
    small_confirmed = service.place_order(buyer, q_small.quote_id)
    assert small_confirmed.status == "confirmed"
    # Placed before small_confirmed existed? No, place q_pending on a third day before a concurrent confirmation:
    third_day = date(2026, 11, 18)
    q_pend_a = service.create_quote(agent, QuoteRequest(delivery_date=third_day, lines=[{"product_id": "milk", "quantity": 7}]))
    q_fast_b = service.create_quote(buyer, QuoteRequest(delivery_date=third_day, lines=[{"product_id": "milk", "quantity": 4}]))
    fast_confirmed = service.place_order(buyer, q_fast_b.quote_id)
    assert fast_confirmed.status == "confirmed"
    assert service.place_order(agent, q_pend_a.quote_id).status == "rejected"

    # And when a single pending order of 7/10 is approved, it excludes itself and confirms cleanly
    fourth_day = date(2026, 11, 19)
    q_ok = service.create_quote(agent, QuoteRequest(delivery_date=fourth_day, lines=[{"product_id": "milk", "quantity": 7}]))
    pending_ok = service.place_order(agent, q_ok.quote_id)
    assert pending_ok.status == "pending_approval"
    assert service.decide_approval(admin, pending_ok.approval_id, "approve").status == "confirmed"


def test_order_records_delivery_address_snapshot(gateway):
    import sqlite3

    client = principal_for_key("demo-hotel-client-key")
    place = lambda day, **options: service.place_order(client, service.create_quote(client, QuoteRequest(
        delivery_date=date(2026, 11, day), lines=[{"product_id": "milk", "quantity": 5}])).quote_id, **options)
    save_settings(Preferences(), client)
    with pytest.raises(service.GatewayError, match="street address"):
        place(16)
    assert service.list_orders(client) == []
    save_settings(Preferences(address="Saved kitchen, Testikatu 1,  00100 Helsinki"), client)
    saved = place(17)
    assert saved.delivery_address == "Saved kitchen, Testikatu 1, 00100 Helsinki"
    explicit = place(18, delivery_address="Event site, Testitie 2, 33100 Tampere")
    assert explicit.delivery_address == "Event site, Testitie 2, 33100 Tampere"
    # Changing the workspace setting afterwards does not move an order already placed.
    save_settings(Preferences(address="New kitchen, 00200 Helsinki"), client)
    assert service.get_order(client, saved.order_id).delivery_address == "Saved kitchen, Testikatu 1, 00100 Helsinki"
    received = next(e for e in store.events(order_id=explicit.order_id) if e["event_type"] == "ORDER_RECEIVED")
    assert received["data"]["delivery_address"] == explicit.delivery_address
    with pytest.raises(service.GatewayError):
        place(19, delivery_address="x" * 241)
    assert store.verify_chain()["ok"]

    # A database created before the column existed is upgraded in place and old orders read back empty.
    old = store.settings.db_path.with_name("old.db")
    with sqlite3.connect(old) as db:
        db.executescript(store.SCHEMA.replace(", delivery_address TEXT NOT NULL DEFAULT ''", ""))
        assert "delivery_address" not in {row[1] for row in db.execute("PRAGMA table_info(orders)")}
    with store.connect(old) as conn:
        assert "delivery_address" in {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
