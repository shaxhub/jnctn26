import asyncio
from datetime import date

from httpx import ASGITransport, AsyncClient

from gateway import service
from gateway.auth import principal_for_key
from gateway.models import QuoteRequest
from test_portals import gateway


def test_split_hosts_request_tracking_and_settings(gateway):
    from gateway.admin_app import app as admin_app
    from gateway.api import app

    hotel = {"X-API-Key": "demo-hotel-client-key"}
    hospital = {"X-API-Key": "demo-hospital-client-key"}
    admin = {"X-API-Key": "test-admin-credential"}
    principal = principal_for_key(hotel["X-API-Key"])
    request = QuoteRequest(delivery_date=date(2026, 11, 16), lines=[{"product_id": "milk", "quantity": 5}])
    draft = service.create_quote(principal, request)

    async def verify():
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://client") as client,
            AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://admin") as aimo,
        ):
            assert (await client.get("/admin")).status_code == 404
            assert (await client.get("/assets/admin.js")).status_code == 404
            assert (await aimo.get("/assets/client.js")).status_code == 404
            assert (await aimo.get("/client/settings")).status_code == 404
            assert (await client.get("/client/drafts", headers=hospital)).json() == []
            edited = await client.post(f"/client/drafts/{draft.quote_id}/edit", headers=hotel,
                                       json={"delivery_date": "2026-11-16", "quantities": {"milk": 8}})
            assert edited.status_code == 200, edited.text
            revised = edited.json()["quote_id"]
            assert [item["quote_id"] for item in (await client.get("/client/drafts", headers=hotel)).json()] == [revised]
            submitted = await client.post("/client/tickets/submit", headers=hotel, json={"quote_id": revised})
            assert submitted.status_code == 200, submitted.text
            order_id = submitted.json()["order_id"]
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
    asyncio.run(verify())
