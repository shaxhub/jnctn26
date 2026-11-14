import asyncio
from base64 import urlsafe_b64encode
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp.server.transport_security import TransportSecuritySettings
import pytest

from test_portals import gateway

ORIGIN = "https://mcp.example.com"
RESOURCE = ORIGIN + "/mcp"
VERIFIER = "v" * 64
CHALLENGE = urlsafe_b64encode(sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


@pytest.fixture
def oauth_app(gateway, monkeypatch):
    from gateway.accounts import provision
    from gateway.accounts import router as session_router
    from gateway.auth import McpAuthMiddleware
    from gateway.mcp_connect import oauth_routes
    from gateway.mcp_connect import router as connection_router
    from gateway.mcp_oauth import oauth
    from gateway.mcp_server import mcp
    from gateway.workspace import router as workspace_router

    monkeypatch.setenv("REQUIRE_PORTAL_LOGIN", "1")
    monkeypatch.setenv("MCP_PUBLIC_URL", RESOURCE)
    monkeypatch.setenv("MCP_OAUTH_ENABLED", "1")
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://chatgpt.com")
    provision("kitchen-a", "client", "hotel", "hotel-password-test")
    provision("kitchen-b", "client", "hospital", "hospital-password-test")
    transport = mcp.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app = FastAPI(lifespan=transport.router.lifespan_context)
    app.add_middleware(McpAuthMiddleware)
    app.router.routes.extend([*transport.routes, *oauth_routes(oauth())])
    app.include_router(session_router("client"))
    app.include_router(connection_router)
    app.include_router(workspace_router)
    return app


def test_chatgpt_oauth_link_refresh_and_disconnect(oauth_app):
    from gateway.mcp_oauth import CALLBACK, CLIENT_ID, SCOPE, oauth_provider

    async def check():
        async with (
            oauth_app.router.lifespan_context(oauth_app),
            AsyncClient(transport=ASGITransport(app=oauth_app), base_url=ORIGIN,
                        headers={"Accept": "application/json, text/event-stream", "Origin": ORIGIN}) as http,
        ):
            http.headers.pop("Origin")
            web = {"Origin": "https://chatgpt.com"}
            preflight = await http.options("/mcp", headers={**web, "Access-Control-Request-Method": "POST",
                                                           "Access-Control-Request-Headers": "Content-Type,MCP-Protocol-Version"})
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == web["Origin"]
            denied_origin = await http.post("/mcp", json={}, headers={"Origin": "https://other.example"})
            assert denied_origin.status_code == 403
            rejected = await http.post("/mcp", json={}, headers=web)
            assert rejected.status_code == 401
            assert rejected.headers["access-control-allow-origin"] == web["Origin"]
            assert "WWW-Authenticate" in rejected.headers["access-control-expose-headers"]
            metadata_url = rejected.headers["www-authenticate"].split('"')[1]
            assert metadata_url == ORIGIN + "/.well-known/oauth-protected-resource/mcp"
            resource_response = await http.get(metadata_url, headers=web)
            assert resource_response.headers["access-control-allow-origin"] == web["Origin"]
            metadata = resource_response.json()
            assert metadata["resource"] == RESOURCE
            issuer, = metadata["authorization_servers"]
            discovery = (await http.get(issuer + "/.well-known/oauth-authorization-server")).json()
            assert discovery["issuer"] == issuer
            assert discovery["token_endpoint_auth_methods_supported"] == ["none"]
            assert discovery["code_challenge_methods_supported"] == ["S256"]
            params = {"client_id": CLIENT_ID, "redirect_uri": CALLBACK, "response_type": "code",
                      "scope": SCOPE, "state": "test-value", "code_challenge": CHALLENGE,
                      "code_challenge_method": "S256", "resource": RESOURCE}
            invalid_redirect = await http.get(discovery["authorization_endpoint"],
                                              params={**params, "redirect_uri": "https://other.example/callback"})
            assert invalid_redirect.status_code == 400
            assert "location" not in invalid_redirect.headers
            denied_scope = await http.get(discovery["authorization_endpoint"], params={**params, "scope": "orders:write"})
            assert parse_qs(urlsplit(denied_scope.headers["location"]).query)["iss"] == [issuer]
            authorization = await http.get(discovery["authorization_endpoint"], params=params)
            assert authorization.status_code == 302
            pending_url = authorization.headers["location"]
            consent = await http.get(pending_url)
            assert consent.status_code == 200
            assert "Sign in and connect" in consent.text
            request_id, = parse_qs(urlsplit(pending_url).query)["request_id"]
            consent_fields = {"request_id": request_id, "decision": "allow",
                              "username": "kitchen-a", "password": "hotel-password-test"}
            assert (await http.post("/oauth/connect", data=consent_fields)).status_code == 403
            approved = await http.post("/oauth/connect", data=consent_fields, headers={"Origin": ORIGIN})
            assert approved.status_code == 303, approved.text
            callback = urlsplit(approved.headers["location"])
            assert callback._replace(query="").geturl() == CALLBACK
            values = parse_qs(callback.query)
            assert values["iss"] == [issuer] and values["state"] == [params["state"]]
            exchange = {"grant_type": "authorization_code", "client_id": CLIENT_ID, "resource": RESOURCE,
                        "code": values["code"][0], "redirect_uri": CALLBACK, "code_verifier": VERIFIER}
            token_url = discovery["token_endpoint"]
            for invalid, expected in (({"resource": issuer}, "invalid_target"),
                                      ({"code_verifier": "x" * 64}, "invalid_grant")):
                assert (await http.post(token_url, data={**exchange, **invalid})).json()["error"] == expected
            result = await http.post(token_url, data=exchange)
            assert result.status_code == 200, result.text
            tokens = result.json()
            assert (await http.post(token_url, data=exchange)).json()["error"] == "invalid_grant"
            assert oauth_provider("https://another.example/mcp").access_grant(tokens["access_token"]) is None

            async def rpc(method, params, token):
                return await http.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params})

            access = tokens["access_token"]
            initialized = await rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                    "clientInfo": {"name": "pytest", "version": "1"}}, access)
            assert initialized.status_code == 200, initialized.text
            http.headers["MCP-Protocol-Version"] = initialized.json()["result"]["protocolVersion"]
            listings = (await rpc("tools/list", {}, access)).json()["result"]["tools"]
            names = {tool["name"] for tool in listings}
            assert "check_offers" in names and names.isdisjoint({"place_order", "post_request_message", "create_quote"})
            assert all(tool["annotations"]["readOnlyHint"] for tool in listings)
            buyer = (await rpc("tools/call", {"name": "get_my_mandate", "arguments": {}}, access)).json()
            assert "hotel" in str(buyer)
            for method in ("place_order", "post_request_message"):
                denied = (await rpc("tools/call", {"name": method, "arguments": {}}, access)).json()
                assert denied["result"]["isError"]
                assert "read-only" in denied["result"]["content"][0]["text"]
            assert (await rpc("tools/list", {}, tokens["refresh_token"])).status_code == 401
            refresh = {"grant_type": "refresh_token", "client_id": CLIENT_ID, "resource": RESOURCE,
                       "refresh_token": tokens["refresh_token"]}
            refreshed = await http.post(token_url, data=refresh)
            assert refreshed.status_code == 200, refreshed.text
            assert (await http.post(token_url, data=refresh)).json()["error"] == "invalid_grant"
            assert (await rpc("tools/list", {}, access)).status_code == 401
            new_access = refreshed.json()["access_token"]
            assert (await rpc("tools/list", {}, new_access)).status_code == 200

            async def sign_in(username, password):
                response = await http.post("/session/login", headers={"Origin": ORIGIN},
                                           json={"username": username, "password": password})
                assert response.status_code == 200

            await sign_in("kitchen-a", "hotel-password-test")
            connection, = (await http.get("/client/agent-connections")).json()
            assert connection["last_used_at"]
            key = await http.post("/client/agent-credentials", headers={"Origin": ORIGIN},
                                  json={"label": "My agent"})
            assert (await rpc("tools/list", {}, key.json()["secret"])).status_code == 200
            await sign_in("kitchen-b", "hospital-password-test")
            assert (await http.get("/client/agent-connections")).json() == []
            disconnect = "/client/agent-connections/" + connection["id"] + "/disconnect"
            assert (await http.post(disconnect, headers={"Origin": ORIGIN})).status_code == 404
            await sign_in("kitchen-a", "hotel-password-test")
            assert (await http.post(disconnect, headers={"Origin": ORIGIN})).status_code == 200
            assert (await rpc("tools/list", {}, new_access)).status_code == 401

    asyncio.run(check())


def test_funnel_oauth_discovery_through_portal_prefix(oauth_app):
    from gateway.mcp_connect import oauth_routes
    from gateway.mcp_oauth import oauth_provider

    issuer = ORIGIN + "/agent-dairy"
    provider = oauth_provider(issuer + "/mcp")
    app = FastAPI(routes=oauth_routes(provider))

    async def check():
        async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as http:
            resource = await http.get("/oauth-protected-resource/agent-dairy/mcp")
            discovery = await http.get("/oauth-authorization-server/agent-dairy")
            assert resource.json()["resource"] == issuer + "/mcp"
            assert resource.json()["authorization_servers"] == [issuer]
            assert discovery.json()["authorization_endpoint"] == issuer + "/authorize"
            assert provider.origin == ORIGIN

    asyncio.run(check())
