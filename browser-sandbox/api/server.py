from __future__ import annotations

from fastapi import FastAPI

from api.routes import router

app = FastAPI(title="ClosedClaw Browser Sandbox")
app.include_router(router)
