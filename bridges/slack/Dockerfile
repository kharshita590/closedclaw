FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY bridges/slack/requirements.txt requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt
COPY bridges/channel_policy.py .
COPY bridges/slack/bridge.py .
COPY agent/db ./agent/db

EXPOSE 8080
CMD ["uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8080"]
