import json
import asyncio
from datetime import date

import httpx
import pytest

from gateway import decisions, fulfillment, service, store
from gateway.auth import admin_for_key, principal_for_key
from gateway.models import QuoteRequest
from test_portals import gateway


DAY = date(2026, 11, 16)


def _evidence(**changes):
    return fulfillment.Evidence.model_validate({
        "unit": "ST",
        "observed_at": "2026-11-14T09:30:00+02:00", "valid_until": "2026-11-14T11:00:00+02:00",
        "dispatch_by": "2026-11-16T10:00:00+02:00", "deliver_by": "2026-11-16T11:00:00+02:00",
        "pick_setup_minutes": 10, "pick_units_per_minute": 50, "load_minutes": 15, "transit_minutes": 30,
        "route_capacity_available": True, "handling": "chilled", "handling_ready": True,
        "minimum_shelf_life_days": 2,
        "lots": [{"lot_id": "milk-lot", "quantity": 2000, "date_mark": "best_before", "marked_date": "2026-11-20"}],
        **changes,
    })


@pytest.mark.parametrize(("case", "status", "rule"), [
    ("clean", "confirmed", None),
    ("provider_down", "confirmed", None),
    ("model_flag", "pending_approval", "decision_not_duplicate"),
    ("missing", "pending_approval", "warehouse_evidence_missing"),
    ("capacity", "pending_approval", "warehouse_capacity"),
    ("spend", "pending_approval", "per_order_limit"),
    ("shelf_life", "rejected", "warehouse_shelf_life"),
    ("dispatch", "rejected", "warehouse_timing"),
    ("inbound_delay", "rejected", "warehouse_timing"),
])
def test_submission_applies_warehouse_and_model_review(gateway, monkeypatch, case, status, rule):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/v1beta/decisions" and request.headers["x-goog-api-key"] == "test"
        assert body["model"] == "gemini-decision-1" and set(body["questions"]) == {"quantity_typical", "not_duplicate"}
        assert "hotel" not in body["input"] and "warehouse" not in body["input"]  # no buyer identity or evidence
        if case == "provider_down":
            raise httpx.ReadTimeout("simulated")
        likely = 0.4 if case == "model_flag" else 0.97
        return httpx.Response(200, json={"answers": {
            "not_duplicate": {"type": "noul", "noul": likely, "confidence": max(likely, 1 - likely)},
            "quantity_typical": {"type": "score", "score": 0.1, "confidence": 0.9,
                                 "probabilities": {"0": 0.9, "1": 0.1, "2": 0.0}}}})

    client_class = httpx.Client
    monkeypatch.setattr(decisions.httpx, "Client",
                        lambda **options: client_class(transport=httpx.MockTransport(respond), **options))
    if case != "missing":
        changes = {}
        if case == "capacity":
            changes["route_capacity_available"] = False
        elif case == "shelf_life":
            changes["lots"] = [{"lot_id": "old", "quantity": 2000, "date_mark": "use_by", "marked_date": "2026-11-15"}]
        elif case == "dispatch":
            changes["dispatch_by"] = "2026-11-14T10:05:00+02:00"
        elif case == "inbound_delay":
            changes["ready_to_pick_at"] = "2026-11-16T09:45:00+02:00"
        fulfillment.save("milk", DAY, _evidence(**changes))

    buyer = principal_for_key("demo-hotel-client-key")
    # An order with no need, substitute or history has nothing to ask, so the first one makes no model call.
    earlier = service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 4}]))
    service.place_order(buyer, earlier.quote_id)
    assert not calls
    quote = service.create_quote(buyer, QuoteRequest(
        delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 1000 if case == "spend" else 5}]))
    order = service.place_order(buyer, quote.quote_id, replay=True)
    assert order.status == status
    assert service.place_order(buyer, quote.quote_id, replay=True).order_id == order.order_id
    if rule:
        assert rule in {entry.rule_id for entry in order.policy.fired_rules}
    assert len(calls) == int(case in {"clean", "provider_down", "model_flag"})
    audit = service.get_audit_log(buyer, order.order_id)
    events = [event for event in audit["events"] if event["event_type"] == "AIMO_APPROVAL_EVALUATED"]
    assert len(events) == 1 and audit["chain"]["ok"]
    if case == "provider_down":
        assert events[0]["data"]["method"] == "rules_fallback"
    if case in {"clean", "model_flag"}:
        admin_event = next(event for event in service.get_audit_log(
            admin_for_key("test-admin-credential"), order.order_id)["events"]
            if event["event_type"] == "AIMO_APPROVAL_EVALUATED")
        assert admin_event["data"]["method"] == "gemini_decision" and admin_event["data"]["model"] == "gemini-decision-1"
        assert admin_event["data"]["answers"]["not_duplicate"]["flagged"] == (case == "model_flag")
        assert "Gemini Decision 1 (2 questions" in admin_event["summary"]
        assert "answers" not in events[0]["data"]  # the buyer view omits model probabilities
    if case in {"missing", "capacity"}:
        admin = admin_for_key("test-admin-credential")
        with pytest.raises(service.GatewayError, match="Record current warehouse evidence"):
            service.decide_approval(admin, order.approval_id, "approve")
        fulfillment.save("milk", DAY, _evidence())
        assert service.decide_approval(admin, order.approval_id, "approve").status == "confirmed"


def test_hard_warehouse_failure_blocks_human_review_without_rejecting(gateway, monkeypatch):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    buyer = principal_for_key("demo-hotel-client-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 5}]))
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "pending_approval"
    fulfillment.save("milk", DAY, _evidence(route_capacity_available=False,
                                             ready_to_pick_at="2026-11-16T09:45:00+02:00"))
    admin = admin_for_key("test-admin-credential")
    with pytest.raises(service.GatewayError, match="warehouse_capacity, warehouse_timing") as blocked:
        service.decide_approval(admin, order.approval_id, "approve")
    assert blocked.value.status == 409
    assert service.get_order(admin, order.order_id).status == "pending_approval"
    fulfillment.save("milk", DAY, _evidence(observed_at="2026-11-14T09:45:00+02:00"))
    assert service.decide_approval(admin, order.approval_id, "approve").status == "confirmed"


def test_hard_mandate_failure_still_rejects_at_human_review(gateway, monkeypatch):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    buyer = principal_for_key("demo-hotel-client-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 5}]))
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "pending_approval"
    monkeypatch.setattr(service, "get_offers", lambda *_, **_options: ([], store.now()))
    admin = admin_for_key("test-admin-credential")
    assert service.decide_approval(admin, order.approval_id, "approve").status == "rejected"


def test_fulfillment_checks_default_follows_offline_demo(monkeypatch):
    monkeypatch.delenv("AIMO_FULFILLMENT_CHECKS", raising=False)
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    assert not fulfillment.enabled()
    monkeypatch.setenv("OFFLINE_DEMO", "1")
    assert fulfillment.enabled()
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "0")
    assert not fulfillment.enabled()
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    assert fulfillment.enabled()


def test_evidence_observed_after_gateway_clock_is_refused(gateway):
    with pytest.raises(ValueError, match=r"gateway clock \(2026-11-14T10:00:00\+02:00\)"):
        fulfillment.save("milk", DAY, _evidence(observed_at="2026-11-14T10:30:00+02:00"))
    assert not store.fetchone("SELECT 1 FROM fulfillment_evidence")


def test_lot_quantity_is_net_of_other_orders(gateway, monkeypatch):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    lots = [{"lot_id": "milk-lot", "quantity": 8, "date_mark": "best_before", "marked_date": "2026-11-20"}]
    fulfillment.save("milk", DAY, _evidence(lots=lots))
    buyer = principal_for_key("demo-hotel-client-key")

    def order(quantity):
        quote = service.create_quote(buyer, QuoteRequest(
            delivery_date=DAY, lines=[{"product_id": "milk", "quantity": quantity}]))
        return service.place_order(buyer, quote.quote_id)

    assert order(5).status == "confirmed"
    second = order(5)
    assert second.status == "rejected"
    assert "only 3 ST" in " ".join(second.policy.reasons)
    assert order(3).status == "confirmed"

    # A pending order does not count against itself when it is approved.
    fulfillment.save("milk", date(2026, 11, 17), _evidence(
        route_capacity_available=False, dispatch_by="2026-11-17T10:00:00+02:00", deliver_by="2026-11-17T11:00:00+02:00",
        lots=[{**lots[0], "quantity": 5}]))
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=date(2026, 11, 17),
                                                    lines=[{"product_id": "milk", "quantity": 5}]))
    pending = service.place_order(buyer, quote.quote_id)
    assert pending.status == "pending_approval"
    fulfillment.save("milk", date(2026, 11, 17), _evidence(
        observed_at="2026-11-14T09:45:00+02:00", dispatch_by="2026-11-17T10:00:00+02:00",
        deliver_by="2026-11-17T11:00:00+02:00", lots=[{**lots[0], "quantity": 5}]))
    admin = admin_for_key("test-admin-credential")
    assert service.decide_approval(admin, pending.approval_id, "approve").status == "confirmed"


def test_buyer_audit_omits_warehouse_evidence_and_admin_identity(gateway, monkeypatch):
    from gateway.api import app
    from gateway.auth import Admin

    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    fulfillment.save("milk", DAY, _evidence(route_capacity_available=False))
    buyer = principal_for_key("demo-hotel-client-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 5}]))
    order = service.place_order(buyer, quote.quote_id)
    fulfillment.save("milk", DAY, _evidence(observed_at="2026-11-14T09:45:00+02:00"))
    service.decide_approval(Admin(actor="admin:warehouse-reviewer"), order.approval_id, "approve")

    async def fetch(order_id, key):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://client") as client:
            return await client.get(f"/client/requests/{order_id}/audit", headers={"X-API-Key": key})

    response = asyncio.run(fetch(order.order_id, "demo-hotel-client-key"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"order_id", "events"}
    assert all(set(event) == {"event_type", "ts", "actor", "data"} for event in body["events"])
    assert all(set(event["data"]) <= {"decision", "status", "rules"} for event in body["events"])
    events = {event["event_type"]: event for event in body["events"]}
    assert events["AIMO_APPROVAL_EVALUATED"]["data"] == {"decision": "needs_approval", "rules": ["warehouse_capacity"]}
    assert events["AIMO_APPROVAL_RECHECKED"]["actor"] == "admin"
    assert events["ORDER_CONFIRMED"]["data"] == {"status": "confirmed"}
    for leaked in ("warehouse-reviewer", "evidence", "preparation_minutes", "pick", "eligible_quantity",
                   "capacity_available", "dispatch_by", "milk-lot"):
        assert leaked not in response.text
    assert "preparation_minutes" in str(service.get_audit_log(admin_for_key("test-admin-credential"), order.order_id))
    assert asyncio.run(fetch(order.order_id, "demo-hospital-client-key")).status_code == 404

    # The agent-key routes (REST /audit, MCP and the reference agent) share service.get_audit_log.
    shared = service.get_audit_log(buyer, order.order_id)
    kinds = {event["event_type"]: event for event in shared["events"]}
    assert kinds["AIMO_APPROVAL_EVALUATED"]["data"]["decision"] == "needs_approval"
    assert kinds["AIMO_APPROVAL_RECHECKED"]["actor"] == "admin" and shared["chain"]["ok"]
    assert "approved by admin" in shared["text"]
    for leaked in ("warehouse-reviewer", "evidence", "preparation_minutes", "min picking", "eligible_quantity",
                   "capacity_available", "dispatch_by", "milk-lot"):
        assert leaked not in json.dumps(shared)


def test_warehouse_evidence_endpoint_requires_admin(gateway):
    from gateway.admin_app import app

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin") as client:
            path = f"/operations/fulfillment-evidence/{DAY}/milk"
            evidence = _evidence().model_dump(mode="json")
            assert (await client.put(path, json=evidence)).status_code == 401
            auth = {"X-API-Key": "test-admin-credential"}
            response = await client.put(path, json=evidence, headers=auth)
            assert response.status_code == 204, response.text
            evidence["observed_at"] = "2026-11-14T09:00:00+02:00"
            assert (await client.put(path, json=evidence, headers=auth)).status_code == 422
            evidence["observed_at"] = "2026-11-14T10:30:00+02:00"
            future = await client.put(path, json=evidence, headers=auth)
            assert future.status_code == 422 and "2026-11-14T10:00:00+02:00" in future.text
            assert store.fetchone("SELECT 1 FROM fulfillment_evidence WHERE product_id='milk'")

    asyncio.run(check())


def test_decision_questions_follow_the_order_and_route_by_threshold():
    order = {
        "delivery_date": "2026-11-16",
        "order_lines": [
            {"product_id": "milk", "name": "Milk 1 L", "quantity": 40, "sales_unit": "ST", "usual_quantity": 5,
             "ratio_to_usual": 8.0},
            {"product_id": "oat", "name": "Oat drink 1 L", "quantity": 5, "sales_unit": "ST", "is_substitute": True,
             "substitute_for": "soy"}],
        "buyer_request": {"item": "milk", "quantity": 45, "unit": "L", "covered_quantity": 45},
        "agent_rationale": "Weekly breakfast order.",
    }
    questions = decisions._applicable(order)
    assert set(questions) == {"matches_request", "substitution_fit", "quantity_typical",
                              "rationale_consistent", "free_of_instructions"}
    assert set(decisions._applicable({"order_lines": order["order_lines"][:1]})) == {"quantity_typical"}
    assert decisions.review({"order_lines": [{"product_id": "milk", "quantity": 5}]}) is None

    def read(key, **answer):
        return decisions._read(questions[key], {"type": questions[key]["type"], **answer})["flagged"]

    assert not read("matches_request", noul=0.85, confidence=0.85)
    assert read("matches_request", noul=0.84, confidence=0.84)
    assert not read("substitution_fit", choice="equivalent", confidence=0.9)
    assert read("substitution_fit", choice="equivalent", confidence=0.6)
    assert read("substitution_fit", choice="acceptable_with_consent", confidence=0.95)
    assert not read("quantity_typical", score=0.3, confidence=0.7)
    assert read("quantity_typical", score=1.6, confidence=0.6)
    for bad in ({"type": "choice", "choice": "equivalent", "confidence": 0.9}, {"type": "noul", "noul": 1.4, "confidence": 0.9},
                {"type": "noul", "confidence": 0.9}):
        with pytest.raises((ValueError, KeyError)):
            decisions._read(questions["matches_request"], bad)
    review = decisions.Review({"matches_request": {"flagged": True}, "not_duplicate": {"flagged": False}})
    assert [rule.rule_id for rule in review.rules()] == ["decision_matches_request"]


def test_decision_context_adds_history_without_buyer_identity(gateway, monkeypatch):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    fulfillment.save("milk", DAY, _evidence())
    buyer = principal_for_key("demo-hotel-client-key")

    def quote(quantity):
        return service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": quantity}]))

    assert service.place_order(buyer, quote(5).quote_id).status == "confirmed"
    lines = [service.QuoteLine(**line) for line in json.loads(store.fetchone(
        "SELECT payload_json FROM quotes WHERE quote_id=?", (quote(20).quote_id,))["payload_json"])["lines"]]
    order = decisions.context(buyer.buyer_id, lines, None, {"required_claims": [], "exclude_allergens": []}, "",
                              DAY, store.now())
    assert order["order_lines"][0]["usual_quantity"] == 5 and order["order_lines"][0]["ratio_to_usual"] == 4
    assert order["recent_orders"][0]["same_delivery_date"] and not order["recent_orders"][0]["identical_lines"]
    assert "dietary_requirements" not in order and "agent_rationale" not in order
    assert buyer.buyer_id not in json.dumps(order)
    assert set(decisions._applicable(order)) == {"quantity_typical", "not_duplicate"}


@pytest.mark.parametrize(("quantity", "flagged"), [(100, False), (300, False), (301, True), (1, False)])
def test_order_far_above_the_stated_need_goes_to_review(gateway, quantity, flagged):
    from gateway.models import Need, Offer, OrderableReason, QuoteLine

    buyer = principal_for_key("demo-hotel-key")
    offer = Offer(product_id="milk", sales_unit="ST", unit_price=.1, available_qty=2000, category="10400",
                  orderable=True, reason=OrderableReason.ok)
    # A single sales unit may exceed a small need, because the buyer cannot order less.
    need = Need(item="milk", quantity=.2 if quantity == 1 else 100, unit="L", delivery_date=DAY)
    line = QuoteLine(product_id="milk", quantity=quantity, sales_unit="ST", unit_price=.1, line_total=quantity * .1,
                     covers=quantity)
    result = service._evaluate(buyer, [line], {"milk": offer}, line.line_total, need, delivery=DAY)
    assert ("over_coverage" in {rule.rule_id for rule in result.fired_rules}) == flagged, result.reasons
    assert result.decision.value == ("needs_approval" if flagged else "auto"), result.reasons
