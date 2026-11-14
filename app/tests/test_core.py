"""Unit tests that need no network and no catalog DB."""
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from gateway import policy, quotes, service, store
from gateway.auth import Admin, principal_for_key
from gateway.load_catalog import parse_size_from_name
from gateway.models import (LineRequest, Need, Offer, OrderableReason, OrderStatus, ProductSummary, QuoteLine,
                            QuoteRequest, expand_allergens)
from gateway.offers import build_offer
from gateway.planner import amount_per_sales_unit, make_plans, round_qty


NOW = datetime.fromisoformat("2026-11-14T10:00:00+02:00")
MONDAY = date(2026, 11, 16)


def product(**kw) -> ProductSummary:
    base = dict(id="464073", name_fi="Valio täysmaito 1 l laktoositon UHT", category="10400", sales_unit="ST",
                base_unit="ST", volume_l=1.0, allergens_contains=["AM"], claims=["FREE_FROM_LACTOSE"])
    return ProductSummary(**{**base, **kw})


def raw(closing="2026-11-15T17:00:00+0200", amount=999999.0, model="Stock", price=1.64, cmp_=1.64, lines=True):
    return {
        "price": {"catalogPrice": {"value": price, "valueWithTax": round(price * 1.135, 2), "validFrom": "2026-09-01T00:00:00+0300",
                                   "validTo": "2026-12-31T00:00:00+0200", "currency": "EUR"},
                  "comparisonPrice": {"value": cmp_}, "comparisonUnit": "L", "tax": {"taxRate": 13.5}, "error": False},
        "availability": {"productId": "464073", "closingTime": closing, "salesBlock": False, "logisticModel": model,
                         "scheduleLines": [{"salesBlock": False, "availableAmount": amount, "availableDate": "2026-11-16",
                                            "salesUnit": "ST"}] if lines else []},
    }


# --- unit conversion -------------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("Valio täysmaito 1 l laktoositon UHT", (1.0, "L", None)),
    ("Valio kevytmaito 2,5 dl laktoositon UHT", (0.25, "L", None)),
    ("Arla Annosmaito 100x2 cl laktoositon", (0.02, "L", 100)),
    ("12 x Arla Täysmaitojuoma 1 L UHT", (1.0, "L", None)),  # x 12 comes from units[KI]
    ("Valio rasvaton piimä 5 kg laktoositon", (5.0, "KG", None)),
])
def test_parse_size(name, expected):
    size, unit, count = parse_size_from_name(name)
    assert (round(size, 4), unit, count) == expected


def test_box_price_api_content_and_plan_in_sales_units():
    # 12 x 1 L box: catalogPrice 30.42 / comparisonPrice 2.54 per L -> ~12 L per KI; catalog says 12
    p = product(id="464768", sales_unit="KI", volume_l=12.0, base_units_per_sales_unit=12)
    o = build_offer(p, raw(price=30.42, cmp_=2.54), MONDAY, NOW)
    assert o.content_per_sales_unit == 12.0 and o.content_source == "catalog+price_api"
    need = Need(item="milk", quantity=1000, unit="L", delivery_date=MONDAY)
    plan = make_plans(need, [o]).plans[0]
    assert plan.lines[0].quantity == 84 and plan.lines[0].sales_unit == "KI"   # ceil(1000/12)
    assert plan.covered == 1008


# --- cutoff handling ---------------------------------------------------------------------------
def test_cutoff_passed_not_orderable_even_with_stock():
    o = build_offer(product(), raw(closing="2026-11-12T15:00:00+0200", model="Terminal"), MONDAY, NOW)
    assert not o.orderable and o.reason == OrderableReason.cutoff_passed and o.unlimited


def test_missing_availability_is_unknown():
    r = raw(lines=False)
    r["availability"].update(closingTime=None, logisticModel=None)
    o = build_offer(product(), r, MONDAY, NOW)
    assert o.reason == OrderableReason.no_availability_data and not o.orderable


def test_limited_stock_splits():
    a = build_offer(product(id="A"), raw(amount=384, price=2.48, cmp_=2.48), MONDAY, NOW)
    b = build_offer(product(id="B"), raw(amount=999999, price=2.65, cmp_=2.65), MONDAY, NOW)
    assert a.available_qty == 384 and b.unlimited
    plan = make_plans(Need(item="milk", quantity=500, unit="L", delivery_date=MONDAY), [a, b]).plans[0]
    assert [(l.product_id, l.quantity) for l in plan.lines] == [("A", 384), ("B", 116)]


# --- policy ----------------------------------------------------------------------------------
def _line(pid="464073", qty=100, price=1.64, **kw):
    return QuoteLine(product_id=pid, name="x", category="10400", quantity=qty, sales_unit="ST", unit_price=price,
                     line_total=round(qty * price, 2), covers=qty, **kw)


def _offer(pid="464073", allergens=("AM",), may=(), category="10400"):
    return Offer(product_id=pid, sales_unit="ST", category=category, orderable=True, reason="ok",
                 allergens_contains=list(allergens), allergens_may_contain=list(may), claims=["FREE_FROM_LACTOSE"])


def test_policy_hotel_auto_and_limits():
    m = policy.load_mandate("hotel")
    ok = policy.evaluate(m, [_line(qty=100)], {"464073": _offer()}, total_net=164, today=date(2026, 11, 14))
    assert ok.decision.value == "auto"
    big = policy.evaluate(m, [_line(qty=1000)], {"464073": _offer()}, total_net=1640, today=date(2026, 11, 14))
    assert big.decision.value == "needs_approval" and big.fired_rules[0].rule_id == "per_order_limit"
    week = policy.evaluate(m, [_line(qty=100)], {"464073": _offer()}, total_net=164, weekly_spent=4900, today=date(2026, 11, 14))
    assert [r.rule_id for r in week.fired_rules] == ["weekly_limit"]
    cap = policy.evaluate(m, [_line(qty=5000)], {"464073": _offer()}, total_net=8200, today=date(2026, 11, 14))
    assert cap.decision.value == "reject" and "hard_cap" in {r.rule_id for r in cap.fired_rules}


def test_policy_hospital_forbidden_allergen_rejects():
    m = policy.load_mandate("hospital")
    r = policy.evaluate(m, [_line()], {"464073": _offer(allergens=("AM",))}, total_net=164, today=date(2026, 11, 14))
    assert r.decision.value == "reject" and r.fired_rules[0].rule_id == "forbidden_allergen"
    trace = policy.evaluate(m, [_line()], {"464073": _offer(allergens=("GO",), may=("AW",))}, total_net=164, today=date(2026, 11, 14))
    assert trace.decision.value == "needs_approval"


def test_policy_hospital_any_substitution_needs_approval():
    m = policy.load_mandate("hospital")
    r = policy.evaluate(m, [_line(pid="X", is_substitute=True, substitute_for="Y", substitute_for_category="10402")],
                        {"X": _offer(pid="X", allergens=("GO",))}, total_net=164, today=date(2026, 11, 14))
    assert r.decision.value == "needs_approval" and r.fired_rules[0].rule_id == "substitution_preference"


# --- audit hash chain ----------------------------------------------------------------------------
def test_hash_chain_detects_tampering(tmp_path):
    db = tmp_path / "t.db"
    for i in range(3):
        store.append_event("TEST", "tester", {"i": i}, order_id="o1", db_path=db)
    assert store.verify_chain(db)["ok"]
    import sqlite3
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_events SET data_json='{\"i\":99}' WHERE seq=2")
    # an attacker who drops the trigger can edit, but the chain no longer verifies
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit_events SET data_json='{\"i\":99}' WHERE seq=2")
    conn.commit()
    res = store.verify_chain(db)
    assert not res["ok"] and res["first_bad_seq"] == 2


# --- quote signatures -----------------------------------------------------------------------------
def test_quote_signature_roundtrip_and_tamper():
    payload = {"quote_id": "q1", "total_net": 10.0}
    jws = quotes.sign(payload)
    assert quotes.verify(jws) == payload
    h, p, s = jws.split(".")
    forged = quotes._b64(b'{"quote_id":"q1","total_net":1.0}')
    with pytest.raises(ValueError):
        quotes.verify(f"{h}.{forged}.{s}")


# --- planner: units, lot sizes, mandate safety, CO2 ----------------------------------------------
def test_planner_units_and_lot_sizes():
    kg_offer = Offer(product_id="K1", name="Juusto", sales_unit="KG", base_unit="KG",
                     content_per_sales_unit=1.0, content_unit="KG", allowed_lot_size=3.0,
                     unit_price=10.0, unlimited=True, orderable=True, reason="ok")
    assert amount_per_sales_unit(kg_offer, "L") is None
    assert amount_per_sales_unit(kg_offer, "PCS") is None
    assert amount_per_sales_unit(kg_offer, "KG") == 1.0
    assert round_qty(10.0, kg_offer) == 12.0

    pcs_box = Offer(product_id="P1", name="12x bottles", sales_unit="KI", base_unit="ST",
                    base_units_per_sales_unit=12.0, unit_price=12.0, unlimited=True, orderable=True, reason="ok")
    assert amount_per_sales_unit(pcs_box, "PCS") == 12.0
    plan = make_plans(Need(item="bottles", quantity=25, unit="PCS", delivery_date=MONDAY), [pcs_box]).plans[0]
    assert plan.lines[0].quantity == 3 and plan.covered == 36


def test_planner_mandate_safe_substitute_and_allow_partial():
    hospital = policy.load_mandate("hospital")
    pref_oos = Offer(product_id="468465", name="Oddlygood GF", category="10402", sales_unit="ST",
                     content_per_sales_unit=1.0, content_unit="L", unit_price=1.2, available_qty=0,
                     orderable=False, reason=OrderableReason.insufficient_stock,
                     allergens_contains=["GO"], claims=["FREE_FROM_GLUTEN"], substitutes=["470863", "SAFE1"])
    unsafe = Offer(product_id="470863", name="Oatly", category="10402", sales_unit="ST",
                   content_per_sales_unit=1.0, content_unit="L", unit_price=1.4, unlimited=True,
                   orderable=True, reason="ok", allergens_contains=["AW", "GO"])
    safe = Offer(product_id="SAFE1", name="Safe Oat", category="10402", sales_unit="ST",
                 content_per_sales_unit=1.0, content_unit="L", unit_price=1.8, unlimited=True,
                 orderable=True, reason="ok", allergens_contains=["GO"], claims=["FREE_FROM_GLUTEN"])
    need = Need(item="oat drink", quantity=60, unit="L", delivery_date=MONDAY, preferred_product_ids=["468465"])

    # When a safe offer exists, planner filters out the mandate-forbidden one and picks SAFE1
    res_with_safe = make_plans(need, [pref_oos, unsafe, safe], mandate=hospital)
    assert res_with_safe.plans[0].lines[0].product_id == "SAFE1"
    assert any(e["product_id"] == "470863" and "mandate_forbidden" in e["reason"] for e in res_with_safe.excluded)

    # When ONLY unsafe is orderable, planner retains it so policy.evaluate rejects explicitly
    res_only_unsafe = make_plans(need, [pref_oos, unsafe], mandate=hospital)
    assert res_only_unsafe.plans[0].lines[0].product_id == "470863"

    # allow_partial=False suppresses incomplete plans
    short = Offer(product_id="S1", name="Milk", category="10400", sales_unit="ST", content_per_sales_unit=1.0,
                  content_unit="L", unit_price=1.0, available_qty=10, orderable=True, reason="ok")
    assert make_plans(Need(item="milk", quantity=50, unit="L", delivery_date=MONDAY, allow_partial=False), [short]).plans == []


def test_planner_co2_tiebreak_and_metrics():
    high_co2 = Offer(product_id="C1", name="Milk A", category="10400", sales_unit="ST",
                     content_per_sales_unit=1.0, content_unit="L", net_weight_kg=1.0, unit_price=1.50,
                     unlimited=True, logistic_model="Stock", orderable=True, reason="ok",
                     reliability=1.0, co2_per_kg=3.0)
    low_co2 = Offer(product_id="C2", name="Milk B", category="10400", sales_unit="ST",
                    content_per_sales_unit=1.0, content_unit="L", net_weight_kg=1.0, unit_price=1.50,
                    unlimited=True, logistic_model="Stock", orderable=True, reason="ok",
                    reliability=1.0, co2_per_kg=0.9)
    plan = make_plans(Need(item="milk", quantity=10, unit="L", delivery_date=MONDAY), [high_co2, low_co2]).plans[0]
    assert plan.lines[0].product_id == "C2"
    assert plan.avg_reliability == 1.0
    assert plan.estimated_co2_kg == 9.0


# --- policy: extended rules and allergen expansion -------------------------------------------------
def test_policy_extended_rules_and_allergen_groups():
    assert expand_allergens(["dairy", "eggs", "peanuts", "oats"]) == ["AE", "AM", "AP", "GO", "ML"]
    hotel = policy.load_mandate("hotel")

    expired_mandate = hotel.model_copy(update={"valid_until": date(2026, 11, 1)})
    r_exp = policy.evaluate(expired_mandate, [_line()], {"464073": _offer()}, total_net=164, today=date(2026, 11, 14))
    assert r_exp.decision.value == "reject" and "mandate_not_valid" in {x.rule_id for x in r_exp.fired_rules}

    need_qty = Need(item="milk", quantity=10, unit="L", delivery_date=MONDAY, free_from=["FREE_FROM_LACTOSE"],
                    exclude_allergens=["nuts"], exclude_terms=["kaakao"])
    r_qcap = policy.evaluate(hotel, [_line(qty=60, price=1.0)], {"464073": _offer()},
                             total_net=60, need=need_qty, today=date(2026, 11, 14))
    assert r_qcap.decision.value == "reject" and "hard_cap" in {x.rule_id for x in r_qcap.fired_rules}

    cat_mandate = hotel.model_copy(update={"allowed_categories": ["10400"]})
    r_cat = policy.evaluate(cat_mandate, [_line()], {"464073": _offer(category="41760")}, total_net=164, today=date(2026, 11, 14))
    assert r_cat.decision.value == "reject" and "hard_cap" in {x.rule_id for x in r_cat.fired_rules}

    unk_offer = _offer().model_copy(update={"orderable": False, "reason": OrderableReason.no_availability_data})
    r_unk = policy.evaluate(hotel, [_line()], {"464073": unk_offer}, total_net=164, today=date(2026, 11, 14))
    assert r_unk.decision.value == "needs_approval" and {x.rule_id for x in r_unk.fired_rules} == {"unknown_availability"}

    # Hotel allows same-category substitution automatically, but cross-category needs approval
    r_same = policy.evaluate(hotel, [_line(is_substitute=True, substitute_for="Y", substitute_for_category="10400")],
                             {"464073": _offer(category="10400")}, total_net=164, today=date(2026, 11, 14))
    assert r_same.decision.value == "auto"
    r_diff = policy.evaluate(hotel, [_line(is_substitute=True, substitute_for="Y", substitute_for_category="10402")],
                             {"464073": _offer(category="10400")}, total_net=164, today=date(2026, 11, 14))
    assert r_diff.decision.value == "needs_approval" and {x.rule_id for x in r_diff.fired_rules} == {"substitution_preference"}

    # Need mismatch: missing claim, need-excluded allergen, excluded term, unit mismatch (covers=None), partial coverage
    nut_offer = _offer(allergens=("AN",)).model_copy(update={"name": "Pähkinä kaakao", "claims": []})
    bad_line = QuoteLine(product_id="464073", name="Pähkinä kaakao", category="10400", quantity=10, sales_unit="ST",
                         unit_price=1.0, line_total=10.0, covers=None)
    r_need = policy.evaluate(hotel, [bad_line], {"464073": nut_offer}, total_net=10, need=need_qty,
                             coverage=0.5, today=date(2026, 11, 14))
    assert r_need.decision.value == "needs_approval"
    assert {"need_mismatch", "partial_coverage"} <= {x.rule_id for x in r_need.fired_rules}


# --- service: lifecycle, roles, concurrency/replay, expiry, stock re-check ------------------------
def test_service_lifecycle_guards_and_store_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "settings", replace(store.settings, db_path=tmp_path / "gw.db"))
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "0")
    store.set_demo_now(NOW)
    try:
        hotel_agent = principal_for_key("demo-hotel-key")
        hotel_approver = principal_for_key("demo-hotel-approver-key")
        hospital_agent = principal_for_key("demo-hospital-key")
        hospital_approver = principal_for_key("demo-hospital-approver-key")

        stock = {"464306": 2000.0}
        closing = datetime.fromisoformat("2026-11-15T17:00:00+02:00")
        valid_to = datetime.fromisoformat("2026-12-31T00:00:00+02:00")

        def fake_offers(ids, delivery_date, *, fresh=False):
            out = []
            for pid in dict.fromkeys(ids):
                if pid == "464306":
                    avail = stock["464306"]
                    out.append(Offer(
                        product_id="464306", name="Valio Arki 1L", category="10400", sales_unit="ST",
                        content_per_sales_unit=1.0, content_unit="L", unit_price=1.01, unit_price_with_tax=1.15,
                        price_valid_to=valid_to, available_qty=avail, closing_time=closing, logistic_model="Stock",
                        orderable=avail > 0, reason=OrderableReason.ok if avail > 0 else OrderableReason.insufficient_stock,
                        allergens_contains=["AM"], claims=["FREE_FROM_LACTOSE"], substitutes=["464073"],
                    ))
                elif pid == "464073":
                    out.append(Offer(
                        product_id="464073", name="Valio Täysmaito 1L", category="10400", sales_unit="ST",
                        content_per_sales_unit=1.0, content_unit="L", unit_price=1.64, price_valid_to=valid_to,
                        unlimited=True, closing_time=closing, logistic_model="Stock",
                        orderable=True, reason=OrderableReason.ok, allergens_contains=["AM"], claims=["FREE_FROM_LACTOSE"],
                    ))
            return out, store.now()

        monkeypatch.setattr(service, "get_offers", fake_offers)
        monkeypatch.setattr(service, "get_products", lambda ids: {
            "464306": ProductSummary(id="464306", name_fi="Valio Arki", category="10400", sales_unit="ST", base_unit="ST")
        })

        # Approver blocked from quoting/ordering
        qreq = QuoteRequest(delivery_date=MONDAY, lines=[LineRequest(product_id="464306", quantity=1000)])
        with pytest.raises(service.GatewayError) as exc_role:
            service.create_quote(hotel_approver, qreq)
        assert exc_role.value.status == 403

        # Duplicate line exceeding stock rejected in create_quote
        dup_req = QuoteRequest(delivery_date=MONDAY, lines=[
            LineRequest(product_id="464306", quantity=1200),
            LineRequest(product_id="464306", quantity=1000),
        ])
        with pytest.raises(service.GatewayError) as exc_dup:
            service.create_quote(hotel_agent, dup_req)
        assert exc_dup.value.status == 409

        # Valid quote -> pending_approval -> human approval -> confirmed + audit chain ok
        q = service.create_quote(hotel_agent, qreq)
        assert q.policy_preview.decision.value == "needs_approval"
        ord_pending = service.place_order(hotel_agent, q.quote_id, "over 1k limit")
        assert ord_pending.status == OrderStatus.pending_approval

        # Quote replay blocked
        with pytest.raises(service.GatewayError) as exc_replay:
            service.place_order(hotel_agent, q.quote_id, "replay")
        assert exc_replay.value.status == 409

        # Agent and cross-buyer approver blocked from deciding approval
        with pytest.raises(service.GatewayError) as exc_ag:
            service.decide_approval(hotel_agent, ord_pending.approval_id, "approve")
        assert exc_ag.value.status == 403
        with pytest.raises(service.GatewayError) as exc_xb:
            service.decide_approval(hospital_approver, ord_pending.approval_id, "approve")
        assert exc_xb.value.status == 404
        with pytest.raises(service.GatewayError) as exc_bad_dec:
            service.decide_approval(Admin(), ord_pending.approval_id, "maybe")
        assert exc_bad_dec.value.status == 400

        ord_done = service.decide_approval(Admin(), ord_pending.approval_id, "approve", "Approved by Aimo")
        assert ord_done.status == OrderStatus.confirmed
        assert service.get_audit_log(hotel_agent, ord_done.order_id)["chain"]["ok"]

        # Stock drop between quote and order triggers stale insufficient_stock rejection
        q_drop = service.create_quote(hotel_agent, QuoteRequest(
            delivery_date=MONDAY, lines=[LineRequest(product_id="464306", quantity=500)]))
        stock["464306"] = 10.0
        ord_drop = service.place_order(hotel_agent, q_drop.quote_id, "stock dropped")
        assert ord_drop.status == OrderStatus.rejected
        assert "quote_invalid" in {r.rule_id for r in ord_drop.policy.fired_rules}

        # plan_need auto-expands Valio substitutes when preferred offer is out of stock
        stock["464306"] = 0.0
        plan_res, _ = service.plan_need(hotel_agent, Need(
            item="milk", quantity=50, unit="L", delivery_date=MONDAY, preferred_product_ids=["464306"]), ["464306"])
        assert plan_res.plans[0].lines[0].product_id == "464073"

        # Quote tampered in DB is rejected by place_order
        q_tamper = service.create_quote(hotel_agent, QuoteRequest(
            delivery_date=MONDAY, lines=[LineRequest(product_id="464073", quantity=10)]))
        store.execute("UPDATE quotes SET payload_json='{\"tampered\":true}' WHERE quote_id=?", (q_tamper.quote_id,))
        with pytest.raises(service.GatewayError) as exc_tmp:
            service.place_order(hotel_agent, q_tamper.quote_id, "tampered")
        assert exc_tmp.value.status == 409

        # Approval granted after quote expiry marks order expired & approval rejected (not approved)
        q_exp = service.create_quote(hotel_agent, QuoteRequest(
            delivery_date=MONDAY, lines=[LineRequest(product_id="464073", quantity=800)]))
        ord_exp = service.place_order(hotel_agent, q_exp.quote_id, "awaiting approval")
        assert ord_exp.status == OrderStatus.pending_approval
        store.set_demo_now(closing + timedelta(minutes=5))
        ord_late = service.decide_approval(Admin(), ord_exp.approval_id, "approve", "too late")
        assert ord_late.status == OrderStatus.expired
        assert service.list_approvals(hotel_approver, status="rejected")[0]["approval"]["approval_id"] == ord_exp.approval_id

        # Expired quote cannot be placed
        q_old = service.create_quote(hospital_agent, QuoteRequest(
            delivery_date=MONDAY, lines=[LineRequest(product_id="464073", quantity=10)]))
        assert q_old.expires_at <= store.now()
        with pytest.raises(service.GatewayError) as exc_exp:
            service.place_order(hospital_agent, q_old.quote_id, "expired")
        assert exc_exp.value.status == 409

        # reset_db wipes quotes/orders/approvals/audit and keeps chain valid
        store.reset_db()
        assert store.fetchall("SELECT * FROM orders") == []
        assert store.verify_chain()["ok"]
    finally:
        store.set_demo_now(None)
