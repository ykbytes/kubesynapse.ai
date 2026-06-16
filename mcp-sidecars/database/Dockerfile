# syntax=docker/dockerfile:1.7
# mcp-database — read-only SQL database queries (PostgreSQL, MySQL, SQLite).
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Database"
LABEL org.opencontainers.image.description="Read-only SQL database sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
WORKDIR /app
COPY --chown=mcpuser:mcpuser database/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser database/requirements.lock /app/requirements.lock

# Install build deps, compile psycopg2-binary against system libpq, then drop
# the build toolchain and keep only the runtime libpq library.
RUN apk add --no-cache postgresql-dev gcc musl-dev linux-headers \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock \
    && apk del --purge postgresql-dev gcc musl-dev linux-headers \
    && apk add --no-cache libpq \
    && rm -rf /var/cache/apk/* /tmp/*

COPY --chown=mcpuser:mcpuser database/server.py /app/server.py
COPY --chown=mcpuser:mcpuser database/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=database \
    MCP_LISTEN_PORT=8084 \
    MCP_HEALTH_PORT=8094

USER mcpuser
EXPOSE 8084 8094
CMD ["python", "/app/server.py"]
