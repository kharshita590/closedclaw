from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_policy import ChannelPolicy, PairingStore  # noqa: E402

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()
PAIRING_TTL = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
app = FastAPI(title="ClosedClaw Telegram Bridge")
policy = ChannelPolicy()
pairing = PairingStore(ttl_seconds=PAIRING_TTL)


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
    sender_id = str(chat.get("id") or sender.get("id", "telegram-user"))
    if not policy.is_allowed("telegram", sender_id):
        if text.strip().isdigit() and len(text.strip()) == 6:
            ok, reason = pairing.verify_code("telegram", sender_id, text.strip())
            if ok:
                policy.add_sender("telegram", sender_id)
                await _send_telegram_message(sender_id, "Pairing complete. You can now message the agent.")
                return {"ok": True, "paired": True}
            await _send_telegram_message(sender_id, f"Pairing failed: {reason}")
            return {"ok": True, "paired": False, "reason": reason}
        code = pairing.create_code("telegram", sender_id)
        await _send_telegram_message(sender_id, f"Pairing required. Reply with this code within 10 minutes: {code}")
        return {"ok": True, "pairing_required": True}
    async with httpx.AsyncClient(timeout=120) as client:
        result = await client.post(
            f"{AGENT_URL}/chat",
            headers=_agent_headers(),
            json={
                "message": text,
                "channel": "telegram",
                "user_id": sender_id,
                "thread_id": str(chat.get("id", "")),
                "group_id": str(chat.get("id", "")) if chat.get("type") in {"group", "supergroup"} else None,
                "metadata": payload,
            },
        )
    return {"ok": True, "agent": result.json()}


def _agent_headers() -> dict[str, str]:
    """Builds auth headers for forwarding bridge messages to the agent API."""

    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


async def _send_telegram_message(chat_id: str, text: str) -> None:
    """Sends a Telegram pairing message when a bot token is configured."""

    if not TELEGRAM_BOT_TOKEN:
        print(text)
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
