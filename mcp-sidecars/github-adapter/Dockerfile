# syntax=docker/dockerfile:1.7
# mcp-github-adapter — GitHub MCP adapter using the official MCP SDK + FastAPI.
FROM python:3.12-alpine AS builder

WORKDIR /app
COPY github-adapter/requirements.lock /app/requirements.lock
RUN apk add --no-cache gcc musl-dev linux-headers libffi-dev openssl-dev \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock \
    && find /opt/venv -type d \( -name tests -o -name test -o -name testing -o -name docs -o -name examples \) -prune -exec rm -rf {} + 2>/dev/null || true \
    && rm -rf /tmp/* /var/cache/apk/*

FROM python:3.12-alpine
LABEL org.opencontainers.image.title="KubeSynapse MCP GitHub Adapter"
LABEL org.opencontainers.image.description="GitHub MCP adapter sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_LISTEN_ADDR=0.0.0.0:8096 \
    PATH=/opt/venv/bin:$PATH

RUN apk add --no-cache libffi openssl \
    && addgroup -g 1000 -S mcpuser \
    && adduser -u 1000 -S mcpuser -G mcpuser \
    && mkdir -p /app && chown -R mcpuser:mcpuser /app \
    && rm -rf /var/cache/apk/* /tmp/*

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=mcpuser:mcpuser github-adapter/server.py /app/server.py
COPY --chown=mcpuser:mcpuser github-adapter/capabilities.json /app/capabilities.json

USER mcpuser
EXPOSE 8096
CMD ["python", "/app/server.py"]
