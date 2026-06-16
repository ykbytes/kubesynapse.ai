# syntax=docker/dockerfile:1.7
# mcp-documents — read PDF, Word, Excel, and generate PDFs.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Documents"
LABEL org.opencontainers.image.description="Document parsing and generation sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser documents/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser documents/requirements.lock /app/requirements.lock

# reportlab compiles extensions and needs freetype support for PDF rendering.
RUN apk add --no-cache gcc musl-dev linux-headers freetype-dev zlib-dev \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock \
    && apk del --purge gcc musl-dev linux-headers freetype-dev zlib-dev \
    && apk add --no-cache freetype zlib \
    && rm -rf /var/cache/apk/* /tmp/*

COPY --chown=mcpuser:mcpuser documents/server.py /app/server.py
COPY --chown=mcpuser:mcpuser documents/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=documents \
    MCP_LISTEN_PORT=8092 \
    MCP_HEALTH_PORT=8192

USER mcpuser
EXPOSE 8092 8192
CMD ["python", "/app/server.py"]
