from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_policy import ChannelPolicy, PairingStore  # noqa: E402
from enabled_channels import channel_enabled  # noqa: E402

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()
PAIRING_TTL = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
SIGNAL_CLI_REST_URL = (os.getenv("SIGNAL_CLI_REST_URL") or "http://signal-cli-rest-api:8080").rstrip("/")
SIGNAL_SENDER_NUMBER = os.getenv("SIGNAL_SENDER_NUMBER", "")

app = FastAPI(title="ClosedClaw Signal Bridge")
policy = ChannelPolicy()
pairing = PairingStore(ttl_seconds=PAIRING_TTL)


def _agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


async def _send_signal(recipient: str, text: str) -> None:
    if not SIGNAL_SENDER_NUMBER:
        print(text)
        return
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{SIGNAL_CLI_REST_URL}/v2/send",
            json={"message": text, "number": SIGNAL_SENDER_NUMBER, "recipients": [recipient]},
        )


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "enabled": channel_enabled("signal")}


@app.post("/signal/incoming")
async def signal_incoming(request: Request) -> dict:
    """Webhook receiver for signal-cli-rest-api callbacks."""

    if not channel_enabled("signal"):
        return {"ok": True, "disabled": True}

    payload = await request.json()
    envelope = payload.get("envelope") or {}
    data_message = envelope.get("dataMessage") or {}
    text = data_message.get("message")
    sender_id = str(envelope.get("source") or "")
    if not text or not sender_id:
        return {"ok": True}

    if not policy.is_allowed("signal", sender_id):
        stripped = str(text).strip()
        if stripped.isdigit() and len(stripped) == 6:
            ok, reason = pairing.verify_code("signal", sender_id, stripped)
            if ok:
                policy.add_sender("signal", sender_id)
                await _send_signal(sender_id, "Pairing complete. You can now message the agent.")
                return {"ok": True, "paired": True}
            await _send_signal(sender_id, f"Pairing failed: {reason}")
            return {"ok": True, "paired": False}
        code = pairing.create_code("signal", sender_id)
        await _send_signal(sender_id, f"Pairing required. Reply with this code within 10 minutes: {code}")
        return {"ok": True, "pairing_required": True}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{AGENT_URL}/chat",
            headers=_agent_headers(),
            json={"message": text, "channel": "signal", "user_id": sender_id, "thread_id": sender_id, "metadata": payload},
        )
        resp.raise_for_status()
        result = resp.json()
    await _send_signal(sender_id, result.get("response") or "Done.")
    return {"ok": True}

