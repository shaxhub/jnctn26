"""Client assistant calls the same MCP tools as external buyers, with a read-only credential."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Literal

import anyio
import httpx
from fastapi import APIRouter, Depends
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError

from . import audit, gemini, kitchen, meal_planning, service, store
from .agent import explicit_quantity, parse_need_heuristic, requested_date
from .auth import Principal, current_principal, require_client
from .delivery import postal_code_from_address
from .mcp_server import mcp
from .models import Need, OrderRequest, QuoteRequest
from .search import get_products

router = APIRouter(prefix="/client")


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    delivery_date: date | None = None
    action: Literal["lookup", "draft", "shop"] = "lookup"
    postal_code: str | None = Field(None, pattern=r"^[0-9]{5}$")
    language: Literal["en", "fi"] = "en"
    include_substitutes: bool = True
    plan_lines: list[tuple[str, float]] | None = Field(None, min_length=1, max_length=100)


# A typed command or the explicit draft button can opt in to drafting.
DRAFT_COMMAND = re.compile(r"^(?:please\s+)?(?:create|draft|prepare)\s+(?:an?\s+)?(?:order\s+)?(?:ticket|draft)\b", re.I)
ALLERGY = re.compile(r"\b(?:allergy to|allergic to|exclude allergen)\s+([\w -]+?)(?=[,.;]|\s+(?:by|for|on)\b|$)", re.I)
CATALOG_STAPLES = ("potato", "carrot", "tomato", "apple", "rapeseed oil", "red lentils",
                   "wholegrain bread", "oats", "salmon", "pasta", "rice", "beans", "cabbage")


async def _ground_inferred_recipes(text: str, parsed, excluded: list[str]) -> str | None:
    names = list(dict.fromkeys(ingredient.name for recipe in parsed.recipes for ingredient in recipe.ingredients))
    matches = {name: await anyio.to_thread.run_sync(kitchen.catalog_candidates, name, excluded) for name in names}
    if all(matches.values()):
        return None
    for name in CATALOG_STAPLES:
        if name not in matches:
            matches[name] = await anyio.to_thread.run_sync(kitchen.catalog_candidates, name, excluded)
    candidates = {row["id"]: {**row, "ingredient": name} for name, rows in matches.items() for row in rows[:3]}
    if candidates:
        try:
            revised = await gemini.ground_recipes(text, parsed.recipes, list(candidates.values()))
            ids = [ingredient.name for recipe in revised.recipes for ingredient in recipe.ingredients]
            if ids and all(product_id in candidates for product_id in ids):
                parsed.recipes = revised.recipes
                return None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            pass
    return "The catalog could not support the full recipe. Review the matched items and any ingredients still needed."


def _lookup(text: str, today: date) -> Need:
    need = parse_need_heuristic(text, today)
    need.exclude_allergens.extend(match.group(1).strip() for match in ALLERGY.finditer(text))
    return need


@router.get("/models")
def models():
    return {"models": [{"id": gemini.MODEL, "name": gemini.LABEL, "available": gemini.enabled()}]}


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
    today = store.now().date()
    if request.action == "shop":
        postcode = request.postal_code or postal_code_from_address(text)
        delivery = request.delivery_date or requested_date(text, today)
        if not postcode or not delivery:
            missing = [label for label, value in (("delivery date", delivery), ("five-digit delivery postcode", postcode)) if not value]
            raise service.GatewayError(422, "Add " + " and ".join(missing) + " in your request or in the fields below it.")
        if delivery < today:
            raise service.GatewayError(422, "Choose today or a future delivery date.")
        request = request.model_copy(update={"postal_code": postcode, "delivery_date": delivery})
    mode = "guided"
    parsed = None
    if gemini.enabled():
        try:
            parsed = await gemini.extract(text, today, language="Finnish" if request.language == "fi" else "English")
            mode = gemini.MODEL
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            mode = "guided_fallback"
    school_meal = meal_planning.school_lunch(text, today, request.delivery_date, parsed=parsed, language=request.language)
    catalog_gap = None
    if request.action == "shop" and parsed and parsed.recipes and not any(
            kitchen.LINE.fullmatch(line.strip().removeprefix("- ")) for line in text.splitlines()):
        excluded = school_meal[0].exclude_allergens if school_meal else parsed.exclude_allergens
        catalog_gap = await _ground_inferred_recipes(text, parsed, excluded + p.mandate.forbidden_allergens)
        if school_meal:
            school_meal = meal_planning.school_lunch(text, today, request.delivery_date, parsed=parsed, language=request.language)
    if school_meal:
        sourcing, meal = school_meal
        result = await _read_tool("source_ingredients", sourcing.model_dump(mode="json"), p)
        complete = all(row["status"] == "available" for row in result["ingredients"])
        if request.action == "shop" and not complete and request.include_substitutes:
            alternative, alternate_meal = meal_planning.school_lunch(
                text, today, request.delivery_date, parsed=parsed, stock_menu=True, language=request.language)
            alternate = await _read_tool("source_ingredients", alternative.model_dump(mode="json"), p)
            if all(row["status"] == "available" for row in alternate["ingredients"]):
                sourcing, meal, result = alternative, alternate_meal, alternate
                meal["alternative"] = True
                complete, catalog_gap = True, None
        partial_total = round(sum(row["sourcing"]["plan"]["total_net"] for row in result["ingredients"]
                                  if row.get("sourcing")), 2)
        meal["matched_total_net"] = partial_total
        meal["complete"] = complete
        draft = None
        if complete and request.action == "shop":
            basket = kitchen.basket_request(result)
            basket.exclude_allergens = sourcing.exclude_allergens
            try:
                quote = await anyio.to_thread.run_sync(lambda: service.create_quote(
                    p, basket, max_total_gross=meal["budgets"].get("hard"),
                    name=(parsed.ticket_name if parsed and not meal.get("alternative") else None)
                    or meal["recipes"][0]["name"], postal_code=request.postal_code))
                draft = quote.model_dump(mode="json")
            except service.GatewayError as exc:
                if exc.status not in (409, 422):
                    raise
                catalog_gap = exc.message
        return {"recipe": result, "meal": meal, "draft": draft,
                "mode": gemini.MODEL if meal["generated"] else "guided_meal",
                "message": catalog_gap or ("School lunch draft ready. Verify labels, cross-contact controls and school meal standards before submitting."
                                           if draft else "School lunch proposal and purchasing list ready for kitchen review.")}
    recipes = parsed.recipes if parsed else []
    if not recipes and "\n" in text:
        recipe_rows = sum(bool(kitchen.LINE.fullmatch(line.strip().removeprefix("- "))) for line in text.splitlines())
        if recipe_rows >= 1:
            first = text.splitlines()[0].strip()
            recipe_input = "Pasted recipe (1)\n" + text if kitchen.LINE.fullmatch(first.removeprefix("- ")) else text
            try:
                recipes = kitchen.recipes_from_text(recipe_input, 1)
            except (ValidationError, ValueError, OverflowError, service.GatewayError) as exc:
                raise service.GatewayError(422, "Paste recipe quantities in metric units, such as 500 g tomato.") from exc
    if recipes:
        servings = parsed.servings if parsed and parsed.servings else recipes[0].servings
        delivery = request.delivery_date or (parsed.delivery_date if parsed else None)
        if delivery is None and parsed and parsed.recipes:
            delivery = requested_date(text, today) or today + timedelta(days=2)
        draft_requested = delivery is not None and (draft_requested or request.action == "shop")
        result = await _kitchen_result(KitchenChatRequest(
            kind="recipes", text=text, servings=servings,
            delivery_date=delivery, exclude_allergens=parsed.exclude_allergens if parsed else [],
            draft=draft_requested), p, recipes=recipes, allow_incomplete=True,
            name=parsed.ticket_name if parsed else recipes[0].name,
            postal_code=request.postal_code or postal_code_from_address(text))
        return {"recipe": result, "draft": result.get("draft"), "mode": mode,
                "message": ("Recipe draft ready for review." if result.get("draft") else
                            catalog_gap or result.get("draft_blocker", "Recipe shopping list ready for review."))}
    need = parsed.need if parsed and parsed.need else _lookup(text, today)
    draft_requested = draft_requested or (request.action == "shop" and explicit_quantity(text))
    if request.delivery_date:
        need.delivery_date = request.delivery_date
    need.exclude_allergens = sorted(set(need.exclude_allergens + p.mandate.forbidden_allergens))[:30]
    entry = await anyio.to_thread.run_sync(lambda: audit.log(
        "CLIENT_INQUIRY", p.actor, {"text": text, "action": "draft" if draft_requested else "lookup"},
        buyer_id=p.buyer_id))
    token = audit.inquiry_sequence.set(entry["seq"])
    try:
        return await _handle_request(request, p, text, need, mode, draft_requested,
                                     name=parsed.ticket_name if parsed else None)
    finally:
        audit.inquiry_sequence.reset(token)


async def _handle_request(request: ChatRequest, p: Principal, text: str, need: Need, mode: str,
                          draft_requested: bool, *, name=None) -> dict:
    if need.preferred_product_ids and need.search_text in need.preferred_product_ids:
        # A bare SKU is an exact lookup. The MCP offer tool handles its alternatives.
        found = {"results": []}
    else:
        search_args = {"text": need.search_text, "free_from": need.free_from,
                   "exclude_allergens": need.exclude_allergens, "category": need.category,
                   "exclude_terms": need.exclude_terms, "limit": 16}
        found = await _read_tool("search_products", search_args, p)
    ids = list(dict.fromkeys(need.preferred_product_ids + [row["id"] for row in found["results"]]))
    if request.action == "shop" and need.preferred_product_ids:
        ids = list(await anyio.to_thread.run_sync(get_products, ids))
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
        if mode != gemini.MODEL and not explicit_quantity(text):
            return {**response, "message": "Include a quantity and unit before drafting, such as 5 litres or 2 boxes."}
        best = plans[0]
        if request.plan_lines is not None:
            best = next((plan for plan in plans if request.plan_lines == [
                (line["product_id"], line["quantity"]) for line in plan["lines"]]), None)
            if best is None:
                return {**response, "message": "That plan changed. Review the refreshed options before drafting."}
        if request.action == "shop" and best["coverage"] < 0.9999:
            return {**response, "message": "The catalog only covers part of this request. Review the matched items and the shortfall."}
        if not need.preferred_product_ids:
            fallback_ids = {offer["product_id"] for group in result.get("alternatives", {}).values()
                            for offer in group if offer["substitution_source"] == "catalog_ingredient_match"}
            if any(line["product_id"] in fallback_ids for line in best["lines"]):
                need.preferred_product_ids = ids
        quote_request = QuoteRequest(delivery_date=need.delivery_date, need=need,
                                     lines=[{"product_id": line["product_id"], "quantity": line["quantity"]}
                                            for line in best["lines"]])
        draft = await anyio.to_thread.run_sync(lambda: service.create_quote(
            p, quote_request, name=name, postal_code=request.postal_code or postal_code_from_address(text)))
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
    return await _kitchen_result(request, p)


async def _kitchen_result(request: KitchenChatRequest, p: Principal, *, recipes=None, allow_incomplete=False, name=None,
                          postal_code: str | None = None):
    try:
        dishes = [line.strip().removeprefix("- ").strip() for line in request.text.splitlines() if line.strip()]
        args = kitchen.KitchenRequest(
            servings=request.servings,
            dishes=dishes if request.kind == "menu" else [],
            recipes=recipes if recipes is not None else (kitchen.recipes_from_text(request.text, request.servings)
                                                         if request.kind == "recipes" else []),
        ).model_dump(mode="json")
    except ValidationError as exc:
        raise service.GatewayError(422, exc.errors()[0]["msg"]) from exc
    except (ValueError, OverflowError) as exc:
        raise service.GatewayError(422, "Paste recipe quantities in metric units, such as 500 g tomato.") from exc
    if request.delivery_date is None:
        if request.draft:
            raise service.GatewayError(422, "Choose a delivery date before drafting")
        return await _read_tool("compile_ingredients", args, p)
    args.update(delivery_date=request.delivery_date.isoformat(), exclude_allergens=request.exclude_allergens,
                required_claims=request.required_claims, unavailable_ingredients=request.unavailable_ingredients)
    if not request.draft:
        return await _read_tool("source_ingredients", args, p)
    entry = await anyio.to_thread.run_sync(lambda: audit.log(
        "CLIENT_INQUIRY", p.actor, {"text": "Menu draft", "action": "draft",
                                    "dishes": args["dishes"] or [recipe["name"] for recipe in args["recipes"]]},
        buyer_id=p.buyer_id))
    token = audit.inquiry_sequence.set(entry["seq"])
    try:
        result = await _read_tool("source_ingredients", args, p)
        try:
            basket = kitchen.basket_request(result)
            basket.exclude_allergens = request.exclude_allergens
            basket.required_claims = request.required_claims
            quote = await anyio.to_thread.run_sync(lambda: service.create_quote(p, basket, name=name, postal_code=postal_code))
        except service.GatewayError as exc:
            if not allow_incomplete or exc.status not in (409, 422):
                raise
            return {**result, "draft_blocker": exc.message}
        result["draft"] = quote.model_dump(mode="json")
        return result
    finally:
        audit.inquiry_sequence.reset(token)


@router.get("/seasonal")
async def seasonal_products(delivery_date: date, p: Principal = Depends(require_client)):
    return await _read_tool("discover_seasonal_products", {"delivery_date": delivery_date.isoformat()}, p)


@router.post("/tickets/{order_id}/repeat")
def repeat_ticket(order_id: str, delivery_date: date, p: Principal = Depends(require_client)):
    return service.repeat_quote(p, order_id, delivery_date)


@router.get("/tickets/{quote_id}/recurring")
def recurring_ticket(quote_id: str, p: Principal = Depends(require_client)):
    return service.check_recurring_quote(p, quote_id)


@router.post("/tickets/submit")
def submit(request: OrderRequest, p: Principal = Depends(require_client)):
    return service.place_order(p, request.quote_id, "Client reviewed and submitted the signed ticket draft.", replay=True,
                               delivery_address=request.delivery_address)
