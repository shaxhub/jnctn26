import asyncio
from datetime import date

from httpx import ASGITransport, AsyncClient

from gateway import service
from gateway.auth import principal_for_key
from gateway.models import QuoteRequest
from test_portals import gateway


def test_shared_portal_request_tracking_and_settings(gateway):
    from gateway.api import app

    hotel = {"X-API-Key": "demo-hotel-client-key"}
    hospital = {"X-API-Key": "demo-hospital-client-key"}
    admin = {"X-API-Key": "test-admin-credential"}
    principal = principal_for_key(hotel["X-API-Key"])
    request = QuoteRequest(delivery_date=date(2026, 11, 16), lines=[{"product_id": "milk", "quantity": 5}])
    draft = service.create_quote(principal, request)

    async def verify():
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://portal") as client,
            AsyncClient(transport=ASGITransport(app=app), base_url="http://portal") as aimo,
        ):
            assert (await client.get("/admin/")).status_code == 200
            assert (await client.get("/assets/admin.js")).status_code == 200
            assert (await client.get("/operations/activity", headers=hotel)).status_code == 401
            assert (await aimo.get("/client/settings", headers=admin)).status_code == 401
            assert (await client.get("/client/drafts", headers=hospital)).json() == []
            from gateway.auth import principal_for_mcp_key
            issued = await client.post("/client/agent-credentials", headers=hotel, json={"label": "Kitchen agent"})
            assert issued.status_code == 201
            credential = issued.json()
            agent = principal_for_mcp_key(credential["secret"])
            assert agent.buyer_id == "hotel" and not agent.can_order and agent.credential_id == credential["id"]
            listed = await client.get("/client/agent-credentials", headers=hotel)
            assert credential["secret"] not in listed.text
            assert (await client.get("/client/agent-credentials", headers=hospital)).json() == []
            revoke = "/client/agent-credentials/" + credential["id"] + "/revoke"
            assert (await client.post(revoke, headers=hospital)).status_code == 404
            assert (await client.post(revoke, headers=hotel)).status_code == 200
            assert principal_for_mcp_key(credential["secret"]) is None
            name_url = f"/client/drafts/{draft.quote_id}/name"
            assert (await client.post(name_url, headers=hospital, json={"name": "Other kitchen"})).status_code == 404
            named = await client.post(name_url, headers=hotel, json={"name": "Monday milk"})
            assert named.status_code == 200 and named.json()["name"] == "Monday milk"
            edited = await client.post(f"/client/drafts/{draft.quote_id}/edit", headers=hotel,
                                       json={"delivery_date": "2026-11-16", "quantities": {"milk": 8}})
            assert edited.status_code == 200, edited.text
            revised = edited.json()["quote_id"]
            assert edited.json()["name"] == "Monday milk"
            assert [item["quote_id"] for item in (await client.get("/client/drafts", headers=hotel)).json()] == [revised]
            submitted = await client.post("/client/tickets/submit", headers=hotel, json={"quote_id": revised})
            assert submitted.status_code == 200, submitted.text
            order_id = submitted.json()["order_id"]
            assert submitted.json()["name"] == "Monday milk"
            url = "/client/requests/" + order_id
            ops = "/operations/orders/" + order_id
            assert (await client.get(url, headers=hospital)).status_code == 404
            assert (await client.get(url, headers=hotel)).json()["stage"] == "registered"
            assert (await aimo.post(ops + "/stage", headers=admin, json={"stage": "arrived"})).status_code == 409
            assert (await aimo.post(ops + "/stage", headers=admin, json={"stage": "retrieving"})).json()["stage"] == "retrieving"
            await aimo.post(ops + "/messages", headers=admin, json={"text": "Picking your order"})
            note = await client.post(url + "/messages", headers=hotel, json={"text": "Use the side entrance"})
            assert [item["side"] for item in note.json()["messages"]] == ["aimo", "client"]
            assert (await client.get("/client/dashboard", headers=hotel)).json()["stages"] == {"retrieving": 1}
            result = await client.get("/client/analytics?year=2026", headers=hotel)
            assert result.json()["months"][10]["net"] == 16
            saved = await client.post("/client/settings", headers=hotel,
                                      json={"agent_self_order": False, "theme": "dark", "recurring_prompt": "Milk tomorrow"})
            assert saved.status_code == 200 and saved.json()["theme"] == "dark"
            assert not principal_for_key("demo-hotel-key").can_order
            assert principal_for_key("demo-hospital-key").can_order
            assert (await client.get("/client/reminders", headers=hotel)).json()["reminder"]["delivery_date"] == "2026-11-15"
            recipe = await client.post("/client/chat", headers=hotel, json={
                "text": "Tomato salad (4)\n500 g tomato\n80 g red onion"})
            assert recipe.status_code == 200, recipe.text
            assert recipe.json()["recipe"]["ingredients"][0]["quantity"] == .5
            assert recipe.headers["X-Gateway-Now"] == "2026-11-14T10:00:00+02:00"
    asyncio.run(verify())


def test_unhandled_exception_returns_json_500():
    from fastapi import FastAPI
    from gateway.web_common import configure_errors

    boom_app = FastAPI()
    configure_errors(boom_app)

    @boom_app.get("/boom")
    def boom():
        raise ZeroDivisionError("unexpected math error")

    async def verify():
        async with AsyncClient(transport=ASGITransport(app=boom_app, raise_app_exceptions=False),
                               base_url="http://test") as client:
            res = await client.get("/boom")
            assert res.status_code == 500
            assert res.json() == {"detail": "An unexpected server error occurred."}

    asyncio.run(verify())
