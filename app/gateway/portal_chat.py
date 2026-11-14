"""Client assistant calls the same MCP tools as external buyers, with a read-only credential."""
from __future__ import annotations

import json
import re
from typing import Literal

import anyio
from fastapi import APIRouter, Depends
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from . import audit, service, store
from .agent import parse_need_heuristic, parse_need_llm
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


async def _read_tool(name: Literal["search_products", "check_offers"], args: dict, p: Principal) -> dict:
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
    audit.log("CLIENT_INQUIRY", p.actor, {"text": text, "action": "draft" if draft_requested else "lookup"},
              buyer_id=p.buyer_id)
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
    }, p)
    plans = (result.get("plan") or {}).get("plans", [])
    response.update(result)
    response["message"] = f"Checked {len(result['offers'])} products for {need.delivery_date:%d %B}."
    if not plans:
        response["message"] += " No orderable plan meets this request."
        return response
    if draft_requested:
        best = plans[0]
        if not need.preferred_product_ids:
            fallback_ids = {offer["product_id"] for group in result.get("alternatives", {}).values()
                            for offer in group if offer["substitution_source"] == "catalog_ingredient_match"}
            if any(line["product_id"] in fallback_ids for line in best["lines"]):
                need.preferred_product_ids = ids
        quote_request = QuoteRequest(delivery_date=need.delivery_date, need=need,
                                     lines=[{"product_id": line["product_id"], "quantity": line["quantity"]}
                                            for line in best["lines"]])
        draft = await anyio.to_thread.run_sync(service.create_quote, p, quote_request)
        response["draft"] = draft.model_dump(mode="json", exclude={"signature"})
        response["message"] = "Ticket draft created. Review the quantities and total before submitting."
    return response


@router.post("/tickets/submit")
def submit(request: OrderRequest, p: Principal = Depends(require_client)):
    return service.place_order(p, request.quote_id, "Client reviewed and submitted the signed ticket draft.")
