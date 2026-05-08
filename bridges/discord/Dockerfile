FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py /app/bridge.py
COPY ../channel_policy.py /app/channel_policy.py
COPY ../enabled_channels.py /app/enabled_channels.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "bridge"]

