"""Client assistant calls the same MCP tools as external buyers, with a read-only credential."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Literal

import anyio
from fastapi import APIRouter, Depends
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError

from . import audit, kitchen, service, store
from .agent import explicit_quantity, parse_need_heuristic, parse_need_llm
from .auth import Principal, current_principal, require_client
from .config import settings
from .delivery import postal_code_from_address
from .mcp_server import mcp
from .models import Need, OrderRequest, QuoteRequest

router = APIRouter(prefix="/client")


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    action: Literal["lookup", "draft"] = "lookup"
    postal_code: str | None = Field(None, pattern=r"^[0-9]{5}$")
    include_substitutes: bool = True
    plan_lines: list[tuple[str, float]] | None = Field(None, min_length=1, max_length=100)


# A typed command or the explicit draft button can opt in to drafting.
DRAFT_COMMAND = re.compile(r"^(?:please\s+)?(?:create|draft|prepare)\s+(?:an?\s+)?(?:order\s+)?(?:ticket|draft)\b", re.I)
ALLERGY = re.compile(r"\b(?:allergy to|allergic to|exclude allergen)\s+([\w -]+?)(?=[,.;]|\s+(?:by|for|on)\b|$)", re.I)


async def _lookup(p: Principal, text: str) -> tuple[Need, str]:
    today = store.now().date()
    if settings.anthropic_api_key:
        import anthropic

        def parse():
            with anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=15, max_retries=0) as client:
                return parse_need_llm(client, text, today)

        try:
            return await anyio.to_thread.run_sync(parse), "ai"
        except (anthropic.APIError, RuntimeError, ValueError):
            pass
    need = parse_need_heuristic(text, today)
    need.exclude_allergens.extend(match.group(1).strip() for match in ALLERGY.finditer(text))
    return need, "guided"


async def _read_tool(name: Literal["search_products", "check_offers", "compile_ingredients", "source_ingredients", "discover_seasonal_products"], args: dict, p: Principal) -> dict:
    token = current_principal.set(p)
    try:
        result = await mcp.call_tool(name, args)
        if result.is_error:
            raise service.GatewayError(502, "Catalog lookup failed")
        if result.structured_content is not None:
            return result.structured_content
        if result.content and result.content[0].type == "text":
            return json.loads(result.content[0].text)
        raise service.GatewayError(502, "Catalog lookup did not return data")
    except ToolError as exc:
        raise service.GatewayError(502, str(exc)) from exc
    finally:
        current_principal.reset(token)


@router.post("/chat")
async def chat(request: ChatRequest, p: Principal = Depends(require_client)):
    text = request.text.strip()
    if not text:
        raise service.GatewayError(422, "Enter a product request")
    draft_requested = request.action == "draft" or bool(DRAFT_COMMAND.match(text))
    need, mode = await _lookup(p, text)
    need.exclude_allergens = sorted(set(need.exclude_allergens + p.mandate.forbidden_allergens))
    entry = await anyio.to_thread.run_sync(lambda: audit.log(
        "CLIENT_INQUIRY", p.actor, {"text": text, "action": "draft" if draft_requested else "lookup"},
        buyer_id=p.buyer_id))
    token = audit.inquiry_sequence.set(entry["seq"])
    try:
        return await _handle_request(request, p, text, need, mode, draft_requested)
    finally:
        audit.inquiry_sequence.reset(token)


async def _handle_request(request: ChatRequest, p: Principal, text: str, need: Need, mode: str,
                          draft_requested: bool) -> dict:
    if need.preferred_product_ids and need.search_text in need.preferred_product_ids:
        # A bare SKU is an exact lookup. The MCP offer tool handles its alternatives.
        found = {"results": []}
    else:
        search_args = {"text": need.search_text, "free_from": need.free_from,
                   "exclude_allergens": need.exclude_allergens, "category": need.category,
                   "exclude_terms": need.exclude_terms, "limit": 16}
        found = await _read_tool("search_products", search_args, p)
    ids = list(dict.fromkeys(need.preferred_product_ids + [row["id"] for row in found["results"]]))
    response = {"mode": mode, "need": need.model_dump(mode="json"), "draft": None}
    if not ids:
        return {**response, "message": "No catalog items match. Try a product name or Valio product code."}
    result = await _read_tool("check_offers", {
        "product_ids": ids, "delivery_date": need.delivery_date.isoformat(), "quantity": need.quantity,
        "unit": need.unit, "include_substitutes": request.include_substitutes,
        "required_claims": need.free_from, "exclude_allergens": need.exclude_allergens,
        "postal_code": request.postal_code or postal_code_from_address(text),
        "include_next_delivery": request.include_substitutes,
    }, p)
    plans = (result.get("plan") or {}).get("plans", [])
    response.update(result)
    response["message"] = f"Checked {len(result['offers'])} products for {need.delivery_date:%d %B}."
    if not plans:
        response["message"] += " No orderable plan meets this request."
        return response
    if draft_requested:
        if mode == "guided" and not explicit_quantity(text):
            return {**response, "message": "Include a quantity and unit before drafting, such as 5 litres or 2 boxes."}
        best = plans[0]
        if request.plan_lines is not None:
            best = next((plan for plan in plans if request.plan_lines == [
                (line["product_id"], line["quantity"]) for line in plan["lines"]]), None)
            if best is None:
                return {**response, "message": "That plan changed. Review the refreshed options before drafting."}
        if not need.preferred_product_ids:
            fallback_ids = {offer["product_id"] for group in result.get("alternatives", {}).values()
                            for offer in group if offer["substitution_source"] == "catalog_ingredient_match"}
            if any(line["product_id"] in fallback_ids for line in best["lines"]):
                need.preferred_product_ids = ids
        quote_request = QuoteRequest(delivery_date=need.delivery_date, need=need,
                                     lines=[{"product_id": line["product_id"], "quantity": line["quantity"]}
                                            for line in best["lines"]])
        draft = await anyio.to_thread.run_sync(service.create_quote, p, quote_request)
        response["draft"] = draft.model_dump(mode="json")
        response["message"] = "Ticket draft created. Review the quantities and total before submitting."
    return response


class KitchenChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    kind: Literal["menu", "recipes"]
    draft: bool = False
    servings: int = Field(ge=1, le=5000)
    delivery_date: date | None = None
    exclude_allergens: list[kitchen.Text] = Field(default_factory=list, max_length=20)
    required_claims: list[kitchen.Text] = Field(default_factory=list, max_length=10)
    unavailable_ingredients: list[kitchen.Text] = Field(default_factory=list, max_length=30)


@router.post("/kitchen")
async def kitchen_chat(request: KitchenChatRequest, p: Principal = Depends(require_client)):
    try:
        dishes = [line.strip().removeprefix("- ").strip() for line in request.text.splitlines() if line.strip()]
        args = kitchen.KitchenRequest(
            servings=request.servings,
            dishes=dishes if request.kind == "menu" else [],
            recipes=kitchen.recipes_from_text(request.text, request.servings) if request.kind == "recipes" else [],
        ).model_dump(mode="json")
    except ValidationError as exc:
        raise service.GatewayError(422, exc.errors()[0]["msg"]) from exc
    if request.delivery_date is None:
        if request.draft:
            raise service.GatewayError(422, "Choose a delivery date before drafting")
        return await _read_tool("compile_ingredients", args, p)
    args.update(delivery_date=request.delivery_date.isoformat(), exclude_allergens=request.exclude_allergens,
                required_claims=request.required_claims, unavailable_ingredients=request.unavailable_ingredients)
    result = await _read_tool("source_ingredients", args, p)
    if request.draft:
        basket = kitchen.basket_request(result)
        basket.exclude_allergens = request.exclude_allergens
        basket.required_claims = request.required_claims
        quote = await anyio.to_thread.run_sync(service.create_quote, p, basket)
        result["draft"] = quote.model_dump(mode="json")
    return result


@router.get("/seasonal")
async def seasonal_products(delivery_date: date, p: Principal = Depends(require_client)):
    return await _read_tool("discover_seasonal_products", {"delivery_date": delivery_date.isoformat()}, p)


@router.post("/tickets/{order_id}/repeat")
def repeat_ticket(order_id: str, delivery_date: date, p: Principal = Depends(require_client)):
    if delivery_date < store.now().date():
        raise service.GatewayError(422, "Choose today or a future delivery date")
    original = service.get_order(p, order_id)
    if original.status != "confirmed":
        raise service.GatewayError(409, "Choose a confirmed ticket to repeat")
    signed = store.fetchone("SELECT payload_json FROM quotes WHERE quote_id=?", (original.quote_id,))
    payload = json.loads(signed["payload_json"]) if signed else {}
    need = payload.get("need")
    if need:
        need["delivery_date"] = delivery_date.isoformat()
    return service.create_quote(p, QuoteRequest(delivery_date=delivery_date, need=need,
        exclude_allergens=payload.get("exclude_allergens", []), required_claims=payload.get("required_claims", []), lines=[
        {"product_id": line.product_id, "quantity": line.quantity} for line in original.lines
    ]))


@router.get("/tickets/{quote_id}/recurring")
def recurring_ticket(quote_id: str, p: Principal = Depends(require_client)):
    return service.check_recurring_quote(p, quote_id)


@router.post("/tickets/submit")
def submit(request: OrderRequest, p: Principal = Depends(require_client)):
    return service.place_order(p, request.quote_id, "Client reviewed and submitted the signed ticket draft.", replay=True)
