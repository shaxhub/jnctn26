"""The shared origin must preserve the buyer/admin authorization boundary."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from gateway import accounts, store
from gateway.api import app
from test_portals import gateway


@pytest.mark.parametrize("prefix", ["", "/agent-dairy"])
@pytest.mark.parametrize("required", [True, False])
def test_shared_login_role_boundary_and_logout(gateway, monkeypatch, prefix, required):
    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1" if required else "0")
    password = "a-local-test-only-password"
    accounts.provision("kitchen-test", "client", "hotel", password)
    accounts.provision("review-test", "admin", None, password)
    # A legacy admin cookie must not bypass or outlive shared portal logout.
    from datetime import datetime, timedelta, timezone
    legacy_token = "legacy-admin-test-token"
    store.execute("INSERT INTO portal_sessions VALUES (?,?,?)",
                  (accounts.token_hash(legacy_token), "review-test",
                   (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
    origin = "https://portal.test"

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app, root_path=prefix), base_url=origin) as http:
            http.cookies.set(accounts.COOKIES["admin"], legacy_token)

            async def login(username):
                result = await http.post(prefix + "/session/login", headers={"Origin": origin},
                                         json={"username": username, "password": password})
                assert result.status_code == 200, result.text
                assert "HttpOnly" in result.headers["set-cookie"]
                assert "Secure" in result.headers["set-cookie"]
                assert f"Path={prefix or '/'}" in result.headers["set-cookie"]
                return result.json()

            assert (await http.get(prefix + "/session")).json()["role"] is None
            assert (await http.get(prefix + "/operations/activity")).status_code == 401
            if required:
                page = await http.get(prefix + "/admin/")
                assert page.status_code == 303 and page.headers["location"] == prefix + "/"
            assert (await login("kitchen-test"))["role"] == "client"
            session = (await http.get(prefix + "/session")).json()
            assert session["role"] == "client" and session["buyer_id"] == "hotel"
            assert (await http.get(prefix + "/client/dashboard")).status_code == 200
            # A buyer cannot change their assigned kitchen by spoofing the admin header.
            assert (await http.get(prefix + "/me", headers={"X-Workspace-Buyer": "hospital"})).json()["buyer_id"] == "hotel"
            assert (await http.get(prefix + "/admin/")).status_code == 403
            assert (await http.get(prefix + "/operations/activity")).status_code == 401
            assert (await http.post(prefix + "/demo/reset", headers={"Origin": origin})).status_code == 401
            old_token = http.cookies.get(accounts.COOKIES["portal"])

            assert (await login("review-test"))["role"] == "admin"
            assert store.fetchone("SELECT * FROM portal_sessions WHERE token_hash=?",
                                  (accounts.token_hash(old_token),)) is None
            session = (await http.get(prefix + "/session")).json()
            assert session["role"] == "admin" and session["buyer_id"] is None
            page = await http.get(prefix + "/admin/")
            assert page.status_code == 200 and f'<base href="{prefix}/">' in page.text
            assert (await http.get(prefix + "/assets/admin.js")).status_code == 200
            assert (await http.get(prefix + "/operations/activity")).status_code == 200
            assert (await http.get(prefix + "/client/dashboard")).status_code == 200
            me = (await http.get(prefix + "/me")).json()
            assert me["buyer_id"] == "hotel" and me["role"] == "client"
            selected = await http.get(prefix + "/me", headers={"X-Workspace-Buyer": "hospital"})
            assert selected.json()["buyer_id"] == "hospital"
            assert (await http.get(prefix + "/me", headers={"X-Workspace-Buyer": "unknown"})).status_code == 422
            assert (await http.post(prefix + "/demo/reset", headers={"Origin": "https://other.test"})).status_code == 403
            assert (await http.post(prefix + "/session/logout", headers={"Origin": "https://other.test"})).status_code == 403
            assert (await http.get(prefix + "/session")).json()["role"] == "admin"
            token = http.cookies.get(accounts.COOKIES["portal"])
            assert (await http.post(prefix + "/session/logout", headers={"Origin": origin})).status_code == 200
            assert (await http.get(prefix + "/session")).json()["role"] is None
            # A copied cookie cannot restore a logged-out session.
            http.cookies.set(accounts.COOKIES["portal"], token)
            assert (await http.get(prefix + "/operations/activity")).status_code == 401

    asyncio.run(exercise())


def test_admin_can_order_as_buyer_then_review_without_another_login(gateway, monkeypatch):
    from gateway import service
    from gateway.models import ProductSummary

    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1")
    monkeypatch.setattr(service, "get_products", lambda ids: {
        sku: ProductSummary(id=sku, name_en="Milk", sales_unit="ST", base_unit="ST") for sku in ids
    })
    password = "a-local-test-only-password"
    accounts.provision("review-test", "admin", None, password)
    origin = "https://portal.test"

    async def exercise():
        async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as http:
            assert (await http.post("/session/login", headers={"Origin": origin}, json={
                "username": "review-test", "password": password})).status_code == 200
            hotel = {"Origin": origin, "X-Workspace-Buyer": "hotel"}
            hospital = {"Origin": origin, "X-Workspace-Buyer": "hospital"}
            created = await http.post("/client/basket", headers=hotel,
                                      json={"delivery_date": "2026-11-16", "postal_code": "00580", "quantities": {"milk": 1000}})
            assert created.status_code == 200, created.text
            assert created.json()["postal_code"] == "00580"
            quote_id = created.json()["quote_id"]
            assert (await http.get(f"/client/drafts/{quote_id}", headers=hospital)).status_code == 404
            submitted = await http.post("/client/tickets/submit", headers=hotel, json={"quote_id": quote_id})
            assert submitted.status_code == 200, submitted.text
            order = submitted.json()
            assert order["status"] == "pending_approval"
            assert (await http.get("/operations/orders/" + order["order_id"])).status_code == 200
            approved = await http.post("/operations/approvals/" + order["approval_id"], headers={"Origin": origin},
                                       json={"decision": "approve"})
            assert approved.status_code == 200 and approved.json()["status"] == "confirmed", approved.text
            detail_url = "/client/requests/" + order["order_id"]
            assert (await http.get(detail_url, headers=hotel)).json()["order"]["status"] == "confirmed"
            assert (await http.get(detail_url, headers=hospital)).status_code == 404
            saved = await http.post("/client/settings", headers=hospital, json={"theme": "dark"})
            assert saved.status_code == 200 and saved.json()["theme"] == "dark"
            assert (await http.get("/client/settings", headers=hotel)).json()["theme"] == "light"
            # Writes still require the same origin even for the administrator.
            assert (await http.post("/client/settings", headers={"X-Workspace-Buyer": "hotel"},
                                    json={"theme": "dark"})).status_code == 403
            actor = store.fetchone("SELECT actor FROM audit_events WHERE event_type='QUOTE_CREATED' AND quote_id=?",
                                   (quote_id,))
            assert "review-test (admin)" in actor["actor"]

    asyncio.run(exercise())
