"""OAuth discovery, ChatGPT consent and buyer-owned connection management."""
from html import escape
import re
import time
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.transport_security import RequestBodyLimitMiddleware
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route, request_response

from . import store
from .accounts import Login, authenticate, hosted, same_origin
from .auth import Principal, require_client
from .mcp_oauth import CALLBACK, SCOPE, OAuthProvider, oauth, public_mcp_url

router = APIRouter(prefix="/client")
_PAGE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
                 "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"}


@router.get("/agent-integration")
def agent_integration(response: Response, _: Principal = Depends(require_client)):
    response.headers["Cache-Control"] = "no-store"
    return {"url": public_mcp_url(), "chatgpt_oauth": oauth() is not None and hosted()}


@router.get("/agent-connections")
def agent_connections(response: Response, p: Principal = Depends(require_client)):
    response.headers["Cache-Control"] = "no-store"
    provider = oauth()
    if not provider or not hosted():
        return []
    rows = store.fetchall(
        "SELECT id, created_at, last_used_at FROM mcp_oauth_grants "
        "WHERE username=? AND resource=? AND refresh_expires>? ORDER BY created_at DESC",
        (p.name, provider.resource, int(time.time())))
    return [dict(row) for row in rows]


@router.post("/agent-connections/{connection_id}/disconnect")
def disconnect(connection_id: str, p: Principal = Depends(require_client)):
    provider = oauth()
    if not provider or not hosted():
        raise HTTPException(404, "Connection not found.")
    with store.transaction() as conn:
        changed = conn.execute("DELETE FROM mcp_oauth_grants WHERE id=? AND username=? AND resource=?",
                               (connection_id, p.name, provider.resource)).rowcount
    if not changed:
        raise HTTPException(404, "Connection not found.")
    return {"disconnected": True}


def _consent_page(request_id: str, action: str, error: str = "", status: int = 200) -> HTMLResponse:
    alert = f'<p role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect ChatGPT to Agent Dairy</title>
<style>
body{{margin:0;background:#f4f7fb;color:#0b2440;font:16px system-ui}}
main{{max-width:30rem;margin:8vh auto;padding:1.6rem;background:white;border:1px solid #ced8e8;border-radius:16px}}
label{{display:grid;gap:.3rem;margin:.9rem 0}} input,button{{font:inherit;padding:.7rem;border:1px solid #8095ad;border-radius:6px}}
button[value=allow]{{background:#0b2440;color:white}} button{{cursor:pointer;margin-right:.4rem}}
@media(max-width:38rem){{main{{margin:1rem}}}}
</style>
<main><h1>Connect ChatGPT</h1>
<p>Allow ChatGPT to look up Aimo products, prices and availability and read requests in your Agent Dairy workspace.</p>
<p>This connection is read-only. You can disconnect it from Agent Dairy Settings.</p>
{alert}<form method="post" action="{escape(action, quote=True)}">
<input type="hidden" name="request_id" value="{escape(request_id, quote=True)}">
<label>Agent Dairy username<input name="username" autocomplete="username" maxlength="48" required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" maxlength="128" required></label>
<button name="decision" value="allow">Sign in and connect</button>
<button name="decision" value="deny" formnovalidate>Cancel</button>
</form></main></html>""", status_code=status, headers=_PAGE_HEADERS)


def _bad_token_request(error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=400, headers={"Cache-Control": "no-store"})


def oauth_routes(provider: OAuthProvider) -> list[Route]:
    authorization_handler = AuthorizationHandler(provider)
    token_handler = TokenHandler(provider, ClientAuthenticator(provider))
    consent_url = provider.issuer + "/oauth/connect"
    issuer_path = urlsplit(provider.issuer).path

    async def resource_metadata(_):
        return JSONResponse({"resource": provider.resource, "resource_name": "Agent Dairy",
                             "authorization_servers": [provider.issuer], "scopes_supported": [SCOPE],
                             "bearer_methods_supported": ["header"]})

    async def metadata(_):
        return JSONResponse({
            "issuer": provider.issuer,
            "authorization_endpoint": provider.issuer + "/authorize",
            "token_endpoint": provider.issuer + "/token",
            "scopes_supported": [SCOPE],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
        })

    async def authorize(request: Request):
        if request.query_params.get("code_challenge_method") != "S256":
            return _bad_token_request("invalid_request")
        response = await authorization_handler.handle(request)
        location = response.headers.get("location")
        if location and location.split("?", 1)[0] == CALLBACK:
            params = {key: values[0] for key, values in parse_qs(urlsplit(location).query, keep_blank_values=True).items()}
            response.headers["location"] = construct_redirect_uri(CALLBACK, **params, iss=provider.issuer)
        for name, value in _PAGE_HEADERS.items():
            response.headers[name] = value
        return response

    async def consent(request: Request):
        if not hosted():
            return HTMLResponse("Agent Dairy account login is required.", status_code=404, headers=_PAGE_HEADERS)
        if request.method == "GET":
            request_id = request.query_params.get("request_id", "")
            form = None
        else:
            same_origin(request, provider.origin)
            form = await request.form()
            request_id = form.get("request_id", "")
        if (not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", request_id)
                or not await run_in_threadpool(provider.pending, request_id)):
            return HTMLResponse("This connection request expired. Start again in ChatGPT.",
                                status_code=400, headers=_PAGE_HEADERS)
        if form is None:
            return _consent_page(request_id, consent_url)
        try:
            approved = form.get("decision") == "allow"
            if not approved and form.get("decision") != "deny":
                raise HTTPException(400, "Choose whether to connect ChatGPT.")
            account = None
            if approved:
                credentials = Login(username=form.get("username", ""), password=form.get("password", ""))
                account = await run_in_threadpool(authenticate, credentials, request, "client", origin=provider.origin)
            callback = await run_in_threadpool(provider.finish, request_id, account, approved)
            return RedirectResponse(callback, status_code=303, headers=_PAGE_HEADERS)
        except ValidationError:
            return _consent_page(request_id, consent_url, "Enter a valid Agent Dairy username and password.", 400)
        except HTTPException as error:
            return _consent_page(request_id, consent_url, error.detail, error.status_code)

    async def token(request: Request):
        form = await request.form()
        if form.getlist("resource") != [provider.resource]:
            return _bad_token_request("invalid_target")
        if form.get("grant_type") == "authorization_code" and not re.fullmatch(
                r"[A-Za-z0-9._~-]{43,128}", str(form.get("code_verifier", ""))):
            return _bad_token_request("invalid_request")
        return await token_handler.handle(request)

    routes = [
        Route("/.well-known/oauth-protected-resource/mcp", resource_metadata, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]),
        Route("/authorize", authorize, methods=["GET"]),
        Route("/oauth/connect", RequestBodyLimitMiddleware(request_response(consent), 8192), methods=["GET", "POST"]),
        Route("/token", RequestBodyLimitMiddleware(request_response(token), 8192), methods=["POST"]),
    ]
    if issuer_path:
        # The Funnel maps the two public discovery URLs to these internal paths.
        routes += [
            Route("/oauth-protected-resource" + issuer_path + "/mcp", resource_metadata, methods=["GET"]),
            Route("/oauth-authorization-server" + issuer_path, metadata, methods=["GET"]),
        ]
    return routes
