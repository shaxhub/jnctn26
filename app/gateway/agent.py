"""Buyer-side purchasing agent.

    uv run python -m gateway.agent "I need 1,000 litres of lactose-free milk by Monday" --buyer hotel
    uv run python -m gateway.agent "..." --buyer hotel --mode scripted     # no LLM, deterministic

Two modes, same gateway calls and the same audit trail:
- scripted: regex parser -> Need -> search -> offers+plan -> quote(best plan) -> order. No API key needed.
- llm: Claude (claude-opus-5-5) parses the request into a Need (structured output), then drives the
  gateway tools through the Anthropic SDK tool runner and explains the result.

Tools run IN-PROCESS (direct calls into gateway.service) for now. To exercise the real MCP endpoint
instead, see `run_llm_via_mcp_connector` below: it points the Claude API MCP connector at a publicly
hosted /mcp URL (Claude's servers must be able to reach it, so localhost will not work).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from . import audit, service
from .auth import Principal, principal_for_key
from .config import settings
from .models import LineRequest, Need, OffersRequest, QuoteRequest, SearchRequest
from .store import now as store_now

MODEL = settings.agent_model  # claude-opus-5-5
FALLBACK_BETA = "server-side-fallback-2026-07-01"   # server-side refusal fallbacks ("default" routing)
MCP_CONNECTOR_BETA = "mcp-client-2025-11-20"

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "maanantai": 0, "tiistai": 1, "keskiviikko": 2, "torstai": 3, "perjantai": 4, "lauantai": 5, "sunnuntai": 6}

# keyword -> (search text, category prefix, exclude terms), matched longest-key-first.
ITEM_HINTS = {
    "cooking cream": ("ruokakerma", None, []),
    "oat drink": ("kaurajuoma", None, []),
    "oat milk": ("kaurajuoma", None, []),
    "kaurajuoma": ("kaurajuoma", None, []),
    "buttermilk": ("piimä", None, []),
    "yoghurt": ("jogurtti", None, []),
    "yogurt": ("jogurtti", None, []),
    "cheese": ("juusto", None, []),
    "butter": ("voi", None, ["voileipä"]),
    "quark": ("rahka", None, []),
    "piimä": ("piimä", None, []),
    "maito": ("maito", "10400", ["kahvi", "latte", "piimä", "kaakao", "jogurt", "soygurt"]),
    "cream": ("kerma", None, []),
    "potato": ("peruna", None, []),
    "tomato": ("tomaatti", None, []),
    "carrot": ("porkkana", None, []),
    "onion": ("sipuli", None, []),
    "apple": ("omena", None, []),
    "lemon": ("sitruuna", None, []),
    "basil": ("basilika", None, []),
    "bread": ("leipä", None, []),
    "milk": ("maito", "10400", ["kahvi", "latte", "piimä", "kaakao", "jogurt", "soygurt"]),
}
CLAIM_WORDS = {"lactose-free": "FREE_FROM_LACTOSE", "lactose free": "FREE_FROM_LACTOSE", "laktoositon": "FREE_FROM_LACTOSE",
               "gluten-free": "FREE_FROM_GLUTEN", "gluten free": "FREE_FROM_GLUTEN", "gluteeniton": "FREE_FROM_GLUTEN",
               "vegan": "VEGAN"}
UNIT_WORDS = {"l": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L", "litraa": "L",
              "dl": "L", "cl": "L", "ml": "L",
              "kg": "KG", "kilo": "KG", "kilos": "KG", "kilograms": "KG", "g": "KG",
              "pcs": "PCS", "pieces": "PCS", "kpl": "PCS", "boxes": "KI", "box": "KI"}
UNIT_SCALE = {"dl": 0.1, "cl": 0.01, "ml": 0.001, "g": 0.001}
_UNIT_RE = re.compile(
    r"(\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*("
    + "|".join(sorted(UNIT_WORDS, key=len, reverse=True))
    + r")\b"
)


def _parse_number(raw: str) -> float:
    s = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    return float(s)


def next_weekday(weekday: int, today: date) -> date:
    days = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


# --- need parsing ------------------------------------------------------------------------------
def parse_need_heuristic(text: str, today: date | None = None) -> Need:
    """Deterministic fallback parser. Good enough for the demo scenarios, not for real users."""
    today = today or store_now().date()
    t = text.lower()
    m = _UNIT_RE.search(t)
    if m:
        raw_unit = m.group(2)
        qty = round(_parse_number(m.group(1)) * UNIT_SCALE.get(raw_unit, 1.0), 6)
        unit = UNIT_WORDS.get(raw_unit, "PCS")
    else:
        qty, unit = 1.0, "PCS"
    m_date = re.search(r"\d{4}-\d{2}-\d{2}", t)
    delivery: date | None = None
    if m_date:
        try:
            delivery = date.fromisoformat(m_date.group(0))
        except ValueError:
            delivery = None
    if delivery is None:
        wd = next((v for k, v in WEEKDAYS.items() if re.search(rf"\b{re.escape(k)}\b", t)), None)
        if wd is None:
            wd = next((v for k, v in WEEKDAYS.items() if re.search(rf"\b{re.escape(k)}", t)), None)
        if wd is not None:
            delivery = next_weekday(wd, today)
        elif re.search(r"\b(tomorrow|huomenna)\b", t):
            delivery = today + timedelta(days=1)
        elif re.search(r"\b(today|tänään)\b", t):
            delivery = today
        else:
            delivery = today + timedelta(days=2)
    free_from = sorted({v for k, v in CLAIM_WORDS.items() if k in t})
    keys_desc = sorted(ITEM_HINTS, key=len, reverse=True)
    item_key = next((k for k in keys_desc if re.search(rf"\b{re.escape(k)}\b", t)), None)
    if item_key is None:
        item_key = next((k for k in keys_desc if k in t), None)
    words = [w for w in (tok.strip(".,!?;:\"'()[]") for tok in t.split()) if w]
    fallback_word = words[-1] if words else ""
    search_text, category, exclude = ITEM_HINTS.get(item_key, (fallback_word, None, []))
    preferred_ids = list(dict.fromkeys(re.findall(r"\b(4\d{5})\b", text)))
    if not preferred_ids and item_key in {"oat drink", "oat milk", "kaurajuoma"} and any(
        w in t for w in ("usual", "stock-out", "stockout", "out of stock", "preferred")
    ):
        preferred_ids = ["468465"]
    claim_labels = [
        lbl
        for lbl, code in (("lactose-free", "FREE_FROM_LACTOSE"), ("gluten-free", "FREE_FROM_GLUTEN"), ("vegan", "VEGAN"))
        if code in free_from
    ]
    item = " ".join(claim_labels + [item_key or search_text or "item"]).strip()
    return Need(
        item=item, quantity=qty, unit=unit, delivery_date=delivery, search_text=search_text,
        category=category, free_from=free_from, exclude_terms=exclude, preferred_product_ids=preferred_ids,
    )


class NeedDraft(BaseModel):
    """Structured-output schema the LLM fills from the buyer's text."""
    item: str = Field(description="Short English description of the product wanted")
    quantity: float
    unit: Literal["L", "KG", "PCS"]
    delivery_date: str = Field(description="YYYY-MM-DD")
    search_text_fi: str = Field(description="One Finnish word to search product names, e.g. maito, kerma, kaurajuoma")
    free_from: list[str] = Field(description="Claims such as FREE_FROM_LACTOSE, FREE_FROM_GLUTEN, VEGAN")
    exclude_allergens: list[str] = Field(description="Allergen groups to avoid: milk, gluten, nuts, egg, fish, soy")
    exclude_terms: list[str] = Field(description="Finnish words of near-miss products to exclude, e.g. kahvi, kaakao for plain milk")
    preferred_product_ids: list[str] = Field(default_factory=list,
                                             description="Explicit 6-digit Valio product IDs mentioned by the buyer, e.g. ['468465']")


def parse_need_llm(client, text: str, today: date) -> Need:
    resp = client.beta.messages.parse(
        model=MODEL, max_tokens=4000,
        betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": "low"},
        output_format=NeedDraft,
        system=f"Extract a purchasing need from a food-service buyer's message. Today is {today.isoformat()} "
               f"({today.strftime('%A')}). Resolve weekday names to the next such date. Use only the listed units.",
        messages=[{"role": "user", "content": text}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("The model declined to parse this request")
    d: NeedDraft | None = resp.parsed_output
    if d is None:
        raise RuntimeError("The model did not return a structured purchasing need")
    try:
        delivery = date.fromisoformat(d.delivery_date)
    except ValueError as exc:
        raise RuntimeError(f"Model returned invalid delivery_date {d.delivery_date!r}") from exc
    return Need(item=d.item, quantity=d.quantity, unit=d.unit, delivery_date=delivery,
                search_text=d.search_text_fi, free_from=d.free_from, exclude_allergens=d.exclude_allergens,
                exclude_terms=d.exclude_terms, preferred_product_ids=d.preferred_product_ids)


# --- compact views (fewer tokens for the model, easier to read in the UI trace) ------------------
def compact_offers(result: dict) -> dict:
    keep = (
        "product_id", "name", "sales_unit", "content_per_sales_unit", "content_unit", "unit_price",
        "unit_price_with_tax", "tax_rate", "price_per_content_unit", "available_qty", "unlimited",
        "available_date", "allowed_lot_size", "closing_time", "price_valid_to", "logistic_model",
        "category", "orderable", "reason", "reliability", "co2_per_kg", "allergens_contains",
        "allergens_may_contain", "claims", "labels", "substitutes", "currency", "net_price_found", "net_weight_kg",
    )
    out = dict(result)
    out["offers"] = [{k: o.get(k) for k in keep} for o in result.get("offers", [])]
    return out


# --- scripted (no LLM) ------------------------------------------------------------------------
def run_scripted(p: Principal, text: str, today: date | None = None, need: Need | None = None) -> dict:
    trace: list[dict] = []
    need = need or parse_need_heuristic(text, today)
    # When preferred_product_ids are specified (e.g. a stockout/substitute demo), let plan_need evaluate
    # Valio's listed substitutes so place_order hits the gateway's policy checks rather than pre-filtering them.
    if not need.preferred_product_ids:
        need.exclude_allergens = sorted(set(need.exclude_allergens) | set(p.mandate.forbidden_allergens))
        search_exclude = need.exclude_allergens
    else:
        search_exclude = []
    trace.append({"step": "parse_need", "output": need.model_dump(mode="json")})

    sreq = SearchRequest(text=need.search_text, free_from=need.free_from, exclude_allergens=search_exclude,
                         category=need.category, exclude_terms=need.exclude_terms, limit=40)
    found = service.search_products(p, sreq)
    trace.append({"tool": "search_products", "input": sreq.model_dump(exclude_defaults=True),
                  "output": {"total_matches": found.total_matches, "top": [f"{r.id} {r.name_fi}" for r in found.results[:8]]}})
    ids = list(dict.fromkeys(need.preferred_product_ids + [r.id for r in found.results]))
    if not ids:
        return {"need": need.model_dump(mode="json"), "trace": trace, "final": "No matching products in the catalog."}

    offers = service.check_offers(p, OffersRequest(product_ids=ids, delivery_date=need.delivery_date))
    plan_res, _ = service.plan_need(p, need, ids)
    trace.append({"tool": "check_offers", "input": {"product_ids": ids, "delivery_date": need.delivery_date.isoformat()},
                  "output": {"orderable": sum(o["orderable"] for o in offers["offers"]), "excluded": plan_res.excluded,
                             "plans": [f"{pl.label}: €{pl.total_net:,.2f}, coverage {pl.coverage:.0%}" for pl in plan_res.plans]}})
    if not plan_res.plans:
        return {"need": need.model_dump(mode="json"), "trace": trace, "plans": plan_res.model_dump(mode="json"),
                "final": "Nothing can be delivered on that date within the constraints."}

    best = plan_res.plans[0]
    qreq = QuoteRequest(delivery_date=need.delivery_date, need=need,
                        lines=[LineRequest(product_id=l.product_id, quantity=l.quantity) for l in best.lines])
    quote = service.create_quote(p, qreq)
    trace.append({"tool": "create_quote", "input": qreq.model_dump(mode="json", exclude={"need"}),
                  "output": {"quote_id": quote.quote_id, "total_net": quote.total_net, "expires_at": quote.expires_at.isoformat(),
                             "policy_preview": quote.policy_preview.decision.value}})
    if plan_res.excluded:
        reasons = ", ".join(sorted({str(e.get("reason", "excluded")) for e in plan_res.excluded})[:3])
        excl_note = f"{len(plan_res.excluded)} offers excluded ({reasons})"
    else:
        excl_note = "no offers excluded"
    rationale = (f"Plan '{best.label}' ({best.strategy}); covers {best.covered:g}/{best.requested:g} {best.unit}; "
                 f"{excl_note}.")
    order = service.place_order(p, quote.quote_id, rationale)
    trace.append({"tool": "place_order", "input": {"quote_id": quote.quote_id, "agent_rationale": rationale},
                  "output": {"order_id": order.order_id, "status": order.status.value}})
    items_summary = "; ".join(f"{l.quantity:g} {l.sales_unit} x {l.name}" for l in order.lines)
    reasons_text = " ".join(order.policy.reasons)
    status_val = order.status.value
    if status_val == "rejected":
        final = (f"Order {order.order_id} REJECTED for {need.delivery_date} ({items_summary}, "
                 f"€{order.total_net:,.2f} net). {reasons_text}").strip()
    elif status_val == "pending_approval":
        final = (f"Order {order.order_id} PENDING APPROVAL for {need.quantity:g} {need.unit} of {need.item} "
                 f"on {need.delivery_date}: {items_summary}. Total €{order.total_net:,.2f} net. {reasons_text}").strip()
    else:
        final = (f"Ordered {need.quantity:g} {need.unit} of {need.item} for {need.delivery_date}: {items_summary}. "
                 f"Total €{order.total_net:,.2f} net. Status: {status_val}. {reasons_text}").strip()
    return {"need": need.model_dump(mode="json"), "trace": trace, "plans": plan_res.model_dump(mode="json"),
            "quote": quote.model_dump(mode="json"), "order": order.model_dump(mode="json"), "final": final}


# --- LLM agent (Anthropic SDK tool runner, tools in-process) --------------------------------------
SYSTEM_PROMPT = """You are a purchasing agent for a food-service buyer ordering from Valio Aimo through a gateway.
Workflow:
1. search_products with structured filters (Finnish search text, free_from claims, category, exclude_terms).
   Name searches return near-misses (e.g. 'laktoositon' also matches cocoa drinks and coffee milk), so use the
   claim filters and check names before choosing.
2. check_offers for the shortlist with the delivery date, quantity and unit. Offers with orderable=false
   cannot be ordered (reason says why, e.g. cutoff_passed). The response includes ranked plans in sales units.
3. create_quote with the chosen plan's lines (product_id + quantity in sales units) and the need.
4. place_order with the quote id and a one-sentence rationale. The gateway applies the buyer's mandate;
   needs_approval is a normal outcome, not an error. Never try to work around limits by splitting orders.
5. Finish with a short explanation: what was ordered, price, coverage, what was excluded and why, and the status.
Only use product ids returned by the tools. If nothing fits, say so instead of guessing."""


def _llm_tools(p: Principal, trace: list[dict], need: Need, state: dict | None = None):
    from anthropic import beta_tool

    if state is None:
        state = {}

    def record(name: str, args: dict, out):
        trace.append({"tool": name, "input": args, "output": out})
        return json.dumps(out, default=str)

    def safe(name: str, args: dict, fn):
        try:
            return record(name, args, fn())
        except service.GatewayError as e:
            return record(name, args, {"error": e.message})
        except Exception as e:
            return record(name, args, {"error": str(e)})

    @beta_tool
    def search_products(text: str, free_from: list[str] | None = None, exclude_allergens: list[str] | None = None,
                        category: str | None = None, exclude_terms: list[str] | None = None, limit: int = 30) -> str:
        """Search the Valio Aimo catalog (static data, no prices).

        Args:
            text: Finnish/English word(s) matched as substrings of product names, e.g. 'maito'.
            free_from: Required claims, e.g. FREE_FROM_LACTOSE, FREE_FROM_GLUTEN, VEGAN.
            exclude_allergens: Allergen groups or codes the product must not contain (milk, gluten, AM...).
            category: Category code prefix, e.g. '10400' for milk.
            exclude_terms: Drop products whose name contains these words, e.g. kahvi, kaakao.
            limit: Max results (1-100).
        """
        args = dict(text=text, free_from=free_from or [], exclude_allergens=exclude_allergens or [],
                    category=category, exclude_terms=exclude_terms or [], limit=limit)
        return safe("search_products", args, lambda: service.search_products(p, SearchRequest(**args)).model_dump(
            include={"total_matches", "category_counts", "results"}))

    @beta_tool
    def check_offers(product_ids: list[str], delivery_date: str, quantity: float | None = None,
                     unit: str | None = None) -> str:
        """Live price and availability for up to 1000 products for one delivery date, plus ranked plans.

        Args:
            product_ids: Product ids from search_products.
            delivery_date: YYYY-MM-DD.
            quantity: Needed amount (optional, enables plans).
            unit: Unit of quantity: L, KG, PCS or a sales unit code.
        """
        args = dict(product_ids=product_ids, delivery_date=delivery_date, quantity=quantity, unit=unit)

        def _run_offers():
            res = compact_offers(service.check_offers(p, OffersRequest(**args)))
            if res.get("plan") is not None:
                state["plans"] = res["plan"]
            return res

        return safe("check_offers", args, _run_offers)

    @beta_tool
    def create_quote(delivery_date: str, lines: list[dict]) -> str:
        """Create a signed fixed-price quote. Returns totals, expiry and a policy preview.

        Args:
            delivery_date: YYYY-MM-DD.
            lines: List of {"product_id": str, "quantity": number in SALES units}.
        """
        args = dict(delivery_date=delivery_date, lines=lines)

        def _run_quote():
            dumped = service.create_quote(
                p, QuoteRequest(delivery_date=delivery_date, lines=lines, need=need)
            ).model_dump(mode="json")
            state["quote"] = dumped
            return {k: v for k, v in dumped.items() if k != "signature"}

        return safe("create_quote", args, _run_quote)

    @beta_tool
    def place_order(quote_id: str, agent_rationale: str) -> str:
        """Place an order from a quote. The buyer's mandate decides: confirmed, pending_approval or rejected.

        Args:
            quote_id: Id returned by create_quote.
            agent_rationale: One sentence explaining the choice (goes to the audit log).
        """
        args = dict(quote_id=quote_id, agent_rationale=agent_rationale)

        def _run_order():
            order = service.place_order(p, quote_id, agent_rationale).model_dump(mode="json")
            state["order"] = order
            return order

        return safe("place_order", args, _run_order)

    @beta_tool
    def get_order_status(order_id: str) -> str:
        """Current status of an order.

        Args:
            order_id: Order id.
        """
        return safe("get_order_status", {"order_id": order_id},
                    lambda: service.get_order(p, order_id).model_dump(mode="json"))

    @beta_tool
    def get_audit_log(order_id: str) -> str:
        """Human-readable audit timeline of an order.

        Args:
            order_id: Order id.
        """
        return safe("get_audit_log", {"order_id": order_id}, lambda: {"text": service.get_audit_log(p, order_id)["text"]})

    return [search_products, check_offers, create_quote, place_order, get_order_status, get_audit_log]


def run_llm(p: Principal, text: str, today: date | None = None) -> dict:
    import anthropic

    today = today or store_now().date()
    client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY (or an `ant auth login` profile)
    trace: list[dict] = []
    state: dict = {"plans": None, "quote": None, "order": None}
    need = parse_need_llm(client, text, today)
    if not need.preferred_product_ids:
        need.exclude_allergens = sorted(set(need.exclude_allergens) | set(p.mandate.forbidden_allergens))
    trace.append({"step": "parse_need", "output": need.model_dump(mode="json")})
    mandate_summary = json.dumps(
        {
            "buyer_id": p.buyer_id,
            "name": p.name,
            "mandate": p.mandate.model_dump(mode="json"),
            "weekly_spent_eur": service.weekly_spent(p.buyer_id),
        },
        indent=2,
    )
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=16000, max_iterations=15,
        betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": "medium"},
        system=SYSTEM_PROMPT,
        tools=_llm_tools(p, trace, need, state),
        messages=[{
            "role": "user",
            "content": (
                f"Buyer request: {text}\n\nParsed need (confirmed):\n{need.model_dump_json(indent=2)}\n\n"
                f"Buyer mandate and current spend:\n{mandate_summary}\n\nToday is {today.isoformat()}."
            ),
        }],
    )
    final_text, last = "", None
    for message in runner:   # one BetaMessage per model turn; tools run between turns
        last = message
        texts = [b.text for b in message.content if b.type == "text"]
        if texts:
            final_text = "\n".join(texts)
    if last is not None:
        if last.stop_reason == "refusal":
            final_text = "The model declined this request."
        elif last.stop_reason == "max_tokens" and not final_text:
            final_text = "Agent stopped early after reaching max_tokens."
        elif not final_text:
            final_text = "Agent stopped without a final summary (tool iteration limit reached)."
    return {
        "need": need.model_dump(mode="json"),
        "trace": trace,
        "plans": state["plans"],
        "quote": state["quote"],
        "order": state["order"],
        "final": final_text,
    }


def run_llm_via_mcp_connector(text: str, mcp_url: str, buyer_api_key: str) -> str:
    """OPTION (not used by default): let Claude call the gateway's hosted MCP endpoint directly.

    Requires the gateway to be reachable from the internet at `mcp_url` (e.g. https://<host>/mcp).
    The buyer's API key is sent as the MCP authorization token (Bearer), so the mandate still applies.
    TODO(C): enable once the gateway is deployed; add a --mcp-url flag to the CLI.
    """
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": text}]
    while True:
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM_PROMPT,
            betas=[MCP_CONNECTOR_BETA, FALLBACK_BETA], fallbacks="default",
            mcp_servers=[{"type": "url", "url": mcp_url, "name": "valio-gateway", "authorization_token": buyer_api_key}],
            tools=[{"type": "mcp_toolset", "mcp_server_name": "valio-gateway"}],
            messages=messages,
        )
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        return "\n".join(b.text for b in resp.content if b.type == "text")


def run_agent(p: Principal, text: str, mode: str = "auto", today: date | None = None) -> dict:
    if mode == "auto":
        mode = "llm" if settings.anthropic_api_key else "scripted"
    if mode == "llm" and not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; use mode=scripted or mode=auto")
    result = run_llm(p, text, today) if mode == "llm" else run_scripted(p, text, today)
    result["mode"] = mode
    audit.log("AGENT_RUN", p.actor, {"mode": mode, "text": text, "final": result.get("final", "")[:500],
                                             "order_id": (result.get("order") or {}).get("order_id")},
                      buyer_id=p.buyer_id, order_id=(result.get("order") or {}).get("order_id"))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the buyer agent against the in-process gateway.")
    ap.add_argument("text")
    ap.add_argument("--buyer", default="hotel", help="hotel | hospital (uses demo-<buyer>-key)")
    ap.add_argument("--mode", default="auto", choices=["auto", "llm", "scripted"])
    a = ap.parse_args()
    p = principal_for_key(f"demo-{a.buyer}-key")
    if p is None:
        raise SystemExit(f"unknown buyer {a.buyer}")
    try:
        res = run_agent(p, a.text, a.mode)
    except Exception as exc:
        raise SystemExit(f"Agent run failed: {exc}") from exc
    print("Parsed need:\n" + json.dumps(res["need"], indent=2))
    print("\nTool trace:")
    for t in res["trace"]:
        print(" -", t.get("tool") or t.get("step"), json.dumps(t.get("output"), default=str)[:300])
    print("\nResult:\n" + res.get("final", ""))


if __name__ == "__main__":
    main()
