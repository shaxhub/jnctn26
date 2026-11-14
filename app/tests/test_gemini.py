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
