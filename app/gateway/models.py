"""Pydantic models shared by the REST API, the MCP tools, the agent and the evals.

Export JSON Schemas (written to app/schemas/):
    uv run python -m gateway.models
"""
from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# --- allergen codes ---------------------------------------------------------------------------
# The data set uses GS1 AllergenTypeCode values. The schema file does NOT define them, so this map
# comes from the GS1 code list; entries marked (?) were inferred from product names and are unverified.
ALLERGEN_NAMES: dict[str, str] = {
    "AC": "crustaceans", "AE": "eggs", "AF": "fish", "AM": "milk", "AN": "tree nuts",
    "AP": "peanuts", "AS": "sesame", "AU": "sulphites", "AW": "cereals containing gluten",
    "AY": "soy", "BC": "celery", "BM": "mustard", "GB": "barley", "GK": "kamut", "GO": "oats",
    "GS": "spelt", "ML": "lactose", "NL": "lupin", "NR": "rye", "SA": "almonds", "SC": "cashews",
    "SH": "hazelnuts", "SM": "macadamia nuts", "SP": "pecans", "SR": "brazil nuts",
    "ST": "pistachios", "SW": "walnuts", "UM": "molluscs", "UW": "wheat",
    "X99": "no declaration-obligatory allergens",
    "BF": "beef (?)", "NC": "cocoa (?)", "NE": "peas (?)", "NK": "coriander (?)", "NM": "maize/corn (?)",
    "NW": "carrot (?)", "PN": "pine nuts (?)", "PO": "pork (?)", "SO": "unknown (?)", "UN": "unknown (?)",
    "ABD": "avocado (?)", "ADQ": "buckwheat (?)", "BP": "bee pollen (?)", "CM": "camel milk (?)", "NP": "poppy seeds (?)",
}
# Friendly groups the agent / mandates can use instead of raw codes.
ALLERGEN_GROUPS: dict[str, list[str]] = {
    "milk": ["AM", "ML"],
    "gluten": ["AW", "UW", "GB", "NR", "GS", "GK"],  # oats (GO) listed separately on purpose
    "oats": ["GO"],
    "nuts": ["AN", "SA", "SC", "SH", "SM", "SP", "SR", "ST", "SW", "PN"],
    "egg": ["AE"], "fish": ["AF"], "soy": ["AY"], "peanut": ["AP"], "sesame": ["AS"],
}
_ALLERGEN_ALIASES: dict[str, list[str]] = {
    "dairy": ["AM", "ML"],
    "eggs": ["AE"],
    "peanuts": ["AP"],
    "tree nuts": ALLERGEN_GROUPS["nuts"],
    "treenuts": ALLERGEN_GROUPS["nuts"],
    "soya": ["AY"],
    "celery": ["BC"],
    "mustard": ["BM"],
    "sulphites": ["AU"],
    "sulfites": ["AU"],
    "lupin": ["NL"],
    "crustaceans": ["AC"],
    "molluscs": ["UM"],
}


def expand_allergens(items: list[str]) -> list[str]:
    out: list[str] = []
    for x in items:
        k = x.strip().lower()
        if not k:
            continue
        if k in ALLERGEN_GROUPS:
            out += ALLERGEN_GROUPS[k]
        elif k in _ALLERGEN_ALIASES:
            out += _ALLERGEN_ALIASES[k]
        else:
            singular = k.rstrip("s")
            if singular in ALLERGEN_GROUPS:
                out += ALLERGEN_GROUPS[singular]
            elif singular in _ALLERGEN_ALIASES:
                out += _ALLERGEN_ALIASES[singular]
            else:
                out.append(x.strip().upper())
    return sorted(set(out))


# --- catalog / search -------------------------------------------------------------------------
class SearchRequest(BaseModel):
    text: str = Field("", description="Free text, matched as a substring of fi/en/sv names and brand (min 3 chars per word).")
    free_from: list[str] = Field(default_factory=list, description="nutritionalClaim ids that must be present, e.g. FREE_FROM_LACTOSE, FREE_FROM_GLUTEN, VEGAN.")
    exclude_allergens: list[str] = Field(default_factory=list, description="Allergen codes (AM, AW...) or groups (milk, gluten, nuts) the product must not CONTAIN.")
    category: str | None = Field(None, description="Category code or prefix, e.g. '10400' (milk) or '104'.")
    labels: list[str] = Field(default_factory=list, description="packagingMarkedLabel ids that must be present, e.g. GOODS_FROM_FINLAND_BLUE_SWAN.")
    exclude_terms: list[str] = Field(default_factory=list, description="Drop products whose name contains any of these words (e.g. kahvi, kaakao).")
    limit: int = Field(20, ge=1, le=100)


class ProductSummary(BaseModel):
    id: str
    name_fi: str | None = None
    name_en: str | None = None
    brand: str | None = None
    vendor: str | None = None
    category: str | None = None
    sales_unit: str
    base_unit: str
    base_units_per_sales_unit: float = 1.0
    volume_l: float | None = Field(None, description="Litres per sales unit (catalog-derived).")
    net_weight_kg: float | None = Field(None, description="Kilograms per sales unit (catalog-derived).")
    allowed_lot_size: float | None = None
    allergens_contains: list[str] = []
    allergens_may_contain: list[str] = []
    claims: list[str] = []
    labels: list[str] = []
    reliability: float | None = None
    co2_per_kg: float | None = None
    substitutes: list[str] = []


class SearchResult(BaseModel):
    results: list[ProductSummary]
    total_matches: int
    category_counts: dict[str, int] = Field(default_factory=dict, description="Matches per category code, to help narrow the search.")


# --- offers -----------------------------------------------------------------------------------
class OrderableReason(str, Enum):
    ok = "ok"
    cutoff_passed = "cutoff_passed"
    no_availability_data = "no_availability_data"
    sales_block = "sales_block"
    insufficient_stock = "insufficient_stock"
    later_date = "later_date"          # earliest availableDate is after the requested date
    no_price = "no_price"


UNLIMITED_THRESHOLD = 999_999  # availableAmount >= this means "effectively unlimited" (Terminal: unknown)


class Offer(BaseModel):
    product_id: str
    name: str | None = None
    brand: str | None = None
    category: str | None = None
    sales_unit: str
    base_unit: str | None = None
    allowed_lot_size: float | None = None
    base_units_per_sales_unit: float = 1.0
    volume_l: float | None = None
    net_weight_kg: float | None = None
    content_per_sales_unit: float | None = Field(None, description="How many L or KG one sales unit contains.")
    content_unit: Literal["L", "KG"] | None = None
    content_source: str | None = Field(None, description="price_api (catalogPrice/comparisonPrice) or catalog.")
    unit_price: float | None = Field(None, description="Net price per sales unit, EUR, without VAT.")
    unit_price_with_tax: float | None = None
    tax_rate: float | None = None
    price_per_content_unit: float | None = Field(None, description="EUR per L or KG without VAT.")
    currency: str = "EUR"
    price_valid_to: datetime | None = None
    net_price_found: bool | None = None
    available_qty: float | None = Field(None, description="Sales units available; None when unlimited or unknown.")
    unlimited: bool = False
    available_date: date | None = None
    closing_time: datetime | None = Field(None, description="Order cutoff for this delivery date.")
    logistic_model: str | None = None
    orderable: bool
    reason: OrderableReason
    reliability: float | None = None
    co2_per_kg: float | None = None
    allergens_contains: list[str] = []
    allergens_may_contain: list[str] = []
    claims: list[str] = []
    labels: list[str] = []
    substitutes: list[str] = []


class OffersRequest(BaseModel):
    product_ids: list[str] = Field(..., min_length=1, max_length=1000)
    delivery_date: date
    quantity: float | None = Field(None, gt=0, description="Optional: needed amount, to also get a plan.")
    unit: str | None = Field(None, description="Unit of quantity: L, KG, PCS or a sales unit code.")


# --- need / plan ------------------------------------------------------------------------------
class Need(BaseModel):
    """What the buyer asked for, in structured form (shown to the user before anything is ordered)."""
    item: str = Field(..., description="Short description, e.g. 'lactose-free milk'.")
    quantity: float = Field(..., gt=0)
    unit: str = Field(..., description="L, KG, PCS (consumer pieces) or a sales unit code such as KI.")
    delivery_date: date
    search_text: str = ""
    category: str | None = None
    free_from: list[str] = []            # nutritionalClaim ids required, e.g. FREE_FROM_LACTOSE
    exclude_allergens: list[str] = []    # codes or groups
    exclude_terms: list[str] = []
    preferred_product_ids: list[str] = []
    allow_partial: bool = True


class PlanLine(BaseModel):
    product_id: str
    name: str | None = None
    category: str | None = None
    quantity: float = Field(..., description="In sales units.")
    sales_unit: str
    covers: float | None = Field(None, description="Amount of the need covered, in need units.")
    unit_price: float
    line_total: float
    closing_time: datetime | None = None
    is_substitute: bool = False
    substitute_for: str | None = None
    note: str | None = None
    co2_per_kg: float | None = None
    reliability: float | None = None


class Plan(BaseModel):
    label: str                           # best / better / good
    strategy: str
    lines: list[PlanLine]
    requested: float
    unit: str
    covered: float
    coverage: float                      # 0..1
    total_net: float
    currency: str = "EUR"
    avg_reliability: float | None = None
    estimated_co2_kg: float | None = None
    notes: list[str] = []


class PlanResult(BaseModel):
    plans: list[Plan]
    excluded: list[dict] = Field(default_factory=list, description="Offers that were not usable, with reason.")


# --- policy -----------------------------------------------------------------------------------
class Decision(str, Enum):
    auto = "auto"
    needs_approval = "needs_approval"
    reject = "reject"


class FiredRule(BaseModel):
    rule_id: str
    effect: Decision
    message: str


class PolicyResult(BaseModel):
    decision: Decision
    fired_rules: list[FiredRule] = []
    reasons: list[str] = []
    mandate_id: str | None = None


# --- quotes / orders --------------------------------------------------------------------------
class LineRequest(BaseModel):
    product_id: str
    quantity: float = Field(..., gt=0, description="In sales units.")


class QuoteRequest(BaseModel):
    delivery_date: date
    lines: list[LineRequest] = Field(..., min_length=1)
    need: Need | None = Field(None, description="Optional original need, so the gateway can check the match.")


class QuoteLine(BaseModel):
    product_id: str
    name: str | None = None
    category: str | None = None
    quantity: float
    sales_unit: str
    unit_price: float
    unit_price_with_tax: float | None = None
    line_total: float
    closing_time: datetime | None = None
    covers: float | None = Field(None, description="Amount of the need covered, in need units.")
    is_substitute: bool = False
    substitute_for: str | None = None
    substitute_for_category: str | None = None


class Quote(BaseModel):
    quote_id: str
    buyer_id: str
    delivery_date: date
    lines: list[QuoteLine]
    total_net: float
    total_gross: float
    currency: str = "EUR"
    created_at: datetime
    expires_at: datetime
    need: Need | None = None
    policy_preview: PolicyResult
    signature: str = Field(..., description="Compact JWS (EdDSA/Ed25519) over the quote payload.")
    warnings: list[str] = []


class OrderRequest(BaseModel):
    quote_id: str
    agent_rationale: str = Field("", description="Why the agent chose this quote; stored in the audit log.")


class OrderStatus(str, Enum):
    confirmed = "confirmed"
    pending_approval = "pending_approval"
    rejected = "rejected"
    expired = "expired"


class Order(BaseModel):
    order_id: str
    quote_id: str
    buyer_id: str
    status: OrderStatus
    total_net: float
    currency: str = "EUR"
    delivery_date: date
    lines: list[QuoteLine]
    policy: PolicyResult
    approval_id: str | None = None
    agent_rationale: str = ""
    created_at: datetime
    updated_at: datetime


class Approval(BaseModel):
    approval_id: str
    order_id: str
    buyer_id: str
    status: Literal["pending", "approved", "rejected"]
    reasons: list[str]
    created_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    comment: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = ""


class AuditEvent(BaseModel):
    seq: int
    ts: datetime
    event_type: str
    actor: str
    buyer_id: str | None = None
    order_id: str | None = None
    quote_id: str | None = None
    data: dict = {}
    prev_hash: str
    hash: str


class Mandate(BaseModel):
    """Rules a buyer organisation issues to its purchasing agent. The gateway enforces them; the
    agent cannot pass or change limits (no tool accepts them)."""
    mandate_id: str
    buyer_id: str
    buyer_name: str
    issued_by: str = Field(..., description="Person/role at the buyer who issued the mandate.")
    issued_at: date
    valid_until: date
    currency: str = "EUR"
    max_order_total: float | None = Field(None, description="Net EUR per order; above -> needs_approval.")
    max_weekly_total: float | None = Field(None, description="Net EUR per ISO week incl. pending orders; above -> needs_approval.")
    hard_cap_order_total: float | None = Field(None, description="Net EUR per order; above -> reject (hard_cap). Default 5x max_order_total.")
    max_quantity_multiple: float | None = Field(5.0, description="Reject (hard_cap) a quote covering more than this multiple of the requested quantity.")
    forbidden_allergens: list[str] = Field(default_factory=list, description="Codes or groups; CONTAINS -> reject, always.")
    may_contain_forbidden: Literal["ignore", "needs_approval", "reject"] = "needs_approval"
    allowed_categories: list[str] | None = Field(None, description="Category code prefixes; null = any.")
    substitution_policy: Literal["allowed", "same_category", "always_approval"] = "same_category"
    unknown_availability: Literal["needs_approval", "reject"] = "needs_approval"
    partial_coverage: Literal["allowed", "needs_approval"] = "needs_approval"
    notes: str = ""


class AgentRunRequest(BaseModel):
    text: str = Field(..., min_length=1)
    mode: Literal["auto", "llm", "scripted"] = "auto"


EXPORTED = [SearchRequest, SearchResult, ProductSummary, OffersRequest, Offer, Need, Plan, PlanResult,
            PolicyResult, Mandate, QuoteRequest, Quote, OrderRequest, Order, Approval, ApprovalDecisionRequest,
            AuditEvent]


def export_schemas() -> list[str]:
    from .config import APP_DIR

    out_dir = APP_DIR / "schemas"
    out_dir.mkdir(exist_ok=True)
    written = []
    for m in EXPORTED:
        path = out_dir / f"{m.__name__}.json"
        path.write_text(json.dumps(m.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
        written.append(path.name)
    return written


if __name__ == "__main__":
    print("\n".join(export_schemas()))
