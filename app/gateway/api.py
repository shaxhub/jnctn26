"""FastAPI app: REST API, static UI at /, MCP (Streamable HTTP) at /mcp.

    uv run uvicorn gateway.api:app --reload --port 8000
    open http://localhost:8000        (UI)      http://localhost:8000/docs   (OpenAPI)
"""
from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

import anyio
import httpx
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from mcp.server.transport_security import TransportSecuritySettings

from . import quotes, service, store
from .agent import compact_offers, run_agent
from .auth import McpAuthMiddleware, Principal, require_agent, require_approver, require_principal
from .config import APP_DIR, TZ, settings
from .mcp_server import mcp
from .models import (AgentRunRequest, ApprovalDecisionRequest, Need, OffersRequest, OrderRequest, QuoteRequest,
                     SearchRequest)

# stateless + JSON responses: every MCP request is independent, which suits a horizontally scaled gateway.
# DNS-rebinding protection is off so the app works behind any host name.
# TODO(C): set allowed_hosts/allowed_origins for the deployed host name.
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():   # the MCP session manager must run inside the app's lifespan
        yield


app = FastAPI(title="Valio Aimo Trade Gateway (Junction 2026 demo)", version="0.1.0", lifespan=lifespan,
              description="Search, offers, signed quotes, mandate-governed orders, human approvals and a "
                          "hash-chained audit log. Auth: X-API-Key (demo keys in buyers.json).")
app.router.routes.extend(mcp_app.routes)    # serves POST/GET /mcp from the same process and port
app.add_middleware(McpAuthMiddleware)


@app.exception_handler(service.GatewayError)
async def _gateway_error(_, exc: service.GatewayError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.exception_handler(httpx.HTTPError)
async def _upstream_error(_, exc: httpx.HTTPError):
    return JSONResponse(status_code=502, content={"detail": f"Upstream Valio API error: {exc}"})


@app.exception_handler(RuntimeError)
async def _runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


async def _thread(fn, *args):
    """Run blocking core code (httpx + sqlite) off the event loop."""
    return await anyio.to_thread.run_sync(lambda: fn(*args))


# --- UI and meta ------------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(APP_DIR / "ui" / "index.html")


@app.get("/health")
def health():
    return {
        "ok": True,
        "catalog": settings.catalog_db_path.exists(),
        "llm_agent": bool(settings.anthropic_api_key),
        "valio_api_key": bool(settings.valio_api_key),
        "demo_now": store.now().isoformat(),
    }


@app.get("/.well-known/jwks.json")
def jwks():
    """Public key(s) to verify quote signatures (JWS, EdDSA/Ed25519)."""
    return quotes.jwks()


@app.get("/me")
def me(p: Principal = Depends(require_principal)):
    """Who the API key belongs to, and the mandate the gateway enforces for it."""
    return {"buyer_id": p.buyer_id, "role": p.role, "name": p.name, "mandate": p.mandate.model_dump(mode="json"),
            "weekly_spent": service.weekly_spent(p.buyer_id)}


# --- buyer agent endpoints --------------------------------------------------------------------
@app.post("/search")
async def search(req: SearchRequest, p: Principal = Depends(require_principal)):
    return (await _thread(service.search_products, p, req)).model_dump(mode="json")


@app.post("/offers")
async def offers(req: OffersRequest, p: Principal = Depends(require_principal)):
    return compact_offers(await _thread(service.check_offers, p, req))


@app.post("/plan")
async def plan(need: Need, p: Principal = Depends(require_principal)):
    """Convenience: search with the need's filters, fetch offers and return ranked plans (no quote)."""
    def run():
        found = service.search_products(p, SearchRequest(text=need.search_text, free_from=need.free_from,
                                                         exclude_allergens=need.exclude_allergens, category=need.category,
                                                         exclude_terms=need.exclude_terms, limit=40))
        ids = need.preferred_product_ids + [r.id for r in found.results if r.id not in need.preferred_product_ids]
        res, _ = service.plan_need(p, need, ids)
        return res.model_dump(mode="json")
    return await _thread(run)


@app.post("/quotes")
async def create_quote(req: QuoteRequest, p: Principal = Depends(require_agent)):
    return (await _thread(service.create_quote, p, req)).model_dump(mode="json")


@app.post("/orders")
async def place_order(req: OrderRequest, p: Principal = Depends(require_agent)):
    return (await _thread(service.place_order, p, req.quote_id, req.agent_rationale)).model_dump(mode="json")


@app.get("/orders")
def list_orders(p: Principal = Depends(require_principal)):
    return [o.model_dump(mode="json") for o in service.list_orders(p)]


@app.get("/orders/{order_id}")
def get_order(order_id: str, p: Principal = Depends(require_principal)):
    return service.get_order(p, order_id).model_dump(mode="json")


# --- human approvals --------------------------------------------------------------------------
@app.get("/approvals")
def approvals(status: str | None = "pending", p: Principal = Depends(require_principal)):
    return service.list_approvals(p, status or None)


@app.post("/approvals/{approval_id}")
def decide(approval_id: str, req: ApprovalDecisionRequest, p: Principal = Depends(require_principal)):
    require_approver(p)
    return service.decide_approval(p, approval_id, req.decision, req.comment).model_dump(mode="json")


# --- audit ------------------------------------------------------------------------------------
@app.get("/audit")
def audit_log(order_id: str, p: Principal = Depends(require_principal)):
    return service.get_audit_log(p, order_id)


# --- agent ------------------------------------------------------------------------------------
@app.post("/agent/run")
async def agent_run(req: AgentRunRequest, p: Principal = Depends(require_principal)):
    """Run the buyer agent on free text. mode=auto uses the LLM if ANTHROPIC_API_KEY is set, else scripted."""
    if p.role != "agent":
        raise HTTPException(403, "Use an agent key to run the agent")
    if req.mode == "llm" and not settings.anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY is not set; use mode=scripted")
    return await _thread(run_agent, p, req.text, req.mode)


@app.get("/demo/next-monday", include_in_schema=False)
def next_monday():
    from .agent import next_weekday
    cur = store.now().date()
    return {"date": next_weekday(0, cur).isoformat(), "today": cur.isoformat()}


@app.post("/demo/reset", include_in_schema=False)
def demo_reset(payload: dict[str, Any] | None = Body(default=None)):
    store.reset_db()
    if payload is not None and "demo_now" in payload:
        raw = payload["demo_now"]
        if raw is None or raw == "":
            store.set_demo_now(None)
        else:
            try:
                dt = datetime.fromisoformat(str(raw))
            except ValueError as exc:
                raise HTTPException(422, f"Invalid demo_now ISO timestamp: {raw}") from exc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            store.set_demo_now(dt)
    return {"ok": True, "now": store.now().isoformat()}
