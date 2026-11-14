"""Scripted end-to-end demo WITHOUT an LLM, against the live Valio mock API.

search -> offers -> plan -> quote -> order -> pending_approval -> approve -> confirmed -> audit timeline

    uv run python scripts/demo_flow.py                       # 1000 L lactose-free milk, next Monday, hotel
    uv run python scripts/demo_flow.py --quantity 300        # small order: auto-approved within the mandate
    uv run python scripts/demo_flow.py --date 2026-11-17 --buyer hotel
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import audit, service, store  # noqa: E402
from gateway.agent import next_weekday  # noqa: E402
from gateway.auth import Admin, Principal, admin_for_key, principal_for_key  # noqa: E402
from gateway.models import LineRequest, Need, OffersRequest, QuoteRequest, SearchRequest  # noqa: E402


def h(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))


def _run_demo(a: argparse.Namespace, agent: Principal, approver: Admin | None) -> None:
    today = store.now()
    delivery = a.date or next_weekday(0, today.date())
    need = Need(item="lactose-free milk", quantity=a.quantity, unit="L", delivery_date=delivery,
                search_text="maito", category="10400", free_from=["FREE_FROM_LACTOSE"],
                exclude_terms=["kahvi", "latte", "piimä", "kaakao", "jogurt"])

    h("1. Request")
    print(f"now {today:%a %Y-%m-%d %H:%M} | buyer {agent.buyer_id} ({agent.mandate.buyer_name})")
    print(f"need: {need.quantity:g} {need.unit} {need.item}, delivery {delivery:%a %Y-%m-%d}")
    m = agent.mandate
    print(f"mandate {m.mandate_id}: max €{m.max_order_total}/order, €{m.max_weekly_total}/week, "
          f"substitutions={m.substitution_policy}; spent this week €{service.weekly_spent(agent.buyer_id):,.2f}")

    h("2. Search (static catalog)")
    found = service.search_products(agent, SearchRequest(text=need.search_text, free_from=need.free_from,
                                                          category=need.category, exclude_terms=need.exclude_terms, limit=40))
    print(f"{found.total_matches} lactose-free milk products (claim FREE_FROM_LACTOSE, category 10400)")
    for r in found.results[:5]:
        print(f"  {r.id}  {r.name_fi}  [{r.sales_unit}, {r.volume_l or '?'} L/sales unit]")
    print("  ...")

    h("3. Live price + availability")
    ids = [r.id for r in found.results]
    res = service.check_offers(agent, OffersRequest(product_ids=ids, delivery_date=delivery))
    offers = sorted(res["offers"], key=lambda o: (not o["orderable"], o["price_per_content_unit"] or 99))
    print(f"checked at {res['checked_at']}")
    print(f"  {'id':<7} {'name':<46} {'unit':<4} {'€/unit':>7} {'€/L':>6} {'stock':>8}  {'cutoff':<16} status")
    for o in offers:
        stock = "unlim." if o["unlimited"] else ("-" if o["available_qty"] is None else f"{o['available_qty']:g}")
        cutoff = o["closing_time"][:16].replace("T", " ") if o["closing_time"] else "-"
        status = "OK" if o["orderable"] else f"EXCLUDED: {o['reason']}"
        print(f"  {o['product_id']:<7} {(o['name'] or '')[:46]:<46} {o['sales_unit']:<4} {o['unit_price'] or 0:>7.2f} "
              f"{o['price_per_content_unit'] or 0:>6.2f} {stock:>8}  {cutoff:<16} {status}")

    h("4. Plans (in sales units)")
    plans, _ = service.plan_need(agent, need, ids)
    for pl in plans.plans:
        print(f"[{pl.label}] {pl.strategy}\n   total €{pl.total_net:,.2f} net, coverage {pl.coverage:.0%} " + " ".join(pl.notes))
        for l in pl.lines:
            print(f"     {l.quantity:g} {l.sales_unit} x {l.product_id} {l.name} @ €{l.unit_price:.2f} = €{l.line_total:,.2f}"
                  + (f"  ({l.note})" if l.note else ""))
    if not plans.plans:
        print("no plan possible; stopping")
        return
    best = plans.plans[0]

    h("5. Signed quote")
    quote = service.create_quote(agent, QuoteRequest(delivery_date=delivery, need=need,
                                                     lines=[LineRequest(product_id=l.product_id, quantity=l.quantity) for l in best.lines]))
    print(f"{quote.quote_id}: €{quote.total_net:,.2f} net / €{quote.total_gross:,.2f} incl. VAT, expires {quote.expires_at}")
    print(f"signature (JWS, EdDSA): {quote.signature[:60]}...")
    print(f"policy preview: {quote.policy_preview.decision.value} - " + " ".join(quote.policy_preview.reasons))

    h("6. Agent places the order")
    order = service.place_order(agent, quote.quote_id,
                                f"Cheapest orderable lactose-free milk for {delivery}; Terminal items excluded (cutoff passed).")
    print(f"{order.order_id}: status = {order.status.value}")
    for r in order.policy.fired_rules:
        print(f"  rule {r.rule_id} -> {r.effect.value}: {r.message}")

    if order.status.value == "pending_approval":
        h("7. Human approval")
        if approver is None:
            print("Aimo review is pending. Sign in at /admin or configure AIMO_ADMIN_API_KEY for this script.")
            return
        try:
            service.decide_approval(agent, order.approval_id, "approve")
        except service.GatewayError as e:
            print(f"agent tries to approve its own order -> {e.status}: {e.message}")
        order = service.decide_approval(approver, order.approval_id, "approve", "OK, breakfast buffet for the conference week.")
        print(f"approved by {approver.actor} -> order status = {order.status.value}")

    h("8. Audit timeline")
    print(audit.render_text(order.order_id))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buyer", default="hotel")
    ap.add_argument("--quantity", type=float, default=1000)
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="delivery date (default: next Monday)")
    ap.add_argument("--reset", action="store_true", help="reset the gateway SQLite DB before running")
    a = ap.parse_args()

    agent = principal_for_key(f"demo-{a.buyer}-key")
    approver = admin_for_key(os.getenv("AIMO_ADMIN_API_KEY"))
    if agent is None:
        raise SystemExit(f"Unknown buyer {a.buyer!r}; check buyers.json for valid keys")
    if a.reset:
        store.reset_db()

    try:
        _run_demo(a, agent, approver)
    except (httpx.HTTPError, RuntimeError, service.GatewayError) as exc:
        raise SystemExit(f"Demo aborted (gateway/Valio error): {exc}") from exc


if __name__ == "__main__":
    main()
