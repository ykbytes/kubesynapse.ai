# ── Stage 1: Build dependencies ──
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates build-essential \
    && python -m venv /opt/venv \
    && python -m venv /opt/vibe-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/vibe-venv/bin/pip install --no-cache-dir \
        'mistralai @ https://files.pythonhosted.org/packages/0f/74/0f6188190e79eef4363754c71414c1a791537b1e506cbee615bb581cb05f/mistralai-2.4.4-py3-none-any.whl#sha256=43dd3b1f0f4f960a723359165c4da0d035590b27c050028322934fe4f189f14e' \
        mistral-vibe==2.9.5

# ── Stage 2: Minimal runtime ──
FROM python:3.12-slim

# Runtime deps only (no build-essential = ~300MB savings)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venvs from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/vibe-venv /opt/vibe-venv

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
