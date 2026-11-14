import asyncio
import json

import httpx

from gateway import gemini


def test_gemini_uses_hydrogen_medium_and_parses_structured_recipe(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    client_class = httpx.AsyncClient

    def respond(request):
        assert request.url.path == "/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == "unit-test-key"
        body = json.loads(request.content)
        assert body["model"] == "gemini-4-hydrogen"
        assert body["generation_config"] == {"thinking_level": "medium"}
        assert body["store"] is False
        return httpx.Response(200, json={"status": "completed", "steps": [{"type": "model_output",
            "content": [{"type": "text", "text":
            '{"recipes":[{"name":"salad","servings":4,"ingredients":[{"name":"tomato","amount":500,"unit":"g"}]}]}'
        }]}]})

    monkeypatch.setattr(gemini.httpx, "AsyncClient",
                        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(gemini.extract("Tomato salad", "2026-11-14"))
    assert result.recipes[0].servings == 4
    assert result.recipes[0].ingredients[0].amount == 500


def test_provider_schema_keeps_property_names_and_states_date_format():
    from datetime import date

    from pydantic import BaseModel, Field

    class Note(BaseModel):
        title: str = Field(max_length=40)
        format: str = "plain"
        due: date

    schema = gemini._provider_schema(Note.model_json_schema())
    assert set(schema["properties"]) == {"title", "format", "due"}
    assert schema["required"] == ["title", "due"]
    assert "title" not in schema and schema["properties"]["title"] == {"type": "string"}
    assert schema["properties"]["format"] == {"type": "string"}
    assert schema["properties"]["due"] == {"type": "string", "description": "ISO 8601 date, YYYY-MM-DD."}


def test_interpretation_schema_is_built_once():
    assert gemini._interpretation() is gemini._interpretation()
    assert gemini._schema(gemini._interpretation()) is gemini._schema(gemini._interpretation())
    need = gemini._schema(gemini._interpretation())["$defs"]["Need"]["properties"]
    assert "YYYY-MM-DD" in need["delivery_date"]["description"] and "format" not in need["delivery_date"]
