# syntax=docker/dockerfile:1.7
# mcp-rag — vector search with Qdrant and fastembed embeddings.
# fastembed pulls onnxruntime, which does not provide musllinux wheels, so
# this image layers on the Debian-based mcp-base-debian image.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base-debian:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP RAG"
LABEL org.opencontainers.image.description="RAG / vector search sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser rag/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser rag/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser rag/server.py /app/server.py
COPY --chown=mcpuser:mcpuser rag/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=rag \
    MCP_LISTEN_PORT=8088 \
    MCP_HEALTH_PORT=8188

USER mcpuser
EXPOSE 8088 8188
CMD ["python", "/app/server.py"]
