"""Structured Gemini interactions for input interpretation and approval review."""
import json
import os
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .models import Need

MODEL = "gemini-4-hydrogen"
LABEL = "Gemini 4 Hydrogen (Medium)"
INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"


class ApprovalAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["approve", "needs_review"]
    concern: Literal["none", "fulfillment_margin", "combined_handling", "evidence_inconsistency"]


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _provider_schema(value):
    """Keep structural constraints in Gemini and enforce value bounds locally."""
    if isinstance(value, list):
        return [_provider_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    ignored = {"title", "default", "format", "pattern", "minimum", "maximum",
               "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "minItems", "maxItems"}
    return {key: _provider_schema(item) for key, item in value.items() if key not in ignored}


def _request(text: str, instruction: str, schema) -> dict:
    return {
        "headers": {"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip(), "Api-Revision": "2026-05-20"},
        "json": {"model": MODEL, "input": text, "system_instruction": instruction, "store": False,
                 "generation_config": {"thinking_level": "medium"},
                 "response_format": {"type": "text", "mime_type": "application/json",
                                     "schema": _provider_schema(schema.model_json_schema())}},
    }


def _parse(response: httpx.Response, schema):
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("status") != "completed":
        raise ValueError("Gemini did not complete the interaction")
    output = "".join(part["text"] for step in data["steps"] if step["type"] == "model_output"
                     for part in step["content"] if part["type"] == "text")
    return schema.model_validate_json(output)


async def _structured(text: str, instruction: str, schema):
    async with httpx.AsyncClient(timeout=35) as http:
        response = await http.post(INTERACTIONS, **_request(text, instruction, schema))
    return _parse(response, schema)


def review_approval(evidence: dict) -> ApprovalAdvice:
    instruction = (
        "Review structured wholesale fulfillment evidence. Local rules enforce buyer mandates and safety. "
        "Recommend needs_review only for a concrete combination of timing, handling or evidence risks "
        "in the supplied facts. Do not infer missing warehouse data. If no concern exists, return approve and none."
    )
    with httpx.Client(timeout=8) as http:
        response = http.post(INTERACTIONS, **_request(json.dumps(evidence), instruction, ApprovalAdvice))
    result = _parse(response, ApprovalAdvice)
    if (result.recommendation == "approve") != (result.concern == "none"):
        raise ValueError("Inconsistent Gemini approval recommendation")
    return result


async def extract(text: str, today):
    from .kitchen import Recipe

    class Interpretation(BaseModel):
        need: Need | None = None
        recipes: list[Recipe] = Field(default_factory=list, max_length=12)
        servings: int | None = Field(None, ge=1, le=5000)

    return await _structured(text, (
        f"Today is {today}. Extract one purchasing Need or pasted recipes. Use Finnish catalog terms. "
        "Extract explicitly stated yields and metric ingredients. Use recipe yield if no target is stated. "
        "Never invent products or submit orders."
    ), Interpretation)


async def suggest_edit(text: str, draft: dict):
    from .workspace import DraftEdit

    snapshot = {"date": draft["delivery_date"], "lines": [
        {key: line[key] for key in ("product_id", "name", "quantity", "sales_unit")}
        for line in draft["lines"]]}
    return await _structured(json.dumps({"draft": snapshot, "request": text}),
        "Propose edits to the existing draft. Use only existing product codes and sales units. "
        "Return all remaining quantities and the ISO delivery date. Never submit an order.", DraftEdit)
