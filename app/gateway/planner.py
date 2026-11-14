"""Need + offers -> ranked plans in sales units.

Simple greedy heuristic (on purpose, for the scaffold):
1. Filter offers: orderable, unit-compatible with the need, matching the need's hard constraints.
2. For each strategy, sort usable offers by its key and fill the need greedily, capping each line
   at the available stock (so limited stock splits across products).
3. Return up to three distinct plans labelled best / better / good.

TODO(B): smarter optimisation (fewest lines, avoid tiny remainder lines, pack-size fit,
         prefer the buyer's usual products, CO2 budget, delivery reliability thresholds).
"""
from __future__ import annotations

import math
from typing import Callable

from .models import Mandate, Need, Offer, Plan, PlanLine, PlanResult, expand_allergens
from .search import normalize_claims

DEFAULT_RELIABILITY = 0.95  # assumed when the reliability CSV has no row for a product


def amount_per_sales_unit(offer: Offer, unit: str) -> float | None:
    """How much of the need (in `unit`) one sales unit of this offer covers."""
    u = unit.upper()
    if u in ("L", "KG"):
        if offer.content_unit == u and offer.content_per_sales_unit is not None:
            return offer.content_per_sales_unit
        return getattr(offer, "volume_l", None) if u == "L" else getattr(offer, "net_weight_kg", None)
    if u in ("PCS", "ST", "KPL"):
        if getattr(offer, "base_unit", None) in ("KG", "L", "LTR", "KGM"):
            return None
        return offer.base_units_per_sales_unit or 1.0
    if u == offer.sales_unit:
        return 1.0
    return None


def round_qty(qty: float, offer: Offer, up: bool = True) -> float:
    """Round a sales-unit quantity to what can actually be ordered (allowedLotSize; integers for packs)."""
    lot = offer.allowed_lot_size or 1.0
    if offer.sales_unit != "KG" and lot < 1:
        lot = 1.0  # boxes and pieces are ordered whole
    f = math.ceil if up else math.floor
    return round(f(round(qty / lot, 6)) * lot, 4)


def constraint_violations(offer: Offer, need: Need) -> list[str]:
    problems = []
    for claim in normalize_claims(need.free_from):
        if claim not in offer.claims:
            problems.append(f"missing claim {claim}")
    bad = set(expand_allergens(need.exclude_allergens)) & set(offer.allergens_contains)
    if bad:
        problems.append(f"contains {','.join(sorted(bad))}")
    name = (offer.name or "").lower()
    for term in need.exclude_terms:
        if term.lower() in name:
            problems.append(f"name contains '{term}'")
    return problems


def _price_per_need_unit(o: Offer, unit: str) -> float:
    a = amount_per_sales_unit(o, unit)
    return (o.unit_price if o.unit_price is not None else 1e9) / a if a else 1e9


def _strategies(need: Need) -> list[tuple[str, str, Callable[[Offer], tuple]]]:
    pref = set(need.preferred_product_ids)

    def balanced(o: Offer):
        rel = o.reliability if o.reliability is not None else DEFAULT_RELIABILITY
        stock_bonus = 0.97 if o.logistic_model == "Stock" else 1.0
        co2_factor = 1 + min((o.co2_per_kg or 0.0) * 0.01, 0.05)
        return (o.product_id not in pref,
                _price_per_need_unit(o, need.unit) * (1 + (1 - rel)) * stock_bonus * co2_factor,
                o.co2_per_kg if o.co2_per_kg is not None else 1e9)

    def cheapest(o: Offer):
        return (o.product_id not in pref, _price_per_need_unit(o, need.unit))

    def reliable(o: Offer):
        rel = o.reliability if o.reliability is not None else DEFAULT_RELIABILITY
        return (o.product_id not in pref, o.logistic_model != "Stock", -rel, not o.unlimited,
                _price_per_need_unit(o, need.unit))

    return [("best", "balanced: price per unit adjusted for delivery reliability and CO2, stock items preferred", balanced),
            ("better", "lowest price per unit", cheapest),
            ("good", "most reliable: stocked items with the best delivery record", reliable)]


def _fill(need: Need, offers: list[Offer], label: str, strategy: str, key) -> Plan:
    remaining = need.quantity
    lines: list[PlanLine] = []
    pref = need.preferred_product_ids
    by_id = {o.product_id: o for o in offers}
    has_line_co2 = "co2_per_kg" in PlanLine.model_fields
    has_line_rel = "reliability" in PlanLine.model_fields
    for o in sorted(offers, key=key):
        if remaining <= 1e-9:
            break
        per = amount_per_sales_unit(o, need.unit)
        qty = round_qty(remaining / per, o)
        note = None
        if o.available_qty is not None and qty > o.available_qty:
            qty = round_qty(o.available_qty, o, up=False)
            note = f"limited stock: {o.available_qty:g} {o.sales_unit} available"
        if qty <= 0:
            continue
        covers = round(qty * per, 3)
        remaining -= covers
        is_sub = bool(pref) and o.product_id not in pref
        line_kw: dict = {}
        if has_line_co2:
            line_kw["co2_per_kg"] = o.co2_per_kg
        if has_line_rel:
            line_kw["reliability"] = o.reliability
        lines.append(PlanLine(
            product_id=o.product_id, name=o.name, category=o.category, quantity=qty, sales_unit=o.sales_unit,
            covers=covers, unit_price=o.unit_price, line_total=round(qty * o.unit_price, 2),
            closing_time=o.closing_time, is_substitute=is_sub, substitute_for=pref[0] if is_sub else None,
            note=note, **line_kw))
    covered = round(sum(l.covers or 0 for l in lines), 3)
    notes = []
    if covered + 1e-9 < need.quantity:
        notes.append(f"partial: only {covered:g} of {need.quantity:g} {need.unit} can be delivered on {need.delivery_date}")
    if len(lines) > 1:
        notes.append(f"split across {len(lines)} products")
    rel_pairs = [(by_id[l.product_id].reliability, l.covers or l.quantity)
                 for l in lines if by_id[l.product_id].reliability is not None]
    rel_weight = sum(w for _, w in rel_pairs)
    avg_rel = round(sum(r * w for r, w in rel_pairs) / rel_weight, 4) if rel_pairs and rel_weight > 0 else None
    co2_parts = []
    for l in lines:
        off = by_id[l.product_id]
        if off.co2_per_kg is None:
            continue
        kg_per_unit = getattr(off, "net_weight_kg", None)
        if kg_per_unit is None and off.content_unit in ("KG", "L"):
            kg_per_unit = off.content_per_sales_unit
        if kg_per_unit:
            co2_parts.append(l.quantity * kg_per_unit * off.co2_per_kg)
    est_co2 = round(sum(co2_parts), 2) if co2_parts else None
    plan_kw: dict = {}
    if "avg_reliability" in Plan.model_fields:
        plan_kw["avg_reliability"] = avg_rel
    if "estimated_co2_kg" in Plan.model_fields:
        plan_kw["estimated_co2_kg"] = est_co2
    return Plan(label=label, strategy=strategy, lines=lines, requested=need.quantity, unit=need.unit,
                covered=covered, coverage=round(min(covered / need.quantity, 1.0), 4),
                total_net=round(sum(l.line_total for l in lines), 2), notes=notes, **plan_kw)


def make_plans(need: Need, offers: list[Offer], mandate: Mandate | None = None) -> PlanResult:
    usable, excluded = [], []
    for o in offers:
        if not o.orderable:
            excluded.append({"product_id": o.product_id, "name": o.name, "reason": o.reason.value,
                             "closing_time": o.closing_time.isoformat() if o.closing_time else None,
                             "available_date": o.available_date.isoformat() if o.available_date else None})
            continue
        if amount_per_sales_unit(o, need.unit) is None:
            excluded.append({"product_id": o.product_id, "name": o.name, "reason": f"unit_mismatch ({need.unit})"})
            continue
        problems = constraint_violations(o, need)
        if problems:
            excluded.append({"product_id": o.product_id, "name": o.name, "reason": "; ".join(problems)})
            continue
        usable.append(o)

    if mandate is not None and usable:
        forbidden = set(expand_allergens(mandate.forbidden_allergens))
        safe_usable, unsafe = [], []
        for o in usable:
            reasons = []
            bad = forbidden & set(o.allergens_contains)
            if bad:
                reasons.append(f"mandate_forbidden ({','.join(sorted(bad))})")
            if mandate.allowed_categories is not None and not any((o.category or "").startswith(c) for c in mandate.allowed_categories):
                reasons.append(f"mandate_category ({o.category})")
            if reasons:
                unsafe.append((o, "; ".join(reasons)))
            else:
                safe_usable.append(o)
        if safe_usable:
            for o, reason in unsafe:
                excluded.append({"product_id": o.product_id, "name": o.name, "reason": reason})
            usable = safe_usable

    plans: list[Plan] = []
    seen = set()
    if usable:
        for label, strategy, key in _strategies(need):
            plan = _fill(need, usable, label, strategy, key)
            if not need.allow_partial and plan.coverage < 0.999:
                continue
            sig = tuple((l.product_id, l.quantity) for l in plan.lines)
            if sig in seen:
                continue
            seen.add(sig)
            plans.append(plan)
    # relabel so the list always reads best, better, good in order
    for plan, label in zip(plans, ["best", "better", "good"]):
        plan.label = label
    return PlanResult(plans=plans, excluded=excluded)
