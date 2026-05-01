# ClosedClaw Personal Agent

ClosedClaw is a local-first scaffold for a personal coding and productivity agent. It exposes one agent API that can be reached from the web UI, Slack, Telegram, or WhatsApp, and delegates work to email, calendar, browser automation, memory, and specialist sub-agent modules.

## What is implemented

- Email: list and summarize Gmail messages, create drafts, send email, trash messages, and clear spam once Google OAuth is configured.
- Calendar: list events, create/reschedule events, and find free slots through Google Calendar.
- Browser automation: controlled Chromium sandbox with Playwright for navigation, form steps, extraction, and screenshots.
- Memory/CRM: SQLite memory store plus JSON contact store.
- Multi-channel: Streamlit UI plus Slack, Telegram, and WhatsApp bridge entry points.
- Approvals: risky tasks create pending approvals instead of immediately sending, deleting, or booking.
- Audit: channel messages and approval decisions are written to JSONL logs.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Open:

- UI: http://localhost:8501
- Agent API: http://localhost:8000/health

## Google setup

Create a Google OAuth desktop/web client with Gmail and Calendar APIs enabled, then place the client secret at:

```text
secrets/google_client_secret.json
```

Set `TOKEN_ENCRYPTION_KEY` in `.env` to a Fernet key. You can generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The token helper in `agent/auth/oauth.py` can run a local OAuth flow and store encrypted tokens as `gmail_token.enc` and `calendar_token.enc`.

## API examples

```bash
curl -X POST http://localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"summarize my inbox","channel":"ui","user_id":"me"}'
```

```bash
curl -X POST http://localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"browse https://example.com and summarize it","channel":"ui","user_id":"me"}'
```
