import asyncio
from datetime import date

import httpx
import pytest

from gateway import fulfillment, gemini, service, store
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
    ("model_flag", "pending_approval", "gemini_combined_handling"),
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

    def review(snapshot):
        calls.append(snapshot)
        if case == "provider_down":
            raise httpx.ReadTimeout("simulated")
        if case == "model_flag":
            return gemini.ApprovalAdvice(recommendation="needs_review", concern="combined_handling")
        return gemini.ApprovalAdvice(recommendation="approve", concern="none")

    monkeypatch.setattr(gemini, "review_approval", review)
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
    if case in {"missing", "capacity"}:
        admin = admin_for_key("test-admin-credential")
        with pytest.raises(service.GatewayError, match="Record current warehouse evidence"):
            service.decide_approval(admin, order.approval_id, "approve")
        fulfillment.save("milk", DAY, _evidence())
        assert service.decide_approval(admin, order.approval_id, "approve").status == "confirmed"


def test_hard_warehouse_failure_takes_precedence_at_human_review(gateway, monkeypatch):
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "0")
    buyer = principal_for_key("demo-hotel-client-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=DAY, lines=[{"product_id": "milk", "quantity": 5}]))
    order = service.place_order(buyer, quote.quote_id)
    assert order.status == "pending_approval"
    fulfillment.save("milk", DAY, _evidence(route_capacity_available=False,
                                             ready_to_pick_at="2026-11-16T09:45:00+02:00"))
    admin = admin_for_key("test-admin-credential")
    result = service.decide_approval(admin, order.approval_id, "approve")
    assert result.status == "rejected"
    assert "Stock readiness" in service.get_audit_log(admin, order.order_id)["text"]


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
            assert store.fetchone("SELECT 1 FROM fulfillment_evidence WHERE product_id='milk'")

    asyncio.run(check())
