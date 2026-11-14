"""API key -> principal (buyer + role) -> mandate.

The buyer id and limits are NEVER taken from the request body or tool arguments: they come from the
credential. REST uses the `require_principal` dependency; MCP requests go through
`McpAuthMiddleware`, which sets the `current_principal` contextvar (tools also fall back to the
request headers).

Accepted headers: `X-API-Key: <key>` or `Authorization: Bearer <key>` (the Claude MCP connector
sends `authorization_token` as a Bearer token).

"""
from __future__ import annotations

import hmac
import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from fastapi import Depends, Header, HTTPException, Request

from .accounts import hosted, identity, token_hash
from . import store

from .config import APP_DIR
from .models import Mandate
from .mcp_oauth import ACCESS_PREFIX, SCOPE, oauth
from .policy import load_mandate


@dataclass(frozen=True)
class Principal:
    buyer_id: str
    role: str          # agent | client | approver
    name: str
    mandate: Mandate
    can_order: bool = True
    credential_id: str | None = None
    oauth_read_only: bool = False

    @property
    def actor(self) -> str:
        return f"{self.role}:{self.buyer_id}:{self.name}" + (f" [{self.credential_id}]" if self.credential_id else "")


@dataclass(frozen=True)
class Admin:
    actor: str = "admin:aimo"


def admin_for_key(key: str | None) -> Admin | None:
    expected = os.getenv("AIMO_ADMIN_API_KEY")
    if expected and key and hmac.compare_digest(key.strip().encode(), expected.encode()):
        return Admin()
    return None


def require_admin(request: Request, x_api_key: str | None = Header(None), authorization: str | None = Header(None)) -> Admin:
    user = identity(request, "admin")
    if user:
        return Admin(actor=f"admin:{user['username']}")
    if hosted():
        raise HTTPException(401, "Sign in to Aimo operations.")
    admin = admin_for_key(key_from_headers({"x-api-key": x_api_key, "authorization": authorization}))
    if admin is None:
        raise HTTPException(401, "Enter a valid Aimo operations key")
    return admin


current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


@lru_cache(maxsize=1)
def _keys() -> dict[str, dict]:
    data = json.loads((APP_DIR / "buyers.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def principal_for_key(key: str | None) -> Principal | None:
    entry = None if hosted() else _keys().get((key or "").strip())
    if not entry:
        return None
    can_order = entry.get("can_order", True)
    if can_order and entry["role"] == "agent":
        from .preferences import preferences
        can_order = preferences(entry["buyer_id"]).agent_self_order
    return Principal(buyer_id=entry["buyer_id"], role=entry["role"], name=entry.get("name", entry["buyer_id"]),
                     mandate=load_mandate(entry["buyer_id"]), can_order=can_order)


def principal_for_mcp_key(key: str | None) -> Principal | None:
    if not key or not key.startswith("ad_mcp_"):
        return principal_for_key(key)
    if len(key) > 120:
        return None
    row = store.fetchone("SELECT id,buyer_id,label,can_order FROM agent_credentials WHERE secret_hash=? AND revoked_at IS NULL",
                         (token_hash(key),))
    if not row:
        return None
    from .preferences import preferences
    return Principal(row["buyer_id"], "agent", row["label"], load_mandate(row["buyer_id"]),
                     bool(row["can_order"]) and preferences(row["buyer_id"]).agent_self_order, row["id"])


def principal_for_mcp_request(headers: Mapping[str, str]) -> Principal | None:
    authz = headers.get("authorization", "")
    if authz.lower().startswith("bearer ") and (key := authz[7:].strip()).startswith(ACCESS_PREFIX):
        provider = oauth()
        row = provider.access_grant(key) if provider and hosted() else None
        if row:
            return Principal(row["buyer_id"], "agent", "ChatGPT " + row["username"], load_mandate(row["buyer_id"]),
                             can_order=False, credential_id=row["id"], oauth_read_only=True)
        return None
    return principal_for_mcp_key(key_from_headers(headers))


def key_from_headers(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    normalized = {k.lower(): v for k, v in headers.items() if v}
    key = normalized.get("x-api-key")
    if key:
        return key.strip()
    authz = normalized.get("authorization", "")
    return authz[7:].strip() if authz.lower().startswith("bearer ") else None


def require_principal(request: Request, x_api_key: str | None = Header(None), authorization: str | None = Header(None)) -> Principal:
    key = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    user = identity(request, "client")
    p = (Principal(user["buyer_id"], "client", user["username"], load_mandate(user["buyer_id"]))
         if user else principal_for_key(key))
    if p is None:
        raise HTTPException(401, "Missing or unknown API key (X-API-Key or Authorization: Bearer)")
    current_principal.set(p)
    return p


def require_client(p: Principal = Depends(require_principal)) -> Principal:
    if p.role != "client":
        raise HTTPException(403, "Use a client workspace key")
    return p


def require_agent(p: Principal = Depends(require_principal)) -> Principal:
    if p.role != "agent":
        raise HTTPException(403, "Only a purchasing agent key can perform this action; approver keys are for human sign-off")
    return p


def require_approver(p: Principal) -> Principal:
    if p.role != "approver":
        raise HTTPException(403, "Only a human approver key can decide approvals; agents cannot approve their own orders")
    return p


class McpAuthMiddleware:
    """Pure ASGI middleware: authenticates /mcp requests and sets current_principal."""

    def __init__(self, app, prefix: str = "/mcp"):
        self.app, self.prefix = app, prefix

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root_path = scope.get("root_path", "")
        if root_path and path.startswith(root_path + "/"):
            path = path[len(root_path):]
        if scope["type"] != "http" or not (path == self.prefix or path.startswith(self.prefix + "/")):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        allowed_origins = {value.strip() for value in os.getenv(
            "MCP_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",") if value.strip()}
        if origin and origin not in allowed_origins:
            await send({"type": "http.response.start", "status": 403, "headers": []})
            return await send({"type": "http.response.body", "body": b"Origin forbidden"})
        import anyio
        p = await anyio.to_thread.run_sync(principal_for_mcp_request, headers)
        if p is None or p.role not in {"agent", "client"}:
            provider = oauth()
            challenge = f'Bearer resource_metadata="{provider.metadata}", scope="{SCOPE}"' if provider and hosted() else "Bearer"
            body = json.dumps({"error": "Missing or invalid MCP credentials"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", challenge.encode()),
                                    (b"cache-control", b"no-store")]})
            return await send({"type": "http.response.body", "body": body})
        token = current_principal.set(p)
        try:
            if p.credential_id:
                await anyio.to_thread.run_sync(_record_mcp_request, p, scope["method"])
            return await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)


def _record_mcp_request(p: Principal, method: str) -> None:
    with store.transaction() as conn:
        table = "mcp_oauth_grants" if p.oauth_read_only else "agent_credentials"
        conn.execute(f"UPDATE {table} SET last_used_at=? WHERE id=?", (store.now().isoformat(), p.credential_id))
        store.append_in_transaction(conn, "MCP_REQUEST", p.actor,
                                    {"credential_id": p.credential_id, "method": method}, buyer_id=p.buyer_id)
