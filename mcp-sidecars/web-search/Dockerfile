# syntax=docker/dockerfile:1.7
# mcp-web-search — web search, URL fetch, and text extraction.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Web Search"
LABEL org.opencontainers.image.description="Web search and content extraction sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser web-search/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser web-search/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser web-search/server.py /app/server.py
COPY --chown=mcpuser:mcpuser web-search/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=web-search \
    MCP_LISTEN_PORT=8081 \
    MCP_HEALTH_PORT=8181

USER mcpuser
EXPOSE 8081 8181
CMD ["python", "/app/server.py"]
