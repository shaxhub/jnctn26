"""Core gateway operations. REST (api.py), MCP (mcp_server.py), the agent and the scripts all call
these functions, so behaviour and audit logging are identical on every channel.

Every function takes the authenticated Principal first; buyer id and mandate come from it, never
from the caller's arguments.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import audit, policy, quotes, recurring, store, substitutions
from .auth import Admin, Principal
from .config import TZ
from .delivery import estimate
from .models import (Approval, Decision, FiredRule, Need, Offer, OffersRequest, Order, OrderableReason, OrderStatus, PlanResult,
                     PolicyResult, Quote, QuoteLine, QuoteRequest, SearchRequest, SearchResult, expand_allergens)
from .offers import get_offers
from .planner import amount_per_sales_unit, constraint_violations, make_plans, round_qty
from .search import get_products, normalize_claims, search

QUOTE_FALLBACK_TTL = timedelta(hours=2)
# Reasons a product cannot be quoted at all. `no_availability_data` is quotable but goes to a human.
_BLOCKING = {OrderableReason.cutoff_passed, OrderableReason.sales_block, OrderableReason.insufficient_stock,
             OrderableReason.later_date, OrderableReason.no_price}


class GatewayError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# --- search & offers ---------------------------------------------------------------------------
def search_products(p: Principal, req: SearchRequest) -> SearchResult:
    res = search(req)
    audit.log("SEARCH", p.actor, {"text": req.text, "matches": res.total_matches,
                                  "categories": res.category_counts, "filters": req.model_dump(exclude={"text", "limit"}, exclude_defaults=True)},
              buyer_id=p.buyer_id)
    return res


def check_offers(p: Principal, req: OffersRequest) -> dict:
    offers, now = get_offers(req.product_ids, req.delivery_date)
    unknown = sorted(set(req.product_ids) - {o.product_id for o in offers})
    result: dict = {"delivery_date": req.delivery_date.isoformat(), "checked_at": now.isoformat(),
                    "offers": [o.model_dump(mode="json") for o in offers], "unknown_product_ids": unknown}
    need = Need(item="Requested products", quantity=req.quantity or 1, unit=req.unit or "PCS",
                delivery_date=req.delivery_date, free_from=req.required_claims,
                exclude_allergens=req.exclude_allergens, preferred_product_ids=req.product_ids)
    hints = {o.product_id: o.substitutes for o in offers if o.substitutes and _needs_alternatives(o, need)}
    if hints:
        result["substitution_hints"] = hints
    candidates = offers
    forbidden = set(expand_allergens(req.exclude_allergens + p.mandate.forbidden_allergens))
    explicit_exclusions = set(expand_allergens(req.exclude_allergens))

    def eligible(offer: Offer, *, alternative: bool = False) -> bool:
        trace_exclusions = forbidden if alternative else explicit_exclusions
        return (
            not forbidden.intersection(offer.allergens_contains)
            and not trace_exclusions.intersection(offer.allergens_may_contain)
            and not constraint_violations(offer, need)
            and (p.mandate.allowed_categories is None or any(
                (offer.category or "").startswith(category) for category in p.mandate.allowed_categories))
        )

    if req.include_substitutes:
        catalog_hints = {
            offer.product_id: substitutions.candidates(offer, req.required_claims, req.exclude_allergens)
            for offer in offers[:20] if not offer.substitutes and _needs_alternatives(offer, need)
        }
        candidates = _with_substitutes(offers, hints | catalog_hints, need)
        requested = set(req.product_ids)
        alternatives = {offer.product_id: offer for offer in candidates if offer.orderable and offer.product_id not in requested}
        result["alternatives"] = {
            pid: [{**alternatives[sid].model_dump(mode="json"),
                   "substitution_source": "valio_listed" if pid in hints else "catalog_ingredient_match"}
                  for sid in ids if sid in alternatives and eligible(alternatives[sid], alternative=True)]
            for pid, ids in (hints | catalog_hints).items() if ids
        }
        allowed_alternatives = {item["product_id"] for group in result["alternatives"].values() for item in group}
        candidates = offers + [offer for pid, offer in alternatives.items() if pid in allowed_alternatives]
    if req.quantity and req.unit:
        safe_candidates = [offer for offer in candidates if eligible(offer)]
        result["plan"] = make_plans(need, safe_candidates, mandate=p.mandate).model_dump(mode="json")
    if req.include_next_delivery:
        by_date: dict[date, list[str]] = defaultdict(list)
        for offer in offers:
            if offer.reason == OrderableReason.later_date and offer.available_date:
                by_date[offer.available_date].append(offer.product_id)
        later = []
        # Restrict follow-up traffic to the three soonest dates Valio reported.
        for day in sorted(by_date)[:3]:
            checked, _ = get_offers(by_date[day], day)
            later.extend({"delivery_date": day.isoformat(), "offer": offer.model_dump(mode="json")}
                         for offer in checked if offer.orderable and offer.available_date and eligible(offer))
        result["next_delivery_options"] = later
    if req.postal_code:
        result["delivery_estimate"] = estimate(req.postal_code)
    result["sources"] = {"price_and_availability": "Valio Aimo mock API",
                         "product_attributes": "Valio Aimo challenge catalog",
                         "co2_per_kg": "Challenge product-level average kg CO2e per kg",
                         "reliability": "Challenge delivery reliability data"}
    excluded = [f"{o.product_id}:{o.reason.value}" for o in offers if not o.orderable]
    audit.log("OFFERS_CHECKED", p.actor, {"count": len(offers), "delivery_date": req.delivery_date.isoformat(),
                                          "orderable": sum(o.orderable for o in offers), "excluded": excluded,
                                          "product_ids": req.product_ids,
                                          "observed_product_ids": [o.product_id for o in offers],
                                          "orderable_product_ids": [o.product_id for o in offers if o.orderable],
                                          "categories": sorted({o.category for o in offers if o.category})},
              buyer_id=p.buyer_id)
    return result


def _needs_alternatives(offer: Offer, need: Need) -> bool:
    per = amount_per_sales_unit(offer, need.unit)
    return not offer.orderable or bool(per and offer.available_qty is not None
                                       and offer.available_qty * per < need.quantity)


def _with_substitutes(offers: list[Offer], hints: dict[str, list[str]], need: Need) -> list[Offer]:
    seen = {offer.product_id for offer in offers}
    missing = list(dict.fromkeys(sid for ids in hints.values() for sid in ids if sid not in seen))
    if missing:
        extra, _ = get_offers(missing[:1000], need.delivery_date)
        return offers + extra
    return offers


def plan_need(p: Principal, need: Need, product_ids: list[str]) -> tuple[PlanResult, list[Offer]]:
    offers, _ = get_offers(product_ids, need.delivery_date)
    hints = {offer.product_id: offer.substitutes for offer in offers if _needs_alternatives(offer, need)}
    offers = _with_substitutes(offers, hints, need)
    return make_plans(need, offers, mandate=p.mandate), offers


# --- quotes ------------------------------------------------------------------------------------
def weekly_spent(buyer_id: str, at: datetime | None = None, *, conn=None) -> float:
    at = at or store.now()
    monday = (at - timedelta(days=at.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    fetch = store.fetchone if conn is None else lambda sql, params: conn.execute(sql, params).fetchone()
    row = fetch(
        "SELECT COALESCE(SUM(o.total_net),0) AS s FROM orders o JOIN quotes q USING(quote_id) "
        "WHERE o.buyer_id=? AND julianday(o.created_at)>=julianday(?) AND "
        "(o.status='confirmed' OR (o.status='pending_approval' AND julianday(q.expires_at)>julianday(?)))",
        (buyer_id, monday.isoformat(), at.isoformat()))
    return float(row["s"])


def _evaluate(p: Principal, lines: list[QuoteLine], offers: dict[str, Offer], total: float, need: Need | None, *, delivery: date, conn=None) -> PolicyResult:
    coverage = None
    if need is not None:
        covered = sum(l.covers or 0 for l in lines)
        coverage = min(covered / need.quantity, 1.0)
    result = policy.evaluate(p.mandate, lines, offers, total_net=total, weekly_spent=weekly_spent(p.buyer_id, conn=conn),
                             need=need, coverage=coverage, today=store.now().date())
    if result.decision == Decision.reject:
        return result
    supplier_stock = any(
        offer.unlimited and (offer.logistic_model or "").casefold() == "terminal"
        for offer in offers.values()
    )
    review = {
        "catalog_substitution": (any(line.substitution_source == "catalog_ingredient_match" for line in lines),
                                 "Aimo review is required for a catalog-suggested substitute."),
        "supplier_stock_unverified": (supplier_stock, "Aimo review is required to confirm supplier stock quantities."),
    }
    for rule, (triggered, message) in review.items():
        if triggered:
            result.decision = Decision.needs_approval
            result.reasons = [reason for reason in result.reasons if reason != "All mandate rules passed."] + [message]
            result.fired_rules.append(FiredRule(rule_id=rule, effect=Decision.needs_approval, message=message))
    for entry in recurring.compare(p.buyer_id, delivery, lines, conn=conn):
        if entry["changes"]:
            message = (f"Recurring SKU {entry['product_id']} differs from its usual order. "
                       f"Quantity {entry['quantity_change_pct']:+g}%. "
                       + (f"Unit price {entry['price_change_pct']:+g}%." if entry["price_change_pct"] is not None else ""))
            result.decision = Decision.needs_approval
            result.reasons = [reason for reason in result.reasons if reason != "All mandate rules passed."] + [message]
            result.fired_rules.append(FiredRule(rule_id="standing_order_drift", effect=Decision.needs_approval, message=message))
    return result


def _dietary_conflicts(offers: list[Offer], allergens: list[str], claims: list[str]) -> list[str]:
    forbidden = set(expand_allergens(allergens))
    required = set(normalize_claims(claims))
    return [offer.product_id for offer in offers if
            forbidden.intersection(offer.allergens_contains + offer.allergens_may_contain)
            or not required.issubset(offer.claims)]


def create_quote(p: Principal, req: QuoteRequest, *, supersedes: str | None = None) -> Quote:
    if p.role not in {"agent", "client"} or not p.can_order:
        raise GatewayError(403, "Use a purchasing agent or client workspace key")
    ids = [l.product_id for l in req.lines]
    offers_list, now = get_offers(ids, req.delivery_date, fresh=True)
    offers = {o.product_id: o for o in offers_list}
    catalog = get_products(list(req.need.preferred_product_ids) if req.need else [])
    conflicts = _dietary_conflicts(offers_list, req.exclude_allergens, req.required_claims)
    errors = [f"{sku}: conflicts with requested dietary constraints" for sku in conflicts]
    warnings, lines = [], []
    qty_by_pid: dict[str, float] = {}
    for l in req.lines:
        o = offers.get(l.product_id)
        if o is None:
            errors.append(f"{l.product_id}: unknown product")
            continue
        if o.reason in _BLOCKING:
            errors.append(f"{l.product_id}: not orderable for {req.delivery_date} ({o.reason.value}"
                          + (f", cutoff was {o.closing_time.isoformat()}" if o.reason == OrderableReason.cutoff_passed else "") + ")")
            continue
        qty = round_qty(l.quantity, o)
        if qty != l.quantity:
            warnings.append(f"{l.product_id}: quantity rounded {l.quantity:g} -> {qty:g} {o.sales_unit} (lot size)")
        qty_by_pid[o.product_id] = qty_by_pid.get(o.product_id, 0.0) + qty
        if o.available_qty is not None and qty_by_pid[o.product_id] > o.available_qty:
            errors.append(f"{l.product_id}: only {o.available_qty:g} {o.sales_unit} available, asked {qty_by_pid[o.product_id]:g}")
            continue
        if o.reason == OrderableReason.no_availability_data:
            warnings.append(f"{l.product_id}: availability unknown, a human must confirm")
        need = req.need
        pref = need.preferred_product_ids if need else []
        is_sub = bool(pref) and o.product_id not in pref
        source = None
        if is_sub:
            source = ("valio_listed" if any(o.product_id in catalog[pid].substitutes for pid in pref if pid in catalog)
                      else "catalog_ingredient_match")
        per = amount_per_sales_unit(o, need.unit) if need else None
        kg = amount_per_sales_unit(o, "KG")
        emissions = round(qty * kg * o.co2_per_kg, 3) if kg is not None and o.co2_per_kg is not None else None
        lines.append(QuoteLine(
            product_id=o.product_id, name=o.name, category=o.category, quantity=qty, sales_unit=o.sales_unit,
            unit_price=o.unit_price, unit_price_with_tax=o.unit_price_with_tax,
            line_total=round(qty * o.unit_price, 2), closing_time=o.closing_time,
            covers=round(qty * per, 3) if per else None, is_substitute=is_sub, estimated_kg_co2e=emissions,
            country=o.country, availability_checked_at=now, available_sales_units=o.available_qty,
            delivery_reliability=o.reliability,
            substitute_for=pref[0] if is_sub else None, substitution_source=source,
            substitute_for_category=catalog[pref[0]].category if is_sub and pref[0] in catalog else None))
    if errors:
        audit.log("QUOTE_REJECTED", p.actor, {"errors": errors, "lines": [l.model_dump() for l in req.lines]},
                  buyer_id=p.buyer_id)
        raise GatewayError(409, "Cannot quote: " + "; ".join(errors))

    total = round(sum(l.line_total for l in lines), 2)
    gross = round(sum(l.quantity * (l.unit_price_with_tax or l.unit_price) for l in lines), 2)
    preview = _evaluate(p, lines, offers, total, req.need, delivery=req.delivery_date)
    expires = quotes.expiry([offers[l.product_id].price_valid_to for l in lines],
                            [l.closing_time for l in lines], now + QUOTE_FALLBACK_TTL)
    quote_id = _id("q")
    payload = {"quote_id": quote_id, "buyer_id": p.buyer_id, "delivery_date": req.delivery_date.isoformat(),
               "lines": [l.model_dump(mode="json") for l in lines], "total_net": total, "total_gross": gross,
               "currency": "EUR", "created_at": now.isoformat(), "expires_at": expires.isoformat(),
               "need": req.need.model_dump(mode="json") if req.need else None, "order_channel": p.role,
               "exclude_allergens": req.exclude_allergens, "required_claims": req.required_claims}
    jws = quotes.sign(payload)
    quote = Quote(**payload, policy_preview=preview, signature=jws, warnings=warnings)
    with store.transaction() as conn:
        if supersedes:
            changed = conn.execute("UPDATE quotes SET status='superseded' WHERE quote_id=? AND buyer_id=? "
                                   "AND status='open' AND json_extract(payload_json,'$.order_channel')='client'",
                                   (supersedes, p.buyer_id))
            if changed.rowcount != 1:
                raise GatewayError(409, "The original draft changed. Refresh and try again.")
        conn.execute("INSERT INTO quotes (quote_id,buyer_id,created_at,expires_at,status,total_net,payload_json,jws)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (quote_id, p.buyer_id, now.isoformat(), expires.isoformat(), "open", total, json.dumps(payload), jws))
        evidence = {"lines": payload["lines"], "total_net": total, "expires_at": payload["expires_at"],
                    "decision": preview.decision.value, "policy_preview": preview.model_dump(mode="json"),
                    "warnings": warnings}
        if audit.inquiry_sequence.get() is not None:
            evidence["inquiry_seq"] = audit.inquiry_sequence.get()
        if supersedes:
            evidence["supersedes"] = supersedes
        store.append_in_transaction(conn, "QUOTE_CREATED", p.actor, evidence, buyer_id=p.buyer_id, quote_id=quote_id)
    return quote


# --- orders ------------------------------------------------------------------------------------
def _order_from_row(r) -> Order:
    return Order(order_id=r["order_id"], quote_id=r["quote_id"], buyer_id=r["buyer_id"], status=r["status"],
                 total_net=r["total_net"], currency=r["currency"], delivery_date=r["delivery_date"],
                 lines=json.loads(r["lines_json"]), policy=json.loads(r["policy_json"]),
                 approval_id=r["approval_id"], agent_rationale=r["agent_rationale"] or "",
                 created_at=r["created_at"], updated_at=r["updated_at"])


def _quote_invalid(p: Principal, quote_id: str, status: int, msg: str) -> GatewayError:
    """Rule quote_invalid: unknown, reused, tampered or expired quotes never become orders."""
    audit.log("QUOTE_INVALID", p.actor, {"rule_id": "quote_invalid", "reason": msg}, buyer_id=p.buyer_id, quote_id=quote_id)
    return GatewayError(status, f"quote_invalid: {msg}")


def repeat_quote(p: Principal, order_id: str, delivery_date: date) -> Quote:
    if p.role not in {"agent", "client"} or not p.can_order:
        raise GatewayError(403, "Use a purchasing agent or client workspace key")
    if delivery_date < store.now().date():
        raise GatewayError(422, "Choose today or a future delivery date")
    original = get_order(p, order_id)
    if original.status != "confirmed":
        raise GatewayError(409, "Choose a confirmed ticket to repeat")
    signed = store.fetchone("SELECT jws FROM quotes WHERE quote_id=?", (original.quote_id,))
    if signed is None:
        raise GatewayError(409, "The original signed quote is unavailable")
    try:
        payload = quotes.verify(signed["jws"])
    except ValueError as exc:
        raise GatewayError(409, "The original quote could not be verified") from exc
    need = payload.get("need")
    if need:
        need["delivery_date"] = delivery_date.isoformat()
    return create_quote(p, QuoteRequest(delivery_date=delivery_date, need=need,
        exclude_allergens=payload.get("exclude_allergens", []), required_claims=payload.get("required_claims", []), lines=[
        {"product_id": line.product_id, "quantity": line.quantity} for line in original.lines
    ]))



def check_recurring_quote(p: Principal, quote_id: str) -> dict:
    row = store.fetchone("SELECT buyer_id, jws FROM quotes WHERE quote_id=?", (quote_id,))
    if row is None or row["buyer_id"] != p.buyer_id:
        raise GatewayError(404, "Quote not found for this buyer")
    payload = quotes.verify(row["jws"])
    delivery = date.fromisoformat(payload["delivery_date"])
    lines = [QuoteLine.model_validate(line) for line in payload["lines"]]
    return {"quote_id": quote_id, "delivery_date": delivery.isoformat(),
            "quantity_threshold_pct": recurring.QUANTITY_LIMIT * 100,
            "price_threshold_pct": recurring.PRICE_LIMIT * 100,
            "baselines": recurring.compare(p.buyer_id, delivery, lines)}


def _recheck_stock(lines: list[QuoteLine], delivery: date) -> tuple[dict[str, Offer], list[str]]:
    quantities: dict[str, float] = {}
    for line in lines:
        quantities[line.product_id] = quantities.get(line.product_id, 0) + line.quantity
    live, _ = get_offers(list(quantities), delivery, fresh=True)
    offers = {offer.product_id: offer for offer in live}
    problems = []
    for pid, quantity in quantities.items():
        offer = offers.get(pid)
        if offer is None:
            problems.append(f"{pid}:unknown_product")
        elif offer.reason in _BLOCKING:
            problems.append(f"{pid}:{offer.reason.value}")
        elif offer.available_qty is not None and quantity > offer.available_qty:
            problems.append(f"{pid}:insufficient_stock")
    return offers, problems


_APPROVAL_QUERY = (
    "SELECT a.*, o.quote_id, o.delivery_date, o.lines_json, q.expires_at, q.payload_json, "
    "json_extract(q.payload_json, '$.order_channel') AS channel "
    "FROM approvals a JOIN orders o USING(order_id) JOIN quotes q USING(quote_id) WHERE a.approval_id=?"
)


def _pending_approval(p: Principal | Admin, row, approval_id: str):
    if row is None or (isinstance(p, Principal) and row["buyer_id"] != p.buyer_id):
        raise GatewayError(404, f"Approval {approval_id} not found")
    if isinstance(p, Principal) and row["channel"]:
        raise GatewayError(403, "This request requires Aimo operations review")
    if row["status"] != "pending":
        raise GatewayError(409, f"Approval {approval_id} is already {row['status']}")
    return row


def place_order(p: Principal, quote_id: str, agent_rationale: str = "", *, replay: bool = False) -> Order:
    if p.role not in {"agent", "client"} or not p.can_order:
        raise GatewayError(403, "Use a purchasing agent or client workspace key")
    row = store.fetchone("SELECT * FROM quotes WHERE quote_id=?", (quote_id,))
    if row is None or row["buyer_id"] != p.buyer_id:
        raise _quote_invalid(p, quote_id, 404, f"quote {quote_id} not found for this buyer")
    try:
        payload = quotes.verify(row["jws"])                 # tamper check on the stored, signed quote
    except ValueError as e:
        raise _quote_invalid(p, quote_id, 409, str(e)) from e
    if payload != json.loads(row["payload_json"]):
        raise _quote_invalid(p, quote_id, 409, "quote payload does not match its signature")
    if payload.get("order_channel", "agent") != p.role:
        raise _quote_invalid(p, quote_id, 403, "Quote belongs to a different purchasing channel")
    if row["status"] != "open":
        if replay:
            existing = store.fetchone("SELECT * FROM orders WHERE quote_id=? AND status!='received'", (quote_id,))
            if existing:
                return _order_from_row(existing)
        raise _quote_invalid(p, quote_id, 409, f"quote {quote_id} was already used")
    if store.now() >= _aware(datetime.fromisoformat(payload["expires_at"])):
        raise _quote_invalid(p, quote_id, 409, f"Quote {quote_id} expired; request a new quote")

    lines = [QuoteLine(**line) for line in payload["lines"]]
    need = Need(**payload["need"]) if payload.get("need") else None
    delivery = date.fromisoformat(payload["delivery_date"])
    offers, stale = _recheck_stock(lines, delivery)
    stale.extend(f"{sku}:dietary_conflict" for sku in _dietary_conflicts(
        list(offers.values()), payload.get("exclude_allergens", []), payload.get("required_claims", [])))
    order_id = _id("ord")
    ids = dict(buyer_id=p.buyer_id, order_id=order_id, quote_id=quote_id)
    with store.transaction() as conn:
        now = store.now()
        if now >= _aware(datetime.fromisoformat(payload["expires_at"])):
            raise GatewayError(409, "Quote expired while checking availability")
        claimed = conn.execute("UPDATE quotes SET status='used' WHERE quote_id=? AND status='open'", (quote_id,))
        if claimed.rowcount != 1:
            if replay:
                existing = conn.execute(
                    "SELECT * FROM orders WHERE quote_id=? AND status!='received'", (quote_id,)
                ).fetchone()
                if existing:
                    return _order_from_row(existing)
            raise GatewayError(409, f"quote_invalid: quote {quote_id} was already used")
        result = _evaluate(p, lines, offers, payload["total_net"], need, delivery=delivery, conn=conn)
        if stale:
            message = f"No longer orderable since the quote: {', '.join(stale)}"
            result = PolicyResult(decision=Decision.reject, mandate_id=result.mandate_id,
                                  fired_rules=result.fired_rules + [
                                      FiredRule(rule_id="quote_invalid", effect=Decision.reject, message=message)],
                                  reasons=[r for r in result.reasons if r != "All mandate rules passed."] + [message])
        status = {Decision.auto: "confirmed", Decision.needs_approval: "pending_approval",
                  Decision.reject: "rejected"}[result.decision]
        approval_id = _id("apr") if status == "pending_approval" else None
        conn.execute(
            "INSERT INTO orders (order_id,quote_id,buyer_id,status,total_net,currency,delivery_date,lines_json,"
            "policy_json,approval_id,agent_rationale,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, quote_id, p.buyer_id, status, payload["total_net"], payload["currency"], payload["delivery_date"],
             json.dumps(payload["lines"]), result.model_dump_json(), approval_id, agent_rationale,
             now.isoformat(), now.isoformat()))
        store.append_in_transaction(conn, "ORDER_RECEIVED", p.actor,
                                    {"agent_rationale": agent_rationale, "total_net": payload["total_net"],
                                     "channel": p.role}, **ids)
        store.append_in_transaction(conn, "POLICY_EVALUATED", "gateway:policy", result.model_dump(mode="json"), **ids)
        if approval_id:
            conn.execute("INSERT INTO approvals (approval_id,order_id,buyer_id,status,reasons_json,created_at)"
                         " VALUES (?,?,?,?,?,?)", (approval_id, order_id, p.buyer_id, "pending",
                                                  json.dumps(result.reasons), now.isoformat()))
            store.append_in_transaction(conn, "APPROVAL_REQUESTED", "gateway",
                                        {"approval_id": approval_id, "reasons": result.reasons}, **ids)
        else:
            event = "ORDER_CONFIRMED" if status == "confirmed" else "ORDER_REJECTED"
            store.append_in_transaction(conn, event, "gateway:policy", {"reason": " ".join(result.reasons)}, **ids)
    return get_order(p, order_id)


def expire_pending(*, buyer_id: str | None = None, order_id: str | None = None) -> None:
    now = store.now().isoformat()
    query = (
        "SELECT a.approval_id, o.order_id, o.quote_id, o.buyer_id, q.expires_at "
        "FROM approvals a JOIN orders o USING(order_id) JOIN quotes q USING(quote_id) "
        "WHERE a.status='pending' AND julianday(q.expires_at)<=julianday(?) "
        "AND (? IS NULL OR o.buyer_id=?) AND (? IS NULL OR o.order_id=?)"
    )
    params = (now, buyer_id, buyer_id, order_id, order_id)
    if not store.fetchone(query + " LIMIT 1", params):
        return
    with store.transaction() as conn:
        for row in conn.execute(query, params).fetchall():
            reason = f"Quote expired at {row['expires_at']} before approval"
            conn.execute("UPDATE approvals SET status='rejected', decided_at=?, decided_by=?, comment=? WHERE approval_id=?",
                         (now, "gateway:expiry", reason, row["approval_id"]))
            conn.execute("UPDATE orders SET status='expired', updated_at=? WHERE order_id=?", (now, row["order_id"]))
            store.append_in_transaction(conn, "ORDER_EXPIRED", "gateway:expiry", {"reason": reason},
                                        buyer_id=row["buyer_id"], order_id=row["order_id"], quote_id=row["quote_id"])


def get_order(p: Principal | Admin, order_id: str) -> Order:
    expire_pending(buyer_id=p.buyer_id if isinstance(p, Principal) else None, order_id=order_id)
    r = store.fetchone("SELECT * FROM orders WHERE order_id=?", (order_id,))
    if r is None or r["status"] == "received" or (isinstance(p, Principal) and r["buyer_id"] != p.buyer_id):
        raise GatewayError(404, f"Order {order_id} not found for this buyer")
    return _order_from_row(r)


def list_orders(p: Principal, limit: int = 50) -> list[Order]:
    expire_pending(buyer_id=p.buyer_id)
    rows = store.fetchall("SELECT * FROM orders WHERE buyer_id=? AND status!='received' ORDER BY created_at DESC LIMIT ?", (p.buyer_id, limit))
    return [_order_from_row(r) for r in rows]


# --- approvals ---------------------------------------------------------------------------------
def _approval_from_row(r) -> Approval:
    return Approval(approval_id=r["approval_id"], order_id=r["order_id"], buyer_id=r["buyer_id"], status=r["status"],
                    reasons=json.loads(r["reasons_json"]), created_at=r["created_at"], decided_at=r["decided_at"],
                    decided_by=r["decided_by"], comment=r["comment"])


def list_approvals(p: Principal, status: str | None = "pending") -> list[dict]:
    expire_pending(buyer_id=p.buyer_id)
    sql, params = "SELECT * FROM approvals WHERE buyer_id=?", [p.buyer_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = store.fetchall(sql + " ORDER BY created_at DESC", tuple(params))
    return [{"approval": _approval_from_row(r).model_dump(mode="json"),
             "order": get_order(p, r["order_id"]).model_dump(mode="json")} for r in rows]


def decide_approval(p: Principal | Admin, approval_id: str, decision: str, comment: str = "") -> Order:
    if isinstance(p, Principal) and p.role != "approver":
        raise GatewayError(403, "Only a human approver can decide approvals")
    if decision not in ("approve", "reject"):
        raise GatewayError(400, "Decision must be 'approve' or 'reject'")
    row = _pending_approval(p, store.fetchone(_APPROVAL_QUERY, (approval_id,)), approval_id)
    problems = []
    if decision == "approve" and store.now() < _aware(datetime.fromisoformat(row["expires_at"])):
        lines = [QuoteLine.model_validate(line) for line in json.loads(row["lines_json"])]
        offers, problems = _recheck_stock(lines, date.fromisoformat(row["delivery_date"]))
        payload = json.loads(row["payload_json"])
        problems.extend(f"{sku}:dietary_conflict" for sku in _dietary_conflicts(
            list(offers.values()), payload.get("exclude_allergens", []), payload.get("required_claims", [])))
    with store.transaction() as conn:
        row = _pending_approval(p, conn.execute(_APPROVAL_QUERY, (approval_id,)).fetchone(), approval_id)
        now = store.now()
        expired = decision == "approve" and now >= _aware(datetime.fromisoformat(row["expires_at"]))
        approved = decision == "approve" and not expired and not problems
        status = "expired" if expired else "confirmed" if approved else "rejected"
        if expired:
            reason = f"Quote expired at {row['expires_at']}"
        elif problems:
            reason = f"No longer orderable at review: {', '.join(problems)}"
        else:
            reason = "approved by human" if approved else "rejected by approver"
        conn.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=?, comment=? WHERE approval_id=?",
                     ("approved" if approved else "rejected", now.isoformat(), p.actor, comment or reason, approval_id))
        conn.execute("UPDATE orders SET status=?, updated_at=? WHERE order_id=?",
                     (status, now.isoformat(), row["order_id"]))
        ids = dict(buyer_id=row["buyer_id"], order_id=row["order_id"], quote_id=row["quote_id"])
        if not expired:
            store.append_in_transaction(conn, "APPROVAL_GRANTED" if approved else "APPROVAL_DENIED",
                                        p.actor, {"approval_id": approval_id, "comment": comment, "reason": reason}, **ids)
        store.append_in_transaction(conn, f"ORDER_{status.upper()}", p.actor,
                                    {"reason": reason},
                                    **ids)
    return get_order(p, row["order_id"])


# --- audit -------------------------------------------------------------------------------------
def get_audit_log(p: Principal | Admin, order_id: str) -> dict:
    get_order(p, order_id)  # ownership check
    return {"order_id": order_id, "events": audit.timeline(order_id), "text": audit.render_text(order_id),
            "chain": store.verify_chain()}
