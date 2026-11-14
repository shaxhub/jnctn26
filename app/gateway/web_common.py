"""Shared HTTP error mapping and explicit static asset routing."""
import logging
from html import escape

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import APP_DIR
from .service import GatewayError

logger = logging.getLogger(__name__)


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

    @app.exception_handler(Exception)
    async def unhandled_error(_, exc: Exception):
        logger.exception("Unhandled server error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "An unexpected server error occurred."})


def mount_assets(app: FastAPI, allowed: set[str]) -> None:
    @app.get("/assets/{name}", include_in_schema=False)
    def asset(name: str):
        if name == "logo.svg":
            return FileResponse(APP_DIR.parent / "assets" / "logo.svg", media_type="image/svg+xml")
        if name not in allowed:
            raise HTTPException(404)
        return FileResponse(APP_DIR / "ui" / name)
