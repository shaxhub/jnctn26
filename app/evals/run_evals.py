"""Evaluate planner + policy on evals/cases.jsonl.

    uv run python evals/run_evals.py            # deterministic: fixture offers, no network, no LLM
    uv run python evals/run_evals.py --live     # same needs, but live catalog search + live Valio API
    uv run python evals/run_evals.py --agent    # full agent on each case's text (LLM if ANTHROPIC_API_KEY set)

Fixture offers in cases.jsonl are copied from real API responses (Nov 2026), so deterministic mode
stays stable when live cutoffs move. --live and --agent results depend on the clock and live data:
read them as a report, not a pass/fail gate.
TODO(B): add cases for partial coverage, may-contain traces, unit mismatch (KG vs L), lot sizes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import policy  # noqa: E402
from gateway.config import TZ  # noqa: E402
from gateway.models import Need, Offer, QuoteLine  # noqa: E402
from gateway.planner import make_plans  # noqa: E402

CASES = Path(__file__).with_name("cases.jsonl")


def plan_and_decide(case: dict, offers: list[Offer]) -> dict:
    need = Need(**case["need"])
    mandate = policy.load_mandate(case["buyer"])
    res = make_plans(need, offers, mandate=mandate)
    out = {"excluded": [e["product_id"] for e in res.excluded], "plans": len(res.plans)}
    if not res.plans:
        out.update(decision="reject", rules=["no_plan"], best_plan={}, coverage=0.0)
        return out
    best = res.plans[0]
    by_id = {o.product_id: o for o in offers}
    pref = need.preferred_product_ids
    lines = [QuoteLine(product_id=l.product_id, name=l.name, category=l.category, quantity=l.quantity,
                       sales_unit=l.sales_unit, unit_price=l.unit_price, line_total=l.line_total, covers=l.covers,
                       is_substitute=l.is_substitute, substitute_for=l.substitute_for,
                       substitute_for_category=by_id[pref[0]].category if l.is_substitute and pref[0] in by_id else None)
             for l in best.lines]
    result = policy.evaluate(mandate, lines, by_id, total_net=best.total_net, weekly_spent=case.get("weekly_spent", 0.0),
                             need=need, coverage=best.coverage, today=need.delivery_date - timedelta(days=2))
    out.update(decision=result.decision.value, rules=sorted({r.rule_id for r in result.fired_rules}),
               best_plan={l.product_id: l.quantity for l in best.lines}, coverage=best.coverage, total=best.total_net)
    return out


def check(expected: dict, got: dict) -> list[str]:
    fails = []
    if "decision" in expected and got["decision"] != expected["decision"]:
        fails.append(f"decision {got['decision']} != {expected['decision']}")
    missing = set(expected.get("rules", [])) - set(got.get("rules", []))
    if missing:
        fails.append(f"rules missing {sorted(missing)} (got {got.get('rules')})")
    if "rules" in expected and not expected["rules"] and got.get("rules"):
        fails.append(f"unexpected rules {got['rules']}")
    if "best_plan" in expected and got.get("best_plan") != {k: float(v) for k, v in expected["best_plan"].items()}:
        fails.append(f"best plan {got.get('best_plan')} != {expected['best_plan']}")
    missing_ex = set(expected.get("excluded", [])) - set(got.get("excluded", []))
    if missing_ex:
        fails.append(f"not excluded: {sorted(missing_ex)}")
    if "coverage" in expected and abs(got.get("coverage", 0) - expected["coverage"]) > 1e-6:
        fails.append(f"coverage {got.get('coverage')} != {expected['coverage']}")
    return fails


def run_live(case: dict) -> dict:
    from gateway.agent import next_weekday
    from gateway.models import SearchRequest
    from gateway.offers import get_offers
    from gateway.search import search

    need = Need(**case["need"])
    need.delivery_date = next_weekday(need.delivery_date.weekday(), date.today())
    found = search(SearchRequest(text=need.search_text, free_from=need.free_from,
                                 exclude_allergens=need.exclude_allergens, category=need.category,
                                 exclude_terms=need.exclude_terms, limit=40))
    ids = list(dict.fromkeys(need.preferred_product_ids + [r.id for r in found.results]))
    offers, _ = get_offers(ids, need.delivery_date)
    case = {**case, "need": need.model_dump(mode="json")}
    return plan_and_decide(case, offers)


def run_agent_case(case: dict) -> dict:
    from gateway import agent as agent_mod
    from gateway import service, store
    from gateway.auth import principal_for_key
    from gateway.models import ProductSummary, SearchResult, expand_allergens
    from gateway.search import normalize_claims

    case_need = Need(**case["need"])
    demo_dt = datetime.combine(case_need.delivery_date - timedelta(days=2), time(10, 0), tzinfo=TZ)
    if hasattr(store, "reset_db"):
        store.reset_db()
    if hasattr(store, "set_demo_now"):
        store.set_demo_now(demo_dt)

    ws = float(case.get("weekly_spent", 0.0))
    if ws > 0:
        qid, oid, ts = f"q_seed_{case['id']}", f"ord_seed_{case['id']}", demo_dt.isoformat()
        store.execute(
            "INSERT INTO quotes (quote_id,buyer_id,created_at,expires_at,status,total_net,payload_json,jws)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (qid, case["buyer"], ts, (demo_dt + timedelta(days=1)).isoformat(), "used", ws, "{}", "seed"),
        )
        store.execute(
            "INSERT INTO orders (order_id,quote_id,buyer_id,status,total_net,currency,delivery_date,lines_json,"
            "policy_json,approval_id,agent_rationale,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, qid, case["buyer"], "confirmed", ws, "EUR", case_need.delivery_date.isoformat(),
             "[]", "{}", None, "seed weekly_spent", ts, ts),
        )

    offers_by_id = {o["product_id"]: Offer(**o) for o in case.get("offers", [])}
    orig_get_offers = service.get_offers
    orig_search_products = service.search_products
    orig_get_products = service.get_products
    orig_parse_heuristic = agent_mod.parse_need_heuristic

    def fake_get_offers(product_ids: list[str], delivery_date: date):
        if not offers_by_id:
            return orig_get_offers(product_ids, delivery_date)
        return [offers_by_id[pid] for pid in dict.fromkeys(product_ids) if pid in offers_by_id], store.now()

    def fake_search_products(p, req):
        if not offers_by_id:
            return orig_search_products(p, req)
        req_claims = set(normalize_claims(req.free_from))
        excl_allergens = set(expand_allergens(req.exclude_allergens))
        results = []
        for o in offers_by_id.values():
            if req_claims and not req_claims.issubset(set(o.claims)):
                continue
            if excl_allergens & set(o.allergens_contains):
                continue
            if req.category and o.category and not o.category.startswith(req.category):
                continue
            name_lower = (o.name or "").lower()
            if any(t.lower() in name_lower for t in req.exclude_terms):
                continue
            results.append(ProductSummary(
                id=o.product_id, name_fi=o.name, brand=o.brand, category=o.category,
                sales_unit=o.sales_unit, base_unit=getattr(o, "base_unit", None) or o.sales_unit,
                base_units_per_sales_unit=o.base_units_per_sales_unit,
                volume_l=o.content_per_sales_unit if o.content_unit == "L" else getattr(o, "volume_l", None),
                net_weight_kg=o.content_per_sales_unit if o.content_unit == "KG" else getattr(o, "net_weight_kg", None),
                allowed_lot_size=o.allowed_lot_size,
                allergens_contains=o.allergens_contains, allergens_may_contain=o.allergens_may_contain,
                claims=o.claims, reliability=o.reliability, co2_per_kg=o.co2_per_kg, substitutes=o.substitutes,
            ))
        return SearchResult(results=results[:req.limit], total_matches=len(results))

    def fake_get_products(ids: list[str]):
        prods = orig_get_products(ids)
        for pid in ids:
            if pid not in prods and pid in offers_by_id:
                o = offers_by_id[pid]
                prods[pid] = ProductSummary(
                    id=o.product_id, name_fi=o.name, category=o.category,
                    sales_unit=o.sales_unit, base_unit=getattr(o, "base_unit", None) or o.sales_unit,
                    base_units_per_sales_unit=o.base_units_per_sales_unit,
                    allergens_contains=o.allergens_contains, allergens_may_contain=o.allergens_may_contain,
                    claims=o.claims, substitutes=o.substitutes,
                )
        return prods

    def wrapped_parse_heuristic(text: str, today: date | None = None) -> Need:
        parsed = orig_parse_heuristic(text, today)
        if case_need.preferred_product_ids and not parsed.preferred_product_ids:
            parsed.preferred_product_ids = list(case_need.preferred_product_ids)
        return parsed

    service.get_offers = fake_get_offers
    service.search_products = fake_search_products
    service.get_products = fake_get_products
    agent_mod.parse_need_heuristic = wrapped_parse_heuristic
    try:
        res = agent_mod.run_agent(principal_for_key(f"demo-{case['buyer']}-key"), case["text"])
    finally:
        service.get_offers = orig_get_offers
        service.search_products = orig_search_products
        service.get_products = orig_get_products
        agent_mod.parse_need_heuristic = orig_parse_heuristic
        if hasattr(store, "set_demo_now"):
            store.set_demo_now(None)

    order = res.get("order") or {}
    pol = order.get("policy") or {}
    plans_out = res.get("plans") or {}
    plan_list = plans_out.get("plans") or []
    return {
        "decision": pol.get("decision", "no_order"),
        "rules": sorted({r["rule_id"] for r in pol.get("fired_rules", [])}),
        "best_plan": {l["product_id"]: l["quantity"] for l in order.get("lines", [])},
        "excluded": [e["product_id"] for e in plans_out.get("excluded", [])],
        "coverage": plan_list[0]["coverage"] if plan_list else 0.0,
        "mode": res.get("mode"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--live", action="store_true")
    g.add_argument("--agent", action="store_true")
    a = ap.parse_args()
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    passed = 0
    for case in cases:
        if a.agent:
            got = run_agent_case(case)
        elif a.live:
            got = run_live(case)
        else:
            got = plan_and_decide(case, [Offer(**o) for o in case["offers"]])
        fails = check(case["expected"], got)
        passed += not fails
        print(f"{'PASS' if not fails else 'FAIL'}  {case['id']:<32} decision={got['decision']:<15} rules={got.get('rules')}"
              f" plan={got.get('best_plan')}")
        for f in fails:
            print(f"        - {f}")
    print(f"\n{passed}/{len(cases)} passed ({'agent' if a.agent else 'live' if a.live else 'deterministic'} mode)")
    from gateway.config import settings
    return 0 if (passed == len(cases) or a.live or (a.agent and bool(settings.anthropic_api_key))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
