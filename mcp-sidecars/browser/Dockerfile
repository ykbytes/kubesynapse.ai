# syntax=docker/dockerfile:1.7
# mcp-browser — browser automation with Playwright + Chromium.
# Browser automation is hard to run on Alpine/musl, so this image layers on
# the Debian-based mcp-base-debian image.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base-debian:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Browser"
LABEL org.opencontainers.image.description="Browser automation sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

ENV MCP_SERVER_TYPE=browser \
    MCP_LISTEN_PORT=8083 \
    MCP_HEALTH_PORT=8183 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

USER root
# Runtime libraries required by Chromium.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
       libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app
COPY --chown=mcpuser:mcpuser browser/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser browser/requirements.lock /app/requirements.lock
# Install the pinned browser stack (playwright) then download Chromium.
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock \
    && /opt/venv/bin/playwright install chromium --with-deps \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --chown=mcpuser:mcpuser browser/server.py /app/server.py
COPY --chown=mcpuser:mcpuser browser/capabilities.json /app/capabilities.json

USER mcpuser
EXPOSE 8083 8183
CMD ["python", "/app/server.py"]
