"""Aimo-only inquiry, review and reporting endpoints."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from . import audit, service, store
from .auth import Admin, require_admin
from .config import TZ
from .models import ApprovalDecisionRequest

router = APIRouter(prefix="/operations", dependencies=[Depends(require_admin)])
SECTORS = {"hotel": "Hospitality", "hospital": "Healthcare"}
INQUIRIES = ("CLIENT_INQUIRY", "SEARCH", "OFFERS_CHECKED", "AGENT_RUN", "KITCHEN_PLAN", "SEASONAL_DISCOVERY")
DECISIONS = ("POLICY_EVALUATED", "APPROVAL_GRANTED", "APPROVAL_DENIED",
             "ORDER_CONFIRMED", "ORDER_REJECTED", "ORDER_EXPIRED")
EVENT_TYPES = {"all": INQUIRIES + DECISIONS + ("ORDER_RECEIVED", "APPROVAL_REQUESTED", "QUOTE_REJECTED", "QUOTE_INVALID"),
               "inquiries": INQUIRIES, "decisions": DECISIONS}
Period = Literal["month", "quarter", "year", "all"]


@router.get("/activity")
def activity(kind: Literal["all", "inquiries", "decisions"] = "all", buyer: str = Query("", max_length=80),
             q: str = Query("", max_length=160), before: int | None = Query(None, ge=1)):
    service.expire_pending(buyer_id=buyer or None)
    kinds = EVENT_TYPES[kind]
    where = [f"event_type IN ({','.join('?' for _ in kinds)})"]
    params = list(kinds)
    if buyer:
        where.append("buyer_id=?")
        params.append(buyer)
    if q.strip():
        where.append("instr(lower(coalesce(order_id,'') || ' ' || actor || ' ' || data_json), lower(?))>0")
        params.append(q.strip())
    if before is not None:
        where.append("seq < ?")
        params.append(before)
    rows = store.fetchall("SELECT * FROM audit_events WHERE " + " AND ".join(where) +
                          " ORDER BY seq DESC LIMIT 31", tuple(params))
    events = [store._row_event(row) for row in rows[:30]]
    for event in events:
        event["summary"] = audit._summary(event)
        event["sector"] = SECTORS.get(event["buyer_id"], "Other")
    return {"events": events, "next_before": events[-1]["seq"] if len(rows) > 30 else None}


@router.get("/orders")
def orders(status: Literal["pending_approval", "confirmed", "rejected", "expired"] | None = None,
           buyer: str = Query("", max_length=80), q: str = Query("", max_length=160),
           offset: int = Query(0, ge=0)):
    service.expire_pending(buyer_id=buyer or None)
    rows = store.fetchall(
        "SELECT * FROM orders WHERE status!='received' AND (? IS NULL OR status=?) AND (?='' OR buyer_id=?) "
        "AND (?='' OR instr(lower(order_id || ' ' || lines_json || ' ' || coalesce(agent_rationale,'')),lower(?))>0) "
        "ORDER BY created_at DESC, order_id DESC LIMIT 31 OFFSET ?", (status, status, buyer, buyer, q, q, offset))
    return {"orders": [service._order_from_row(row) for row in rows[:30]],
            "next_offset": offset + 30 if len(rows) > 30 else None}


@router.get("/orders/{order_id}")
def order_detail(order_id: str, admin: Admin = Depends(require_admin)):
    order = service.get_order(admin, order_id)
    details = service.get_audit_log(admin, order_id)
    row = store.fetchone("SELECT * FROM approvals WHERE approval_id=?", (order.approval_id,))
    return {"order": order, "approval": service._approval_from_row(row) if row else None, "audit": details}


@router.post("/approvals/{approval_id}")
def review(approval_id: str, request: ApprovalDecisionRequest, admin: Admin = Depends(require_admin)):
    return service.decide_approval(admin, approval_id, request.decision, request.comment)


def _period_start(period: Period, now: datetime) -> datetime:
    month = {"month": now.month, "quarter": 1 + 3 * ((now.month - 1) // 3), "year": 1, "all": 1}[period]
    return datetime(now.year if period != "all" else 1970, month, 1, tzinfo=TZ)


@router.get("/analytics")
def analytics(period: Period = "month"):
    service.expire_pending()
    now = store.now().astimezone(TZ)
    start = _period_start(period, now)
    window = (start.isoformat(), now.isoformat())
    sectors = defaultdict(lambda: {"inquiries": 0, "confirmed_orders": 0, "net_eur": 0.0, "kg_co2e": 0.0, "carbon_covered_lines": 0})
    buyers = defaultdict(lambda: {"orders": 0, "net_eur": 0.0})
    products = defaultdict(float)
    product_names = {}
    categories = Counter()
    missing, covered = 0, 0

    with store.connect() as conn:
        conn.execute("BEGIN")
        events = conn.execute(
            "SELECT buyer_id, event_type, data_json FROM audit_events WHERE julianday(ts) BETWEEN julianday(?) AND julianday(?) "
            "AND event_type IN ('CLIENT_INQUIRY','SEARCH','OFFERS_CHECKED','KITCHEN_PLAN')", window)
        for event in events:
            data = json.loads(event["data_json"])
            if event["event_type"] == "CLIENT_INQUIRY" or "inquiry_seq" not in data:
                sectors[SECTORS.get(event["buyer_id"], "Other")]["inquiries"] += 1
            categories.update(set(data.get("categories") or ()))
        states = dict(conn.execute(
            "SELECT status, count(*) FROM orders WHERE status!='received' "
            "AND julianday(created_at) BETWEEN julianday(?) AND julianday(?) GROUP BY status", window))
        orders = conn.execute(
            "SELECT buyer_id, total_net, lines_json FROM orders WHERE status='confirmed' "
            "AND julianday(created_at) BETWEEN julianday(?) AND julianday(?)", window)
        for order in orders:
            buyer = buyers[order["buyer_id"]]
            buyer["orders"] += 1
            buyer["net_eur"] += order["total_net"]
            sector = sectors[SECTORS.get(order["buyer_id"], "Other")]
            sector["confirmed_orders"] += 1
            sector["net_eur"] += order["total_net"]
            for line in json.loads(order["lines_json"]):
                products[line["product_id"], line["sales_unit"]] += line["quantity"]
                product_names[line["product_id"]] = line.get("name")
                emissions = line.get("estimated_kg_co2e")
                if emissions is None:
                    missing += 1
                else:
                    covered += 1
                    sector["kg_co2e"] += emissions
                    sector["carbon_covered_lines"] += 1

    for sector in sectors.values():
        sector["net_eur"] = round(sector["net_eur"], 2)
        sector["kg_co2e"] = round(sector["kg_co2e"], 2)

    return {
        "period": period, "from": window[0], "to": window[1], "statuses": states,
        "inquiries": sum(sector["inquiries"] for sector in sectors.values()),
        "confirmed_net_eur": round(sum(buyer["net_eur"] for buyer in buyers.values()), 2),
        "estimated_kg_co2e": round(sum(sector["kg_co2e"] for sector in sectors.values()), 2) if covered else None,
        "carbon_covered_lines": covered, "carbon_missing_lines": missing,
        "sectors": dict(sectors), "categories": dict(categories.most_common(8)),
        "buyers": sorted(({"buyer_id": key, **value} for key, value in buyers.items()),
                         key=lambda entry: (-entry["orders"], -entry["net_eur"]))[:8],
        "products": [{"product_id": pid, "name": product_names[pid], "sales_unit": unit, "quantity": round(qty, 4)}
                     for (pid, unit), qty in sorted(products.items(), key=lambda entry: -entry[1])[:8]],
    }
