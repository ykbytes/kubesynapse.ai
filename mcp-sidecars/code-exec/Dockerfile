# syntax=docker/dockerfile:1.7
# mcp-code-exec — execute Python, Bash, and Node.js snippets safely.
# Multi-stage build copies only the Node.js binary from the official Alpine
# image, avoiding the full ~200 MB node layer.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM node:20-alpine AS node-bin
RUN apk add --no-cache binutils && strip /usr/local/bin/node && rm -rf /var/cache/apk/*

FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Code Execution"
LABEL org.opencontainers.image.description="Sandboxed code execution sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
# bash is required for the run_bash tool; libstdc++/libgcc are required by
# the Node.js binary copied from the Alpine node stage.
RUN apk add --no-cache bash libstdc++ libgcc \
    && rm -rf /var/cache/apk/* /tmp/*
COPY --from=node-bin /usr/local/bin/node /usr/local/bin/node
RUN ln -sf /usr/local/bin/node /usr/local/bin/nodejs 2>/dev/null || true \
    && node --version >/dev/null 2>&1

WORKDIR /app
COPY --chown=mcpuser:mcpuser code-exec/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser code-exec/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser code-exec/server.py /app/server.py
COPY --chown=mcpuser:mcpuser code-exec/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=code-exec \
    MCP_LISTEN_PORT=8082 \
    MCP_HEALTH_PORT=8092 \
    TMPDIR=/tmp

USER mcpuser
EXPOSE 8082 8092
CMD ["python", "/app/server.py"]
