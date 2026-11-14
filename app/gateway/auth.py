"""API key -> principal (buyer + role) -> mandate.

The buyer id and limits are NEVER taken from the request body or tool arguments: they come from the
credential. REST uses the `require_principal` dependency; MCP requests go through
`McpAuthMiddleware`, which sets the `current_principal` contextvar (tools also fall back to the
request headers).

Accepted headers: `X-API-Key: <key>` or `Authorization: Bearer <key>` (the Claude MCP connector
sends `authorization_token` as a Bearer token).

TODO(C): real identity (OAuth 2.1 client credentials for agents, SSO for approvers), hashed keys.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from fastapi import Depends, Header, HTTPException

from .config import APP_DIR
from .models import Mandate
from .policy import load_mandate


@dataclass(frozen=True)
class Principal:
    buyer_id: str
    role: str          # "agent" | "approver"
    name: str
    mandate: Mandate

    @property
    def actor(self) -> str:
        return f"{self.role}:{self.buyer_id}:{self.name}"


current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


@lru_cache(maxsize=1)
def _keys() -> dict[str, dict]:
    data = json.loads((APP_DIR / "buyers.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def principal_for_key(key: str | None) -> Principal | None:
    entry = _keys().get((key or "").strip())
    if not entry:
        return None
    return Principal(buyer_id=entry["buyer_id"], role=entry["role"], name=entry.get("name", entry["buyer_id"]),
                     mandate=load_mandate(entry["buyer_id"]))


def key_from_headers(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    normalized = {k.lower(): v for k, v in headers.items() if v}
    key = normalized.get("x-api-key")
    if key:
        return key.strip()
    authz = normalized.get("authorization", "")
    return authz[7:].strip() if authz.lower().startswith("bearer ") else None


def require_principal(x_api_key: str | None = Header(None), authorization: str | None = Header(None)) -> Principal:
    key = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    p = principal_for_key(key)
    if p is None:
        raise HTTPException(401, "Missing or unknown API key (X-API-Key or Authorization: Bearer)")
    current_principal.set(p)
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
        if scope["type"] != "http" or not (path == self.prefix or path.startswith(self.prefix + "/")):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        p = principal_for_key(key_from_headers(headers))
        if p is None:
            body = json.dumps({"error": "Missing or unknown API key"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            return await send({"type": "http.response.body", "body": body})
        token = current_principal.set(p)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)
