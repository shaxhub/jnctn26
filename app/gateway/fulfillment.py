"""Warehouse evidence and deterministic feasibility checks for Aimo approvals."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import ceil
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from . import store
from .config import TZ, demo_catalog_enabled
from .models import Decision, FiredRule, QuoteLine

GEMINI_CONCERNS = {
    "fulfillment_margin": "The approval agent flagged a timing risk. Verify the dispatch and delivery margins.",
    "combined_handling": "The approval agent flagged combined handling requirements. Verify loading and transport capacity.",
    "evidence_inconsistency": "The approval agent flagged inconsistent warehouse evidence. Verify the recorded facts.",
}


def enabled() -> bool:
    return os.getenv("AIMO_FULFILLMENT_CHECKS", "1") != "0"


class Lot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, allow_inf_nan=False, le=1e9)
    date_mark: Literal["best_before", "use_by", "none"]
    marked_date: date | None = None

    @model_validator(mode="after")
    def matching_date(self) -> Lot:
        if (self.date_mark == "none") != (self.marked_date is None):
            raise ValueError("A dated lot must supply its date. Use none for stock without a date mark.")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = Field(min_length=1, max_length=12)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    dispatch_by: AwareDatetime
    deliver_by: AwareDatetime
    pick_setup_minutes: int = Field(ge=0, le=1440)
    pick_units_per_minute: float = Field(gt=0, allow_inf_nan=False, ge=0.01, le=1e6)
    load_minutes: int = Field(ge=0, le=1440)
    transit_minutes: int = Field(gt=0, le=2880)
    route_capacity_available: bool
    handling: Literal["ambient", "chilled", "frozen", "special"]
    handling_ready: bool
    minimum_shelf_life_days: int = Field(ge=0, le=365)
    lots: list[Lot] = Field(max_length=500)

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Evidence:
        if not self.observed_at < self.valid_until <= self.deliver_by or not self.observed_at < self.dispatch_by < self.deliver_by:
            raise ValueError("Evidence validity and dispatch must end after observation and by delivery.")
        if len({lot.lot_id for lot in self.lots}) != len(self.lots):
            raise ValueError("Lot IDs must be unique within a snapshot.")
        return self


def save(product_id: str, delivery: date, evidence: Evidence) -> None:
    if evidence.deliver_by.astimezone(TZ).date() != delivery:
        raise ValueError("The delivery deadline must match the requested date in Helsinki.")
    with store.transaction() as conn:
        current = conn.execute(
            "SELECT evidence_json FROM fulfillment_evidence WHERE product_id=? AND delivery_date=?",
            (product_id, delivery.isoformat()),
        ).fetchone()
        if current and Evidence.model_validate_json(current["evidence_json"]).observed_at > evidence.observed_at:
            raise ValueError("The warehouse snapshot is older than the recorded evidence.")
        conn.execute("INSERT INTO fulfillment_evidence VALUES (?,?,?) ON CONFLICT(delivery_date,product_id) "
                     "DO UPDATE SET evidence_json=excluded.evidence_json",
                     (delivery.isoformat(), product_id, evidence.model_dump_json()))


def _demo(ids: list[str], delivery: date, now: datetime) -> dict[str, Evidence]:
    from .demo_catalog import ITEMS

    arrival = datetime.combine(delivery, time(21), TZ)
    dispatch = arrival - timedelta(hours=1)
    if now >= dispatch:
        return {}
    return {sku: Evidence(
        unit=unit, observed_at=now, valid_until=min(now + timedelta(hours=1), dispatch),
        dispatch_by=dispatch, deliver_by=arrival, pick_setup_minutes=5, pick_units_per_minute=20,
        load_minutes=4, transit_minutes=35, route_capacity_available=True,
        handling="chilled" if sku in {"490001", "490002"} else "ambient", handling_ready=True,
        minimum_shelf_life_days=2,
        lots=[Lot(lot_id="synthetic", quantity=stock, date_mark="best_before", marked_date=delivery + timedelta(days=5))],
    ) for sku, _, _, _, unit, _, _, stock in ITEMS if sku in ids}


def assess(lines: list[QuoteLine], delivery: date, now: datetime, *, conn=None) -> tuple[dict, list[FiredRule]]:
    by_product = defaultdict(list)
    for line in lines:
        by_product[line.product_id].append(line)
    ids = list(by_product)
    if demo_catalog_enabled():
        sources, source = _demo(ids, delivery, now), "synthetic"
    else:
        rows = (conn.execute if conn is not None else store.fetchall)(
            "SELECT product_id, evidence_json FROM fulfillment_evidence WHERE delivery_date=? "
            "AND product_id IN (SELECT value FROM json_each(?))", (delivery.isoformat(), store.canonical(ids)),
        )
        sources = {row["product_id"]: Evidence.model_validate_json(row["evidence_json"]) for row in rows}
        source = "warehouse"
    rules = []
    facts = []
    prep = 0
    known = []

    def flag(code: str, message: str, effect: Decision = Decision.needs_approval) -> None:
        rules.append(FiredRule(rule_id=code, effect=effect, message=message))

    for sku, entries in by_product.items():
        required = sum(line.quantity for line in entries)
        evidence = sources.get(sku)
        if evidence is None or not evidence.observed_at <= now < evidence.valid_until:
            flag("warehouse_evidence_missing", f"{sku}: current warehouse evidence is unavailable.")
            continue
        if any(line.sales_unit != evidence.unit for line in entries):
            flag("warehouse_unit_mismatch", f"{sku}: warehouse evidence uses a different sales unit.")
            continue
        eligible = [
            lot for lot in evidence.lots
            if ((lot.marked_date - delivery).days >= evidence.minimum_shelf_life_days if lot.marked_date is not None
                else evidence.minimum_shelf_life_days == 0)
        ]
        available = sum(lot.quantity for lot in eligible)
        if available + 1e-9 < required:
            flag("warehouse_shelf_life", f"{sku}: only {available:g} {evidence.unit} meet shelf-life requirements.",
                 Decision.reject)
        if not evidence.route_capacity_available or not evidence.handling_ready:
            flag("warehouse_capacity", f"{sku}: route capacity or {evidence.handling} handling needs confirmation.")
        minutes = evidence.pick_setup_minutes + ceil(required / evidence.pick_units_per_minute) + evidence.load_minutes
        prep += minutes
        known.append(evidence)
        facts.append({"product_id": sku, "required": required, "unit": evidence.unit, "eligible_quantity": available,
                      "earliest_eligible_date_mark": min((lot.marked_date.isoformat() for lot in eligible if lot.marked_date), default=None),
                      "minimum_shelf_life_days": evidence.minimum_shelf_life_days, "handling": evidence.handling,
                      "capacity_available": evidence.route_capacity_available, "handling_ready": evidence.handling_ready,
                      "preparation_minutes": minutes, "transit_minutes": evidence.transit_minutes,
                      "observed_at": evidence.observed_at.isoformat(), "valid_until": evidence.valid_until.isoformat()})
    timing = {}
    if known:
        transit = max(evidence.transit_minutes for evidence in known)
        dispatch = min(evidence.dispatch_by for evidence in known)
        deadline = min(evidence.deliver_by for evidence in known)
        # Serial preparation and the slowest quoted route give a conservative bound.
        margin = min((dispatch - now).total_seconds() / 60 - prep,
                     (deadline - now).total_seconds() / 60 - prep - transit)
        timing = {"preparation_minutes": prep, "transit_minutes": transit,
                  "dispatch_by": dispatch.isoformat(), "deliver_by": deadline.isoformat(),
                  "margin_minutes": round(margin, 1)}
        if margin < 0:
            flag("warehouse_timing", "Picking, loading or transport cannot meet the recorded deadlines.", Decision.reject)
        elif margin < 15:
            flag("warehouse_timing_margin", "The dispatch or delivery deadline has less than 15 minutes of slack.")
    return {"source": source, "delivery_date": delivery.isoformat(), "lines": facts, **timing}, rules
