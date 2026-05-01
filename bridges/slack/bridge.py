from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
app = FastAPI(title="ClosedClaw Slack Bridge")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request) -> dict:
    payload = await request.json()
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    event = payload.get("event", {})
    text = event.get("text")
    if not text or event.get("bot_id"):
        return {"ok": True}
    async with httpx.AsyncClient(timeout=120) as client:
        result = await client.post(
            f"{AGENT_URL}/chat",
            json={
                "message": text,
                "channel": "slack",
                "user_id": event.get("user", "slack-user"),
                "thread_id": event.get("thread_ts") or event.get("ts"),
                "group_id": event.get("channel"),
                "metadata": event,
            },
        )
    return {"ok": True, "agent": result.json()}
