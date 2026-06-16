# syntax=docker/dockerfile:1.7
# mcp-messaging — Slack messaging integration.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Messaging"
LABEL org.opencontainers.image.description="Messaging sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser messaging/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser messaging/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser messaging/server.py /app/server.py
COPY --chown=mcpuser:mcpuser messaging/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=messaging \
    MCP_LISTEN_PORT=8087 \
    MCP_HEALTH_PORT=8187

USER mcpuser
EXPOSE 8087 8187
CMD ["python", "/app/server.py"]
