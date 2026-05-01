from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
app = FastAPI(title="ClosedClaw Telegram Bridge")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat", {})
    sender = message.get("from", {})
    text = message.get("text")
    if not text:
        return {"ok": True}
    async with httpx.AsyncClient(timeout=120) as client:
        result = await client.post(
            f"{AGENT_URL}/chat",
            json={
                "message": text,
                "channel": "telegram",
                "user_id": str(sender.get("id", "telegram-user")),
                "thread_id": str(chat.get("id", "")),
                "group_id": str(chat.get("id", "")) if chat.get("type") in {"group", "supergroup"} else None,
                "metadata": payload,
            },
        )
    return {"ok": True, "agent": result.json()}
