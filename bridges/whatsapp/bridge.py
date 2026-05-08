from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_policy import ChannelPolicy, PairingStore  # noqa: E402
from enabled_channels import channel_enabled  # noqa: E402

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()
PAIRING_TTL = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
WHATSAPP_SIDECAR_URL = (os.getenv("WHATSAPP_SIDECAR_URL") or "http://whatsapp-sidecar:8085").rstrip("/")

app = FastAPI(title="ClosedClaw WhatsApp Bridge")
policy = ChannelPolicy()
pairing = PairingStore(ttl_seconds=PAIRING_TTL)


class IncomingWhatsAppMessage(BaseModel):
    sender_id: str = Field(min_length=1, max_length=200)
    chat_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    metadata: dict = Field(default_factory=dict)


class SendWhatsAppMessage(BaseModel):
    chat_id: str
    text: str


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "enabled": channel_enabled("whatsapp")}


@app.post("/whatsapp/incoming")
async def whatsapp_incoming(payload: IncomingWhatsAppMessage) -> dict:
    """Receive inbound messages from the Node sidecar and apply pairing+allowlist."""

    if not channel_enabled("whatsapp"):
        return {"ok": True, "disabled": True}

    text = payload.text.strip()
    sender_id = payload.sender_id

    if not policy.is_allowed("whatsapp", sender_id):
        if text.isdigit() and len(text) == 6:
            ok, reason = pairing.verify_code("whatsapp", sender_id, text)
            if ok:
                policy.add_sender("whatsapp", sender_id)
                await _send(payload.chat_id, "Pairing complete. You can now message the agent.")
                return {"ok": True, "paired": True}
            await _send(payload.chat_id, f"Pairing failed: {reason}")
            return {"ok": True, "paired": False, "reason": reason}
        code = pairing.create_code("whatsapp", sender_id)
        await _send(payload.chat_id, f"Pairing required. Reply with this code within 10 minutes: {code}")
        return {"ok": True, "pairing_required": True}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{AGENT_URL}/chat",
            headers=_agent_headers(),
            json={
                "message": payload.text,
                "channel": "whatsapp",
                "user_id": sender_id,
                "thread_id": payload.chat_id,
                "group_id": payload.chat_id if payload.chat_id.endswith("@g.us") else None,
                "metadata": payload.metadata,
            },
        )
        resp.raise_for_status()
        result = resp.json()
    await _send(payload.chat_id, result.get("response") or "Done.")
    return {"ok": True, "agent": result}


def _agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


async def _send(chat_id: str, text: str) -> None:
    """Send a WhatsApp message via the local sidecar REST API."""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{WHATSAPP_SIDECAR_URL}/send", json=SendWhatsAppMessage(chat_id=chat_id, text=text).model_dump())
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"WhatsApp sidecar send failed: {resp.text}")

