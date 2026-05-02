# ClosedClaw Personal Agent

ClosedClaw is a local-first scaffold for a personal coding and productivity agent. It exposes one agent API that can be reached from the web UI, Slack, Telegram, or WhatsApp, and delegates work to email, calendar, browser automation, memory, and specialist sub-agent modules.

## What is implemented

- Email: list and summarize Gmail messages, create drafts, send email, trash messages, and clear spam once Google OAuth is configured.
- Calendar: list events, create/reschedule events, and find free slots through Google Calendar.
- Browser automation: controlled Chromium sandbox with Playwright for navigation, form steps, extraction, and screenshots.
- Memory/CRM: PostgreSQL-backed memory and contact store.
- Multi-channel: Streamlit UI plus Slack, Telegram, and WhatsApp bridge entry points.
- Approvals: risky tasks create PostgreSQL-backed approvals and execute through Celery workers after approval.
- Audit: channel messages and approval decisions are written to JSONL logs.
- LLM routing: choose deterministic routing, bring your own OpenAI-compatible API key, or local Ollama.

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
  -H "authorization: Bearer $AGENT_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"message":"summarize my inbox","channel":"ui","user_id":"me"}'
```

```bash
curl -X POST http://localhost:8000/chat \
  -H "authorization: Bearer $AGENT_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"message":"browse https://example.com and summarize it","channel":"ui","user_id":"me"}'
```

## LLM options

The agent supports three routing modes.

Deterministic fallback:

```bash
LLM_PROVIDER=none
```

Bring your own OpenAI-compatible API key:

```bash
LLM_PROVIDER=api
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=your_api_key
LLM_API_BASE_URL=https://api.openai.com/v1
```

You can also point `LLM_API_BASE_URL` at any service that implements `/chat/completions`.

Local Ollama:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Before starting Docker, run on the host:

```bash
ollama pull llama3.1
ollama serve
```

The LLM only chooses the intent and handles general conversation. Email, calendar, browser, memory, and approval behavior still runs through the local tool layer.

## Security Architecture

ClosedClaw now puts six safety layers in front of sensitive tools.

1. Authenticated API

Every agent route requires an API key through either:

```text
Authorization: Bearer <key>
```

or:

```text
X-API-Key: <key>
```

Set one of these in `.env`:

```bash
AGENT_API_KEY=long_random_secret
AGENT_API_KEYS=long_random_secret,another_key
```

The UI and bridges forward the key automatically when the same environment variables are present.

2. Per-channel allowlist and pairing

Allowed Slack, Telegram, and WhatsApp senders live in the PostgreSQL `channel_policy` table. Unknown senders are not forwarded to the agent. Instead, bridges create a six-digit pairing code in the PostgreSQL `pairing_requests` table.

The sender must reply with the code before `PAIRING_CODE_TTL_SECONDS` expires. After five incorrect attempts, the pairing request is deleted and the sender must request a new code.

3. Persistent approval ledger

Sensitive action plans are stored in PostgreSQL in the `approval_ledger` table.

The `approval_ledger` table records action id, type, JSONB payload, requester, timestamps, status, approver, and execution result. `/approvals` reads from this ledger instead of process memory. Approving an action queues a Celery task; the worker executes the stored typed action and writes the result back to the row.

4. Typed action plans

The supervisor creates Pydantic action models before approval or execution:

- `SendEmailAction`
- `DeleteEmailAction`
- `ClearSpamAction`
- `CreateCalendarEventAction`
- `BrowserNavigateAction`

Each model validates fields such as recipient, URL, body length, event times, and message ids. Each action has `to_human_readable()` for UI approval text.

5. Scoped tool permissions

Tool functions are protected with runtime scopes:

```text
email:read
email:send
email:delete
calendar:read
calendar:write
browser:navigate
```

Autonomous actions receive only safe default scopes: email read, calendar read, and browser navigation. Elevated scopes such as sending or deleting email are only granted inside approved action execution.

6. Policy checks before execution

`agent/policy/policy_engine.py` checks every typed action before execution:

- blocks configured URL domains
- restricts outbound email recipient domains when `ALLOWED_EMAIL_DOMAINS` is set
- enforces payload and email body size limits
- rate-limits repeated action types using the approval ledger

If a policy rejects an action, a rejected ledger row is written with the reason.

7. Background execution and tracing

Approved browser, email, and calendar actions are executed by Celery workers over Redis instead of inside the HTTP request. FastAPI tracing is instrumented with OpenTelemetry, and an OTLP endpoint can be configured for Jaeger or another collector.

Useful policy settings:

```bash
ALLOWED_EMAIL_DOMAINS=example.com,yourcompany.com
BLOCKED_URL_DOMAINS=paypal.com,stripe.com,adult.example,phishing.example
MAX_EMAIL_BODY_CHARS=10000
MAX_ACTION_PAYLOAD_BYTES=20000
ACTION_RATE_LIMIT_PER_HOUR=10
PAIRING_CODE_TTL_SECONDS=600
```

## Running in Production

Use PostgreSQL for all durable state:

```bash
DATABASE_URL=postgresql://closedclaw:strong_password@postgres:5432/closedclaw
```

The Compose file includes a `postgres` service with a healthcheck. For a managed database, point `DATABASE_URL` to that database and remove the local `postgres` service.

Use Redis and Celery for action execution:

```bash
CELERY_BROKER_URL=redis://redis:6379/0
```

Run at least one worker:

```bash
celery -A worker.celery_app worker --loglevel=info
```

Use Jaeger or another OTLP collector for tracing:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

The local Compose file includes Jaeger at:

```text
http://localhost:16686
```

Before upgrading an existing SQLite deployment, run:

```bash
python scripts/migrate_sqlite_to_postgres.py
```

For production, set long random API keys, restrict `ALLOWED_EMAIL_DOMAINS`, keep bridge allowlists small, and expose only the UI or bridge endpoints you actually use.
