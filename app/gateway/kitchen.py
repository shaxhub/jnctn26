"""Compile kitchen requirements and source them without creating purchasing commitments."""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from . import audit, service
from .auth import Principal
from .menu_catalog import DISH_ALIASES, DISHES, INGREDIENT_ALIASES, SEARCH_TERMS, SWAPS
from .models import Need, Offer, SearchRequest, expand_allergens
from .planner import make_plans
from .search import normalize_claims, search

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Unit = Literal["g", "kg", "ml", "dl", "l", "pcs"]
UNITS = {"g": ("KG", .001), "kg": ("KG", 1), "ml": ("L", .001), "dl": ("L", .1), "l": ("L", 1), "pcs": ("PCS", 1)}
LINE = re.compile(r"^([0-9]+(?:[.,][0-9]+)?)\s*(kg|g|ml|dl|l|pcs)\s+(.+)$", re.I)
CATEGORIES = {
    **dict.fromkeys(("potato", "carrot", "parsnip", "turnip", "onion", "red onion", "shallot", "leek",
                     "basil", "dill", "parsley", "lettuce", "cucumber", "tomato", "zucchini", "bell pepper",
                     "apple", "pear", "orange", "lemon", "lime", "spinach", "mushroom", "cabbage", "beetroot", "cauliflower", "broccoli"), "174"),
    "salmon": "187", "cream": "10401", "milk": "10400", "rapeseed oil": "10530", "butter": "105",
}
EXCLUDED = {
    "potato": ("muusi", "sose", "keitto", "kermaperun"), "carrot": ("keitto", "sose"),
    "tomato": ("kastike", "murska", "keitto", "kuutio"), "salmon": ("savu", "graavi", "kypsä", "maustettu"),
    "cream": ("vaahto", "vanilja", "suklaa"), "milk": ("kahvi", "latte", "kaakao", "piimä"),
    "butter": ("margariini", "voileipä"),
}


class Ingredient(BaseModel):
    name: Text
    amount: float = Field(ge=.001, le=100_000, allow_inf_nan=False)
    unit: Unit


class Recipe(BaseModel):
    name: Text
    servings: int = Field(ge=1, le=5000)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=30)


class KitchenRequest(BaseModel):
    servings: int = Field(ge=1, le=5000)
    dishes: list[Text] = Field(default_factory=list, max_length=12)
    recipes: list[Recipe] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def check_input(self):
        if not self.dishes and not self.recipes:
            raise ValueError("Provide at least one dish or recipe")
        return self


class SourceRequest(KitchenRequest):
    delivery_date: date
    exclude_allergens: list[Text] = Field(default_factory=list, max_length=20)
    required_claims: list[Text] = Field(default_factory=list, max_length=10)
    unavailable_ingredients: list[Text] = Field(default_factory=list, max_length=30)


def capabilities() -> dict:
    return {"dish_templates": sorted(DISHES), "dish_aliases": DISH_ALIASES,
            "recipe_units": list(UNITS), "maximum_servings_per_dish": 5000,
            "culinary_swaps": [{"dish": dish, "ingredient": ingredient, "replacement": replacement,
                                "culinary_note": note} for (dish, ingredient), (replacement, note) in SWAPS.items()]}


def canonical_name(text: str) -> str:
    name = " ".join(text.lower().split())
    return INGREDIENT_ALIASES.get(name, name)


def dish_key(text: str) -> str:
    key = " ".join(text.lower().split())
    return DISH_ALIASES.get(key, key)


def compile_ingredients(request: KitchenRequest) -> dict:
    recipes = {dish_key(recipe.name): recipe for recipe in request.recipes}
    if len(recipes) != len(request.recipes):
        raise service.GatewayError(422, "Use a unique name for each recipe")
    names = list(dict.fromkeys([dish_key(name) for name in request.dishes] + list(recipes)))
    unresolved, rows = [], {}
    for name in names:
        recipe = recipes.get(name)
        template = DISHES.get(name)
        if recipe:
            ingredients = recipe.ingredients
            factor = request.servings / recipe.servings
        elif template:
            ingredients = [Ingredient(name=item, amount=amount, unit=unit) for item, amount, unit in template]
            factor = request.servings
        else:
            unresolved.append(name)
            continue
        for ingredient in ingredients:
            key = canonical_name(ingredient.name)
            unit, multiplier = UNITS[ingredient.unit]
            row = rows.setdefault((key, unit), {"ingredient": key, "quantity": 0.0, "unit": unit,
                                                 "dishes": [], "estimated": False})
            amount = ingredient.amount * factor * multiplier
            row["quantity"] += amount
            per_dish = row.setdefault("quantities_by_dish", {})
            per_dish[name] = per_dish.get(name, 0) + amount
            row["estimated"] |= recipe is None
            if name not in row["dishes"]:
                row["dishes"].append(name)
    if len(rows) > 40:
        raise service.GatewayError(422, "Use at most 40 distinct ingredient and unit combinations")
    for row in rows.values():
        row["quantity"] = round(row["quantity"], 9)
        row["quantities_by_dish"] = {name: round(amount, 9) for name, amount in row["quantities_by_dish"].items()}
    return {"servings_per_dish": request.servings, "ingredients": list(rows.values()),
            "unresolved_dishes": unresolved, "known_dishes": sorted(DISHES)}


def recipes_from_text(text: str, servings: int) -> list[Recipe]:
    """Parse named blocks with an amount and unit on each ingredient line."""
    recipes = []
    for block in re.split(r"\n\s*\n", text.strip()):
        if not block.strip():
            continue
        heading, *lines = block.splitlines()
        match = re.fullmatch(r"(.+?)\s*\(([0-9]+)\)\s*", heading.strip())
        name, yield_count = (match[1], int(match[2])) if match else (heading, servings)
        ingredients = []
        for line in lines:
            item = LINE.fullmatch(line.strip().removeprefix("- ").strip())
            if not item:
                raise service.GatewayError(422, f"Use amount, unit and ingredient on one line. Check: {line[:100]}")
            ingredients.append(Ingredient(name=item[3], amount=float(item[1].replace(",", ".")), unit=item[2].lower()))
        recipes.append(Recipe(name=name, servings=yield_count, ingredients=ingredients))
    return recipes


def _candidate_ids(name: str, excluded: list[str], claims: list[str]) -> list[str]:
    term = SEARCH_TERMS.get(name, name)
    if len(term) < 3:
        return []
    result = search(SearchRequest(text=term, category=CATEGORIES.get(name), limit=8,
                                  free_from=claims, exclude_allergens=excluded,
                                  exclude_terms=list(EXCLUDED.get(name, ()))))
    return [item.id for item in result.results]


def _pick(principal: Principal, name: str, row: dict, offers: list[Offer], request: SourceRequest) -> dict | None:
    forbidden = set(expand_allergens(request.exclude_allergens + principal.mandate.forbidden_allergens))
    claims = set(normalize_claims(request.required_claims))
    usable = [offer for offer in offers if offer.orderable and not offer.stale
              and not forbidden.intersection(offer.allergens_contains + offer.allergens_may_contain)
              and claims.issubset(offer.claims)
              and (principal.mandate.allowed_categories is None or any(
                  (offer.category or "").startswith(category) for category in principal.mandate.allowed_categories))]
    need = Need(item=name, quantity=row["quantity"], unit=row["unit"], delivery_date=request.delivery_date)
    plans = make_plans(need, usable).plans
    if not plans:
        return None
    chosen = max(plans, key=lambda plan: plan.coverage)
    selected = {line.product_id for line in chosen.lines}
    evidence = [offer.model_dump(mode="json") for offer in usable if offer.product_id in selected]
    return {"plan": chosen.model_dump(mode="json"), "offers": evidence}


def source_ingredients(principal: Principal, request: SourceRequest) -> dict:
    result = compile_ingredients(request)
    rows = result["ingredients"]
    excluded = request.exclude_allergens + principal.mandate.forbidden_allergens
    forced = {canonical_name(name) for name in request.unavailable_ingredients}
    options = {}
    for row in rows:
        name = row["ingredient"]
        options[name] = list(dict.fromkeys(SWAPS[(dish, name)] for dish in row["dishes"] if (dish, name) in SWAPS))
    names = {row["ingredient"] for row in rows} - forced
    names.update(name for alternatives in options.values() for name, _ in alternatives if name not in forced)
    ids_by_name = {name: _candidate_ids(name, excluded, request.required_claims) for name in sorted(names)}
    ids = list(dict.fromkeys(pid for matches in ids_by_name.values() for pid in matches))
    offers, checked_at = service.get_offers(ids, request.delivery_date) if ids else ([], None)
    by_id = {offer.product_id: offer for offer in offers}

    def match(name: str, row: dict) -> dict | None:
        return _pick(principal, name, row, [by_id[pid] for pid in ids_by_name.get(name, []) if pid in by_id], request)

    for row in rows:
        name = row["ingredient"]
        direct = match(name, row)
        if direct and direct["plan"]["coverage"] >= 0.9999:
            row.update(status="available", sourcing=direct, alternatives=[])
            continue
        alternatives = []
        for replacement, note in options[name]:
            compatible = [dish for dish in row["dishes"] if SWAPS.get((dish, name)) == (replacement, note)]
            amount = sum(row["quantities_by_dish"][dish] for dish in compatible)
            available = match(replacement, {**row, "quantity": amount})
            if available:
                alternatives.append({"ingredient": replacement, "culinary_note": note, "compatible_dishes": compatible,
                                     "suggested_quantity": round(amount, 9), "unit": row["unit"],
                                     "review_required": True, **available})
        matched = [by_id[pid] for pid in ids_by_name.get(name, []) if pid in by_id]
        if direct:
            status = "partial"
        elif name in forced:
            status = "stockout"
        elif not matched:
            status = "unmatched"
        elif all(offer.reason.value == "insufficient_stock" and not offer.stale for offer in matched):
            status = "stockout"
        else:
            status = "unverified"
        row.update(status=status, sourcing=direct, alternatives=alternatives)

    log_plan(principal, request, result, delivery_date=request.delivery_date.isoformat())
    return {**result, "delivery_date": request.delivery_date.isoformat(),
            "checked_at": checked_at.isoformat() if checked_at else None,
            "cached_offers_excluded": any(offer.stale for offer in offers),
            "notes": ["Dish templates estimate quantities. Check kitchen stock and actual recipe yield.",
                      "Each ingredient is sourced independently. Recheck combined quantities before ordering.",
                      "Culinary alternatives require review and apply only to the dishes listed."]}


def log_plan(principal: Principal, request: KitchenRequest, result: dict, **context) -> None:
    audit.log("KITCHEN_PLAN", principal.actor, {"dishes": request.dishes + [recipe.name for recipe in request.recipes],
              "ingredient_count": len(result["ingredients"]), **context}, buyer_id=principal.buyer_id)
