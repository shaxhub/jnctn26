"""Shared HTTP error mapping and explicit static asset routing."""
from html import escape

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import APP_DIR
from .service import GatewayError


def portal_page(request: Request, filename: str) -> HTMLResponse:
    base = escape(request.scope.get("root_path", "").rstrip("/") + "/", quote=True)
    page = (APP_DIR / "ui" / filename).read_text(encoding="utf-8")
    return HTMLResponse(page.replace('<base href="/">', f'<base href="{base}">', 1))


def configure_errors(app: FastAPI) -> None:
    @app.exception_handler(GatewayError)
    async def gateway_error(_, exc: GatewayError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(_, exc: httpx.HTTPError):
        return JSONResponse(status_code=502, content={"detail": "The upstream service is unavailable. Try again shortly."})

    @app.exception_handler(RuntimeError)
    async def runtime_error(_, exc: RuntimeError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})


def mount_assets(app: FastAPI, allowed: set[str]) -> None:
    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str):
        if name not in allowed:
            raise HTTPException(404)
        return FileResponse(APP_DIR / "ui" / name)
