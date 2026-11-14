"""Client workspace projections and buyer-scoped preferences."""
from collections import Counter, defaultdict
import re

from datetime import date, datetime, timedelta
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from . import audit, quotes, service, store
from .auth import Admin, Principal, require_client
from .config import TZ
from .models import QuoteRequest
from .preferences import Preferences, preferences

router = APIRouter(prefix="/client")
STAGES = ("pending", "registered", "retrieving", "on_delivery", "almost_there", "arrived")


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ShipmentUpdate(BaseModel):
    stage: Literal["retrieving", "on_delivery", "almost_there", "arrived"]


class DraftEdit(BaseModel):
    delivery_date: date
    quantities: dict[str, Annotated[float, Field(gt=0, le=1_000_000, allow_inf_nan=False)]] = Field(min_length=1, max_length=1000)


@router.get("/settings")
def get_settings(p: Principal = Depends(require_client)):
    return preferences(p.buyer_id)


@router.post("/settings")
def save_settings(value: Preferences, p: Principal = Depends(require_client)):
    store.execute("INSERT INTO workspace_preferences VALUES (?,?) ON CONFLICT(buyer_id) "
                  "DO UPDATE SET settings_json=excluded.settings_json", (p.buyer_id, value.model_dump_json()))
    return value


def ticket_activity(order, *, with_messages: bool = True) -> dict:
    events = store.fetchall("SELECT * FROM audit_events WHERE order_id=? "
                            "AND event_type IN ('ORDER_CONFIRMED','FULFILLMENT_STAGE') ORDER BY seq", (order.order_id,))
    stages = [{"stage": "pending", "at": order.created_at.isoformat()}]
    for row in events:
        event = store._row_event(row)
        if event["event_type"] == "ORDER_CONFIRMED":
            stages.append({"stage": "registered", "at": event["ts"]})
        elif event["event_type"] == "FULFILLMENT_STAGE":
            stages.append({"stage": event["data"]["stage"], "at": event["ts"]})
    messages = []
    if with_messages:
        message_rows = store.fetchall("SELECT ts,data_json FROM audit_events WHERE order_id=? AND event_type='ORDER_MESSAGE' "
                                      "ORDER BY seq DESC LIMIT 100", (order.order_id,))
        messages = [{**json.loads(row["data_json"]), "at": row["ts"]} for row in reversed(message_rows)]
    if order.status == "confirmed" and stages[-1]["stage"] == "pending":
        stages.append({"stage": "registered", "at": order.updated_at.isoformat()})
    return {"stage": order.status if order.status in {"expired", "rejected"} else stages[-1]["stage"],
            "stages": stages, "messages": messages}


def advance(admin: Admin, order_id: str, update: ShipmentUpdate) -> dict:
    order = service.get_order(admin, order_id)
    if order.status != "confirmed":
        raise service.GatewayError(409, "Register the order before updating fulfillment")
    with store.transaction() as conn:
        row = conn.execute("SELECT data_json FROM audit_events WHERE order_id=? AND event_type='FULFILLMENT_STAGE' "
                           "ORDER BY seq DESC LIMIT 1", (order_id,)).fetchone()
        current = json.loads(row["data_json"])["stage"] if row else "registered"
        if STAGES.index(update.stage) != STAGES.index(current) + 1:
            raise service.GatewayError(409, "Refresh the request and choose its next stage")
        store.append_in_transaction(conn, "FULFILLMENT_STAGE", admin.actor, update.model_dump(),
                                    buyer_id=order.buyer_id, order_id=order_id, quote_id=order.quote_id)
    return ticket_activity(order)


def send_message(actor: Principal | Admin, order_id: str, message: Message) -> dict:
    order = service.get_order(actor, order_id)
    content = message.text.strip()
    if not content:
        raise service.GatewayError(422, "Enter a message")
    with store.transaction() as conn:
        store.append_in_transaction(conn, "ORDER_MESSAGE", actor.actor,
            {"side": "aimo" if isinstance(actor, Admin) else "agent" if actor.role == "agent" else "client", "text": content},
            buyer_id=order.buyer_id, order_id=order_id, quote_id=order.quote_id)
    return ticket_activity(order)


@router.get("/requests")
def requests(p: Principal = Depends(require_client), offset: int = Query(0, ge=0)):
    service.expire_pending(buyer_id=p.buyer_id)
    rows = store.fetchall("SELECT * FROM orders WHERE buyer_id=? AND status!='received' "
                         "ORDER BY created_at DESC, order_id DESC LIMIT 31 OFFSET ?", (p.buyer_id, offset))
    orders = [service._order_from_row(row) for row in rows[:30]]
    return {"requests": [{"order": order, "stage": ticket_activity(order, with_messages=False)["stage"]} for order in orders],
            "next_offset": offset + 30 if len(rows) > 30 else None}


@router.get("/requests/{order_id}")
def request_detail(order_id: str, p: Principal = Depends(require_client)):
    order = service.get_order(p, order_id)
    return {"order": order, **ticket_activity(order)}


def _buyer_event(event: dict) -> dict:
    """Outcome-level view of an audit event, without warehouse evidence or operator names."""
    data, kind = event["data"], event["event_type"]
    status = kind.split("_", 1)[1].lower() if kind in ("ORDER_CONFIRMED", "ORDER_REJECTED", "ORDER_EXPIRED") else None
    outcome = {"decision": data.get("decision"), "status": status,
               "rules": [rule["rule_id"] for rule in data.get("fired_rules") or data.get("checks") or []]}
    return {"event_type": kind, "ts": event["ts"], "actor": event["actor"].split(":", 1)[0],
            "data": {key: value for key, value in outcome.items() if value}}


@router.get("/requests/{order_id}/audit")
def request_audit(order_id: str, p: Principal = Depends(require_client)):
    service.get_order(p, order_id)  # ownership check
    return {"order_id": order_id, "events": [_buyer_event(event) for event in audit.timeline(order_id)]}


@router.post("/requests/{order_id}/messages")
def post_message(order_id: str, body: Message, p: Principal = Depends(require_client)):
    return send_message(p, order_id, body)


def _draft(p: Principal, quote_id: str) -> dict:
    row = store.fetchone("SELECT jws FROM quotes WHERE quote_id=? AND buyer_id=? AND status='open' "
                         "AND json_extract(payload_json,'$.order_channel')='client'", (quote_id, p.buyer_id))
    if not row:
        raise service.GatewayError(404, "Draft not found")
    payload = quotes.verify(row["jws"])
    event = store.fetchone("SELECT data_json FROM audit_events WHERE quote_id=? AND event_type='QUOTE_CREATED' "
                           "ORDER BY seq DESC LIMIT 1", (quote_id,))
    evidence = json.loads(event["data_json"]) if event else {}
    return {**payload, "signature": row["jws"], "warnings": evidence.get("warnings", []),
            "policy_preview": evidence.get("policy_preview", {"reasons": [], "decision": evidence.get("decision")})}


@router.get("/drafts")
def drafts(p: Principal = Depends(require_client)):
    rows = store.fetchall("SELECT quote_id FROM quotes WHERE buyer_id=? AND status='open' "
                          "AND json_extract(payload_json,'$.order_channel')='client' "
                          "ORDER BY created_at DESC LIMIT 100", (p.buyer_id,))
    result = []
    for row in rows:
        try:
            result.append(_draft(p, row["quote_id"]))
        except service.GatewayError as exc:
            if exc.status != 404:
                raise
    return result


@router.post("/drafts/{quote_id}/edit")
def edit_draft(quote_id: str, body: DraftEdit, p: Principal = Depends(require_client)):
    old = _draft(p, quote_id)
    original_ids = {line["product_id"] for line in old["lines"]}
    if not body.quantities.keys() <= original_ids:
        raise service.GatewayError(422, "Use product search to add a new product")
    if body.delivery_date < store.now().date():
        raise service.GatewayError(422, "Choose a current or future delivery date")
    need = old.get("need")
    if need:
        need["delivery_date"] = body.delivery_date.isoformat()
    fresh = service.create_quote(p, QuoteRequest(delivery_date=body.delivery_date, need=need,
        exclude_allergens=old.get("exclude_allergens", []), required_claims=old.get("required_claims", []),
        lines=[{"product_id": sku, "quantity": quantity} for sku, quantity in body.quantities.items()]),
        supersedes=quote_id)
    return fresh


@router.get("/dashboard")
def dashboard(p: Principal = Depends(require_client)):
    service.expire_pending(buyer_id=p.buyer_id)
    rows = store.fetchall("SELECT * FROM orders WHERE buyer_id=? AND status!='received'", (p.buyer_id,))
    stages = Counter(ticket_activity(service._order_from_row(row), with_messages=False)["stage"] for row in rows)
    saved = store.fetchone("SELECT count(*) total FROM quotes WHERE buyer_id=? AND status='open' "
                           "AND json_extract(payload_json,'$.order_channel')='client'", (p.buyer_id,))
    return {"drafts": saved["total"], "submitted": len(rows), "stages": stages}


@router.get("/analytics")
def analytics(p: Principal = Depends(require_client), year: int | None = Query(None, ge=2000, le=9998)):
    year = year or store.now().year
    orders = store.fetchall("SELECT * FROM orders WHERE buyer_id=? AND status='confirmed' "
                            "AND delivery_date>=? AND delivery_date<?",
                            (p.buyer_id, f"{year}-01-01", f"{year+1}-01-01"))
    timeline = [{"month": month, "orders": 0, "net": 0.0, "checked": 0, "available": 0}
                for month in range(1, 13)]
    products, durations = Counter(), defaultdict(list)
    availability = defaultdict(lambda: [{"month": month, "checked": 0, "available": 0} for month in range(1, 13)])
    for row in orders:
        order = service._order_from_row(row)
        bucket = timeline[order.delivery_date.month - 1]
        bucket["orders"] += 1
        bucket["net"] += order.total_net
        for line in order.lines:
            products[(line.product_id, line.name, line.sales_unit)] += line.quantity
        stages = ticket_activity(order, with_messages=False)["stages"]
        if stages[-1]["stage"] == "arrived":
            elapsed = datetime.fromisoformat(stages[-1]["at"]) - datetime.fromisoformat(stages[0]["at"])
            if elapsed.total_seconds() >= 0:
                durations["end_to_end"].append(elapsed.total_seconds() / 3600)
        for before, after in zip(stages, stages[1:]):
            hours = (datetime.fromisoformat(after["at"]) - datetime.fromisoformat(before["at"])).total_seconds() / 3600
            if hours >= 0:
                durations[after["stage"]].append(hours)
    events = store.fetchall("SELECT ts,data_json FROM audit_events WHERE buyer_id=? AND event_type='OFFERS_CHECKED' "
                            "AND ts>=? AND ts<?", (p.buyer_id, f"{year}-01-01", f"{year+1}-01-01"))
    for event in events:
        values = json.loads(event["data_json"])
        bucket = timeline[datetime.fromisoformat(event["ts"]).astimezone(TZ).month - 1]
        bucket["checked"] += values.get("count", 0)
        bucket["available"] += values.get("orderable", 0)
        available_ids = set(values.get("orderable_product_ids", []))
        for sku in set(values.get("observed_product_ids", [])):
            point = availability[sku][bucket["month"]-1]
            point["checked"] += 1
            point["available"] += sku in available_ids
    ranked_skus = sorted(availability, key=lambda sku: (-sum(point["checked"] for point in availability[sku]), sku))
    return {"year": year, "months": timeline, "availability_by_sku": {sku: availability[sku] for sku in ranked_skus[:20]},
            "stage_hours": {stage: {"average": round(sum(values)/len(values), 2), "samples": len(values)}
                            for stage, values in durations.items()},
            "products": [{"id": sku, "name": name, "unit": unit, "quantity": count}
                         for (sku, name, unit), count in products.most_common(10)]}


@router.get("/reminders")
def reminders(p: Principal = Depends(require_client)):
    settings = preferences(p.buyer_id)
    now = store.now().astimezone(TZ)
    if not settings.recurring_prompt:
        return {"reminder": None}
    if now.strftime("%H:%M") < settings.recurring_time:
        return {"reminder": None}
    return {"reminder": {"text": settings.recurring_prompt, "delivery_date": (now.date()+timedelta(days=1)).isoformat()}}


class HelperPrompt(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/drafts/{quote_id}/help")
async def help_draft(quote_id: str, body: HelperPrompt, p: Principal = Depends(require_client)):
    from . import gemini

    draft = _draft(p, quote_id)
    current = {line["product_id"]: line["quantity"] for line in draft["lines"]}
    if gemini.enabled():
        try:
            proposal = await gemini.suggest_edit(body.text, draft)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise service.GatewayError(502, "Gemini did not return a valid edit. Enter the changes directly.") from exc
        if not proposal.quantities.keys() <= current.keys():
            raise service.GatewayError(422, "Use product search to add a new product")
        return proposal
    match = re.fullmatch(r"(?:set )?([A-Za-z0-9_-]+) (?:to )?([0-9]+(?:[.,][0-9]+)?)", body.text.strip(), re.I)
    if not match or match[1] not in current:
        raise service.GatewayError(422, "Enter a change such as Set 464306 to 12, or edit the values directly.")
    current[match[1]] = float(match[2].replace(",", "."))
    return DraftEdit(delivery_date=draft["delivery_date"], quantities=current)
