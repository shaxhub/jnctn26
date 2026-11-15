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
            session_info = (await kitchen.get("/session")).json()
            assert session_info["offline_demo"] and session_info["now"] == store.now().isoformat()
            school = await kitchen.post("/client/chat", headers={"Origin": buyer_origin}, json={"action": "draft",
                "text": "I need to feed 200 children (7-9 years old) on Wednesday. Dietary wise:\n"
                        "- 27 portions for lactose intolerance children\n- 67 portions without peanuts\n"
                        "- Follows strict Finnish dietary restrictions required by law for schools and institutions to follow\n"
                        "Draft up the recipe and give me everything I need to order. "
                        "My soft budget is 1000 euros, and hard budget is 2000 euros."})
            assert school.status_code == 200, school.text
            meal = school.json()
            assert meal["mode"] == "guided_meal"
            assert meal["meal"]["servings"] == 200
            assert meal["meal"]["delivery_date"] == "2026-11-18"
            assert meal["meal"]["budgets"] == {"soft": 1000, "hard": 2000}
            assert meal["meal"]["matched_total_net"] > 0
            assert meal["draft"] is None and not meal["meal"]["complete"]
            assert any(item["ingredient"] == "potato" and item["quantity"] == 25
                       for item in meal["recipe"]["ingredients"])
            chat = {"text": "I need 1000 litres of lactose-free milk", "delivery_date": "2026-11-16", "action": "draft"}
            assert (await kitchen.post("/client/chat", json=chat, headers={"Origin": admin_origin})).status_code == 403
            draft = await kitchen.post("/client/chat", json=chat, headers={"Origin": buyer_origin})
            assert draft.status_code == 200, draft.text
            submitted = await kitchen.post("/client/tickets/submit", headers={"Origin": buyer_origin},
                                           json={"quote_id": draft.json()["draft"]["quote_id"],
                                                 "delivery_address": "Testikatu 1, 00100 Helsinki"})
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
    from gateway.admin_app import app as admin_app
    from gateway.api import app

    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1")
    password = "a-local-test-only-password"
    accounts.provision("kitchen-test", "client", "hotel", password)
    accounts.provision("other-kitchen", "client", "hospital", password)
    accounts.provision("review-test", "admin", None, password)
    origin = "https://client.test"
    admin_origin = "https://admin.test"

    async def exercise():
        def portal(source, target=app, base=origin):
            return AsyncClient(transport=ASGITransport(app=target, client=(source, 50000)), base_url=base)

        wrong = {"username": "kitchen-test", "password": "not-the-right-password"}
        right = {"username": "kitchen-test", "password": password}
        other = {"username": "other-kitchen", "password": password}
        admin_login = {"username": "review-test", "password": password}
        async with (
            portal("203.0.113.9") as attacker,
            portal("198.51.100.4") as owner,
            portal("203.0.113.9", admin_app, admin_origin) as shared_ip_admin,
        ):
            for _ in range(12):
                assert (await attacker.post("/session/login", json=wrong, headers={"Origin": origin})).status_code == 401
            # The throttled (source, role, username) tuple is refused before its password is checked.
            assert (await attacker.post("/session/login", json=right, headers={"Origin": origin})).status_code == 429
            # Behind a shared proxy/Funnel IP, another client username and the admin portal remain accessible.
            assert (await attacker.post("/session/login", json=other, headers={"Origin": origin})).status_code == 200
            assert (await shared_ip_admin.post("/session/login", json=admin_login,
                                               headers={"Origin": admin_origin})).status_code == 200
            assert (await owner.post("/session/login", json=right, headers={"Origin": origin})).status_code == 200

    asyncio.run(exercise())


def test_demo_reset_persists_clock_clears_state_and_evening_cutoff(gateway, monkeypatch, tmp_path):
    from datetime import datetime
    import sqlite3
    from gateway.admin_app import app as admin_app
    from gateway.api import app as client_app

    # Verify seamless migration of a legacy portal_login_attempts table missing 'role'.
    legacy_db = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_db) as raw_conn:
        raw_conn.execute("CREATE TABLE portal_login_attempts (source TEXT NOT NULL, username TEXT NOT NULL, at TEXT NOT NULL)")
    with store.connect(legacy_db) as migrated:
        cols = {row["name"] for row in migrated.execute("PRAGMA table_info(portal_login_attempts)").fetchall()}
        assert "role" in cols

    accounts.provision("kitchen-test", "client", "hotel", "a-local-test-only-password")
    store.execute("INSERT INTO fulfillment_evidence VALUES ('2026-11-16', '490001', '{}')")
    store.execute("INSERT INTO ticket_names VALUES ('q-demo', 'Morning milk')")
    store.execute("INSERT INTO mcp_oauth_pending (request_hash, params, expires_at) VALUES ('h1', '{}', 9999999999)")

    evening = "2026-11-14T19:30:00+02:00"
    admin_headers = {"X-API-Key": "test-admin-credential"}

    async def exercise():
        async with (
            AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://admin") as ops,
            AsyncClient(transport=ASGITransport(app=client_app), base_url="http://client") as client,
        ):
            res = await ops.post("/demo/reset", headers=admin_headers, json={"demo_now": evening})
            assert res.status_code == 200 and res.json()["now"] == evening
            # Persisted in SQLite gateway_runtime rather than process-local _demo_now.
            assert store._demo_now is None
            assert store.get_demo_now() == datetime.fromisoformat(evening)
            assert store.now() == datetime.fromisoformat(evening)
            assert (await client.get("/session")).json()["now"] == evening
            assert store.fetchone("SELECT 1 FROM fulfillment_evidence") is None
            assert store.fetchone("SELECT 1 FROM ticket_names") is None
            assert store.fetchone("SELECT 1 FROM mcp_oauth_pending") is None
            assert store.fetchone("SELECT 1 FROM portal_accounts WHERE username='kitchen-test'") is not None

            cleared = await ops.post("/demo/reset", headers=admin_headers, json={"demo_now": None})
            assert cleared.status_code == 200
            assert store.get_demo_now() is None

    asyncio.run(exercise())

    evening_dt = datetime.fromisoformat(evening)
    today_raw = demo_catalog.offers(["490001"], date(2026, 11, 14), evening_dt)
    tomorrow_raw = demo_catalog.offers(["490001"], date(2026, 11, 15), evening_dt)
    assert today_raw.products["490001"]["availability"]["closingTime"] == "2026-11-14T18:00:00+02:00"
    assert tomorrow_raw.products["490001"]["availability"]["closingTime"] == "2026-11-15T18:00:00+02:00"
