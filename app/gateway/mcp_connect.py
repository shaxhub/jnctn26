"""OAuth discovery, ChatGPT consent and buyer-owned connection management."""
from collections import deque
from functools import lru_cache
from html import escape
import re
import threading
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


AUTHORIZE_WINDOW = 60.0
AUTHORIZE_LIMIT = 30
_AUTHORIZE_MAX_HOSTS = 4096
_authorize_lock = threading.Lock()
_authorize_hits: dict[str, deque[float]] = {}


def _authorize_throttled(request: Request) -> bool:
    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    cutoff = now - AUTHORIZE_WINDOW
    with _authorize_lock:
        for stale_host in list(_authorize_hits):
            bucket = _authorize_hits[stale_host]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                del _authorize_hits[stale_host]
            else:
                break
        bucket = _authorize_hits.get(host)
        if bucket is not None:
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= AUTHORIZE_LIMIT:
                return True
            del _authorize_hits[host]
        else:
            if len(_authorize_hits) >= _AUTHORIZE_MAX_HOSTS:
                _authorize_hits.pop(next(iter(_authorize_hits)))
            bucket = deque()
        bucket.append(now)
        _authorize_hits[host] = bucket
        return False


class _CorsApp:
    def __init__(self, app, methods: tuple[str, ...]):
        self.app = app
        self.headers = [
            (b"access-control-allow-origin", b"*"),
            (b"access-control-allow-methods", ", ".join(methods).encode()),
            (b"access-control-allow-headers", b"Authorization, Content-Type, Accept, MCP-Protocol-Version"),
        ]

    async def __call__(self, scope, receive, send):
        if "agent_dairy_mcp" in scope:
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": list(self.headers)})
            return await send({"type": "http.response.body", "body": b""})

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in self.headers if k not in existing]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_cors)


@lru_cache(maxsize=4)
def _provider_apps(provider: OAuthProvider) -> dict:
    authorization_handler = AuthorizationHandler(provider)
    token_handler = TokenHandler(provider, ClientAuthenticator(provider))
    consent_url = provider.issuer + "/oauth/connect"

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
        if _authorize_throttled(request):
            return JSONResponse({"error": "slow_down"}, status_code=429, headers={"Cache-Control": "no-store"})
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

    return {
        "resource_metadata": _CorsApp(request_response(resource_metadata), ("GET", "OPTIONS")),
        "metadata": _CorsApp(request_response(metadata), ("GET", "OPTIONS")),
        "authorize": RequestBodyLimitMiddleware(request_response(authorize), 8192),
        "consent": RequestBodyLimitMiddleware(request_response(consent), 8192),
        "token": _CorsApp(RequestBodyLimitMiddleware(request_response(token), 8192), ("POST", "OPTIONS")),
    }


class _DynamicOAuthApp:
    def __init__(self, target: str, *, funnel_prefix: bool = False):
        self.target = target
        self.funnel_prefix = funnel_prefix

    async def __call__(self, scope, receive, send):
        active = oauth()
        if active is not None and self.funnel_prefix:
            prefix = scope.get("path_params", {}).get("prefix", "")
            if prefix != prefix.strip("/") or "/" + prefix.strip("/") != urlsplit(active.issuer).path:
                active = None
        if active is None:
            response = JSONResponse({"error": "not_found"}, status_code=404, headers={"Cache-Control": "no-store"})
            return await response(scope, receive, send)
        await _provider_apps(active)[self.target](scope, receive, send)


def oauth_routes(provider: OAuthProvider | None = None) -> list[Route]:
    if provider is None:
        return [
            Route("/.well-known/oauth-protected-resource/mcp", _DynamicOAuthApp("resource_metadata"),
                  methods=["GET", "OPTIONS"], include_in_schema=False),
            Route("/.well-known/oauth-authorization-server", _DynamicOAuthApp("metadata"),
                  methods=["GET", "OPTIONS"], include_in_schema=False),
            Route("/authorize", _DynamicOAuthApp("authorize"), methods=["GET"], include_in_schema=False),
            Route("/oauth/connect", _DynamicOAuthApp("consent"), methods=["GET", "POST"], include_in_schema=False),
            Route("/token", _DynamicOAuthApp("token"), methods=["POST", "OPTIONS"], include_in_schema=False),
            Route("/oauth-protected-resource/{prefix:path}/mcp",
                  _DynamicOAuthApp("resource_metadata", funnel_prefix=True),
                  methods=["GET", "OPTIONS"], include_in_schema=False),
            Route("/oauth-authorization-server/{prefix:path}",
                  _DynamicOAuthApp("metadata", funnel_prefix=True),
                  methods=["GET", "OPTIONS"], include_in_schema=False),
        ]
    apps = _provider_apps(provider)
    issuer_path = urlsplit(provider.issuer).path
    routes = [
        Route("/.well-known/oauth-protected-resource/mcp", apps["resource_metadata"],
              methods=["GET", "OPTIONS"], include_in_schema=False),
        Route("/.well-known/oauth-authorization-server", apps["metadata"],
              methods=["GET", "OPTIONS"], include_in_schema=False),
        Route("/authorize", apps["authorize"], methods=["GET"], include_in_schema=False),
        Route("/oauth/connect", apps["consent"], methods=["GET", "POST"], include_in_schema=False),
        Route("/token", apps["token"], methods=["POST", "OPTIONS"], include_in_schema=False),
    ]
    if issuer_path:
        # The Funnel maps the two public discovery URLs to these internal paths.
        routes += [
            Route("/oauth-protected-resource" + issuer_path + "/mcp", apps["resource_metadata"],
                  methods=["GET", "OPTIONS"], include_in_schema=False),
            Route("/oauth-authorization-server" + issuer_path, apps["metadata"],
                  methods=["GET", "OPTIONS"], include_in_schema=False),
        ]
    return routes
