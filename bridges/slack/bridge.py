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
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
app = FastAPI(title="ClosedClaw Slack Bridge")
policy = ChannelPolicy()
pairing = PairingStore(ttl_seconds=PAIRING_TTL)


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
    sender_id = event.get("user", "slack-user")
    channel_id = event.get("channel")
    if not policy.is_allowed("slack", sender_id):
        if text.strip().isdigit() and len(text.strip()) == 6:
            ok, reason = pairing.verify_code("slack", sender_id, text.strip())
            if ok:
                policy.add_sender("slack", sender_id)
                await _send_slack_message(channel_id, "Pairing complete. You can now message the agent.")
                return {"ok": True, "paired": True}
            await _send_slack_message(channel_id, f"Pairing failed: {reason}")
            return {"ok": True, "paired": False, "reason": reason}
        code = pairing.create_code("slack", sender_id)
        await _send_slack_message(channel_id, f"Pairing required. Reply with this code within 10 minutes: {code}")
        return {"ok": True, "pairing_required": True}
    async with httpx.AsyncClient(timeout=120) as client:
        result = await client.post(
            f"{AGENT_URL}/chat",
            headers=_agent_headers(),
            json={
                "message": text,
                "channel": "slack",
                "user_id": sender_id,
                "thread_id": event.get("thread_ts") or event.get("ts"),
                "group_id": channel_id,
                "metadata": event,
            },
        )
    return {"ok": True, "agent": result.json()}


def _agent_headers() -> dict[str, str]:
    """Builds auth headers for forwarding bridge messages to the agent API."""

    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


async def _send_slack_message(channel_id: str | None, text: str) -> None:
    """Sends a Slack pairing message when a bot token is configured."""

    if not SLACK_BOT_TOKEN or not channel_id:
        print(text)
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"channel": channel_id, "text": text},
        )
