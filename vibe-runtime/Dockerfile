FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates build-essential \
    && python -m venv /opt/venv \
    && python -m venv /opt/vibe-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/vibe-venv/bin/pip install --no-cache-dir mistral-vibe

COPY main.py ./main.py
COPY runtime_events.py ./runtime_events.py

RUN useradd --uid 1000 --create-home vibeuser \
    && mkdir -p /app/state/home/.vibe /workspace \
    && chown -R vibeuser:vibeuser /app /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    VIBE_BIN=/opt/vibe-venv/bin/vibe \
    VIBE_HOME=/app/state/home/.vibe \
    HOME=/app/state/home \
    VIBE_WORKDIR=/workspace \
    VIBE_ACTIVE_MODEL=devstral-small

USER vibeuser

EXPOSE 8080

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
