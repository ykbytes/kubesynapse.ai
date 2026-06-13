# OpenCode Runtime for KubeSynapse
# Multi-stage: official opencode binary + Python wrapper
#
# To pin the upstream runtime or Python base image:
#   docker build --build-arg OPENCODE_IMAGE=ghcr.io/anomalyco/opencode@sha256:<digest> .
#   docker build --build-arg PYTHON_IMAGE=python:3.12-alpine .

# ── Stage 1: Extract opencode binary from official image ──
ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:latest
ARG PYTHON_IMAGE=python:3.12-alpine
FROM ${OPENCODE_IMAGE} AS opencode-bin

# ── Stage 2: Build Python dependencies ──
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 3: Minimal runtime ──
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}

# Copy opencode binary (both stages use musl/Alpine, binary compatible)
COPY --from=opencode-bin /usr/local/bin/opencode /usr/local/bin/opencode

# Runtime deps only (no build tools)
RUN apk add --no-cache git curl ca-certificates ripgrep libgcc libstdc++

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /root/.local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages/
# Copy console scripts (uvicorn, etc.) from builder
COPY --from=builder /root/.local/bin /usr/local/bin/

COPY main.py hitl.py config.py tracing.py utils.py prompts.py models.py session.py skills.py opencode_client.py analysis.py invoke.py supervisor.py workspace.py sanitize_secrets.py content_safety.py runtime_events.py worker.py runtime_permissions.py ./
COPY providers.py ./
COPY memory/ ./memory/

RUN adduser -D -u 1000 opencodeuser \
    && mkdir -p /app/state /workspace \
    && chown -R opencodeuser:opencodeuser /app /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:$PATH \
    HOME=/app/state/home \
    XDG_CONFIG_HOME=/app/state/home/.config \
    XDG_DATA_HOME=/app/state/home/.local/share \
    OPENCODE_CONFIG_DIR=/app/state/home/.config/opencode-profile \
    OPENCODE_BIN=/usr/local/bin/opencode \
    OPENCODE_WORKDIR=/workspace

USER opencodeuser

EXPOSE 8080 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os; port = 8081 if os.getenv('CREDENTIAL_PROXY_ENABLED', 'false').lower() in ('true', '1', 'yes') else 8080; import urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{port}/ready', timeout=3)"

ENTRYPOINT ["python", "main.py"]
