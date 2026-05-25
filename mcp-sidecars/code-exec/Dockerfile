# ── Stage 1: Extract node binary from slim node image ──
FROM node:22-slim AS node-bin

# ── Stage 2: Python runtime with extracted node ──
FROM python:3.12-slim

# Copy node and npm binaries from node image (~200MB saved vs apt install)
COPY --from=node-bin /usr/local/bin/node /usr/local/bin/node
COPY --from=node-bin /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-bin /opt/ /opt/

# Install only bash (node already copied)
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && ln -s /usr/local/bin/node /usr/local/bin/nodejs 2>/dev/null || true \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY code-exec/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY code-exec/server.py /app/server.py
COPY code-exec/capabilities.json /app/capabilities.json
ENV MCP_LISTEN_PORT=8082
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8082
CMD ["python", "/app/server.py"]
