"""MCP server: tools for external purchasing agents (Streamable HTTP, mounted at /mcp by api.py).

Uses the official MCP Python SDK v2 (`mcp` 2.x), where FastMCP is called `MCPServer`
(`from mcp.server.mcpserver import MCPServer`). The tools are thin wrappers over gateway.service.

Authentication: the HTTP request must carry `X-API-Key: <key>` or `Authorization: Bearer <key>`.
The key identifies the buyer and its mandate. No tool takes a buyer id, a customer number or a
limit as an argument, so an agent cannot widen its own authority.

The tool descriptions below are the agent's documentation: keep them precise.
"""
from __future__ import annotations

from datetime import date
from functools import partial

import anyio
import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import ValidationError

from . import kitchen, seasonal, service, store, workspace
from .agent import compact_offers
from .auth import Principal, current_principal, key_from_headers, principal_for_key
from .config import demo_catalog_enabled
from .delivery import estimate, postal_code_from_address
from .valio_client import get_client
from .models import LineRequest, Need, OffersRequest, QuoteRequest, SearchRequest

READ_TOOLS = ("ping", "get_my_mandate", "search_products", "check_offers",
              "estimate_delivery", "discover_seasonal_products", "check_recurring_quote", "get_order_status",
              "get_request_thread", "get_audit_log", "get_kitchen_capabilities", "compile_ingredients", "source_ingredients")

INSTRUCTIONS = """Valio Aimo trade gateway for food-service purchasing agents.
Typical flow: get_my_mandate -> search_products -> check_offers (with quantity+unit to get plans)
-> create_quote -> place_order -> get_order_status / get_audit_log.
For menu planning use compile_ingredients and source_ingredients. These are read-only.
Quantities in quotes and orders are in SALES units (see sales_unit).
Your buyer's mandate is enforced server-side; orders may be confirmed, wait for human approval, or be rejected."""

def _is_read_only(p: Principal) -> bool:
    return p.oauth_read_only or p.role != "agent" or not p.can_order


class PurchasingMCPServer(MCPServer):
    async def list_tools(self):
        tools = await super().list_tools()
        principal = current_principal.get()
        if principal and _is_read_only(principal):
            return [tool.model_copy(update={"annotations": ToolAnnotations(read_only_hint=True)})
                    for tool in tools if tool.name in READ_TOOLS]
        return tools

    async def call_tool(self, name, arguments, context=None):
        principal = current_principal.get()
        if principal and name not in READ_TOOLS:
            if principal.oauth_read_only:
                raise ToolError("This ChatGPT connection has read-only access")
            if _is_read_only(principal):
                raise ToolError("This credential has read-only access")
        return await super().call_tool(name, arguments, context)


mcp = PurchasingMCPServer(name="valio-aimo-gateway", title="Agent Dairy — Valio Aimo Trade Gateway",
                instructions=INSTRUCTIONS, version="0.1.0")


def _principal(ctx: Context | None, *, write: bool = False) -> Principal:
    p = current_principal.get()
    if p is None and ctx is not None:
        try:
            p = principal_for_key(key_from_headers(ctx.headers))
        except ValueError:
            p = None
    if p is None:
        raise ToolError("Unauthenticated: send X-API-Key or Authorization: Bearer <key>")
    if p.role not in {"agent", "client"} or (write and _is_read_only(p)):
        raise ToolError("This credential does not have permission to perform this action")
    return p


def _parse_args(fn):
    try:
        return fn()
    except (ValidationError, TypeError, ValueError) as e:
        raise ToolError(f"Invalid tool arguments: {e}") from e


async def _run(fn, *args, **kwargs):
    try:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))
    except service.GatewayError as e:
        raise ToolError(e.message) from e
    except httpx.HTTPError as e:
        raise ToolError(f"Valio upstream API error: {e}") from e
    except OverflowError as e:
        raise ToolError("A numeric value is outside the supported range.") from e
    except (ValidationError, TypeError, ValueError, RuntimeError) as e:
        raise ToolError(str(e)) from e


@mcp.tool()
async def ping(ctx: Context = None) -> dict:
    """Report the gateway and Valio mock API status."""
    _principal(ctx)
    if demo_catalog_enabled():
        return {"status": "ok", "valio": "simulated", "checked_at": store.now().isoformat()}
    try:
        upstream = "ok" if await _run(get_client().ping) else "unexpected_response"
    except ToolError:
        upstream = "unavailable"
    return {"status": "ok", "valio": upstream, "checked_at": store.now().isoformat()}


@mcp.tool()
async def discover_seasonal_products(delivery_date: str, exclude_allergens: list[kitchen.Text] | None = None,
                                     required_claims: list[kitchen.Text] | None = None, ctx: Context = None) -> dict:
    """Suggest in-season Finnish produce with verified availability for the requested date.
    Applies buyer constraints and returns price, origin, and sustainability evidence when available.
    """
    principal = _principal(ctx)
    delivery = _parse_args(lambda: date.fromisoformat(delivery_date))
    excluded, claims = exclude_allergens or [], required_claims or []
    if len(excluded) > 20 or len(claims) > 10:
        raise ToolError("Use at most 20 allergen exclusions and 10 required claims")
    return await _run(seasonal.discover, principal, delivery, excluded, claims)


@mcp.tool()
async def get_kitchen_capabilities(ctx: Context = None) -> dict:
    """List recognized dish templates, recipe units and supported dish-specific replacements."""
    _principal(ctx)
    return kitchen.capabilities()


@mcp.tool()
async def compile_ingredients(servings: int, dishes: list[str] | None = None,
                              recipes: list[kitchen.Recipe] | None = None, ctx: Context = None) -> dict:
    """Compile a shopping list for dish names and/or recipes. Servings apply per dish.
    Recipe quantities refer to the recipe's own servings and use g, kg, ml, dl, l, or pcs.
    Dish-name templates are estimates. Unrecognized dishes are returned for clarification.
    Supply a recipe with the same name to override a template. Does not create tickets.
    """
    principal = _principal(ctx)
    request = _parse_args(lambda: kitchen.KitchenRequest(servings=servings, dishes=dishes or [], recipes=recipes or []))
    result = await _run(kitchen.compile_ingredients, request)
    await _run(kitchen.log_plan, principal, request, result)
    return result


@mcp.tool()
async def source_ingredients(servings: int, delivery_date: str, dishes: list[str] | None = None,
                             recipes: list[kitchen.Recipe] | None = None, exclude_allergens: list[str] | None = None,
                             required_claims: list[str] | None = None, unavailable_ingredients: list[str] | None = None,
                             ctx: Context = None) -> dict:
    """Compile a menu or recipe list, check Valio offers and suggest dish-specific alternatives.
    Add unavailable_ingredients to request replacements for ingredients known to be out of stock.
    Returned options include coverage, pack quantities, price, stock, carbon and reliability when present.
    Ingredients are sourced independently. Culinary swaps apply to the listed dishes and require review.
    This is a read-only planning operation.
    """
    principal = _principal(ctx)
    request = _parse_args(lambda: kitchen.SourceRequest(
        servings=servings, delivery_date=delivery_date, dishes=dishes or [], recipes=recipes or [],
        exclude_allergens=exclude_allergens or [], required_claims=required_claims or [],
        unavailable_ingredients=unavailable_ingredients or []))
    return await _run(kitchen.source_ingredients, principal, request)


@mcp.tool()
async def estimate_delivery(postal_code: str | None = None, ctx: Context = None, address: str | None = None) -> dict:
    """Estimate travel from Rautatientori to a Finnish postcode area. Provide a postcode or an address containing one.
    Returns estimate_unavailable if the postcode has no area in the bundled dataset.
    """
    _principal(ctx)
    if postal_code is None and address and len(address) <= 300:
        postal_code = postal_code_from_address(address)
    if postal_code is None or len(postal_code) != 5 or not postal_code.isascii() or not postal_code.isdecimal():
        raise ToolError("Provide a five-digit Finnish postal code")
    return estimate(postal_code)


@mcp.tool()
async def get_my_mandate(ctx: Context = None) -> dict:
    """Inspect your buyer identity, purchasing mandate (limits, forbidden allergens, allowed claims,
    substitution rules, approval thresholds) and current weekly spend."""
    p = _principal(ctx)
    spent = await _run(service.weekly_spent, p.buyer_id)
    return {
        "buyer_id": p.buyer_id,
        "role": p.role,
        "name": p.name,
        "mandate": p.mandate.model_dump(mode="json"),
        "weekly_spent": spent,
        "allowed_tools": list(READ_TOOLS) + ([] if _is_read_only(p) else ["post_request_message", "create_quote", "repeat_quote", "place_order"]),
    }


@mcp.tool()
async def search_products(text: str = "", free_from: list[str] | None = None, exclude_allergens: list[str] | None = None,
                          category: str | None = None, labels: list[str] | None = None,
                          exclude_terms: list[str] | None = None, limit: int = 20, ctx: Context = None) -> dict:
    """Search the Valio Aimo product catalog (static data: names, units, allergens, claims). No prices here.

    - text: words matched as substrings of Finnish/English/Swedish names and brand (Finnish works best:
      'maito' finds täysmaito, kevytmaito...). Every word of 3+ letters must match.
    - free_from: required nutritional claims, e.g. FREE_FROM_LACTOSE, FREE_FROM_GLUTEN, VEGAN, VEGETARIAN.
      Name search alone is not enough: 'laktoositon' also matches cocoa drinks and coffee milk.
    - exclude_allergens: allergen codes (AM milk, AW gluten cereals, AE eggs...) or groups (milk, gluten, nuts)
      that the product must not CONTAIN.
    - category: category code or prefix, e.g. '10400' (milk). Use category_counts in the result to narrow.
    - labels: required package labels, e.g. GOODS_FROM_FINLAND_BLUE_SWAN.
    - exclude_terms: drop products whose name contains these words (e.g. kahvi, kaakao, latte).
    Returns products with id, names, sales_unit, litres/kg per sales unit, allergens, claims, delivery
    reliability (0..1), CO2 per kg and Valio's listed substitutes.
    """
    p = _principal(ctx)
    req = _parse_args(
        lambda: SearchRequest(
            text=text, free_from=free_from or [], exclude_allergens=exclude_allergens or [],
            category=category, labels=labels or [], exclude_terms=exclude_terms or [], limit=limit,
        )
    )
    res = await _run(service.search_products, p, req)
    return res.model_dump(mode="json")


@mcp.tool()
async def check_offers(product_ids: list[str], delivery_date: str, quantity: float | None = None,
                       unit: str | None = None, ctx: Context = None, include_substitutes: bool = False,
                       required_claims: list[str] | None = None, exclude_allergens: list[str] | None = None,
                       postal_code: str | None = None, include_next_delivery: bool = False) -> dict:
    """Live price and availability for specific products (max 1000) and one delivery date (YYYY-MM-DD).

    Each offer has: unit_price (EUR per sales unit, without VAT), price_per_content_unit (EUR per L or KG),
    content_per_sales_unit, available_qty (None = unlimited or not reported), closing_time (order cutoff),
    logistic_model, and `orderable` with a `reason`:
      ok | cutoff_passed (the order cutoff for that date is already past) | no_availability_data |
      sales_block | insufficient_stock | later_date (earliest delivery is after the date) | no_price.
    Only orderable offers can be quoted (no_availability_data can be quoted but needs human approval).
    If you pass quantity and unit (L, KG, PCS or a sales unit code), the result also contains `plan`:
    up to three ranked plans (best, better, good) in sales units, split across products when stock is limited.
    Set include_substitutes to fetch live replacements for unavailable or insufficient stock.
    Catalog ingredient matches may be returned for selected produce when no Valio replacement is listed.
    Use required_claims and exclude_allergens for dietary constraints. Postal code adds a travel estimate.
    Set include_next_delivery to check later dates reported by Valio without changing the requested date.
    """
    p = _principal(ctx)
    req = _parse_args(lambda: OffersRequest(
        product_ids=product_ids, delivery_date=delivery_date, quantity=quantity, unit=unit,
        include_substitutes=include_substitutes, required_claims=required_claims or [],
        exclude_allergens=exclude_allergens or [], postal_code=postal_code,
        include_next_delivery=include_next_delivery))
    return compact_offers(await _run(service.check_offers, p, req))


@mcp.tool()
async def create_quote(delivery_date: str, lines: list[dict], need: dict | None = None, ctx: Context = None) -> dict:
    """Create a fixed-price quote, signed by the gateway (compact JWS, EdDSA).

    - delivery_date: YYYY-MM-DD.
    - lines: [{"product_id": "464073", "quantity": 1000}] with quantity in SALES units (use the plan from
      check_offers). Quantities are rounded up to the allowed lot size.
    - need (optional but recommended): the buyer's original need, e.g. {"item": "lactose-free milk",
      "quantity": 1000, "unit": "L", "delivery_date": "2026-11-16", "free_from": ["FREE_FROM_LACTOSE"],
      "preferred_product_ids": []}. With it the gateway checks coverage, claims and substitutions.
    Returns totals, expires_at (= earliest of price validity and order cutoffs) and policy_preview: what the
    buyer's mandate will decide (auto / needs_approval / reject) and why. Fails if a line is not orderable.
    """
    p = _principal(ctx, write=True)
    req = _parse_args(
        lambda: QuoteRequest(
            delivery_date=delivery_date,
            lines=[LineRequest(**l) for l in lines],
            need=Need(**need) if need else None,
        )
    )
    q = await _run(service.create_quote, p, req)
    return q.model_dump(mode="json")


@mcp.tool()
async def place_order(quote_id: str, agent_rationale: str, ctx: Context = None) -> dict:
    """Place an order from an unexpired quote. agent_rationale: one or two sentences on why this option was
    chosen; it is stored in the audit log for the human reviewer.

    The gateway re-checks availability and applies the buyer's mandate. Resulting status:
    confirmed (auto-approved), pending_approval (a human must approve; this is normal, do not retry or split
    the order), or rejected (with reasons). A quote can be used once.
    """
    p = _principal(ctx, write=True)
    if len(agent_rationale) > 1000:
        raise ToolError("Rationale must be at most 1,000 characters")
    order = await _run(service.place_order, p, quote_id, agent_rationale)
    return order.model_dump(mode="json")


@mcp.tool()
async def repeat_quote(order_id: str, delivery_date: str, ctx: Context = None) -> dict:
    """Create a new signed quote for a confirmed order on a new delivery date.
    Checks current stock, pricing, dietary constraints and recurring-order drift. Requires ordering permission.
    """
    principal = _principal(ctx, write=True)
    delivery = _parse_args(lambda: date.fromisoformat(delivery_date))
    quote = await _run(service.repeat_quote, principal, order_id, delivery)
    return quote.model_dump(mode="json")


@mcp.tool()
async def check_recurring_quote(quote_id: str, ctx: Context = None) -> dict:
    """Compare a buyer-owned signed quote with recent same-weekday confirmed orders.
    Results include per-SKU baselines and drift flags when enough history is available.
    """
    return await _run(service.check_recurring_quote, _principal(ctx), quote_id)


@mcp.tool()
async def get_order_status(order_id: str, ctx: Context = None) -> dict:
    """Current status of one of your orders: confirmed, pending_approval, rejected or expired, with the
    lines, totals and the policy decision with the rules that fired."""
    p = _principal(ctx)
    order = await _run(service.get_order, p, order_id)
    return order.model_dump(mode="json")


@mcp.tool()
async def get_audit_log(order_id: str, ctx: Context = None) -> dict:
    """Human-readable, hash-chained audit timeline of one of your orders (search, offers, quote, policy,
    approval, final status) plus a chain-integrity check."""
    p = _principal(ctx)
    res = await _run(service.get_audit_log, p, order_id)
    return {"order_id": order_id, "text": res["text"], "events": res["events"], "chain": res["chain"]}

@mcp.tool()
async def get_request_thread(order_id: str, ctx: Context = None) -> dict:
    """Read fulfillment status and the conversation for one of your buyer's submitted requests."""
    principal = _principal(ctx)
    order = await _run(service.get_order, principal, order_id)
    return await _run(workspace.ticket_activity, order)


@mcp.tool()
async def post_request_message(order_id: str, text: str, ctx: Context = None) -> dict:
    """Post a message to Aimo in the conversation for one of your buyer's submitted requests."""
    principal = _principal(ctx, write=True)
    message = _parse_args(lambda: workspace.Message(text=text))
    return await _run(workspace.send_message, principal, order_id, message)
