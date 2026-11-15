import asyncio
import json

from httpx import ASGITransport, AsyncClient
import pytest

from test_portals import gateway


def test_quote_signing_refuses_nonfinite_json():
    from gateway.quotes import sign

    with pytest.raises(ValueError, match="Out of range float values"):
        sign({"total_net": float("inf")})


def test_mcp_initialize_and_tool_validation(gateway):
    from gateway.api import app
    from gateway.auth import principal_for_key
    from gateway.preferences import Preferences
    from gateway.workspace import save_settings

    profile_address = "Profile kitchen, Testikatu 1, 00100 Helsinki"
    save_settings(Preferences(address=profile_address), principal_for_key("demo-hotel-client-key"))

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
            order_tool = next(tool for tool in tools["tools"] if tool["name"] == "place_order")
            assert {"delivery_address", "postal_code"} <= order_tool["inputSchema"]["properties"].keys()
            mandate = await rpc("tools/call", {"name": "get_my_mandate", "arguments": {}})
            assert not mandate.get("isError")
            for postcode, arguments in (
                ("00580", {"address": "00580 Helsinki"}),
                ("22100", {"postal_code": "22100"}),
                ("99990", {"postal_code": "99990"}),
            ):
                estimate = await rpc("tools/call", {"name": "estimate_delivery", "arguments": arguments})
                assert not estimate.get("isError")
                eta = json.loads(estimate["content"][0]["text"])
                assert eta["postal_code"] == postcode
                assert eta["status"] == "estimated"
                assert eta["distance_km"] > 0
                assert eta["travel_minutes_max"] > eta["travel_minutes_min"]
            missing = await rpc("tools/call", {"name": "estimate_delivery", "arguments": {"postal_code": "00000"}})
            assert not missing.get("isError")
            assert json.loads(missing["content"][0]["text"])["status"] == "estimate_unavailable"
            for name, args, expected in (
                ("estimate_delivery", {"postal_code": "580"}, "five-digit Finnish postal code"),
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

            async def call(name, arguments):
                result = await rpc("tools/call", {"name": name, "arguments": arguments})
                assert not result.get("isError"), result
                return json.loads(result["content"][0]["text"])

            quote_args = {"delivery_date": "2026-11-16", "lines": [{"product_id": "milk", "quantity": 1}]}
            quote = await call("create_quote", quote_args)
            order_args = {"quote_id": quote["quote_id"], "agent_rationale": "Requested by the buyer."}
            for invalid_address in (
                {"delivery_address": "Testikuja 15 B 089"},
                {"delivery_address": "00580 Helsinki"},
                {"delivery_address": "Testikuja, 00580 Helsinki"},
                {"delivery_address": "Testikuja 15 B 089, REF00580"},
                {"postal_code": "00580", "delivery_address": "Helsinki"},
                {"delivery_address": ""},
                {"postal_code": "580", "delivery_address": "Testikuja 15 B 089"},
                {"postal_code": "00580", "delivery_address": "   "},
                {"postal_code": "00580", "delivery_address": "Testikatu 1, 00100 Helsinki"},
                {"postal_code": "00580", "delivery_address": "x" * 240},
            ):
                error = await rpc("tools/call", {"name": "place_order", "arguments": order_args | invalid_address})
                assert error["isError"], error

            order = await call("place_order", order_args | {
                "delivery_address": "Testikuja 15 B 089", "postal_code": "00580",
            })
            assert order["delivery_address"] == "Testikuja 15 B 089, 00580"
            status = await call("get_order_status", {"order_id": order["order_id"]})
            assert status["delivery_address"] == order["delivery_address"]

            for overrides, expected in (
                ({}, profile_address),
                ({"delivery_address": "Testikuja 15, 00580 Helsinki"}, "Testikuja 15, 00580 Helsinki"),
                ({"delivery_address": "Testikuja 15, 00580 Helsinki", "postal_code": "00580"},
                 "Testikuja 15, 00580 Helsinki"),
            ):
                quote = await call("create_quote", quote_args)
                order = await call("place_order", order_args | {"quote_id": quote["quote_id"]} | overrides)
                assert order["delivery_address"] == expected

            quote = await call("create_quote", quote_args)
            save_settings(Preferences(address="Testikuja 15 B 089"), principal_for_key("demo-hotel-client-key"))
            error = await rpc("tools/call", {"name": "place_order", "arguments": order_args | {
                "quote_id": quote["quote_id"],
            }})
            assert error["isError"]
            assert "street address" in error["content"][0]["text"]

    asyncio.run(check())


def test_readonly_bearer_key_and_mcp_cors(gateway, monkeypatch):
    from datetime import date
    from gateway import service
    from gateway.api import app
    from gateway.auth import principal_for_key
    from gateway.models import QuoteRequest

    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://chatgpt.com")

    buyer = principal_for_key("demo-hotel-client-key")
    quote = service.create_quote(buyer, QuoteRequest(delivery_date=date(2026, 11, 16),
                                                     lines=[{"product_id": "milk", "quantity": 5}]))
    order = service.place_order(buyer, quote.quote_id)

    async def check():
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000",
                        headers={"Accept": "application/json, text/event-stream"}) as http,
        ):
            # CORS preflight and 401 challenge headers for allowed browser origins vs forbidden origins.
            assert (await http.options("/mcp", headers={"Origin": "https://evil.example"})).status_code == 403
            preflight = await http.options("/mcp", headers={
                "Origin": "https://chatgpt.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            })
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "https://chatgpt.com"
            assert "POST" in preflight.headers["access-control-allow-methods"]
            assert "Authorization" in preflight.headers["access-control-allow-headers"]
            challenge = await http.post("/mcp", json={}, headers={"Origin": "https://chatgpt.com"})
            assert challenge.status_code == 401
            assert challenge.headers["access-control-allow-origin"] == "https://chatgpt.com"
            assert "WWW-Authenticate" in challenge.headers["access-control-expose-headers"]

            # Issue a read-only agent Bearer credential (can_order=False) and verify MCP read-only enforcement.
            issued = await http.post("/client/agent-credentials",
                                     headers={"X-API-Key": "demo-hotel-client-key"},
                                     json={"label": "Read-only monitor", "can_order": False})
            assert issued.status_code == 201
            ro_secret = issued.json()["secret"]

            for token in ("demo-hotel-lookup-key", ro_secret):
                headers = {"Authorization": f"Bearer {token}"}
                init_res = await http.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "pytest", "version": "1"}},
                })
                assert init_res.status_code == 200
                headers["MCP-Protocol-Version"] = init_res.json()["result"]["protocolVersion"]
                tools = (await http.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
                })).json()["result"]["tools"]
                names = {tool["name"] for tool in tools}
                assert "check_offers" in names
                assert names.isdisjoint({"create_quote", "place_order", "repeat_quote", "post_request_message"})
                assert all(tool["annotations"]["readOnlyHint"] for tool in tools)

                mandate_res = (await http.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "get_my_mandate", "arguments": {}},
                })).json()["result"]
                assert not mandate_res.get("isError")
                mandate_data = json.loads(mandate_res["content"][0]["text"])
                assert set(mandate_data["allowed_tools"]).isdisjoint(
                    {"create_quote", "place_order", "repeat_quote", "post_request_message"}
                )

                for write_tool, args in (
                    ("post_request_message", {"order_id": order.order_id, "text": "Should be blocked"}),
                    ("create_quote", {"delivery_date": "2026-11-16", "lines": [{"product_id": "milk", "quantity": 1}]}),
                ):
                    denied = (await http.post("/mcp", headers=headers, json={
                        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": write_tool, "arguments": args},
                    })).json()["result"]
                    assert denied["isError"]
                    assert "read-only" in denied["content"][0]["text"]

    asyncio.run(check())
