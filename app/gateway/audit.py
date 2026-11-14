"""Write audit events and render a human-readable timeline for an order.

Event types (data payloads are small and human-meaningful, never secrets):
  SEARCH, OFFERS_CHECKED, QUOTE_CREATED, QUOTE_REJECTED, QUOTE_INVALID, ORDER_RECEIVED, POLICY_EVALUATED,
  APPROVAL_REQUESTED, APPROVAL_GRANTED, APPROVAL_DENIED, ORDER_CONFIRMED, ORDER_REJECTED, ORDER_EXPIRED,
  AIMO_APPROVAL_EVALUATED, AIMO_APPROVAL_RECHECKED, AGENT_RUN
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime

from . import store


inquiry_sequence: ContextVar[int | None] = ContextVar("inquiry_sequence", default=None)


def log(event_type: str, actor: str, data: dict, **ids) -> dict:
    sequence = inquiry_sequence.get()
    if sequence is not None:
        data = {**data, "inquiry_seq": sequence}
    return store.append_event(event_type, actor, data, **ids)


def _summary(ev: dict) -> str:
    d, t = ev["data"], ev["event_type"]
    if t == "CLIENT_INQUIRY":
        return f"{d.get('action', 'lookup')}: {d.get('text', '')}"
    if t == "SEASONAL_DISCOVERY":
        return f"Checked {d['season']} produce for {d['delivery_date']}"
    if t == "KITCHEN_PLAN":
        return f"Planned {d['ingredient_count']} ingredients for {', '.join(d['dishes'])}"
    if t == "FULFILLMENT_STAGE":
        return "Fulfillment advanced to " + d["stage"].replace("_", " ")
    if t == "ORDER_MESSAGE":
        return f"{d['side']} posted a request message"
    if t == "SEARCH":
        return f"searched '{d.get('text', '')}' filters={d.get('filters')} -> {d.get('matches')} matches"
    if t == "OFFERS_CHECKED":
        return f"checked price+availability for {d.get('count')} products for {d.get('delivery_date')}: {d.get('orderable')} orderable, excluded {d.get('excluded')}"
    if t == "QUOTE_CREATED":
        lines = "; ".join(
            f"{(l.get('quantity') or 0):g} {l.get('sales_unit', '')} x {l.get('product_id', '')}"
            f" {l.get('name') or ''} @ €{(l.get('unit_price') or 0):.2f}"
            for l in d.get("lines", [])
        )
        return (
            f"quote total €{(d.get('total_net') or 0):,.2f} net, expires {d.get('expires_at')},"
            f" preview={d.get('decision')} | {lines}"
        )
    if t == "ORDER_RECEIVED":
        return f"order placed from quote {ev.get('quote_id')}. Agent rationale: \"{d.get('agent_rationale', '')}\""
    if t == "POLICY_EVALUATED":
        rules = ", ".join(r["rule_id"] for r in d.get("fired_rules", [])) or "none"
        decision = (d.get("decision") or "unknown").upper()
        return f"mandate {d.get('mandate_id')} -> {decision} (rules fired: {rules}). " + " ".join(d.get("reasons", []))
    if t == "APPROVAL_REQUESTED":
        return f"waiting for a human approver ({d.get('approval_id')})"
    if t in ("AIMO_APPROVAL_EVALUATED", "AIMO_APPROVAL_RECHECKED"):
        evidence = d.get("evidence") or {}  # absent in the buyer view
        subject = "Aimo fulfillment review"
        if d.get("decision"):
            subject += " → " + d["decision"].replace("_", " ")
        if d.get("method") == "gemini":
            subject += " with Gemini 4 Hydrogen"
        elif d.get("method") == "rules_fallback":
            subject += " using verified rules after Gemini was unavailable"
        elif d.get("method") == "rules_after_evidence_change":
            subject += " after warehouse evidence changed during model review"
        if "preparation_minutes" in evidence:
            subject += (f". {evidence['preparation_minutes']} min picking and loading, "
                        f"{evidence['transit_minutes']} min transit, {evidence['margin_minutes']:g} min slack")
        checks = " ".join(rule["message"] for rule in d["checks"])
        source = f" ({evidence['source']} evidence)" if evidence else ""
        return f"{subject}{source}." + (f" {checks}" if checks else "")
    if t in ("APPROVAL_GRANTED", "APPROVAL_DENIED"):
        return f"{'approved' if t == 'APPROVAL_GRANTED' else 'rejected'} by {ev['actor']}" + (f": \"{d.get('comment')}\"" if d.get("comment") else "")
    if t in ("ORDER_CONFIRMED", "ORDER_REJECTED", "ORDER_EXPIRED"):
        return f"order status -> {t.split('_', 1)[1].lower()}" + (f" ({d.get('reason')})" if d.get("reason") else "")
    return ", ".join(f"{k}={v}" for k, v in d.items())


def timeline(order_id: str | None = None, quote_id: str | None = None) -> list[dict]:
    order_row = None
    if order_id:
        order_row = store.fetchone(
            "SELECT quote_id, buyer_id, created_at FROM orders WHERE order_id = ?",
            (order_id,),
        )
        if order_row and not quote_id:
            quote_id = order_row["quote_id"]

    evs = store.events(order_id=order_id, quote_id=quote_id)

    inquiry_seq = next((ev["data"].get("inquiry_seq") for ev in evs if ev["event_type"] == "QUOTE_CREATED"), None)
    if inquiry_seq is not None and order_row:
        rows = store.fetchall(
            "SELECT * FROM audit_events WHERE buyer_id=? AND (seq=? OR (seq>? AND "
            "event_type IN ('SEARCH','OFFERS_CHECKED','KITCHEN_PLAN') AND json_extract(data_json, '$.inquiry_seq')=?)) "
            "ORDER BY seq LIMIT 30", (order_row["buyer_id"], inquiry_seq, inquiry_seq, inquiry_seq))
        evs = sorted(evs + [store._row_event(row) for row in rows], key=lambda event: event["seq"])
    elif order_id and order_row:
        buyer_id = order_row["buyer_id"]
        upper_ts = order_row["created_at"]
        upper_seq = next((ev["seq"] for ev in evs if ev["event_type"] == "ORDER_RECEIVED"), None)
        if upper_seq is None and evs:
            upper_seq = min(ev["seq"] for ev in evs)

        base = (
            "SELECT * FROM audit_events"
            " WHERE buyer_id = ? AND event_type IN ('SEARCH', 'OFFERS_CHECKED')"
            " AND order_id IS NULL AND quote_id IS NULL AND json_extract(data_json, '$.inquiry_seq') IS NULL"
        )
        with store.connect() as conn:
            if upper_seq is not None:
                prev_row = conn.execute(
                    "SELECT MAX(seq) AS prev_seq FROM audit_events"
                    " WHERE buyer_id = ? AND event_type = 'ORDER_RECEIVED' AND seq < ?",
                    (buyer_id, upper_seq),
                ).fetchone()
                prev_seq = prev_row["prev_seq"] if prev_row and prev_row["prev_seq"] is not None else 0
                ctx_rows = conn.execute(
                    f"{base} AND seq > ? AND seq < ? ORDER BY seq DESC LIMIT 30",
                    (buyer_id, prev_seq, upper_seq),
                ).fetchall()
            else:
                prev_order = conn.execute(
                    "SELECT MAX(created_at) AS prev_ts FROM orders"
                    " WHERE buyer_id = ? AND order_id != ? AND created_at < ?",
                    (buyer_id, order_id, upper_ts),
                ).fetchone()
                prev_ts = prev_order["prev_ts"] if prev_order else None
                cond = " AND ts > ? AND ts <= ?" if prev_ts else " AND ts <= ?"
                params = (buyer_id, prev_ts, upper_ts) if prev_ts else (buyer_id, upper_ts)
                ctx_rows = conn.execute(f"{base}{cond} ORDER BY seq DESC LIMIT 30", params).fetchall()

        seen = {ev["seq"] for ev in evs}
        for r in ctx_rows:
            if r["seq"] not in seen:
                evs.append(store._row_event(r))
                seen.add(r["seq"])
        evs.sort(key=lambda ev: ev["seq"])

    for ev in evs:
        ev["summary"] = _summary(ev)
    return evs


def buyer_view(events: list[dict]) -> list[dict]:
    """Copy of a timeline without internal warehouse evidence or the names of Aimo operators."""
    out = []
    for ev in events:
        ev = {**ev, "data": {key: value for key, value in ev["data"].items() if key != "evidence"}}
        if ev["actor"].startswith("admin:"):
            ev["actor"] = "admin"
        ev["summary"] = _summary(ev)
        out.append(ev)
    return out


def render_text(order_id: str, *, events: list[dict] | None = None, chain: dict | None = None) -> str:
    out = [f"Audit timeline for order {order_id}"]
    for ev in timeline(order_id) if events is None else events:
        ts = datetime.fromisoformat(ev["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        out.append(f"  #{ev['seq']:<4} {ts}  {ev['event_type']:<19} {ev['actor']}\n         {ev['summary']}")
    chain = store.verify_chain() if chain is None else chain
    out.append(f"  hash chain: {'OK' if chain['ok'] else 'BROKEN at #' + str(chain['first_bad_seq'])} ({chain['events']} events)")
    return "\n".join(out)
