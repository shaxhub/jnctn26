"""Aimo operations HTTP app. Run separately from the client gateway."""
from datetime import datetime
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import store
from .auth import Admin, require_admin
from .config import APP_DIR, TZ
from .operations import router
from .web_common import configure_errors, mount_assets

app = FastAPI(title="Agent Dairy | Aimo operations")
configure_errors(app)
app.include_router(router)
mount_assets(app, {"admin.js", "common.js", "portal.css", "order_thread.js"})


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(APP_DIR / "ui" / "admin.html")


@app.post("/demo/reset", include_in_schema=False)
def demo_reset(payload: dict[str, Any] | None = Body(default=None), admin: Admin = Depends(require_admin)):
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
    store.reset_db()
    return {"ok": True, "now": store.now().isoformat()}
