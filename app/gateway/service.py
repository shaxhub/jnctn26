"""Core gateway operations. REST (api.py), MCP (mcp_server.py), the agent and the scripts all call
these functions, so behaviour and audit logging are identical on every channel.

Every function takes the authenticated Principal first; buyer id and mandate come from it, never
from the caller's arguments.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta

from . import audit, policy, quotes, store
from .auth import Principal
from .config import TZ
from .models import (Approval, Decision, FiredRule, Need, Offer, OffersRequest, Order, OrderableReason, OrderStatus, PlanResult,
                     PolicyResult, Quote, QuoteLine, QuoteRequest, SearchRequest, SearchResult)
from .offers import get_offers
from .planner import amount_per_sales_unit, make_plans, round_qty
from .search import get_products, search

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
                                  "filters": req.model_dump(exclude={"text", "limit"}, exclude_defaults=True)},
              buyer_id=p.buyer_id)
    return res


def check_offers(p: Principal, req: OffersRequest) -> dict:
    offers, now = get_offers(req.product_ids, req.delivery_date)
    unknown = sorted(set(req.product_ids) - {o.product_id for o in offers})
    result: dict = {"delivery_date": req.delivery_date.isoformat(), "checked_at": now.isoformat(),
                    "offers": [o.model_dump(mode="json") for o in offers], "unknown_product_ids": unknown}
    # substitution hints: Valio's own substitution list for products that cannot be delivered
    hints = {o.product_id: o.substitutes for o in offers if not o.orderable and o.substitutes}
    if hints:
        result["substitution_hints"] = hints
    if req.quantity and req.unit:
        need = Need(item="ad-hoc", quantity=req.quantity, unit=req.unit, delivery_date=req.delivery_date)
        result["plan"] = make_plans(need, offers, mandate=p.mandate).model_dump(mode="json")
    excluded = [f"{o.product_id}:{o.reason.value}" for o in offers if not o.orderable]
    audit.log("OFFERS_CHECKED", p.actor, {"count": len(offers), "delivery_date": req.delivery_date.isoformat(),
                                          "orderable": sum(o.orderable for o in offers), "excluded": excluded},
              buyer_id=p.buyer_id)
    return result


def plan_need(p: Principal, need: Need, product_ids: list[str]) -> tuple[PlanResult, list[Offer]]:
    offers, _ = get_offers(product_ids, need.delivery_date)
    seen_ids = {o.product_id for o in offers}
    missing_sub_ids = list(dict.fromkeys(
        sid for o in offers if not o.orderable for sid in o.substitutes if sid not in seen_ids
    ))
    if missing_sub_ids:
        sub_offers, _ = get_offers(missing_sub_ids, need.delivery_date)
        offers = offers + sub_offers
    return make_plans(need, offers, mandate=p.mandate), offers


# --- quotes ------------------------------------------------------------------------------------
def weekly_spent(buyer_id: str, at: datetime | None = None) -> float:
    at = at or store.now()
    monday = (at - timedelta(days=at.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    row = store.fetchone("SELECT COALESCE(SUM(total_net),0) AS s FROM orders WHERE buyer_id=? AND created_at>=?"
                         " AND status IN ('confirmed','pending_approval')", (buyer_id, monday.isoformat()))
    return float(row["s"])


def _evaluate(p: Principal, lines: list[QuoteLine], offers: dict[str, Offer], total: float, need: Need | None) -> PolicyResult:
    coverage = None
    if need is not None:
        covered = sum(l.covers or 0 for l in lines)
        coverage = min(covered / need.quantity, 1.0)
    return policy.evaluate(p.mandate, lines, offers, total_net=total, weekly_spent=weekly_spent(p.buyer_id),
                           need=need, coverage=coverage, today=store.now().date())


def create_quote(p: Principal, req: QuoteRequest) -> Quote:
    if p.role != "agent":
        raise GatewayError(403, "Only a purchasing agent key can create quotes or place orders; approver keys are for human sign-off")
    ids = [l.product_id for l in req.lines]
    offers_list, now = get_offers(ids, req.delivery_date)
    offers = {o.product_id: o for o in offers_list}
    catalog = get_products(list(req.need.preferred_product_ids) if req.need else [])
    errors, warnings, lines = [], [], []
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
        per = amount_per_sales_unit(o, need.unit) if need else None
        lines.append(QuoteLine(
            product_id=o.product_id, name=o.name, category=o.category, quantity=qty, sales_unit=o.sales_unit,
            unit_price=o.unit_price, unit_price_with_tax=o.unit_price_with_tax,
            line_total=round(qty * o.unit_price, 2), closing_time=o.closing_time,
            covers=round(qty * per, 3) if per else None, is_substitute=is_sub,
            substitute_for=pref[0] if is_sub else None,
            substitute_for_category=catalog[pref[0]].category if is_sub and pref[0] in catalog else None))
    if errors:
        audit.log("QUOTE_REJECTED", p.actor, {"errors": errors, "lines": [l.model_dump() for l in req.lines]},
                  buyer_id=p.buyer_id)
        raise GatewayError(409, "Cannot quote: " + "; ".join(errors))

    total = round(sum(l.line_total for l in lines), 2)
    gross = round(sum(l.quantity * (l.unit_price_with_tax or l.unit_price) for l in lines), 2)
    preview = _evaluate(p, lines, offers, total, req.need)
    expires = quotes.expiry([offers[l.product_id].price_valid_to for l in lines],
                            [l.closing_time for l in lines], now + QUOTE_FALLBACK_TTL)
    quote_id = _id("q")
    payload = {"quote_id": quote_id, "buyer_id": p.buyer_id, "delivery_date": req.delivery_date.isoformat(),
               "lines": [l.model_dump(mode="json") for l in lines], "total_net": total, "total_gross": gross,
               "currency": "EUR", "created_at": now.isoformat(), "expires_at": expires.isoformat(),
               "need": req.need.model_dump(mode="json") if req.need else None}
    jws = quotes.sign(payload)
    quote = Quote(**payload, policy_preview=preview, signature=jws, warnings=warnings)
    store.execute("INSERT INTO quotes (quote_id,buyer_id,created_at,expires_at,status,total_net,payload_json,jws)"
                  " VALUES (?,?,?,?,?,?,?,?)", (quote_id, p.buyer_id, now.isoformat(), expires.isoformat(), "open",
                                                total, json.dumps(payload), jws))
    audit.log("QUOTE_CREATED", p.actor, {"lines": payload["lines"], "total_net": total, "expires_at": payload["expires_at"],
                                         "decision": preview.decision.value, "warnings": warnings},
              buyer_id=p.buyer_id, quote_id=quote_id)
    return quote


# --- orders ------------------------------------------------------------------------------------
def _order_from_row(r) -> Order:
    return Order(order_id=r["order_id"], quote_id=r["quote_id"], buyer_id=r["buyer_id"], status=r["status"],
                 total_net=r["total_net"], currency=r["currency"], delivery_date=r["delivery_date"],
                 lines=json.loads(r["lines_json"]), policy=json.loads(r["policy_json"]),
                 approval_id=r["approval_id"], agent_rationale=r["agent_rationale"] or "",
                 created_at=r["created_at"], updated_at=r["updated_at"])


def _set_status(order_id: str, status: OrderStatus) -> None:
    store.execute("UPDATE orders SET status=?, updated_at=? WHERE order_id=?", (status.value, store.now().isoformat(), order_id))


def _quote_invalid(p: Principal, quote_id: str, status: int, msg: str) -> GatewayError:
    """Rule quote_invalid: unknown, reused, tampered or expired quotes never become orders."""
    audit.log("QUOTE_INVALID", p.actor, {"rule_id": "quote_invalid", "reason": msg}, buyer_id=p.buyer_id, quote_id=quote_id)
    return GatewayError(status, f"quote_invalid: {msg}")


def place_order(p: Principal, quote_id: str, agent_rationale: str = "") -> Order:
    if p.role != "agent":
        raise GatewayError(403, "Only a purchasing agent key can create quotes or place orders; approver keys are for human sign-off")
    row = store.fetchone("SELECT * FROM quotes WHERE quote_id=?", (quote_id,))
    if row is None or row["buyer_id"] != p.buyer_id:
        raise _quote_invalid(p, quote_id, 404, f"quote {quote_id} not found for this buyer")
    if row["status"] != "open":
        raise _quote_invalid(p, quote_id, 409, f"quote {quote_id} was already used")
    try:
        payload = quotes.verify(row["jws"])                 # tamper check on the stored, signed quote
    except ValueError as e:
        raise _quote_invalid(p, quote_id, 409, str(e)) from e
    if payload != json.loads(row["payload_json"]):
        raise _quote_invalid(p, quote_id, 409, "quote payload does not match its signature")
    now = store.now()
    if now >= _aware(datetime.fromisoformat(payload["expires_at"])):
        raise _quote_invalid(p, quote_id, 409, f"quote {quote_id} expired at {payload['expires_at']}; request a new quote")

    lines = [QuoteLine(**l) for l in payload["lines"]]
    need = Need(**payload["need"]) if payload.get("need") else None
    delivery = date.fromisoformat(payload["delivery_date"])
    order_id = _id("ord")
    claimed = False
    try:
        with store._lock, store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute("UPDATE quotes SET status='used' WHERE quote_id=? AND status='open'", (quote_id,))
                if cur.rowcount == 1:
                    conn.execute(
                        "INSERT INTO orders (order_id,quote_id,buyer_id,status,total_net,currency,delivery_date,lines_json,"
                        "policy_json,approval_id,agent_rationale,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (order_id, quote_id, p.buyer_id, "received", payload["total_net"], "EUR", payload["delivery_date"],
                         json.dumps(payload["lines"]), "{}", None, agent_rationale, now.isoformat(), now.isoformat()))
                    conn.execute("COMMIT")
                    claimed = True
                else:
                    conn.execute("ROLLBACK")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.IntegrityError as e:
        raise _quote_invalid(p, quote_id, 409, f"quote {quote_id} was already used") from e
    if not claimed:
        raise _quote_invalid(p, quote_id, 409, f"quote {quote_id} was already used")
    ids = dict(buyer_id=p.buyer_id, order_id=order_id, quote_id=quote_id)
    audit.log("ORDER_RECEIVED", p.actor, {"agent_rationale": agent_rationale, "total_net": payload["total_net"]}, **ids)

    # Re-check live availability: something may have changed since the quote (cutoff, sales block, stock drop).
    offers_list, _ = get_offers([l.product_id for l in lines], delivery)
    offers = {o.product_id: o for o in offers_list}
    stale = [f"{o.product_id}:{o.reason.value}" for o in offers_list if o.reason in _BLOCKING]
    qty_by_pid: dict[str, float] = {}
    for l in lines:
        qty_by_pid[l.product_id] = qty_by_pid.get(l.product_id, 0.0) + l.quantity
    for pid, total_qty in qty_by_pid.items():
        o = offers.get(pid)
        if o is not None and o.reason not in _BLOCKING and o.available_qty is not None and total_qty > o.available_qty:
            stale.append(f"{pid}:insufficient_stock")
    result = _evaluate(p, lines, offers, payload["total_net"], need)
    if stale:
        msg = f"No longer orderable since the quote: {', '.join(stale)}"
        result = PolicyResult(decision=Decision.reject, mandate_id=result.mandate_id,
                              fired_rules=result.fired_rules + [FiredRule(rule_id="quote_invalid", effect=Decision.reject, message=msg)],
                              reasons=[r for r in result.reasons if r != "All mandate rules passed."] + [msg])
    store.execute("UPDATE orders SET policy_json=? WHERE order_id=?", (result.model_dump_json(), order_id))
    audit.log("POLICY_EVALUATED", "gateway:policy", result.model_dump(mode="json"), **ids)

    if result.decision == Decision.auto:
        _set_status(order_id, OrderStatus.confirmed)
        # TODO(A): here the order would be sent to Valio's order API (not part of the mock).
        audit.log("ORDER_CONFIRMED", "gateway", {"reason": "auto-approved within mandate"}, **ids)
    elif result.decision == Decision.needs_approval:
        approval_id = _id("apr")
        store.execute("INSERT INTO approvals (approval_id,order_id,buyer_id,status,reasons_json,created_at)"
                      " VALUES (?,?,?,?,?,?)", (approval_id, order_id, p.buyer_id, "pending",
                                                json.dumps(result.reasons), now.isoformat()))
        store.execute("UPDATE orders SET approval_id=? WHERE order_id=?", (approval_id, order_id))
        _set_status(order_id, OrderStatus.pending_approval)
        audit.log("APPROVAL_REQUESTED", "gateway", {"approval_id": approval_id, "reasons": result.reasons}, **ids)
        # TODO(C): notify the approver (email / Teams / Slack) with a deep link to the Approvals tab.
    else:
        _set_status(order_id, OrderStatus.rejected)
        audit.log("ORDER_REJECTED", "gateway", {"reason": "; ".join(result.reasons)}, **ids)
    return get_order(p, order_id)


def get_order(p: Principal, order_id: str) -> Order:
    r = store.fetchone("SELECT * FROM orders WHERE order_id=?", (order_id,))
    if r is None or r["buyer_id"] != p.buyer_id:
        raise GatewayError(404, f"Order {order_id} not found for this buyer")
    return _order_from_row(r)


def list_orders(p: Principal, limit: int = 50) -> list[Order]:
    rows = store.fetchall("SELECT * FROM orders WHERE buyer_id=? ORDER BY created_at DESC LIMIT ?", (p.buyer_id, limit))
    return [_order_from_row(r) for r in rows]


# --- approvals ---------------------------------------------------------------------------------
def _approval_from_row(r) -> Approval:
    return Approval(approval_id=r["approval_id"], order_id=r["order_id"], buyer_id=r["buyer_id"], status=r["status"],
                    reasons=json.loads(r["reasons_json"]), created_at=r["created_at"], decided_at=r["decided_at"],
                    decided_by=r["decided_by"], comment=r["comment"])


def list_approvals(p: Principal, status: str | None = "pending") -> list[dict]:
    sql, params = "SELECT * FROM approvals WHERE buyer_id=?", [p.buyer_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = store.fetchall(sql + " ORDER BY created_at DESC", tuple(params))
    return [{"approval": _approval_from_row(r).model_dump(mode="json"),
             "order": get_order(p, r["order_id"]).model_dump(mode="json")} for r in rows]


def decide_approval(p: Principal, approval_id: str, decision: str, comment: str = "") -> Order:
    if p.role != "approver":
        raise GatewayError(403, "Only a human approver can decide approvals")
    if decision not in ("approve", "reject"):
        raise GatewayError(400, "Decision must be 'approve' or 'reject'")
    r = store.fetchone("SELECT * FROM approvals WHERE approval_id=?", (approval_id,))
    if r is None or r["buyer_id"] != p.buyer_id:
        raise GatewayError(404, f"Approval {approval_id} not found")
    if r["status"] != "pending":
        raise GatewayError(409, f"Approval {approval_id} is already {r['status']}")
    now = store.now()
    order = get_order(p, r["order_id"])
    ids = dict(buyer_id=p.buyer_id, order_id=order.order_id, quote_id=order.quote_id)
    if decision == "reject":
        store.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=?, comment=? WHERE approval_id=?",
                      ("rejected", now.isoformat(), p.actor, comment, approval_id))
        audit.log("APPROVAL_DENIED", p.actor, {"approval_id": approval_id, "comment": comment}, **ids)
        _set_status(order.order_id, OrderStatus.rejected)
        audit.log("ORDER_REJECTED", "gateway", {"reason": "rejected by approver"}, **ids)
        return get_order(p, order.order_id)
    q = store.fetchone("SELECT expires_at FROM quotes WHERE quote_id=?", (order.quote_id,))
    if now >= _aware(datetime.fromisoformat(q["expires_at"])):
        exp_comment = comment or f"Quote expired at {q['expires_at']}"
        store.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=?, comment=? WHERE approval_id=?",
                      ("rejected", now.isoformat(), p.actor, exp_comment, approval_id))
        _set_status(order.order_id, OrderStatus.expired)
        audit.log("ORDER_EXPIRED", "gateway", {"reason": f"approved after quote expiry {q['expires_at']}"}, **ids)
        return get_order(p, order.order_id)
    store.execute("UPDATE approvals SET status=?, decided_at=?, decided_by=?, comment=? WHERE approval_id=?",
                  ("approved", now.isoformat(), p.actor, comment, approval_id))
    audit.log("APPROVAL_GRANTED", p.actor, {"approval_id": approval_id, "comment": comment}, **ids)
    _set_status(order.order_id, OrderStatus.confirmed)
    audit.log("ORDER_CONFIRMED", "gateway", {"reason": "approved by human"}, **ids)
    return get_order(p, order.order_id)


# --- audit -------------------------------------------------------------------------------------
def get_audit_log(p: Principal, order_id: str) -> dict:
    get_order(p, order_id)  # ownership check
    return {"order_id": order_id, "events": audit.timeline(order_id), "text": audit.render_text(order_id),
            "chain": store.verify_chain()}
