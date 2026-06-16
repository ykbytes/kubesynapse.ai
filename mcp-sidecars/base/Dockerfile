# syntax=docker/dockerfile:1.7
# mcp-base — shared runtime for all KubeSynapse MCP sidecars.
# Multi-stage Alpine build with a non-root user.  The final image contains
# only the compiled Python virtualenv and the shared mcp_base.py module.
FROM python:3.12-alpine AS builder

WORKDIR /app
COPY base/requirements-base.lock /app/requirements-base.lock

# Install build dependencies, create a venv, install the pinned stack, then
# strip the venv to runtime essentials.
RUN apk add --no-cache \
    gcc \
    musl-dev \
    linux-headers \
    libffi-dev \
    openssl-dev \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements-base.lock \
    && find /opt/venv -type d \( -name tests -o -name test -o -name testing \) -prune -exec rm -rf {} + 2>/dev/null || true \
    && find /opt/venv -type d \( -name docs -o -name doc -o -name examples \) -prune -exec rm -rf {} + 2>/dev/null || true \
    && rm -rf /tmp/* /var/cache/apk/*

FROM python:3.12-alpine

LABEL org.opencontainers.image.title="KubeSynapse MCP Base"
LABEL org.opencontainers.image.description="Common runtime for KubeSynapse MCP sidecars"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MCP_LISTEN_PORT=8080 \
    MCP_HEALTH_PORT=8090 \
    MCP_SERVER_TYPE=base \
    PATH=/opt/venv/bin:$PATH

# Runtime libraries required by compiled wheels (cryptography, cffi, etc.).
RUN apk add --no-cache libffi openssl \
    && addgroup -g 1000 -S mcpuser \
    && adduser -u 1000 -S mcpuser -G mcpuser \
    && mkdir -p /app && chown -R mcpuser:mcpuser /app \
    && rm -rf /var/cache/apk/* /tmp/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=mcpuser:mcpuser base/mcp_base.py /app/mcp_base.py

USER mcpuser
EXPOSE 8080 8090

CMD ["python", "-c", "print('mcp-base: no server module mounted')"]
