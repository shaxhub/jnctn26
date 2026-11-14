"""Mandate (buyer rules) + quote lines -> auto | needs_approval | reject.

Rule ids: per_order_limit, weekly_limit, hard_cap, forbidden_allergen, may_contain_allergen,
substitution_preference, unknown_availability, need_mismatch, partial_coverage, mandate_not_valid,
unknown_product. quote_invalid is raised in service.place_order (expired, tampered or stale quote).

Every rule that fires is returned with an id, its effect and a human-readable message, so the
decision is explainable in the UI and in the audit log. Combination: any reject -> reject, else any
needs_approval -> needs_approval, else auto.

TODO(B): price-change tolerance vs. last order, max quantity vs. usual consumption, per-category limits,
         time-of-day rules, approver routing (who must approve what).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import store
from .config import APP_DIR
from .search import normalize_claims
from .models import (ALLERGEN_NAMES, Decision, FiredRule, Mandate, Need, Offer, OrderableReason, PolicyResult,
                     QuoteLine, expand_allergens)

MANDATE_DIR = APP_DIR / "mandates"


def load_mandate(buyer_id: str, directory: Path = MANDATE_DIR) -> Mandate:
    return Mandate.model_validate(json.loads((directory / f"{buyer_id}.json").read_text(encoding="utf-8")))


def hard_cap_total(mandate: Mandate) -> float | None:
    if mandate.hard_cap_order_total is not None:
        return mandate.hard_cap_order_total
    return mandate.max_order_total * 5 if mandate.max_order_total is not None else None


def _names(codes) -> str:
    return ", ".join(f"{c} ({ALLERGEN_NAMES.get(c, '?')})" for c in sorted(codes))


def evaluate(mandate: Mandate, lines: list[QuoteLine], offers: dict[str, Offer], *, total_net: float,
             weekly_spent: float = 0.0, need: Need | None = None, coverage: float | None = None,
             today: date | None = None) -> PolicyResult:
    fired: list[FiredRule] = []

    def fire(rule_id: str, effect: Decision, msg: str) -> None:
        fired.append(FiredRule(rule_id=rule_id, effect=effect, message=msg))

    today = today or store.now().date()
    if not (mandate.issued_at <= today <= mandate.valid_until):
        fire("mandate_not_valid", Decision.reject, f"Mandate {mandate.mandate_id} is valid {mandate.issued_at}..{mandate.valid_until}.")

    if mandate.max_order_total is not None and total_net > mandate.max_order_total:
        fire("per_order_limit", Decision.needs_approval,
             f"Order total €{total_net:,.2f} exceeds the per-order limit €{mandate.max_order_total:,.2f}.")
    if mandate.max_weekly_total is not None and weekly_spent + total_net > mandate.max_weekly_total:
        fire("weekly_limit", Decision.needs_approval,
             f"This week €{weekly_spent:,.2f} + this order €{total_net:,.2f} exceeds the weekly limit €{mandate.max_weekly_total:,.2f}.")

    # hard_cap: absolute ceilings that no human approval can lift through this channel (the
    # "manipulated agent" guard). Going over max_order_total alone only asks for approval.
    cap = hard_cap_total(mandate)
    if cap is not None and total_net > cap:
        fire("hard_cap", Decision.reject, f"Order total €{total_net:,.2f} exceeds the hard ceiling €{cap:,.2f}; refused outright.")
    if need is not None and mandate.max_quantity_multiple:
        covered = sum(l.covers or 0 for l in lines)
        if covered > mandate.max_quantity_multiple * need.quantity:
            fire("hard_cap", Decision.reject, f"Quote covers {covered:g} {need.unit}, more than {mandate.max_quantity_multiple:g}x "
                                              f"the requested {need.quantity:g} {need.unit}.")

    forbidden = set(expand_allergens(mandate.forbidden_allergens))
    for line in lines:
        o = offers.get(line.product_id)
        label = f"{line.product_id} {line.name or ''}".strip()
        if o is None:
            fire("unknown_product", Decision.reject, f"{label}: no offer data.")
            continue
        bad = forbidden & set(o.allergens_contains)
        if bad:
            fire("forbidden_allergen", Decision.reject, f"{label} contains forbidden allergen(s) {_names(bad)}.")
        maybe = forbidden & set(o.allergens_may_contain)
        if maybe and mandate.may_contain_forbidden != "ignore":
            fire("may_contain_allergen", Decision(mandate.may_contain_forbidden),
                 f"{label} may contain {_names(maybe)} (trace warning).")
        if mandate.allowed_categories is not None and not any((o.category or "").startswith(c) for c in mandate.allowed_categories):
            fire("hard_cap", Decision.reject, f"{label}: category {o.category} is not in the mandate's allowed categories.")
        if o.reason == OrderableReason.no_availability_data:
            fire("unknown_availability", Decision(mandate.unknown_availability),
                 f"{label}: Valio returned no availability data for {line.quantity:g} {line.sales_unit}; a human should confirm.")
        if line.is_substitute:
            if mandate.substitution_policy == "always_approval":
                fire("substitution_preference", Decision.needs_approval,
                     f"{label} substitutes the preferred product {line.substitute_for}; every substitution needs approval.")
            elif mandate.substitution_policy == "same_category" and line.substitute_for_category and o.category != line.substitute_for_category:
                fire("substitution_preference", Decision.needs_approval,
                     f"{label} (category {o.category}) substitutes {line.substitute_for} from category {line.substitute_for_category}.")
        if need is not None:
            missing = [c for c in normalize_claims(need.free_from) if c not in o.claims]
            if missing:
                fire("need_mismatch", Decision.needs_approval, f"{label} lacks requested claim(s) {', '.join(missing)}.")
            need_bad = (set(expand_allergens(need.exclude_allergens)) - forbidden) & set(o.allergens_contains)
            if need_bad:
                fire("need_mismatch", Decision.needs_approval,
                     f"{label} contains need-excluded allergen(s) {_names(need_bad)}.")
            name_lower = (o.name or "").lower()
            bad_terms = [t for t in need.exclude_terms if t.lower() in name_lower]
            if bad_terms:
                fire("need_mismatch", Decision.needs_approval,
                     f"{label} name matches excluded term(s) {', '.join(bad_terms)}.")
            if line.covers is None:
                fire("need_mismatch", Decision.needs_approval,
                     f"{label}: unit {line.sales_unit} cannot be converted to requested unit {need.unit}.")

    if need is not None and coverage is not None and coverage < 0.999 and mandate.partial_coverage == "needs_approval":
        fire("partial_coverage", Decision.needs_approval,
             f"Quote covers {coverage:.0%} of the requested {need.quantity:g} {need.unit}.")

    effects = {f.effect for f in fired}
    decision = (Decision.reject if Decision.reject in effects
                else Decision.needs_approval if Decision.needs_approval in effects else Decision.auto)
    reasons = [f.message for f in fired] or ["All mandate rules passed."]
    return PolicyResult(decision=decision, fired_rules=fired, reasons=reasons, mandate_id=mandate.mandate_id)
