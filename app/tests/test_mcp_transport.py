import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from test_portals import gateway


def test_quote_signing_refuses_nonfinite_json():
    from gateway.quotes import sign

    with pytest.raises(ValueError, match="Out of range float values"):
        sign({"total_net": float("inf")})


def test_mcp_initialize_and_tool_validation(gateway):
    from gateway.api import app

    async def check():
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000",
                        headers={"Accept": "application/json, text/event-stream"}) as http,
        ):
            async def rpc(method, params, request_id=1):
                response = await http.post("/mcp", json={
                    "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
                })
                assert response.status_code == 200, response.text
                return response.json()["result"]

            assert (await http.post("/mcp", json={})).status_code == 401
            http.headers["Authorization"] = "Bearer demo-hotel-key"
            initialized = await rpc("initialize", {"protocolVersion": "2025-03-26",
                                    "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}})
            http.headers["MCP-Protocol-Version"] = initialized["protocolVersion"]
            notification = await http.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert notification.status_code == 202
            tools = await rpc("tools/list", {})
            assert {"check_offers", "create_quote", "source_ingredients"} <= {tool["name"] for tool in tools["tools"]}
            mandate = await rpc("tools/call", {"name": "get_my_mandate", "arguments": {}})
            assert not mandate.get("isError")
            for name, args, expected in (
                ("check_offers", {"product_ids": ["milk"], "delivery_date": "2026-11-16",
                                  "quantity": 1_000_001, "unit": "ST"}, "1000000"),
                ("create_quote", {"delivery_date": "2026-11-16",
                                  "lines": [{"product_id": "milk", "quantity": 1_000_001}]}, "1000000"),
                ("source_ingredients", {"servings": 1, "delivery_date": "2026-11-13",
                                        "dishes": ["Tomato salad"]}, "future delivery date"),
                ("source_ingredients", {"servings": 1, "delivery_date": "2026-11-16", "recipes": [{
                    "name": "Small sample", "servings": 5000,
                    "ingredients": [{"name": "potato", "amount": 0.001, "unit": "g"}],
                }]}, "below supported precision"),
            ):
                error = await rpc("tools/call", {"name": name, "arguments": args})
                assert error["isError"]
                assert expected in error["content"][0]["text"]

    asyncio.run(check())
