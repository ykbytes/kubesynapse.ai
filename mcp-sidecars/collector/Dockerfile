# syntax=docker/dockerfile:1.7
# mcp-collector — runtime event collector for KubeSynapse agents.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Collector"
LABEL org.opencontainers.image.description="Runtime event collector sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser collector/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser collector/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser collector/server.py /app/server.py
COPY --chown=mcpuser:mcpuser collector/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=collector \
    MCP_LISTEN_PORT=8100 \
    MCP_HEALTH_PORT=8200

USER mcpuser
EXPOSE 8100 8200
CMD ["python", "/app/server.py"]
