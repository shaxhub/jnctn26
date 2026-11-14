"""Password-based portal accounts and revocable, role-scoped sessions."""
import hashlib
import hmac
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import store
from .config import demo_catalog_enabled

COOKIES = {"client": "ad_client_session", "admin": "ad_admin_session"}
SESSION_SECONDS = 8 * 3600
_SCRYPT_LIMIT = threading.BoundedSemaphore(4)


def hosted() -> bool:
    return os.getenv("REQUIRE_PORTAL_LOGIN") == "1"


def password_hash(password: str, salt: bytes) -> bytes:
    with _SCRYPT_LIMIT:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64*1024*1024)


def provision(username: str, role: str, buyer: str | None, password: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,47}", username):
        raise ValueError("Use 3–48 lowercase letters, numbers, dots, hyphens or underscores.")
    if role == "client":
        from .policy import load_mandate
        if buyer not in {"hotel", "hospital"}:
            raise ValueError("Select the hotel or hospital buyer.")
        load_mandate(buyer)
    elif role != "admin" or buyer is not None:
        raise ValueError("Admin accounts do not have a buyer.")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must be 12–128 characters.")
    salt = secrets.token_bytes(16)
    digest = password_hash(password, salt)
    with store.transaction() as conn:
        conn.execute("INSERT INTO portal_accounts VALUES (?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET "
                     "salt=excluded.salt,password_hash=excluded.password_hash "
                     "WHERE role=excluded.role AND buyer_id IS excluded.buyer_id", (username, role, buyer, salt, digest))
        row = conn.execute("SELECT role,buyer_id FROM portal_accounts WHERE username=?", (username,)).fetchone()
        if (row["role"], row["buyer_id"]) != (role, buyer):
            raise ValueError("That username belongs to a different portal or buyer.")
        conn.execute("DELETE FROM portal_sessions WHERE username=?", (username,))
        conn.execute("DELETE FROM mcp_oauth_grants WHERE username=?", (username,))
        conn.execute("DELETE FROM mcp_oauth_pending WHERE username=?", (username,))
        conn.execute("DELETE FROM portal_login_attempts WHERE username=?", (username,))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(body: "Login", request: Request, role: str, *, origin: str | None = None):
    same_origin(request, origin)
    username = body.username.strip().lower()
    source = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    since = (now - timedelta(minutes=5)).isoformat()
    with store.transaction() as conn:
        conn.execute("DELETE FROM portal_login_attempts WHERE julianday(at)<julianday(?)", (since,))
        user_attempts = conn.execute(
            "SELECT count(*) FROM portal_login_attempts WHERE source=? AND role=? AND username=?",
            (source, role, username),
        ).fetchone()[0]
        source_attempts = conn.execute(
            "SELECT count(*) FROM portal_login_attempts WHERE source=? AND role=?",
            (source, role),
        ).fetchone()[0]
        if user_attempts >= 12 or source_attempts >= 60:
            raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
        attempt = conn.execute(
            "INSERT INTO portal_login_attempts (source,role,username,at) VALUES (?,?,?,?)",
            (source, role, username, now.isoformat()),
        ).lastrowid
    row = store.fetchone("SELECT * FROM portal_accounts WHERE username=? AND role=?", (username, role))
    digest = password_hash(body.password, row["salt"] if row else bytes(16))
    if row is None or not hmac.compare_digest(digest, row["password_hash"]):
        raise HTTPException(401, "Invalid username or password.")
    with store.transaction() as conn:
        conn.execute("DELETE FROM portal_login_attempts WHERE rowid=?", (attempt,))
    return row


def same_origin(request: Request, origin: str | None = None) -> None:
    # Comparing Origin prevents cookie-authenticated writes from a sibling port.
    url = request.url
    if request.headers.get("origin") != (origin or f"{url.scheme}://{url.netloc}"):
        raise HTTPException(403, "Use the portal to make this request.")


def identity(request: Request, role: str):
    token = request.cookies.get(COOKIES[role])
    if not token or len(token) > 100:
        return None
    row = store.fetchone(
        "SELECT a.username,a.buyer_id FROM portal_sessions s JOIN portal_accounts a USING(username) "
        "WHERE s.token_hash=? AND a.role=? AND julianday(s.expires_at)>julianday(?)",
        (token_hash(token), role, datetime.now(timezone.utc).isoformat()))
    if row and request.method not in {"GET", "HEAD", "OPTIONS"}:
        same_origin(request)
    return row


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=48)
    password: str = Field(min_length=1, max_length=128)


def router(role: str) -> APIRouter:
    routes = APIRouter(prefix="/session")
    cookie = COOKIES[role]

    @routes.get("")
    def status(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        user = identity(request, role)
        return {"required": hosted(), "username": user["username"] if user else None,
                "buyer_id": user["buyer_id"] if user else None, "offline_demo": demo_catalog_enabled(),
                "now": store.now().isoformat()}

    @routes.post("/login")
    def login(body: Login, request: Request, response: Response):
        row = authenticate(body, request, role)
        username = row["username"]
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(32)
        with store.transaction() as conn:
            current = conn.execute("SELECT password_hash FROM portal_accounts WHERE username=?", (username,)).fetchone()
            if current is None or current["password_hash"] != row["password_hash"]:
                raise HTTPException(401, "Invalid username or password.")
            conn.execute("DELETE FROM portal_sessions WHERE julianday(expires_at)<=julianday(?)", (now.isoformat(),))
            conn.execute("INSERT INTO portal_sessions VALUES (?,?,?)",
                         (token_hash(token), username, (now+timedelta(seconds=SESSION_SECONDS)).isoformat()))
        response.headers["Cache-Control"] = "no-store"
        response.set_cookie(cookie, token, max_age=SESSION_SECONDS, httponly=True,
                            path=request.scope.get("root_path") or "/",
                            secure=request.url.scheme == "https", samesite="strict")
        return {"username": username, "buyer_id": row["buyer_id"]}

    @routes.post("/logout")
    def logout(request: Request, response: Response):
        same_origin(request)
        token = request.cookies.get(cookie)
        if token and len(token) <= 100:
            store.execute("DELETE FROM portal_sessions WHERE token_hash=?", (token_hash(token),))
        response.delete_cookie(cookie, httponly=True, secure=request.url.scheme == "https", samesite="strict",
                               path=request.scope.get("root_path") or "/")
        return {"ok": True}

    return routes
