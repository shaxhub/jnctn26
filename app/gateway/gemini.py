"""Gemini 4 Carbon extracts structured purchasing input. The gateway controls all writes."""
import os

import httpx
from pydantic import BaseModel, Field

from .kitchen import Recipe
from .models import Need

MODEL = "gemini-4-carbon"
LABEL = "Gemini 4 Carbon"


class Interpretation(BaseModel):
    need: Need | None = None
    recipes: list[Recipe] = Field(default_factory=list, max_length=12)
    servings: int | None = Field(None, ge=1, le=5000)


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


async def _structured(text: str, instruction: str, schema):
    async with httpx.AsyncClient(timeout=35) as http:
        response = await http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()},
            json={"systemInstruction": {"parts": [{"text": instruction}]},
                  "contents": [{"parts": [{"text": text}]}],
                  "generationConfig": {"responseMimeType": "application/json",
                                       "responseJsonSchema": schema.model_json_schema()}},
        )
        response.raise_for_status()
    parts = response.json()["candidates"][0]["content"]["parts"]
    output = "".join(part.get("text", "") for part in parts if not part.get("thought"))
    return schema.model_validate_json(output)

async def extract(text: str, today) -> Interpretation:
    return await _structured(text, (
        f"Today is {today}. Extract one purchasing Need or pasted recipes. Use Finnish catalog terms. "
        "Extract explicitly stated yields and metric ingredients. Use recipe yield if no target is stated. "
        "Never invent products or submit orders."
    ), Interpretation)


async def suggest_edit(text: str, draft: dict):
    import json
    from .workspace import DraftEdit

    snapshot = {"date": draft["delivery_date"], "lines": [
        {key: line[key] for key in ("product_id", "name", "quantity", "sales_unit")}
        for line in draft["lines"]]}
    return await _structured(json.dumps({"draft": snapshot, "request": text}),
        "Propose edits to the existing draft. Use only existing product codes and sales units. "
        "Return all remaining quantities and the ISO delivery date. Never submit an order.", DraftEdit)
