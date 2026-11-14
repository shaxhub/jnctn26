import asyncio

import httpx

from gateway import gemini


def test_gemini_uses_carbon_and_parses_structured_recipe(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    client_class = httpx.AsyncClient

    def respond(request):
        assert request.url.path.endswith("/gemini-4-carbon:generateContent")
        assert request.headers["x-goog-api-key"] == "unit-test-key"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text":
            '{"recipes":[{"name":"salad","servings":4,"ingredients":[{"name":"tomato","amount":500,"unit":"g"}]}]}'
        }]}}]})

    monkeypatch.setattr(gemini.httpx, "AsyncClient",
                        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(gemini.extract("Tomato salad", "2026-11-14"))
    assert result.recipes[0].servings == 4
    assert result.recipes[0].ingredients[0].amount == 500
