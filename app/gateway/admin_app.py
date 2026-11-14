"""Legacy standalone Aimo operations app. New deployments use gateway.api:app."""
from fastapi import FastAPI, Request

from .accounts import router as session_router
from .operations import demo_router, router
from .web_common import configure_errors, mount_assets, portal_page

app = FastAPI(title="Agent Dairy | Aimo operations")
configure_errors(app)
app.include_router(session_router('admin'))
app.include_router(router)
app.include_router(demo_router)
mount_assets(app, {"theme.js", "admin.js", "common.js", "portal.css", "order_thread.js"})


@app.get("/", include_in_schema=False)
def home(request: Request):
    return portal_page(request, "admin.html")
