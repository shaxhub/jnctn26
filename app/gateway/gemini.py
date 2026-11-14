"""Structured Gemini interactions for input interpretation. Order review lives in decisions.py."""
import functools
import json
import os
from datetime import date

import httpx
from pydantic import BaseModel, Field

from .models import Need

MODEL = "gemini-4-hydrogen"
LABEL = "Gemini 4 Hydrogen (Medium)"
INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _provider_schema(value, names=False):
    """Keep structural constraints in Gemini and enforce value bounds locally.

    `names` marks a mapping such as `properties`, whose keys are field names and not schema keywords.
    """
    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    ignored = {"title", "default", "format", "pattern", "minimum", "maximum",
               "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems"}
    schema = {key: _provider_schema(item, not names and key in ("properties", "$defs"))
              for key, item in value.items() if names or key not in ignored}
    if not names and value.get("format") == "date":
        # The format keyword is not sent, so state the expected form in the description.
        schema["description"] = " ".join(filter(None, [value.get("description"), "ISO 8601 date, YYYY-MM-DD."]))
    return schema


@functools.cache
def _schema(model) -> dict:
    return _provider_schema(model.model_json_schema())


def _request(text: str, instruction: str, schema) -> dict:
    return {
        "headers": {"x-goog-api-key": os.getenv("GEMINI_API_KEY", "").strip(), "Api-Revision": "2026-05-20"},
        "json": {"model": MODEL, "input": text, "system_instruction": instruction, "store": False,
                 "generation_config": {"thinking_level": "medium"},
                 "response_format": {"type": "text", "mime_type": "application/json",
                                     "schema": _schema(schema)}},
    }


def _parse(response: httpx.Response, schema):
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("status") != "completed":
        raise ValueError("Gemini did not complete the interaction")
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise ValueError("Gemini did not return interaction steps")
    output = "".join(part.get("text", "") for step in steps
                     if isinstance(step, dict) and step.get("type") == "model_output"
                     for part in (step.get("content") or ())
                     if isinstance(part, dict) and part.get("type") == "text")
    return schema.model_validate_json(output)


async def _structured(text: str, instruction: str, schema):
    async with httpx.AsyncClient(timeout=35) as http:
        response = await http.post(INTERACTIONS, **_request(text, instruction, schema))
    return _parse(response, schema)


@functools.cache
def _interpretation():
    from .kitchen import Recipe  # kitchen imports service, which imports this module

    class Interpretation(BaseModel):
        need: Need | None = None
        recipes: list[Recipe] = Field(default_factory=list, max_length=12)
        servings: int | None = Field(None, ge=1, le=5000)
        delivery_date: date | None = None
        exclude_allergens: list[str] = Field(default_factory=list, max_length=20)
        ticket_name: str | None = Field(None, max_length=100)

    return Interpretation


async def extract(text: str, today, language: str | None = None):
    return await _structured(text, (
        f"Today is {today}. Extract one purchasing Need or pasted recipes. Use Finnish catalog terms. "
        "Extract explicitly stated yields and metric ingredients. Use recipe yield if no target is stated. "
        "When the buyer describes a goal rather than naming a product, infer the shopping list by proposing recipes "
        "with metric ingredient quantities and catalog-friendly ingredient names. Include all requested components. "
        "Respect stated dietary constraints in every relevant recipe. If groups overlap or overlap is unspecified, "
        "prefer one shared set of recipes that respects all restrictions. Put allergens to avoid in exclude_allergens. "
        "For a direct product request, return need instead. "
        f"Write recipe titles and a short ticket_name in {language or 'the same language as the buyer'}. "
        "Set servings to the requested headcount, and resolve an explicit weekday or date into delivery_date. "
        "Never invent products or submit orders."
    ), _interpretation())


class BasketName(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


async def name_basket(products: list[str], language: str) -> str | None:
    if enabled():
        try:
            result = await _structured(json.dumps(products),
                f"Give this purchasing basket a short descriptive title in {language}. Use only the product names.",
                BasketName)
            return result.name.strip()
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            pass
    return None


async def ground_recipes(text: str, recipes, candidates: list[dict]):
    return await _structured(json.dumps({"request": text, "proposal": [recipe.model_dump() for recipe in recipes],
                                        "catalog": candidates}),
        "Revise this inferred meal using only the provided catalog. In each ingredient name return the exact "
        "catalog product id. Keep the requested meal components, diet and headcount. Preserve meaningful staple "
        "and protein roles. If the catalog cannot cover the request, return an empty recipes list. "
        "Do not replace explicitly named ingredients or invent items.", _interpretation())


async def suggest_edit(text: str, draft: dict):
    from .workspace import DraftEdit

    snapshot = {"date": draft["delivery_date"], "lines": [
        {key: line[key] for key in ("product_id", "name", "quantity", "sales_unit")}
        for line in draft["lines"]]}
    return await _structured(json.dumps({"draft": snapshot, "request": text}),
        "Propose edits to the existing draft. Use only existing product codes and sales units. "
        "Return all remaining quantities and the ISO delivery date. Never submit an order.", DraftEdit)
