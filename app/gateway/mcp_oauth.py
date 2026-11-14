"""SQLite-backed grants for the MCP SDK's OAuth authorization-code flow."""
from __future__ import annotations

import logging
import os
import re
import secrets
import time
from functools import lru_cache
from urllib.parse import urlencode, urlsplit

import anyio
from fastapi import HTTPException
from mcp.server.auth.provider import (
    AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken, TokenError, construct_redirect_uri,
)
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, ValidationError

from . import store
from .accounts import token_hash

SCOPE = "workspace:read"
CLIENT_ID = "https://chatgpt.com/oauth/client.json"
CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
PENDING_TTL = 600
MAX_PENDING = 500
CODE_TTL = 120
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
ACCESS_PREFIX = "ad_oauth_"
REFRESH_PREFIX = "ad_refresh_"


def public_mcp_url() -> str | None:
    value = os.getenv("MCP_PUBLIC_URL", "").strip()
    return value or None


@lru_cache(maxsize=4)
def oauth_provider(public_url: str | None) -> OAuthProvider | None:
    if not public_url:
        return None
    url = AnyHttpUrl(public_url)
    if (url.scheme != "https" or not re.fullmatch(r"(?:/[a-zA-Z0-9_-]+)*/mcp", url.path or "")
            or url.query is not None or url.fragment is not None
            or url.username is not None or url.password is not None or str(url) != public_url):
        raise ValueError("MCP_PUBLIC_URL must be a canonical HTTPS URL ending in /mcp when OAuth is enabled.")
    return OAuthProvider(public_url)


def oauth() -> OAuthProvider | None:
    if os.getenv("MCP_OAUTH_ENABLED") != "1":
        return None
    try:
        provider = oauth_provider(public_mcp_url())
        if provider is None:
            raise ValueError("Set MCP_PUBLIC_URL when enabling MCP OAuth.")
        return provider
    except (ValueError, ValidationError) as exc:
        logging.getLogger(__name__).warning("MCP OAuth disabled due to invalid configuration: %s", exc)
        return None


def _save_pending(params: AuthorizationParams, request_id: str) -> None:
    now = int(time.time())
    over_limit = False
    with store.transaction() as conn:
        conn.execute("DELETE FROM mcp_oauth_pending WHERE expires_at<=?", (now,))
        count = conn.execute("SELECT count(*) FROM mcp_oauth_pending").fetchone()[0]
        if count >= MAX_PENDING:
            conn.execute(
                "DELETE FROM mcp_oauth_pending WHERE rowid IN ("
                "SELECT rowid FROM mcp_oauth_pending WHERE code_hash IS NULL ORDER BY expires_at ASC, rowid ASC LIMIT ?)",
                (count - MAX_PENDING + 1,),
            )
            if conn.execute("SELECT count(*) FROM mcp_oauth_pending").fetchone()[0] >= MAX_PENDING:
                over_limit = True
        if not over_limit:
            conn.execute("INSERT INTO mcp_oauth_pending (request_hash,params,expires_at) VALUES (?,?,?)",
                         (token_hash(request_id), params.model_dump_json(), now + PENDING_TTL))
    if over_limit:
        raise AuthorizeError("temporarily_unavailable", "Too many pending authorization requests. Try again shortly.")


class OAuthProvider:
    def __init__(self, resource: str):
        self.resource = resource
        self.issuer = resource.removesuffix("/mcp")
        issuer = urlsplit(self.issuer)
        self.origin = f"{issuer.scheme}://{issuer.netloc}"
        self.metadata = str(build_resource_metadata_url(AnyHttpUrl(resource)))
        # Pin the supported ChatGPT CIMD document's identity, redirect and public-client method.
        # This keeps authorization independent of arbitrary client URLs or outbound metadata requests.
        self.client = OAuthClientInformationFull(
            client_id=CLIENT_ID, redirect_uris=[CALLBACK], client_name="ChatGPT",
            token_endpoint_auth_method="none", grant_types=["authorization_code", "refresh_token"],
            response_types=["code"], scope=SCOPE,
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.client if client_id == CLIENT_ID else None

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource != self.resource:
            raise AuthorizeError("invalid_target", "Use the Agent Dairy MCP URL as the OAuth resource.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "Use an S256 PKCE code challenge.")
        if params.state and len(params.state) > 1024:
            raise AuthorizeError("invalid_request", "OAuth state is too long.")
        request_id = secrets.token_urlsafe(32)
        await anyio.to_thread.run_sync(_save_pending, params, request_id)
        return f"{self.issuer}/oauth/connect?{urlencode({'request_id': request_id})}"

    def pending(self, request_id: str) -> bool:
        return store.fetchone(
            "SELECT 1 FROM mcp_oauth_pending WHERE request_hash=? AND code_hash IS NULL AND expires_at>?",
            (token_hash(request_id), int(time.time()))) is not None

    def finish(self, request_id: str, account, approved: bool) -> str:
        now = int(time.time())
        code = secrets.token_urlsafe(32)
        with store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_oauth_pending WHERE request_hash=? AND expires_at>? AND code_hash IS NULL",
                (token_hash(request_id), now)).fetchone()
            if row is None:
                raise HTTPException(400, "This connection request expired. Start again in ChatGPT.")
            params = AuthorizationParams.model_validate_json(row["params"])
            if approved:
                current = conn.execute("SELECT password_hash FROM portal_accounts WHERE username=? AND role='client'",
                                       (account["username"],)).fetchone()
                if current is None or current["password_hash"] != account["password_hash"]:
                    raise HTTPException(401, "Invalid username or password.")
                conn.execute("UPDATE mcp_oauth_pending SET code_hash=?, username=?, expires_at=? WHERE request_hash=?",
                             (token_hash(code), account["username"], now + CODE_TTL, row["request_hash"]))
            else:
                conn.execute("DELETE FROM mcp_oauth_pending WHERE request_hash=?", (row["request_hash"],))
        return construct_redirect_uri(CALLBACK, iss=self.issuer, state=params.state,
                                      code=code if approved else None, error=None if approved else "access_denied")

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        return await anyio.to_thread.run_sync(self._load_code, authorization_code)

    def _load_code(self, code: str) -> AuthorizationCode | None:
        if len(code) != 43:
            return None
        row = store.fetchone("SELECT * FROM mcp_oauth_pending WHERE code_hash=? AND expires_at>?",
                             (token_hash(code), int(time.time())))
        if row is None:
            return None
        params = AuthorizationParams.model_validate_json(row["params"])
        if params.resource != self.resource:
            return None
        return AuthorizationCode(code=code, client_id=CLIENT_ID, scopes=[SCOPE], expires_at=row["expires_at"],
                                 subject=row["username"], code_challenge=params.code_challenge, resource=params.resource,
                                 redirect_uri=params.redirect_uri,
                                 redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode):
        return await anyio.to_thread.run_sync(self._exchange_code, authorization_code)

    def _exchange_code(self, code: AuthorizationCode) -> OAuthToken:
        now = int(time.time())
        with store.transaction() as conn:
            if not conn.execute("DELETE FROM mcp_oauth_pending WHERE code_hash=? AND expires_at>?",
                                (token_hash(code.code), now)).rowcount:
                raise TokenError("invalid_grant")
            conn.execute("DELETE FROM mcp_oauth_grants WHERE refresh_expires<=?", (now,))
            count = conn.execute("SELECT count(*) FROM mcp_oauth_grants WHERE username=?",
                                 (code.subject,)).fetchone()[0]
            if count >= 20:
                raise TokenError("invalid_grant", "Disconnect an existing ChatGPT connection in Agent Dairy Settings.")
            access, refresh = self._new_tokens()
            conn.execute(
                "INSERT INTO mcp_oauth_grants VALUES (?,?,?,?,?,?,?,?,NULL)",
                ("oauth_" + secrets.token_hex(12), code.subject, self.resource, token_hash(access), token_hash(refresh),
                 now + ACCESS_TTL, now + REFRESH_TTL, store.now().isoformat()))
        return self._token_response(access, refresh)

    @staticmethod
    def _new_tokens() -> tuple[str, str]:
        return ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)

    @staticmethod
    def _token_response(access: str, refresh: str) -> OAuthToken:
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=ACCESS_TTL, scope=SCOPE)

    def _grant(self, token: str, *, refresh: bool = False):
        if len(token) != 43 + len(REFRESH_PREFIX if refresh else ACCESS_PREFIX):
            return None
        key = "refresh" if refresh else "access"
        now = int(time.time())
        return store.fetchone(
            "SELECT g.*, a.buyer_id FROM mcp_oauth_grants g JOIN portal_accounts a USING(username) "
            f"WHERE g.{key}_hash=? AND g.{key}_expires>? AND g.refresh_expires>? AND g.resource=? AND a.role='client'",
            (token_hash(token), now, now, self.resource))

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        row = await anyio.to_thread.run_sync(lambda: self._grant(refresh_token, refresh=True))
        if row is None:
            return None
        return RefreshToken(token=refresh_token, client_id=CLIENT_ID, scopes=[SCOPE], expires_at=row["refresh_expires"],
                            resource=self.resource, subject=row["username"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]):
        return await anyio.to_thread.run_sync(self._exchange_refresh, refresh_token)

    def _exchange_refresh(self, token: RefreshToken) -> OAuthToken:
        now = int(time.time())
        access, refresh = self._new_tokens()
        with store.transaction() as conn:
            changed = conn.execute(
                "UPDATE mcp_oauth_grants SET access_hash=?,refresh_hash=?,access_expires=?,refresh_expires=? "
                "WHERE refresh_hash=? AND resource=? AND refresh_expires>?",
                (token_hash(access), token_hash(refresh), now + ACCESS_TTL, now + REFRESH_TTL,
                 token_hash(token.token), self.resource, now))
            if not changed.rowcount:
                raise TokenError("invalid_grant")
        return self._token_response(access, refresh)

    def access_grant(self, token: str):
        return self._grant(token) if token.startswith(ACCESS_PREFIX) else None
