import asyncio
from dataclasses import replace
from datetime import date

from httpx import ASGITransport, AsyncClient

from gateway import accounts, demo_catalog, offers, search, store
from test_portals import gateway


def test_hosted_accounts_and_synthetic_purchase(gateway, monkeypatch, tmp_path):
    from gateway import service
    from gateway.admin_app import app as admin
    from gateway.api import app as client

    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1")
    monkeypatch.setenv("OFFLINE_DEMO", "1")
    monkeypatch.setenv("AIMO_FULFILLMENT_CHECKS", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(service, "get_offers", offers.get_offers)
    catalog = replace(demo_catalog.settings, catalog_db_path=tmp_path / "synthetic.db")
    monkeypatch.setattr(demo_catalog, "settings", catalog)
    monkeypatch.setattr(search, "settings", catalog)
    search._catalog_path.cache_clear()
    demo_catalog.build()
    password = "a-local-test-only-password"
    accounts.provision("kitchen-test", "client", "hotel", password)
    accounts.provision("review-test", "admin", None, password)

    async def exercise():
        buyer_origin = "https://client.test"
        admin_origin = "https://admin.test"
        async with (
            AsyncClient(transport=ASGITransport(app=client), base_url=buyer_origin) as kitchen,
            AsyncClient(transport=ASGITransport(app=admin), base_url=admin_origin) as aimo,
        ):
            auth = {"username": "kitchen-test", "password": password}
            assert (await kitchen.get("/client/dashboard", headers={"X-API-Key": "demo-hotel-client-key"})).status_code == 401
            assert (await aimo.get("/operations/activity", headers={"X-API-Key": "test-admin-credential"})).status_code == 401
            assert (await aimo.post("/session/login", json=auth, headers={"Origin": admin_origin})).status_code == 401
            assert (await kitchen.post("/session/login", json=auth, headers={"Origin": admin_origin})).status_code == 403
            signed_in = await kitchen.post("/session/login", json=auth, headers={"Origin": buyer_origin})
            assert signed_in.status_code == 200, signed_in.text
            assert "HttpOnly" in signed_in.headers["set-cookie"] and "Secure" in signed_in.headers["set-cookie"]
            assert (await kitchen.get("/session")).json()["offline_demo"]
            chat = {"text": "I need 1000 litres of lactose-free milk", "delivery_date": "2026-11-16", "action": "draft"}
            assert (await kitchen.post("/client/chat", json=chat, headers={"Origin": admin_origin})).status_code == 403
            draft = await kitchen.post("/client/chat", json=chat, headers={"Origin": buyer_origin})
            assert draft.status_code == 200, draft.text
            submitted = await kitchen.post("/client/tickets/submit", headers={"Origin": buyer_origin},
                                           json={"quote_id": draft.json()["draft"]["quote_id"]})
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["status"] == "pending_approval"
            approval_id = submitted.json()["approval_id"]
            assert (await aimo.post("/session/login", headers={"Origin": admin_origin},
                                    json={"username": "review-test", "password": password})).status_code == 200
            reviewed = await aimo.post(f"/operations/approvals/{approval_id}", headers={"Origin": admin_origin},
                                       json={"decision": "approve"})
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["status"] == "confirmed"
            await kitchen.post("/session/logout", headers={"Origin": buyer_origin}, json={})
            assert (await kitchen.get("/client/dashboard")).status_code == 401

        async with AsyncClient(transport=ASGITransport(app=admin, root_path="/agent-dairy-admin"),
                               base_url=admin_origin) as proxied_admin:
            prefix = "/agent-dairy-admin"
            assert f'<base href="{prefix}/">' in (await proxied_admin.get(prefix + "/")).text
            assert (await proxied_admin.get(prefix + "/assets/portal.css")).status_code == 200
            login = await proxied_admin.post(prefix + "/session/login", headers={"Origin": admin_origin},
                                             json={"username": "review-test", "password": password})
            assert login.status_code == 200, login.text
            assert f"Path={prefix}" in login.headers["set-cookie"]
            assert (await proxied_admin.get(prefix + "/operations/activity")).status_code == 200
            assert (await proxied_admin.get("/operations/activity")).status_code == 401
            await proxied_admin.post(prefix + "/session/logout", headers={"Origin": admin_origin})
            assert (await proxied_admin.get(prefix + "/operations/activity")).status_code == 401

    try:
        asyncio.run(exercise())
    finally:
        search._catalog_path.cache_clear()


def test_failed_logins_from_one_source_do_not_lock_the_account_elsewhere(gateway, monkeypatch):
    from gateway.api import app

    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1")
    password = "a-local-test-only-password"
    accounts.provision("kitchen-test", "client", "hotel", password)
    origin = "https://client.test"

    async def exercise():
        def portal(source):
            return AsyncClient(transport=ASGITransport(app=app, client=(source, 50000)), base_url=origin)

        wrong = {"username": "kitchen-test", "password": "not-the-right-password"}
        right = {"username": "kitchen-test", "password": password}
        async with portal("203.0.113.9") as attacker, portal("198.51.100.4") as owner:
            for _ in range(12):
                assert (await attacker.post("/session/login", json=wrong, headers={"Origin": origin})).status_code == 401
            # The throttled source is refused before its password is checked.
            assert (await attacker.post("/session/login", json=right, headers={"Origin": origin})).status_code == 429
            assert (await owner.post("/session/login", json=right, headers={"Origin": origin})).status_code == 200

    asyncio.run(exercise())
