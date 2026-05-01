FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY telegram/requirements.txt requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt
COPY channel_policy.py .
COPY telegram/bridge.py .

EXPOSE 8080
CMD ["uvicorn", "bridge:app", "--host", "0.0.0.0", "--port", "8080"]
