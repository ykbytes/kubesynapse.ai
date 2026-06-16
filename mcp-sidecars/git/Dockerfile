# syntax=docker/dockerfile:1.7
# mcp-git — Git operations and GitHub REST API access.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Git"
LABEL org.opencontainers.image.description="Git and GitHub API sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
RUN apk add --no-cache git openssh-client \
    && rm -rf /var/cache/apk/* /tmp/* \
    && git --version \
    && mkdir -p /home/mcpuser/.ssh \
    && chmod 700 /home/mcpuser/.ssh \
    && chown -R mcpuser:mcpuser /home/mcpuser/.ssh

WORKDIR /app
COPY --chown=mcpuser:mcpuser git/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser git/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser git/server.py /app/server.py
COPY --chown=mcpuser:mcpuser git/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=git \
    MCP_LISTEN_PORT=8085 \
    MCP_HEALTH_PORT=8095 \
    MCP_WORK_DIR=/tmp

USER mcpuser
EXPOSE 8085 8095
CMD ["python", "/app/server.py"]
